"""Independent threshold, safety and adversarial checkpoint witnesses."""
from datetime import date, timedelta
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.recovery_bridge import model
from research.recovery_bridge.sources import load
from research.recovery_bridge.run import projection_view, reconcile, screen


@pytest.fixture
def bridge_type():
    mutant = os.environ.get("RECOVERY_BRIDGE_MUTANT_FILE")
    if not mutant:
        return model.RecoveryBridge
    namespace = {"__name__": "mutant_bridge"}
    exec(compile(Path(mutant).read_text(), mutant, "exec"), namespace)
    return namespace["RecoveryBridge"]


class Parent:
    identity = "controlled-cause-witness"

    def __init__(self, native=1., reason="FULL_RISK_HELD", ceiling=1.):
        self.native, self.reason, self.ceiling = native, reason, ceiling
        self.last_session = None

    def step(self, row):
        self.last_session = row["session"]
        return dict(native=self.native, base=dict(reason=self.reason),
                    target=0. if self.reason == "FULL_RISK_HELD" else min(self.native, self.ceiling),
                    ceiling=self.ceiling)

    def snapshot(self):
        return dict(last_session=self.last_session)

    def restore(self, value):
        self.last_session = value["last_session"]


def row(day, r20=.04, damage=.60, green=.25):
    return dict(session=(date(2020, 1, 1)+timedelta(days=day)).isoformat(),
        observation=dict(shadow_drawdown=-.05, shadow_r5=.01, shadow_r10=.02,
            shadow_r20=r20, shadow_r40=.01, damaged_breadth=damage, green_breadth=green,
            damaged_breadth_delta5=0., spy_r20=.01, spy_vol_ratio=0., stops20=0, shadow_nav=100000.),
        leadership=dict(recent_r20=-.02, recent_r40=-.06))


def test_exact_eighth_and_relapse(bridge_type):
    bridge = bridge_type(Parent())
    values = [bridge.step(row(day))["target"] for day in range(8)]
    assert values == [0.]*7 + [.55]
    assert bridge.step(row(8, r20=0))["target"] == 0.
    assert [bridge.step(row(day))["target"] for day in range(9,17)] == [0.]*7 + [.55]


@pytest.mark.parametrize("field,value", [("r20", None), ("r20", float("nan")),
    ("damage", None), ("green", None), ("r20", 0.), ("damage", .64), ("green", .19)])
def test_missing_or_unhealthy_resets(bridge_type, field, value):
    bridge = bridge_type(Parent())
    for day in range(7):
        bridge.step(row(day))
    assert bridge.step(row(7, **{field:value}))["streak"] == 0
    assert bridge.step(row(8))["target"] == 0.


def test_native_is_independent(bridge_type):
    parent = Parent(native=0.)
    bridge = bridge_type(parent)
    assert all(bridge.step(row(day))["target"] == 0 for day in range(15))
    parent.native = 1.
    assert [bridge.step(row(day))["target"] for day in range(15,23)] == [0.]*7 + [.55]
    parent.native = 0.
    assert bridge.step(row(23))["target"] == 0


def test_no_change_to_full_release_or_divergence(bridge_type):
    for reason, ceiling, expected in (("NORMAL", 1., 1.), ("LD_ENTER_DIVERGENCE", .55, .55),
                                      ("FULL_RISK_HELD|LD_ENTER_DIVERGENCE", .55, .55)):
        bridge = bridge_type(Parent(reason=reason, ceiling=ceiling))
        assert [bridge.step(row(day))["target"] for day in range(10)] == [expected]*10


def test_owned_cap_and_monotonic_recovery(bridge_type):
    # Counterfactual stronger owned r20 alone cannot lower bridge exposure.
    for r20 in (.001, .04, .25):
        bridge = bridge_type(Parent(ceiling=.40))
        values = [bridge.step(row(day, r20=r20))["target"] for day in range(8)]
        assert values == [0.]*7 + [.40]


def test_leaders_alone_cannot_qualify_owned_recovery(bridge_type):
    bridge = bridge_type(Parent())
    for day in range(12):
        stimulus = row(day, r20=-.01)
        stimulus["leadership"] = dict(recent_r20=.30, recent_r40=.50)
        assert bridge.step(stimulus)["target"] == 0.


def test_retained_legacy_full_release_is_not_globally_monotone(tmp_path, bridge_type):
    # Explicitly retain an adverse design limitation; this is NOT an acceptance
    # oracle claiming global monotonicity or permission to change the parent.
    _, parameters, _, owned, _ = load(tmp_path)
    targets = []
    for core_r20 in (.01, .03):
        parent = owned.Owned55(parameters.ProbeController("current"))
        parent.base.candidate.episode = True
        parent.base.candidate.recent_positive_streak = 7
        bridge = bridge_type(parent)
        bridge.streak = 7
        stimulus = row(0, r20=core_r20)
        stimulus["leadership"] = dict(recent_r20=.02, recent_r40=-.05)
        stimulus["observation"]["spy_r20"] = .02
        targets.append(bridge.step(stimulus)["target"])
    assert targets == [1., .55]


