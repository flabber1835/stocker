"""The migration delta: legacy book out, Wealth Core book in.

The tests that matter are about the OVERLAP policy and about exposure scaling.
Both are places where a reasonable-looking shortcut produces a book that is
quietly wrong: keeping overlapping shares fabricates episode state, and scaling
membership instead of size turns Sentinel into a stock picker.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.core.migration import plan_migration  # noqa: E402

MARKS = {"AAA": 10.0, "BBB": 20.0, "CCC": 50.0, "DDD": 100.0}


def plan(**kw):
    base = dict(session="2026-08-10", broker_positions={}, target_weights={},
                marks=MARKS, account_equity=100_000.0)
    base.update(kw)
    return plan_migration(**base)


class TestTheOverlapPolicy:
    def test_an_overlapping_security_is_SOLD_AND_REBOUGHT(self):
        """An inherited position carries no episode — no entry price, no peak, no
        age. Fabricating those makes the 30% stop and the 119-session review
        wrong in the direction of LESS protection."""
        p = plan(broker_positions={"AAA": 100.0}, target_weights={"AAA": 0.04})
        assert [l.ticker for l in p.exits] == ["AAA"]
        assert [l.ticker for l in p.entries] == ["AAA"]
        assert [l.ticker for l in p.overlap] == ["AAA"]

    def test_the_churn_is_PRICED_not_assumed(self):
        """The decision not to retain overlap has a cost; showing it is what
        makes the trade-off reviewable rather than a preference."""
        p = plan(broker_positions={"AAA": 100.0, "BBB": 50.0},
                 target_weights={"AAA": 0.04, "BBB": 0.04})
        assert p.churn_notional == pytest.approx(100 * 10.0 + 50 * 20.0)

    def test_the_policy_is_stated_in_the_OUTPUT_not_just_the_code(self):
        p = plan(broker_positions={"AAA": 100.0}, target_weights={"AAA": 0.04})
        assert "SOLD AND REBOUGHT" in p.to_dict()["overlap"]["policy"]
        assert any("no episode" in c for c in p.caveats)

    def test_NO_overlap_produces_no_churn_and_no_caveat(self):
        p = plan(broker_positions={"AAA": 100.0}, target_weights={"BBB": 0.04})
        assert p.overlap == []
        assert p.churn_notional == 0.0
        assert not any("BOTH books" in c for c in p.caveats)


class TestExposureScalesSIZENotMEMBERSHIP:
    def test_a_partial_exposure_buys_EVERY_name_smaller(self):
        """Sentinel decides HOW MUCH of Wealth Core's book is held, never WHAT is
        in it. Scaling membership would make the controller a stock picker."""
        full = plan(target_weights={"AAA": 0.04, "BBB": 0.04, "CCC": 0.04})
        half = plan(target_weights={"AAA": 0.04, "BBB": 0.04, "CCC": 0.04},
                    target_exposure=0.55)
        assert [l.ticker for l in full.entries] == [l.ticker for l in half.entries]
        for f, h in zip(full.entries, half.entries):
            assert h.notional == pytest.approx(f.notional * 0.55)

    def test_zero_exposure_still_targets_the_same_NAMES(self):
        """0% Core is a size, not a liquidation of the target's identity — the
        shadow still holds everything, which is what lets the ramp restore."""
        p = plan(target_weights={"AAA": 0.04, "BBB": 0.04}, target_exposure=0.0)
        assert [l.ticker for l in p.entries] == ["AAA", "BBB"]
        assert all(l.notional == 0.0 for l in p.entries)


class TestSizing:
    def test_shares_come_from_the_MARK(self):
        p = plan(target_weights={"CCC": 0.10})
        (leg,) = p.entries
        assert leg.notional == pytest.approx(10_000.0)
        assert leg.shares == pytest.approx(200.0)      # 10,000 / 50

    def test_a_leg_with_NO_MARK_is_named_not_sized_at_zero(self):
        """A plan that quietly omits an unpriced leg reports a migration that
        does not cover the account."""
        p = plan(broker_positions={"ZZZ": 10.0}, target_weights={"AAA": 0.04})
        assert any("NO MARK" in c and "ZZZ" in c for c in p.caveats)
        (exit_leg,) = p.exits
        assert exit_leg.shares == 10.0
        assert exit_leg.notional is None, "an unpriced leg must not claim a value"

    def test_zero_share_positions_are_not_exits(self):
        """Alpaca can report a closed position transiently."""
        p = plan(broker_positions={"AAA": 0.0})
        assert p.exits == []


class TestTheWholeLegacyBookLeaves:
    def test_every_held_security_is_exited_even_if_the_target_is_empty(self):
        """A degraded or empty target must not be read as 'hold everything' —
        this is a migration, and the legacy book leaves regardless."""
        p = plan(broker_positions={"AAA": 1.0, "BBB": 2.0, "CCC": 3.0},
                 target_weights={})
        assert sorted(l.ticker for l in p.exits) == ["AAA", "BBB", "CCC"]
        assert p.entries == []
