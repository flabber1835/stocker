"""Market-open proof reuse with real PostgreSQL and strict invalidation."""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from sentinel import schema, structural_verification as verified, shadow_supervisor
from sentinel.execution import journal, feed_inputs
from sentinel.panel import model, sources
from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES
from tests.sentinel.test_rolling_paper_inputs import (
    conn, pg, source, issuer_source, ready, operational_source, published, approve, gateway,
)


def test_only_economic_proofs_ignore_exact_broker_records(conn, published):
    schema.ensure_schema(conn)
    conn.commit()
    calls = {'rolling-checkpoint': 0, 'dual-sizing': 0, 'retained-runtime-checkpoint': 0,
             'unknown-proof': 0}

    def read(scope, slot):
        def load():
            calls[slot] += 1
            return {'value': [calls[slot]]}
        with psycopg.connect(conn.info.dsn) as fresh, scope.guard(fresh):
            return verified.material(fresh, slot=slot, key='current', load=load)

    with journal.writer_lock(conn), feed_inputs.pinned(conn, commit=False), verified.callback(conn) as scope:
        for slot in calls:
            read(scope, slot)['value'].clear()
        for name in (*PAPER_CURSOR_NAMES, *(prefix + 'test' for prefix in PAPER_CURSOR_PREFIXES)):
            conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                         "VALUES (%s,'2026-09-14','{}')", (name,))
            conn.commit()
            for slot in calls:
                before = calls[slot]
                expected = before + (slot == 'unknown-proof')
                assert read(scope, slot) == {'value': [expected]}
            conn.execute("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name=%s", (name,))
            conn.commit()
            for slot in calls:
                before = calls[slot]
                expected = before + (slot == 'unknown-proof')
                assert read(scope, slot) == {'value': [expected]}
            conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s", (name,))
            conn.commit()
            for slot in calls:
                before = calls[slot]
                expected = before + (slot == 'unknown-proof')
                assert read(scope, slot) == {'value': [expected]}
        assert calls['rolling-checkpoint'] == 1
        assert calls['dual-sizing'] == 1
        assert calls['retained-runtime-checkpoint'] == 1
        assert calls['unknown-proof'] == 1 + 3 * (len(PAPER_CURSOR_NAMES) + len(PAPER_CURSOR_PREFIXES))
        for name in ('unknown-economic:v1', 'dual-plan-sizing-authority:v1:test', 'rolling-daily-input:v1:test'):
            conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                         "VALUES (%s,'2026-09-14','{}')", (name,))
            conn.commit()
            for slot in calls:
                before = calls[slot]
                assert read(scope, slot) == {'value': [before + 1]}
            conn.execute("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name=%s", (name,))
            conn.commit()
            for slot in calls:
                before = calls[slot]
                assert read(scope, slot) == {'value': [before + 1]}
            conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s", (name,))
            conn.commit()
            for slot in calls:
                before = calls[slot]
                assert read(scope, slot) == {'value': [before + 1]}
    assert verified.owned(conn) is None


@pytest.mark.parametrize('slot', ['dual-sizing', 'retained-runtime-checkpoint'])
def test_economic_inventory_falsifier_detects_broker_invalidation(conn, published, monkeypatch, slot):
    monkeypatch.setattr(verified, '_ECONOMIC_INPUT_SLOTS', verified._ECONOMIC_INPUT_SLOTS - {slot})
    with pytest.raises(AssertionError):
        test_only_economic_proofs_ignore_exact_broker_records(conn, published)


def test_gateway_owner_can_warm_actual_retained_proof_once(conn, published, monkeypatch):
    from sentinel import rolling_runtime
    from tests.sentinel.test_rolling_initialization import OBS
    approve(conn)
    original = rolling_runtime._load_closure
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(rolling_runtime, '_load_closure', counted)
    with journal.writer_lock(conn), feed_inputs.pinned(conn, commit=False), verified.callback(conn) as scope:
        result = rolling_runtime.status(conn, observation_id=OBS, starting_cash=100000)
        assert verified.owned(conn) is scope
        with psycopg.connect(conn.info.dsn) as fresh:
            assert verified.owned(fresh) is None
            for _ in range(5):
                with scope.guard(fresh):
                    current = rolling_runtime.status(fresh, observation_id=OBS, starting_cash=100000)
                    assert current.state.state_hash == result.state.state_hash
        assert len(calls) == 1
    assert verified.owned(conn) is None


