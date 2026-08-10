"""A split is a TRANSFORMATION, not a sale. No value may leave the book.

THE DEFECT, reproduced 2026-08-09 before anything was changed:

    ep.current_shares = int(before * b.split_ratio)

    15 shares  x 1.5      exact 22.5      engine 22    lost 0.5 sh  = $33.33
    100 shares 1-for-7    exact 14.2857   engine 14    lost 0.2857  = $200.00

That last one is 2% of a $10,000 position, destroyed silently: no fractional
holding, no cash-in-lieu, no receivable, no ledger event. The position simply
became worth less and nothing recorded why.

Nobody traded, so nothing may be lost. The terminal-CONVERSION path already held
this standard — it REFUSES to apply without a cash-in-lieu price rather than
dropping the stub — and an ordinary split had been held to a lower one.

THE POLICY (owner decision): preserve FRACTIONAL ENTITLEMENT canonically rather
than inventing cash-in-lieu inside the alpha engine. Cash-in-lieu needs a
per-share price at the action instant the vendor does not supply, and it is
broker-specific treatment. Integer-share constraints are a BROKER fact and
belong in the execution projection.

ENTRY SIZING IS UNCHANGED and still whole shares — buying is a TRADE against a
real order book, which is a different question from transforming a holding.

THE INVARIANT IS ECONOMIC VALUE, not share count:

    shares_before x price_before  ==  shares_after x price_after
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    step_session, tradeability_only_bars)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.settlement import (
    C1_GRACE_SESSIONS, empty_counters)
from stock_strategy_shared.wealth_core.shares import as_json, split_shares
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def seated(shares, entry=100.0, cash=1_000.0):
    st = PortfolioState.fresh(cash)
    st.slots[0].occupied_by = "S1"
    st.episodes[0] = HoldingEpisode("S1", "T1", "I1", 0, "d0", "d0",
                                    entry, entry, shares, shares, entry)
    st.initialized = True
    st.last_valid_mark_session["S1"] = "d0"
    return st


def bar(session="d1", *, close, split=1.0):
    return DailyBar(security_id="S1", ticker="T1", issuer_id="I1",
                    session=session, signal_close_split_adj_div_unadj=close,
                    raw_open=close, raw_mark_close=close, tradeable=True,
                    split_ratio=split, dividend_per_share=0.0,
                    unresolved_corporate_action=False)


def apply(st, ratio, px_after, session="d1", ledger=None, last_known=None):
    b = [bar(session, close=px_after, split=ratio)]
    step_session(session=session, state=st, bars=b, pending=[],
                 ledger=ledger or Ledger(),
                 last_known=last_known if last_known is not None else {},
                 cfg=CFG, strategy_id=SID, strategy_version=VER,
                 security_bars=tradeability_only_bars(b, None))
    return st.episodes[0].current_shares if 0 in st.episodes else 0


# ── 1. the arithmetic ────────────────────────────────────────────────────────

class TestNoShareIsTruncated:

    def test_the_reported_forward_case(self):
        st = seated(15, entry=90.0)
        assert apply(st, 1.5, 60.0) == pytest.approx(22.5), (
            "15 x 1.5 truncated to 22 — half a share destroyed with no record")

    def test_a_hostile_REVERSE_split(self):
        """1-for-7 on 100 shares. The engine returned 14 and lost 0.2857
        shares — 2% of the position."""
        st = seated(100, entry=100.0)
        got = apply(st, 1 / 7, 700.0)
        assert got == pytest.approx(100 / 7, rel=1e-9)
        assert got != 14

    def test_an_EXACT_split_is_still_exact(self):
        assert apply(seated(10), 2.0, 50.0) == 20
        assert apply(seated(700, entry=100.0), 1 / 7, 700.0) == 100

    def test_CHAINED_splits_do_not_accumulate_float_artefacts(self):
        """The `21.9999999997` failure mode: a value a later reader cannot
        distinguish from a genuine fraction. The multiply is done in Decimal and
        quantised, so a chain lands on a repeatable number."""
        n = 15.0
        for ratio in (1.5, 3.0, 0.5, 1.5, 2.0):
            n = split_shares(n, ratio)
        exact = Decimal("15")
        for ratio in ("1.5", "3", "0.5", "1.5", "2"):
            exact *= Decimal(ratio)
        assert n == pytest.approx(float(exact), abs=1e-9)
        assert n == float(f"{n:.12g}"), f"float artefact survived: {n!r}"

    def test_a_ZERO_or_ABSENT_ratio_changes_nothing(self):
        """A corporate action that says nothing must not zero a holding."""
        assert split_shares(15, 0) == 15.0
        assert split_shares(15, None) == 15.0
        assert split_shares(15, -2) == 15.0


# ── 2. the invariant is VALUE, not share count ───────────────────────────────

class TestEconomicValueIsPreserved:

    @pytest.mark.parametrize("shares,ratio", [
        (15, 1.5), (100, 1 / 7), (10, 2.0), (33, 1.5), (7, 0.2), (1, 3.0)])
    def test_position_value_survives_the_split(self, shares, ratio):
        px_before = 210.0
        px_after = px_before / ratio
        st = seated(shares, entry=px_before)
        after = apply(st, ratio, px_after)
        assert after * px_after == pytest.approx(shares * px_before, rel=1e-9), (
            "the split moved money; nobody traded, so nothing may be lost")

    def test_the_LEDGER_records_the_exact_delta(self):
        led = Ledger()
        st = seated(15, entry=90.0)
        apply(st, 1.5, 60.0, ledger=led)
        ev, = [e for e in led.events if e.event_type is EventType.SPLIT]
        assert ev.shares_delta == pytest.approx(7.5)
        assert ev.detail["before"] == 15 and ev.detail["after"] == 22.5


# ── 3. the grace interaction ─────────────────────────────────────────────────

class TestASplitDuringTheTerminalGrace:
    """Where a truncation would become a real settlement discrepancy: the carry
    is tallied on one share count and the settlement on another, so a share lost
    in between is a dollar difference the reconciliation must explain and
    cannot."""

    def _terms(self):
        return TerminalTerms(session="d1", security_id="S1",
                             kind=TerminalKind.CASH_MERGER,
                             reference="test/terms-pending")

    def test_settlement_uses_the_CORRECTED_share_count(self):
        st, led = seated(15, entry=90.0), Ledger()
        lk, c = {"S1": 90.0}, empty_counters()
        step_session(session="d1", state=st, bars=[], pending=[], ledger=led,
                     last_known=lk, cfg=CFG, strategy_id=SID,
                     strategy_version=VER,
                     security_bars=tradeability_only_bars([], None),
                     terminal_terms=[self._terms()], settlement_counters=c)

        # A 3-for-2 mid-grace: 15 -> 22.5, and a later trustworthy print.
        b = [bar("m0", close=60.0, split=1.5)]
        step_session(session="m0", state=st, bars=b, pending=[], ledger=led,
                     last_known=lk, cfg=CFG, strategy_id=SID,
                     strategy_version=VER,
                     security_bars=tradeability_only_bars(b, None),
                     settlement_counters=c)
        assert st.episodes[0].current_shares == pytest.approx(22.5)

        audits = []
        for i in range(C1_GRACE_SESSIONS + 1):
            res = step_session(session=f"q{i}", state=st, bars=[], pending=[],
                               ledger=led, last_known=lk, cfg=CFG,
                               strategy_id=SID, strategy_version=VER,
                               security_bars=tradeability_only_bars([], None),
                               settlement_counters=c)
            audits += [r["terminal_audit"] for r in res.terminal_results
                       if r.get("terminal_audit")]
        a, = audits
        assert a["shares_at_carry"] == 15
        assert a["shares_at_settlement"] == pytest.approx(22.5), (
            "the settlement used a truncated share count, so the carry->settle "
            "delta contains a destroyed half-share the audit cannot explain")
        assert a["grace_split_multiplier"] == pytest.approx(1.5)
        assert a["settlement_price"] == pytest.approx(60.0)
        assert a["notional_delta"] == pytest.approx(22.5 * 60.0 - 15 * 90.0)

    def test_the_audit_notional_is_NOT_truncated(self):
        """`_notional` used `int(shares)`, which would have reintroduced the
        destruction inside the audit built to prove none occurred."""
        from stock_strategy_shared.wealth_core.terminal_audit import episode_audit
        a = episode_audit(
            security_id="S1", ticker="T1", event_session="d1",
            event_kind="CASH_MERGER",
            carry={"shares_at_carry": 22.5, "carry_price": 60.0},
            settlement_session="q", settlement_method="LAST_TRUSTWORTHY_MARK",
            shares_at_settlement=22.5, settlement_price=61.0)
        assert a["carry_notional"] == pytest.approx(1350.0)
        assert a["settlement_notional"] == pytest.approx(1372.5)


# ── 4. representation must not masquerade as semantics ───────────────────────

class TestSerialisationIsCanonical:
    """Widening the share field so a split can keep its fraction must not
    re-serialise every whole-share book. Measured over all seven parity hashes
    plus the ledger: NONE moved."""

    def test_an_integral_quantity_serialises_as_int(self):
        assert as_json(20.0) == 20 and isinstance(as_json(20.0), int)
        assert as_json(20) == 20

    def test_a_fractional_quantity_stays_fractional(self):
        assert as_json(22.5) == pytest.approx(22.5)
        assert not isinstance(as_json(22.5), int)

    def test_a_whole_share_book_serialises_EXACTLY_as_before(self):
        st = seated(10)
        apply(st, 2.0, 50.0)
        d = st.to_dict()["episodes"]["0"]
        assert d["current_shares"] == 20 and isinstance(d["current_shares"], int)
        assert isinstance(d["initial_shares"], int)

    def test_a_fractional_book_serialises_the_fraction(self):
        st = seated(15, entry=90.0)
        apply(st, 1.5, 60.0)
        assert st.to_dict()["episodes"]["0"]["current_shares"] == pytest.approx(22.5)
