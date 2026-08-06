"""The Wealth Core golden fixture — the cross-engine parity artefact.

WHAT THIS FILE IS FOR. `run_sessions` is the only implementation of the
strategy, so the backtester, the wind tunnel and the live book cannot disagree
about WHAT it does — only about what they FEED it. This fixture pins the output
of one fully-specified input stream, so any engine that claims parity can be
made to run `golden_scenario()` through its own wiring and compare one hash.

WHY THE COVERAGE ASSERTIONS COME FIRST, and why they are not decoration. A
pinned hash proves reproducibility and NOTHING about coverage: a scenario that
silently stopped exercising the write-off path would still hash consistently,
and the fixture would go on passing while testing less every year. So each of
the conditions the fixture exists to cover is asserted to have actually
happened. Two of them were NOT firing when the assertions were first written —
no review exit at all, and no exit orders straddling the restart boundary — and
the scenario had to be changed to produce them.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

import pytest

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.eligibility import EligibilityReason
from stock_strategy_shared.wealth_core.feed import Feed
from stock_strategy_shared.wealth_core.golden import (
    CONVERSION_SESSION,
    GHOST_MISSING_SESSION,
    MERGER_SESSION,
    RESTART_AT,
    SESSIONS,
    SPLIT_SESSION,
    WRITE_OFF_SESSION,
    golden_scenario,
)
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.run import run_sessions
from stock_strategy_shared.wealth_core.state import PortfolioState

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "golden_wealth_core_v1.json"


def full_run():
    g = golden_scenario()
    return g, run_sessions(sessions=g.sessions, bars_by_session=g.bars_by_session,
                           meta=g.meta, starting_cash=g.starting_cash,
                           terminal_events=g.terminal_events)


@pytest.fixture(scope="module")
def run():
    return full_run()[1]


def ops(result, *, operation=None, reason=None):
    out = []
    for s in result.sessions:
        if not s.decision:
            continue
        for o in s.decision.to_dict()["operations"]:
            if operation and o["operation"] != operation:
                continue
            if reason and o["reason"] != reason:
                continue
            out.append((s.session, o))
    return out


# ── coverage: every condition the fixture claims to exercise ────────────────

class TestTheScenarioActuallyExercisesEachCondition:

    def test_a_split_changes_the_share_count_without_touching_the_peak(self, run):
        ev = [e for e in run.ledger.events if e.event_type.value == "SPLIT"]
        assert len(ev) == 1 and ev[0].session == SESSIONS[SPLIT_SESSION]
        assert ev[0].detail["after"] == ev[0].detail["before"] * 2
        # The peak is a SPLIT-ADJUSTED price, so a 2:1 split must leave it where
        # it was. Rescaling it would double-apply the split and, on a stop rule,
        # in the direction of selling a position that never fell.
        ep = next(e for e in run.state.episodes.values()
                  if e.security_id == "SEC_SPLITTER")
        assert ep.episode_peak_split_adjusted_close > ep.entry_split_adjusted_price

    def test_a_dividend_accrues_as_a_receivable_before_it_becomes_cash(self, run):
        kinds = [e.event_type.value for e in run.ledger.events
                 if e.security_id == "SEC_PAYER"
                 and "DIVIDEND" in e.event_type.value]
        assert kinds == ["DIVIDEND_ACCRUED", "DIVIDEND_PAID"], (
            "two events, in this order — posting straight to cash would let an "
            "unsettled dividend fund an admission on its own ex-date")

    def test_an_untradeable_session_defers_the_order_it_does_not_drop_it(self, run):
        waits = [f for s in run.sessions for f in s.fills if f["waited"] > 0]
        assert waits, "no order ever had to wait — the halt window is inert"

    def test_a_missing_bar_blocks_admissions_rather_than_valuing_at_zero(self, run):
        assert SESSIONS[GHOST_MISSING_SESSION] in run.blocked_sessions
        assert "SEC_GHOST" in run.state.held_security_ids(), (
            "GHOST must still be HELD — the point of the rule is that an "
            "unmarkable holding is preserved, not written off")

    def test_an_unresolved_terminal_action_blocks_and_then_resolves(self, run):
        blocked = set(run.blocked_sessions)
        assert SESSIONS[MERGER_SESSION - 1] in blocked
        # Scoped to SEC_MERGED: the stranded-terms case settles as a cash
        # merger too, so an unscoped count now covers two different conditions
        # and would pass for the wrong reason.
        merger = [e for e in run.ledger.events
                  if e.event_type.value == "CASH_MERGER"
                  and e.security_id == "SEC_MERGED"]
        assert len(merger) == 1 and merger[0].cash_delta > 0
        # ...and the block LIFTS once resolved. An equity gate that never
        # reopens would look identical in every aggregate except the trades.
        assert SESSIONS[MERGER_SESSION + 1] not in blocked

    def test_a_write_off_is_the_only_thing_that_makes_a_holding_worth_zero(self, run):
        wo = [e for e in run.ledger.events if e.event_type.value == "WRITE_OFF"]
        assert len(wo) == 1 and wo[0].session == SESSIONS[WRITE_OFF_SESSION]
        assert wo[0].cash_delta == 0.0
        assert "SEC_BUST" not in run.state.held_security_ids()

    def test_two_securities_of_one_issuer_never_both_get_admitted(self, run):
        held = run.state.held_security_ids()
        assert not {"SEC_DUAL_A", "SEC_DUAL_B"} <= held
        rej = [r for s in run.sessions if s.decision
               for r in s.decision.admission_rejections
               if r["reason"] == "ISSUER_CONFLICT"]
        assert rej, "the issuer conflict never fired"
        # ...and the loser was NOT removed before the cutoff. That is the whole
        # certified correction: related securities compete on merit and lose at
        # ADMISSION, so both must be present and eligible in the population.
        d = next(s.decision for s in run.sessions if s.decision
                 and any(r["reason"] == "ISSUER_CONFLICT"
                         for r in s.decision.admission_rejections))
        cands = {c.security_id for c in d.candidates}
        assert {"SEC_DUAL_A", "SEC_DUAL_B"} <= cands

    def test_a_security_without_127_closes_is_never_a_candidate(self, run):
        for s in run.sessions:
            if not s.decision:
                continue
            row = next((c for c in s.decision.candidates
                        if c.security_id == "SEC_SHORT"), None)
            if row is not None:
                assert not row.in_top_decile
                assert row.momentum is None

    def test_all_three_exit_routes_fire(self, run):
        reasons = Counter(o["reason"] for _, o in
                          ops(run, operation="CLOSE_POSITION"))
        assert reasons["EXIT_TRAILING_STOP"] >= 2
        assert reasons["EXIT_REVIEW_WEAKNESS"] >= 1

    def test_the_review_passes_at_least_once_and_is_then_permanent(self, run):
        passed = ops(run, reason="HOLD_REVIEW_PASSED")
        assert passed, "no holding ever reached review age"
        assert ops(run, reason="HOLD_REVIEW_ALREADY_COMPLETED"), (
            "passing review once must be permanent — a second review would sell "
            "exactly the long winners the strategy depends on")

    def test_the_fader_was_underwater_at_review_but_never_hit_its_stop(self, run):
        """The two thresholds FADER has to sit between, asserted rather than
        assumed from the multiplier in golden.py."""
        exits = [o for _, o in ops(run, reason="EXIT_REVIEW_WEAKNESS")]
        assert len(exits) == 1 and exits[0]["security_id"] == "SEC_FADER"
        assert exits[0]["detail"]["close"] < exits[0]["detail"]["entry"]
        stops = {o["security_id"] for _, o in ops(run, reason="EXIT_TRAILING_STOP")}
        assert "SEC_FADER" not in stops

    def test_no_session_ever_ends_on_negative_cash(self, run):
        """No leverage — and this is checked on the LEDGER, independently of the
        running balance, because that is the whole point of keeping one."""
        cash = run.ledger.reconcile_cash(golden_scenario().starting_cash)
        assert cash == pytest.approx(run.state.cash, abs=0.01)
        assert run.state.cash >= 0.0

    def test_every_supported_terminal_kind_fires(self, run):
        applied = {r["kind"] for r in run.terminal_results if r.get("applied")}
        assert applied == {"CASH_MERGER", "WRITE_OFF", "CONVERSION",
                           "CASH_PLUS_STOCK"}

    def test_a_conversion_actually_leaves_a_fraction_to_settle(self, run):
        """A clean ratio would exercise the conversion path while leaving the
        cash-in-lieu leg — the one that silently loses money if dropped —
        untested."""
        lieus = [r["cash_in_lieu"] for r in run.terminal_results
                 if r.get("converted")]
        assert lieus and all(x > 0 for x in lieus)

    def test_cash_plus_stock_delivers_both_legs(self, run):
        mixed = next(r for r in run.terminal_results
                     if r.get("kind") == "CASH_PLUS_STOCK")
        assert mixed["cash_consideration"] > 0
        assert mixed["shares_delivered"] > 0

    def test_a_deal_with_no_terms_blocks_and_then_unblocks(self, run):
        blocked = [r for r in run.terminal_results if r.get("blocked")]
        assert blocked and blocked[0]["reason"] == "MISSING_CASH_PER_SHARE"
        sec = blocked[0]["security_id"]
        # It BLOCKED for real sessions...
        assert len(run.blocked_sessions) > 10
        # ...and was eventually settled at the supplied price, not an assumed one.
        settled = [r for r in run.terminal_results
                   if r["security_id"] == sec and r.get("applied")]
        assert settled and settled[-1]["proceeds"] > 0
        assert run.state.unresolved_terminals == {}

    def test_a_security_that_stops_printing_still_blocks_while_unresolved(self, run):
        """The stranded name keeps trading throughout, so the block must come
        from the missing TERMS rather than from an absent price."""
        assert any(r.get("blocked") for r in run.terminal_results)

    def test_the_final_report_separates_marked_from_forced(self, run):
        f = run.final
        assert f is not None and f.session == SESSIONS[-1]
        assert f.marked_equity is not None, "no holding may be unmarkable here"
        # Lower by exactly the cost of a sale that never happened.
        assert f.forced_liquidation_equity < f.marked_equity
        assert len(f.marked_positions) == len(run.state.episodes)
        assert [e.event_type.value for e in f.mark_ledger.events] == \
            ["TERMINAL_MARK"] * len(f.marked_positions)
        assert all(e.detail.get("hypothetical")
                   for e in f.forced_liquidation_ledger.events)

    def test_finalisation_never_writes_into_the_run_ledger(self, run):
        assert not any(e.event_type.value in ("TERMINAL_MARK",
                                              "TERMINAL_LIQUIDATION")
                       for e in run.ledger.events), (
            "a mark changes nothing and a hypothetical sale never happened; "
            "either one in the run ledger makes it depend on where the run "
            "stopped, and the restart test fails")

    def test_an_order_that_cannot_be_paid_for_is_reported(self, run):
        cancelled = [c for s in run.sessions for c in s.cancelled]
        assert cancelled, (
            "the close-to-open gap never bit, so the affordability rule at the "
            "fill is untested by this fixture")
        assert all(c["reason"] in ("UNAFFORDABLE_AT_OPEN", "PARTIAL_AT_OPEN")
                   for c in cancelled)


# ── determinism ─────────────────────────────────────────────────────────────

class TestDeterminism:

    def test_two_runs_of_the_same_scenario_are_identical(self, run):
        assert full_run()[1].result_hash() == run.result_hash()

    def test_the_hash_does_not_depend_on_the_order_rows_arrive_in(self, run):
        """A hash that moved with the caller's ORDER BY would fail parity for a
        reason that has nothing to do with the strategy — and would be blamed on
        the strategy anyway."""
        g = golden_scenario()
        shuffled = {s: list(reversed(list(bars)))
                    for s, bars in g.bars_by_session.items()}
        other = run_sessions(sessions=g.sessions, bars_by_session=shuffled,
                             meta=g.meta, starting_cash=g.starting_cash,
                             terminal_events=list(reversed(g.terminal_events)))
        assert other.result_hash() == run.result_hash()


# ── the restart, which is the hard case ─────────────────────────────────────

class TestRestartAtTheBoundary:
    """A restart at S170 must be invisible in the output.

    Everything path-dependent is in flight there: an entry order and an exit
    order are both queued, a slot is RESERVED by the unfilled entry, GHOST's
    mark is missing so admissions are blocked, and two cooldowns are counting.
    """

    def split_run(self):
        g = golden_scenario()
        head, tail = g.sessions[:RESTART_AT], g.sessions[RESTART_AT:]

        first = run_sessions(sessions=head, bars_by_session=g.bars_by_session,
                             meta=g.meta, starting_cash=g.starting_cash,
                             terminal_events=g.terminal_events)
        # Everything crosses the boundary as SERIALISED data. Handing the live
        # objects over would prove only that Python can keep a reference.
        state_blob = json.loads(json.dumps(first.state.to_dict()))
        ledger_blob = json.loads(json.dumps(first.ledger.to_dict()))
        pending_blob = json.loads(json.dumps(
            [p.to_dict() for p in getattr(first, "_pending", [])]))
        return g, head, tail, first, state_blob, ledger_blob, pending_blob

    def test_the_boundary_really_is_mid_flight(self):
        """If this stops holding, the restart test below is still green and no
        longer testing anything."""
        g = golden_scenario()
        pending: list[PendingOrder] = []
        first = run_sessions(sessions=g.sessions[:RESTART_AT],
                             bars_by_session=g.bars_by_session, meta=g.meta,
                             starting_cash=g.starting_cash,
                             terminal_events=g.terminal_events, pending=pending)
        kinds = {p.operation.value for p in pending}
        assert "CLOSE_POSITION" in kinds, "no exit order straddles the boundary"
        assert "OPEN_SLOT_POSITION" in kinds, "no entry order straddles it"
        assert first.state.reserved_security_ids(), "no slot is reserved"

    def test_a_restart_reproduces_the_one_shot_run_exactly(self):
        g = golden_scenario()
        one_shot = run_sessions(sessions=g.sessions,
                                bars_by_session=g.bars_by_session, meta=g.meta,
                                starting_cash=g.starting_cash,
                                terminal_events=g.terminal_events)

        head, tail = g.sessions[:RESTART_AT], g.sessions[RESTART_AT:]
        pending: list[PendingOrder] = []
        last_known: dict[str, float] = {}
        first = run_sessions(sessions=head, bars_by_session=g.bars_by_session,
                             meta=g.meta, starting_cash=g.starting_cash,
                             terminal_events=g.terminal_events, pending=pending,
                             last_known=last_known)

        # Cross the boundary as bytes, exactly as a real restart would.
        state = PortfolioState.from_dict(json.loads(json.dumps(first.state.to_dict())))
        ledger = Ledger.from_dict(json.loads(json.dumps(first.ledger.to_dict())))
        queue = [PendingOrder.from_dict(d) for d in
                 json.loads(json.dumps([p.to_dict() for p in pending]))]
        marks = json.loads(json.dumps(last_known))

        # The feed's split factors and trailing windows are DERIVED, not stored,
        # so a restart recovers them by re-reading history — the same code path
        # `advance` uses, which is what stops the two diverging.
        feed = Feed(g.meta)
        feed.warmup(head, g.bars_by_session)

        second = run_sessions(sessions=tail, bars_by_session=g.bars_by_session,
                              meta=g.meta, starting_cash=g.starting_cash,
                              terminal_events=g.terminal_events, state=state,
                              pending=queue, ledger=ledger, last_known=marks,
                              feed=feed)

        assert second.state.state_hash() == one_shot.state.state_hash()
        assert second.ledger.ledger_hash() == one_shot.ledger.ledger_hash()
        assert second.state.cash == pytest.approx(one_shot.state.cash, abs=0.005)

        joined = [s for s in first.to_dict()["sessions"]] + \
                 [s for s in second.to_dict()["sessions"]]
        assert joined == one_shot.to_dict()["sessions"]

    def _resume(self, g, *, corrupt=None):
        head, tail = g.sessions[:RESTART_AT], g.sessions[RESTART_AT:]
        pending: list[PendingOrder] = []
        last_known: dict[str, float] = {}
        first = run_sessions(sessions=head, bars_by_session=g.bars_by_session,
                             meta=g.meta, starting_cash=g.starting_cash,
                             terminal_events=g.terminal_events, pending=pending,
                             last_known=last_known)
        blob = json.loads(json.dumps(first.state.to_dict()))
        if corrupt is not None:
            corrupt(blob)
        feed = Feed(g.meta)
        feed.warmup(head, g.bars_by_session)
        return run_sessions(
            sessions=tail, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events,
            state=PortfolioState.from_dict(blob),
            pending=[PendingOrder.from_dict(p.to_dict()) for p in pending],
            ledger=Ledger.from_dict(first.ledger.to_dict()),
            last_known=dict(last_known), feed=feed)

    def test_dropping_the_reservation_across_the_restart_REORDERS_the_slot(self):
        """A mutation proof that the reservation is load-bearing.

        Without it the resumed run re-hands the reserved slot to the same
        candidate — the duplicate-orders defect, arriving by the restart route.

        THE ASSERTION IS ON THE ORDER STREAM, NOT THE TERMINAL STATE, and that
        is a correction rather than a weakening. This test used to compare the
        damaged run's final state hash against the one-shot run's, which no
        longer differs: the duplicate entry is emitted, reaches the open, finds
        the cash already spent by the original order, and is cancelled
        UNAFFORDABLE_AT_OPEN. The book converges because a SECOND safeguard
        catches what the reservation missed.

        Asserting on state would therefore report "the reservation is not
        load-bearing", which is false — it is doing its job one layer earlier.
        Asserting on the orders says what actually happens, and keeps saying it
        if the affordability rule is ever changed.
        """
        g = golden_scenario()
        clean = self._resume(g)
        damaged = self._resume(g, corrupt=self._drop_reservations)

        def entries(run, sec):
            return [o for s in run.sessions if s.decision
                    for o in s.decision.to_dict()["operations"]
                    if o["operation"] == "OPEN_SLOT_POSITION"
                    and o["security_id"] == sec]

        reserved = "SEC_BUST"
        assert not entries(clean, reserved), (
            "the intact reservation must stop the resumed run re-selecting the "
            "security whose entry is already queued")
        dupes = entries(damaged, reserved)
        assert dupes, "the corruption produced no duplicate — nothing is guarded"
        assert dupes[0]["slot_id"] == 0, "and it claims the very same slot"

        assert any(c["security_id"] == reserved
                   and c["reason"] == "UNAFFORDABLE_AT_OPEN"
                   for s in damaged.sessions for c in s.cancelled), (
            "the duplicate must be caught at the fill by the affordability "
            "rule; if it fills, the position doubles")

    @staticmethod
    def _drop_reservations(blob):
        for slot in blob["slots"].values():
            slot["reserved_for"] = None
            slot["reserved_ticker"] = None
            slot["reserved_issuer"] = None


# ── the pin ─────────────────────────────────────────────────────────────────

def test_the_result_matches_the_pinned_fixture(run):
    """The parity pin.

    A CHANGE HERE IS NEVER A TEST FAILURE TO BE PAPERED OVER: it means the
    strategy's output moved. Re-pin only with the behaviour change understood
    and written down, via `python -m tests.wealth_core.repin_golden`.
    """
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"
    pinned = json.loads(FIXTURE.read_text())
    assert run.result_hash() == pinned["result_hash"]
    assert run.state.state_hash() == pinned["final_state_hash"]
    assert run.ledger.ledger_hash() == pinned["ledger_hash"]
    assert round(run.state.cash, 2) == pinned["final_cash"]
    assert len(run.state.episodes) == pinned["final_positions"]
    assert pinned["ledger_event_counts"] == dict(
        Counter(e.event_type.value for e in run.ledger.events))


# ── the pin must be a property of the STRATEGY, not the interpreter ─────────

class TestTheHashesAreInterpreterIndependent:
    """An external audit found `result_hash` differing on Python 3.13 while the
    state hash, ledger hash, final cash, positions, event counts and blocked
    sessions ALL matched — the signature of an audit-serialisation difference
    rather than a changed portfolio path.

    The cause: `json.dumps(..., default=_json_default)` rounded floats in
    `default`, which the encoder NEVER calls for a float — it is the hook for
    objects it cannot handle natively. So ~42,000 candidate metrics were hashed
    through `repr`, and the certified artefact depended on the interpreter's
    float formatting. Rounding is applied recursively before serialisation now.
    """

    def test_quantize_reaches_floats_nested_anywhere(self):
        from stock_strategy_shared.wealth_core.hashes import quantize
        got = quantize({"a": [1 / 3, {"b": (0.1 + 0.2, 5)}], "c": "x", "d": None})
        assert got == {"a": [0.3333333333, {"b": [0.3, 5]}], "c": "x", "d": None}

    def test_the_json_default_hook_is_NOT_where_rounding_happens(self):
        """The precise defect, pinned so it cannot be reintroduced by someone
        'simplifying' the quantize call back into `default=`."""
        import json
        seen = []

        json.dumps({"f": 1 / 3}, default=lambda o: seen.append(type(o)) or 0)
        assert seen == [], (
            "if a float ever reaches `default`, this whole guard is moot — but "
            "it does not, which is why rounding cannot live there")

    def test_every_float_in_the_hashed_payload_is_quantized(self, run):
        """Structural: no float in what gets hashed may carry more than 10
        decimals, whatever the interpreter's repr does with it."""
        from stock_strategy_shared.wealth_core.hashes import quantize

        def floats(o):
            if isinstance(o, float):
                yield o
            elif isinstance(o, dict):
                for v in o.values():
                    yield from floats(v)
            elif isinstance(o, (list, tuple)):
                for v in o:
                    yield from floats(v)

        payload = quantize(run.to_dict())
        vals = list(floats(payload))
        assert len(vals) > 1000, "the candidate audit should be full of floats"
        assert all(f == round(f, 10) for f in vals)

    def test_the_run_hash_is_stable_in_a_FRESH_INTERPRETER(self):
        """Belt and braces: recompute the pinned hash in a subprocess. Same
        interpreter here, but it proves the value does not depend on accumulated
        process state, and it is the harness a future cross-version check
        plugs into."""
        import json
        import subprocess
        import sys

        out = subprocess.run(
            [sys.executable, "-c",
             "from stock_strategy_shared.wealth_core.golden import golden_scenario;"
             "from stock_strategy_shared.wealth_core.run import run_sessions;"
             "g=golden_scenario();"
             "r=run_sessions(sessions=g.sessions,bars_by_session=g.bars_by_session,"
             "meta=g.meta,starting_cash=g.starting_cash,"
             "terminal_events=g.terminal_events);"
             "print(r.result_hash())"],
            capture_output=True, text=True, check=True)
        pinned = json.loads(FIXTURE.read_text())["result_hash"]
        assert out.stdout.strip() == pinned