def test_dependency_alert_never_claims_source_deadline_even_after_open(monkeypatch):
    now = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
    alerts = []
    monkeypatch.setattr(shadow_supervisor, '_enqueue_alert', lambda **kw: alerts.append(kw))
    shadow_supervisor._dependency_retry_alert(now=now)
    shadow_supervisor._dependency_retry_alert(now=now + timedelta(minutes=5))
    assert alerts[0] == alerts[1]
    assert alerts[0]['severity'] == 'WARN'
    assert alerts[0]['event_type'] == 'SHADOW_DEPENDENCY_UNAVAILABLE'
    assert 'recovery_deadline_at' not in alerts[0]['payload']


def test_local_worker_deadline_is_not_a_source_coverage_failure():
    from sentinel import shadow_worker
    from sentinel.feed.rolling_jobs import JobDeadlineExceeded
    failure = JobDeadlineExceeded('local worker execution budget exhausted')
    assert shadow_worker._availability_failure(failure)
    assert shadow_worker._availability_exit(failure) == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE


def test_gateway_warms_scope_before_constructing_guarded_broker(conn, gateway, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from sentinel import paper
    from sentinel.feed import calendar
    from sentinel.paper import execution
    from sentinel.execution.guarded import AutomationExecutionGrant
    from tests.sentinel.test_rolling_paper_inputs import prepare
    from tests.sentinel.test_rolling_initialization import OBS
    _shadow, bound, broker = gateway
    plan = prepare(conn, broker).plan
    opened, _ = calendar.session_window(plan.effective_session)
    grant = AutomationExecutionGrant('EXECUTE', 'owned-proof', 1, 'worker', 1,
        'paper-fixture', bound.takeover_epoch, 'CONTROLLER', 2, 'a' * 64)
    monkeypatch.setattr(execution, '_validate_automation_grant', lambda *_: (
        None, SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint())))
    class VerifiedBoundaryReached(Exception):
        pass
    def inspect_boundary(**kwargs):
        scope = verified.owned(kwargs['conn'])
        assert scope is not None and 'rolling-checkpoint' in scope.values
        assert 'dual-sizing' in scope.values
        raise VerifiedBoundaryReached
    monkeypatch.setattr(execution, '_guard_broker', inspect_boundary)
    with pytest.raises(VerifiedBoundaryReached):
        asyncio.run(paper.execute_automated_paper_plan(
            conn=conn, broker=broker, base_url='https://paper-api.alpaca.markets',
            grant=grant, automation_config_sha256='f' * 64,
            today=opened+timedelta(seconds=60),
            dual_shadow_observation_id=OBS, dual_shadow_starting_cash=100000))
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    assert verified.owned(conn) is None


def test_active_callback_uses_original_deadline_and_preserves_failures():
    now = datetime(2026, 10, 12, 13, 31, tzinfo=timezone.utc)
    deadline = now + timedelta(minutes=15)
    cycle = {'state': 'EXECUTING', 'observation_callback': {'started_at': now, 'deadline': deadline}}
    recovery = sources._observation_recovery(cycle)
    assert recovery.deadline == deadline
    row = model.broker_row(available=True, positions=0, completeness='COMPLETE',
                          runtime_state='RUNNING', as_of=now-timedelta(hours=5), recovery=recovery)
    assert row.effective_status(now + timedelta(minutes=5)) == 'warn'
    assert row.effective_status(deadline + timedelta(seconds=1)) == 'fail'
    failed = model.broker_row(available=True, positions=0, completeness='PARTIAL',
                             runtime_state='RUNNING', as_of=now, recovery=recovery)
    assert failed.effective_status(now + timedelta(seconds=1)) == 'fail'
    assert sources._observation_recovery({'state': 'EXECUTING'}) is None
    assert sources._observation_recovery({'state': 'RECONCILING', 'updated_at': now}) is None


