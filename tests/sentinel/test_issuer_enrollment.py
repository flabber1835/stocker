"""One-time account enrollment uses the authenticated current book and GETs only."""
import asyncio
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerCapabilities, BrokerInstrument, Side)
from sentinel.config import LiveEndpointRefused
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant,
    PaperPreparationGrant, PreTransportAuthorityRefused)
from sentinel.execution.states import CommandState
from sentinel.paper import issuer_enrollment as operation
from sentinel.paper.model import PaperActivationRefused
from tests.sentinel.test_issuer_admission import (
    BINDING, NOW, command, instruments, reconciliation, source, state, store)  # noqa: F401


@pytest.fixture
def enrollment_context(store, source, monkeypatch):
    events = []
    value = state(held=('A', 'A2'))
    rec = reconciliation('A', 'A2')
    binding = SimpleNamespace(identity=BINDING, **BINDING.to_dict())
    publication = SimpleNamespace(version=7)
    store.commit = lambda: events.append('commit')
    store.locked = False

    @contextmanager
    def writer(conn):
        assert conn is store and not store.locked
        store.locked = True
        events.append('lock')
        try:
            yield
        finally:
            store.locked = False

    @contextmanager
    def pinned(conn, *, commit):
        assert conn is store and store.locked and not commit
        events.append('pin')
        yield publication

    def certified(_broker, *, expected_wrapper_kind):
        assert expected_wrapper_kind == 'generation-fenced-execution'
        events.append('sealed-preparation-read')

    def verified(conn, **kwargs):
        assert conn is store and store.locked
        assert kwargs == {'decision_session': '2026-10-26', 'observation_id': 'shadow-owner',
                          'starting_cash': Decimal('50000')}
        events.append('authenticate-shadow')
        return SimpleNamespace(state=value)

    class ReadOnlyBroker:
        grant = PaperPreparationGrant(BINDING.broker_account_id, date(2026, 10, 26))

        async def account_snapshot(self):
            assert store.locked
            events.append('account-GET')
            return BrokerAccountSnapshot(BrokerAccountIdentity('alpaca', 'paper-issuer'), Decimal(50000), Decimal(40000))

        async def submit(self, **_kwargs):
            pytest.fail('enrollment attempted broker submit')

        async def cancel(self, **_kwargs):
            pytest.fail('enrollment attempted broker cancellation')

    async def observed(**kwargs):
        assert store.locked and kwargs['informational_current_book'] is True
        assert kwargs['deployment'] == BINDING
        events.append('fresh-reconcile')
        return rec

    monkeypatch.setattr(operation.local_paper, 'enabled', lambda: True)
    monkeypatch.setattr(operation, '_require_certified_paper_broker', certified)
    monkeypatch.setattr(operation.schema, 'require_runtime_schema', lambda _conn: events.append('schema'))
    monkeypatch.setattr(operation.journal, 'require_observation_integrity', lambda _conn: events.append('observation-integrity'))
    monkeypatch.setattr(operation.journal, 'writer_lock', writer)
    monkeypatch.setattr(operation, 'assert_no_legacy_path', lambda _conn: binding)
    monkeypatch.setattr(operation, 'load_rollout_state', lambda _conn: SimpleNamespace(mode='PINNED_1_00'))
    monkeypatch.setattr(operation, 'require_observation_safety_authority', lambda _conn, **_kwargs: events.append('signed-safety-authority'))
    monkeypatch.setattr(operation.feed_inputs, 'pinned', pinned)
    monkeypatch.setattr(operation.feed_inputs, 'coherent', lambda _conn: events.append('source-coherent'))
    monkeypatch.setattr(operation.feed_inputs, 'require_shadow_mode', lambda *_args: events.append('dual-mode'))
    monkeypatch.setattr(operation.feed_inputs, 'frontier', lambda *_args: '2026-10-26')
    monkeypatch.setattr(operation.dual_reconciliation, 'verified_shadow_intent', verified)
    monkeypatch.setattr(operation.issuer_runtime, 'reference_instruments', lambda *_args: instruments('A', 'A2'))
    monkeypatch.setattr(operation, 'load_snapshot', lambda: source)
    monkeypatch.setattr(operation, '_action_lookup', lambda *_args: None)
    monkeypatch.setattr(operation.reconciliation, 'reconcile', observed)
    return SimpleNamespace(store=store, events=events, rec=rec, state=value, broker=ReadOnlyBroker(), binding=binding)


