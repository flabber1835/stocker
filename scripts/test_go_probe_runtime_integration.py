#!/usr/bin/env python3
"""Real-container regression for the GO cold-start/marker protocol.

This is CI-only destructive work inside a unique Compose project. It never uses
the production ``sentinel`` project or its volumes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_deployment_bootstrap as deploy_bootstrap  # noqa: E402
import sentinel_go_24x7_entry as source_final  # noqa: E402
import sentinel_go_probe_contract as contract  # noqa: E402
import sentinel_go_readonly_data_preflight as preflight  # noqa: E402
import sentinel_go_validate as go  # noqa: E402


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _source_export_fixture(
        code: str, status: str, *,
        observed_at: str = "2026-08-22T03:45:00+00:00") -> str:
    if status not in {"fresh", "creating"}:
        raise ValueError("unknown CI export fixture status")
    instant = datetime.fromisoformat(observed_at)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("CI source observation requires a timezone")
    if code.count("import datetime as dt") != 1:
        raise ValueError("CI clock import seam changed")
    # This container test proves database/marker behavior. Source validation has
    # its own HTTP simulator tests; a dummy API key must never contact a vendor.
    prefix = r'''
import datetime as _ci_real_dt
from types import SimpleNamespace as _ci_namespace
from sentinel.feed import calendar as _ci_calendar
from sentinel.feed import snapshot_export as _ci_exports
_ci_export_instant = _ci_real_dt.datetime.fromisoformat(__CI_OBSERVED_AT__)
class _ci_datetime(_ci_real_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return (_ci_export_instant.astimezone(tz) if tz is not None
                else _ci_export_instant.replace(tzinfo=None))
_ci_clock = _ci_namespace(
    datetime=_ci_datetime, date=_ci_real_dt.date,
    timezone=_ci_real_dt.timezone, timedelta=_ci_real_dt.timedelta)
_ci_calendar._dt = _ci_clock
_ci_export_calls = []
def _ci_export_probe(table, *, params=None, **kwargs):
    _ci_export_calls.append((table, dict(params or {})))
    if __CI_EXPORT_STATUS__ != 'fresh':
        raise _ci_exports.SharadarSnapshotExportError(
            'Sharadar %s export status=creating; CI source fixture' % table)
    return _ci_exports.ExportSnapshot(
        table, dict(params or {}), 'https://exports.example.invalid/ci-probe.zip',
        _ci_export_instant, _ci_export_instant)
_ci_exports.probe_snapshot = _ci_export_probe
'''.strip()
    prefix = prefix.replace("__CI_EXPORT_STATUS__", repr(status)).replace(
        "__CI_OBSERVED_AT__", repr(observed_at))
    return prefix + "\n" + code.replace("import datetime as dt", "dt = _ci_clock", 1)


def _run_probe(runner, compose_args, env: Mapping[str, str], code: str,
               *, database_url: str | None = None,
               source_export_status: str | None = None,
               source_observed_at: str = "2026-08-22T03:45:00+00:00"):
    if source_export_status is not None:
        code = _source_export_fixture(
            code, source_export_status, observed_at=source_observed_at)
    command = [
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps",
    ]
    if database_url is not None:
        command.extend(["--env", "SENTINEL_DATABASE_URL=" + database_url])
    command.extend(["--entrypoint", "python", "sentinel", "-c", code])
    return runner.run(command, env=env)


def _require_readonly_report(completed, *, check: str, status: str, reason: str):
    report = preflight._payload(completed)
    evidence = {"check": check, "child_exit": completed.returncode}
    if report is not None:
        for name in ("status", "reason_code", "failure_phase", "error_type",
                     "detail_sha256"):
            if name in report:
                evidence[name] = report[name]
    else:
        evidence["reason_code"] = "READONLY_MARKER_MISSING_OR_MALFORMED"
    passed = bool(completed.returncode == 0 and report is not None
                  and report.get("status") == status
                  and report.get("reason_code") == reason)
    evidence["result"] = "PASS" if passed else "FAIL"
    evidence["expected_status"] = status
    evidence["expected_reason"] = reason
    print("GO_PROBE_RUNTIME_CHECK=" + json.dumps(evidence, sort_keys=True),
          flush=True)
    _require(passed, "GO runtime check %s failed: %s" % (
        check, json.dumps(evidence, sort_keys=True)))
    return report


def _preparation_failure(completed):
    matches = []
    for stream in (completed.stdout or "", completed.stderr or ""):
        for line in stream.splitlines():
            if not line.startswith(contract.PREPARATION_FAILURE_MARKER):
                continue
            try:
                value = json.loads(
                    line[len(contract.PREPARATION_FAILURE_MARKER):])
            except ValueError:
                return None
            if not isinstance(value, dict):
                return None
            matches.append(value)
    return matches[0] if len(matches) == 1 else None


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    runtime_image = args[0] if args else "sentinel:latest"
    project = "sentinel-go-probe-ci-%d" % os.getpid()
    compose_args = ["-p", project, "-f", "docker-compose.sentinel.yml"]
    env = dict(os.environ)
    env.update({
        "SENTINEL_POSTGRES_PASSWORD": "ci-probe-database-password",
        "SENTINEL_PUBLICATION_RECEIPT_KEY": "ci-probe-publication-receipt-key",
        "SENTINEL_BACKUP_DIR": "/ci/unused-backup",
        "SHARADAR_API_KEY": "ci-probe-sharadar-key",
        "SENTINEL_RUNTIME_IMAGE_REF": runtime_image,
        "SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "120",
    })
    runner = go.CommandRunner()
    prefix = ["docker", "compose", *compose_args]

    def cleanup() -> None:
        subprocess.run(
            prefix + ["down", "-v", "--remove-orphans"],
            cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False)

    cleanup()
    try:
        failure = contract.ensure_postgres_ready(
            runner, env=env, compose_args=compose_args)
        _require(failure is None, "cold-start PostgreSQL helper did not pass")

        identity = runner.run(prefix + [
            "--profile", "cli", "run", "--rm", "-T", "--no-deps",
            "--entrypoint", "sh", "sentinel", "-ceu",
            "test \"$(id -u)\" = 10001; test \"$(id -g)\" = 10001",
        ], env=env)
        _require(identity.returncode == 0,
                 "ordinary Sentinel probe did not run as uid/gid 10001")

        nonfinal = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE,
            source_export_status="creating",
            source_observed_at="2026-08-22T03:44:59+00:00")
        _require_readonly_report(
            nonfinal, check="cold_source_not_final", status="RECOVERY_REQUIRED",
            reason="CORPUS_SCHEMA_NOT_INSTALLED")

        creating = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE,
            source_export_status="creating")
        _require_readonly_report(
            creating, check="cold_export_creating", status="REFUSED",
            reason="SOURCE_EXPORT_UNAVAILABLE")

        empty = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE,
            source_export_status="fresh")
        _require_readonly_report(
            empty, check="cold_export_fresh", status="RECOVERY_REQUIRED",
            reason="CORPUS_SCHEMA_NOT_INSTALLED")

        stopped = runner.run(prefix + ["stop", contract.POSTGRES_SERVICE], env=env)
        _require(stopped.returncode == 0, "could not stop probe PostgreSQL")
        unavailable = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE)
        _require_readonly_report(
            unavailable, check="stopped_database", status="REFUSED",
            reason="DATABASE_CONNECT_UNAVAILABLE")

        failure = contract.ensure_postgres_ready(
            runner, env=env, compose_args=compose_args)
        _require(failure is None, "stopped PostgreSQL did not recover to healthy")

        broken_code = preflight._READ_ONLY_CODE.replace(
            "from sentinel.feed import (",
            "from sentinel_missing_for_go_probe import (", 1)
        broken = _run_probe(runner, compose_args, env, broken_code)
        _require_readonly_report(
            broken, check="runtime_import", status="REFUSED",
            reason="RUNTIME_IMPORT_UNAVAILABLE")

        bad = _run_probe(
            runner, compose_args, env, preflight._READ_ONLY_CODE,
            database_url=(
                "postgresql://sentinel:ci-intentionally-wrong@"
                "sentinel-postgres:5432/sentinel"))
        _require_readonly_report(
            bad, check="database_authentication", status="REFUSED",
            reason="DATABASE_CONNECT_UNAVAILABLE")
        marker_text = bad.stdout or ""
        _require("ci-intentionally-wrong" not in marker_text,
                 "bad-auth marker leaked the synthetic password")
        _require("postgresql://" not in marker_text,
                 "bad-auth marker leaked a database URL")

        mutable_import_code = source_final._PREPARATION_CODE.replace(
            "from sentinel import backup_guard, schema",
            "from sentinel_missing_for_go_probe import backup_guard, schema", 1)
        mutable_import = _run_probe(
            runner, compose_args, env, mutable_import_code)
        mutable_import_report = _preparation_failure(mutable_import)
        _require(mutable_import.returncode != 0,
                 "24x7 import failure did not fail the child")
        _require(mutable_import_report is not None,
                 "24x7 import failure emitted no preparation marker")
        _require(
            mutable_import_report.get("reason_code")
            == "PREPARATION_RUNTIME_IMPORT_FAILURE",
            "24x7 import failure lost its causal reason")

        mutable_bad = _run_probe(
            runner, compose_args, env, source_final._PREPARATION_CODE,
            database_url=(
                "postgresql://sentinel:ci-24x7-intentionally-wrong@"
                "sentinel-postgres:5432/sentinel"))
        mutable_bad_report = _preparation_failure(mutable_bad)
        _require(mutable_bad.returncode != 0,
                 "24x7 bad-auth failure did not fail the child")
        _require(mutable_bad_report is not None,
                 "24x7 bad-auth failure emitted no preparation marker")
        _require(
            mutable_bad_report.get("reason_code")
            == "PREPARATION_DATABASE_CONNECT_FAILURE",
            "24x7 bad-auth failure lost its causal reason")
        mutable_marker_text = mutable_bad.stdout or ""
        _require("ci-24x7-intentionally-wrong" not in mutable_marker_text,
                 "24x7 bad-auth marker leaked the synthetic password")
        _require("postgresql://" not in mutable_marker_text,
                 "24x7 bad-auth marker leaked a database URL")

        original_compose_args = deploy_bootstrap._compose_args
        original_backup_target = deploy_bootstrap._require_backup_target
        deploy_bootstrap._compose_args = lambda _env: compose_args
        deploy_bootstrap._require_backup_target = lambda _env: None
        try:
            state = deploy_bootstrap._receipt_ancestry(env)
            _require(
                state == deploy_bootstrap.SAFE_FRESH_DATABASE,
                "fresh database was not safe for first-install receipt authority")

            # The generation guard must own the same advisory lock canonical
            # publication uses. A second publisher-shaped lock attempt must fail
            # for the whole yielded ancestry interval.
            with deploy_bootstrap._receipt_ancestry_guard(env) as locked_state:
                _require(
                    locked_state == deploy_bootstrap.SAFE_FRESH_DATABASE,
                    "locked fresh ancestry changed classification")
                competing = deploy_bootstrap._psql(
                    env, compose_args,
                    "SELECT pg_try_advisory_lock(%d)::int"
                    % deploy_bootstrap.CORPUS_LOCK_KEY)
                _require(
                    competing == "0",
                    "receipt bootstrap did not exclude canonical publication")
            released = deploy_bootstrap._psql(
                env, compose_args,
                "SELECT pg_try_advisory_lock(%d)::int"
                % deploy_bootstrap.CORPUS_LOCK_KEY)
            _require(
                released == "1",
                "receipt bootstrap did not release publication authority")

            deploy_bootstrap._psql(
                env, compose_args,
                "CREATE TABLE sentinel_corpus_publications (version BIGINT PRIMARY KEY);"
                " INSERT INTO sentinel_corpus_publications(version) VALUES (7)")
            try:
                deploy_bootstrap._receipt_ancestry(env)
            except deploy_bootstrap.BootstrapRefused as exc:
                _require(
                    "cannot distinguish a verified pre-receipt database" in str(exc),
                    "ambiguous 1:0:0 ancestry refused for the wrong reason")
            else:
                raise RuntimeError(
                    "publication history without receipt authority was grandfathered")

            state = deploy_bootstrap._receipt_ancestry(
                env, allow_verified_pre_receipt=True)
            _require(
                state == deploy_bootstrap.SAFE_VERIFIED_PRE_RECEIPT_DATABASE,
                "operator-attested pre-receipt ancestry was not recognized")

            deploy_bootstrap._psql(
                env, compose_args,
                "CREATE TABLE sentinel_publication_validation_policy ("
                "id BOOLEAN PRIMARY KEY, required_after_version BIGINT NOT NULL);"
                " INSERT INTO sentinel_publication_validation_policy"
                "(id,required_after_version) VALUES (TRUE,7);"
                " CREATE TABLE sentinel_publication_validation_receipts ("
                "publication_version BIGINT PRIMARY KEY)")
            state = deploy_bootstrap._receipt_ancestry(env)
            _require(
                state == deploy_bootstrap.SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS,
                "empty receipt-policy era was not recognized")

            deploy_bootstrap._psql(
                env, compose_args,
                "INSERT INTO sentinel_publication_validation_receipts"
                "(publication_version) VALUES (8)")
            state = deploy_bootstrap._receipt_ancestry(env)
            _require(
                state == deploy_bootstrap.AUTHENTICATED_RECEIPTS_EXIST,
                "authenticated receipt ancestry did not fence key rotation")
            attested_state = deploy_bootstrap._receipt_ancestry(
                env, allow_verified_pre_receipt=True)
            _require(
                attested_state == deploy_bootstrap.AUTHENTICATED_RECEIPTS_EXIST,
                "pre-receipt attestation bypassed authenticated receipt ancestry")
        finally:
            deploy_bootstrap._compose_args = original_compose_args
            deploy_bootstrap._require_backup_target = original_backup_target

        print("GO_PROBE_RUNTIME_INTEGRATION_PASS")
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
