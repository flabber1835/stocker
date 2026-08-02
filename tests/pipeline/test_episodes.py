"""Position-episode reconciliation — pure rules, no DB.

The rule carrying the weight is CLOSING. `live_positions` is a per-sync snapshot,
so a ticker's absence reads identically whether it was sold or the sync was
degraded. Closing on first absence would mean one bad sync ends the episode, the
ticker reappears next run, a NEW episode opens with a RESET peak, and the trailing
stop silently loosens on that position — a risk control failing quietly toward less
protection, which is the worst direction available.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline"))

from app.episodes import (  # noqa: E402
    blocked_reentries,
    build_stop_states,
    plan_episode_sync,
    sessions_after,
)

D1, D2, D3 = date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)


class _S:
    """Stand-in for engine.StopState — injected, so this module needs no engine."""
    def __init__(self, peak_close, last_close, sessions_held, sessions_since_close):
        self.peak_close = peak_close
        self.last_close = last_close
        self.sessions_held = sessions_held
        self.sessions_since_close = sessions_since_close


class TestOpening:
    def test_a_newly_held_ticker_opens_an_episode(self):
        s = plan_episode_sync({"AAA"}, {}, {}, D1)
        assert s.to_open == {"AAA"} and not s.to_close

    def test_an_already_tracked_ticker_does_not_reopen(self):
        s = plan_episode_sync({"AAA"}, {"AAA": D1}, {"AAA": None}, D2)
        assert s.to_open == set() and s.to_close == set()


class TestClosingNeedsConfirmation:
    def test_first_absence_only_marks_pending(self):
        """One missing sync is suspicion, not proof."""
        s = plan_episode_sync(set(), {"AAA": D1}, {"AAA": None}, D2)
        assert s.to_mark_pending == {"AAA"}
        assert s.to_close == set(), "closed on a single absent snapshot"

    def test_second_absence_on_a_later_run_closes(self):
        s = plan_episode_sync(set(), {"AAA": D1}, {"AAA": D2}, D3)
        assert s.to_close == {"AAA"} and s.to_mark_pending == set()

    def test_absence_twice_in_the_same_session_does_not_close(self):
        """A re-run of the same session (manual run-now after the cron chain) must
        not advance the timer — confirmation counts RUNS ON DIFFERENT SESSIONS, the
        same semantics as orphan_confirmation_days."""
        s = plan_episode_sync(set(), {"AAA": D1}, {"AAA": D2}, D2)
        assert s.to_close == set()

    def test_reappearing_clears_the_pending_mark(self):
        """It was a bad snapshot. The episode — and its peak — survive intact."""
        s = plan_episode_sync({"AAA"}, {"AAA": D1}, {"AAA": D2}, D3)
        assert s.to_clear_pending == {"AAA"}
        assert s.to_close == set() and s.to_open == set()

    def test_a_flapping_position_never_closes_and_never_reopens(self):
        """The scenario the confirmation exists for: absent, present, absent. The
        peak must never be reset, or the stop loosens without anyone noticing."""
        open_eps, pending = {"AAA": D1}, {"AAA": None}
        s = plan_episode_sync(set(), open_eps, pending, D1)
        assert s.to_close == set()
        pending["AAA"] = D1
        s = plan_episode_sync({"AAA"}, open_eps, pending, D2)   # back
        assert s.to_close == set() and s.to_clear_pending == {"AAA"}
        pending["AAA"] = None
        s = plan_episode_sync(set(), open_eps, pending, D3)     # gone again
        assert s.to_close == set() and s.to_mark_pending == {"AAA"}


class TestSessionsAfter:
    def test_counts_sessions_not_calendar_days(self):
        """A weekend must not make a Friday print look two days stale and disarm
        the stop."""
        cal = [date(2026, 7, 3), date(2026, 7, 6), date(2026, 7, 7)]  # Fri, Mon, Tue
        assert sessions_after(cal, date(2026, 7, 3)) == 2
        assert sessions_after(cal, date(2026, 7, 7)) == 0

    def test_unknown_date_is_none(self):
        assert sessions_after([D1], None) is None


class TestBuildStopStates:
    def _row(self, **over):
        row = {"ticker": "AAA", "peak_close": 100.0, "last_close": 80.0,
               "last_date": D2, "sessions_held": 30}
        row.update(over)
        return row

    def test_a_complete_row_becomes_a_state(self):
        st = build_stop_states([self._row()], [D1, D2], _S)
        assert st["AAA"].peak_close == 100.0
        assert st["AAA"].sessions_since_close == 0

    @pytest.mark.parametrize("bad", [
        {"peak_close": None}, {"last_close": None}, {"sessions_held": None},
        {"last_date": None}, {"peak_close": 0.0}, {"last_close": -1.0},
        {"peak_close": float("nan")}, {"ticker": None},
    ])
    def test_an_incomplete_row_is_DROPPED_not_defaulted(self, bad):
        """Absent from stop_states means the planner never considers it — the same
        'no fresh price ⇒ never force-sell' rule the engine's data-gap branch
        applies. Defaulting would invent a peak, and an invented peak sells a real
        position."""
        assert build_stop_states([self._row(**bad)], [D1, D2], _S) == {}

    def test_staleness_comes_from_the_calendar_not_the_row(self):
        cal = [D1, D2, D3, date(2026, 7, 6)]
        st = build_stop_states([self._row(last_date=D1)], cal, _S)
        assert st["AAA"].sessions_since_close == 3


class TestBlockedReentries:
    def _blocked(self, last, peak, *, sessions_since_stop=None,
                 policy="peak", cooldown_sessions=21):
        """Stand-in for engine.reentry_blocked. It grew keyword-only policy
        arguments when the cooldown was added; the fake mirrors the real
        signature so this suite cannot pass against a call the engine would
        reject."""
        if policy == "cooldown":
            return (sessions_since_stop is not None
                    and sessions_since_stop < cooldown_sessions)
        return last is not None and peak is not None and last <= peak

    def test_the_fake_matches_the_real_signature(self):
        """Guards the paragraph above: a divergence here makes every other test
        in this class green against a contract that does not exist."""
        import inspect
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                        "../../services/pipeline/app"))
        from engine import reentry_blocked
        real = inspect.signature(reentry_blocked).parameters
        fake = {k: v for k, v in inspect.signature(self._blocked).parameters.items()
                if k != "self"}
        kw = inspect.Parameter.KEYWORD_ONLY
        # blocked_reentries passes the first two POSITIONALLY (so their names may
        # differ) and everything else BY KEYWORD (so those names must match).
        assert ([k for k, v in real.items() if v.kind is kw]
                == [k for k, v in fake.items() if v.kind is kw])
        assert (len([v for v in real.values() if v.kind is not kw])
                == len([v for v in fake.values() if v.kind is not kw]))

    def test_a_cooldown_block_survives_a_missing_price(self):
        """The peak rule needs a price to compare against; the cooldown does not.
        Requiring one would silently unblock a halted name early."""
        out = blocked_reentries({"AAA": 100.0}, {}, set(), self._blocked,
                                sessions_since_stop={"AAA": 3},
                                policy="cooldown", cooldown_sessions=21)
        assert out == {"AAA"}

    def test_a_cooldown_expires(self):
        out = blocked_reentries({"AAA": 100.0}, {}, set(), self._blocked,
                                sessions_since_stop={"AAA": 21},
                                policy="cooldown", cooldown_sessions=21)
        assert out == set()

    def test_an_unrecovered_stop_blocks(self):
        out = blocked_reentries({"AAA": 100.0}, {"AAA": 90.0}, set(), self._blocked)
        assert out == {"AAA"}

    def test_recovery_above_the_peak_clears_it(self):
        out = blocked_reentries({"AAA": 100.0}, {"AAA": 101.0}, set(), self._blocked)
        assert out == set()

    def test_a_held_ticker_is_never_blocked(self):
        """Re-buying clears the block; a position we already hold is governed by
        its own live episode."""
        out = blocked_reentries({"AAA": 100.0}, {"AAA": 90.0}, {"AAA"}, self._blocked)
        assert out == set()

    def test_no_fresh_close_does_not_block(self):
        """Without a price nothing can buy it anyway, and inventing a block on
        missing data would strand the name."""
        out = blocked_reentries({"AAA": 100.0}, {}, set(), self._blocked)
        assert out == set()
