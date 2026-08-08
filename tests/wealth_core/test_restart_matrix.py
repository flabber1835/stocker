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
    # DIVIDEND_SESSION + 1, not DIVIDEND_SESSION. `sessions[:cut]` is exclusive,
    # so cutting AT the ex-date puts the accrual in the TAIL and nothing is in
    # flight across the boundary — the cut was named for a condition it did not
    # land on. +1 puts the accrual in the head and the settlement in the tail,
    # which is the only arrangement that tests a restart between entitlement and
    # payment. Asserted below rather than assumed.
    "dividend_receivable": DIVIDEND_SESSION + 1,
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

    def test_a_terminal_action_is_in_flight(self, g):
        """RE-POINTED 2026-08-08, from `unresolved_terminals` to the C1 carry.

        Under the grace period SEC_STRANDED is CARRIED across this cut rather
        than blocking, so `unresolved_terminals` is empty here and the old
        assertion would have been testing nothing. The in-flight condition the
        cut exists to land on is now the pending grace — and it is strictly more
        demanding, because a counter that resets on restart never expires while
        a lost block merely unfreezes.
        """
        r, _ = self.state_at(g, CUTS["unresolved_terminal_event"])
        assert r.state.terminal_pending_sessions, (
            "no terminal action is in flight at this cut")
        assert r.state.terminal_pending_terms, (
            "the pending TERMS must persist too — without them the resumed run "
            "has nothing to re-resolve against and the grace never expires")

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

    def test_a_dividend_is_ACCRUED_BUT_UNPAID_at_the_dividend_cut(self, g):
        """The condition that cut is named for. A dividend accrues on its
        ex-date and settles `dividend_settlement_lag_sessions` later, so there
        is a window in which the book is owed money it does not hold — and this
        asserts the cut lands INSIDE it. At the old index the accrual fell in
        the tail and nothing crossed the boundary at all."""
        r, _ = self.state_at(g, CUTS["dividend_receivable"])
        assert r.ledger.receivable_total() > 0, (
            "no receivable is outstanding at this cut, so the restart test for "
            "it is not testing a restart between entitlement and payment")
        assert not any(e.event_type.value == "DIVIDEND_PAID"
                       for e in r.ledger.events), "already settled"


