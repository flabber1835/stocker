"""Run from the staged runtime, with this directory on pytest's explicit path."""
from __future__ import annotations

from datetime import date, timedelta
import json
import math
import random

import pytest

from sentinel.controller import champion_frozen, champion, median5
from sentinel.controller import champion_config as ex3_v6
from sentinel.controller.machine import Controller, Observation
from sentinel.core.session import SessionState
from sentinel.core.decision import runtime_strategy_identity


def observations(count):
    rng = random.Random(331352)
    for i in range(count):
        yield Observation(session=str(date(2006, 1, 3) + timedelta(days=i)),
            shadow_nav=100_000 * (1 + rng.random()),
            shadow_drawdown=rng.choice([None, -.155, -.10, -.06, -.03, 0.]),
            shadow_r5=rng.choice([None, -.05, -.04, .01]),
            shadow_r10=rng.choice([None, -.10, -.08, .01]),
            shadow_r20=rng.choice([None, -.085, -.03, 0., .01, .10]),
            shadow_r40=rng.choice([None, -.04, -.03, 0., .01]),
            damaged_breadth=rng.choice([0., .63, .75, .88, 1.]),
            green_breadth=rng.choice([0., .20, .25, .50]),
            damaged_breadth_delta5=rng.choice([None, 0., .30, .31]),
            spy_r20=rng.choice([None, -.01, 0., .11, .12]),
            spy_vol_ratio=rng.choice([None, 0., .04, .05]),
            stops20=rng.choice([0, 2, 3]))


def test_registered_runtime_and_restart_identity():
    from sentinel.paper.preparation import _default_paper_strategy
    cfg, identity = _default_paper_strategy()
    assert cfg.strategy_id == "sentinel-compact-champion-v1"
    assert identity["research_reference_source_sha256"] == "3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663"
    state = SessionState.fresh(starting_cash=100000, controller=Controller(cfg), strategy_identity=identity)
    assert len(state.wealth_core["slots"]) == 20
    assert SessionState.from_dict(json.loads(json.dumps(state.to_dict()))).state_hash == state.state_hash


def test_controller_attachment_matches_frozen_transitions_and_restarts():
    cfg = ex3_v6.load()
    controller = Controller(cfg)
    actual, overlay = controller.initial_state(), median5.fresh(champion=True)
    native, candidate = champion_frozen.Native(), champion_frozen.CandidateA()
    effective = previous = 1.
    rng = random.Random(352331)
    for i, ob in enumerate(observations(12000)):
        expected_native, fast, slow = native.step((ob.shadow_drawdown, ob.shadow_r5,
            ob.shadow_r10, ob.shadow_r20, ob.shadow_r40, ob.damaged_breadth,
            ob.green_breadth, ob.damaged_breadth_delta5, ob.spy_r20,
            ob.spy_vol_ratio, ob.stops20, ob.shadow_nav))
        actual, decision = controller.step(observation=ob, state=actual)
        assert decision.target_core_exposure == expected_native
        assert {k: actual[v] for k, v in champion.NATIVE_FIELDS.items()} == native.__dict__
        r20 = rng.choice([None, -.085, 0., .03, .12])
        r40 = rng.choice([None, -.04, -.03999999, .02])
        expected = candidate.step(expected_native, effective, ob.shadow_drawdown,
            r20, r40, ob.spy_r20, ob.shadow_r20)
        effective, previous = previous, expected_native
        overlay, result = ex3_v6.recover(state=overlay, native=expected_native,
            wc_drawdown=ob.shadow_drawdown, recent_r20=r20, recent_r40=r40,
            spy_r20=ob.spy_r20, wc_r20=ob.shadow_r20)
        assert (result["desired_allocation"], result["reason"]) == expected
        assert overlay["champion_audit"] == candidate._audit
        if i % 37 == 0:
            actual, overlay = json.loads(json.dumps([actual, overlay]))
            native = champion_frozen.Native.from_snapshot(native.snapshot())
            candidate = champion_frozen.CandidateA.from_snapshot(candidate.snapshot())


@pytest.mark.parametrize("field,value", [("ramp_active", True), ("_r40_history", [.01]),
                                        ("ordinary_stress_age", 21)])
def test_incompatible_native_state_is_rejected(field, value):
    controller = Controller(ex3_v6.load())
    state = controller.initial_state()
    state[field] = value
    with pytest.raises(ValueError):
        controller.step(observation=next(observations(1)), state=state)


def test_counter_corruption_and_missing_audit_are_rejected():
    state = median5.fresh(champion=True)
    state["full_streak"] = 9
    args = dict(native=1., wc_drawdown=0., recent_r20=.01, recent_r40=.01, spy_r20=0., wc_r20=.01)
    with pytest.raises(ValueError, match="snapshot"):
        ex3_v6.recover(state=state, **args)
    state = median5.fresh(champion=True)
    del state["champion_audit"]
    with pytest.raises(ValueError):
        ex3_v6.recover(state=state, **args)


def test_rebound_and_cleared_latch_follow_selected_champion():
    state = median5.fresh(champion=True)
    state.update(episode=True, previous_native=0., previous_desired=0.)
    after, decision = ex3_v6.recover(state=state, native=1., wc_drawdown=-.15,
        recent_r20=-.10, recent_r40=-.10, spy_r20=.12, wc_r20=-.01)
    assert after["episode"] and decision["desired_allocation"] == 0.
    assert "SPY_V_REBOUND" not in decision["reason"]


def test_rec8_requires_eight_sessions_and_strict_r40_recovery():
    state = median5.fresh(champion=True)
    state.update(latched=True, previous_desired=.55)
    def step(current, r40):
        return ex3_v6.recover(state=current, native=1., wc_drawdown=-.05,
            recent_r20=.02, recent_r40=r40, spy_r20=.01, wc_r20=.03)
    for _ in range(10):
        state, _ = step(state, -.04)
    assert state["full_streak"] == 0 and state["latched"]
    for _ in range(7):
        state, decision = step(state, math.nextafter(-.04, math.inf))
        assert decision["desired_allocation"] == .55
    state, decision = step(state, math.nextafter(-.04, math.inf))
    assert decision["desired_allocation"] == 1. and not state["latched"]
