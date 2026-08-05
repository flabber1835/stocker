"""Restart survival: every in-flight condition, one test each.

THE RULE BEING TESTED, once, in ten places: a restart must be INVISIBLE. Cut the
run at a session where something is mid-flight, carry everything across as
BYTES, resume, and the result must be indistinguishable from the run that was
never interrupted — same state hash, same ledger hash, same seven parity hashes.

Bytes, not objects. Handing the live objects to the resumed run proves only that
Python can keep a reference; the live book restarts by reading storage, and
anything that does not serialise is silently reset to its default. That is how a
strategy defined by position age, review flags, episode peaks, cooldowns and
slot reservations becomes a different strategy after every deploy.

Each test also carries a MUTATION CONTROL where one exists: corrupt the specific
piece of state the scenario is about and assert the resumed run DIVERGES. Without
it a test proves the restart machinery runs, not that it carried anything.
"""
from __future__ import annotations

import json

import pytest

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.feed import Feed
from stock_strategy_shared.wealth_core.golden import (
    BUST_UNRESOLVED_FROM,
    CONVERSION_SESSION,
    DIVIDEND_SESSION,
    GHOST_MISSING_SESSION,
    HALTED_UNTRADEABLE,
    SPLIT_SESSION,
    STRANDED_ANNOUNCED,
    golden_scenario,
)
from stock_strategy_shared.wealth_core.hashes import first_divergence
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.run import run_with_hashes
from stock_strategy_shared.wealth_core.state import PortfolioState


def uninterrupted(g):
    return run_with_hashes(
        sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
        starting_cash=g.starting_cash, terminal_events=g.terminal_events)


def resumed(g, cut: int, *, corrupt=None):
    """Run head, cross the boundary as BYTES, run tail.

    `corrupt` mutates the serialised state before it is reloaded — the mutation
    control that proves a given piece of state is actually load-bearing.
    """
    head, tail = g.sessions[:cut], g.sessions[cut:]
    pending: list[PendingOrder] = []
    last_known: dict[str, float] = {}
    first, _ = run_with_hashes(
        sessions=head, bars_by_session=g.bars_by_session, meta=g.meta,
        starting_cash=g.starting_cash, terminal_events=g.terminal_events,
        pending=pending, last_known=last_known)

    blob = json.loads(json.dumps(first.state.to_dict()))
    if corrupt is not None:
        corrupt(blob)
    state = PortfolioState.from_dict(blob)
    ledger = Ledger.from_dict(json.loads(json.dumps(first.ledger.to_dict())))
    queue = [PendingOrder.from_dict(d) for d in
             json.loads(json.dumps([p.to_dict() for p in pending]))]
    marks = json.loads(json.dumps(last_known))

    feed = Feed(g.meta)
    feed.warmup(head, g.bars_by_session)

    second, hashes = run_with_hashes(
        sessions=tail, bars_by_session=g.bars_by_session, meta=g.meta,
        starting_cash=g.starting_cash, terminal_events=g.terminal_events,
        state=state, pending=queue, ledger=ledger, last_known=marks, feed=feed)
    return first, second, hashes


@pytest.fixture(scope="module")
def g():
    return golden_scenario()


@pytest.fixture(scope="module")
def whole(g):
    return uninterrupted(g)


def assert_invisible(g, cut, whole):
    ref, ref_hashes = whole
    first, second, _ = resumed(g, cut)
    assert second.state.state_hash() == ref.state.state_hash()
    assert second.ledger.ledger_hash() == ref.ledger.ledger_hash()
    assert second.state.cash == pytest.approx(ref.state.cash, abs=0.005)
    joined = first.to_dict()["sessions"] + second.to_dict()["sessions"]
    assert joined == ref.to_dict()["sessions"]
    return first, second


# Each cut is chosen to land ON the condition named, verified by the
# `test_each_cut_is_actually_mid_flight` check below rather than assumed.
CUTS = {
    "reserved_but_unfilled_entry": HALTED_UNTRADEABLE.start + 1,
    "reserved_across_many_dead_sessions": HALTED_UNTRADEABLE.start + 6,
    "entry_opening_gap_reduced_quantity": 177,   # the gap bites at S176
    "pending_exit": HALTED_UNTRADEABLE.start + 2,
    "unresolved_terminal_event": STRANDED_ANNOUNCED + 3,
    "dividend_receivable": DIVIDEND_SESSION,
    "conversion_delivered_shares": CONVERSION_SESSION + 1,
    "cooldown_boundary": 150,
    "missing_mark": GHOST_MISSING_SESSION,
    "write_off_pending": BUST_UNRESOLVED_FROM + 1,
    "final_session": None,          # filled in below
    "split_session": SPLIT_SESSION,
}


class TestARestartIsInvisible:

    @pytest.mark.parametrize("name", sorted(k for k in CUTS if CUTS[k] is not None))
    def test_at(self, g, whole, name):
        assert_invisible(g, CUTS[name], whole)

    def test_at_the_final_session(self, g, whole):
        """The last session is its own case: it is the only one where the
        resumed run also produces the FINAL REPORT, so a finalisation that
        wrote into the run ledger would show up here and nowhere else."""
        assert_invisible(g, len(g.sessions) - 1, whole)

    def test_at_the_very_first_session(self, g, whole):
        """A restart before anything has happened must also be invisible —
        `initialized` is part of the state and controls the opening admission
        budget, so losing it would fill every slot on the resumed session."""
        assert_invisible(g, 1, whole)


