"""Final issuer admission is pre-transport and preserves exact unsent proof."""
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerCapabilities, BrokerInstrument, CommandOutcome, Side,
)
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant,
    OrderEvidenceNotReady,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState

INSTRUMENT = BrokerInstrument('EQUITY', 'CLASS.A', 'asset-class-a')
DEPLOYMENT = DeploymentIdentity('issuer-test', 'sim', 'SIM-ACCOUNT', 1)


@pytest.fixture(autouse=True)
def isolated_policy(monkeypatch):
    for name in ('SENTINEL_LOCAL_PAPER_MODE', 'SENTINEL_LOCAL_PAPER_BACKUP_POLICY',
                 'SENTINEL_PAPER_BUY_POLICY', 'SENTINEL_PAPER_BUY_CAP_BPS'):
        monkeypatch.delenv(name, raising=False)


def wrapper(*, admission=None, transport_refusal=False):
    events = []

    class Inner:
        capabilities = BrokerCapabilities()

        async def submit(self, **kwargs):
            events.append(('transport', kwargs))
            if transport_refusal:
                raise OrderEvidenceNotReady('inner transport raised a lookalike refusal')
            return CommandOutcome(CommandState.ACKNOWLEDGED, 'broker-order')

    async def before_read(*_args):
        events.append(('read-authority',))

    async def after_read(*_args):
        events.append(('after-read-authority',))

    async def before_mutation(*_args):
        events.append(('final-authority',))

    grant = ManualExecutionGrant('SIM-ACCOUNT', 'plan', date(2026, 10, 27), True)
    broker = GuardedExecutionBroker(inner=Inner(), grant=grant,
        guard=ExecutionBrokerGuard(before_read, after_read, before_mutation),
        issuer_admission_check=admission(events) if admission is not None else None)
    return broker, events


def command(*, instrument=INSTRUMENT, side=Side.BUY):
    return Command(CommandIdentity(DEPLOYMENT, 'plan', instrument.security_id),
        instrument, side, Decimal(2), state=CommandState.SEND_PENDING)


def submit(broker, current):
    return asyncio.run(broker.submit(client_key=current.client_key, instrument=current.instrument,
        side=current.side, quantity=current.quantity, order_terms=current.order_terms))


def test_issuer_denial_prevents_authority_and_transport_and_issues_exact_single_use_proof():
    def admission(events):
        def deny(**kwargs):
            events.append(('issuer', kwargs))
            raise OrderEvidenceNotReady('ISSUER_CONFLICT')
        return deny

    broker, events = wrapper(admission=admission)
    current = command()
    with pytest.raises(OrderEvidenceNotReady, match='ISSUER_CONFLICT') as refusal:
        submit(broker, current)
    assert [event[0] for event in events] == ['issuer']
    assert events[0][1] == dict(client_key=current.client_key, instrument=current.instrument,
        side=current.side, quantity=current.quantity, order_terms=current.order_terms)
    broker.consume_not_transported(refusal.value, current)
    with pytest.raises(ValueError, match='no matching unused'):
        broker.consume_not_transported(refusal.value, current)


def test_issuer_check_precedes_final_authority_with_no_later_network_read():
    def admission(events):
        def permit(**_kwargs):
            events.append(('issuer',))
            return SimpleNamespace(allowed=True, reason='ADMITTED_EPISODE')
        return permit

    broker, events = wrapper(admission=admission)
    assert submit(broker, command()).state is CommandState.ACKNOWLEDGED
    assert [event[0] for event in events] == ['issuer', 'final-authority', 'transport']


def test_sell_never_consults_issuer_callback():
    def admission(_events):
        def unavailable(**_kwargs):
            pytest.fail('SELL consulted issuer admission')
        return unavailable

    broker, events = wrapper(admission=admission)
    assert submit(broker, command(side=Side.SELL)).state is CommandState.ACKNOWLEDGED
    assert [event[0] for event in events] == ['final-authority', 'transport']


