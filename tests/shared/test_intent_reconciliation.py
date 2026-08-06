"""Intent reconciliation — one net instruction per ticker (defect 4).

The defect: crash-brake moves are APPENDED to the decision list without removing
the base decision, and `delta_intents` has no unique key, so a ticker can carry
`exit` AND `risk_reduce` in one run. Whichever row a reader picked up was the
trade that executed.

The first test here is that defect, stated as a scenario. Everything else exists
to show the composition rule is a RULE and not a coincidence of ordering: each
falsifier is written so that a plausible wrong implementation (take the last
proposal, take the highest-priority action name, treat a missing weight as zero,
let `hold` veto a control) fails it.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.intent_reconciliation import (
    BUY_SIDE, NEUTRAL, SELL_SIDE, NetIntent, Proposal, RULE_BUY_MIN_WEIGHT,
    RULE_EXIT_DOMINATES, RULE_NEUTRAL_PRECEDENCE, RULE_SELL_MIN_WEIGHT,
    RULE_SOLE, compare_to_rows, provenance_json, reconcile)


def _p(ticker, action, source="delta_engine", seq=0, weight=None, **kw):
    return Proposal(ticker=ticker, action=action, source=source, seq=seq,
                    target_weight=weight, **kw)


# ── the defect itself ────────────────────────────────────────────────────────

def test_exit_and_risk_reduce_on_one_ticker_resolves_to_exit():
    """THE defect scenario. The delta engine drops a name while the crash brake
    trims the book; both propose for the same ticker in the same run.

    `exit` must win: a full liquidation subsumes a partial reduction, and the
    opposite resolution would leave a position the strategy has decided to close.
    """
    nets = reconcile([
        _p("AMD", "exit", "delta_engine", seq=3),
        _p("AMD", "risk_reduce", "crash_brake", seq=41, weight=0.02),
    ])
    assert len(nets) == 1
    assert nets[0].action == "exit"
    assert nets[0].resolved_by == RULE_EXIT_DOMINATES
    assert nets[0].conflicted


def test_the_discarded_proposal_survives_in_provenance():
    """Reconciliation must not be a silent deletion. The losing proposal is what
    tells a reviewer that two controls disagreed at all."""
    nets = reconcile([
        _p("AMD", "exit", "delta_engine", seq=3),
        _p("AMD", "risk_reduce", "crash_brake", seq=41, weight=0.02),
    ])
    prov = provenance_json(nets[0])
    assert prov["resolved_by"] == RULE_EXIT_DOMINATES
    assert [c["source"] for c in prov["contributing"]] == ["delta_engine", "crash_brake"]
    assert [c["won"] for c in prov["contributing"]] == [True, False]
    assert len(nets[0].discarded) == 1
    assert nets[0].discarded[0].source == "crash_brake"


def test_crash_brake_proposing_last_does_not_win_by_being_last():
    """Falsifier for the most likely wrong implementation: last-write-wins.

    The brake always proposes AFTER the delta engine, so an implementation that
    simply takes the highest `seq` would pass every conflict test that happens to
    want the brake's answer — and silently override every exit.
    """
    nets = reconcile([
        _p("NVDA", "exit", "delta_engine", seq=0),
        _p("NVDA", "risk_reduce", "crash_brake", seq=99, weight=0.03),
    ])
    assert nets[0].action == "exit"
    assert nets[0].winner.source == "delta_engine"


# ── sell-side dominance ──────────────────────────────────────────────────────

def test_sell_beats_buy_regardless_of_order():
    for seqs in ((0, 1), (1, 0)):
        nets = reconcile([
            _p("X", "buy_add", "delta_engine", seq=seqs[0], weight=0.05),
            _p("X", "risk_reduce", "crash_brake", seq=seqs[1], weight=0.02),
        ])
        assert nets[0].action == "risk_reduce", f"order {seqs} changed the result"


def test_among_partial_sells_the_lowest_target_weight_wins():
    """Conservative composition: the smaller residual position is the one both
    controls can be said to permit."""
    nets = reconcile([
        _p("X", "sell_trim", "delta_engine", seq=0, weight=0.06),
        _p("X", "risk_reduce", "crash_brake", seq=1, weight=0.02),
    ])
    assert nets[0].action == "risk_reduce"
    assert nets[0].resolved_by == RULE_SELL_MIN_WEIGHT

    # …and the reverse assignment must flip the winner, or the test above only
    # proved that the brake wins.
    nets = reconcile([
        _p("X", "sell_trim", "delta_engine", seq=0, weight=0.01),
        _p("X", "risk_reduce", "crash_brake", seq=1, weight=0.04),
    ])
    assert nets[0].winner.source == "delta_engine"


def test_exit_beats_a_partial_sell_with_a_lower_weight():
    """An exit has no residual weight, so it must not be compared on one. A
    naive min-weight rule over all sells would let a 1% trim outrank a close."""
    nets = reconcile([
        _p("X", "sell_trim", "delta_engine", seq=0, weight=0.01),
        _p("X", "exit", "crash_brake", seq=1, weight=None),
    ])
    assert nets[0].action == "exit"


# ── buy-side composition ─────────────────────────────────────────────────────

def test_among_buys_the_smallest_wins():
    nets = reconcile([
        _p("X", "buy_add", "delta_engine", seq=0, weight=0.08),
        _p("X", "risk_restore", "crash_brake", seq=1, weight=0.05),
    ])
    assert nets[0].action == "risk_restore"
    assert nets[0].resolved_by == RULE_BUY_MIN_WEIGHT


def test_a_missing_weight_never_wins_a_buy():
    """Falsifier for `float(w or 0)`. Treating None as 0.0 would make a proposal
    that cannot say how much it wants outrank a real instruction — the most
    conservative-looking bug there is, and wrong: it silently cancels the buy."""
    nets = reconcile([
        _p("X", "buy_add", "delta_engine", seq=0, weight=None),
        _p("X", "risk_restore", "crash_brake", seq=1, weight=0.05),
    ])
    assert nets[0].winner.target_weight == pytest.approx(0.05)


def test_all_weights_missing_still_resolves_deterministically():
    nets = reconcile([
        _p("X", "buy_add", "delta_engine", seq=7, weight=None),
        _p("X", "entry", "other", seq=2, weight=None),
    ])
    assert nets[0].winner.seq == 2  # lowest seq, not dict order


# ── neutral proposals ────────────────────────────────────────────────────────

def test_hold_does_not_veto_the_brake():
    """`hold` is the delta engine saying it has nothing to do, not a veto over a
    control that does. Reading it as one would let engine silence disarm the
    brake — a risk control defeated by the absence of an opinion."""
    nets = reconcile([
        _p("X", "hold", "delta_engine", seq=0, weight=0.04),
        _p("X", "risk_reduce", "crash_brake", seq=1, weight=0.02),
    ])
    assert nets[0].action == "risk_reduce"


def test_at_risk_survives_against_hold():
    """at_risk carries a countdown; hold does not. Collapsing to hold would erase
    the reason the position is still held."""
    nets = reconcile([
        _p("X", "hold", "delta_engine", seq=0),
        _p("X", "at_risk", "other", seq=1),
    ])
    assert nets[0].action == "at_risk"
    assert nets[0].resolved_by == RULE_NEUTRAL_PRECEDENCE


def test_at_risk_does_not_suppress_a_risk_reduce():
    """at_risk is not executable — it must not outrank an instruction that is."""
    nets = reconcile([
        _p("X", "at_risk", "delta_engine", seq=0),
        _p("X", "risk_reduce", "crash_brake", seq=1, weight=0.02),
    ])
    assert nets[0].action == "risk_reduce"


# ── invariants ───────────────────────────────────────────────────────────────

def test_one_net_intent_per_account_ticker():
    nets = reconcile([
        _p("A", "exit", seq=0), _p("A", "risk_reduce", "crash_brake", seq=1, weight=0.01),
        _p("B", "hold", seq=2), _p("B", "risk_reduce", "crash_brake", seq=3, weight=0.02),
        _p("C", "entry", seq=4, weight=0.04),
    ])
    keys = [(n.account_id, n.ticker) for n in nets]
    assert len(keys) == len(set(keys)) == 3


def test_two_accounts_are_not_collapsed_into_one():
    """The unique key is (run, account, ticker). Dropping account_id would merge
    two books' instructions for the same name into one."""
    nets = reconcile([
        Proposal("X", "exit", "delta_engine", 0, account_id="paper"),
        Proposal("X", "entry", "delta_engine", 1, target_weight=0.04, account_id="live"),
    ])
    assert {(n.account_id, n.action) for n in nets} == {("paper", "exit"), ("live", "entry")}


