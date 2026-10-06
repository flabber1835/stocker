"""Fresh quote and funding guards are checked at real broker transport seam."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel.execution.contract import Side
from sentinel.execution.guarded import GuardedExecutionBroker, PreTransportAuthorityRefused
from sentinel.execution.opening_prices import RegularQuotes
from sentinel.execution.opening_prices import OpeningPriceNotReady
from sentinel.feed import calendar
from tests.sentinel.test_opening_submit_freshness_boundary import ClockedBroker, wrap, instrument
from tests.sentinel.test_guarded_execution_broker import conn, pg, DEPLOYMENT  # noqa: F401


class QuoteBroker(ClockedBroker):
    def __init__(self):
        super().__init__()
        self.capabilities = replace(self.capabilities, regular_session_quote_prices=True,
                                    regular_session_open_prices=True)
        self.quote_age = 0
        self.cash = D('1000')
        self.ask = D('100')
        self.wrong_identity = False
        self.missing = False

    async def opening_prices(self, *, session, instruments):
        self.calls.append('quote-read')
        if self.missing:
            raise OpeningPriceNotReady('quote has not arrived')
        opened, _ = calendar.session_window(session)
        return RegularQuotes(session=session, opening_at=opened, observed_at=self.now,
            prices={sid:self.ask for sid in instruments},
            bids={sid:self.ask-D('0.01') for sid in instruments},
            symbols={sid:i.symbol for sid,i in instruments.items()},
            broker_ids={sid:'another-asset' if self.wrong_identity else i.broker_id
                        for sid,i in instruments.items()},
            quoted_at={sid:self.now-timedelta(seconds=self.quote_age) for sid in instruments})


@pytest.mark.parametrize('fault', [None, 'cash', 'stale', 'identity'])
def test_fresh_quote_and_cash_required_before_any_buy_transport(fault):
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    if fault == 'cash':
        inner.cash = D('99')
    if fault == 'stale':
        inner.quote_age = 61
    if fault == 'identity':
        inner.wrong_identity = True
    broker = wrap(inner)
    operation = broker.submit(client_key='quote-buy', instrument=instrument(),
                              side=Side.BUY, quantity=D(1))
    if fault:
        with pytest.raises(PreTransportAuthorityRefused, match='quote or affordability'):
            asyncio.run(operation)
        assert 'submit:quote-buy' not in inner.calls
    else:
        asyncio.run(operation)
        assert inner.calls.index('quote-read') < inner.calls.index('submit:quote-buy')


def test_quote_expiring_during_authority_wait_never_reaches_transport():
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    broker = wrap(inner)
    async def delayed(grant, operation):
        inner.now += timedelta(seconds=61)
    broker = GuardedExecutionBroker(inner=inner, grant=broker.grant,
                                   guard=replace(broker.guard, before_mutation=delayed))
    with pytest.raises(PreTransportAuthorityRefused, match='final next-open freshness'):
        asyncio.run(broker.submit(client_key='expired-quote', instrument=instrument(),
                                  side=Side.BUY, quantity=D(1)))
    assert 'submit:expired-quote' not in inner.calls
    from sentinel.automation_runtime import classify_dependency_failure
    from sentinel.automation.model import SourceDataPending
    with pytest.raises(PreTransportAuthorityRefused) as pending:
        asyncio.run(broker.submit(client_key='still-expired', instrument=instrument(),
                                  side=Side.BUY, quantity=D(1)))
    assert isinstance(classify_dependency_failure(pending.value), SourceDataPending)


@pytest.mark.parametrize('fault', ['cash', 'missing', 'identity'])
def test_pre_submit_pending_and_identity_have_distinct_retry_taxonomy(fault):
    from sentinel.automation_runtime import classify_dependency_failure
    from sentinel.automation.model import SourceDataPending
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    if fault == 'cash':
        inner.cash = D('99')
    if fault == 'missing':
        inner.missing = True
    if fault == 'identity':
        inner.wrong_identity = True
    with pytest.raises(PreTransportAuthorityRefused) as caught:
        asyncio.run(wrap(inner).submit(client_key='pending-buy', instrument=instrument(),
                                     side=Side.BUY, quantity=D(1)))
    mapped = classify_dependency_failure(caught.value)
    if fault == 'identity':
        assert mapped is None
    else:
        assert isinstance(mapped, SourceDataPending)
    assert 'submit:pending-buy' not in inner.calls


def test_proven_no_transport_restores_planned_identity_then_submits_once(conn):
    from sentinel.execution import executor, journal, recovery
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.states import CommandState as S
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    inner.missing = True
    broker = wrap(inner)
    planned = Command(identity=CommandIdentity(deployment=DEPLOYMENT,
        plan_id='quote-retry-plan', security_id=instrument().security_id),
        instrument=instrument(), side=Side.BUY, quantity=D(1))
    with pytest.raises(PreTransportAuthorityRefused) as caught:
        asyncio.run(executor._persist_and_send(conn, broker, planned))
    retained = journal.load_commands(conn, DEPLOYMENT)[0]
    assert retained.state is S.PLANNED
    assert retained.client_key == planned.client_key and retained.quantity == planned.quantity
    assert [row['to'] for row in journal.command_history(conn, planned.client_key)] == [
        'PLANNED', 'SEND_PENDING', 'PLANNED']
    with pytest.raises(ValueError, match='unused pre-transport'):
        broker.consume_not_transported(caught.value, recovery.prepare_send(retained))
    inner.missing = False
    result = asyncio.run(executor._persist_and_send(conn, broker, retained, already_planned=True))
    assert result.state is S.ACKNOWLEDGED and result.client_key == planned.client_key
    assert inner.calls.count('submit:'+planned.client_key) == 1


def test_inner_transport_refusal_cannot_issue_no_transport_proof(conn, monkeypatch):
    from sentinel.execution import executor, journal
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.states import CommandState as S
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    planned = Command(identity=CommandIdentity(deployment=DEPLOYMENT,
        plan_id='transport-plan', security_id=instrument().security_id),
        instrument=instrument(), side=Side.BUY, quantity=D(1))
    async def uncertain(**kwargs):
        inner.calls.append('submit:'+kwargs['client_key'])
        raise PreTransportAuthorityRefused('exception from inside transport is not proof')
    monkeypatch.setattr(inner, 'submit', uncertain)
    with pytest.raises(PreTransportAuthorityRefused):
        asyncio.run(executor._persist_and_send(conn, wrap(inner), planned))
    assert journal.load_commands(conn, DEPLOYMENT)[0].state is S.SEND_PENDING
    assert [row['to'] for row in journal.command_history(conn, planned.client_key)] == [
        'PLANNED', 'SEND_PENDING']


def test_generic_command_cannot_reset_pending_or_unknown_to_planned():
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.states import CommandState as S, IllegalTransition
    planned = Command(identity=CommandIdentity(deployment=DEPLOYMENT,
        plan_id='no-reset', security_id=instrument().security_id),
        instrument=instrument(), side=Side.BUY, quantity=D(1))
    for state in (S.SEND_PENDING, S.UNKNOWN):
        with pytest.raises(IllegalTransition):
            replace(planned, state=state).transition(S.PLANNED)


def test_missing_or_mismatched_membrane_proof_cannot_restore_a_command():
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    inner.missing = True
    broker = wrap(inner)
    command = Command(identity=CommandIdentity(deployment=DEPLOYMENT,
        plan_id='proof-bound-command', security_id=instrument().security_id),
        instrument=instrument(), side=Side.BUY, quantity=D(1))
    with pytest.raises(ValueError, match='unused pre-transport'):
        broker.consume_not_transported(PreTransportAuthorityRefused('unsealed'), command)
    with pytest.raises(PreTransportAuthorityRefused) as caught:
        asyncio.run(broker.submit(client_key=command.client_key, instrument=command.instrument,
                                  side=command.side, quantity=command.quantity))
    with pytest.raises(ValueError, match='unused pre-transport'):
        broker.consume_not_transported(caught.value, replace(command, quantity=D(2)))


def test_proof_cannot_overwrite_a_command_that_already_became_unknown(conn):
    from sentinel.execution import journal, recovery
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.states import CommandState as S
    inner = QuoteBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(minutes=3)
    inner.missing = True
    broker = wrap(inner)
    planned = Command(identity=CommandIdentity(deployment=DEPLOYMENT,
        plan_id='changed-checkpoint', security_id=instrument().security_id),
        instrument=instrument(), side=Side.BUY, quantity=D(1))
    pending = recovery.prepare_send(planned)
    journal.save_command(conn, planned)
    journal.save_command(conn, pending, previous=S.PLANNED)
    with pytest.raises(PreTransportAuthorityRefused) as caught:
        asyncio.run(broker.submit(client_key=pending.client_key, instrument=pending.instrument,
                                  side=pending.side, quantity=pending.quantity))
    journal.save_command(conn, recovery.promote_to_unknown(pending), previous=S.SEND_PENDING)
    with pytest.raises(ValueError, match='checkpoint changed'):
        journal.restore_proven_unsent(conn, pending, broker=broker, refusal=caught.value)
    conn.rollback()
    assert journal.load_commands(conn, DEPLOYMENT)[0].state is S.UNKNOWN
