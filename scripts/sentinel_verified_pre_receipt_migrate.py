#!/usr/bin/env python3
"""One-time receipt-schema migration for an independently verified legacy corpus.

This command exists only for the exact legacy state in which canonical corpus
publications predate authenticated publication receipts: the publication table
exists while both receipt-policy relations are absent.  It is intentionally not
part of routine GO preparation.

The operator attestation is consumed by the feed migration itself.  The runtime
migration holds the canonical corpus lock while measuring the legacy publication
frontier and installing the receipt policy/constraint trigger, so the policy
boundary cannot move underneath the migration.  Durable-backup write authority
is proven before any DDL.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Mapping, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_probe_contract as probe_contract  # noqa: E402
import sentinel_go_readonly_data_preflight as readonly_preflight  # noqa: E402
import sentinel_go_validate as go  # noqa: E402

MARKER = "SENTINEL_VERIFIED_PRE_RECEIPT_MIGRATION="

_MIGRATION_CODE = r'''
import hashlib
import json
import os

MARKER = 'SENTINEL_VERIFIED_PRE_RECEIPT_MIGRATION='
state = {'phase': 'RUNTIME_IMPORT', 'emitted': False}


def emit(value):
    state['emitted'] = True
    print(MARKER + json.dumps(value, sort_keys=True), flush=True)


def controlled_detail(exc):
    raw = str(exc).strip()
    if not raw:
        return {}
    digest = hashlib.sha256(raw.encode('utf-8', errors='replace')).hexdigest()
    lowered = raw.lower()
    prohibited = ('http://', 'https://', 'api_key', 'api-key', 'password',
                  'authorization', 'postgres://', 'postgresql://', 'apca-api-')
    value = {'detail_sha256': digest}
    if any(item in lowered for item in prohibited) or '\n' in raw or '\r' in raw:
        return value
    if len(raw) > 420:
        raw = raw[:365] + ' ... [sha256:%s]' % digest[:16]
    value['detail'] = raw
    return value


def refuse(code, exc=None, **extra):
    value = {'status': 'REFUSED', 'reason_code': code}
    if exc is not None:
        value.update(controlled_detail(exc))
    value.update(extra)
    emit(value)


def receipt_shape(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT "
            "(to_regclass('public.sentinel_corpus_publications') IS NOT NULL)::int"
            " || ':' || "
            "(to_regclass('public.sentinel_publication_validation_policy') IS NOT NULL)::int"
            " || ':' || "
            "(to_regclass('public.sentinel_publication_validation_receipts') IS NOT NULL)::int")
        row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else ''


c = None
try:
    state['phase'] = 'RUNTIME_IMPORT'
    from sentinel import backup_guard
    from sentinel.feed import publication, runtime_schema, store

    state['phase'] = 'DATABASE_CONNECT'
    c = store.connect(os.environ['SENTINEL_DATABASE_URL'], schema_mode='skip')

    state['phase'] = 'LEGACY_AUTHORITY_PROOF'
    shape = receipt_shape(c)
    c.rollback()
    if shape == '0:0:0':
        refuse('FRESH_DATABASE_NOT_PRE_RECEIPT_UPGRADE')
    elif shape == '1:1:1':
        refuse('PUBLICATION_RECEIPT_SCHEMA_ALREADY_INSTALLED')
    elif shape != '1:0:0':
        refuse('PUBLICATION_RECEIPT_SCHEMA_PARTIAL')
    else:
        state['phase'] = 'BACKUP_DURABILITY'
        backup_guard.require_writes_permitted(
            c, operation='verified pre-receipt receipt-schema migration')

        state['phase'] = 'RECEIPT_SCHEMA_MIGRATION'
        runtime_schema.migrate_feed_schema(
            c, allow_verified_pre_receipt=True)

        state['phase'] = 'POST_MIGRATION_AUTHORITY'
        if receipt_shape(c) != '1:1:1':
            raise RuntimeError('receipt schema did not reach complete installed shape')
        with c.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*)::bigint, MIN(required_after_version)::bigint,'
                ' MAX(required_after_version)::bigint'
                ' FROM sentinel_publication_validation_policy')
            policy = cur.fetchone()
            cur.execute(
                'SELECT COALESCE(MAX(version),0)::bigint'
                ' FROM sentinel_corpus_publications')
            latest_version = int(cur.fetchone()[0])
        if (not policy or int(policy[0]) != 1 or policy[1] is None
                or int(policy[1]) != int(policy[2]) or int(policy[1]) < 0):
            raise RuntimeError('receipt policy singleton is missing or ambiguous')
        boundary = int(policy[1])
        current = publication.current(c)
        current_version = int(current.version) if current is not None else 0
        if current_version != latest_version:
            raise RuntimeError('validated current publication does not match latest version')
        if current_version < boundary:
            raise RuntimeError('receipt policy boundary is ahead of current publication')
        c.rollback()
        emit({
            'status': 'PASS',
            'reason_code': 'VERIFIED_PRE_RECEIPT_SCHEMA_MIGRATED',
            'required_after_version': boundary,
            'current_publication_version': current_version,
        })
except Exception as exc:
    if c is not None:
        try:
            c.rollback()
        except Exception:
            pass
    phase = str(state.get('phase') or 'UNKNOWN')
    code = {
        'RUNTIME_IMPORT': 'MIGRATION_RUNTIME_IMPORT_FAILURE',
        'DATABASE_CONNECT': 'MIGRATION_DATABASE_CONNECT_FAILURE',
        'LEGACY_AUTHORITY_PROOF': 'MIGRATION_LEGACY_AUTHORITY_PROOF_FAILED',
        'BACKUP_DURABILITY': 'MIGRATION_BACKUP_DURABILITY_REFUSED',
        'RECEIPT_SCHEMA_MIGRATION': 'MIGRATION_RECEIPT_SCHEMA_REFUSED',
        'POST_MIGRATION_AUTHORITY': 'MIGRATION_POST_AUTHORITY_FAILED',
    }.get(phase, 'MIGRATION_RUNTIME_FAILURE')
    refuse(code, exc, error_type=type(exc).__name__, failure_phase=phase)
finally:
    if c is not None:
        c.close()
'''.strip()


class MigrationRefused(RuntimeError):
    pass


def _safe_detail(value: object) -> Optional[str]:
    detail = str(value or "").strip()
    if not detail:
        return None
    lowered = detail.lower()
    prohibited = (
        "http://", "https://", "api_key", "api-key", "password", "authorization",
        "postgres://", "postgresql://", "apca-api-",
    )
    if any(item in lowered for item in prohibited) or re.search(r"[\r\n\x00]", detail):
        return None
    if len(detail) <= 500:
        return detail
    digest = hashlib.sha256(detail.encode("utf-8", errors="replace")).hexdigest()[:16]
    return detail[:445] + " ... [sha256:%s]" % digest


def _payload(completed) -> Optional[Mapping[str, object]]:
    matches = []
    for line in (completed.stdout or "").splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            value = json.loads(line[len(MARKER):])
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        matches.append(value)
    return matches[0] if len(matches) == 1 else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate an independently verified pre-receipt Sentinel corpus")
    parser.add_argument(
        "--provision-verified-pre-receipt",
        action="store_true",
        help=(
            "Attest that the current publication-only receipt schema is the verified "
            "pre-receipt legacy corpus. Required; accepted only for exact 1:0:0 state."))
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.provision_verified_pre_receipt:
        print(
            "REFUSED: verified pre-receipt schema migration requires "
            "--provision-verified-pre-receipt",
            file=sys.stderr,
        )
        return 2

    runner = go.CommandRunner()
    env = go.merged_environment()
    now_text = go._utc_text(datetime.now(timezone.utc))
    try:
        git, gate = go.probe_git(runner, now_text=now_text)
        if gate.status != go.PASS or git.commit is None:
            raise MigrationRefused(
                "migration requires clean current main equal to origin/main")
        if not str(env.get("SENTINEL_POSTGRES_PASSWORD") or "").strip():
            raise MigrationRefused("Sentinel database authority is unavailable")
        receipt_key = str(env.get("SENTINEL_PUBLICATION_RECEIPT_KEY") or "").strip()
        if len(receipt_key.encode("utf-8")) < 32:
            raise MigrationRefused("publication receipt authority is unavailable")
        if not str(env.get("SENTINEL_BACKUP_DIR") or "").strip():
            raise MigrationRefused("durable backup target is unavailable")

        run_env = go._without_broker_authority(env)
        compose_args = go._resolve_compose_args(runner, run_env)
        if compose_args is None:
            raise MigrationRefused("Sentinel Compose graph is unavailable")
        database_failure = probe_contract.ensure_postgres_ready(
            runner, env=run_env, compose_args=compose_args)
        if database_failure is not None:
            raise MigrationRefused(
                "Sentinel PostgreSQL is unavailable (%s)"
                % database_failure["reason"])

        runtime = readonly_preflight._build_exact_ordinary(runner, git.commit)
        run_env["SENTINEL_RUNTIME_IMAGE_REF"] = runtime
        completed = runner.run([
            "docker", "compose", *compose_args, "--profile", "cli", "run",
            "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
            "-c", _MIGRATION_CODE,
        ], env=run_env)
        report = _payload(completed)
        if completed.returncode != 0 or report is None:
            evidence = (probe_contract.subprocess_evidence(
                completed, context="VERIFIED_PRE_RECEIPT_MIGRATION")
                if completed.returncode != 0
                else probe_contract.malformed_report_evidence(
                    completed, context="VERIFIED_PRE_RECEIPT_MIGRATION"))
            probe_contract.emit_probe_failure(evidence)
            raise MigrationRefused(
                "verified pre-receipt migration child failed (%s)"
                % evidence["reason"])

        status = str(report.get("status") or "")
        code = str(report.get("reason_code") or "MIGRATION_RUNTIME_FAILURE")
        detail = _safe_detail(report.get("detail"))
        if status != "PASS":
            text = "REFUSED: verified pre-receipt schema migration %s" % code
            if detail:
                text += " - " + detail
            if report.get("detail_sha256"):
                text += " [detail_sha256=%s]" % str(report["detail_sha256"])
            print(text, file=sys.stderr)
            return 2

        boundary = int(report.get("required_after_version") or 0)
        current = int(report.get("current_publication_version") or 0)
        print(
            "verified pre-receipt schema migration: PASS - receipt policy installed "
            "at legacy publication v%d; current publication v%d"
            % (boundary, current),
            flush=True,
        )
        return 0
    except MigrationRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