def test_resume_and_corruption(bridge_type):
    bridge = bridge_type(Parent())
    for day in range(20):
        before = json.loads(json.dumps(bridge.snapshot()))
        restarted = bridge_type(Parent())
        restarted.restore(before)
        stimulus = row(day, r20=0 if day == 10 else .04)
        assert restarted.step(stimulus) == bridge.step(stimulus)
        assert restarted.snapshot() == bridge.snapshot()
    changed = copy.deepcopy(bridge.snapshot())
    changed["streak"] = 1
    with pytest.raises(ValueError, match="commitment"):
        bridge_type(Parent()).restore(changed)
    changed = copy.deepcopy(bridge.snapshot())
    changed["identity"] = "other-rule"
    changed["sha256"] = model.digest({k:v for k,v in changed.items() if k != "sha256"})
    with pytest.raises(ValueError):
        bridge_type(Parent()).restore(changed)
    with pytest.raises(ValueError, match="advance"):
        bridge.step(row(19))


def test_real_native_entry_then_owned_bridge(tmp_path, bridge_type):
    _, parameters, _, owned, _ = load(tmp_path)
    bridge = bridge_type(owned.Owned55(parameters.ProbeController("current")))
    shock = row(0, r20=-.2, damage=1., green=0.)
    shock["observation"].update(shadow_drawdown=-.2, shadow_r5=-.1, shadow_r10=-.2,
        shadow_r40=-.2, damaged_breadth_delta5=.8, spy_r20=-.05, spy_vol_ratio=.2, shadow_nav=80000.)
    assert bridge.step(shock)["native"] == 0.
    results = [bridge.step(row(day)) for day in range(1,25)]
    native_clear = next(i for i,r in enumerate(results) if r["native"] == 1)
    first_bridge = next(i for i,r in enumerate(results) if r["bridge"])
    assert first_bridge-native_clear == 7
    assert all(r["owned"]["target"] == 0 for r in results)
    assert all(r["target"] == .55 for r in results[first_bridge:])


def test_prior_projection_view_does_not_mutate_core():
    prior = SimpleNamespace(wealth_core={"episodes":{"0":{"security_id":"A", "current_shares":10}}}, ledger={})
    bars = [SimpleNamespace(security_id="A", split_ratio=2)]
    view = projection_view(prior, bars)
    assert view.wealth_core["episodes"]["0"]["current_shares"] == "20"
    assert prior.wealth_core["episodes"]["0"]["current_shares"] == 10


def test_independent_money_oracle_rejects_free_shares():
    before = dict(cash="100", shares={}, fees="0")
    execution = dict(trades=[["A", "5", "10"]])
    after = dict(cash="49.95", shares={"A":"5"}, fees=".05")
    reconcile(before, after, execution, [])
    with pytest.raises(AssertionError, match="cash"):
        reconcile(before, dict(after, cash="50"), execution, [])
    with pytest.raises(AssertionError, match="share"):
        reconcile(before, dict(after, shares={"A":"6"}), execution, [])


def test_screen_needs_activity_and_rejects_adverse_budget():
    empty = dict(screen=dict(terminal_delta=0, drawdown_delta_pp=0, fee_delta=0), target_difference_days=[])
    panel = {"40":{"healthy":empty, "test":copy.deepcopy(empty)}}
    assert not screen(panel)["eligible_for_historical_followup"]
    panel["40"]["test"].update(target_difference_days=[12], screen=dict(terminal_delta=100, drawdown_delta_pp=0, fee_delta=1))
    assert screen(panel)["eligible_for_historical_followup"]
    panel["40"]["test"]["screen"]["drawdown_delta_pp"] = -2.01
    assert not screen(panel)["eligible_for_historical_followup"]


def test_timing_oracle_rejects_same_close_and_future_book():
    from research.recovery_bridge.audit import check_timing
    before = dict(session="2020-01-02", decisions={"current":{"target":0.}},
                  accounts={"current":{"after":{"cash":"100"}}})
    today = dict(session="2020-01-03", decisions={"current":{"target":1.}},
                 accounts={"current":{"source_session":"2020-01-02", "execution":{"target":0.},
                                      "before":{"cash":"100"}}})
    check_timing([before,today])
    today["accounts"]["current"]["execution"]["target"] = 1.
    with pytest.raises(AssertionError, match="same-close"):
        check_timing([before,today])
    today["accounts"]["current"]["execution"]["target"] = 0.
    today["accounts"]["current"]["source_session"] = "2020-01-03"
    with pytest.raises(AssertionError, match="future Core"):
        check_timing([before,today])
