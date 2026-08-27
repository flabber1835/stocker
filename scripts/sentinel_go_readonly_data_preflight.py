#!/usr/bin/env python3
"""Fail fast on deterministic Sharadar/local-feed refusals without mutation.

This preflight is allowed to run before stable artifact certification because it
is read-only. It builds the exact ordinary runtime for current clean main, opens
the production PostgreSQL transaction READ ONLY, validates the durable SEP,
ACTIONS, and recent-complete-reconciliation cursor shapes against the current
publication and decision frontier, then—only after the reviewed source-final
boundary—fetches the pending SEP ``lastupdated`` interval twice through the
normal Sharadar transport and runs the production mutation-row authority
validator.

If a pending mutation fails only because local permanent identity is absent or a
single known listing interval is stale, the preflight may observe current TICKERS
GET-only. It accepts that as liveness evidence only after the production TICKERS
source membrane proves complete keys, structural validity and a stable second
observation; the routine historical-identity guard must also prove the candidate
is forward-only. The candidate is never written or published here.

It never creates/migrates schema, advances a cursor, creates an ingest run,
renormalizes bars, publishes a corpus generation, downloads the complete ACTIONS
export, or performs the recent complete SEP export. Those stronger source and
mutation boundaries remain owned by the certified preparation.

If the newest closed session has not reached the reviewed Sharadar source-final
boundary, this phase deliberately defers SEP source inspection. A still-
publishing vendor view is never negative authority. Missing legacy cursor/schema
state is reported as recovery-required rather than treated as evidence of source
corruption.

The certified preparation later repeats source observation under the normal feed
write membrane. This phase is only a liveness filter, never deployment authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Mapping, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402

MARKER = "SENTINEL_GO_READONLY_DATA_PREFLIGHT="

_READ_ONLY_CODE = r'''
import datetime as dt
import json, os
from sentinel.feed import (
    calendar, identity_refresh, maintenance_impl as maintenance, publication,
    recent_reconciliation, sharadar, store, universe)
from sentinel.shadow_runtime import publication_not_before

MARKER = 'SENTINEL_GO_READONLY_DATA_PREFLIGHT='


def emit(value):
    print(MARKER + json.dumps(value, sort_keys=True), flush=True)


def refuse(code, detail=None, **extra):
    value = {'status': 'REFUSED', 'reason_code': code}
    if detail:
        value['detail'] = detail
    value.update(extra)
    emit(value)


def controlled_detail(exc):
    detail = str(exc).strip()
    lowered = detail.lower()
    prohibited = ('http://', 'https://', 'api_key', 'password', 'authorization',
                  'postgres://', 'postgresql://', 'apca-api-')
    if not detail or len(detail) > 500 or any(item in lowered for item in prohibited):
        return None
    return detail


def cursor_from_row(row, *, name, kind, current_version):
    if row is None:
        return None
    raw = row[1]
    if isinstance(raw, dict):
        state = raw
    else:
        try:
            state = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise maintenance.SharadarMutationRefused(
                'source cursor %s is not valid JSON' % name) from exc
    required = {'kind', 'processed_through', 'publication_version'}
    if (not isinstance(state, dict) or set(state) != required
            or state.get('kind') != kind):
        raise maintenance.SharadarMutationRefused(
            'source cursor %s has an unknown durable state shape' % name)
    try:
        through = dt.date.fromisoformat(str(state['processed_through']))
        version = int(state['publication_version'])
        row_date = (row[0] if isinstance(row[0], dt.date)
                    else dt.date.fromisoformat(str(row[0])))
    except (TypeError, ValueError) as exc:
        raise maintenance.SharadarMutationRefused(
            'source cursor %s has invalid date/version evidence' % name) from exc
    if row_date != through:
        raise maintenance.SharadarMutationRefused(
            'source cursor %s row date disagrees with its state' % name)
    if version > current_version:
        raise maintenance.SharadarMutationRefused(
            'source cursor %s is ahead of current publication v%d'
            % (name, current_version))
    return through, version


def load_cursor_readonly(conn, *, name, kind, current_version):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
            (name,))
        row = cur.fetchone()
    cursor = cursor_from_row(
        row, name=name, kind=kind, current_version=current_version)
    if cursor is None:
        return None
    through, version = cursor
    with conn.cursor() as cur:
        cur.execute(
            'SELECT 1 FROM sentinel_corpus_publications WHERE version=%s',
            (version,))
        if cur.fetchone() is None:
            raise maintenance.SharadarMutationRefused(
                'source cursor %s names missing publication v%d' % (name, version))
    return through, version


def require_not_future(cursor, *, name, target):
    if cursor is not None and cursor[0] > target:
        raise maintenance.SharadarMutationRefused(
            'source cursor %s processed_through %s is ahead of current closed session %s'
            % (name, cursor[0], target))


c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    with c.cursor() as cur:
        cur.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cur.execute('SHOW transaction_read_only')
        if str(cur.fetchone()[0]).lower() not in {'on', 'true'}:
            raise RuntimeError('read-only transaction could not be established')
        cur.execute("SELECT to_regclass('public.sentinel_corpus_publications')")
        publication_table = cur.fetchone()[0]
        cur.execute("SELECT to_regclass('public.sentinel_processed_sessions')")
        cursor_table = cur.fetchone()[0]

    if publication_table is None:
        emit({'status': 'RECOVERY_REQUIRED', 'reason_code': 'CORPUS_SCHEMA_NOT_INSTALLED'})
    else:
        current = publication.require_current(c)
        target_raw = calendar.latest_closed_session()
        target = dt.date.fromisoformat(str(target_raw))
        if cursor_table is None:
            emit({'status': 'RECOVERY_REQUIRED', 'reason_code': 'CURSOR_SCHEMA_NOT_INSTALLED'})
        else:
            sep_cursor = load_cursor_readonly(
                c, name=maintenance.SEP_CURSOR_NAME,
                kind='sharadar-sep-lastupdated/v1',
                current_version=current.version)
            actions_cursor = load_cursor_readonly(
                c, name=maintenance.ACTIONS_CURSOR_NAME,
                kind=maintenance.ACTIONS_CURSOR_KIND,
                current_version=current.version)
            recent_cursor = load_cursor_readonly(
                c, name=recent_reconciliation.CURSOR_NAME,
                kind=recent_reconciliation.CURSOR_KIND,
                current_version=current.version)

            require_not_future(
                sep_cursor, name=maintenance.SEP_CURSOR_NAME, target=target)
            require_not_future(
                actions_cursor, name=maintenance.ACTIONS_CURSOR_NAME, target=target)
            require_not_future(
                recent_cursor, name=recent_reconciliation.CURSOR_NAME, target=target)

            if sep_cursor is None:
                emit({'status': 'RECOVERY_REQUIRED', 'reason_code': 'SEP_CURSOR_MISSING'})
            else:
                through, _version = sep_cursor
                local_lag = []
                if actions_cursor is None:
                    local_lag.append('ACTIONS_CURSOR_MISSING')
                elif actions_cursor[0] < target:
                    local_lag.append('ACTIONS_CURSOR_BEHIND')
                if recent_cursor is None:
                    local_lag.append('RECENT_SEP_CURSOR_MISSING')
                elif recent_cursor[0] < target:
                    local_lag.append('RECENT_SEP_CURSOR_BEHIND')

                if through == target:
                    emit({
                        'status': 'PASS', 'reason_code': 'SEP_CDC_ALREADY_CURRENT',
                        'source_rows': 0, 'affected_source_dates': 0,
                        'local_followup': local_lag,
                    })
                elif dt.datetime.now(dt.timezone.utc) < publication_not_before(target_raw):
                    emit({
                        'status': 'DEFERRED',
                        'reason_code': 'SHARADAR_SOURCE_NOT_FINAL',
                        'local_followup': local_lag,
                    })
                else:
                    lo = through - dt.timedelta(days=1)
                    params = {
                        'lastupdated.gte': lo.isoformat(),
                        'lastupdated.lte': target.isoformat(),
                    }
                    rows = maintenance._stable_rows(
                        sharadar.fetch_table, sharadar.SEP, params)
                    market_start, market_end = maintenance._retained_market_bounds(c)
                    dates, refresh_required = (
                        identity_refresh.validate_with_current_tickers_if_refreshable(
                            c, rows, lo=lo, hi=target,
                            published_from=dt.date.fromisoformat(market_start),
                            published_through=dt.date.fromisoformat(market_end),
                        ))
                    emit({
                        'status': 'PASS',
                        'reason_code': (
                            'LOCAL_IDENTITY_REFRESH_REQUIRED'
                            if refresh_required else 'SEP_CDC_SOURCE_VALID'),
                        'source_rows': len(rows),
                        'affected_source_dates': len(set(dates)),
                        'local_followup': local_lag,
                    })
except identity_refresh.SepMutationIdentityRefused as exc:
    detail = controlled_detail(exc)
    codes = {
        'NO_PERMANENT_ID': 'SOURCE_IDENTITY_NO_PERMANENT_ID',
        'IDENTITY_INTERVAL_GAP': 'SOURCE_IDENTITY_INTERVAL_GAP',
        'TICKER_REUSE_UNRESOLVED': 'SOURCE_IDENTITY_TICKER_REUSE_UNRESOLVED',
        'AMBIGUOUS_IDENTITY': 'SOURCE_IDENTITY_AMBIGUOUS',
    }
    refuse(
        codes.get(exc.reason_code, 'SOURCE_IDENTITY_UNRESOLVED'), detail,
        identity_reason=exc.reason_code)
except universe.HistoricalIdentityMutation as exc:
    refuse('SOURCE_IDENTITY_HISTORY_MUTATION', controlled_detail(exc))
except maintenance.SharadarMutationRefused as exc:
    detail = controlled_detail(exc)
    lowered = str(exc).lower()
    if 'source cursor' in lowered:
        code = 'LOCAL_CURSOR_CORRUPT'
    elif 'no positive raw close' in lowered:
        code = 'SOURCE_RAW_CLOSE_INVALID'
    elif 'lastupdated' in lowered or 'invalid date' in lowered:
        code = 'SOURCE_CDC_INVALID'
    else:
        code = 'SOURCE_AUTHORITY_REFUSED'
    refuse(code, detail)
except Exception as exc:
    name = type(exc).__name__
    if name == 'VendorPublicationUnstable':
        code = 'SOURCE_PUBLICATION_UNSTABLE'
    elif name in {
            'TickersStructureInvalid', 'TickerMetadataIncomplete',
            'SourceAuthorityRefused', 'SnapshotExportIncomplete'}:
        code = 'SOURCE_IDENTITY_CANDIDATE_INVALID'
    else:
        code = 'READONLY_PREFLIGHT_UNAVAILABLE'
    emit({'status': 'REFUSED', 'reason_code': code,
          'error_type': name})
finally:
    try:
        c.rollback()
    finally:
        c.close()
'''.strip()


class PreflightRefused(RuntimeError):
    pass


def _safe_detail(value: object) -> Optional[str]:
    detail = str(value or "").strip()
    if not detail or len(detail) > 500:
        return None
    lowered = detail.lower()
    prohibited = (
        "http://", "https://", "api_key", "password", "authorization",
        "postgres://", "postgresql://", "apca-api-",
    )
    if any(item in lowered for item in prohibited) or re.search(r"[\r\n\x00]", detail):
        return None
    return detail


def _payload(completed) -> Optional[Mapping[str, object]]:
    for line in (completed.stdout or "").splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            value = json.loads(line[len(MARKER):])
        except ValueError:
            return None
        return value if isinstance(value, dict) else None
    return None


def _build_exact_ordinary(runner: go.CommandRunner, commit: str) -> str:
    ref = "sentinel-go-runtime:%s" % commit
    built = runner.run([
        "docker", "build", "--network", "host", "--build-arg",
        "SOURCE_GIT_SHA=" + commit, "-t", ref,
        "-f", "Dockerfile.sentinel", ".",
    ])
    if built.returncode != 0:
        raise PreflightRefused("exact ordinary Sentinel image build failed")
    digest = go._inspect_image_id(runner, ref)
    if digest is None or go._IMAGE_DIGEST.fullmatch(str(digest)) is None:
        raise PreflightRefused("exact ordinary Sentinel image identity is unavailable")
    return str(digest)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _ = list(argv if argv is not None else sys.argv[1:])
    runner = go.CommandRunner()
    env = go.merged_environment()
    now_text = go._utc_text(datetime.now(timezone.utc))
    try:
        git, gate = go.probe_git(runner, now_text=now_text)
        if gate.status != go.PASS or git.commit is None:
            raise PreflightRefused(
                "read-only data preflight requires clean current main equal to origin/main")
        if not str(env.get("SHARADAR_API_KEY") or "").strip():
            raise PreflightRefused("Sharadar authority is unavailable")
        if not str(env.get("SENTINEL_POSTGRES_PASSWORD") or "").strip():
            raise PreflightRefused("Sentinel database authority is unavailable")
        runtime = _build_exact_ordinary(runner, git.commit)
        run_env = go._without_broker_authority(env)
        compose_args = go._resolve_compose_args(runner, run_env)
        if compose_args is None:
            raise PreflightRefused("Sentinel Compose graph is unavailable")
        run_env["SENTINEL_RUNTIME_IMAGE_REF"] = runtime
        completed = runner.run([
            "docker", "compose", *compose_args, "--profile", "cli", "run",
            "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
            "-c", _READ_ONLY_CODE,
        ], env=run_env)
        report = _payload(completed)
        if completed.returncode != 0 or report is None:
            raise PreflightRefused("read-only Sharadar diagnostic did not complete")
        status = str(report.get("status") or "")
        code = str(report.get("reason_code") or "READONLY_PREFLIGHT_UNAVAILABLE")
        if status == "REFUSED":
            detail = _safe_detail(report.get("detail"))
            text = "REFUSED: read-only Sharadar preflight %s" % code
            if detail:
                text += " - " + detail
            print(text, file=sys.stderr)
            return 2
        if status == "PASS":
            print("read-only Sharadar preflight: PASS - %s" % code, flush=True)
            return 0
        if status == "DEFERRED":
            print(
                "read-only Sharadar preflight: DEFERRED - %s; stable certification may proceed but source is not yet final"
                % code,
                flush=True,
            )
            return 0
        if status == "RECOVERY_REQUIRED":
            print(
                "read-only Sharadar preflight: RECOVERY_REQUIRED - %s; certified recovery will decide the write path"
                % code,
                flush=True,
            )
            return 0
        raise PreflightRefused("read-only Sharadar diagnostic returned unknown state")
    except PreflightRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
