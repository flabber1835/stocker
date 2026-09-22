import copy
from decimal import Decimal

import pytest

from research.owned55_replay.model import (
    Owned55, digest, helper, oracle, owned55_rule, parent_rule, update_metrics, validate_resume,
)


def row(day, *, dd=-.11, damage=.9, green=.1, r20=-.1):
    ns, _ = helper()
    observation = dict(zip(ns["FIELDS"], (dd, -.01, -.02, r20, -.1, damage, green, 0., 0., 0., 0, 90.)))
    return dict(session=day, observation=observation,
                leadership=dict(recent_r20=0., recent_r40=0.))


def test_only_parent_active_ceiling_changes():
    parent, parent_sha = parent_rule()
    rule, actual_sha = owned55_rule()
    assert actual_sha == parent_sha
    assert parent["active_ceiling"] == 0.
    assert rule == parent | {"active_ceiling": .55}
    assert {key for key in rule if rule[key] != parent[key]} == {"active_ceiling"}


def test_enters_on_fifth_bad_close_at_partial_ceiling_and_restarts():
    ns, _ = helper()
    policy = Owned55(ns["ProbeController"]("current"))
    for index in range(5):
        before = policy.snapshot()
        result = policy.step(row(f"2011-08-{index+1:02d}"))
        restored = Owned55(ns["ProbeController"]("current"))
        restored.restore(before)
        assert restored.step(row(f"2011-08-{index+1:02d}")) == result
        assert restored.snapshot() == policy.snapshot()
        assert result["target"] == (.55 if index == 4 else 1.)
    assert result["active"] and result["reason"] == "OWNED_IMPAIRMENT_ENTER"


def test_existing_zero_cause_remains_zero():
    ns, _ = helper()
    policy = Owned55(ns["ProbeController"]("current"))
    policy.active = True
    for index in range(15):
        observation = dict(zip(ns["FIELDS"], (-.2, -.06, -.11, -.12, -.1, .9, .1, .31, -.02, .05, 0, 80.)))
        result = policy.step(dict(session=f"2012-01-{index+1:02d}", observation=observation,
                                  leadership=dict(recent_r20=-.1, recent_r40=-.1)))
    assert result["base"]["target"] == 0.
    assert result["target"] == 0.


def test_release_requires_eighth_owned_healthy_close():
    ns, _ = helper()
    policy = Owned55(ns["ProbeController"]("current"))
    policy.active = True
    for index in range(8):
        result = policy.step(row(f"2013-02-{index+1:02d}", dd=-.05, damage=.6, green=.3, r20=.01))
        assert result["target"] == (1. if index == 7 else .55)
    assert not result["active"] and result["reason"] == "OWNED_RECOVERED"


def test_exit_pays_for_overnight_loss_before_partial_reallocation():
    previous = dict(strategy_nav="100", last_session="2006-07-31", pending_allocation=".55",
        held_allocation="1", parent_core_close_equity="100")
    result = dict(parent_core_open_equity="80", parent_core_close_equity="120",
        bil_open_adjusted="1.01", bil_close_adjusted="1.0302",
        bil_previous_close_adjusted_current_publication="1")
    expected_open = Decimal("80")*(1-Decimal(".001")*Decimal(".45"))
    assert oracle(previous, result) == expected_open*(Decimal(".55")*Decimal("1.5") + Decimal(".45")*Decimal("1.02"))


def test_measurement_uses_july_close():
    assert update_metrics({}, "2006-07-28", "92500") == {}
    measured = update_metrics({}, "2006-07-31", "90000")
    measured = update_metrics(measured, "2026-07-31", "180000")
    assert Decimal(measured["multiple"]) == 2
    with pytest.raises(ValueError, match="baseline"):
        update_metrics({}, "2006-08-01", "100000")


def fixture():
    value = dict(binding={"rule": "owned55"}, cursor="2006-07-31",
                 economics={"last_session": "2006-07-31"})
    value["sha256"] = digest(value)
    return value


def test_resume_binding_cursor_and_commitment():
    value = fixture()
    assert validate_resume(value, value["binding"], value["cursor"]) == value
    with pytest.raises(ValueError, match="binding"):
        validate_resume(value, {"rule": "zero"}, value["cursor"])
    with pytest.raises(ValueError, match="cursor"):
        validate_resume(value, value["binding"], "2006-08-01")
    changed = copy.deepcopy(value)
    changed["economics"]["strategy_nav"] = "200000"
    with pytest.raises(ValueError, match="commitment"):
        validate_resume(changed, value["binding"], value["cursor"])