@pytest.mark.parametrize('sid,symbol,blocked', [
    ('EQUITY', 'BIL', True), ('SENTINEL:BIL', 'BIL', False)])
def test_owner_paper_missing_callback_fails_closed_for_non_sleeve_identity(monkeypatch, sid, symbol, blocked):
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_MODE', 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1')
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_ACCOUNT_ID', 'PAFIXTURE')
    broker, events = wrapper()
    current = command(instrument=BrokerInstrument(sid, symbol, 'asset'))
    if blocked:
        with pytest.raises(OrderEvidenceNotReady, match='issuer admission authority is absent'):
            submit(broker, current)
        assert not events
    else:
        assert submit(broker, current).state is CommandState.ACKNOWLEDGED


def test_missing_callback_guard_has_a_falsifier(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, '_require_issuer_admission', lambda *_args, **_kwargs: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_owner_paper_missing_callback_fails_closed_for_non_sleeve_identity(
            monkeypatch, 'EQUITY', 'BIL', True)


def test_issuer_callback_guard_has_a_falsifier(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, '_require_issuer_admission', lambda *_args, **_kwargs: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_issuer_denial_prevents_authority_and_transport_and_issues_exact_single_use_proof()


def test_generic_simulator_without_local_mode_retains_buy_path():
    broker, events = wrapper()
    assert submit(broker, command()).state is CommandState.ACKNOWLEDGED
    assert [event[0] for event in events] == ['final-authority', 'transport']


def test_transport_lookalike_refusal_cannot_acquire_unsent_proof():
    broker, events = wrapper(transport_refusal=True)
    current = command()
    with pytest.raises(OrderEvidenceNotReady) as refusal:
        submit(broker, current)
    assert events[-1][0] == 'transport'
    with pytest.raises(ValueError, match='no matching unused'):
        broker.consume_not_transported(refusal.value, current)


def test_async_callback_cannot_skip_admission():
    def admission(_events):
        async def invalid(**_kwargs):
            return None
        return invalid

    broker, events = wrapper(admission=admission)
    with pytest.raises(OrderEvidenceNotReady, match='synchronous'):
        submit(broker, command())
    assert not events


@pytest.mark.parametrize('decision', [None, {}, True, SimpleNamespace(allowed=1),
    SimpleNamespace(allowed=False, reason='ISSUER_CONFLICT')])
def test_missing_malformed_or_denied_callback_result_cannot_authorize_transport(decision):
    broker, events = wrapper(admission=lambda _events: lambda **_kwargs: decision)
    with pytest.raises(OrderEvidenceNotReady):
        submit(broker, command())
    assert not events


@pytest.mark.parametrize('replacement', [None, lambda **_kwargs: None])
def test_certified_wrapper_detects_issuer_callback_removal_or_substitution(replacement):
    from sentinel.execution.certification import (
        AdapterNotCertified, require_certified_adapter,
    )
    from sentinel.execution.simulator import SimulatedBroker

    async def noop(*_args):
        return None

    broker = GuardedExecutionBroker(inner=SimulatedBroker(),
        grant=ManualExecutionGrant('SIM-ACCOUNT', 'plan', date(2026, 10, 27), True),
        guard=ExecutionBrokerGuard(noop, noop, noop),
        issuer_admission_check=lambda **_kwargs: None)
    assert require_certified_adapter(broker).wrapper_kind == 'generation-fenced-execution'
    broker._issuer_admission_check = replacement
    with pytest.raises(AdapterNotCertified, match='configuration changed'):
        require_certified_adapter(broker)


def test_issuer_callback_certification_binding_has_a_falsifier(monkeypatch):
    from sentinel.execution import certification
    specification = certification._WRAPPER_SPECS['generation-fenced-execution']
    changed = (*specification[:2], tuple(name for name in specification[2]
        if name != '_issuer_admission_check'))
    monkeypatch.setitem(certification._WRAPPER_SPECS, 'generation-fenced-execution', changed)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_certified_wrapper_detects_issuer_callback_removal_or_substitution(None)
