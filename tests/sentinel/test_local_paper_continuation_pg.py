"""Real SQL and immutable genesis for owner-authorized PAPER continuation."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from sentinel import binding, local_paper
from sentinel.automation import integrity, schedule, store
from sentinel.automation.model import ControlBinding, CycleState, PaperDebugWindow, ProspectiveReplacementRefused
from tests.sentinel.test_automation_service import pg, conn, config, service_for
from tests.sentinel.test_automation_generation import future_friday


@pytest.mark.parametrize('command_state', ['FILLED', 'UNKNOWN', 'ACKNOWLEDGED'])
def test_native_recovery_then_fresh_genesis_preserves_filled_intent(conn, monkeypatch, command_state):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, 'PATESTACCOUNT')
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    monkeypatch.setattr(binding, 'require', lambda conn: SimpleNamespace(broker='alpaca', broker_account_id='PATESTACCOUNT'))
    cfg = config()
    timing, now = future_friday(conn, cfg)
    cfg = cfg.model_copy(update={'paper_debug_window': PaperDebugWindow(
        effective_session=timing.effective_session,
        not_before=timing.execute_at, not_after=timing.execute_at+timedelta(minutes=30))})
    timing = schedule.for_decision_session(timing.decision_session, cfg)
    control_binding = ControlBinding(deployment_id='test-local', broker='alpaca',
        broker_account_id='PATESTACCOUNT', takeover_epoch=1, certificate_sha256='d'*64,
        rollout_mode='CONTROLLER', rollout_version=1, config_sha256=cfg.fingerprint)
    def activate():
        store.activate(conn, binding=control_binding, actor='test', reason='local PAPER')
        store.release_kill(conn, expected_binding=control_binding, actor='test', reason='local PAPER')
        return store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    permit = activate()
    service = service_for(cfg)
    old = store.create_cycle(conn, permit=permit, spec=service._spec(store.load_control(conn), timing), config=cfg)
    for target in (CycleState.REFRESHING_DATA, CycleState.PREPARING, CycleState.PLAN_READY, CycleState.EXECUTING):
        old = store.transition_cycle(conn, permit=permit, cycle_id=old.cycle_id, to_state=target,
            **({'plan_id': 'prior-filled-plan'} if target is CycleState.PLAN_READY else {}))
    seq = conn.execute("INSERT INTO sentinel_observations(observed_at,completeness,runtime_state) "
        "VALUES(clock_timestamp(),'COMPLETE','RUNNING') RETURNING seq").fetchone()[0]
    conn.execute("INSERT INTO sentinel_observation_provenance(observation_seq,broker,broker_account_id,observed_at,canonical_payload_sha256) "
        "VALUES(%s,'alpaca','PATESTACCOUNT',clock_timestamp(),%s)", (seq, 'a'*64))
    conn.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state) "
        "VALUES('prior-command','prior-filled-plan','sec','test-local','alpaca','PATESTACCOUNT',1,'TEST','SELL',1,%s)", (command_state,))
    conn.commit()
    store.engage_kill(conn, actor='test', reason='local successor')
    store.deactivate(conn, actor='test', reason='local successor')
    permit = activate()
    old = store.adopt_cycle(conn, permit=permit, cycle_id=old.cycle_id, to_state=CycleState.SUPERSEDED,
        failure_code='OLD_GENERATION_RECOVERED', last_clean_reconciliation_id=str(seq),
        diagnostic=dict(clean=True, unresolved=[], foreign_orders=[], foreign_positions=[]))
    prior_events = conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq', (old.cycle_id,)).fetchall()
    conn.rollback()
    spec = service._spec(store.load_control(conn), timing)
    if command_state != 'FILLED':
        with pytest.raises(ProspectiveReplacementRefused):
            store.create_cycle(conn, permit=permit, spec=spec, now=now, config=cfg)
        return
    fresh = store.create_cycle(conn, permit=permit, spec=spec, now=now, config=cfg)
    integrity.validate_cycle_lineage(conn, fresh)
    assert fresh.cycle_id != old.cycle_id and fresh.plan_id is None
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq', (old.cycle_id,)).fetchall() == prior_events
    assert conn.execute("SELECT state FROM sentinel_commands WHERE client_key='prior-command'").fetchone()[0] == 'FILLED'
