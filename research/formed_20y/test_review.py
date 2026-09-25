from copy import deepcopy
from decimal import Decimal as D

import pytest

from sentinel.feed.calendar import previous_sessions
from .inputs import START, END
from .review import performance


def rows():
    axis=[d for d in previous_sessions(END,6000) if d >= START]
    return [dict(session=day,spy=100,economics=dict(strategy_nav='50000',
        previous_strategy_nav='50000',parent_core_close_equity='60000',net_factor='1'))
        for day in axis]


def test_flat_full_axis_preserves_independent_cash_and_shadow_baselines():
    result=performance(rows())
    assert result['measured_sessions'] == 5032
    assert result['combined']['multiple'] == '1'
    assert result['shadow_core']['multiple'] == '1'
    assert result['combined']['cagr'] == 0
    assert result['independent_factor_product_final_nav'] == '50000'


@pytest.mark.parametrize('fault',['prefix','duplicate','reordered','invented_nav','first_close_return'])
def test_partial_or_incoherent_performance_is_not_a_twenty_year_result(fault):
    data=rows()
    if fault == 'prefix': data=data[:-1]
    elif fault == 'duplicate': data[1]=deepcopy(data[0])
    elif fault == 'reordered': data[1],data[2]=data[2],data[1]
    elif fault == 'invented_nav': data[-1]['economics']['strategy_nav']='100000'
    else: data[0]['economics']['net_factor']='1.01'
    with pytest.raises(ValueError): performance(data)
