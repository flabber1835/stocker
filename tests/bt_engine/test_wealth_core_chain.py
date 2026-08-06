"""The wind tunnel rehearsing the LIVE Wealth Core chain.

WHAT WAS MISSING. The tunnel could replay Wealth Core in BULK — one
`run_sessions` call over a whole stream. That exercises the strategy and nothing
about how it would be OPERATED: the live chain runs one session at a time, gates
every order through the risk profile, and records which stages ran. None of it
was reachable from any engine, so "would the live path produce this backtest?"
could not be asked.

THE ASSERTION THAT MATTERS is the equivalence: the session-by-session path must
reproduce the bulk path's terminal state and ledger exactly. Everything else
here is plumbing that makes the question askable. A rehearsal that diverges is
describing a different run than the engine it rehearses, so it raises rather
than reporting — the same posture as BASELINE_REPLAY.
"""
from __future__ import annotations

import pytest

from app.wealth_core_chain import (
    ChainRehearsalDiverged,
    STATEFUL_MODEL,
    rehearse_chain,
)
from stock_strategy_shared.wealth_core.execution_model import (
    LEGACY_STAGES_BYPASSED,
    STATEFUL_OWNERSHIP_CHAIN,
)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.golden import golden_scenario
from stock_strategy_shared.wealth_core.risk_profile import (
    PROFILE_NAME,
    WealthCoreRiskProfile,
)
from stock_strategy_shared.wealth_core.run import run_sessions

# A slice long enough to build the book AND reach the first exit (the STOPOUT
# crash resolves at S145), short enough to stay fast. A shorter slice makes
# `test_exits_are_exempt_wherever_they_occur` vacuous rather than failing, which
# is why the number is justified here rather than tuned until green.
SLICE = 160


@pytest.fixture(scope="module")
def scenario():
    g = golden_scenario()
    return g, list(g.sessions[:SLICE])


@pytest.fixture(scope="module")
def rehearsal(scenario):
    g, sessions = scenario
    return rehearse_chain(
        sessions=sessions, bars_by_session=g.bars_by_session, meta=g.meta,
        starting_cash=g.starting_cash, terminal_events=g.terminal_events,
        config={"execution_model": STATEFUL_MODEL})


# ── the equivalence: this is the test ───────────────────────────────────────

class TestTheLivePathReproducesTheReplay:

    def test_terminal_state_and_ledger_match_the_bulk_run(self, rehearsal):
        eq = rehearsal.equivalence
        assert eq["state_hash_matches"] is True
        assert eq["ledger_hash_matches"] is True
        assert eq["final_cash_matches"] is True

    def test_it_RAISES_rather_than_reporting_a_divergence(self, scenario,
                                                          monkeypatch):
        """The falsifier. Perturb the per-session path so it decides something
        the bulk path does not, and the rehearsal must refuse to report at all.

        A rehearsal that scored a divergent run would be describing a strategy
        nobody would get if they deployed it — worse than not running.
        """
        import app.wealth_core_chain as mod
        g, sessions = scenario

        real = mod.plan_session
        calls = {"n": 0}

        def _drifting(**kw):
            # Skip one session's decision entirely, a third of the way in: the
            # cheapest possible way to make the live path diverge from bulk.
            calls["n"] += 1
            if calls["n"] == SLICE // 3:
                from stock_strategy_shared.wealth_core.live import LiveSessionPlan
                return LiveSessionPlan(session=kw["session"])
            return real(**kw)

        monkeypatch.setattr(mod, "plan_session", _drifting)
        with pytest.raises(ChainRehearsalDiverged) as exc:
            rehearse_chain(
                sessions=sessions, bars_by_session=g.bars_by_session,
                meta=g.meta, starting_cash=g.starting_cash,
                terminal_events=g.terminal_events,
                config={"execution_model": STATEFUL_MODEL})
        assert "did not reproduce the bulk replay" in str(exc.value)

    def test_the_rehearsal_actually_traded(self, rehearsal):
        """Equivalence between two runs that both did nothing is not evidence.
        The slice has to build a book and issue orders."""
        assert rehearsal.final_positions > 0
        assert sum(len(s.intents) for s in rehearsal.sessions) > 0


# ── the chain, and the stages it does NOT run ───────────────────────────────