def test_output_order_is_deterministic():
    a = reconcile([_p("C", "hold", seq=0), _p("A", "hold", seq=1), _p("B", "hold", seq=2)])
    b = reconcile([_p("B", "hold", seq=2), _p("C", "hold", seq=0), _p("A", "hold", seq=1)])
    assert [n.ticker for n in a] == [n.ticker for n in b] == ["A", "B", "C"]


def test_sole_proposal_is_not_marked_conflicted():
    nets = reconcile([_p("X", "entry", seq=0, weight=0.04)])
    assert nets[0].resolved_by == RULE_SOLE
    assert not nets[0].conflicted
    assert nets[0].discarded == ()


def test_unknown_action_raises_rather_than_guessing():
    """A new control's action reaching this function means nobody decided where
    it sits in the composition order. Guessing is how a risk-reducing
    instruction gets silently outranked by a buy."""
    with pytest.raises(ValueError, match="unknown action"):
        reconcile([_p("X", "liquidate_everything", seq=0)])


def test_action_partition_is_total_and_disjoint():
    """Every action in the delta_intents vocabulary must be classified. An
    unclassified one would reach the ValueError above at runtime instead of
    failing here."""
    vocabulary = {"entry", "exit", "hold", "watch", "at_risk", "buy_add",
                  "sell_trim", "risk_reduce", "risk_restore"}
    assert SELL_SIDE | BUY_SIDE | NEUTRAL == vocabulary
    assert not (SELL_SIDE & BUY_SIDE) and not (SELL_SIDE & NEUTRAL) and not (BUY_SIDE & NEUTRAL)


