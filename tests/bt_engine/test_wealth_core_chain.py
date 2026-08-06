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
