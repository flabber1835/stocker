#!/usr/bin/env python3
"""Source-final preparation overlay for 24x7 Sentinel installation.

The supported operator entry remains ``scripts/sentinel-go-validate.sh``. This
module is imported by ``sentinel_go_verified_entry.py`` only after the public
lifecycle lock and one-run capability have been proven.

Its single responsibility is to choose the newest Sharadar decision session
whose reviewed source-final not-before has elapsed and run the existing bounded,
feed-authorized recovery/preparation through that session. A later closed but
not-yet-final session remains visible as an ordinary readiness/session NO_GO.

No public gate is redefined here. Sharadar readiness keeps its original
latest-closed-session meaning and ``prospective_trading_window`` keeps its
original following-open meaning. The separate installation overlay decides
whether those temporal NO_GO facts are safe for fenced software installation.
"""
from __future__ import annotations

import json
import math
import sys
import time
from typing import Mapping, Optional

import sentinel_go_verified_entry as verified

controller = verified.controller
go = verified.go
entry = controller.entry


_PREPARATION_CODE = r'''
import hashlib
import json, os

SUCCESS_MARKER = 'SENTINEL_GO_PREPARATION='
RECOVERY_MARKER = 'SENTINEL_GO_PREPARATION_RECOVERY='
FAILURE_MARKER = 'SENTINEL_GO_PREPARATION_FAILURE='
IDENTITY_REASON_CODES = {
    'NO_PERMANENT_ID': 'SOURCE_IDENTITY_NO_PERMANENT_ID',
    'IDENTITY_INTERVAL_GAP': 'SOURCE_IDENTITY_INTERVAL_GAP',
    'TICKER_REUSE_UNRESOLVED': 'SOURCE_IDENTITY_TICKER_REUSE_UNRESOLVED',
    'AMBIGUOUS_IDENTITY': 'SOURCE_IDENTITY_AMBIGUOUS',
}


def failure_detail(exc):
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
    from sentinel.source_diagnostic import coverage_diagnostic
    source = coverage_diagnostic(raw)
    if source is not None:
        value['source_coverage'] = source
    if len(raw) > 420:
        raw = raw[:365] + ' ... [sha256:%s]' % digest[:16]
    value['detail'] = raw
    return value


def reason_code(phase, exc):
    name = type(exc).__name__
    lowered = str(exc).lower()
    if name == 'SeedIdentityCollision':
        return 'SOURCE_IDENTITY_COLLISION'
    if name == 'VendorPublicationUnstable':
        return 'SOURCE_PUBLICATION_UNSTABLE'
    if name == 'OperationalAcquisitionRefused':
        return 'OPERATIONAL_ACQUISITION_BOUND_EXCEEDED'
    if name == 'SharadarSnapshotExportError':
        return 'SOURCE_EXPORT_UNAVAILABLE'
    if name == 'ExportPending':
        return 'SOURCE_EXPORT_PENDING'
    if name == 'SharadarRetryDeferred':
        return 'SOURCE_RETRY_DEFERRED'
    if name == 'MutationCursorUnavailable':
        return 'LOCAL_CURSOR_MISSING'
    if name == 'HistoricalIdentityMutation':
        return 'SOURCE_IDENTITY_HISTORY_MUTATION'
    if name == 'SeedHistoryIncomplete' and lowered.startswith(
            'sharadar sep seed eligible-set coverage refused:'):
        return 'SOURCE_SEED_COVERAGE_INCOMPLETE'
    if name == 'SepMutationIdentityRefused':
        identity_reason = str(getattr(exc, 'reason_code', '') or '')
        return IDENTITY_REASON_CODES.get(
            identity_reason, 'SOURCE_IDENTITY_UNRESOLVED')
    if name in {'SharadarMutationRefused', 'SourceAuthorityRefused'}:
        if 'source cursor' in lowered:
            return 'LOCAL_CURSOR_CORRUPT'
        if 'no positive raw close' in lowered:
            return 'SOURCE_RAW_CLOSE_INVALID'
        if 'lastupdated' in lowered or 'invalid date' in lowered:
            return 'SOURCE_CDC_INVALID'
        return 'SOURCE_AUTHORITY_REFUSED'
    return {
        'RUNTIME_IMPORT': 'PREPARATION_RUNTIME_IMPORT_FAILURE',
        'DATABASE_CONNECT': 'PREPARATION_DATABASE_CONNECT_FAILURE',
        'BACKUP_DURABILITY': 'PREPARATION_BACKUP_DURABILITY_REFUSED',
        'SCHEMA_MIGRATION': 'PREPARATION_SCHEMA_MIGRATION_FAILED',
        'SOURCE_FINAL_FRONTIER': 'PREPARATION_SOURCE_FINAL_FRONTIER_FAILED',
        'DAILY_CATCHUP': 'PREPARATION_DAILY_CATCHUP_FAILED',
        'PUBLICATION_CHECK': 'PREPARATION_PUBLICATION_CHECK_FAILED',
    }.get(str(phase), 'PREPARATION_RUNTIME_FAILURE')


def emit_failure(phase, exc):
    value = {
        'phase': str(phase),
        'error_type': type(exc).__name__,
        'reason_code': reason_code(phase, exc),
        'schema_migration_attempted': schema_attempted,
        'bounded_sharadar_daily_attempted': daily_attempted,
    }
    if type(exc).__name__ == 'SepMutationIdentityRefused':
        identity_reason = str(getattr(exc, 'reason_code', '') or '')
        if identity_reason:
            value['identity_reason'] = identity_reason
    value.update(failure_detail(exc))
    print(FAILURE_MARKER + json.dumps(value, sort_keys=True), flush=True)


c = None
schema_attempted = False
daily_attempted = False
phase = 'RUNTIME_IMPORT'
try:
    from datetime import datetime, timezone
    from sentinel import backup_guard, schema
    from sentinel.feed import calendar, rolling_go_inputs, publication, store, progress
    from sentinel.shadow_runtime import publication_not_before

    def latest_source_final(now):
        target = calendar.latest_closed_session(now)
        while now < publication_not_before(target):
            previous = calendar.previous_sessions(target, 2)
            if len(previous) != 2 or previous[-1] != target:
                raise RuntimeError('source-final predecessor session is unavailable')
            target = previous[0]
        return target

    phase = 'DATABASE_CONNECT'
    progress.emit('database_connect', 'started')
    c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
    phase = 'BACKUP_DURABILITY'
    progress.emit('backup_durability', 'started')
    backup_guard.require_writes_permitted(
        c, operation='NAS validation schema migration')
    phase = 'SCHEMA_MIGRATION'
    progress.emit('schema_migration', 'started', reason='BEHAVIORAL_SCHEMA')
    schema_attempted = True
    schema.ensure_schema(c)
    progress.emit('schema_migration', 'started', reason='FEED_SCHEMA')
    store.migrate_schema(c)
    progress.emit('schema_migration', 'completed')

    phase = 'SOURCE_FINAL_FRONTIER'
    now = datetime.now(timezone.utc)
    target = latest_source_final(now)
    execution_session = calendar.next_session(target)
    execution_open, _execution_close = calendar.session_window(execution_session)
    source_final = now >= publication_not_before(target)
    following_open_future = now < execution_open.astimezone(timezone.utc)

    phase = 'DAILY_CATCHUP'
    progress.emit('daily_catchup', 'started', date_to=target)
    daily_attempted = True
    recovered = rolling_go_inputs.prepare(c, target_session=target)
    print(RECOVERY_MARKER + json.dumps({
        'mode': recovered['status'],
        'input_contract': recovered['schema'],
    }, sort_keys=True), flush=True)

    phase = 'PUBLICATION_CHECK'
    progress.emit('publication_check', 'started', date_to=target)
    after = rolling_go_inputs.current(c)
    visible = after.window_end if after is not None else None
    current = (
        after is not None and after.window_end is not None
        and after.window_end >= target and visible == target
        and publication.chain_gaps(c) == [])
    print(SUCCESS_MARKER + json.dumps({
        'schema_migrated': True,
        'source_not_before_satisfied': source_final,
        'following_open_future': following_open_future,
        'bounded_sharadar_daily': daily_attempted,
        'publication_current': current,
    }, sort_keys=True), flush=True)
except BaseException as exc:
    if c is not None:
        try:
            c.rollback()
        except BaseException:
            pass
    emit_failure(phase, exc)
    raise
finally:
    if c is not None:
        c.close()
'''.strip()


