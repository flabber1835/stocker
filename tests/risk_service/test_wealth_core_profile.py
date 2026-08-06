"""`/check` enforcing the wealth_core_v1 profile, not the inherited limits.

WHY THIS PARTITION EXISTS. The target-portfolio limits were calibrated for a
strategy that rebalances toward normalised weights. Pointed at Wealth Core three
of them are not mis-tuned but WRONG IN KIND, and each fails silently:

    MAX_POSITION_PCT        reads a CONVERTED position — a takeover, not a
                            purchase — as a breach demanding a trim. That is a
                            trade this strategy does not have and must not learn.
    MAX_DAILY_TURNOVER_PCT  throttles exits during a drawdown, which is exactly
                            when the most capital needs to leave. A risk control
                            working against its own purpose.
    MAX_POSITIONS           counts held names and ignores slots RESERVED by
                            queued entries — already-committed capital — so it
                            over-admits by the number in flight.

Every one of them would return "approved" while enforcing a rule computed from
the wrong model of the book. So the dispatch is explicit, the profile is
verified by HASH rather than by name, and everything about it is fail-closed.

The falsifier is at the bottom: removing the dispatch must fail these tests.
"""
from __future__ import annotations

import asyncio

import pytest

import app.main as rs
from stock_strategy_shared.wealth_core.risk_profile import (
    PROFILE_NAME,
    WealthCoreRiskProfile,
)

HASH = WealthCoreRiskProfile().profile_hash()


class _BoomEngine:
    """An engine whose every connection attempt fails — a total DB outage.

    Distinct from `engine=None`, which is the service's DEGRADED mode: there the
    DB-dependent controls are skipped and the legacy path approves. Here they
    are attempted and fail, so the legacy path fails CLOSED. The difference
    matters for anything claiming the Wealth Core check does no I/O.
    """

    def connect(self):
        raise RuntimeError("DB down")


def ctx(**over):
    base = dict(equity=1_000_000.0, cash=500_000.0, held_positions=10,
                pending_reservations=0, entries_this_session=0)
    base.update(over)
    return rs.WealthCoreContext(**base)


def req(action="entry", side="buy", *, profile=PROFILE_NAME, phash=HASH,
        security_id="P:111", wealth_core=..., notional=40_000.0, **over):
    kw = dict(ticker="META", action=action, side=side, qty=100,
              notional=notional, mode="immediate", trade_type="paper",
              execution_model="stateful_ownership", risk_profile=profile,
              risk_profile_hash=phash, security_id=security_id,
              wealth_core=ctx() if wealth_core is ... else wealth_core)
    kw.update(over)
    return rs.TradeCheckRequest(**kw)


def decide(r):
    return asyncio.run(rs._decide(r))


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """No engine. The Wealth Core path must not touch the database at all — its
    inputs are supplied by the caller — so a DB outage cannot change a verdict.
    Leaving an engine in place would let a target-portfolio control run and mask
    that."""
    monkeypatch.setattr(rs, "engine", None)
    monkeypatch.delenv("KILL_SWITCH", raising=False)


# ── 1. the model is dispatched EXPLICITLY ───────────────────────────────────

