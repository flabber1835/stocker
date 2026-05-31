"""
Orphan handling at/over capacity for evaluate_target_vs_live.

Orphan-exit redesign: the target is binding on the live book, and instant
trim-to-cap rotation is RETIRED. An orphan (held, not in the target) is never
force-sold to bring an over-cap book down; instead it is tagged ``at_risk`` and
exits only after it has been absent from the target for confirmation_days
consecutive builds (tracked via ``target_history``). An over-cap book therefore
corrects over time as orphans time out — deterministically, with no rank-driven
churn — rather than in a single snap rotation.

This file asserts:
  - an over-cap book of orphans is NOT instantly trimmed (all at_risk, no exits)
  - a within-cap book of orphans is likewise at_risk, not force-held and not sold
  - targeted holds are never force-sold regardless of cap
  - confirmed orphans (absent from target for confirmation_days builds) DO exit,
    which is what eventually brings an over-cap book back to the cap
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


def test_over_cap_orphans_not_instantly_trimmed():
    """26 in-target holds + 7 orphans = 33 held, cap 30. Instant rotation is retired:
    with no build history the 7 orphans are at_risk (counting down), NOT trimmed —
    the book stays at 33 this run and corrects as orphans time out."""
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
    assert _counts(decisions).get("exit", 0) == 0               # no instant trim
    assert all(decisions[o].action == "at_risk" for o in orphans)
    # targeted names are never trimmed
    assert all(decisions[t].action != "exit" for t in target)


def test_within_cap_orphans_are_at_risk_not_force_held():
    """28 held (≤ cap). Orphans are still orphans → at_risk (counting down toward
    exit), not 'hold' and not sold. The target is binding even under cap."""
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
    assert decisions["O01"].action == "at_risk"
    assert decisions["O02"].action == "at_risk"


def test_targeted_holds_never_force_sold_even_when_over_cap():
    """A weak-but-targeted hold ranking worse than the orphans is still kept —
    only the orphan-exit timer can remove a held name, and only orphans (not
    targeted names) are ever orphans."""
    target = {f"T{i:02d}": 1.0 / 30 for i in range(1, 30)}      # 29 targeted
    live = set(target) | {"O01", "O02", "O03"}                  # 32 held → over cap
    universe = {f"T{i:02d}": _history(i) for i in range(1, 30)}
    universe["T29"] = _history(39)                              # weak (but ≤40) targeted hold
    universe["O01"] = _history(5)
    universe["O02"] = _history(6)
    universe["O03"] = _history(7)                               # orphans rank far BETTER than T29
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    # No instant trim — orphans (even well-ranked) are at_risk, targeted hold stays.
    assert _counts(decisions).get("exit", 0) == 0
    assert decisions["T29"].action == "hold"                   # weak targeted name kept
    assert decisions["O01"].action == "at_risk"
    assert decisions["O02"].action == "at_risk"
    assert decisions["O03"].action == "at_risk"


def test_confirmed_orphans_exit_and_reduce_the_book():
    """When orphans have been absent from the target for confirmation_days builds,
    they exit — this is what brings an over-cap book back toward the cap. Here 3 of
    the 7 orphans are confirmed (in target_history); the other 4 keep counting down."""
    target = {f"T{i:02d}": 1.0 / 30 for i in range(1, 27)}      # 26 targeted
    orphans = {f"O{i:02d}" for i in range(1, 8)}                # 7 → 33 held
    live = set(target) | orphans
    universe = {t: _history(i + 1) for i, t in enumerate(target)}
    for i, o in enumerate(sorted(orphans)):
        universe[o] = _history(31 + i)                          # ranks 31..37

    confirmed = {"O05", "O06", "O07"}
    # In all 3 most-recent builds the target was the 26 T-names plus the 4 NON-confirmed
    # orphans (so only O05/O06/O07 are absent across the whole window).
    present = set(target) | {"O01", "O02", "O03", "O04"}
    history = [present, present, present]

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        target_history=history,
    )
    assert _counts(decisions).get("exit", 0) == 3
    assert {t for t, d in decisions.items() if d.action == "exit"} == confirmed
    assert _retained(decisions, live) == 30
    # the 4 not-yet-confirmed orphans keep counting down
    assert all(decisions[o].action == "at_risk" for o in ("O01", "O02", "O03", "O04"))
