"""Independent fixed-state truth table and explicit overnight ownership oracles."""
from dataclasses import dataclass
import itertools
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.recovery_stress import market, model
from research.recovery_stress.sources import load


def selected(module, name):
    path = os.environ.get(f"RECOVERY_STRESS_MUTANT_{name}")
    if not path:
        return module
    namespace = {"__name__":"isolated_recovery_mutant"}
    exec(compile(Path(path).read_text(),path,"exec"),namespace)
    return SimpleNamespace(**namespace)


@pytest.fixture(scope="module")
def helpers(tmp_path_factory):
    return load(tmp_path_factory.mktemp("sources"))


def candidate(helpers):
    return selected(model,"MODEL").probe(helpers[1][1]).Candidate


def seeded(cls, streak=7, latched=False):
    value = cls()
    value.episode = True
    value.recent_positive_streak = streak
    value.latched = latched
    return value


def test_full_release_uses_three_positive_signs_not_return_ranking(helpers):
    cls = candidate(helpers)
    # Separately catch each former relative comparator.
    for leaders, spy, core in ((.02,.20,.03),(.20,.02,.03),(.02,.02,.30)):
        result = seeded(cls).step(1.,1.,-.05,leaders,-.05,spy,core)
        assert result[0] == 1.
        assert result[1] == "FULL_RISK_CERTIFIED_CROSS_SURFACE"


def test_independent_truth_table_and_fixed_state_monotonicity(helpers):
    cls = candidate(helpers)
    core_values = (-.05,0.,.001,.01,.03,.30)
    # 2*2*3*4*4=192 distinct prior/input states, six ordered Core inputs each.
    for native, latched, streak, leaders, spy in itertools.product(
            (0.,1.),(False,True),(0,6,7),(-.02,0.,.02,None),(-.02,0.,.02,None)):
        outcomes = []
        for core in core_values:
            positive_leaders = leaders is not None and leaders > 0
            allowed = (native == 1 and streak >= 7 and positive_leaders
                       and spy is not None and spy > 0 and core > 0)
            expected = (.55 if latched else 1.) if allowed else 0.
            got = seeded(cls,streak,latched).step(native,1.,-.05,leaders,-.05,spy,core)[0]
            assert got == expected, (native,latched,streak,leaders,spy,core)
            outcomes.append(got)
        assert outcomes == sorted(outcomes), "stronger Core cannot worsen a fixed-state release"


@pytest.mark.parametrize("field",["leaders","spy","core"])
@pytest.mark.parametrize("value",[None,float("nan"),float("inf"),0.,-.01])
def test_missing_nonfinite_and_nonpositive_refuse_cross_route(helpers,field,value):
    values = dict(leaders=.02,spy=.02,core=.03)
    values[field] = value
    got = seeded(candidate(helpers)).step(1.,1.,-.05,values["leaders"],-.05,values["spy"],values["core"])
    assert got[0] == 0.


def test_native_and_persistence_contracts_unchanged(helpers):
    cls = candidate(helpers)
    for native in (0.,1.):
        value = seeded(cls)
        value.full_streak = 7
        assert value.step(native,1.,-.05,.02,.02,None,None)[0] == native
    value = seeded(cls,6)
    assert value.step(1.,1.,-.05,.02,-.05,.02,.30)[0] == 0.
    assert value.step(1.,1.,-.05,.02,-.05,.02,.30)[0] == 1.


def test_checkpoint_identity_and_restart(helpers):
    _, (_, parameters, _, _, _), _ = helpers
    changed = selected(model,"MODEL").probe(parameters)
    current = parameters.ProbeController("current")
    assert changed.identity != current.identity
    with pytest.raises(ValueError,match="identity"):
        changed.restore(current.snapshot())
    changed.candidate = seeded(changed.Candidate)
    before = json.loads(json.dumps(changed.snapshot()))
    resumed = selected(model,"MODEL").probe(parameters)
    resumed.restore(before)
    stimulus = dict(observation=dict(shadow_drawdown=-.05,shadow_r5=.01,shadow_r10=.02,
        shadow_r20=.03,shadow_r40=.02,damaged_breadth=.2,green_breadth=.7,
        damaged_breadth_delta5=0.,spy_r20=.02,spy_vol_ratio=0.,stops20=0,shadow_nav=100000.),
        leadership=dict(recent_r20=.02,recent_r40=-.05))
    assert changed.step(stimulus) == resumed.step(stimulus)
    assert changed.snapshot() == resumed.snapshot()


@dataclass
class Bar:
    security_id: str
    raw_open: float
    raw_close: float
    signal_close: float


@dataclass
class Publication:
    bars: list
    spy_closeadj: list


def test_gap_is_overnight_preserves_intraday_and_future_price_level():
    active = selected(market,"MARKET")
    publication = Publication([Bar("A",100.,110.,110.)],[100.,102.])
    prices = SimpleNamespace(prices={"A":110.},spy=[100.,102.])
    output = active.apply_opening_loss(publication,prices,{"A":.8},.94)
    assert output.bars[0].raw_open == 80.
    assert output.bars[0].raw_close == 88.
    assert output.bars[0].signal_close == 88.
    assert output.bars[0].raw_close/output.bars[0].raw_open == 1.1
    assert prices.prices["A"] == 88.
    assert prices.spy[-1] == 102.*.94
    assert output.spy_closeadj[-1] == prices.spy[-1]
    assert publication.bars[0].raw_open == 100.
    # Ten shares held BEFORE the opening trade lose $200 overnight; a sale at
    # the open cannot erase that. The remaining 10% intraday gain is separate.
    assert 10*(output.bars[0].raw_open-100.) == -200.


def test_stress_waits_for_executed_bridge_and_has_frozen_duration():
    ids, held = ("A","B","C","D"),("B","C")
    assert market.multipliers("overnight_gap",4,None,ids,held) == ({},1.)
    assert market.multipliers("overnight_gap",4,5,ids,held) == ({},1.)
    assert market.multipliers("overnight_gap",5,5,ids,held) == (dict.fromkeys(ids,.8),.94)
    assert market.multipliers("overnight_gap",6,5,ids,held) == ({},1.)
    assert market.multipliers("relapse",14,5,ids,held)[0] == dict.fromkeys(ids,.97)
    assert market.multipliers("relapse",15,5,ids,held) == ({},1.)
    assert market.multipliers("changing_holdings",5,5,ids,held) == ({"B":.65},.97)


def test_source_transformation_refuses_different_parent():
    with pytest.raises(ValueError,match="predicate"):
        model.transformed("no known recovery predicate")


def test_open_sale_cannot_erase_loss_on_prior_ownership():
    from decimal import Decimal as D
    from research.recovery_stress.audit import reconcile
    # $1,000 in ten shares gaps to $800; liquidating at the open leaves $799.20
    # after 10bp fees, even though the account holds zero shares at the close.
    row = dict(prices={"A":dict(open="80",close="88")},accounts={"bridge":dict(
        before=dict(cash="0",shares={"A":"10"},fees="0"),
        after=dict(cash="799.20",shares={},fees=".80"),
        execution=dict(opening_nav=800.,trades=[["A","-10","80"]]),close_nav="799.20")})
    result = reconcile(row,{"A":D(100)},{"A":D(100)})["bridge"]
    assert D(result["overnight"]) == -200
    assert D(result["additional_shock_loss"]) == -200
    assert D(result["intraday"]) == 0
    row["accounts"]["bridge"]["close_nav"] = "999.20"
    with pytest.raises(AssertionError):
        reconcile(row,{"A":D(100)},{"A":D(100)})