class TestExplicitDispatch:

    def test_a_wealth_core_entry_is_judged_by_the_profile(self):
        approved, reason, rule, env = decide(req())
        assert approved is True and rule == "ok"
        assert "Wealth Core" in reason
        assert env["wealth_core_profile"]["name"] == PROFILE_NAME

    def test_the_legacy_model_is_UNTOUCHED_by_default(self):
        """Every existing caller omits `execution_model`, so the field defaults
        to target_portfolio and nothing about the legacy path changes."""
        r = rs.TradeCheckRequest(ticker="AAPL", action="entry", side="buy",
                                 qty=1, notional=100.0, mode="immediate")
        assert r.execution_model == "target_portfolio"
        _, _, rule, env = decide(r)
        assert "wealth_core" not in rule
        assert "wealth_core_profile" not in env

    def test_the_target_portfolio_limits_do_NOT_run(self, monkeypatch):
        """MAX_POSITIONS is 35 by default and the book holds 10 — so a passing
        entry proves nothing on its own. Set the INHERITED limit somewhere it
        would certainly bite and confirm the verdict does not move."""
        monkeypatch.setenv("MAX_POSITIONS", "1")
        monkeypatch.setenv("MAX_POSITION_PCT", "0.0001")
        monkeypatch.setenv("MAX_ORDER_NOTIONAL", "1.0")
        monkeypatch.setenv("MAX_DAILY_TURNOVER_PCT", "0.0")
        approved, _, rule, _ = decide(req())
        assert approved is True and rule == "ok", (
            "an inherited limit reached the Wealth Core path")


# ── 2/3. the profile is verified, and never defaulted ───────────────────────

class TestTheProfileIsVerifiedNotAssumed:

    def test_a_MISSING_profile_is_refused(self):
        approved, _, rule, _ = decide(req(profile=None))
        assert approved is False and rule == "wealth_core_profile_missing"

    def test_an_UNKNOWN_profile_is_refused(self):
        approved, _, rule, _ = decide(req(profile="wealth_core_v2"))
        assert approved is False and rule == "wealth_core_profile_unknown"

    def test_a_MISSING_hash_is_refused(self):
        approved, _, rule, _ = decide(req(phash=None))
        assert approved is False and rule == "wealth_core_profile_hash_missing"

    def test_a_MISMATCHED_hash_is_refused(self):
        approved, reason, rule, _ = decide(req(phash="0000000000000000"))
        assert approved is False and rule == "wealth_core_profile_hash_mismatch"
        assert HASH in reason, "the reason must name the hash actually configured"

    def test_the_HASH_is_what_catches_a_silently_loosened_limit(self):
        """The case a name-only check cannot see. A deploy that raised
        `maximum_positions` without renaming anything still presents
        `wealth_core_v1`, and a name check accepts it — the two sides then
        enforce different limits with nothing saying so."""
        loosened = WealthCoreRiskProfile(maximum_positions=999)
        assert loosened.name == PROFILE_NAME
        assert loosened.profile_hash() != HASH
        approved, _, rule, _ = decide(req(phash=loosened.profile_hash()))
        assert approved is False and rule == "wealth_core_profile_hash_mismatch"

    def test_NOTHING_falls_back_to_the_default_risk_behaviour(self):
        """Each refusal must be a REFUSAL, not a quiet downgrade. If any of
        these were approved on the legacy path the order would go out under
        limits nobody selected."""
        for bad in (req(profile=None), req(profile="other"), req(phash=None),
                    req(phash="deadbeefdeadbeef")):
            approved, _, rule, _ = decide(bad)
            assert approved is False
            assert rule.startswith("wealth_core_"), rule


# ── 4. stateful rules are SUPPLIED, never reconstructed ─────────────────────

