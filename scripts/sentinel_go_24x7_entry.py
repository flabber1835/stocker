#!/usr/bin/env python3
"""Source-final preparation overlay for 24x7 Sentinel installation.

The supported operator entry remains ``scripts/sentinel-go-validate.sh``. This
module is imported by ``sentinel_go_verified_entry.py`` only after the public
lifecycle lock and one-run capability have been proven.

Its single responsibility is to choose the newest market-data decision session
whose reviewed source-final not-before has elapsed and run the bounded,
feed-authorized Alpaca/OpenFIGI preparation through that session. A later closed
but not-yet-final session remains visible as an ordinary readiness/session NO_GO.

No public gate is redefined here. Market-data readiness keeps its original
latest-closed-session meaning and ``prospective_trading_window`` keeps its
original following-open meaning. The separate installation overlay decides
whether those temporal NO_GO facts are safe for fenced software installation.
"""
from __future__ import annotations

import json
import math
import runpy
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import time
from typing import Mapping, Optional

import sentinel_go_verified_entry as verified

controller = verified.controller
go = verified.go
entry = controller.entry


from sentinel_go_preparation_runtime import CODE as _PREPARATION_CODE


_RETAINED_REVISION_CODE = '''
import json, os
from sentinel.feed import store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    c.execute('SET TRANSACTION READ ONLY')
    exists = c.execute("SELECT to_regclass('sentinel_processed_sessions')").fetchone()[0]
    row = c.execute("SELECT state->'checkpoint'->'runtime_identity'->>'git_commit' FROM sentinel_processed_sessions WHERE cursor_name=%s", ('rolling-cold-start:v1',)).fetchone() if exists else None
    print(json.dumps({'retained_revision': row[0] if row else None}))
finally:
    c.rollback()
    c.close()
'''.strip()


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate evidence key')
        value[key] = item
    return value


@contextmanager
def _retained_manifest(runner, *, compose_args, env):
    """Read only an untrusted revision; the image authenticates its entire closure."""
    probe = runner.run(['docker', 'compose', *compose_args, '--profile', 'cli', 'run',
        '--rm', '-T', '--no-deps', '--entrypoint', 'python', 'sentinel', '-c', _RETAINED_REVISION_CODE],
        env=go._without_broker_authority(env))
    value = json.loads(probe.stdout or '', object_pairs_hook=_strict_object)
    if probe.returncode != 0 or not isinstance(value, dict) or set(value) != {'retained_revision'}:
        raise ValueError('retained revision read failed')
    revision = value['retained_revision']
    if revision is None:
        yield []
        return
    if not isinstance(revision, str) or go._HEX40.fullmatch(revision) is None:
        raise ValueError('retained revision invalid')
    # The supported host CLI puts scripts/, not the repository, on sys.path.
    # Load this stdlib-only exporter from the verified checkout's exact path.
    build = runpy.run_path(str(go.ROOT/'tools/sentinel_retained_source_manifest.py'))['build']
    manifest = build(root=go.ROOT, revision=revision)
    # Plain source evidence contains no credentials and is mounted read-only.
    with tempfile.TemporaryDirectory(prefix='sentinel-retained-') as folder:
        path = Path(folder)/'source.json'
        path.write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        # The image UID differs from the host; this public evidence is read-only.
        path.chmod(0o444)
        yield ['--volume', str(path.resolve()) + ':/retained/source.json:ro',
               '--env', 'SENTINEL_RETAINED_SOURCE_MANIFEST=/retained/source.json']