class TestTheChainRouting:

    def test_the_stateful_chain_is_what_ran(self, rehearsal):
        for t in rehearsal.traces:
            assert t["execution_model"] == STATEFUL_MODEL
            assert t["stages_invoked"] == list(STATEFUL_OWNERSHIP_CHAIN.steps)

    def test_every_legacy_stage_is_recorded_as_BYPASSED(self, rehearsal):
        """The claim "Wealth Core does not require the target-portfolio stages"
        is about runtime, and the trace is the only thing that can settle it."""
        for t in rehearsal.traces:
            assert set(LEGACY_STAGES_BYPASSED) <= set(t["stages_bypassed"])
            assert not (set(t["stages_invoked"]) & set(LEGACY_STAGES_BYPASSED))

    def test_the_traces_VALIDATE(self, rehearsal):
        assert rehearsal.trace_problems == [], rehearsal.trace_problems

    def test_a_target_portfolio_config_is_REFUSED(self, scenario):
        """Rehearsing a config through a chain it does not select would report
        on a strategy the config does not describe."""
        g, sessions = scenario
        with pytest.raises(ValueError, match="resolves to"):
            rehearse_chain(sessions=sessions[:5],
                           bars_by_session=g.bars_by_session, meta=g.meta,
                           starting_cash=g.starting_cash,
                           config={"execution_model": "target_portfolio"})

    def test_NOTHING_is_submitted(self, rehearsal):
        """A dry run that submitted would be flagged by `validate()`; asserted
        directly too, because this is the property that makes it safe to run
        against real data."""
        assert all(t["orders_submitted"] == 0 for t in rehearsal.traces)


# ── the risk profile gates every order ──────────────────────────────────────

