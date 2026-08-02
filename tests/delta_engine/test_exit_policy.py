"""exit_policy='trailing_stop_only' — rank picks entries, price manages exits.

The premise: the ranking carries real information about its top TIER but is not
monotone enough over a month to justify retiring a holding because it slipped
from rank 20 to rank 50. Under this policy the builder still names the best N
every day, but falling out of that list is no longer a sell signal — a position
leaves when its own price path breaks, when it drops below the investability
floor, or when it delists.

Two properties carry the whole design:

  * with the flags at their defaults the engine is BIT-IDENTICAL to before, so
    the champion is untouched by construction rather than by care; and
  * the safety exits SURVIVE the policy. Suppressing them too would strand a
    sub-floor or delisted holding forever, which is how a "let winners run" rule
    quietly becomes "never sell anything".
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from engine import RankObservation, evaluate_target_vs_live  # noqa: E402

D = date(2026, 8, 1)


def _obs(rank, score=0.5, n=4):
    return [RankObservation(run_date=D, rank=rank, composite_score=score)
            for _ in range(n)]


def _call(**over):
    """A held book of 3 where AAA has fallen out of the target."""
    kw = dict(
        target_portfolio={"BBB": 0.3, "CCC": 0.3, "DDD": 0.3},
        live_positions={"AAA", "BBB", "CCC"},
        universe={"AAA": _obs(60), "BBB": _obs(2), "CCC": _obs(3), "DDD": _obs(4)},
        confirmation_days=3,
        max_positions=25,
        actual_weights={"AAA": 0.30, "BBB": 0.30, "CCC": 0.30},
        drift_threshold=0.02,
        target_history=[{"BBB", "CCC", "DDD"}] * 4,
        orphan_confirmation_days=2,
    )
    kw.update(over)
    return evaluate_target_vs_live(**kw)


# ── the default must be inert ─────────────────────────────────────────────────

class TestDefaultsAreUnchanged:
    def test_omitting_the_flags_still_orphan_exits(self):
        """The champion runs with neither flag set. If this ever changes, a live
        book starts holding names the builder dropped without anyone asking."""
        assert _call()["AAA"].action == "exit"

    def test_explicit_defaults_match_omission_exactly(self):
        a = _call()
        b = _call(suppress_target_exits=False, drift_rebalance=True)
        assert {t: (d.action, d.reason) for t, d in a.items()} == \
               {t: (d.action, d.reason) for t, d in b.items()}


# ── the policy ────────────────────────────────────────────────────────────────

class TestStopOnlyExits:
    def test_a_name_dropped_from_the_target_is_held_not_exited(self):
        d = _call(suppress_target_exits=True)["AAA"]
        assert d.action == "hold"
        assert "trailing_stop_only" in d.reason

    def test_it_is_not_merely_at_risk(self):
        """at_risk would still count the position as occupying a slot on a
        countdown to sale. Under this policy there is no countdown at all."""
        assert _call(suppress_target_exits=True)["AAA"].action != "at_risk"

    def test_the_orphan_timer_does_not_accumulate_in_the_background(self):
        """If the timer kept running while suppressed, flipping the policy off —
        or a name re-entering the target later — would fire an immediate sale
        from a countdown nobody could see."""
        d = _call(suppress_target_exits=True,
                  target_history=[{"BBB", "CCC", "DDD"}] * 10)["AAA"]
        assert d.confirmation_days_met == 0

    def test_in_target_names_are_unaffected(self):
        out = _call(suppress_target_exits=True)
        assert out["BBB"].action in ("hold", "buy_add", "sell_trim")
        assert out["DDD"].action in ("entry", "watch")


# ── the safety exits must survive ─────────────────────────────────────────────

class TestSafetyExitsSurvive:
    def test_a_below_floor_holding_still_exits(self):
        """It trades, but under the strategy's own price/liquidity floor — the
        exemption that keeps data-gap names alive must not also strand this one,
        or a config switch leaves dead weight in the book forever."""
        out = _call(suppress_target_exits=True,
                    universe={"BBB": _obs(2), "CCC": _obs(3), "DDD": _obs(4)},
                    unranked_below_floor={"AAA"})
        assert out["AAA"].action in ("exit", "at_risk")

    def test_a_data_gap_holding_is_still_held(self):
        out = _call(suppress_target_exits=True,
                    universe={"BBB": _obs(2), "CCC": _obs(3), "DDD": _obs(4)})
        assert out["AAA"].action == "hold"

    def test_an_empty_target_still_holds_everything(self):
        out = _call(suppress_target_exits=True, target_portfolio={},
                    target_history=[set()] * 4)
        assert all(d.action == "hold" for t, d in out.items()
                   if t in ("AAA", "BBB", "CCC"))


# ── drift rebalancing ─────────────────────────────────────────────────────────

class TestDriftRebalanceOff:
    def _drifted(self, **over):
        return _call(actual_weights={"AAA": 0.30, "BBB": 0.10, "CCC": 0.50},
                     **over)

    def test_by_default_drift_still_trims_and_adds(self):
        out = self._drifted()
        assert out["BBB"].action == "buy_add"
        assert out["CCC"].action == "sell_trim"

    def test_disabled_leaves_weights_alone(self):
        """Trimming a winner back to target every few builds is a slow-motion
        version of the rotation this whole policy exists to avoid — it sells
        precisely the names the thesis wants compounding."""
        out = self._drifted(drift_rebalance=False)
        assert out["BBB"].action == "hold"
        assert out["CCC"].action == "hold"
        assert "drift rebalance disabled" in out["CCC"].reason

    def test_entries_are_unaffected(self):
        """Entries still size to the target weight; only rebalancing of EXISTING
        positions is suppressed."""
        out = self._drifted(drift_rebalance=False)
        assert out["DDD"].action in ("entry", "watch")


# ── vacancy refill ────────────────────────────────────────────────────────────

class TestVacancyRefill:
    """The brief asked for `refill_vacancies_from_latest_rank`. No new selection
    path was needed: `select_entries_within_capacity` already admits best-rank
    first up to max_positions, so a stop that frees a slot is filled by the best
    eligible name on the next build. These pin that, because "it already works"
    is only true until someone changes the allocator."""

    def _book(self, n_held, cap, stopped=frozenset()):
        held = {f"H{i:02d}" for i in range(n_held)}
        cands = {f"N{i:02d}": 0.04 for i in range(5)}
        target = {**{h: 0.04 for h in held - stopped}, **cands}
        uni = {t: _obs(i + 1) for i, t in enumerate(sorted(cands))}
        uni.update({h: _obs(100 + i) for i, h in enumerate(sorted(held))})
        return evaluate_target_vs_live(
            target_portfolio=target, live_positions=held, universe=uni,
            confirmation_days=3, max_positions=cap,
            actual_weights={h: 0.04 for h in held},
            target_history=[set(target)] * 4, orphan_confirmation_days=2,
            inflight_exits=stopped or None,
            suppress_target_exits=True, drift_rebalance=False)

    def test_a_full_book_admits_nothing(self):
        out = self._book(n_held=25, cap=25)
        assert not [d for d in out.values() if d.action == "entry"]

    def test_a_stop_frees_exactly_one_slot(self):
        out = self._book(n_held=25, cap=25, stopped={"H00"})
        assert len([d for d in out.values() if d.action == "entry"]) == 1

    def test_the_slot_goes_to_the_best_ranked_candidate(self):
        out = self._book(n_held=25, cap=25, stopped={"H00"})
        entered = [t for t, d in out.items() if d.action == "entry"]
        assert entered == ["N00"], entered

    def test_deferred_entries_are_watch_not_dropped(self):
        out = self._book(n_held=25, cap=25, stopped={"H00"})
        assert len([d for d in out.values() if d.action == "watch"]) >= 1