def run(context, **overrides):
    values = dict(conn=context.store, broker=context.broker,
        base_url='https://paper-api.alpaca.markets', shadow_observation_id='shadow-owner',
        shadow_starting_cash=Decimal('50000'), now=NOW)
    values.update(overrides)
    return asyncio.run(operation.enroll_current_paper_account(**values))


def test_supported_operation_freezes_actual_duplicate_class_episodes_without_replay(enrollment_context):
    context = enrollment_context
    original = context.state.state_hash
    enrolled = run(context)
    assert {ep.security_id for ep in enrolled.episodes} == {'A', 'A2'}
    assert enrolled.canonical_state_sha256 == original == context.state.state_hash
    assert context.events.index('signed-safety-authority') < context.events.index('account-GET')
    assert context.events.index('authenticate-shadow') < context.events.index('fresh-reconcile')
    assert context.events[-1] == 'commit'


def test_restart_returns_original_enrollment_without_broker_reads_or_reseeding(enrollment_context):
    context = enrollment_context
    original = run(context)
    before = dict(context.store.records)
    context.events.clear()
    context.state.wealth_core['episodes']['2'] = {'security_id': 'B', 'slot_id': 2,
        'signal_date': '2026-10-27', 'current_shares': 10}
    assert run(context, now=NOW+timedelta(days=1)) == original
    assert 'account-GET' not in context.events and 'fresh-reconcile' not in context.events
    assert context.store.records == before


def test_enrollment_refuses_unknown_and_cannot_publish_baseline(enrollment_context):
    context = enrollment_context
    context.store.commands = [command('A', CommandState.UNKNOWN)]
    with pytest.raises(operation.issuer_admission.IssuerAdmissionRefused, match='COMMAND_PENDING'):
        run(context)
    assert not any(key.startswith(operation.issuer_admission.ENROLLMENT_PREFIX) for key in context.store.records)


def test_tampered_or_not_current_shadow_refuses_before_account_read(enrollment_context, monkeypatch):
    context = enrollment_context

    def refused(*_args, **_kwargs):
        raise operation.dual_reconciliation.DualReconciliationRefused('shadow authentication failed')

    monkeypatch.setattr(operation.dual_reconciliation, 'verified_shadow_intent', refused)
    with pytest.raises(operation.dual_reconciliation.DualReconciliationRefused):
        run(context)
    assert 'account-GET' not in context.events and not context.store.records


def test_account_takeover_during_observation_refuses_enrollment(enrollment_context, monkeypatch):
    context = enrollment_context
    calls = []

    def binding(_conn):
        calls.append(True)
        if len(calls) == 1:
            return context.binding
        return SimpleNamespace(identity=SimpleNamespace(takeover_epoch=99))

    monkeypatch.setattr(operation, 'assert_no_legacy_path', binding)
    with pytest.raises(PaperActivationRefused, match='binding changed'):
        run(context)
    assert not context.store.records


def test_bare_or_nonlocal_or_live_operation_is_not_supported(enrollment_context, monkeypatch):
    with pytest.raises(LiveEndpointRefused):
        run(enrollment_context, base_url='https://api.alpaca.markets')
    monkeypatch.setattr(operation.local_paper, 'enabled', lambda: False)
    with pytest.raises(PaperActivationRefused, match='local PAPER'):
        run(enrollment_context)