def test_gateway_rejects_real_retained_tamper_before_broker_interaction(conn, gateway, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from sentinel import paper, rolling_checkpoint
    from sentinel.feed import calendar
    from sentinel.paper import execution
    from sentinel.execution.guarded import AutomationExecutionGrant
    from tests.sentinel.test_rolling_paper_inputs import prepare
    from tests.sentinel.test_rolling_initialization import OBS
    _shadow, bound, broker = gateway
    plan = prepare(conn, broker).plan
    opened, _ = calendar.session_window(plan.effective_session)
    grant = AutomationExecutionGrant('EXECUTE', 'tamper-proof', 1, 'worker', 1,
        'paper-fixture', bound.takeover_epoch, 'CONTROLLER', 2, 'a' * 64)
    monkeypatch.setattr(execution, '_validate_automation_grant', lambda *_: (
        None, SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint())))
    monkeypatch.setattr(execution, '_guard_broker', lambda **_: pytest.fail('unverified book reached broker boundary'))
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',to_jsonb(repeat('f',64))) "
                 "WHERE cursor_name=%s", (rolling_checkpoint.CURSOR,))
    conn.commit()
    with pytest.raises(execution.PaperActivationRefused, match='shadow|AUTHENTICATION|checkpoint'):
        asyncio.run(paper.execute_automated_paper_plan(
            conn=conn, broker=broker, base_url='https://paper-api.alpaca.markets',
            grant=grant, automation_config_sha256='f' * 64,
            today=opened+timedelta(seconds=60),
            dual_shadow_observation_id=OBS, dual_shadow_starting_cash=100000))
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0


def test_gateway_guarded_reads_reuse_first_canonical_proof(conn, gateway, monkeypatch):
    """Real gateway and ten fresh guard checks; signing/control are named fixtures."""
    import asyncio
    from types import SimpleNamespace
    from sentinel import dual_plan_authority, paper, rolling_runtime
    from sentinel.automation import store as automation_store
    from sentinel.feed import calendar
    from sentinel.paper import execution, validation
    from sentinel.execution.guarded import AutomationExecutionGrant
    from tests.sentinel.test_rolling_paper_inputs import prepare
    from tests.sentinel.test_rolling_initialization import OBS
    _shadow, bound, broker = gateway
    plan = prepare(conn, broker).plan
    opened, _ = calendar.session_window(plan.effective_session)
    grant = AutomationExecutionGrant('EXECUTE', 'guarded-proof', 1, 'worker', 1,
        'paper-fixture', bound.takeover_epoch, 'CONTROLLER', 2, 'a' * 64)
    cycle = SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
                            decision_session=plan.decision_session)
    for owner in (execution, validation):
        monkeypatch.setattr(owner, '_validate_automation_grant', lambda *_: (None, cycle))
    monkeypatch.setattr(automation_store, 'record_authority_verdict', lambda *_a, **_k: None)
    load, size = rolling_runtime._load_closure, dual_plan_authority._rederive_plan
    construct = execution._guard_broker
    calls, reads = {'checkpoint': 0, 'sizing': 0}, []
    def counted(*args, **kwargs):
        calls['checkpoint'] += 1
        return load(*args, **kwargs)
    def sized(*args, **kwargs):
        calls['sizing'] += 1
        return size(*args, **kwargs)
    monkeypatch.setattr(rolling_runtime, '_load_closure', counted)
    monkeypatch.setattr(dual_plan_authority, '_rederive_plan', sized)
    # Stop the test before mutation; an ordinary broker exception is correctly
    # converted into degraded reconciliation by the canonical reader.
    class ReadBoundaryReached(BaseException):
        pass
    def probe(**kwargs):
        wrapped = construct(**kwargs)
        observe = wrapped.observe
        async def observed():
            for index in range(5):
                conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                             "VALUES ('broker-observation:v4:guarded-read-proof',%s,jsonb_build_object('read_index',%s::integer)) "
                             "ON CONFLICT (cursor_name) DO UPDATE SET state=EXCLUDED.state",
                             (plan.decision_session, index))
                conn.commit()
                reads.append(await observe())
            raise ReadBoundaryReached
        wrapped.observe = observed
        return wrapped
    monkeypatch.setattr(execution, '_guard_broker', probe)
    with pytest.raises(ReadBoundaryReached):
        asyncio.run(paper.execute_automated_paper_plan(
            conn=conn, broker=broker, base_url='https://paper-api.alpaca.markets',
            grant=grant, automation_config_sha256='f' * 64,
            today=opened+timedelta(seconds=60),
            dual_shadow_observation_id=OBS, dual_shadow_starting_cash=100000))
    assert len(reads) == 5 and calls == {'checkpoint': 1, 'sizing': 1}
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    assert verified.owned(conn) is None
