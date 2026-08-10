"""A security that TERMINATES on a session cannot be ADMITTED on that session.

THE DEFECT, reproduced 2026-08-09 from a code review and confirmed here before
anything was changed:

    a WRITE_OFF effective on session d1 returned `NOT_HELD` — correctly, the
    book did not own it — and `decide()` then queued an OPEN_SLOT_POSITION for
    the SAME security at the next open

The book bought a security on its delisting date. This is the same class of
error the Sentinel terminal-order correction found in the reference replay,
where the shadow had spent admission slots on securities already terminated at
the close, and every breadth value read off that book was wrong as a result.

WHY IT SURVIVED. `step_session` already computed `terminated` and already used
it to cancel a pending FILL for a terminating security. It never reached the
DECISION path. So the engine was protected against buying a terminated security
with an order decided YESTERDAY, and unprotected against deciding to buy one
TODAY — two halves of one rule, with only one of them implemented.

`NOT_HELD` means "we did not own it when it terminated". It has never meant "it
is safe to buy".

THE INVARIANT these tests hold, for EVERY terminal kind:

    security_id in terminal_events_for_this_session
        =>  OPEN_SLOT_POSITION for it is impossible
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder, step_session, tradeability_only_bars)
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1

#: A long rising window makes the candidate top-ranked, so if it is admissible
#: at all it WILL be admitted. Anything less and a passing test proves only that
#: the security was unattractive.
WINDOW = [100.0 + i for i in range(127)]


def bar(sec="S1", session="d1", *, close=None, tradeable=True, split=1.0):
    close = WINDOW[-1] if close is None else close
    return DailyBar(security_id=sec, ticker=f"T{sec[1:]}", issuer_id=f"I{sec[1:]}",
                    session=session, signal_close_split_adj_div_unadj=close,
                    raw_open=close * 0.99, raw_mark_close=close,
                    tradeable=tradeable, split_ratio=split,
                    dividend_per_share=0.0, unresolved_corporate_action=False)


def terms(kind, sec="S1", session="d1"):
    """Terms COMPLETE enough to apply, so the test exercises a real terminal
    action rather than the incomplete-terms block."""
    base = dict(session=session, security_id=sec, kind=kind,
                reference=f"test/{kind.value.lower()}")
    if kind is TerminalKind.CASH_MERGER:
        base["cash_per_share"] = 54.0
    if kind in (TerminalKind.CONVERSION, TerminalKind.CASH_PLUS_STOCK):
        base.update(delivered_security_id="S9", delivered_ticker="T9",
                    delivered_issuer_id="I9", exchange_ratio=1.5,
                    cash_in_lieu_price_per_delivered_share=140.0)
    if kind is TerminalKind.CASH_PLUS_STOCK:
        base["cash_per_share"] = 5.0
    return TerminalTerms(**base)


def run_session(*, terminal, pending=None, state=None, bars=None):
    st = state or PortfolioState.fresh(1_000_000.0)
    st.initialized = True
    bars = bars if bars is not None else [bar()]
    pend = pending if pending is not None else []
    res = step_session(session="d1", state=st, bars=bars, pending=pend,
                       ledger=Ledger(), last_known={}, cfg=CFG,
                       strategy_id=SID, strategy_version=VER,
                       security_bars=tradeability_only_bars(
                           bars, {b.security_id: WINDOW for b in bars}),
                       terminal_terms=list(terminal))
    ops = [(o.operation, o.security_id)
           for o in (res.decision.operations if res.decision else [])]
    return st, res, ops, pend


# ── 1. the invariant, for every kind ─────────────────────────────────────────

@pytest.mark.parametrize("kind", list(TerminalKind))
class TestATerminatingSecurityIsNeverAdmitted:
    """Parametrised over EVERY kind on purpose. The disqualifying fact is that
    the security has a terminal event today — not how that event resolved — so a
    rule that held only for write-offs would be a coincidence."""

    def test_no_entry_is_decided(self, kind):
        _, _, ops, _ = run_session(terminal=[terms(kind)])
        assert not [o for o in ops
                    if o[0] is Operation.OPEN_SLOT_POSITION and o[1] == "S1"], (
            f"{kind.value}: the engine decided to buy a security that "
            f"terminated this session")

    def test_no_pending_entry_survives_for_the_next_open(self, kind):
        _, _, _, pend = run_session(terminal=[terms(kind)])
        assert not [p for p in pend if p.security_id == "S1"], (
            f"{kind.value}: an order to buy a terminated security reached the "
            f"queue, so it fills at tomorrow's open")


# ── 2. the control: the veto is the TERMINAL EVENT, nothing else ─────────────

class TestTheControl:

    def test_the_SAME_security_IS_admitted_with_no_terminal_event(self):
        """Without this, every test above passes on a security that was never
        admissible and the suite proves nothing."""
        _, _, ops, pend = run_session(terminal=[])
        assert [o for o in ops
                if o[0] is Operation.OPEN_SLOT_POSITION and o[1] == "S1"], (
            "the candidate was not admissible even WITHOUT a terminal event, "
            "so the tests above are vacuous")
        assert [p for p in pend if p.security_id == "S1"]

    def test_an_UNRELATED_security_is_still_admitted(self):
        """The veto must be surgical. Marking the terminating name ineligible
        must not suppress the rest of the cross-section."""
        bars = [bar("S1"), bar("S2")]
        _, _, ops, pend = run_session(terminal=[terms(TerminalKind.WRITE_OFF)],
                                      bars=bars)
        entered = {o[1] for o in ops if o[0] is Operation.OPEN_SLOT_POSITION}
        assert "S2" in entered and "S1" not in entered


# ── 3. the half that already worked, kept honest ────────────────────────────

class TestAPendingEntryIsCancelled:
    """`step_session` already cancelled a pending FILL for a terminating
    security. That half was correct; this pins it so the fix above cannot be
    "simplified" into replacing it."""

    def test_yesterdays_entry_does_not_fill_into_a_termination(self):
        st = PortfolioState.fresh(1_000_000.0)
        st.initialized = True
        pend = [PendingOrder(operation=Operation.OPEN_SLOT_POSITION,
                             security_id="S1", ticker="T1", slot_id=0,
                             shares=10, signal_session="d0", reason="ENTRY")]
        _, res, _, after = run_session(terminal=[terms(TerminalKind.WRITE_OFF)],
                                       pending=pend, state=st)
        assert not [f for f in res.fills if f["security_id"] == "S1"], (
            "a pending entry filled into a security that terminated at the open")
        assert not [p for p in after if p.security_id == "S1"]
        assert 0 not in st.episodes


# ── 4. a held position still terminates normally ─────────────────────────────

class TestTheVetoDoesNotBreAK_TerminalHandling:
    """Ineligibility governs ADMISSION. It must not interfere with resolving a
    terminal action on a security the book already owns — that would trade one
    defect for a worse one."""

    def test_a_held_security_still_terminates(self):
        st = PortfolioState.fresh(1_000.0)
        st.slots[0].occupied_by = "S1"
        st.episodes[0] = HoldingEpisode("S1", "T1", "I1", 0, "d0", "d0",
                                        100.0, 100.0, 10, 10, 100.0)
        st.initialized = True
        _, res, _, _ = run_session(terminal=[terms(TerminalKind.CASH_MERGER)],
                                   state=st)
        applied = [r for r in res.terminal_results if r.get("applied")]
        assert applied, "the held position's terminal action did not apply"
        assert 0 not in st.episodes, "the position was not released"
        assert st.cash == pytest.approx(1_000.0 + 10 * 54.0)


# ── 5. the cross-section is vetoed, not rewritten ────────────────────────────

class TestTheDecileIsNotSilentlyMoved:
    """The terminating security is marked INELIGIBLE rather than dropped from
    the list. `score_universe` computes the decile over eligible names, so
    removing a row would move the cutoff and change which OTHER securities are
    admitted — a veto must not rewrite the cross-section it vetoes."""

    def test_the_row_is_still_present_but_ineligible(self):
        from stock_strategy_shared.wealth_core import adapter as ad

        seen = {}
        real = ad.decide

        def spy(**kw):
            seen["bars"] = list(kw["bars"])
            return real(**kw)

        ad.decide = spy
        try:
            run_session(terminal=[terms(TerminalKind.WRITE_OFF)],
                        bars=[bar("S1"), bar("S2")])
        finally:
            ad.decide = real

        by_sec = {b.security_id: b for b in seen["bars"]}
        assert set(by_sec) == {"S1", "S2"}, (
            "the terminating security was REMOVED from the cross-section; that "
            "moves the decile cutoff and changes other admissions")
        assert by_sec["S1"].eligible is False
        assert by_sec["S1"].eligibility_reason == "TERMINAL_ACTION_THIS_SESSION"
        assert by_sec["S2"].eligible is True