class TestTheStatefulContextCannotBeInferred:

    def test_a_buy_without_context_is_REFUSED(self):
        """Held positions, slot reservations and the per-session admission count
        are path-dependent. A default of zero-held/zero-reserved approves every
        entry, so absence must refuse rather than default."""
        approved, reason, rule, _ = decide(req(wealth_core=None))
        assert approved is False and rule == "wealth_core_context_missing"
        assert "cannot be reconstructed" in reason

    def test_RESERVATIONS_count_toward_the_position_limit(self):
        """The concrete defect in the inherited MAX_POSITIONS: a queued entry is
        committed capital. 24 held + 1 reserved is AT the 25 limit even though
        only 24 names are owned."""
        ok = decide(req(wealth_core=ctx(held_positions=24,
                                        pending_reservations=0)))
        assert ok[0] is True
        blocked = decide(req(wealth_core=ctx(held_positions=24,
                                             pending_reservations=1)))
        assert blocked[0] is False
        assert blocked[2] == "wealth_core_max_positions"

    def test_the_one_entry_per_session_rule_is_enforced(self):
        blocked = decide(req(wealth_core=ctx(entries_this_session=1)))
        assert blocked[0] is False
        assert blocked[2] == "wealth_core_max_entries_per_session"

    def test_UNRESOLVED_equity_blocks_an_admission(self):
        """4% of an unknown is not a number — the equity gate, restated at the
        risk layer."""
        approved, _, rule, _ = decide(req(wealth_core=ctx(equity=None)))
        assert approved is False and rule == "wealth_core_unresolved_equity"

    def test_the_check_reads_NO_DATABASE(self, monkeypatch):
        """Its inputs come from the caller, so a DB outage cannot move a Wealth
        Core verdict.

        Asserted against an engine whose every connection RAISES, not against
        `engine=None`. The latter is the service's degraded mode, in which the
        DB-dependent controls are skipped — so a passing verdict there would be
        consistent with the check having tried and given up. A failing engine
        proves it never asked.
        """
        monkeypatch.setattr(rs, "engine", _BoomEngine())
        approved, _, rule, _ = decide(req())
        assert approved is True and rule == "ok"


# ── 4b. the opening is a different regime from the steady state ─────────────

class TestInitialConstruction:
    """Spec §6: the opening fills every available slot TOGETHER; only afterwards
    is there at most one admission per session.

    This was not a hypothetical omission. The profile originally knew only the
    steady-state rule, and the wind-tunnel chain rehearsal — the first thing to
    drive the live path session by session — reported 25 rejected intents on the
    opening: the gate refused 24 of the 25 admissions `decide()` had just made,
    so live the book would never have been constructed at all. The unit tests
    were green throughout, because each one asked about a single admission in a
    book that already existed.

    The exemption is deliberately NARROW: only the two SESSION-SHAPED limits
    stand down, because they describe a steady state that does not exist yet.
    Everything that bounds RISK rather than PACE still binds, and there is a
    case below for each.
    """

    def _opening(self, **over):
        # 24 slots already reserved in this same opening and 24 admissions
        # already made — both session-shaped limits far exceeded — with the 25th
        # slot still free, so nothing but those two limits is in play.
        base = dict(held_positions=0, pending_reservations=24,
                    entries_this_session=24, is_initial_construction=True)
        base.update(over)
        return req(wealth_core=ctx(**base))

    def test_the_opening_admits_past_both_session_shaped_limits(self):
        approved, _, rule, _ = decide(self._opening())
        assert approved is True and rule == "ok"

    def test_the_SAME_order_is_REFUSED_in_the_steady_state(self):
        """The falsifier for the exemption. If this passed too, the exemption
        would not be an exemption — it would have removed the limits."""
        approved, reason, rule, _ = decide(
            self._opening(is_initial_construction=False))
        assert approved is False
        assert "MAX_PENDING_RESERVATIONS" in reason
        assert "MAX_ENTRIES_PER_SESSION" in reason
        assert rule == "wealth_core_max_pending_reservations"

    def test_the_default_is_the_STEADY_STATE(self):
        """A caller that says nothing gets the restrictive regime. The opening
        has to be asserted by the one component that knows the book is empty."""
        assert ctx().is_initial_construction is False

    def test_the_SLOT_COUNT_still_binds(self):
        """The opening fills slots; it does not exceed them. 25 in flight is a
        full book whether or not it is the first session."""
        approved, _, rule, _ = decide(self._opening(pending_reservations=25))
        assert approved is False and rule == "wealth_core_max_positions"

    def test_CASH_still_binds(self):
        approved, _, rule, _ = decide(self._opening(cash=100.0))
        assert approved is False
        assert rule == "wealth_core_min_cash_buffer"

    def test_CONCENTRATION_still_binds(self):
        approved, _, rule, _ = decide(
            self._opening(aggregate_exposure_after=0.5))
        assert approved is False
        assert rule == "wealth_core_max_single_security_exposure"

    def test_an_EXIT_is_unaffected_by_the_regime(self):
        """Stated because the exemption touches the entry path only, and the one
        thing that must never depend on which regime the book is in is getting
        out of it."""
        for initial in (True, False):
            approved, _, rule, _ = decide(req(
                "exit", "sell",
                wealth_core=ctx(is_initial_construction=initial)))
            assert approved is True and rule == "wealth_core_exit_exempt"


