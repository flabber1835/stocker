"""Rename THEN reuse, as one continuous decision path.

WHY THIS EXISTS BESIDE `test_identity.py`. That file pins each identity rule in
isolation, which is what makes a failure legible. It does not run them in
SEQUENCE, and the sequence is where the interesting failure lives: a security
vacates a symbol, and some time later a DIFFERENT company picks that symbol up
while the first is still inside its cooldown window.

The certified artefact cannot cover this — across 260 sessions the golden
scenario produces zero relabellings and has 125 distinct tickers for 125
securities. This fixture is independent of it and pins none of its hashes.

THE TWO FAILURE DIRECTIONS, which are opposite and both silent:

    false UNBLOCK   cooldown keyed on the SYMBOL: SEC_A exits as OLD, renames,
                    and is then looked up under NEW — a key that was never
                    written — so it is immediately re-buyable inside its own
                    protection window. (The defect fixed in item 7.)
    false BLOCK     the same key from the other side: SEC_B picks up the vacated
                    OLD and inherits a STRANGER'S cooldown. A company the
                    strategy has never held is refused for 21 sessions, and the
                    audit trail says only "cooldown".

ORDERING IS LOAD-BEARING HERE, and the first version of this file got it wrong.
It renamed SEC_A while its exit was still in flight, so the exit FILLED under
NEW and a symbol-keyed cooldown landed on NEW — a key SEC_B never touches. The
false-BLOCK test then passed under a deliberately sabotaged engine, because the
path never reached the case it was written for. The exit must fill while the
security is still OLD, which is also the realistic order: a company renames, and
the symbol it abandoned is reassigned later.

That constraint is incompatible with relabelling a queued order mid-flight (that
needs the rename BEFORE the fill), so the two live in separate scenarios below
rather than being forced into one.

    d1  SEC_A is held, trading as OLD. An exit is decided.
    d2  SEC_A is untradeable, still OLD; the order waits.
    d3  the exit FILLS under OLD, and SEC_A's cooldown begins.
    d4  SEC_A now trades as NEW, and is offered back as a candidate.
    d5  SEC_B appears trading as OLD — the symbol SEC_A vacated.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    step_session,
    tradeability_only_bars,
)
from stock_strategy_shared.wealth_core.engine import (
    Operation,
    Reason,
    WealthCoreConfig,
)
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState

SID, VER = "stocker_wealth_core_v1", 1
CFG = WealthCoreConfig()

SEC_A, SEC_B = "P:A", "P:B"
OLD, NEW = "OLDCO", "NEWCO"

# Rising, so a candidate has positive momentum and passes the freshness gate.
WINDOW = [100.0 + i for i in range(127)]


def bar(sec, ticker, session, *, px=200.0, tradeable=True):
    return DailyBar(security_id=sec, ticker=ticker, issuer_id=f"I{sec[-1]}",
                    session=session, signal_close_split_adj_div_unadj=px,
                    raw_open=px * 0.99, raw_mark_close=px, tradeable=tradeable)


class Book:
    def __init__(self) -> None:
        self.state = PortfolioState.fresh(1_000_000.0, n_slots=2)
        self.state.slots[0].occupied_by = SEC_A
        self.state.episodes[0] = HoldingEpisode(
            security_id=SEC_A, ticker=OLD, issuer_id="IA", slot_id=0,
            signal_date="d0", entry_date="d0", entry_raw_open=200.0,
            entry_split_adjusted_price=200.0, initial_shares=100,
            current_shares=100, episode_peak_split_adjusted_close=200.0,
            market_sessions_held=30, review_completed=True)
        self.state.initialized = True
        self.ledger = Ledger()
        self.pending: list[PendingOrder] = []
        self.results: dict = {}

    def step(self, session, bars, windows=None):
        r = step_session(session=session, state=self.state, bars=bars,
                         pending=self.pending, ledger=self.ledger,
                         last_known={}, cfg=CFG, strategy_id=SID,
                         strategy_version=VER,
                         security_bars=tradeability_only_bars(bars, windows or {}))
        self.results[session] = r
        return r


@pytest.fixture()
def walked():
    """The whole path, walked once. Each test asserts one property of it, so a
    failure names the property rather than the walk."""
    b = Book()

    # d1 — held as OLD. The exit is queued by hand so the path does not depend
    # on a stop threshold a later tuning change could move.
    b.step("d1", [bar(SEC_A, OLD, "d1")], {SEC_A: WINDOW})
    b.pending.append(PendingOrder(Operation.CLOSE_POSITION, SEC_A, OLD, 0, 100,
                                  "d1", Reason.EXIT_TRAILING_STOP.value))

    # d2 — untradeable, STILL OLD: the order waits without being relabelled.
    b.step("d2", [bar(SEC_A, OLD, "d2", tradeable=False)], {SEC_A: WINDOW})

    # d3 — the exit fills while the security is still OLD. This is the step
    # that decides which key a symbol-keyed cooldown would be written under.
    b.step("d3", [bar(SEC_A, OLD, "d3")], {SEC_A: WINDOW})

    # d4 — SEC_A now trades as NEW and is offered back as a candidate.
    b.step("d4", [bar(SEC_A, NEW, "d4")], {SEC_A: WINDOW})

    # d5 — SEC_B picks up the symbol SEC_A vacated.
    b.step("d5", [bar(SEC_A, NEW, "d5"), bar(SEC_B, OLD, "d5", px=50.0)],
           {SEC_A: WINDOW, SEC_B: WINDOW})
    return b


# ── the exit fills, under the symbol that was trading ───────────────────────

class TestTheExitFillsUnderOLD:

    def test_it_waited_the_untradeable_session_rather_than_being_dropped(self, walked):
        fills = walked.results["d3"].fills
        assert len(fills) == 1
        assert fills[0]["security_id"] == SEC_A and fills[0]["waited"] == 1

    def test_the_SELL_is_booked_under_OLD(self, walked):
        sells = [e for e in walked.ledger.events
                 if e.event_type is EventType.SELL]
        assert len(sells) == 1
        assert sells[0].ticker == OLD and sells[0].security_id == SEC_A


# ── both cooldown directions, from ONE recorded cooldown ────────────────────

class TestTheCooldownBelongsToTheSecurity:
    """The cooldown is written once, at d3, while SEC_A is OLD. A symbol-keyed
    implementation therefore records it under `OLDCO` — and that single wrong
    key produces BOTH wrong answers, which is why one path can catch both."""

    def test_it_is_keyed_on_the_permanent_id(self, walked):
        assert walked.state.security_cooldowns.keys() == {SEC_A}
        for label in (OLD, NEW):
            assert label not in walked.state.security_cooldowns

    def test_SEC_A_is_STILL_REFUSED_after_renaming_to_NEW(self, walked):
        """FALSE-UNBLOCK direction. Keyed on the symbol, the cooldown sits under
        OLDCO and a lookup under NEWCO finds nothing — so a security the
        strategy just exited is re-buyable the same week."""
        rejects = {(r["security_id"], r["reason"])
                   for r in walked.results["d4"].decision.admission_rejections}
        assert (SEC_A, Reason.REJECT_SECURITY_COOLDOWN.value) in rejects
        opened = [o for o in walked.results["d4"].decision.operations
                  if o.operation is Operation.OPEN_SLOT_POSITION]
        assert not opened, "SEC_A was re-admitted inside its own cooldown"

    def test_SEC_B_IS_NOT_BLOCKED_by_SEC_A_s_cooldown(self, walked):
        """FALSE-BLOCK direction, and the one nothing else in the suite pins.

        SEC_B is a different company that happens to have picked up a symbol
        SEC_A stopped using. Keyed on the ticker it inherits a STRANGER'S
        protection window — refused for 21 sessions, with an audit trail saying
        only "cooldown", for a security the strategy has never held.
        """
        d = walked.results["d5"].decision
        blocked = {r["security_id"] for r in d.admission_rejections
                   if r["reason"] == Reason.REJECT_SECURITY_COOLDOWN.value}
        assert SEC_A in blocked, "the real cooldown must still bite"
        assert SEC_B not in blocked, (
            "SEC_B inherited a cooldown belonging to a different company, via a "
            "symbol SEC_A no longer uses")

    def test_SEC_B_is_actually_admitted(self, walked):
        """The falsifier for the assertion above: 'not blocked by cooldown'
        would also hold if SEC_B were blocked for another reason, or never
        considered at all."""
        opened = [o for o in walked.results["d5"].decision.operations
                  if o.operation is Operation.OPEN_SLOT_POSITION]
        assert [o.security_id for o in opened] == [SEC_B]
        assert opened[0].ticker == OLD


# ── nothing else crosses between the two securities ─────────────────────────

class TestNothingCrosses:

    def test_the_two_securities_keep_separate_price_histories(self):
        """Series are keyed on the permanent id, so a reused symbol cannot
        splice SEC_B's prices onto SEC_A's — which would compute momentum
        across the discontinuity between two different businesses."""
        meta = {
            SEC_A: SecurityMeta(security_id=SEC_A, ticker=NEW,
                                category="Domestic Common Stock",
                                permaticker="A", first_session="d1"),
            SEC_B: SecurityMeta(security_id=SEC_B, ticker=OLD,
                                category="Domestic Common Stock",
                                permaticker="B", first_session="d5"),
        }
        feed = Feed(meta)
        feed.advance("d1", [VendorBar("d1", SEC_A, OLD, 200.0, 198.0, 1e6)])
        feed.advance("d4", [VendorBar("d4", SEC_A, NEW, 210.0, 208.0, 1e6)])
        feed.advance("d5", [VendorBar("d5", SEC_A, NEW, 220.0, 218.0, 1e6),
                            VendorBar("d5", SEC_B, OLD, 50.0, 49.0, 1e6)])

        assert feed.series[SEC_A].raw_closes == [200.0, 210.0, 220.0]
        assert feed.series[SEC_B].raw_closes == [50.0]
        assert feed.series[SEC_A].ticker == NEW, "the label tracks the bar"
        assert set(feed.series) == {SEC_A, SEC_B}, (
            "a series keyed on a SYMBOL would appear here holding both "
            "companies' prices")

    def test_no_pending_state_crosses(self, walked):
        """The queue is NOT empty and must not be: SEC_B was admitted at d5, so
        its entry is legitimately waiting for the next open. The property is
        that everything left belongs to SEC_B — asserted on the permanent id,
        since both securities have answered to OLDCO and a check on the SYMBOL
        could not tell them apart."""
        assert {p.security_id for p in walked.pending} == {SEC_B}
        assert all(p.operation is Operation.OPEN_SLOT_POSITION
                   for p in walked.pending), "SEC_A's exit left the queue"
        for s in walked.state.slots.values():
            if s.reserved_for:
                assert s.reserved_for == SEC_B
        assert SEC_A not in {e.security_id
                             for e in walked.state.episodes.values()}


# ── the mid-flight relabel, which needs the opposite ordering ───────────────

def test_a_rename_DURING_an_order_s_flight_retargets_it():
    """Step 5 of the chain, in its own scenario because it needs the rename
    BEFORE the fill — the opposite of what the cooldown case requires.

    Left un-retargeted, the exit is submitted under a symbol that no longer
    trades: it either rejects at the broker or fills against whatever now owns
    that ticker.
    """
    b = Book()
    b.step("e1", [bar(SEC_A, OLD, "e1")], {SEC_A: WINDOW})
    b.pending.append(PendingOrder(Operation.CLOSE_POSITION, SEC_A, OLD, 0, 100,
                                  "e1", Reason.EXIT_TRAILING_STOP.value))

    # Renames while untradeable, so the order is still queued when it happens.
    r = b.step("e2", [bar(SEC_A, NEW, "e2", tradeable=False)], {SEC_A: WINDOW})
    assert {c["where"] for c in r.relabelled} == {"episode", "pending_order"}
    assert b.pending[0].ticker == NEW
    assert b.pending[0].security_id == SEC_A, "identity never moves"

    b.step("e3", [bar(SEC_A, NEW, "e3")], {SEC_A: WINDOW})
    sells = [e for e in b.ledger.events if e.event_type is EventType.SELL]
    assert len(sells) == 1 and sells[0].ticker == NEW


# ── the fixture's own relevance ─────────────────────────────────────────────

def test_the_path_really_did_fill_under_OLD_before_the_rename(walked):
    """The ordering guard. If the fill ever moves after the rename, a
    symbol-keyed cooldown lands on NEWCO — a key SEC_B never touches — and the
    false-BLOCK test above passes while testing nothing. That is precisely how
    the first version of this file failed, and it failed silently."""
    sells = [e for e in walked.ledger.events if e.event_type is EventType.SELL]
    assert sells and sells[0].ticker == OLD, (
        "the exit must fill while the security is still OLD, or the reuse case "
        "is unreachable")
    assert walked.results["d2"].relabelled == [], "no rename before the fill"
    assert any(b_.ticker == NEW for b_ in [bar(SEC_A, NEW, "d4")])


def test_this_fixture_is_INDEPENDENT_of_the_certified_artefact():
    """Checked over IMPORTS rather than text: the prose explaining that the
    artefact is untouched would otherwise fail the check enforcing it."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(__file__).read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [a.name for a in node.names]
    assert not [m for m in imported if "golden" in m or "repin" in m]
