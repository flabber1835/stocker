"""Single-use, real-clock timing evidence from an isolated exact PAPER image.

Run this file outside /app, in the declared image and an owned network-isolated
PG16 namespace. It never loads .env, copies a database, changes a clock/calendar,
or substitutes an execution verifier. A host must independently authenticate the
Docker image/resource/isolation facts; this report alone is not a live certificate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
import uuid

UTC = timezone.utc
SCHEMA = 'sentinel.real-clock-timing-campaign/1'
REPORT_SCHEMA = 'sentinel.real-clock-timing-report/1'
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
CAMPAIGN = re.compile(r'[0-9a-f]{32}\Z')
SYSTEM = re.compile(r'[1-9][0-9]{0,19}\Z')
ASSETS = 5200
SESSIONS = 426
CPU = 1
MEMORY = 2 * 1024 ** 3
FIRST_POST_SECONDS = 120
COMPLETE_SECONDS = 300
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_DEPTH = 64


class TimingRefused(RuntimeError):
    """Bounded public refusal; never include a DSN, credentials or raw driver error."""


def require(condition, code):
    if not condition:
        raise TimingRefused(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def instant(value):
    require(isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None, 'AWARE_ORIGINAL_CLOCK_REQUIRED')
    return value.astimezone(UTC)


def write_new(path, value, *, private=False):
    """O_EXCL plus file/directory fsync; existing evidence is never replaced."""
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600 if private else 0o644)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        parent = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def read_object(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'REGULAR_CAMPAIGN_FILE_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    require(len(raw) <= MAX_DOCUMENT_BYTES, 'DOCUMENT_SIZE_LIMIT_EXCEEDED')
    # Bound nesting before invoking Python's recursive JSON decoder. Brackets
    # in quoted/escaped strings do not contribute to structural depth.
    depth, quoted, escaped = 0, False, False
    for value in raw:
        if quoted:
            if escaped:
                escaped = False
            elif value == 92:
                escaped = True
            elif value == 34:
                quoted = False
        elif value == 34:
            quoted = True
        elif value in (91, 123):
            depth += 1
            require(depth <= MAX_DOCUMENT_DEPTH, 'DOCUMENT_DEPTH_LIMIT_EXCEEDED')
        elif value in (93, 125):
            depth -= 1
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'DUPLICATE_DOCUMENT_KEY')
            result[key] = value
        return result
    def nonfinite(_value):
        raise TimingRefused('NONFINITE_DOCUMENT')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise TimingRefused('INVALID_JSON_DOCUMENT') from exc
    require(type(value) is dict and raw == canonical(value) + b'\n', 'CANONICAL_DOCUMENT_REQUIRED')
    return value


def require_database_address(database, campaign_id):
    require(type(campaign_id) is str and CAMPAIGN.fullmatch(campaign_id), 'PRIVATE_CAMPAIGN_ID_REQUIRED')
    expected = 'postgresql://postgres@127.0.0.1:5432/opening_latency_' + campaign_id
    require(type(database) is str and database == expected, 'EXACT_PRIVATE_LOOPBACK_DATABASE_REQUIRED')
    parsed = urlsplit(database)
    require(parsed.password is None and not parsed.query and not parsed.fragment,
            'PRIVATE_DATABASE_OPTIONS_FORBIDDEN')
    return 'opening_latency_' + campaign_id


def require_environment(values=None, *, sentinel_file=None, cgroup=Path('/sys/fs/cgroup')):
    values = os.environ if values is None else values
    for key, value in values.items():
        require(not value or not (key.startswith(('ALPACA_', 'OPENFIGI_', 'SHARADAR_', 'NDL_'))
                or key in {'REHEARSAL_PRODUCTION_DATABASE_URL', 'SENTINEL_PAPER_DEBUG_WINDOW'}),
                'PROVIDER_CREDENTIAL_OR_DEBUG_ENVIRONMENT_FORBIDDEN')
    if sentinel_file is None:
        import sentinel
        sentinel_file = sentinel.__file__
    require(Path(sentinel_file).resolve().parent == Path('/app/sentinel'), 'EXACT_IMAGE_RUNTIME_IMPORT_REQUIRED')
    # Qualification never changes these files or production resource settings.
    quota, period = (cgroup / 'cpu.max').read_text().strip().split()
    memory = (cgroup / 'memory.max').read_text().strip()
    require(quota != 'max' and int(quota) == CPU * int(period)
            and memory == str(MEMORY), 'ONE_CPU_TWO_GIB_RESOURCE_ENVELOPE_REQUIRED')
    return {'cpu_quota': int(quota), 'cpu_period': int(period), 'memory_limit_bytes': int(memory)}


def scheduler_document(path):
    """Bind a supplied actual profile; do not assume an old lease configuration."""
    from sentinel.automation.model import AutomationConfig
    value = read_object(path)
    require(set(value) == {'schema', 'scheduler', 'config_sha256'}
            and value['schema'] == 'sentinel.attended-scheduler-profile/1', 'SCHEDULER_DOCUMENT_REQUIRED')
    config = AutomationConfig.model_validate(value['scheduler'])
    require(value['config_sha256'] == config.fingerprint, 'SCHEDULER_FINGERPRINT_MISMATCH')
    require(config.paper_debug_window is None and config.execution_delay_seconds == 60
            and config.maximum_execution_lateness_seconds == 540, 'ORDINARY_OPENING_POLICY_REQUIRED')
    return value, config


class OriginalExecuteClock:
    """One monotonic origin anchored to the real scheduled EXECUTE instant.

    Construction is before PREPARE. Late process entry retains the elapsed
    delay from the original due-time. No callback/retry can reset the origin.
    """
    def __init__(self, execute_at, *, now, monotonic=time.monotonic):
        self.execute_at = instant(execute_at)
        self.observed_at = instant(now)
        delay = (self.observed_at - self.execute_at).total_seconds()
        require(delay >= 0, 'ORIGINAL_EXECUTE_NOT_YET_DUE')
        self._clock = monotonic
        sampled = monotonic()
        require(math.isfinite(sampled), 'MONOTONIC_CLOCK_INVALID')
        self.started = sampled - delay
        self._last = sampled

    def elapsed(self):
        value = self._clock()
        require(math.isfinite(value) and value >= self._last, 'MONOTONIC_CLOCK_REGRESSED')
        self._last = value
        return value - self.started

    def check(self, first_post=None, *, complete=False):
        elapsed = self.elapsed()
        require(elapsed <= COMPLETE_SECONDS, 'COMPLETE_BASKET_DEADLINE_EXCEEDED')
        if first_post is None:
            require(not complete and elapsed <= FIRST_POST_SECONDS, 'FIRST_POST_DEADLINE_EXCEEDED')
        else:
            require(type(first_post) in {int, float} and math.isfinite(first_post)
                    and 0 <= first_post <= min(FIRST_POST_SECONDS, elapsed), 'FIRST_POST_DEADLINE_EXCEEDED')
        return elapsed


def run_original_clock(execute_at, *, provider, prepare, execute_recover,
                       verify_commit, record_origin, now=None, monotonic=None):
    """The gateway's measured orchestration, with bounded test-only clock inputs.

    The CLI supplies neither clock seam. Every callback and the final positive
    verification/durable commit use the one original origin; failure propagates.
    """
    clock = OriginalExecuteClock(execute_at,
        now=datetime.now(UTC) if now is None else now(),
        monotonic=time.monotonic if monotonic is None else monotonic)
    provider.started = clock.started
    record_origin(clock)
    clock.check()
    prepared = prepare()
    clock.check(provider.first_order_seconds)
    outcome = execute_recover(prepared)
    clock.check(provider.first_order_seconds)
    verified = verify_commit(outcome)
    elapsed = clock.check(provider.first_order_seconds, complete=True)
    return verified, elapsed


def market_status(decision_session, config, *, now):
    """Use the actual calendar/date; Saturday is explicitly not a gateway PASS."""
    from sentinel.automation import schedule
    from sentinel.feed import calendar, operational_snapshot
    now = instant(now)
    timing = schedule.for_decision_session(decision_session, config)
    actual_day = now.astimezone(__import__('zoneinfo').ZoneInfo(calendar.EXCHANGE_TZ)).date()
    source = str(operational_snapshot.source_final_session(now))
    # A same-day campaign may arm up to ten minutes before the original due
    # instant. This permits genuine issuer/preflight setup before the measured
    # cold PREPARE without moving an exchange window or any clock.
    eligible = (timing.effective_session == actual_day and source == str(decision_session)
                and timing.execute_at - timedelta(seconds=600) <= now < min(timing.execution_close_at,
                    timing.execute_at + timedelta(seconds=config.maximum_execution_lateness_seconds)))
    return {'status': 'ELIGIBLE_REAL_SESSION' if eligible else 'BLOCKED_MARKET_SESSION',
            'observed_at': now.isoformat(), 'decision_session': str(decision_session),
            'effective_session': str(timing.effective_session), 'actual_source_frontier': source,
            'original_execute_at': timing.execute_at.isoformat(),
            'execution_close_at': timing.execution_close_at.isoformat()}, timing


def bundle_identity():
    """Name every external diagnostic/issuer/transport byte used by this driver."""
    modules = [sys.modules[__name__]]
    for name in ('tools.opening_gateway_qualification', 'tools.opening_latency_qualification',
                 'tests.support.current_workflow_authority', 'tests.support.current_workflow_transport',
                 'tests.support.live_timing_campaign'):
        modules.append(importlib.import_module(name))
    return {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules}


def connect(args, *, read_only=False, heartbeat=False):
    """Validate loopback address before opening it, physical identity immediately."""
    import psycopg
    name = require_database_address(args.database, args.campaign_id)
    require(SYSTEM.fullmatch(args.expected_system_id or '') and SYSTEM.fullmatch(args.production_system_id or '')
            and args.expected_system_id != args.production_system_id, 'DISTINCT_PHYSICAL_PRIVATE_DATABASE_REQUIRED')
    milliseconds = 3000 if heartbeat else 120000
    conn = psycopg.connect(args.database, connect_timeout=3,
        options=f'-c default_transaction_read_only={"on" if read_only else "off"} '
                f'-c statement_timeout={milliseconds} -c lock_timeout=1000 '
                f'-c idle_in_transaction_session_timeout={milliseconds}')
    try:
        row = conn.execute('SELECT current_database(),system_identifier::text,host(inet_server_addr()),'
                           'inet_server_port(),current_setting(\'transaction_read_only\') '
                           'FROM pg_control_system()').fetchone()
        require(tuple(row) == (name, args.expected_system_id, '127.0.0.1', 5432, 'on' if read_only else 'off'),
                'PHYSICAL_PRIVATE_DATABASE_IDENTITY_CHANGED')
        conn.rollback()
        return conn
    except BaseException:
        conn.close()
        raise


def _identity():
    from sentinel import identity
    value = identity.rehearsal_identity()
    require(value['certification']['certified'], 'CURRENT_RUNTIME_IDENTITY_NOT_CERTIFIED')
    return value


def _environment(args, *, context=None):
    from sentinel import identity, local_paper
    require(COMMIT.fullmatch(args.commit or '') and DIGEST.fullmatch(args.runtime_image_digest or ''),
            'EXACT_IMAGE_AND_COMMIT_REQUIRED')
    require(os.environ.get('SENTINEL_IMAGE_SOURCE_REVISION') == args.commit, 'BAKED_RUNTIME_COMMIT_MISMATCH')
    values = {'SENTINEL_GIT_COMMIT': args.commit, 'SENTINEL_RUNTIME_IMAGE_DIGEST': args.runtime_image_digest,
        'SENTINEL_TEST_IMAGE_DIGEST': args.runtime_image_digest, 'SENTINEL_FEED_GIT_COMMIT': args.commit,
        'SENTINEL_FEED_RUNTIME_IMAGE_DIGEST': args.runtime_image_digest,
        'SENTINEL_FEED_AUTHORIZED': identity.FEED_AUTHORIZATION_VALUE,
        local_paper.MODE_ENV: local_paper.MODE, local_paper.ACCOUNT_ENV: 'PAQUAL' + args.campaign_id,
        'SENTINEL_REVIEWED_DEPLOYMENT_MODE': 'dual', 'SENTINEL_SHADOW_OBSERVATION_ENABLED': '0',
        'SENTINEL_SHADOW_OBSERVATION_ID': args.observation_id, 'SENTINEL_SHADOW_STARTING_CASH': '50000',
        'SENTINEL_DATABASE_URL': args.database, 'SENTINEL_STATE_DIR': str(args.campaign_dir / 'state'),
        'SENTINEL_PAPER_BUY_POLICY': 'PROTECTED_LIMIT_DAY_V1', 'SENTINEL_PAPER_BUY_CAP_BPS': '100'}
    values.update(SENTINEL_AUTHORIZED_RUNTIME='SIGNED_DIGEST_SERVICE_V1',
        SENTINEL_RUNTIME_BACKUP_AUTHORITY='REQUIRED_V1', SENTINEL_RECOVERED_ORDER_AUTHORITY='STRICT_V1')
    if context is not None:
        require(set(context) == {'environment'}, 'PRIVATE_CONTEXT_SHAPE_INVALID')
        require(set(context['environment']) == {'SENTINEL_PUBLICATION_RECEIPT_KEY',
            'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', 'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256',
            'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256'}, 'PRIVATE_CONTEXT_KEYS_INVALID')
        values.update(context['environment'])
    return patch.dict(os.environ, values)


class _FixtureScope:
    """Small adapter for the existing external issuer; only its inputs are replaced."""
    def __init__(self, stack):
        self.stack = stack

    def setenv(self, name, value):
        self.stack.enter_context(patch.dict(os.environ, {name: str(value)}))

    def setattr(self, owner, name, value):
        self.stack.enter_context(patch.object(owner, name, value))


def prepare(args, config, scheduler, resources):
    """Generate source through canonical publication/formation, without execution."""
    from sentinel import binding, identity, mirror_projection, operational_schema, schema, shadow_runtime
    from sentinel import rolling_initialization, rolling_runtime
    from sentinel.execution import journal
    from sentinel.feed import operational_snapshot, publisher_pipeline, store
    from sentinel.feed.alpaca_source import AlpacaSource
    from sentinel.feed.rolling_contract import digest as source_digest
    from sentinel.strategy import production_strategy
    from tests.support.live_timing_campaign import Source, Classifier
    require(not args.campaign_dir.exists(), 'FRESH_CAMPAIGN_DIRECTORY_REQUIRED')
    args.campaign_dir.mkdir(parents=True)
    write_new(args.campaign_dir / 'prepare-claim.json', {'campaign_id': args.campaign_id,
        'at': datetime.now(UTC).isoformat(), 'authority_effect': 'NONE'})
    started = time.monotonic()
    with _environment(args), connect(args) as conn, ExitStack() as stack:
        require(conn.execute("SELECT to_regclass('public.sentinel_account_binding')").fetchone()[0] is None,
                'EMPTY_PRIVATE_DATABASE_REQUIRED')
        conn.rollback()
        schema.ensure_schema(conn)
        store.migrate_schema(conn)
        binding.bind(conn, deployment_id='real-clock-' + args.campaign_id, broker='alpaca',
                     broker_account_id=os.environ['SENTINEL_LOCAL_PAPER_ACCOUNT_ID'])
        secret = secrets.token_urlsafe(48)
        stack.enter_context(patch.dict(os.environ, SENTINEL_PUBLICATION_RECEIPT_KEY=secret))
        operational_schema.install_quiescent(conn)
        for step in (lambda: journal.bootstrap_observation_integrity(conn, limit=64),
                     lambda: mirror_projection.bootstrap_step(conn, limit=64)):
            for _ in range(100):
                progress = step()
                conn.commit()
                if progress['body']['stage'] == 'COMPLETE':
                    break
            else:
                raise TimingRefused('BOUNDED_PRIVATE_BOOTSTRAP_INCOMPLETE')
        actual = _identity()
        source_identity = actual['identity_hash']
        reviewed = {'schema': 'sentinel.shadow-reviewed-config/1', 'observation_id': args.observation_id,
            'starting_cash': '50000', 'execution_model': shadow_runtime.SHADOW_EXECUTION_MODEL,
            'cutoff_policy': shadow_runtime.SHADOW_CUTOFF_POLICY,
            'publication_timing_policy': shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,
            'validated_source_identity_sha256': source_identity}
        extra = {'SENTINEL_PUBLICATION_RECEIPT_KEY': secret,
                 'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256': source_identity,
                 'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256': digest(reviewed)}
        stack.enter_context(patch.dict(os.environ, extra))
        frontier = str(operational_snapshot.source_final_session(datetime.now(UTC)))
        source = Source(frontier, assets=args.assets)
        classifier = Classifier()
        stack.enter_context(patch.object(publisher_pipeline, '_operational_source',
            lambda window, owner, lease, **kw: AlpacaSource(window, owner, lease, client=source,
                classifier=classifier, verify_during_coverage=kw['verify_during_coverage'])))
        _, strategy = production_strategy()
        job = operational_snapshot.enqueue(conn, strategy_sha256=source_digest(strategy),
            dependencies_sha256=source_digest({'private_generator': source.description}),
            budget_seconds=args.setup_budget_seconds)
        conn.commit()
        publication = operational_snapshot.prepare(conn, job)
        with operational_snapshot.pinned(conn) as (published, _bound):
            subject = shadow_runtime._data_publication_subject_sha256(published, published.window_end)
        conn.rollback()
        extra['SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256'] = subject
        stack.enter_context(patch.dict(os.environ, {'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256': subject}))
        formed = rolling_initialization.initialize(conn, observation_id=args.observation_id, starting_cash=Decimal('50000'))
        restored = rolling_initialization.resume(conn, observation_id=args.observation_id, starting_cash=Decimal('50000'))
        require(restored.state.state_hash == formed.state.state_hash, 'CANONICAL_RESTART_CHANGED_BOOK')
        attested = rolling_runtime.advance(conn, through=frontier, observation_id=args.observation_id,
                                          starting_cash=Decimal('50000'))
        require(attested.verification == 'VERIFIED' and attested.state.state_hash == formed.state.state_hash,
                'CANONICAL_ATTESTATION_CHANGED_BOOK')
        from sentinel.feed import rolling_store
        manifest = rolling_store.manifest(conn, publication['candidate_id'])
        require(manifest.bar_count == args.assets * SESSIONS and len(manifest.window.sessions) == SESSIONS,
                'GENERATED_RETAINED_SHAPE_MISMATCH')
        conn.rollback()
        subject_runtime = _identity()
        campaign = {'schema': SCHEMA, 'campaign_id': args.campaign_id, 'created_at': datetime.now(UTC).isoformat(),
            'commit': args.commit, 'runtime_image_digest': args.runtime_image_digest,
            'private_system_id': args.expected_system_id, 'production_system_id': args.production_system_id,
            'database': require_database_address(args.database, args.campaign_id), 'observation_id': args.observation_id,
            'scheduler': scheduler, 'resources': resources, 'generator': source.description,
            'source_frontier': frontier, 'publication': publication, 'book_sha256': formed.state.state_hash,
            'runtime_identity_sha256': subject_runtime['identity_hash'], 'strategy_sha256': digest(strategy),
            'runtime_source_sha256': subject_runtime['environment']['sentinel_source']['hash'],
            'wealth_core_source_sha256': subject_runtime['environment']['wealth_core_source']['hash'],
            'environment_sha256': digest(extra), 'bundle': bundle_identity(),
            'setup_seconds': round(time.monotonic() - started, 6), 'authority_effect': 'NONE',
            'history_coverage': {'source_publications': 1, 'historical_formation_transitions': 126,
                'native_orders': 0, 'native_observations': 0,
                'limitation': 'does not reproduce prior production publication or broker-journal history'}}
        write_new(args.campaign_dir / 'private-context.json', {'environment': extra}, private=True)
        write_new(args.campaign_dir / 'campaign.json', campaign)
        state, _ = market_status(frontier, config, now=datetime.now(UTC))
        return {'result': 'PREPARED', 'gateway_status': state, 'campaign_sha256': digest(campaign),
                'setup_seconds': campaign['setup_seconds'], 'bar_count': manifest.bar_count,
                'authority_effect': 'NONE', 'gateway_qualified': False}


def load_campaign(args, scheduler, resources):
    value = read_object(args.campaign_dir / 'campaign.json')
    context = read_object(args.campaign_dir / 'private-context.json')
    require(type(args.campaign_sha256) is str and re.fullmatch('[0-9a-f]{64}', args.campaign_sha256)
            and digest(value) == args.campaign_sha256, 'EXTERNAL_CAMPAIGN_SEAL_MISMATCH')
    require(value.get('schema') == SCHEMA and value.get('campaign_id') == args.campaign_id
            and value.get('commit') == args.commit and value.get('runtime_image_digest') == args.runtime_image_digest
            and value.get('private_system_id') == args.expected_system_id
            and value.get('production_system_id') == args.production_system_id
            and value.get('database') == require_database_address(args.database, args.campaign_id)
            and value.get('observation_id') == args.observation_id and value.get('scheduler') == scheduler
            and value.get('resources') == resources and value.get('bundle') == bundle_identity()
            and value.get('environment_sha256') == digest(context.get('environment')), 'CAMPAIGN_SUBJECT_CHANGED')
    return value, context


def cold(args, campaign):
    from sentinel import dual_reconciliation, rolling_checkpoint, shadow_runtime
    with connect(args, read_only=True) as conn:
        origin = rolling_checkpoint.read(conn)
        require(origin is not None and origin.state_sha256 == campaign['book_sha256'], 'SEALED_BOOK_CHANGED')
        started = time.monotonic()
        result = shadow_runtime.verified_shadow_status(conn, observation_id=args.observation_id, starting_cash=Decimal('50000'))
        status_seconds = time.monotonic() - started
        started = time.monotonic()
        intent = dual_reconciliation.verified_shadow_intent(conn, decision_session=date.fromisoformat(campaign['source_frontier']),
            observation_id=args.observation_id, starting_cash=Decimal('50000'))
        intent_seconds = time.monotonic() - started
        require(result is not None and intent is not None, 'COLD_VERIFICATION_INCOMPLETE')
        require(rolling_checkpoint.read(conn) == origin, 'COLD_READ_CHANGED_BOOK')
        return {'result': 'DIAGNOSTIC_ONLY', 'verified_status_seconds': round(status_seconds, 6),
                'verified_intent_seconds': round(intent_seconds, 6), 'gateway_qualified': False,
                'native_broker_calls': 0, 'authority_effect': 'NONE'}


def _gateway_args(args):
    # Existing supervisor/cleanup helpers independently enforce private target
    # identity before every heartbeat or cleanup connection.
    return SimpleNamespace(database=args.database, expected_database=require_database_address(args.database, args.campaign_id),
        expected_system_id=args.expected_system_id, production_system_id=args.production_system_id,
        runtime_image_digest=args.runtime_image_digest, private_rehearsal=True, mutate_private_rehearsal=True,
        repetitions=1, minimum_bars=ASSETS * SESSIONS)


@contextmanager
def _fenced_private_campaign(args):
    """Cleanup covers issuer, activation and lease failures as well as callbacks."""
    from tools import opening_gateway_qualification as existing
    try:
        yield
    finally:
        existing.cleanup_private(args, preserve_failure=sys.exc_info()[0] is not None)


def gateway(args, campaign, config, timing):
    from sentinel import automation_runtime, binding, rolling_checkpoint
    from sentinel.automation import store
    from sentinel.automation.model import ControlBinding, CycleContext, CycleSpec, CycleState
    from sentinel.authority import load_rollout_state
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
    from sentinel.execution import journal, target_reprojection
    from tests.support.current_workflow_authority import issue_current_paper_authority
    from tests.support.live_timing_campaign import assets_for_publication
    from tests.support.current_workflow_transport import NativeWorkflowAlpaca
    from tools import opening_gateway_qualification as existing
    private_args = _gateway_args(args)
    counts = Counter()
    setup_started = time.monotonic()
    with connect(args) as conn, ExitStack() as stack, _fenced_private_campaign(private_args):
        control = store.load_control(conn)
        require(not control.enabled and control.kill_switch_engaged, 'PRIVATE_CAMPAIGN_MUST_START_FENCED')
        require(conn.execute('SELECT (SELECT count(*) FROM sentinel_commands),'
                             '(SELECT count(*) FROM sentinel_automation_cycles),'
                             '(SELECT count(*) FROM sentinel_execution_plans)').fetchone() == (0, 0, 0),
                'UNCONSUMED_PRIVATE_FINANCIAL_NAMESPACE_REQUIRED')
        origin = rolling_checkpoint.read(conn)
        require(origin is not None and origin.state_sha256 == campaign['book_sha256'], 'SEALED_BOOK_CHANGED')
        conn.rollback()
        controller, strategy = __import__('sentinel.strategy', fromlist=['production_strategy']).production_strategy()
        scope = _FixtureScope(stack)
        certificate = issue_current_paper_authority(conn, scope, args.campaign_dir,
            now=datetime.now(UTC), observation_id=args.observation_id, controller=controller,
            strategy=strategy, automation_config_sha256=config.fingerprint)
        bound, rollout = binding.require(conn), load_rollout_state(conn)
        assets = assets_for_publication(conn, campaign['publication'])
        http = NativeWorkflowAlpaca(account=bound.broker_account_id, cash='50000', assets=assets,
            window=lambda: (timing.execution_open_at, timing.execution_close_at),
            forbid_quotes=True, marketable_limit_fills=True)
        class Campaign(automation_runtime.ProductionAutomation):
            def _broker(self, reader, session):
                broker = super()._broker(reader, session)
                broker._http_provider = lambda: http
                return broker
        runtime = Campaign(sentinel_config=SentinelConfig(database_url=args.database, alpaca_key='isolated',
            alpaca_secret='no-network', base_url=DEFAULT_BASE_URL, state_dir=args.campaign_dir / 'state',
            max_cycles=1, poll_seconds=0), automation_config=config, holder_id='timing-' + args.campaign_id)
        runtime._shadow_observation_id, runtime._shadow_starting_cash = args.observation_id, '50000'
        active = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
            broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
            certificate_sha256=certificate, rollout_mode=rollout.mode.value,
            rollout_version=rollout.version, config_sha256=config.fingerprint)
        store.activate(conn, binding=active, actor='PRIVATE_TIMING', reason='isolated exact-image timing only')
        store.release_kill(conn, expected_binding=active, actor='PRIVATE_TIMING', reason='local transport only')
        permit = store.acquire_lease(conn, holder_id=runtime.holder_id, lease_seconds=config.lease_seconds)
        cycle = store.create_cycle(conn, permit=permit, spec=CycleSpec(**timing.model_dump(), **active.model_dump(),
            control_generation=permit.control_generation), now=datetime.now(UTC), config=config)
        conn.rollback()
        stages = []
        def transition(state, **fields):
            return existing.transition_for_callback(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=state, **fields)
        def callback(phase, name, body, *, current_cycle=None):
            context = CycleContext(cycle=cycle if current_cycle is None else current_cycle, permit=permit)
            started = time.monotonic()
            try:
                return existing.supervised_callback(private_args, config, context, phase, body, http, counts)
            finally:
                stages.append({'phase': name, 'seconds': round(time.monotonic() - started, 6)})
        try:
            preflight = callback('RECOVER', 'PREFLIGHT_RECOVER', runtime.recover)
            existing.require_callback_progress(preflight, phase='PREFLIGHT')
            cycle = transition(CycleState.REFRESHING_DATA)
            # The existing generic IPC helper returns ExecuteResult for every
            # non-PREPARE callback; use real source preflight without miscasting
            # RefreshResult. No publication or verification scope crosses PREPARE.
            cycle = transition(CycleState.PREPARING)
            setup_seconds = time.monotonic() - setup_started
            wait_started = time.monotonic()
            while datetime.now(UTC) < timing.execute_at:
                remaining = (timing.execute_at - datetime.now(UTC)).total_seconds()
                require(remaining <= 600, 'BOUNDED_ORIGINAL_OPEN_WAIT_REQUIRED')
                with connect(args, heartbeat=True) as heartbeat:
                    store.heartbeat_lease(heartbeat, permit=permit, lease_seconds=config.lease_seconds)
                time.sleep(min(1, max(0, remaining)))
            wait_seconds = time.monotonic() - wait_started
            def record_origin(clock):
                write_new(args.campaign_dir / 'original-execute-clock.json', {
                    'campaign_sha256': digest(campaign), 'execute_at': timing.execute_at.isoformat(),
                    'observed_at': clock.observed_at.isoformat(), 'monotonic_origin': clock.started,
                    'includes': ['PREPARE', 'EXECUTE', 'ALL_RECOVER', 'POSITIVE_BASKET', 'DURABLE_SUCCEEDED']})
            def prepare_at_origin():
                return callback('PREPARE', 'PREPARE', runtime.prepare)
            def execute_recover(prepared):
                nonlocal cycle
                cycle = transition(CycleState.PLAN_READY, plan_id=prepared.plan_id,
                    plan_fingerprint=prepared.plan_fingerprint, state_fingerprint=prepared.state_fingerprint,
                    data_version=prepared.data_version, publication_fingerprint=prepared.publication_fingerprint)
                cycle = transition(CycleState.WAITING_OPEN)
                cycle = transition(CycleState.EXECUTING)
                cycle, recovered, passes = existing.execute_to_completion(conn=conn, permit=permit, cycle=cycle,
                    deployment=bound.identity, plan_id=prepared.plan_id, asset_count=len(assets), callback=callback,
                    execute=runtime.execute, recover=runtime.recover, http=http,
                    maximum_lateness=config.maximum_execution_lateness_seconds)
                return prepared, recovered, passes
            def verify_commit(outcome):
                nonlocal cycle
                prepared, recovered, passes = outcome
                projection = target_reprojection.load_projection(conn, plan_id=prepared.plan_id)
                require(projection is not None, 'DURABLE_TARGET_PROJECTION_REQUIRED')
                expected = {sid: qty for sid, qty in projection.target_basket.items() if qty}
                actual = {http.by_id[sid]['security_id']: qty for sid, qty in http.positions.items() if qty}
                commands = journal.load_commands(conn, bound.identity, plan_id=prepared.plan_id)
                require(expected and actual == expected and recovered.disposition.value == 'SUCCEEDED'
                        and recovered.last_clean_reconciliation_id and commands and len(commands) == len(http.orders)
                        and all(command.state.value == 'FILLED' for command in commands), 'EXACT_POSITIVELY_RECOVERED_BASKET_REQUIRED')
                require(rolling_checkpoint.read(conn) == origin, 'TIMED_GATEWAY_CHANGED_CANONICAL_BOOK')
                existing.require_no_quotes(http)
                cycle = transition(CycleState.SUCCEEDED, last_clean_reconciliation_id=recovered.last_clean_reconciliation_id)
                return {'passes': passes, 'legs': len(expected)}
            verified, elapsed = run_original_clock(timing.execute_at, provider=http,
                prepare=prepare_at_origin, execute_recover=execute_recover,
                verify_commit=verify_commit, record_origin=record_origin)
            return {'result': 'PASS', 'gateway_qualified': True, 'first_post_seconds': http.first_order_seconds,
                'complete_basket_seconds': round(elapsed, 6), 'orders': len(http.orders), 'legs': verified['legs'],
                'execution_passes': verified['passes'], 'stages': stages, 'original_execute_at': timing.execute_at.isoformat(),
                'pre_execute_setup_seconds': round(setup_seconds, 6),
                'pre_execute_wait_seconds': round(wait_seconds, 6),
                'book_preserved': True, 'callbacks': 'UNCHANGED AutomationService._invoke + ProductionAutomation',
                'substitutions': ['generated external source', 'disposable signed PAPER issuer root',
                                  'native-shaped local broker transport'],
                'native_broker_calls': 0, 'authority_effect': 'NONE', 'live_money_qualified': False}
        finally:
            # The outer guard covers every stage, including activation errors.
            # Retain partial callback diagnostics even when the SLA refuses.
            print(canonical({'stage': 'REAL_CLOCK_CALLBACK_STAGES', 'stages': stages,
                'provider_response_latency': 'IMMEDIATE_LOCAL_TRANSPORT; NATIVE_LATENCY_UNMEASURED'}).decode('ascii'), flush=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('mode', choices=('prepare', 'status', 'cold', 'gateway'))
    result.add_argument('--campaign-dir', type=Path, required=True)
    result.add_argument('--campaign-id', required=True)
    result.add_argument('--campaign-sha256', help='original host-retained prepare report seal; required after prepare')
    result.add_argument('--database', required=True)
    result.add_argument('--expected-system-id', required=True)
    result.add_argument('--production-system-id', required=True)
    result.add_argument('--runtime-image-digest', required=True)
    result.add_argument('--commit', required=True)
    result.add_argument('--scheduler-profile', type=Path, required=True)
    result.add_argument('--assets', type=int, default=ASSETS)
    result.add_argument('--setup-budget-seconds', type=int, default=3600)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    require_database_address(args.database, args.campaign_id)
    require(ASSETS <= args.assets <= 10000 and 600 <= args.setup_budget_seconds <= 7200,
            'GENERATED_SOURCE_SHAPE_OR_SETUP_BUDGET_INVALID')
    args.observation_id = 'real-clock-' + args.campaign_id
    resources = require_environment()
    scheduler, config = scheduler_document(args.scheduler_profile)
    report = {'schema': REPORT_SCHEMA, 'mode': args.mode, 'campaign_id': args.campaign_id,
              'at': datetime.now(UTC).isoformat(), 'result': 'REFUSED', 'authority_effect': 'NONE',
              'gateway_qualified': False, 'live_money_qualified': False,
              'production_opening_qualified': False,
              'qualification_scope': 'GENERATED_CURRENT_PROFILE_REAL_CLOCK_SOFTWARE_GATEWAY',
              'host_image_and_isolation_verification_required': True}
    report_path = args.campaign_dir / (args.mode + '-report.json')
    if args.mode != 'status' and report_path.exists():
        report['failure_code'] = 'ORIGINAL_REPORT_ALREADY_EXISTS'
        print(canonical(report).decode('ascii'), flush=True)
        return 1
    persist = args.mode != 'status'
    try:
        if args.mode == 'prepare':
            report.update(prepare(args, config, scheduler, resources))
        else:
            campaign, context = load_campaign(args, scheduler, resources)
            report['campaign_sha256'] = digest(campaign)
            with _environment(args, context=context):
                require(_identity()['identity_hash'] == campaign['runtime_identity_sha256'], 'SEALED_RUNTIME_IDENTITY_CHANGED')
                state, timing = market_status(campaign['source_frontier'], config, now=datetime.now(UTC))
                report['market'] = state
                if args.mode == 'status':
                    report['result'] = state['status']
                    # Status is read-only and may be repeated; it consumes no
                    # financial campaign and creates no claim or status file.
                    return 0
                write_new(args.campaign_dir / (args.mode + '-claim.json'), {
                    'campaign_sha256': digest(campaign), 'at': datetime.now(UTC).isoformat(), 'mode': args.mode})
                if args.mode == 'cold':
                    report.update(cold(args, campaign))
                elif state['status'] != 'ELIGIBLE_REAL_SESSION':
                    report['result'] = 'BLOCKED_MARKET_SESSION'
                else:
                    with patch.dict(os.environ, SENTINEL_FEED_SERVICE_MODE='AUTOMATION'):
                        report.update(gateway(args, campaign, config, timing))
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
        if isinstance(exc, TimingRefused):
            report['failure_code'] = str(exc)
    finally:
        # Prepare can refuse before it creates the campaign directory. Avoid
        # creating/replacing caller-selected paths merely to report that error.
        if persist and args.campaign_dir.is_dir() and not args.campaign_dir.is_symlink():
            write_new(report_path, report)
        print(canonical(report).decode('ascii'), flush=True)
    return 0 if report['result'] in {'PREPARED', 'DIAGNOSTIC_ONLY'} or report.get('gateway_qualified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