class TestRiskIsApplied:

    def test_every_intent_carries_a_verdict(self, rehearsal):
        for s in rehearsal.sessions:
            assert len(s.risk_verdicts) == len(s.intents)

    def test_the_profile_is_the_certified_one(self, rehearsal):
        assert rehearsal.profile_hash == WealthCoreRiskProfile().profile_hash()
        assert rehearsal.to_dict()["risk_profile"] == PROFILE_NAME

    def test_exits_are_exempt_wherever_they_occur(self, rehearsal):
        exits = [v for s in rehearsal.sessions for v, i in
                 zip(s.risk_verdicts, s.intents)
                 if i["operation"] == "CLOSE_POSITION"]
        assert exits, "the slice produced no exits — the exemption is untested"
        assert all(v["approved"] and v["rule"] == "wealth_core_exit_exempt"
                   for v in exits)

    def test_the_OPENING_is_admitted_rather_than_mass_rejected(self, rehearsal):
        """The defect this rehearsal found on its first run, pinned here.

        Spec §6 opens the book by filling every available slot in one session.
        The risk profile knew only the steady-state rule — one admission per
        session, five reservations — so it refused 24 of the 25 opening entries
        and the book was never constructed. Every unit test was green, because
        each asked about a single admission in a book that already existed.
        """
        opening = max(rehearsal.sessions,
                      key=lambda s: sum(1 for i in s.intents
                                        if i["operation"] == "OPEN_SLOT_POSITION"))
        entries = [v for v, i in zip(opening.risk_verdicts, opening.intents)
                   if i["operation"] == "OPEN_SLOT_POSITION"]
        assert len(entries) > 1, (
            "the slice never opened more than one slot in a session — the "
            "initial-construction regime is untested")
        assert all(v["approved"] for v in entries), [
            v["reasons"] for v in entries if not v["approved"]]

    def test_WITHOUT_THE_EXEMPTION_the_rehearsal_SURFACES_the_rejections(
            self, scenario, monkeypatch):
        """The falsifier, and the demonstration of what the rehearsal is for.

        Force the steady-state regime and the same run reports a wall of
        refusals. Note it does NOT diverge — risk is observational here, so the
        strategy still trades — which is precisely why this had to be found by
        counting rejected intents rather than by a hash mismatch.
        """
        import app.wealth_core_chain as mod
        g, sessions = scenario
        real = mod.evaluate_entry
        monkeypatch.setattr(
            mod, "evaluate_entry",
            lambda **kw: real(**{**kw, "is_initial_construction": False}))
        # The opening cannot happen before the formation window closes (~S126),
        # so a short prefix would pass this vacuously.
        r = rehearse_chain(
            sessions=sessions, bars_by_session=g.bars_by_session,
            meta=g.meta, starting_cash=g.starting_cash,
            terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL})
        assert r.rejected_intents > 10, (
            "the exemption made no difference — either the opening no longer "
            "fills multiple slots, or the gate is not being consulted")

    def test_the_book_actually_REACHES_max_positions(self, rehearsal):
        """The question a rejection count cannot answer.

        The first cut reported "1 rejected intent, 24 positions", which reads as
        a legitimate refusal and was not. `plan_session` RESERVES the slot at the
        moment of decision, so by the time the gate ran, the intent's OWN
        reservation was already in `reserved_security_ids()`. Counting it made
        `projected` one too high for every entry, and at the 25th admission that
        is the difference between a full book and a permanently short one:
        24 held + its own reservation = 25 >= maximum_positions, refused FOREVER.

        A book that can never fill its last slot is a 4% allocation of dead cash
        and a strategy that is not the one that was backtested — and the only
        symptom was a plausible-looking count.
        """
        assert rehearsal.peak_book_size == WealthCoreConfig().n_slots

    def test_the_opening_shortfall_is_filled_by_NORMAL_admission(self, rehearsal):
        """Why the opening session alone does not fill all 25.

        At S126 only 24 candidates are eligible, so `decide()` opens 24 slots —
        the ready set, not the slot count, is the binding constraint. The 25th is
        admitted the NEXT session under the ordinary one-per-session rule and
        fills the session after. That is the second of the two acceptable
        outcomes for an under-filled opening; the first (backfill within the
        opening itself) does not apply because there was no further eligible
        candidate to backfill WITH.

        Asserted rather than assumed, because the alternative explanation for a
        24-name book is a gate that cannot count — which is what it turned out
        to be the first time.
        """
        opening = next(s for s in rehearsal.sessions
                       if any(i["operation"] == "OPEN_SLOT_POSITION"
                              for i in s.intents))
        n_open = sum(1 for i in opening.intents
                     if i["operation"] == "OPEN_SLOT_POSITION")
        assert n_open < WealthCoreConfig().n_slots, (
            "the opening filled every slot, so this scenario no longer exercises "
            "the shortfall path")
        held = {b["session"]: b["held"] for b in rehearsal.book_size_by_session}
        order = [b["session"] for b in rehearsal.book_size_by_session]
        i = order.index(opening.session)
        # Within a handful of sessions of the opening, the book is full.
        assert max(held[s] for s in order[i:i + 5]) == WealthCoreConfig().n_slots

    def test_WITHOUT_THE_EXCLUSION_the_last_slot_can_never_be_FILLED(
            self, scenario, monkeypatch):
        """The falsifier. Put the intent's own reservation back into the count
        and the 25th admission is refused — the original defect, reproduced."""
        import app.wealth_core_chain as mod
        g, sessions = scenario
        real = mod.evaluate_entry
        monkeypatch.setattr(mod, "evaluate_entry", lambda **kw: real(
            **{**kw, "pending_reservations": kw["pending_reservations"] + 1}))
        r = rehearse_chain(
            sessions=sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL})
        assert any(x["rule"] == "wealth_core_max_positions"
                   for x in r.rejections), r.rejections

    def test_every_entry_is_PRICED(self, rehearsal):
        """A notional of zero makes MIN_CASH_BUFFER, INSUFFICIENT_CASH and both
        concentration caps unreachable. The first cut read `intent["price"]`, a
        key `OrderIntent.to_dict()` does not emit, so EVERY entry was gated at
        zero while the suite reported "every intent carries a verdict"."""
        assert rehearsal.entries_without_a_price == 0
        entries = [v for s in rehearsal.sessions for v, i in
                   zip(s.risk_verdicts, s.intents)
                   if i["operation"] == "OPEN_SLOT_POSITION"]
        assert entries
        assert all(v["notional"] > 0 for v in entries)

    def test_the_gate_receives_a_REAL_notional_and_REAL_exposure(
            self, scenario, monkeypatch):
        """Captured at the call, because the inertness was silent: a zero
        notional changes no verdict in this scenario, so nothing about the
        RESULT would have revealed it."""
        import app.wealth_core_chain as mod
        g, sessions = scenario
        real, seen = mod.evaluate_entry, []

        def _spy(**kw):
            seen.append(kw)
            return real(**kw)

        monkeypatch.setattr(mod, "evaluate_entry", _spy)
        rehearse_chain(sessions=sessions[:130],
                       bars_by_session=g.bars_by_session, meta=g.meta,
                       starting_cash=g.starting_cash,
                       terminal_events=g.terminal_events,
                       config={"execution_model": STATEFUL_MODEL})
        assert seen, "no entry reached the gate"
        assert all(kw["notional"] > 0 for kw in seen)
        # ~4% of equity per admission, so the post-entry weight must be in that
        # neighbourhood — a decisive check that the exposure is computed rather
        # than defaulted to the 0.0 the signature allows.
        assert all(0.001 < kw["aggregate_exposure_after"] < 0.25 for kw in seen)
        assert all(kw["issuer_exposure_after"] >= kw["aggregate_exposure_after"]
                   for kw in seen)

    def test_a_ZERO_notional_cannot_trip_the_CASH_rules(self):
        """Why the point above matters, at the pure-function level: an entry
        priced at zero passes the cash gates no matter how broke the book is.

        Cash only — the concentration caps take a caller-supplied exposure, so
        they fail independently of the notional. Both were inert in the first
        cut, but for two different reasons (a key that did not exist, and a
        default of 0.0 nobody overrode), and collapsing them into one assertion
        would leave whichever one got fixed first covering for the other."""
        from stock_strategy_shared.wealth_core.risk_profile import (
            WealthCoreRiskProfile, evaluate_entry as ev)
        broke = dict(profile=WealthCoreRiskProfile(), equity=1_000_000.0,
                     cash=0.0, held_positions=1, pending_reservations=0,
                     entries_this_session=0)
        assert ev(**{**broke, "notional": 0.0}).approved is True
        bad = ev(**{**broke, "notional": 40_000.0})
        assert bad.approved is False
        assert set(bad.reasons) == {"MIN_CASH_BUFFER", "INSUFFICIENT_CASH"}

    def test_a_DEFAULTED_exposure_cannot_trip_the_concentration_caps(self):
        """The other half. `aggregate_exposure_after` defaults to 0.0 in the
        signature, so a caller that simply never computes it — the first cut —
        gets a green verdict from a limit that never ran."""
        from stock_strategy_shared.wealth_core.risk_profile import (
            WealthCoreRiskProfile, evaluate_entry as ev)
        base = dict(profile=WealthCoreRiskProfile(), equity=1_000_000.0,
                    cash=1_000_000.0, notional=40_000.0, held_positions=1,
                    pending_reservations=0, entries_this_session=0)
        assert ev(**base).approved is True, "the default silently passes"
        assert ev(**base, aggregate_exposure_after=0.99).approved is False

    def test_a_rejection_is_NAMED_not_merely_counted(self, scenario,
                                                     monkeypatch):
        """"One rejection" is not something a reader can act on. The session,
        the security, the rule and the counts the rule READ are what turn a
        number into a diagnosis — and reading those counts back is how the
        double-count was found."""
        import app.wealth_core_chain as mod
        g, sessions = scenario
        real = mod.evaluate_entry
        monkeypatch.setattr(mod, "evaluate_entry", lambda **kw: real(
            **{**kw, "pending_reservations": kw["pending_reservations"] + 1}))
        r = rehearse_chain(
            sessions=sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL})
        assert len(r.rejections) == r.rejected_intents
        for x in r.rejections:
            assert x["session"] and x["security_id"] and x["rule"]
            assert x["held_positions"] is not None
            assert x["pending_reservations"] is not None
        assert r.to_dict()["rejections"] == r.rejections

    def test_a_rejected_intent_is_COUNTED_not_silently_dropped(self, rehearsal):
        """The rehearsal reports rejections rather than filtering them: an order
        the risk layer would refuse is exactly what a rehearsal exists to
        surface before it happens live."""
        counted = sum(1 for s in rehearsal.sessions for v in s.risk_verdicts
                      if not v["approved"])
        assert rehearsal.rejected_intents == counted


