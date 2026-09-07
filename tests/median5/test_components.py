from copy import deepcopy
from dataclasses import asdict
import json
import random

import pytest

from sentinel.controller import median5
from sentinel.controller.machine import Controller, Observation
from stock_strategy_shared.wealth_core.median5 import fresh, rank
from stock_strategy_shared.wealth_core.signals import DurableScore
from .oracle import namespace


def test_native_controller_against_frozen_reference():
    reference = namespace()["Native"]()
    controller = Controller(median5.load())
    state = controller.initial_state()
    rng = random.Random(1756)
    for day in range(1500):
        # Long stress/recovery blocks exercise all persistent branches.
        phase = day % 180
        dd = -0.22 if 30 <= phase < 100 else -0.03
        r20 = -0.06 if 30 <= phase < 95 else 0.035
        dam = 0.95 if 30 <= phase < 90 else 0.60
        r40 = rng.choice([-0.10, -0.05, 0.02, None])
        values = (dd, -0.08, -0.12, r20, r40, dam, 0.10 if dam > .8 else .30,
                  .35, -.04, .2, 1, 100_000*(1+day*.0001))
        expected, fast, slow = reference.step(values)
        obs = Observation(str(day).zfill(6), shadow_nav=values[11], shadow_drawdown=dd,
                          shadow_r5=values[1], shadow_r10=values[2], shadow_r20=r20,
                          shadow_r40=r40, damaged_breadth=dam, green_breadth=values[6],
                          damaged_breadth_delta5=.35, spy_r20=-.04, spy_vol_ratio=.2, stops20=1)
        state, decision = controller.step(observation=obs, state=state)
        assert decision.target_core_exposure == expected, (day, values, state, reference.__dict__)
        if day % 19 == 0:
            state = json.loads(json.dumps(state))


def test_candidate_a_differential_and_restart():
    reference = namespace()["CandidateA"]()
    state = median5.fresh()
    rng = random.Random(579)
    for day in range(4000):
        native = rng.choice([0., .55, .65, 1., 1., 1.])
        wcdd = rng.choice([None, -.10, -.20, -.099])
        recent20 = rng.choice([None, -.085, -.12, .02, .08])
        recent40 = rng.choice([None, -.04, .02])
        spy20 = rng.choice([None, -.01, 0., .11, .12])
        wc20 = rng.choice([None, -.04, .01, .04])
        expected, reason = reference.step(native, state["effective_native"], wcdd, recent20, recent40, spy20, wc20)
        state, decision = median5.recover(state=state, native=native, wc_drawdown=wcdd,
            recent_r20=recent20, recent_r40=recent40, spy_r20=spy20, wc_r20=wc20)
        assert (decision["desired_allocation"], decision["reason"]) == (expected, reason)
        assert state["full_streak"] == reference.full_streak
        assert state["recent_positive_streak"] == reference.recent_positive_streak
        state = json.loads(json.dumps(state))


def test_rank_history_precedes_freshness_and_vacancy():
    def rows(ids, negative=()):
        return [DurableScore(sid, sid, .5, -.1 if sid in negative else .1,
                             .2, float(10-i), True, "") for i, sid in enumerate(ids)]
    state = fresh()
    for _ in range(4):
        rank(rows("CBAD"), state)
    # B is filtered only after taking/reordering the current top three.
    assert [x.security_id for x in rank(rows("ABCD", "B"), state)] == ["C", "A", "D"]
    rank([], state)
    assert state["rank_history"][-1] == []


def test_old_slots_cannot_be_relabelled_as_median5():
    from sentinel.core.session import SessionState
    from sentinel.core.decision import runtime_strategy_identity
    cfg = median5.load()
    env = SessionState.fresh(starting_cash=1e6, controller=Controller(cfg),
                             strategy_identity=runtime_strategy_identity(cfg))
    raw = env.to_dict()
    assert len(raw["wealth_core"]["slots"]) == 20
    assert SessionState.from_dict(raw).to_dict() == raw
    del raw["wealth_core"]["median5"]
    with pytest.raises(ValueError, match="Median-5 state requires"):
        SessionState.from_dict(raw)


def test_authority_and_execution_use_one_production_strategy():
    from sentinel.cli.authority import _current_system_identities
    from sentinel.paper.preparation import _default_paper_strategy
    from sentinel.shadow_runtime import _strategy
    _runtime, authority = _current_system_identities()
    assert authority == _default_paper_strategy()[1] == _strategy()[1]