# ── 5. the permanent identity ───────────────────────────────────────────────

class TestPermanentIdentity:

    def test_security_id_is_REQUIRED(self):
        approved, reason, rule, _ = decide(req(security_id=None))
        assert approved is False and rule == "wealth_core_security_id_missing"
        assert "execution label" in reason

    def test_the_TICKER_alone_is_not_an_identity(self):
        """The same permanent security under two symbols must produce the same
        verdict — the label is not an input to any rule."""
        a = decide(req(ticker="FB", security_id="P:111"))
        b = decide(req(ticker="META", security_id="P:111"))
        assert a[0] == b[0] and a[2] == b[2]


# ── 6. exits are never blocked by entry-oriented rules ──────────────────────

class TestExitsAreExempt:

    @pytest.mark.parametrize("action", ["exit", "sell_trim", "risk_reduce"])
    def test_a_sell_is_approved_even_at_every_entry_limit(self, action):
        """Full book, reservations exhausted, admission already used, equity
        unresolved — every entry-side condition simultaneously against it."""
        approved, _, rule, _ = decide(req(
            action, "sell",
            wealth_core=ctx(equity=None, cash=0.0, held_positions=25,
                            pending_reservations=5, entries_this_session=1)))
        assert approved is True and rule == "wealth_core_exit_exempt"

    def test_a_sell_needs_no_context_at_all(self):
        """An exit must remain possible when the book's state cannot be
        assembled — that is the situation in which getting out matters most."""
        approved, _, rule, _ = decide(req("exit", "sell", wealth_core=None))
        assert approved is True and rule == "wealth_core_exit_exempt"

    def test_a_sell_is_exempt_from_any_turnover_cap(self):
        _, _, _, env = decide(req("exit", "sell"))
        assert env["verdict"]["exempt_from_turnover_cap"] is True

    def test_a_ZERO_notional_close_is_still_approved(self):
        """A held position whose local display price is missing sizes to a zero
        notional. The broker closes on quantity, so refusing here would trap a
        position over an audit-display gap."""
        approved, _, rule, _ = decide(req("exit", "sell", notional=0.0))
        assert approved is True and rule == "wealth_core_exit_exempt"

    def test_the_KILL_SWITCH_still_stops_a_sell(self, monkeypatch):
        """The one absolute halt. "Exits are exempt" is about STRATEGY limits;
        it must not become an exemption from the emergency brake."""
        monkeypatch.setenv("KILL_SWITCH", "true")
        approved, _, rule, _ = decide(req("exit", "sell"))
        assert approved is False and rule == "kill_switch"

    def test_a_LIVE_trade_is_still_gated(self, monkeypatch):
        monkeypatch.setenv("PAPER_ONLY", "true")
        approved, _, rule, _ = decide(req("exit", "sell", trade_type="live"))
        assert approved is False and rule in ("live_disabled", "paper_only")


# ── 7. a restart changes nothing ────────────────────────────────────────────

