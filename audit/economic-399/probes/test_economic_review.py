"""Audit-only counterexamples. A passing witness asserts the recorded defect."""
from decimal import Decimal, ROUND_HALF_EVEN
from copy import deepcopy
import json
import pytest
from sentinel.core import rolling_continuity as continuity
from sentinel import rolling_daily_checkpoint as cp
from tests.sentinel.test_rolling_daily import first, ready, conn, pg, source, operational_source, refresh, advance, resume

@pytest.mark.parametrize('factor,expect_refusal', [('0.5',False),('0.997123',True)])
def test_benchmark_scale_change_through_real_publication(conn, first, operational_source, monkeypatch, factor, expect_refusal):
    data=operational_source
    old=deepcopy(data['SFP'])
    scale=Decimal(factor)
    intervals=[]
    ratios=set()
    for row in data['SFP']:
        if row['ticker']!='SPY':continue
        before=Decimal(row['closeadj'])
        after=(before*scale).quantize(Decimal('0.0001'),rounding=ROUND_HALF_EVEN)
        assert abs(after-before*scale)<=Decimal('0.00005')
        intervals.append(((after-Decimal('0.00005'))/before,(after+Decimal('0.00005'))/before))
        ratios.add(after/before)
        row['closeadj']=str(after)
    assert max(lo for lo,hi in intervals)<=scale<=min(hi for lo,hi in intervals)
    # Only the benchmark's presentation scale was altered before append.
    for before,after in zip(old,data['SFP']):
        a,b=dict(before),dict(after)
        a.pop('closeadj');b.pop('closeadj')
        assert a==b
    published=refresh(conn,data,monkeypatch)
    assert published['data_version']>first.state.data_version
    if expect_refusal:
        with pytest.raises(continuity.RollingContinuityRefused,match='NONUNIFORM_BENCHMARK_REBASE: spy_total_return') as caught:
            advance(conn)
        assert cp.read(conn) is None
        assert resume(conn).state.state_hash==first.state.state_hash
        observed=str(caught.value)
    else:
        result=advance(conn)
        assert result.state.wealth_core['episodes']
        observed='DAILY_ADVANCED'
    print('AUDIT_WITNESS',json.dumps(dict(factor=factor,rows=len(intervals),distinct_observed_ratios=len(ratios),common_factor_verified=True,publication=published['data_version'],result=observed)))
