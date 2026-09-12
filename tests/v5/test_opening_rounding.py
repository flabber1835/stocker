"""Execution must preserve the frozen book at numerical share boundaries."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from sentinel.authority import RolloutMode, RolloutState
from sentinel.core.decision import build_execution_plan
from sentinel.execution import opening_sizing
from stock_strategy_shared.wealth_core import v5
from stock_strategy_shared.wealth_core.adapter import PendingOrder, step_session
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.sentinel.test_production_decision import (
    _account, _binding, _observation, _publication,
    DECISION_SESSION, EFFECTIVE_SESSION,
)
from tests.v5.test_opening import base, case, prices


def compare_opening(*, equity, price, cash=None, entries=1, sale=False,
                    sale_price=100., split=1., receivables=()):
    env, _ = case(cash=equity if cash is None else cash,
                  entries=entries, sale=sale)
    intended, _ = v5.admission(equity=equity, cash=equity, price=price)
    for item in env.pending:
        if item.get('intended_dollars') is not None:
            item['intended_dollars'] = intended
    env.last_evidence['wealth_core']['estimated_equity'] = equity
    ledger = Ledger()
    ledger.receivables = deepcopy(list(receivables))
    env.ledger = ledger.to_dict()
    all_ids = {item['security_id']: item['ticker'] for item in env.pending}
    plan = build_execution_plan(
        env, _binding(), _publication(), _account(equity=str(equity)),
        _observation(), {sid: D(str(price)) for sid in all_ids}, all_ids,
        DECISION_SESSION, EFFECTIVE_SESSION, defensive_security=None,
        rollout_state=RolloutState(mode=RolloutMode.CONTROLLER, version=1,
                                  certificate_sha256='a'*64)).plan
    multipliers = {'SEC-X': D(str(split))} if split != 1. else {}
    evidence = ({'security_id': 'SEC-X', 'session': EFFECTIVE_SESSION.isoformat(),
                 'source_row_id': 'split', 'action': 'split',
                 'value': str(split), 'canonical_multiplier': str(split)},) if multipliers else ()
    before = env.to_dict()
    projected = opening_sizing.resolve(
        env, plan, base(env, plan, multipliers=multipliers, evidence=evidence),
        prices(env, plan, price=str(price), sale_price=str(sale_price)))
    book = PortfolioState.from_dict(env.wealth_core)
    result = step_session(
        session=EFFECTIVE_SESSION.isoformat(), state=book,
        bars=[DailyBar(
            sid, ticker, 'issuer-'+sid, EFFECTIVE_SESSION.isoformat(),
            signal_close_split_adj_div_unadj=price,
            raw_open=sale_price if sid == 'SEC-X' else price,
            raw_mark_close=sale_price if sid == 'SEC-X' else price,
            split_ratio=split if sid == 'SEC-X' else 1., tradeable=True)
            for sid, ticker in all_ids.items()],
        security_bars=[], pending=[PendingOrder.from_dict(p) for p in env.pending],
        ledger=ledger, last_known={}, cfg=v5.config(),
        strategy_id=env.strategy_identity['strategy'], strategy_version=1)
    buys = {row['security_id']: row['shares'] for row in result.fills
            if row['operation'] == 'OPEN_SLOT_POSITION'}
    for entry in projected.opening_sizing['entries']:
        sid = entry['security_id']
        assert D(entry['core_shares']) == buys.get(sid, 0)
        assert projected.target_basket[sid] == buys.get(sid, 0)
    assert float(projected.opening_sizing['cash_after_entries']) == book.cash
    assert env.to_dict() == before
    return buys, projected


@pytest.mark.parametrize('equity,price,expected', [
    (103283.18, 51.59, 99), (2682.68, 1.34, 99),
    (2702.7, 1.35, 99), (4824.82, 2.41, 100), (4944.94, 2.47, 100),
])
def test_admitted_dollars_match_canonical_whole_share_boundaries(equity, price, expected):
    buys, _ = compare_opening(equity=equity, price=price)
    assert buys == {'SEC-AAA': expected}


@pytest.mark.parametrize('cash,price', [(.1001, .01), (100.1, 1.), (5164.159, 51.59),
                                        (241.241, 2.41), (232.45, 166.92)])
def test_cash_limited_opening_uses_canonical_affordability(cash, price):
    compare_opening(equity=200000., cash=cash, price=price, entries=2)


@pytest.mark.parametrize('split', [1., .5, 1./30.])
def test_sale_funding_and_repeated_entries_preserve_float_cash_order(split):
    compare_opening(equity=103283.18, cash=5164.159, price=51.59,
                    entries=2, sale=True, sale_price=517.517, split=split)


def test_due_dividends_settle_in_canonical_order_before_sizing():
    receivables = [{'security_id': sid, 'ticker': sid, 'amount': amount,
                    'accrued_session': '2026-08-10', 'due_in': due}
                   for sid, amount, due in [('Z', .000000001, 0),
                                            ('A', 5164.159, 0),
                                            ('LATER', 1000., 1)]]
    compare_opening(equity=200000., cash=.000000001, price=51.59,
                    entries=2, receivables=receivables)
