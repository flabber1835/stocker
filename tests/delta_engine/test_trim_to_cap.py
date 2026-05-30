"""
Trim-to-cap for evaluate_target_vs_live.

The buffer-zone exit is rank-based: a held name only exits after rank > exit_rank
for confirmation_days. That can never clean up a *well-ranked* orphan (held but
covariance-excluded from the target), so the realized book can sit permanently
above max_positions (the live-confirmed "33 positions vs cap 30" case).

Trim-to-cap fixes that: when the retained book exceeds max_positions, exit the
worst-ranked *orphans* (held but weight 0 / not in target) until the book is back
at the cap. It only fires when over capacity, and only ever trims orphans — names
the builder still targets are never force-sold here — so a within-cap book is
untouched (no churn).
"""
from datetime import date, timedelta

from app.engine import RankObservation, evaluate_target_vs_live


def _history(*ranks) -> list[RankObservation]:
    today = date(2026, 5, 28)
    return [
        RankObservation(run_date=today - timedelta(days=i), rank=r, composite_score=1.0)
        for i, r in enumerate(ranks)
    ]


def _counts(decisions):
    out = {}
    for d in decisions.values():
        out[d.action] = out.get(d.action, 0) + 1
    return out


def _retained(decisions, live):
    return sum(1 for t in live if decisions[t].action != "exit")


def test_trim_excess_orphans_back_to_cap():
    """26 in-target holds + 7 orphans = 33 held, cap 30 → exit the 3 worst-ranked
    orphans, leaving exactly 30 retained."""
    target = {f"T{i:02d}": 1.0 / 30 for i in range(1, 27)}      # 26 targeted
    orphans = {f"O{i:02d}" for i in range(1, 8)}                # 7 held, not targeted
    live = set(target) | orphans
    universe = {t: _history(i + 1) for i, t in enumerate(target)}   # ranks 1..26
    for i, o in enumerate(sorted(orphans)):
        universe[o] = _history(31 + i)                          # ranks 31..37, all <= exit_rank

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    c = _counts(decisions)
    assert c.get("exit", 0) == 3                                # 33 - 30
    assert _retained(decisions, live) == 30
    # the 3 worst-ranked orphans (O05/O06/O07 at ranks 35/36/37) are the ones exited
    exited = {t for t, d in decisions.items() if d.action == "exit"}
    assert exited == {"O05", "O06", "O07"}
    # best-ranked orphans survive as holds
    assert decisions["O01"].action == "hold"
    # no targeted name is ever trimmed
    assert all(decisions[t].action != "exit" for t in target)


def test_no_trim_when_within_cap():
    """28 held (≤ cap) → orphans stay hold, nothing trimmed (no churn)."""
    target = {f"T{i:02d}": 1.0 / 30 for i in range(1, 27)}      # 26
    orphans = {"O01", "O02"}                                    # +2 = 28 held
    live = set(target) | orphans
    universe = {t: _history(i + 1) for i, t in enumerate(target)}
    universe["O01"] = _history(33)
    universe["O02"] = _history(34)
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert _counts(decisions).get("exit", 0) == 0
    assert decisions["O01"].action == "hold"
    assert decisions["O02"].action == "hold"


def test_trim_only_touches_orphans_not_targeted_holds():
    """Even when a targeted hold ranks worse than an orphan, only orphans are
    trimmed — the builder's target is respected."""
    target = {f"T{i:02d}": 1.0 / 30 for i in range(1, 30)}      # 29 targeted
    live = set(target) | {"O01", "O02", "O03"}                  # 32 held → overflow 2
    universe = {f"T{i:02d}": _history(i) for i in range(1, 30)}  # T29 rank 29
    universe["T29"] = _history(39)                              # a weak (but ≤40) targeted hold
    universe["O01"] = _history(5)
    universe["O02"] = _history(6)
    universe["O03"] = _history(7)                               # orphans rank far BETTER than T29
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    exited = {t for t, d in decisions.items() if d.action == "exit"}
    assert exited == {"O02", "O03"}                             # 2 worst orphans
    assert decisions["T29"].action == "hold"                   # weak targeted name kept
    assert decisions["O01"].action == "hold"                   # best orphan kept


def test_trim_counts_existing_confirmed_exits():
    """A rank-confirmed exit already reduces the book; trim only the remaining
    overflow on top of it."""
    target = {f"T{i:02d}": 1.0 / 30 for i in range(1, 27)}      # 26
    orphans = {f"O{i:02d}" for i in range(1, 8)}                # 7 → 33 held
    live = set(target) | orphans
    universe = {t: _history(i + 1) for i, t in enumerate(target)}
    # O07 is a rank-confirmed exit (rank>40 for 3 days); O01..O06 are buffer-zone holds
    for i, o in enumerate(sorted(orphans)[:6]):
        universe[o] = _history(31 + i)                          # ranks 31..36
    universe["O07"] = _history(50, 50, 50)                      # confirmed exit by rank

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    # 1 rank-exit (O07) + 2 trimmed orphans = 3 total; book back to 30
    assert _counts(decisions).get("exit", 0) == 3
    assert _retained(decisions, live) == 30
    assert decisions["O07"].action == "exit"
    # the 2 worst remaining orphans (O06 rank36, O05 rank35) get trimmed
    assert decisions["O06"].action == "exit"
    assert decisions["O05"].action == "exit"
    assert decisions["O01"].action == "hold"
