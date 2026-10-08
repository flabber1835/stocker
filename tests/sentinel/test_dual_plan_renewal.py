"""Certificate renewal over a real immutable rolling book and durable plan."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import dual_plan_authority, dual_reconciliation, paper
from sentinel.authority import RolloutMode, RolloutState, load_rollout_state
from sentinel.authority.repository import set_rollout_rows
from sentinel.execution import journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState
from sentinel.paper import preparation, validation
from tests.sentinel.test_rolling_paper_inputs import (
    gateway, prepare, conn, pg, source, published, issuer_source, ready,
    operational_source, OBS)  # noqa: F401


def renew(conn, monkeypatch):
    from tests.sentinel.test_rollout_rotation_schema import _install_signed_certificate
    current = load_rollout_state(conn)
    # These records model only signed succession. The gateway explicitly
    # substitutes cryptographic issuance; rollout/schema verification stays real.
    _install_signed_certificate(conn, 'a'*64, 1)
    _install_signed_certificate(conn, 'b'*64, 2, supersedes='a'*64)
    set_rollout_rows(conn, current=current,
                    next_state=RolloutState(RolloutMode.CONTROLLER, 3, 'b'*64),
                    reason='test authenticated same-mode certificate renewal')
    conn.commit()
    for owner in (preparation, validation):
        monkeypatch.setattr(owner, 'require_current_authority', lambda *_a, **_k:
                            SimpleNamespace(certificate_sha256='b'*64,
                                            authorization_mode='PAPER_OBSERVATION_ONLY'))


def command(conn, plan, bound, state):
    value = Command(CommandIdentity(bound.identity, plan.plan_id, '1'),
                    BrokerInstrument('1', 'AAA'), Side.BUY, Decimal(1), state=state)
    journal.save_command(conn, value)
    return value


def test_renewal_replaces_unsent_plan_and_retry_reuses_exact_economics(conn, gateway, monkeypatch):
    shadow, bound, broker = gateway
    old = prepare(conn, broker).plan
    authority = dual_plan_authority.load_authority(conn, plan_id=old.plan_id)
    command(conn, old, bound, CommandState.PLANNED)
    renew(conn, monkeypatch)
    # Only the executable attestation changes; the verified immutable record
    # and state remain the same. Full runtime admission is qualified separately.
    current_shadow = SimpleNamespace(state=shadow.state,
        record_sha256=shadow.record_sha256, runtime_authority_sha256='c'*64)
    monkeypatch.setattr(dual_reconciliation, 'verified_shadow_intent',
                        lambda *_a, **_k: current_shadow)
    broker.equity = Decimal('260000')
    result = prepare(conn, broker)
    new = result.plan
    assert result.superseded_plans == 1 and new.plan_id != old.plan_id
    assert (new.rollout_version, new.rollout_certificate_sha256) == (3, 'b'*64)
    assert new.shadow_snapshot_hash == old.shadow_snapshot_hash == shadow.state.state_hash
    # Canonical sizing uses observed holdings plus cash, rather than trusting
    # the broker's independently reported equity as a position substitute.
    assert new.account_nav == old.account_nav == Decimal('250000')
    new_authority = dual_plan_authority.load_authority(conn, plan_id=new.plan_id)
    assert new_authority['account_snapshot']['equity'] == '260000'
    assert journal.load_plan(conn, old.plan_id).superseded_by == new.plan_id
    assert dual_plan_authority.load_authority(conn, plan_id=old.plan_id) == authority
    assert journal.load_commands(conn, bound.identity, plan_id=old.plan_id)[0].state is CommandState.PLANNED
    assert dual_plan_authority.rederive_plan(conn, plan=new, binding=bound,
        rollout_state=load_rollout_state(conn), expected_shadow_result=current_shadow)['verdict'] == 'MATCH'
    broker.equity = Decimal('270000')
    assert prepare(conn, broker).plan == new
    assert dual_plan_authority.load_authority(conn, plan_id=new.plan_id) == new_authority
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name='catchup'").fetchone()[0] == 0


@pytest.mark.parametrize('state', [CommandState.UNKNOWN, CommandState.FILLED])
def test_dispatched_same_session_plan_never_gets_a_replacement_before_broker_read(
        conn, gateway, monkeypatch, state):
    _, bound, broker = gateway
    old = prepare(conn, broker).plan
    value = command(conn, old, bound, state)
    renew(conn, monkeypatch)
    broker.calls.clear()
    with pytest.raises(paper.PaperRetryableRefused, match='unsent plan'):
        prepare(conn, broker)
    assert broker.calls == []
    assert journal.latest_plan(conn).plan_id == old.plan_id
    assert journal.load_commands(conn, bound.identity, plan_id=old.plan_id)[0].state is value.state


@pytest.mark.parametrize('state', [state for state in CommandState if state is not CommandState.PLANNED])
def test_every_dispatched_state_blocks_the_unsent_gate(monkeypatch, state):
    value = SimpleNamespace(state=state, filled_quantity=Decimal(0),
                            broker_order_id=None, recovered_key=None)
    monkeypatch.setattr(journal, 'load_commands', lambda *_a, **_k: (value,))
    plan = SimpleNamespace(deployment_id='fixture', broker='sim',
                           broker_account_id='fixture', takeover_epoch=1, plan_id='plan')
    with pytest.raises(paper.PaperRetryableRefused, match='unsent plan'):
        preparation._require_unsent_renewal(None, plan)


@pytest.mark.parametrize('field,value', [('filled_quantity', Decimal(1)),
                                        ('broker_order_id', 'recovered'),
                                        ('recovered_key', 'sntl-recovered')])
def test_planned_label_cannot_hide_broker_evidence(monkeypatch, field, value):
    fields = dict(state=CommandState.PLANNED, filled_quantity=Decimal(0),
                  broker_order_id=None, recovered_key=None)
    fields[field] = value
    monkeypatch.setattr(journal, 'load_commands', lambda *_a, **_k: (SimpleNamespace(**fields),))
    plan = SimpleNamespace(deployment_id='fixture', broker='sim',
                           broker_account_id='fixture', takeover_epoch=1, plan_id='plan')
    with pytest.raises(paper.PaperRetryableRefused, match='unsent plan'):
        preparation._require_unsent_renewal(None, plan)


def test_failed_new_proof_rolls_back_plan_and_supersession(conn, gateway, monkeypatch):
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    def refuse(*_a, **_k):
        raise dual_plan_authority.DualPlanAuthorityRefused('injected proof persistence failure')
    monkeypatch.setattr(dual_plan_authority, 'record_authority', refuse)
    with pytest.raises(dual_plan_authority.DualPlanAuthorityRefused, match='injected'):
        prepare(conn, broker)
    assert journal.latest_plan(conn) == old
    assert conn.execute('SELECT count(*) FROM sentinel_execution_plans').fetchone()[0] == 1


def test_renewal_revalidates_unsent_state_after_reconciliation(conn, gateway, monkeypatch):
    _, bound, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    original = preparation.reconciliation.reconcile
    async def recovered(*a, **k):
        result = await original(*a, **k)
        command(conn, old, bound, CommandState.UNKNOWN)
        return result
    monkeypatch.setattr(preparation.reconciliation, 'reconcile', recovered)
    with pytest.raises(paper.PaperRetryableRefused, match='unsent plan'):
        prepare(conn, broker)
    assert journal.latest_plan(conn).plan_id == old.plan_id
    assert journal.load_commands(conn, bound.identity)[0].state is CommandState.UNKNOWN


def test_corrupt_prior_sizing_is_refused_before_broker_reads(conn, gateway, monkeypatch):
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    verified = dual_reconciliation.verified_shadow_intent
    def foreign_record(*a, **k):
        actual = verified(*a, **k)
        return SimpleNamespace(state=actual.state, record_sha256='f'*64,
            runtime_authority_sha256=actual.runtime_authority_sha256)
    broker.calls.clear()
    with monkeypatch.context() as local:
        local.setattr(dual_reconciliation, 'verified_shadow_intent', foreign_record)
        with pytest.raises(paper.PaperActivationRefused, match='renewal shadow record'):
            prepare(conn, broker)
    assert broker.calls == []
    assert journal.latest_plan(conn).plan_id == old.plan_id
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{account_snapshot,cash}','\"0\"') WHERE cursor_name=%s",
                 (dual_plan_authority._cursor(old.plan_id),))
    conn.commit()
    broker.calls.clear()
    with pytest.raises(paper.PaperActivationRefused, match='refused renewal'):
        prepare(conn, broker)
    assert broker.calls == []
    assert journal.latest_plan(conn).plan_id == old.plan_id


def test_old_plan_stays_stale_for_execution_validation(conn, gateway, monkeypatch):
    shadow, bound, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    from sentinel.execution import feed_inputs
    with pytest.raises(paper.PaperActivationRefused, match='rollout mode/version authority is stale'):
        validation._assert_plan_authorities(conn, state=shadow.state, plan=old,
            binding=bound, pinned=feed_inputs.require_current(conn),
            frontier=old.decision_session.isoformat(), today=old.effective_session,
            runtime_identity=shadow.state.strategy_identity, rollout=load_rollout_state(conn),
            retained_shadow=True)


@pytest.mark.parametrize('mode,version,certificate', [
    ('PINNED_1_00', 2, None), ('CONTROLLER', 3, 'a'*64),
    ('CONTROLLER', 3, 'b'*64), ('CONTROLLER', 4, 'a'*64),
])
def test_renewal_never_waives_unrelated_rollout_mismatch(mode, version, certificate):
    plan = SimpleNamespace(rollout_mode=mode, rollout_version=version,
                           rollout_certificate_sha256=certificate)
    current = RolloutState(RolloutMode.CONTROLLER, 3, 'b'*64)
    assert preparation._dual_renewal_rollout(None, plan, current) is None


def test_renewal_requires_exact_historical_rollout_event(conn, gateway, monkeypatch):
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    foreign = replace(old, rollout_certificate_sha256='f'*64)
    with pytest.raises(paper.PaperActivationRefused, match='rollout history'):
        preparation._dual_renewal_rollout(conn, foreign, load_rollout_state(conn))