class TestRestartDeterminism:

    def test_the_profile_hash_is_identical_in_a_FRESH_PROCESS(self):
        """A restarted risk service must present the same hash, or every caller
        bound to the old one starts being rejected on redeploy.

        Checked in a SUBPROCESS rather than by reloading the module in-process.
        A reload is not what a restart does — it rebinds the enum classes while
        leaving already-imported references pointing at the originals, so
        `is not TurnoverBehavior.EXITS_EXEMPT` starts failing for a security
        that has not changed. That is an artefact of the test, and it would have
        been reported as a profile defect.
        """
        import subprocess
        import sys

        out = subprocess.run(
            [sys.executable, "-c",
             "from stock_strategy_shared.wealth_core.risk_profile import "
             "WealthCoreRiskProfile as P; print(P().profile_hash())"],
            capture_output=True, text=True, check=True)
        assert out.stdout.strip() == HASH

    def test_identical_requests_give_identical_verdicts_and_env(self):
        a = decide(req())
        b = decide(req())
        assert a[:3] == b[:3]
        assert a[3]["wealth_core_profile"] == b[3]["wealth_core_profile"]
        assert a[3]["wealth_core_profile_hash"] == b[3]["wealth_core_profile_hash"]

    def test_the_verdict_is_a_pure_function_of_the_request(self, monkeypatch):
        """Nothing about the decision may come from accumulated service state.
        Re-deciding a rejected request after an approved one must reject
        identically."""
        good = decide(req())
        bad = decide(req(wealth_core=ctx(entries_this_session=1)))
        assert decide(req())[:3] == good[:3]
        assert decide(req(wealth_core=ctx(entries_this_session=1)))[:3] == bad[:3]


# ── 8. the falsifier ────────────────────────────────────────────────────────

def test_WITHOUT_THE_DISPATCH_THE_SAME_ORDER_GETS_A_DIFFERENT_ANSWER(monkeypatch):
    """The control for this whole file, stated as the difference it makes.

    One identical order, judged under the two execution models. If the dispatch
    were removed — the state this work is fixing — a Wealth Core order would
    take the second answer.

    Both are judged with the SAME broken database, which is what makes the
    comparison fair. The inherited path needs one for MAX_POSITIONS and
    MAX_POSITION_PCT and so fails CLOSED; the Wealth Core profile approves the
    identical order without any I/O, because its inputs came from the caller.
    The two models do not merely disagree about a threshold — they disagree
    about what has to be known before an answer exists at all.

    If this ever stops diverging, the dispatch is inert and every test above is
    measuring the legacy path.
    """
    monkeypatch.setattr(rs, "engine", _BoomEngine())
    wc = req()
    legacy = req().model_copy(update={"execution_model": "target_portfolio"})

    wc_approved, _, wc_rule, _ = decide(wc)
    lg_approved, _, lg_rule, _ = decide(legacy)

    assert wc_approved is True and wc_rule == "ok"
    assert lg_approved is False, (
        "the inherited path approved a Wealth Core order with no database — "
        "then the two models agree and this control proves nothing")
    assert wc_rule != lg_rule
    assert lg_rule.endswith("_unavailable"), lg_rule


def test_the_dispatch_is_reached_for_stateful_ownership_only(monkeypatch):
    """A sharper form of the same control: record whether the Wealth Core gate
    was entered, per execution model."""
    seen: list[str] = []
    original = rs._decide_wealth_core

    def _spy(r, env):
        seen.append(r.execution_model)
        return original(r, env)

    monkeypatch.setattr(rs, "_decide_wealth_core", _spy)
    decide(req())
    assert seen == ["stateful_ownership"]

    seen.clear()
    decide(rs.TradeCheckRequest(ticker="AAPL", action="exit", side="sell",
                                qty=1, notional=100.0, mode="immediate"))
    assert seen == [], "the legacy path must not enter the Wealth Core gate"


def test_the_health_endpoint_publishes_what_it_will_enforce():
    """So a deploy can verify the live limits without submitting a trade — the
    alternative is discovering a hash mismatch from a rejected order at the
    open."""
    h = asyncio.run(rs.health())
    assert h["wealth_core_profile"] == PROFILE_NAME
    assert h["wealth_core_profile_hash"] == HASH