def _deployment_preparation_probe(
        runner, *, env: Mapping[str, str], runtime_ref: Optional[str],
        commit: Optional[str], monotonic=time.monotonic):
    """Prepare through the latest source-final frontier using the feed-bound runner."""
    prerequisites = (
        bool(str(env.get('ALPACA_API_KEY') or '').strip())
        and bool(str(env.get('ALPACA_SECRET_KEY') or '').strip())
        and bool(env.get('SENTINEL_POSTGRES_PASSWORD'))
        and commit is not None and go._HEX40.fullmatch(str(commit)) is not None
        and runtime_ref is not None
        and go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None)
    if not prerequisites:
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_market_data_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest({
                'reason': 'PREPARATION_AUTHORITY_UNAVAILABLE'}))

    run_env = go._with_market_data_authority(env)
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_market_data_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest({
                'reason': 'PREPARATION_COMPOSE_GRAPH_UNAVAILABLE'}))

    # Feed authority is injected by the existing verified FeedBoundPreparationRunner.
    run_env['SENTINEL_RUNTIME_IMAGE_REF'] = str(runtime_ref)
    started = monotonic()
    try:
        with _retained_manifest(runner, compose_args=compose_args, env=run_env) as manifest_args:
            completed = runner.run([
                'docker', 'compose', *compose_args, '--profile', 'cli', 'run',
                '--rm', '-T', '--no-deps', *manifest_args, '--env', 'ALPACA_API_KEY',
                '--env', 'ALPACA_SECRET_KEY', '--env', 'OPENFIGI_API_KEY', '--entrypoint', 'python', 'sentinel',
                '-c', _PREPARATION_CODE,
            ], env=run_env)
    except (ValueError, OSError, go.subprocess.SubprocessError):
        return go.PreparationSummary(status=go.FAIL, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False, bounded_market_data_daily_attempted=False,
            broker_mutation_attempts=0, evidence_sha256=go._evidence_digest({'reason': 'RETAINED_SOURCE_EVIDENCE_UNAVAILABLE'}))
    elapsed = max(0, int(math.ceil((monotonic() - started) * 1000.0)))

    marker = 'SENTINEL_GO_PREPARATION='
    payload = None
    lines = [line[len(marker):] for stream in
             (completed.stdout or '', completed.stderr or '')
             for line in stream.splitlines() if line.startswith(marker)]
    if completed.returncode == 0 and len(lines) == 1:
        try:
            payload = json.loads(lines[0], object_pairs_hook=_strict_object)
        except ValueError:
            payload = None
    expected = {
        'schema_migrated', 'source_not_before_satisfied',
        'following_open_future', 'bounded_market_data_daily',
        'publication_current'}
    valid_shape = (isinstance(payload, dict) and set(payload) == expected
                   and all(type(value) is bool for value in payload.values()))
    passed = bool(
        valid_shape
        and payload.get('schema_migrated') is True
        and payload.get('source_not_before_satisfied') is True
        and payload.get('bounded_market_data_daily') is True
        and payload.get('publication_current') is True)
    evidence = {
        'exit_code': int(completed.returncode),
        'schema_migrated': bool(valid_shape and payload.get('schema_migrated')),
        'bounded_market_data_daily': bool(
            valid_shape and payload.get('bounded_market_data_daily')),
        'source_not_before_satisfied': bool(
            valid_shape and payload.get('source_not_before_satisfied')),
        'following_open_future': bool(
            valid_shape and payload.get('following_open_future')),
        'publication_current': bool(
            valid_shape and payload.get('publication_current')),
        'following_open_is_session_authority_only': True,
        'feed_authority_delegated_to_verified_runner': True,
        'paper_account_identity_removed': 'SENTINEL_PAPER_ACCOUNT_ID' not in run_env,
        'market_data_credentials_present': all(
            run_env.get(key) for key in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY')),
    }
    schema_attempted, daily_attempted = go.preparation_attempts(
        completed, schema_migrated=evidence['schema_migrated'],
        daily_completed=evidence['bounded_market_data_daily'])
    evidence.update(schema_migration_attempted=schema_attempted,
                    bounded_market_data_daily_attempted=daily_attempted)
    return go.PreparationSummary(
        status=go.PASS if passed else go.FAIL,
        runtime_image_digest=runtime_ref,
        schema_migration_attempted=schema_attempted,
        bounded_market_data_daily_attempted=daily_attempted,
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