# ── the modules really are the live ones ────────────────────────────────────

def test_the_rehearsal_calls_THE_LIVE_planner_not_a_copy():
    """MODULE IDENTITY, which is strictly stronger than byte equality: there is
    one object, so drift is impossible rather than merely detected. A tunnel
    rehearsing its own copy of the planner would prove nothing about the live
    path."""
    import app.wealth_core_chain as mod
    import stock_strategy_shared.wealth_core.live as canonical
    assert mod.plan_session is canonical.plan_session


def test_the_service_shims_ARE_the_canonical_modules():
    """The scheduler and pipeline keep their import paths, so nothing on the
    live chain changed — but they must resolve to the same objects the tunnel
    uses, or the rehearsal and the deployment diverge silently."""
    import importlib
    import sys

    for shim_path, canon_path in (
            ("app.execution_model",
             "stock_strategy_shared.wealth_core.execution_model"),
            ("app.wealth_core_live", "stock_strategy_shared.wealth_core.live")):
        # The shims live in other services' app packages; import the canonical
        # side and assert the shim file performs the sys.modules replacement.
        canon = importlib.import_module(canon_path)
        assert canon is sys.modules[canon_path]
        assert canon.__name__ == canon_path


# ── live progress ────────────────────────────────────────────────────────────

class TestLiveProgress:
    """A three-year rehearsal is hours of silence otherwise: the chain loop logs
    nothing and the run row carries only `running`. These snapshots are the only
    signal that it is working rather than wedged.

    They are PROVISIONAL by construction — measured mid-run, before the parity
    check that decides whether the run means anything at all. That is the whole
    reason they are a separate field from `performance` rather than an early
    version of it.
    """

    def _collect(self, scenario, **kw):
        g, sessions = scenario
        seen = []
        rehearse_chain(
            sessions=sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL},
            on_progress=seen.append, **kw)
        return seen, sessions

    def test_percentage_rises_monotonically_and_ends_at_one_hundred(self, scenario):
        seen, sessions = self._collect(scenario, progress_every=10)
        assert seen, "no progress was published at all"
        pcts = [s["pct"] for s in seen]
        assert pcts == sorted(pcts)
        assert pcts[-1] == 100.0
        assert seen[-1]["sessions_done"] == len(sessions)
        assert all(s["sessions_total"] == len(sessions) for s in seen)

    def test_the_final_snapshot_always_fires_regardless_of_the_interval(self, scenario):
        """`progress_every` must not be able to leave the bar short of 100%: a
        run that stops at 97% reads as hung."""
        for every in (7, 13, 100):
            seen, sessions = self._collect(scenario, progress_every=every)
            assert seen[-1]["pct"] == 100.0, f"progress_every={every} ended short"

    def test_each_snapshot_carries_a_running_measurement(self, scenario):
        seen, _ = self._collect(scenario, progress_every=20)
        last = seen[-1]["performance"]
        assert seen[-1]["provisional"] is True
        assert last["evaluable"] is True
        assert last["ending_equity"] is not None
        assert last["maximum_drawdown"] is not None
        assert seen[-1]["current_session"]

    def test_a_blocked_session_does_not_blank_the_running_measurement(self, scenario):
        """The golden slice blocks sessions. Under the STRICT rule the running
        figure would read `unevaluable` for the rest of the run — hours of a
        progress display showing nothing, which is why the indicator takes the
        tolerant reading and the final block does not."""
        # The FULL scenario: the slice used elsewhere stops at S160 and the
        # blocked stretch begins at S170, so a slice-based version of this test
        # would pass vacuously.
        g, _ = scenario
        seen = []
        rehearse_chain(
            sessions=list(g.sessions), bars_by_session=g.bars_by_session,
            meta=g.meta, starting_cash=g.starting_cash,
            terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL},
            on_progress=seen.append, progress_every=10)
        blocked_seen = [s for s in seen
                        if s["performance"]["blocked_session_count"] > 0]
        assert blocked_seen, "slice never blocks — this test proves nothing"
        assert all(s["performance"]["evaluable"] for s in blocked_seen)
        assert all(s["performance"]["maximum_drawdown_is_lower_bound"]
                   for s in blocked_seen)

    def test_the_benchmark_comparison_rides_along_live(self, scenario):
        g, sessions = scenario
        # A synthetic SPY that gains steadily across the slice.
        bench = {d: 100.0 * (1.0 + i / 1000.0) for i, d in enumerate(sessions)}
        seen = []
        r = rehearse_chain(
            sessions=sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL},
            on_progress=seen.append, progress_every=20,
            benchmark_closes=bench, benchmark_ticker="SPY")

        live = seen[-1]["performance"]
        assert live["benchmark_ticker"] == "SPY"
        assert live["benchmark_total_return"] is not None
        assert live["excess_total_return"] is not None
        # …and the FINAL block carries it too, from the same code.
        final = r.performance_excluding_blocked or r.performance
        assert final["benchmark_total_return"] is not None

    def test_no_callback_means_no_work_and_no_crash(self, scenario):
        g, sessions = scenario
        r = rehearse_chain(
            sessions=sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events,
            config={"execution_model": STATEFUL_MODEL})
        assert r.equivalence["state_hash_matches"] is True

    def test_progress_is_not_published_after_a_divergence(self, scenario, monkeypatch):
        """A diverged run raises, so the LAST thing an operator saw was a
        healthy-looking snapshot. That is acceptable only because no final
        metrics are published — this pins that the raise still happens."""
        import app.wealth_core_chain as mod
        g, sessions = scenario
        seen = []

        real = mod.run_with_hashes

        def _sabotage(**kw):
            result, hashes = real(**kw)
            result.state.cash += 1.0          # make the bulk state differ
            return result, hashes

        monkeypatch.setattr(mod, "run_with_hashes", _sabotage)
        with pytest.raises(ChainRehearsalDiverged):
            rehearse_chain(
                sessions=sessions, bars_by_session=g.bars_by_session,
                meta=g.meta, starting_cash=g.starting_cash,
                terminal_events=g.terminal_events,
                config={"execution_model": STATEFUL_MODEL},
                on_progress=seen.append, progress_every=20)
        assert seen, "progress did fire during the run"
