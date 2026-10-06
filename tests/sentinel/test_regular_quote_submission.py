"""Fresh quote and funding guards are checked at real broker transport seam."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel.execution.contract import Side
from sentinel.execution.guarded import GuardedExecutionBroker, PreTransportAuthorityRefused
from sentinel.execution.opening_prices import RegularQuotes
from sentinel.feed import calendar
from tests.sentinel.test_opening_submit_freshness_boundary import ClockedBroker, wrap, instrument


class QuoteBroker(ClockedBroker):
    def __init__(self):
        super().__init__()
        self.capabilities = replace(self.capabilities, regular_session_quote_prices=True,
                                    regular_session_open_prices=True)
        self.quote_age = 0
        self.cash = D('1000')
        self.ask = D('100')
        self.wrong_identity = False

    async def opening_prices(self, *, session, instruments):
        self.calls.append('quote-read')
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