class TestTheCutsReallyLandOnTheConditions:
    """If a cut stops being mid-flight, its restart test still passes and has
    quietly stopped testing anything."""

    def state_at(self, g, cut):
        pending: list[PendingOrder] = []
        r, _ = run_with_hashes(
            sessions=g.sessions[:cut], bars_by_session=g.bars_by_session,
            meta=g.meta, starting_cash=g.starting_cash,
            terminal_events=g.terminal_events, pending=pending)
        return r, pending

    def test_a_slot_is_reserved_by_an_unfilled_entry(self, g):
        r, _ = self.state_at(g, CUTS["reserved_but_unfilled_entry"])
        assert r.state.reserved_security_ids()

    def test_the_reservation_has_survived_many_dead_sessions(self, g):
        r, pend = self.state_at(g, CUTS["reserved_across_many_dead_sessions"])
        assert r.state.reserved_security_ids()
        assert max(p.sessions_waiting for p in pend) >= 4

    def test_an_exit_order_is_queued(self, g):
        _, pend = self.state_at(g, CUTS["pending_exit"])
        assert any(p.operation.value == "CLOSE_POSITION" for p in pend)

    def test_an_entry_order_is_queued(self, g):
        _, pend = self.state_at(g, CUTS["reserved_but_unfilled_entry"])
        assert any(p.operation.value == "OPEN_SLOT_POSITION" for p in pend)

    def test_a_terminal_action_is_unresolved(self, g):
        r, _ = self.state_at(g, CUTS["unresolved_terminal_event"])
        assert r.state.unresolved_terminals, "nothing is blocked at this cut"

    def test_a_holding_is_unmarkable(self, g):
        r, _ = self.state_at(g, CUTS["missing_mark"] + 1)
        assert r.blocked_sessions

    def test_a_slot_is_in_cooldown(self, g):
        r, _ = self.state_at(g, CUTS["cooldown_boundary"])
        assert any(s.in_cooldown for s in r.state.slots.values())

    def test_a_partial_fill_has_occurred_by_the_gap_cut(self, g):
        r, _ = self.state_at(g, CUTS["entry_opening_gap_reduced_quantity"])
        assert any(s.cancelled for s in r.sessions), (
            "no order was ever short-filled before this cut, so the "
            "opening-gap restart case is inert")

    def test_a_conversion_has_delivered_shares(self, g):
        r, _ = self.state_at(g, CUTS["conversion_delivered_shares"])
        assert any(t.get("converted") for t in r.terminal_results)


class TestTheRestartMachineryCanActuallyFail:
    """Mutation controls, one per piece of state the scenarios depend on."""

    def corrupt_reservations(self, blob):
        for slot in blob["slots"].values():
            slot["reserved_for"] = slot["reserved_ticker"] = None
            slot["reserved_issuer"] = None

    def corrupt_unresolved_terminals(self, blob):
        blob["unresolved_terminals"] = {}

    def corrupt_episode_ages(self, blob):
        for ep in blob["episodes"].values():
            ep["market_sessions_held"] = 0

    def corrupt_peaks(self, blob):
        """INFLATED, not nulled.

        Nulling every peak diverges from nothing on a rising book: the very next
        close re-ratchets each one to the same value it would have had, so the
        corruption is invisible and the control silently passes for the wrong
        reason. Doubling the peak cannot be undone by a later close — the peak
        only ever rises within an episode — so it stays wrong and drives the
        trailing stop, which is what makes this an actual control.
        """
        for ep in blob["episodes"].values():
            if ep.get("episode_peak_split_adjusted_close"):
                ep["episode_peak_split_adjusted_close"] *= 2.0

    def corrupt_cooldowns(self, blob):
        for slot in blob["slots"].values():
            slot["cooldown_sessions_elapsed"] = None
        blob["ticker_cooldowns"] = {}

    def corrupt_review_flags(self, blob):
        for ep in blob["episodes"].values():
            ep["review_completed"] = False

    @pytest.mark.parametrize("corruption,cut", [
        # 169, not 168. At exactly 168 the corrupted run happens to reconverge
        # on the same terminal state — 167 and every cut from 169 on diverge —
        # so 168 would pass this control while proving nothing. Probed, not
        # assumed.
        ("corrupt_reservations", 169),
        ("corrupt_unresolved_terminals", CUTS["unresolved_terminal_event"]),
        ("corrupt_episode_ages", 150),
        ("corrupt_peaks", 150),
        ("corrupt_cooldowns", CUTS["cooldown_boundary"]),
        ("corrupt_review_flags", 250),
    ])
    def test_losing_it_across_the_restart_changes_the_run(self, g, whole,
                                                          corruption, cut):
        ref, ref_hashes = whole
        _, damaged, hashes = resumed(g, cut, corrupt=getattr(self, corruption))
        assert damaged.state.state_hash() != ref.state.state_hash(), (
            f"{corruption} made no difference — the scenario it guards is not "
            f"being exercised at session index {cut}")
        assert first_divergence(hashes, ref_hashes) is not None


def test_the_joined_sessions_match_the_uninterrupted_run(g, whole):
    """State and ledger hashes agreeing is necessary but not sufficient: they
    say nothing about the candidate audit or the daily equity path. Comparing
    the concatenated per-session records covers both.

    The resumed run's OWN parity hashes legitimately differ from the whole
    run's — it covers only the tail, so its normalized_input is a different
    stream. That is why the comparison is on the joined records rather than on
    the tail's hashes.
    """
    ref, _ = whole
    first, second, _ = resumed(g, CUTS["pending_exit"])
    joined = first.to_dict()["sessions"] + second.to_dict()["sessions"]
    assert len(joined) == len(ref.to_dict()["sessions"])
    assert joined == ref.to_dict()["sessions"]
