"""Attended policy renewal against the real immutable book and SQL journal."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import inspect
from types import SimpleNamespace

import pytest

from sentinel import dual_plan_authority, local_paper, paper
from sentinel.authority import load_rollout_state
from sentinel.execution import journal
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MarketBuyPolicy
from sentinel.execution.states import CommandState
from sentinel.paper import policy_replacement as replacement, preparation
from sentinel.feed import calendar
from tests.sentinel.test_dual_plan_renewal import renew, command
from tests.sentinel.test_market_buy_policy import MARKET_ENV
from tests.sentinel.test_rolling_paper_inputs import (
    gateway, prepare, conn, pg, source, published, issuer_source, ready,
    operational_source, OBS, NOW)  # noqa: F401


@pytest.fixture(autouse=True)
def synthetic_backup_boundary(monkeypatch, tmp_path):
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path/'absent-production-policy')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'replacement-test-receipt-key-'*4)
    monkeypatch.setattr(preparation, '_require_mutation_backup', lambda *a, **k: None)


def request(plan):
    return dict(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        actor='owner', reason='select fractional market purchases for the saved next-session plan',
        confirm_unsent_policy_replacement=True)


def select(monkeypatch):
    selected = MarketBuyPolicy.from_env({**MARKET_ENV, 'SENTINEL_PAPER_BUY_POLICY': FRACTIONAL_MODE})
    monkeypatch.setattr(MarketBuyPolicy, 'from_env', classmethod(lambda cls, values=None: selected))
    # Synthetic SQL fixture has no deployed backup media or physical account.
    # Policy validation, control lineage, journal and reconciliation remain real.
    monkeypatch.setattr(preparation, '_require_mutation_backup', lambda *a, **k: None)
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda c: True)


def test_explicit_replacement_preserves_history_and_retry_is_idempotent(conn, gateway, monkeypatch):
    shadow, bound, broker = gateway
    old = prepare(conn, broker).plan
    old_authority = dual_plan_authority.load_authority(conn, plan_id=old.plan_id)
    unsent = command(conn, old, bound, CommandState.PLANNED)
    old_history = journal.command_history(conn, unsent.client_key)
    renew(conn, monkeypatch)
    select(monkeypatch)
    result = prepare(conn, broker, unsent_policy_replacement=request(old))
    new = result.plan
    assert result.superseded_plans == 1 and new.plan_id != old.plan_id
    assert new.shadow_snapshot_hash == old.shadow_snapshot_hash == shadow.state.state_hash
    assert new.sentinel_transition_hash == old.sentinel_transition_hash
    assert journal.load_plan(conn, old.plan_id) == replace(old, superseded_by=new.plan_id)
    assert dual_plan_authority.load_authority(conn, plan_id=old.plan_id) == old_authority
    assert journal.command_history(conn, unsent.client_key) == old_history
    authority = dual_plan_authority.load_authority(conn, plan_id=new.plan_id)
    assert authority['market_buy_policy_sha256'] == MarketBuyPolicy(fractional=True).fingerprint()
    assert authority['held_share_targets'] == old_authority['held_share_targets']
    assert dual_plan_authority.rederive_plan(conn, plan=new, binding=bound,
        rollout_state=load_rollout_state(conn))['verdict'] == 'MATCH'
    replacement.verify_receipts(conn)
    broker.equity += Decimal(500)
    assert prepare(conn, broker, unsent_policy_replacement=request(old)).plan == new
    assert prepare(conn, broker).plan == new
    assert dual_plan_authority.load_authority(conn, plan_id=new.plan_id) == authority
    assert conn.execute('SELECT count(*) FROM sentinel_execution_plans').fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name='catchup'").fetchone()[0] == 0
    current = load_rollout_state(conn)
    later = replace(current, version=current.version+1, certificate_sha256='c'*64)
    monkeypatch.setattr(preparation, 'load_rollout_state', lambda c: later)
    monkeypatch.setattr(preparation, 'require_current_authority', lambda *a, **k:
        SimpleNamespace(certificate_sha256='c'*64, authorization_mode='PAPER_OBSERVATION_ONLY'))
    broker.calls.clear()
    with pytest.raises(paper.PaperActivationRefused, match='request differs'):
        prepare(conn, broker, unsent_policy_replacement=request(old))
    assert broker.calls == [] and journal.latest_plan(conn) == new


def test_selecting_policy_alone_never_replaces_saved_plan(conn, gateway, monkeypatch):
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    select(monkeypatch)
    broker.calls.clear()
    with pytest.raises(paper.PaperActivationRefused, match='BUY policy differs'):
        prepare(conn, broker)
    assert broker.calls == [] and journal.latest_plan(conn) == old


def test_explicit_request_without_renewed_authority_refuses(conn, gateway, monkeypatch):
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    select(monkeypatch)
    broker.calls.clear()
    with pytest.raises(paper.PaperActivationRefused, match='fresh same-mode'):
        prepare(conn, broker, unsent_policy_replacement=request(old))
    assert broker.calls == [] and journal.latest_plan(conn) == old


def test_unknown_refuses_before_broker_read(conn, gateway, monkeypatch):
    _, bound, broker = gateway
    old = prepare(conn, broker).plan
    command(conn, old, bound, CommandState.UNKNOWN)
    renew(conn, monkeypatch)
    select(monkeypatch)
    broker.calls.clear()
    with pytest.raises(paper.PaperActivationRefused, match='wholly unsent'):
        prepare(conn, broker, unsent_policy_replacement=request(old))
    assert broker.calls == [] and journal.latest_plan(conn) == old


@pytest.mark.parametrize('state', [s for s in CommandState if s is not CommandState.PLANNED])
def test_every_attempted_state_blocks_the_unsent_gate(monkeypatch, state):
    plan = SimpleNamespace(deployment_id='fixture', broker='sim', broker_account_id='fixture',
                           takeover_epoch=1, plan_id='plan')
    value = SimpleNamespace(state=state, filled_quantity=Decimal(0),
                            broker_order_id=None, recovered_key=None)
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: (value,))
    with pytest.raises(paper.PaperActivationRefused, match='wholly unsent'):
        replacement.require_unsent(None, plan)


def test_planned_label_cannot_hide_attempt_history(conn, gateway, monkeypatch):
    _, bound, broker = gateway
    old = prepare(conn, broker).plan
    value = command(conn, old, bound, CommandState.PLANNED)
    conn.execute('INSERT INTO sentinel_command_events (client_key,from_state,to_state) VALUES (%s,%s,%s)',
                 (value.client_key, 'SEND_PENDING', 'PLANNED'))
    conn.commit()
    renew(conn, monkeypatch)
    select(monkeypatch)
    broker.calls.clear()
    with pytest.raises(paper.PaperActivationRefused, match='transport or recovery history'):
        prepare(conn, broker, unsent_policy_replacement=request(old))
    assert broker.calls == [] and journal.latest_plan(conn) == old


def test_reconciliation_discovery_prevents_adoption(conn, gateway, monkeypatch):
    _, bound, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    select(monkeypatch)
    original = preparation.reconciliation.reconcile
    async def discovery(*a, **k):
        result = await original(*a, **k)
        command(conn, old, bound, CommandState.UNKNOWN)
        return result
    monkeypatch.setattr(preparation.reconciliation, 'reconcile', discovery)
    with pytest.raises(paper.PaperRetryableRefused, match='unsent plan'):
        prepare(conn, broker, unsent_policy_replacement=request(old))
    assert journal.latest_plan(conn) == old


def test_receipt_failure_rolls_back_successor_and_supersession(conn, gateway, monkeypatch):
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    select(monkeypatch)
    monkeypatch.setattr(replacement, '_signature', lambda raw: (_ for _ in ()).throw(ValueError('receipt fault')))
    with pytest.raises(ValueError, match='receipt fault'):
        prepare(conn, broker, unsent_policy_replacement=request(old))
    assert journal.latest_plan(conn) == old
    assert conn.execute('SELECT count(*) FROM sentinel_execution_plans').fetchone()[0] == 1


def test_retry_rejects_changed_request_or_receipt(conn, gateway, monkeypatch):
    import json
    _, _, broker = gateway
    old = prepare(conn, broker).plan
    renew(conn, monkeypatch)
    select(monkeypatch)
    prepare(conn, broker, unsent_policy_replacement=request(old))
    original = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                            (replacement.PREFIX + old.plan_id,)).fetchone()[0]
    for fault in ('request', 'hmac', 'successor'):
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
                     (json.dumps(original), replacement.PREFIX + old.plan_id))
        retry = request(old)
        if fault == 'request':
            retry['reason'] = 'another request'
        else:
            path = '{hmac_sha256}' if fault == 'hmac' else '{receipt,successor_plan_id}'
            conn.execute('UPDATE sentinel_processed_sessions SET state=jsonb_set(state,%s,\'"changed"\') '
                         'WHERE cursor_name=%s', (path, replacement.PREFIX + old.plan_id))
        conn.commit()
        broker.calls.clear()
        with pytest.raises(paper.PaperActivationRefused, match='receipt|request differs'):
            prepare(conn, broker, unsent_policy_replacement=retry)
        assert broker.calls == []


def test_unsent_history_guard_has_a_falsifier(monkeypatch):
    source = inspect.getsource(replacement._require_unsent_history)
    guard = "if not history or any(event['from'] not in (None, 'PLANNED') or event['to'] not in {s.value for s in allowed}"
    assert source.count(guard) == 1
    plan = SimpleNamespace(plan_id='plan')
    value = SimpleNamespace(state=CommandState.PLANNED, filled_quantity=Decimal(0),
                            broker_order_id=None, recovered_key=None, client_key='key')
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: (value,))
    events = [{'from':None,'to':'PLANNED','filled':'0'},
              {'from':'SEND_PENDING','to':'PLANNED','filled':'0'}]
    monkeypatch.setattr(journal, 'command_history', lambda *a, **k: events)
    connection = SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: (False,)))
    def rejected():
        with pytest.raises(paper.PaperActivationRefused, match='transport or recovery history'):
            replacement._require_unsent_history(connection, plan, None)
    rejected()
    scope = dict(replacement.__dict__)
    source = source.replace("event['from'] not in (None, 'PLANNED')", 'False')
    exec(compile(source,'removed unsent history guard','exec'),scope)
    monkeypatch.setattr(replacement, '_require_unsent_history', scope['_require_unsent_history'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        rejected()


@pytest.mark.parametrize('fault', ['enabled','released','leader','open','unbound'])
def test_quiescence_and_open_boundary_refuse(monkeypatch, fault):
    plan = SimpleNamespace(effective_session=NOW.date()+timedelta(days=1))
    opened = calendar.session_window(plan.effective_session)[0]
    control = SimpleNamespace(enabled=fault=='enabled', kill_switch_engaged=fault!='released', generation=4)
    conn = SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: (fault=='leader',)))
    monkeypatch.setattr(replacement.store, 'load_control', lambda *a, **k: control)
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda c: fault!='unbound')
    with pytest.raises(paper.PaperActivationRefused):
        replacement.require_quiescent(conn, plan=plan, now=opened if fault=='open' else NOW)


@pytest.mark.parametrize('guard,fault', [
    ('if control.enabled or not control.kill_switch_engaged or live_lease:', 'enabled'),
    ('if now.utcoffset() is None or now >= opened:', 'open'),
    ('if not local_paper.require_bound_account(conn):', 'unbound'),
])
def test_quiescence_guard_falsifiers(monkeypatch, guard, fault):
    source = inspect.getsource(replacement.require_quiescent)
    assert source.count(guard) == 1
    scope = dict(replacement.__dict__)
    exec(compile(source.replace(guard,'if False:'),'removed replacement guard','exec'),scope)
    monkeypatch.setattr(replacement, 'require_quiescent', scope['require_quiescent'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_quiescence_and_open_boundary_refuse(monkeypatch, fault)