# ── the shadow comparison ────────────────────────────────────────────────────

def test_compare_reports_the_conflict_it_resolved():
    proposals = [
        _p("AMD", "exit", "delta_engine", seq=0),
        _p("AMD", "risk_reduce", "crash_brake", seq=1, weight=0.02),
        _p("NVDA", "hold", "delta_engine", seq=2, weight=0.04),
    ]
    nets = reconcile(proposals)
    report = compare_to_rows([(p.ticker, p.action) for p in proposals], nets)

    assert report["legacy_rows"] == 3
    assert report["legacy_tickers"] == 2
    assert report["net_intents"] == 2
    assert not report["agrees"]
    assert report["conflicts"][0]["ticker"] == "AMD"
    assert report["conflicts"][0]["legacy_actions"] == ["exit", "risk_reduce"]
    assert report["conflicts"][0]["net_action"] == "exit"


def test_compare_agrees_when_no_control_overlaps():
    """The ordinary day: the brake is disengaged, one proposal per ticker, and
    the reconciliation changes nothing. If this ever fails the shadow is
    reporting differences that do not exist and nobody will read it."""
    proposals = [_p("A", "entry", seq=0, weight=0.04), _p("B", "hold", seq=1, weight=0.04)]
    nets = reconcile(proposals)
    report = compare_to_rows([(p.ticker, p.action) for p in proposals], nets)
    assert report["agrees"]
    assert report["conflicts"] == [] and report["changed"] == [] and report["missing_from_net"] == []
