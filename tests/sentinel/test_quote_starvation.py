"""Real journal/membrane proof: an unsent quote defect defers only its name."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import inspect

import pytest

from sentinel.execution import executor, journal
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument
from sentinel.execution.guarded import OrderEvidenceNotReady, PreTransportAuthorityRefused
from sentinel.execution.opening_prices import OpeningPriceNotReady, RegularQuotes
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState
from sentinel.feed import calendar
import test_paper_activation as activation
from test_opening_submit_freshness_boundary import ClockedBroker, wrap

pg, conn = activation.pg, activation.conn


class QuotedBroker(ClockedBroker):
    mode = 'quote'

    async def opening_prices(self, *, session, instruments):
        sid = next(iter(instruments))
        if sid == 'SEC-AAA' and self.mode == 'quote':
            raise OpeningPriceNotReady('no fresh quote for AAA')
        if sid == 'SEC-AAA' and self.mode == 'malformed':
            raise ValueError('wrong native quote identity')
        opened, _ = calendar.session_window(session)
        amount = D(10000) if sid == 'SEC-AAA' and self.mode == 'funding' else D(10)
        return RegularQuotes(session=session,opening_at=opened,observed_at=self.now,
            prices={sid:amount},bids={sid:amount-D(1)},quoted_at={sid:self.now},
            symbols={sid:instruments[sid].symbol},broker_ids={sid:instruments[sid].broker_id})

    async def submit(self, **kwargs):
        if kwargs['instrument'].security_id == 'SEC-AAA' and self.mode == 'impostor':
            await super().submit(**kwargs)
            raise OrderEvidenceNotReady('inner transport pretended not to send')
        return await super().submit(**kwargs)


def setup(conn, mode):
    bound = activation._bind(conn)
    inner = QuotedBroker(account=BrokerAccountIdentity(bound.broker,bound.broker_account_id),cash=D(1000))
    inner.capabilities = replace(inner.capabilities,regular_session_quote_prices=True,
        regular_session_open_prices=True)
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened+timedelta(seconds=60)
    inner.mode = mode
    instruments = {sid:BrokerInstrument(sid,sid.removeprefix('SEC-'),'sim-asset-'+sid)
        for sid in ('SEC-AAA','SEC-BBB')}
    plan = ExecutionPlan('quote-readiness-test',inner.now.date(),inner.now.date(),D(1),
        target_basket={sid:D(1) for sid in instruments},deployment_id=bound.deployment_id,
        broker=bound.broker,broker_account_id=bound.broker_account_id,takeover_epoch=bound.takeover_epoch)
    executor.adopt_plan(conn,plan)
    return bound, inner, wrap(inner), instruments, plan


def execute(conn, bound, broker, instruments, plan):
    return asyncio.run(executor.execute_session(conn=conn,broker=broker,deployment=bound.identity,
        instruments=instruments,plan=plan,today=plan.effective_session))


@pytest.mark.parametrize('mode',['quote','funding'])
def test_unavailable_first_leg_preserves_key_and_does_not_starve_later_ready_leg(conn,mode):
    bound, inner, broker, instruments, plan = setup(conn,mode)
    result = execute(conn,bound,broker,instruments,plan)
    commands = {c.security_id:c for c in journal.load_commands(conn,bound.identity)}
    assert [c.security_id for c in result.submitted] == ['SEC-BBB']
    assert result.deferred == ('SEC-AAA',)
    assert 'AAA' in result.deferral_reasons['SEC-AAA']
    assert commands['SEC-AAA'].state is CommandState.PLANNED
    assert commands['SEC-BBB'].state is CommandState.ACKNOWLEDGED
    original = commands['SEC-AAA'].client_key
    assert 'submit:'+original not in inner.calls
    inner.fill(commands['SEC-BBB'].client_key)
    inner.mode = 'ready'
    retry = execute(conn,bound,broker,instruments,plan)
    assert [c.client_key for c in retry.submitted] == [original]
    assert not retry.deferred
    assert inner.calls.count('submit:'+original) == 1


@pytest.mark.parametrize('mode',['malformed','impostor'])
def test_integrity_or_after_transport_imitation_never_continues_basket(conn,mode):
    bound, inner, broker, instruments, plan = setup(conn,mode)
    with pytest.raises(PreTransportAuthorityRefused):
        execute(conn,bound,broker,instruments,plan)
    commands = journal.load_commands(conn,bound.identity)
    assert len(commands) == 1 and commands[0].security_id == 'SEC-AAA'
    assert commands[0].state is (CommandState.SEND_PENDING if mode=='impostor' else CommandState.PLANNED)
    assert not any('SEC-BBB' in call for call in inner.calls if call.startswith('submit:'))


def test_quote_deferral_falsifier_detects_removed_proof_backed_branch(conn,monkeypatch):
    source = inspect.getsource(executor._persist_and_send)
    broken = source.replace('if isinstance(exc, OrderEvidenceNotReady):','if False:')
    assert broken != source
    namespace = dict(vars(executor))
    exec(compile(broken,'quote-deferral-falsifier','exec'),namespace)
    monkeypatch.setattr(executor,'_persist_and_send',namespace['_persist_and_send'])
    with pytest.raises(OrderEvidenceNotReady):
        test_unavailable_first_leg_preserves_key_and_does_not_starve_later_ready_leg(conn,'quote')
