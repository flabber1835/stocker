"""Run the idle scheduler through the next XNYS open on a new private database."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

import psycopg

from sentinel import automation_runtime, backup_runtime_authority, schema
from sentinel.automation import schedule, store
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.feed import calendar, publication, rolling_store
from sentinel.feed import store as feed_store
from sentinel.panel import model, sources
from tests.sentinel.test_automation_service import config, enable, execution_success, service_for
from tests.support.postgres import _EphemeralPostgres
from tools.opening_gateway_qualification import LocalAlpaca


def utcnow():
    return datetime.now(timezone.utc)


@contextmanager
def fixture_inputs():
    """Only fixture data, certificate and runtime identity replace external evidence."""
    def input_version(conn):
        rolling_store._pin_reader(conn)
        return SimpleNamespace(version=1)

    with ExitStack() as stack:
        cls = automation_runtime.ProductionAutomation
        mock = stack.enter_context
        mock(patch.object(backup_runtime_authority, 'POLICY_MARKER', Path('/nonexistent/idle-fixture')))
        mock(patch.object(automation_runtime.feed_inputs, 'require_current', input_version))
        mock(patch.object(automation_runtime, 'production_strategy', lambda: (None, {})))
        mock(patch.object(automation_runtime.system_identity, 'rehearsal_identity', lambda: {}))
        mock(patch.object(cls, '_idle_publication_head', lambda self, conn, **kwargs: {'version': 1}))
        mock(patch.object(cls, '_idle_certificate_identity',
                          lambda self, conn, expected_sha256: SimpleNamespace(certificate_sha256=expected_sha256)))
        mock(patch.object(automation_runtime, 'require_current_authority',
                          lambda conn, **kwargs: SimpleNamespace(certificate_sha256=store.load_control(conn).certificate_sha256)))
        yield


real_observer = automation_runtime._observe_idle_control_authority


def fixture_observer(*args):
    # Runs in the real isolated child with its own read-only PostgreSQL session.
    with fixture_inputs():
        return real_observer(*args)


class Trace:
    def __init__(self, output):
        self.output = output
        self.counts = Counter()
        self.max_age = 0
        self.last_proof = None
        self.fence = None

    def record(self, kind, **values):
        self.counts[kind] += 1
        self.output.write(json.dumps(dict(event=kind, at=utcnow(), **values), default=str) + '\n')
        self.output.flush()

    def panel(self, conn, market_now):
        control = store.load_control(conn)
        now, fence = conn.execute(
            'SELECT clock_timestamp(),fence_token FROM sentinel_automation_lease WHERE id=1').fetchone()
        conn.rollback()
        row = sources._execution_authority_display(
            dict(certificate_sha256=control.certificate_sha256, lifecycle_status='ACTIVE', lifecycle_current=True),
            dict(certificate_sha256=control.certificate_sha256), verdict=control.authority_verdict,
            detail=control.authority_detail, checked_at=control.authority_checked_at)
        self.observe(row, now, fence, market_now)

    def observe(self, row, now, fence, market_now):
        # The OLD row remained the only proof until its successor committed.
        # Compare at the actual commit timestamp even if no poll fell in the gap.
        if self.last_proof is not None:
            endpoint = row.as_of if self.last_proof.as_of != row.as_of and row.as_of else now
            prior_age = (endpoint - self.last_proof.as_of).total_seconds()
            self.max_age = max(self.max_age, prior_age)
            if prior_age < 0 or self.last_proof.effective_status(endpoint) != model.OK:
                self.record('expired', previous=self.last_proof.as_of, endpoint=endpoint)
                raise AssertionError('previous root expired before publication')
        status = row.effective_status(now)
        self.record('panel', market_time=market_now, status=status, proof_at=row.as_of, fence=fence)
        if self.last_proof is not None and (status != model.OK or fence != self.fence):
            raise AssertionError('panel lost current authority or lease continuity')
        if status == model.OK:
            if self.last_proof is None or self.last_proof.as_of != row.as_of:
                self.record('root_publication', proof_at=row.as_of)
            self.last_proof, self.fence = row, fence


async def campaign(dsn, duration, trace):
    cfg = config().model_copy(update={'heartbeat_seconds': 3, 'control_poll_seconds': 3})
    decision = calendar.latest_closed_session(utcnow())
    session = schedule.for_decision_session(decision, cfg)
    start = session.prepare_at
    end = session.execute_at + timedelta(seconds=1)
    duration = duration or (end - start).total_seconds()
    runtime = automation_runtime.ProductionAutomation(automation_config=cfg, holder_id='worker-a',
        sentinel_config=SentinelConfig(alpaca_key='', alpaca_secret='', base_url=DEFAULT_BASE_URL,
            state_dir=Path('.'), max_cycles=1, poll_seconds=0, database_url=dsn))

    # Keep callback counts durable across the production callback subprocess.
    async def execute(context):
        provider = LocalAlpaca(account='endurance', cash='1000', assets={}, window=lambda: (
            session.execution_open_at, session.execution_close_at))
        account = provider.get('https://paper-api.alpaca.markets/v2/account', {}).json()
        if account['account_number'] != 'endurance':
            raise AssertionError('unexpected simulated broker account')
        with psycopg.connect(dsn) as metrics:
            metrics.execute('INSERT INTO endurance_open_observation VALUES (%s,%s)',
                            (context.cycle.plan_id, provider.requests['GET /v2/account']))
        return execution_success(context)

    service = service_for(cfg, execute=execute)
    service.before_callback = runtime._stop_idle_authority_observer
    stop = asyncio.Event()
    with feed_store.connect(dsn) as admin, psycopg.connect(dsn, autocommit=True) as writer:
        schema.ensure_schema(admin)
        admin.execute('CREATE TABLE endurance_open_observation(plan_id text PRIMARY KEY, broker_reads int)')
        admin.commit()
        enable(admin, cfg)
        for _ in range(8):
            prepared = await service.tick(admin, now=start)
            if prepared.cycle is not None and prepared.cycle.state.value == 'WAITING_OPEN':
                break
        else:
            raise AssertionError('private cycle never reached waiting-open')
        began = time.monotonic()
        offset = start - utcnow()
        def market_now():
            return utcnow() + offset
        async def sleep(seconds):
            nonlocal offset
            await asyncio.sleep(seconds)
            fraction = min(1, (time.monotonic() - began) / duration)
            # Advance between polls. During each real clock-skew sample the
            # replay clock runs at wall speed with a fixed known offset.
            offset = start + (end - start) * fraction - utcnow()

        trace.record('start', decision=decision, market_start=start, market_end=end, wall_seconds=duration)
        last_seq = 0
        forced_contention = False
        async def wake(conn):
            nonlocal last_seq, forced_contention
            before = utcnow()
            trace.panel(conn, market_now())
            if trace.last_proof is None and time.monotonic() - began > (
                    automation_runtime._IDLE_AUTHORITY_OBSERVER_SECONDS + 2*cfg.control_poll_seconds):
                raise AssertionError('first authority root missed its initial observation budget')
            count = trace.counts['poll']
            # Once force an admission overlap at the original attestation
            # boundary, then shift the writer's phase across recurring polls.
            attested = runtime._idle_attestation
            force = (not forced_contention and attested is not None and
                     (before-attested[0]).total_seconds() >= automation_runtime._IDLE_ATTESTATION_SECONDS)
            held = force or (count > 2 and count % 5 == (count // 20) % 5)
            forced_contention |= force
            if held:
                writer.execute('SELECT pg_advisory_lock(%s)', (publication.CORPUS_LOCK_KEY,))
                trace.record('writer_hold')
            try:
                due = await runtime.bounded_control_wake(conn)
            finally:
                if held:
                    assert writer.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
            trace.panel(conn, market_now())
            events = conn.execute('SELECT seq,at,from_state,to_state FROM sentinel_automation_cycle_events '
                                  'WHERE seq>%s ORDER BY seq', (last_seq,)).fetchall()
            for seq, at, prior, state in events:
                trace.record('cycle_transition', seq=seq, committed_event_at=at, prior=prior, state=state)
                last_seq = seq
            cycle = store.latest_cycle(conn)
            conn.rollback()
            trace.record('poll', market_time=market_now(), cycle=cycle.state.value,
                         retry_at=runtime._idle_authority_retry_at, observer_active=runtime._idle_authority_flight is not None)
            if cycle.state.value == 'SUCCEEDED':
                stop.set()
            elif cycle.state.terminal or time.monotonic() - began > duration + 90:
                raise AssertionError(f'next-open cycle did not succeed: {cycle.state.value} {cycle.failure_code}')
            if due is not None:
                # Translate the actual retry delay into the scheduler's
                # replay clock without moving the underlying proof deadline.
                return market_now() + max(timedelta(0), due-utcnow())
            return None

        original = runtime._start_idle_authority_observer
        def observer(*args):
            trace.record('observer_start')
            return original(*args)

        try:
            with patch.object(runtime, '_start_idle_authority_observer', observer):
                await service.run(lambda: feed_store.connect(dsn), stop=stop, clock=market_now,
                                  sleep=sleep, control_wake=wake)
            callbacks, reads = admin.execute('SELECT count(*),sum(broker_reads) FROM endurance_open_observation').fetchone()
            if (callbacks, reads) != (1, 1) or not forced_contention or trace.counts['root_publication'] < 2:
                raise AssertionError('missing unique opening callback or contested root renewal')
            trace.record('complete', simulated_open_callbacks=callbacks, simulated_broker_reads=reads,
                         max_proof_age_seconds=trace.max_age,
                         counters=dict(trace.counts), elapsed_seconds=time.monotonic()-began)
        finally:
            runtime._stop_idle_authority_observer()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-seconds', type=int, default=0,
                        help='real soak duration; zero replays the full XNYS interval at wall speed')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.duration_seconds != 0 and not 90 <= args.duration_seconds <= 7*86400:
        parser.error('duration must be zero or between 90 seconds and seven days')
    if any(os.environ.get(key) for key in ('DATABASE_URL','SENTINEL_DATABASE_URL','APCA_API_KEY_ID',
                                           'APCA_API_SECRET_KEY','ALPACA_API_KEY','ALPACA_SECRET_KEY')):
        parser.error('campaign requires an isolated environment')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as out:
        trace = Trace(out)
        server = _EphemeralPostgres()
        try:
            server.start()
            with fixture_inputs(), patch.object(automation_runtime,'_observe_idle_control_authority',fixture_observer):
                asyncio.run(campaign(server.sync_dsn, args.duration_seconds, trace))
        except BaseException as exc:
            trace.record('failed', error=type(exc).__name__, max_proof_age_seconds=trace.max_age,
                         counters=dict(trace.counts))
            raise
        finally:
            server.stop()


if __name__ == '__main__':
    main()