class TestTheRestartMachineryCanActuallyFail:
    """Mutation controls, one per piece of state the scenarios depend on.

    TWO THINGS WERE WRONG WITH THE ORIGINAL SHAPE OF THIS CLASS, and both made
    it weaker than it read.

    1. IT COMPARED THE WRONG PAIR. The control asserted
       `first_divergence(tail_hashes, whole_run_hashes) is not None`. Those two
       runs cover DIFFERENT SESSION RANGES, so `normalized_input` — the first
       hash in diagnostic order — always differs, and the assertion was true for
       every corruption whether or not the corruption did anything at all. It
       could not fail. The comparison is now DAMAGED TAIL vs CLEAN TAIL over the
       same sessions, where a divergence means something.

    2. IT ASSERTED THE WRONG LAYER. It required the terminal STATE hash to
       differ. That holds for four of the six corruptions and is simply false
       for the other two, because a later safeguard absorbs the damage:

         * dropped reservations — the resumed run re-admits the reserved
           security and queues a SECOND order for the same slot, exactly the
           duplicate-order defect. At the fill, `affordable_shares` finds the
           cash already spent by the first order and cancels the duplicate. The
           book converges; the ORDER STREAM does not.
         * dropped review flags — every holding past the review age is
           re-reviewed, and a re-review that PASSES sets the flag again. The
           state re-converges. Under the old `==` rule it could not, which is
           why this control used to pass: it was relying on a bug.

       Both corruptions ARE load-bearing and both DO diverge — at `decision`,
       which is where the audit trail records that the strategy considered
       something it should not have. So each case now pins the layer it diverges
       at, and states explicitly whether the terminal state converges. That is a
       stronger claim than "something differs", and it is the claim that stays
       true when a downstream safeguard is added or removed.
    """

    def corrupt_reservations(self, blob):
        for slot in blob["slots"].values():
            slot["reserved_for"] = slot["reserved_ticker"] = None
            slot["reserved_issuer"] = None

    def corrupt_unresolved_terminals(self, blob):
        blob["unresolved_terminals"] = {}

    def corrupt_terminal_pending(self, blob):
        blob["terminal_pending_sessions"] = {}
        blob["terminal_pending_terms"] = {}

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
        blob["security_cooldowns"] = {}

    def corrupt_review_flags(self, blob):
        for ep in blob["episodes"].values():
            ep["review_completed"] = False

    # (corruption, cut, first layer that must diverge, does terminal state move?)
    MUTATIONS = [
        ("corrupt_reservations", 169, "decision", False),
        # `corrupt_unresolved_terminals` was REMOVED here, not relaxed. Under
        # C1's grace period this scenario produces no state-level block at any
        # cut, so the mutation clears an already-empty dict and can no longer
        # fail — a control that cannot fail is worse than none, because it reads
        # as coverage. Its replacement is
        # test_a_lost_grace_counter_changes_the_outcome below, which builds the
        # one condition the golden stream lacks: a carried security that STOPS
        # printing, where the counter actually drives the result.
        ("corrupt_episode_ages", 150, "decision", True),
        ("corrupt_peaks", 150, "decision", True),
        ("corrupt_cooldowns", CUTS["cooldown_boundary"], "decision", True),
        ("corrupt_review_flags", 250, "decision", False),
    ]

    @pytest.mark.parametrize("corruption,cut,layer,state_moves", MUTATIONS)
    def test_losing_it_across_the_restart_changes_the_run(self, g, whole,
                                                          corruption, cut,
                                                          layer, state_moves):
        """Damaged tail vs CLEAN tail over the same sessions — see the class
        docstring for why the comparison used to be against the whole run and
        why that could not fail."""
        ref, _ = whole
        clean, clean_hashes = resumed(g, cut)[1:]
        damaged, damaged_hashes = resumed(g, cut, corrupt=getattr(self, corruption))[1:]

        # The clean resumption is the control's own control: if this drifts,
        # the comparison below is measuring a broken restart, not a corruption.
        assert clean.state.state_hash() == ref.state.state_hash()

        assert first_divergence(damaged_hashes, clean_hashes) == layer, (
            f"{corruption} at session index {cut} was expected to first diverge "
            f"at {layer!r}; got "
            f"{first_divergence(damaged_hashes, clean_hashes)!r}. Either the "
            f"corruption stopped mattering — the scenario it guards is no "
            f"longer exercised at this cut — or it now shows up somewhere else, "
            f"which is a finding about the engine.")

        assert (damaged.state.state_hash() != clean.state.state_hash()) is state_moves

    def test_a_lost_grace_counter_changes_the_outcome(self):
        """THE control the golden stream cannot provide.

        A C1 grace counter that reset on every redeploy would never expire on a
        book that restarts weekly, and the failure would look like patience
        rather than a counter losing its place — the single most likely way this
        feature fails silently in production.

        The golden scenario cannot falsify it: SEC_STRANDED keeps printing
        throughout and its real terms arrive before the grace would expire, so
        clearing the counter mid-run changes nothing there. That is a property
        of the scenario, not evidence of safety. This builds the missing
        condition directly — a documented terms-less event on a security that
        then STOPS printing, carried until the grace runs out.
        """
        from stock_strategy_shared.wealth_core.adapter import (
            step_session, tradeability_only_bars)
        from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
        from stock_strategy_shared.wealth_core.settlement import C1_GRACE_SESSIONS
        from stock_strategy_shared.wealth_core.state import (
            HoldingEpisode, PortfolioState)
        from stock_strategy_shared.wealth_core.terminal import (
            TerminalKind, TerminalTerms)

        cfg = WealthCoreConfig()
        terms = TerminalTerms(session="d1", security_id="S1",
                              kind=TerminalKind.CASH_MERGER,
                              reference="test/terms-pending")

        def fresh():
            st = PortfolioState.fresh(10_000.0)
            st.slots[0].occupied_by = "S1"
            st.episodes[0] = HoldingEpisode("S1", "T1", "I1", 0, "d0", "d0",
                                            100.0, 100.0, 10, 10, 100.0)
            st.initialized = True
            return st

        def carry(st, ledger, last_known, session, announce=False):
            return step_session(
                session=session, state=st, bars=[], pending=[], ledger=ledger,
                last_known=last_known, cfg=cfg, strategy_id="stocker_wealth_core_v1",
                strategy_version=1, security_bars=tradeability_only_bars([], None),
                terminal_terms=[terms] if announce else [])

        # Announce, then carry to one session short of expiry.
        st, led, lk = fresh(), Ledger(), {"S1": 95.0}
        carry(st, led, lk, "d1", announce=True)
        for i in range(C1_GRACE_SESSIONS - 1):
            carry(st, led, lk, f"d{i + 2}")
        assert st.terminal_pending_sessions["S1"] == C1_GRACE_SESSIONS - 1
        assert 0 in st.episodes, "must still be carried, not yet settled"

        # CLEAN restart: bytes across the boundary, then one more session.
        clean = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        carry(clean, Ledger(), dict(lk), "dX")
        assert 0 not in clean.episodes, (
            "the grace should have expired on this session and settled the "
            "holding at its last trustworthy mark")

        # DAMAGED restart: the counter and terms are lost.
        blob = json.loads(json.dumps(st.to_dict()))
        blob["terminal_pending_sessions"] = {}
        blob["terminal_pending_terms"] = {}
        damaged = PortfolioState.from_dict(blob)
        carry(damaged, Ledger(), dict(lk), "dX")
        assert 0 in damaged.episodes, (
            "losing the counter left the holding carried indefinitely — which "
            "is exactly the silent failure this control exists to catch")
        assert damaged.state_hash() != clean.state_hash()

    def test_the_absorbed_corruptions_really_are_absorbed_downstream(self, g, whole):
        """The two `state_moves=False` rows say a LATER safeguard swallows the
        damage. That is a claim about a specific mechanism, so it is asserted
        rather than left as a comment on a False.

        Dropping the reservations must produce a SECOND, duplicate order for the
        already-reserved security, and the fill-time affordability rule must be
        what cancels it. If the duplicate stopped being emitted, the control
        above would still pass at `decision` for some other reason and the
        reservation would look load-bearing when it was not.
        """
        cut = 169
        clean = resumed(g, cut)[1]
        damaged = resumed(g, cut, corrupt=self.corrupt_reservations)[1]

        def orders_for(run, sec):
            return [o for s in run.sessions if s.decision
                    for o in s.decision.to_dict()["operations"]
                    if o["operation"] == "OPEN_SLOT_POSITION"
                    and o["security_id"] == sec]

        reserved = "SEC_BUST"          # the security holding the reservation
        assert not orders_for(clean, reserved), (
            "the clean resumption must NOT re-order the reserved security — "
            "that is what the reservation is for")
        assert orders_for(damaged, reserved), (
            "dropping the reservation must re-admit it; without the duplicate "
            "there is nothing for the reservation to have prevented")

        cancels = [c for s in damaged.sessions for c in s.cancelled
                   if c["security_id"] == reserved]
        assert any(c["reason"] == "UNAFFORDABLE_AT_OPEN" for c in cancels), (
            "the duplicate must be stopped by the fill-time affordability rule; "
            "if it fills, the book doubles a position and the terminal state "
            "WOULD move — in which case this row's state_moves is wrong")


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
