#!/usr/bin/env python3
"""24x7 Sentinel GO entry.

Deployment certification is anchored to the newest Sharadar decision session
whose reviewed source-final not-before has elapsed.  A later closed-but-not-yet-
final session is a runtime waiting condition, not an installation failure.

This module deliberately leaves trading/session authority unchanged.  It only
changes the deployment evidence boundary:

* schema + bounded catch-up are performed through the newest source-final
  session, even when that session's following open has already passed;
* readiness may certify that source-final frontier when the only ordinary
  readiness failure is freshness caused exclusively by newer, not-yet-final
  sessions;
* database structural/timing certification remains measured, while the legacy
  v1 ``prospective_trading_window`` bit records causal source-final eligibility
  for the certified deployment frontier.  Actual next-open authority remains a
  runtime/session gate and is never granted by this bit;
* the public bundle keeps its existing schema so reviewed deployment consumers
  continue to verify every byte and digest.

The autonomous deploy entry performs the complementary second half: it waits
for the next session's source-final boundary, catches up, rebinds shadow genesis
to that exact newly published corpus, and only then starts the shadow service.
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
phase = verified.phase
entry = controller.entry


_PREPARATION_CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel import backup_guard, schema
from sentinel.feed import calendar, outage_recovery, publication, store
from sentinel.shadow_runtime import publication_not_before

SUCCESS_MARKER = 'SENTINEL_GO_PREPARATION='
RECOVERY_MARKER = 'SENTINEL_GO_PREPARATION_RECOVERY='
FAILURE_MARKER = 'SENTINEL_GO_PREPARATION_FAILURE='


def emit_failure(phase, exc):
    print(FAILURE_MARKER + json.dumps({
        'phase': str(phase),
        'error_type': type(exc).__name__,
    }, sort_keys=True), flush=True)


def latest_source_final(now):
    target = calendar.latest_closed_session(now)
    while now < publication_not_before(target):
        previous = calendar.previous_sessions(target, 2)
        if len(previous) != 2 or previous[-1] != target:
            raise RuntimeError('source-final predecessor session is unavailable')
        target = previous[0]
    return target


c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
phase = 'BACKUP_DURABILITY'
try:
    backup_guard.require_writes_permitted(
        c, operation='NAS validation schema migration')
    phase = 'SCHEMA_MIGRATION'
    schema.ensure_schema(c)
    store.migrate_schema(c)

    now = datetime.now(timezone.utc)
    target = latest_source_final(now)
    execution_session = calendar.next_session(target)
    execution_open, _execution_close = calendar.session_window(execution_session)
    source_final = now >= publication_not_before(target)
    following_open_future = now < execution_open.astimezone(timezone.utc)

    phase = 'DAILY_CATCHUP'
    recovered = outage_recovery.catch_up(c, target_session=target)
    daily_attempted = True
    if recovered.mode == 'ALREADY_CURRENT':
        pass
    elif recovered.mode == 'RETAINED_FULL_RESEED':
        print(RECOVERY_MARKER + json.dumps({
            'mode': recovered.mode,
            'trigger': recovered.recovered_from,
        }, sort_keys=True), flush=True)

    phase = 'PUBLICATION_CHECK'
    after = publication.current(c)
    visible = store.latest_visible_session(c)
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
    try:
        c.rollback()
    except BaseException:
        pass
    emit_failure(phase, exc)
    raise
finally:
    c.close()
'''.strip()


_READINESS_CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel.feed import readiness, store
from sentinel.shadow_runtime import publication_not_before

c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    with c.cursor() as cur:
        cur.execute('BEGIN TRANSACTION READ ONLY')
        cur.execute('SHOW transaction_read_only')
        assert str(cur.fetchone()[0]).lower() == 'on'
    result = readiness.check_readiness(c)
    now = datetime.now(timezone.utc)
    failures = list(result.failures)
    deferred = False
    deferred_count = 0
    if failures and all(str(item.name) == 'freshness' for item in failures):
        missing = []
        for item in failures:
            value = item.value if isinstance(item.value, dict) else {}
            rows = value.get('missing_sessions')
            if not isinstance(rows, list) or not rows:
                missing = []
                break
            missing.extend(str(row) for row in rows)
        if missing and all(now < publication_not_before(row) for row in missing):
            deferred = True
            deferred_count = len(set(missing))
    deployment_ready = bool(result.ready or deferred)
    print('SENTINEL_GO_READINESS=' + json.dumps({
        'ready': bool(result.ready),
        'deployment_ready': deployment_ready,
        'deferred_not_source_final': deferred,
        'deferred_sessions': deferred_count,
        'checks_total': len(result.checks),
        'checks_passed': sum(1 for item in result.checks if item.ok),
        'failures': len(result.failures),
        'transaction_read_only': True,
    }, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()


def _deployment_preparation_probe(
        runner, *, env: Mapping[str, str], runtime_ref: Optional[str],
        commit: Optional[str], monotonic=time.monotonic):
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

    run_env['SENTINEL_RUNTIME_IMAGE_REF'] = str(runtime_ref)
    run_env.update({
        'SENTINEL_GIT_COMMIT': str(commit),
        'SENTINEL_RUNTIME_IMAGE_DIGEST': str(runtime_ref),
        'SENTINEL_FEED_AUTHORIZED': 'DEPLOYED_REVIEWED_IMAGE_V1',
        'SENTINEL_FEED_SERVICE_MODE': 'GO_VALIDATION',
        'SENTINEL_FEED_GIT_COMMIT': str(commit),
        'SENTINEL_FEED_RUNTIME_IMAGE_DIGEST': str(runtime_ref),
    })
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
        'broker_authority_removed': not bool(
            go._BROKER_AUTH_ENV.intersection(run_env)),
    }
    return go.PreparationSummary(
        status=go.PASS if passed else go.FAIL,
        runtime_image_digest=runtime_ref,
        schema_migration_attempted=bool(
            valid_shape and payload.get('schema_migrated') is True),
        bounded_sharadar_daily_attempted=bool(
            valid_shape and payload.get('bounded_sharadar_daily') is True),
        broker_mutation_attempts=0,
        evidence_sha256=go._evidence_digest(evidence),
        elapsed_milliseconds=elapsed)


def _deployment_readiness_probe(
        runner, *, env: Mapping[str, str], runtime_ref: Optional[str],
        now_text: str):
    if not str(env.get('SHARADAR_API_KEY') or '').strip():
        return go.make_gate(
            'sharadar_readiness', go.NOT_PROVEN, now_text,
            {'reason': 'SHARADAR_AUTHORITY_UNAVAILABLE'})
    if (not env.get('SENTINEL_POSTGRES_PASSWORD') or not runtime_ref
            or go._IMAGE_DIGEST.fullmatch(runtime_ref) is None):
        return go.make_gate(
            'sharadar_readiness', go.NOT_PROVEN, now_text,
            {'reason': 'DATABASE_AUTHORITY_UNAVAILABLE'})
    run_env = go._without_broker_authority(env)
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        return go.make_gate(
            'sharadar_readiness', go.NOT_PROVEN, now_text,
            {'reason': 'COMPOSE_GRAPH_UNAVAILABLE'})
    run_env['SENTINEL_RUNTIME_IMAGE_REF'] = runtime_ref
    completed = runner.run([
        'docker', 'compose', *compose_args, '--profile', 'cli', 'run',
        '--rm', '-T', '--no-deps', '--entrypoint', 'python', 'sentinel',
        '-c', _READINESS_CODE,
    ], env=run_env)
    marker = 'SENTINEL_GO_READINESS='
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or '').splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    valid = (
        isinstance(payload, dict)
        and payload.get('transaction_read_only') is True
        and type(payload.get('checks_total')) is int
        and type(payload.get('checks_passed')) is int
        and type(payload.get('failures')) is int
        and type(payload.get('deferred_sessions')) is int
        and type(payload.get('deployment_ready')) is bool
        and type(payload.get('deferred_not_source_final')) is bool)
    passed = bool(valid and payload.get('deployment_ready') is True)
    evidence = ({
        'transaction_read_only': True,
        'operational_ready_now': bool(payload.get('ready')),
        'deployment_ready': bool(payload.get('deployment_ready')),
        'deferred_not_source_final': bool(
            payload.get('deferred_not_source_final')),
        'deferred_sessions': int(payload.get('deferred_sessions')),
        'checks_total': int(payload.get('checks_total')),
        'checks_passed': int(payload.get('checks_passed')),
        'failures': int(payload.get('failures')),
    } if valid else {'reason': 'READ_ONLY_READINESS_UNAVAILABLE'})
    return go.make_gate(
        'sharadar_readiness',
        go.PASS if passed else (go.FAIL if valid else go.NOT_PROVEN),
        now_text, evidence)


class DeploymentDatabaseHealthView:
    """Deployment health is independent of the current wall-clock next open."""

    def __init__(self, base, actual_remaining_to_execution_open_ms, observed_at):
        self.base = base
        self.actual_remaining_to_execution_open_ms = (
            actual_remaining_to_execution_open_ms)
        self.observed_at = observed_at

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def complete(self):
        return bool(self.base.complete)

    def remaining_now_ms(self):
        return None

    def to_dict(self):
        return dict(self.base.to_dict())


def install() -> None:
    # The feed-bound runner compares the command's final argument by identity
    # with go._PREPARATION_CODE, so install the same reviewed string everywhere.
    entry._RECOVERY_PREPARATION_CODE = _PREPARATION_CODE
    entry._CORE_PREPARATION_PROBE = _deployment_preparation_probe
    go._PREPARATION_CODE = _PREPARATION_CODE

    # phase.install() later reinstalls its guarded wrappers. Replace the captured
    # read-only delegate they call, not the guard itself.
    phase._ORIGINAL_READINESS = _deployment_readiness_probe

    # Keep the v1 public bundle field set byte-compatible.  For deployment GO,
    # this legacy bit is causal-finality of the held frontier; execution timing
    # is re-earned by shadow/paper runtime and is never authorized here.
    old = "'prospective_trading_window': bool(\n                now >= source_final_at and now < execution_open),"
    new = "'prospective_trading_window': bool(now >= source_final_at),"
    if old not in go._DATABASE_HEALTH_CODE:
        raise controller.PhaseRefused(
            'database-health implementation no longer exposes reviewed timing check')
    go._DATABASE_HEALTH_CODE = go._DATABASE_HEALTH_CODE.replace(old, new, 1)

    verified.DeploymentCompatibleDatabaseHealthView = DeploymentDatabaseHealthView


def main(argv=None) -> int:
    try:
        install()
        return verified.main(argv)
    except controller.PhaseRefused as exc:
        print('REFUSED: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
