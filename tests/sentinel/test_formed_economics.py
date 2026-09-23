"""Hand-calculated first-funded-open witnesses for a mature shadow book."""
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from sentinel.formed_economics import entry


def state(*, fees=0, shares=50):
    return SimpleNamespace(last_processed_session='2026-09-15',
        wealth_core={'episodes': {'0': dict(security_id='A', current_shares=shares)}},
        ledger={'events': [dict(session='2026-09-15', event_type='BUY', fees=fees),
                           dict(session='2026-09-14', event_type='BUY', fees=100)]})


@pytest.mark.parametrize('allocation,expected', [('1', '.9995'), ('.55', '.999275'), ('0', '.999')])
def test_flat_half_cash_book_pays_for_stock_and_bil_only(allocation, expected):
    # $10,000 Core = 50*$100 stocks + $5,000 cash. Stock entry costs $5;
    # BIL costs $10 per $10,000. Past formation fees must not enter again.
    result = entry(state(), {'A': '100'}, parent_open=D(10000), parent_close=D(10000),
                   allocation=D(allocation), bil_intraday=D(0))
    assert result['net_factor'] == D(expected)


def test_canonical_rotation_cost_is_replaced_by_one_funded_entry():
    # Imaginary old holdings cost $4 to sell and the new stocks cost $5 to buy.
    # The new account owns only the resulting $5,000 stock position; its entry
    # costs $5, not $9+$5, and it earns a $50 stock gain. Core NAV: 10000-9+50.
    result = entry(state(fees=9), {'A': '100'}, parent_open=D(10000), parent_close=D(10041),
                   allocation=D(1), bil_intraday=D(0))
    assert result['gross_factor'] == D('1.005')
    assert result['net_factor'] == D('1.0045')
    assert result['turnover'] == D('.5')


@pytest.mark.parametrize('marks', [{}, {'A': '0'}, {'A': 'NaN'}, {'A': '100', 'ALIEN': '2'}])
def test_missing_or_invented_opening_evidence_refuses(marks):
    with pytest.raises(ValueError):
        entry(state(), marks, parent_open=D(10000), parent_close=D(10000), allocation=D('.55'), bil_intraday=D(0))