def test_certified_preparation_wrapper_is_required_before_broker_read(enrollment_context, monkeypatch):
    def refused(*_args, **_kwargs):
        raise PaperActivationRefused('unsealed broker')

    monkeypatch.setattr(operation, '_require_certified_paper_broker', refused)
    with pytest.raises(PaperActivationRefused, match='unsealed'):
        run(enrollment_context)
    assert 'account-GET' not in enrollment_context.events


@pytest.mark.parametrize('grant', [
    ManualExecutionGrant(BINDING.broker_account_id, 'plan', date(2026, 10, 27), True),
    SimpleNamespace(expected_account=BINDING.broker_account_id, decision_session=date(2026, 10, 26)),
    None,
])
def test_execution_or_untyped_grants_refuse_before_account_read(enrollment_context, grant):
    enrollment_context.broker.grant = grant
    with pytest.raises(PaperActivationRefused, match='exact read-only PaperPreparationGrant'):
        run(enrollment_context)
    assert 'account-GET' not in enrollment_context.events


@pytest.mark.parametrize('grant,reason', [
    (PaperPreparationGrant('another-account', date(2026, 10, 26)), 'account differs'),
    (PaperPreparationGrant(BINDING.broker_account_id, date(2026, 10, 27)), 'session differs'),
])
def test_preparation_grant_must_match_exact_account_and_frontier(enrollment_context, grant, reason):
    enrollment_context.broker.grant = grant
    with pytest.raises(PaperActivationRefused, match=reason):
        run(enrollment_context)
    assert 'account-GET' not in enrollment_context.events
    assert 'fresh-reconcile' not in enrollment_context.events


def test_preparation_grant_subclass_cannot_borrow_enrollment_authority(enrollment_context):
    class OtherGrant(PaperPreparationGrant):
        pass

    enrollment_context.broker.grant = OtherGrant(BINDING.broker_account_id, date(2026, 10, 26))
    with pytest.raises(PaperActivationRefused, match='exact read-only'):
        run(enrollment_context)
    assert 'account-GET' not in enrollment_context.events


def preparation_wrapper(inner, events):
    inner.capabilities = BrokerCapabilities()
    grant = PaperPreparationGrant(BINDING.broker_account_id, date(2026, 10, 26))

    async def before_read(received, _operation):
        assert received is grant
        events.append('prepare-read-authority')

    async def after_read(received, _operation, _result):
        assert received is grant
        events.append('prepare-read-result-authority')

    async def before_mutation(*_args):
        pytest.fail('read-only preparation grant consulted mutation authority')

    return GuardedExecutionBroker(inner=inner, grant=grant,
        guard=ExecutionBrokerGuard(before_read, after_read, before_mutation))


def test_real_preparation_wrapper_composes_with_supported_enrollment(enrollment_context):
    context = enrollment_context
    wrapped = preparation_wrapper(context.broker, context.events)
    enrolled = run(context, broker=wrapped)
    assert {ep.security_id for ep in enrolled.episodes} == {'A', 'A2'}
    assert context.events.index('prepare-read-authority') < context.events.index('account-GET')
    assert context.events.index('account-GET') < context.events.index('prepare-read-result-authority')


def test_real_preparation_wrapper_structurally_forbids_both_mutations():
    events = []

    class Inner:
        async def submit(self, **_kwargs):
            pytest.fail('preparation enrollment reached submit transport')

        async def cancel(self, *_args):
            pytest.fail('preparation enrollment reached cancel transport')

    wrapped = preparation_wrapper(Inner(), events)
    native = BrokerInstrument('A', 'AAA', 'native-A')
    with pytest.raises(PreTransportAuthorityRefused, match='preparation grant is read-only'):
        asyncio.run(wrapped.submit(client_key='sntl-readonly', instrument=native,
            side=Side.SELL, quantity=Decimal(1)))
    with pytest.raises(PreTransportAuthorityRefused, match='preparation grant is read-only'):
        asyncio.run(wrapped.cancel('broker-order'))
    assert events == []