def _deployment_preparation_probe(
        runner, *, env: Mapping[str, str], runtime_ref: Optional[str],
        commit: Optional[str], monotonic=time.monotonic):
    """Prepare through the latest source-final frontier using the feed-bound runner."""
    prerequisites = (
        bool(str(env.get('SHARADAR_API_KEY') or '').strip())
        and bool(env.get('SENTINEL_POSTGRES_PASSWORD'))
        and commit is not None and go._HEX40.fullmatch(str(commit)) is not None
        and runtime_ref is not None
        and go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None)
    if not prerequisites:
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest({
                'reason': 'PREPARATION_AUTHORITY_UNAVAILABLE'}))

    run_env = go._without_broker_authority(env)
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest({
                'reason': 'PREPARATION_COMPOSE_GRAPH_UNAVAILABLE'}))

    # Feed authority is injected by the existing verified FeedBoundPreparationRunner.
    run_env['SENTINEL_RUNTIME_IMAGE_REF'] = str(runtime_ref)
    started = monotonic()
    completed = runner.run([
        'docker', 'compose', *compose_args, '--profile', 'cli', 'run',
        '--rm', '-T', '--no-deps', '--entrypoint', 'python', 'sentinel',
        '-c', _PREPARATION_CODE,
    ], env=run_env)
    elapsed = max(0, int(math.ceil((monotonic() - started) * 1000.0)))

    marker = 'SENTINEL_GO_PREPARATION='
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or '').splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    expected = {
        'schema_migrated', 'source_not_before_satisfied',
        'following_open_future', 'bounded_sharadar_daily',
        'publication_current'}
    valid_shape = isinstance(payload, dict) and set(payload) == expected
    passed = bool(
        valid_shape
        and payload.get('schema_migrated') is True
        and payload.get('source_not_before_satisfied') is True
        and payload.get('bounded_sharadar_daily') is True
        and payload.get('publication_current') is True)
    evidence = {
        'exit_code': int(completed.returncode),
        'schema_migrated': bool(valid_shape and payload.get('schema_migrated')),
        'bounded_sharadar_daily': bool(
            valid_shape and payload.get('bounded_sharadar_daily')),
        'source_not_before_satisfied': bool(
            valid_shape and payload.get('source_not_before_satisfied')),
        'following_open_future': bool(
            valid_shape and payload.get('following_open_future')),
        'publication_current': bool(
            valid_shape and payload.get('publication_current')),
        'following_open_is_session_authority_only': True,
        'feed_authority_delegated_to_verified_runner': True,
        'broker_authority_removed': not bool(
            go._BROKER_AUTH_ENV.intersection(run_env)),
    }
    schema_attempted, daily_attempted = go.preparation_attempts(
        completed, schema_migrated=evidence['schema_migrated'],
        daily_completed=evidence['bounded_sharadar_daily'])
    evidence.update(schema_migration_attempted=schema_attempted,
                    bounded_sharadar_daily_attempted=daily_attempted)
    return go.PreparationSummary(
        status=go.PASS if passed else go.FAIL,
        runtime_image_digest=runtime_ref,
        schema_migration_attempted=schema_attempted,
        bounded_sharadar_daily_attempted=daily_attempted,
        broker_mutation_attempts=0,
        evidence_sha256=go._evidence_digest(evidence),
        elapsed_milliseconds=elapsed)


def install() -> None:
    # The feed-bound runner compares the command's final argument with
    # go._PREPARATION_CODE, so install one identical reviewed string everywhere.
    entry._RECOVERY_PREPARATION_CODE = _PREPARATION_CODE
    entry._CORE_PREPARATION_PROBE = _deployment_preparation_probe
    go._PREPARATION_CODE = _PREPARATION_CODE


def main(argv=None) -> int:
    print(
        'REFUSED: sentinel_go_24x7_entry.py is internal; use '
        'scripts/sentinel-go-validate.sh',
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
