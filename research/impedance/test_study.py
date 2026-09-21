"""Economic and structural falsifiers, not historical performance acceptance."""
from fractions import Fraction

import pytest

from research.impedance.holdings import capital_probe, fixture, measure, turnover_probe
from research.impedance.study import Input, entry_probes, observations, recovery_probes, run_paths, saturation_grid


@pytest.fixture(scope="module")
def paths():
    return run_paths()


def test_saturation_has_independent_bounded_fraction_oracle():
    for row in saturation_grid():
        remaining=1-Fraction(row['prior_damaged'],row['held'])
        assert row['max_attainable_delta']==pytest.approx(float(remaining))
        # All other gates pass. Exact fraction arithmetic supplies the oracle.
        assert row['fast']==(remaining>=Fraction(3,10))
        assert row['target']==(0. if remaining>=Fraction(3,10) else 1.)


def test_more_preexisting_damage_can_remove_protection(paths):
    assert paths['abrupt_shock']['first_native_defense_close']==0
    assert paths['already_damaged']['first_native_defense_close'] is None
    assert paths['already_damaged']['alternative_first_eligibility_close']['five_session_confirmation_memory'] is None


def test_phase_memory_repairs_only_bounded_delay(paths):
    key='five_session_confirmation_memory'
    assert paths['market_confirmation_late']['first_fast_signal'] is None
    assert paths['market_confirmation_late']['alternative_first_eligibility_close'][key]==6
    assert paths['market_confirmation_expired']['alternative_first_eligibility_close'][key] is None


def test_memory_never_bypasses_current_damage():
    # Prior acceleration/volatility evidence must not authorize healthy prices.
    path=[Input(100.,.2,.6,.02,0.)]*60+[Input(88.,1.,0.,-.04,.2),Input(100.,.2,.6,.02,0.)]
    rows=entry_probes(list(observations(path)))
    assert rows[-2]['five_session_confirmation_memory']
    assert not rows[-1]['five_session_confirmation_memory']


def test_persistent_route_exposes_false_exit_tradeoff(paths):
    key='persistent_impairment_addition'
    assert paths['four_session_correction']['alternative_first_eligibility_close'][key] is None
    assert paths['eight_session_correction']['alternative_first_eligibility_close'][key]==4
    assert paths['already_damaged']['alternative_first_eligibility_close'][key]==4
    assert paths['healthy']['alternative_first_eligibility_close'][key] is None


def test_persistence_requires_consecutive_not_accumulated_sessions():
    good=Input(100.,.2,.6,.02,0.)
    bad=Input(88.,1.,0.,-.04,.2)
    path=[good]*60+[bad]*4+[good]+[bad]*4
    assert not any(r['persistent_impairment_addition'] for r in entry_probes(list(observations(path))))


def test_deep_plateau_does_not_mean_additional_slow_loss(paths):
    p=paths['deep_plateau']
    assert p['first_native_defense_close'] is None
    assert p['trace'][-1]['base_duration']==30
    assert p['trace'][-1]['base_anchor']==80.
    assert p['trace'][-1]['nav']==80.
    assert p['alternative_first_eligibility_close']['persistent_impairment_addition']==4


def test_gradual_decline_eventually_enters_slow_defense(paths):
    p=paths['gradual_decline']
    first=p['first_slow_signal']
    assert first is not None
    # At least thirty observations from an ordinary-stress anchor, not day one.
    assert first>=29 and p['trace'][first]['base_duration']==30
    assert p['trace'][first]['nav']/p['trace'][first]['base_anchor']-1<=-.02
    assert p['alternative_first_eligibility_close']['drop_damage_acceleration'] is None


def test_core_quantity_changes_do_not_change_count_breadth():
    a=capital_probe()
    tiny,large=a['tiny_damaged'],a['large_damaged']
    assert tiny['damage_fraction']==large['damage_fraction']==18/20
    assert tiny['damaged_capital_fraction_of_stocks']==pytest.approx(18*80/(18*80+2*110*1000))
    assert large['damaged_capital_fraction_of_stocks']==pytest.approx(18*80*1000/(18*80*1000+2*110))
    assert tiny['damaged_capital_fraction_of_stocks']<.01
    assert large['damaged_capital_fraction_of_stocks']>.99


def test_cash_dilutes_stock_exposure_without_relabeling_breadth():
    state,feed,spy,keys=fixture()
    before=measure(state,feed,spy,keys)
    state.cash=3*before['stock_value']
    after=measure(state,feed,spy,keys)
    assert after['damage_fraction']==before['damage_fraction']
    assert after['invested_fraction']==.25
    assert .55*after['invested_fraction']==.1375


def test_canonical_sales_improve_breadth_without_price_recovery():
    p=turnover_probe();before,after=p['before'],p['after']
    assert p['first_close_fills']==0 and p['next_open_fills']==10
    assert before['damage_fraction']==.5 and after['damage_fraction']==0.
    assert after['held']==10 and after['green_fraction']==1.
    assert after['stock_value']==10*110
    assert after['cash']==pytest.approx(10*60*(1-Fraction(10,10000)))
    assert p['fees']==pytest.approx(.6)
    assert after['nav']==pytest.approx(before['nav']-.6)
    assert p['actual_stock_fraction_at_core_multiplier_055']==pytest.approx(.55*1100/1699.4)


def test_recovery_can_release_on_leadership_while_owned_core_remains_weak():
    r=recovery_probes()
    weak=r['weak_core_strong_leadership']['trace']
    assert all(x['target']==0. for x in weak[:7])
    assert weak[7]['target']==1.
    assert weak[7]['reason']=='FULL_RISK_CERTIFIED_PERSISTENCE'
    assert all(x['target']==0. for x in r['strong_core_weak_leadership']['trace'])
