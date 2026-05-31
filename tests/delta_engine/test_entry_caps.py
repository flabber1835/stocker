"""
Entry caps for evaluate_target_vs_live (regression for the live-confirmed bugs):

Bug 1 — realized portfolio could exceed max_positions: entries were emitted for
        every target ticker not held, with no capacity check, while orphan holds
        (held, not in target, still in buffer zone) were retained. target(30) +
        orphans → >30 positions.

Bug 2 — buy-only rotation blew past buying power: entries were sized against total
        equity assuming offsetting exits, but a rotation that keeps orphans produces
        no exits → naked buys exceeding buying_power → Alpaca "insufficient funds".

The fix allocates the book by rank, then gates buys by cash:
  - capacity (_allocate_capacity): the max_positions slots are filled best-rank
    first by new entries AND trimmable orphans together, so a higher-ranked entry
    rotates out a weaker orphan instead of being locked out. Losing entries → watch,
    losing orphans → exit. Mandatory holds (in-target / data-gap) are never displaced.
  - buying power (_cap_buys): cumulative kept-buy weight <= buying_power/account_value
    + exit proceeds (which now include rotated-out orphans, funding the rotation).
The buying-power gate is only active when account_value & buying_power are supplied.
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


# ── Bug 1: capacity ───────────────────────────────────────────────────────────

def test_full_book_of_unconfirmed_orphans_defers_entries_no_instant_rotation():
    """Orphan-exit redesign: instant rotation is RETIRED. A full book of orphans
    that are NOT yet confirmed-exiting (no build history → at_risk) does not get
    force-rotated to admit better entries. The book is full, so the 10 rank-5
    entries are deferred to 'watch' — they wait for an orphan to time out, rather
    than snap-selling a held position. No exits this run, book stays ≤ cap."""
    held = {f"H{i:02d}" for i in range(30)}                 # full book, orphans
    target = {f"N{i:02d}": 1.0 / 30 for i in range(10)}     # better new names, not held
    universe = {t: _history(30) for t in held}
    universe.update({t: _history(5) for t in target})

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=held, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    c = _counts(decisions)
    assert c.get("exit", 0) == 0                            # no orphan force-rotated
    assert c.get("entry", 0) == 0                           # book full → entries deferred
    assert all(decisions[t].action == "watch" for t in target)
    assert all(decisions[t].action == "at_risk" for t in held)  # orphans counting down


def test_confirmed_orphans_free_slots_for_entries():
    """When orphans ARE confirmed-exiting (absent from the target for
    confirmation_days builds), their slots free up and the best entries fill them.
    6 confirmed-orphan exits → 6 slots → the 6 best of 10 rank-5 entries enter,
    the rest stay watch. Book stays at cap."""
    held = {f"H{i:02d}" for i in range(30)}
    target = {f"N{i:02d}": 1.0 / 30 for i in range(10)}
    universe = {t: _history(30) for t in held}
    universe.update({f"N{i:02d}": _history(i + 1) for i in range(10)})  # ranks 1..10
    # 6 of the held orphans (H00..H05) have been absent from the target for 3 builds.
    confirmed = {f"H{i:02d}" for i in range(6)}
    others = {f"H{i:02d}" for i in range(6, 30)} | {f"N{i:02d}" for i in range(10)}
    history = [others, others, others]                      # confirmed orphans absent in all 3

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=held, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        target_history=history,
    )
    c = _counts(decisions)
    assert c.get("exit", 0) == 6                            # only the confirmed orphans exit
    assert all(decisions[t].action == "exit" for t in confirmed)
    assert c.get("entry", 0) == 6                           # 6 freed slots → 6 best entries
    retained = len(held) - c.get("exit", 0)
    assert retained + c.get("entry", 0) <= 30              # book at cap, never over
    assert decisions["N00"].action == "entry"              # best-ranked enters
    assert decisions["N09"].action == "watch"              # worst deferred


def test_capacity_does_not_bind_for_small_portfolio():
    """Backward-compat: a small target on an empty book → all entries (no capping)."""
    target = {f"N{i:02d}": 1.0 / 30 for i in range(3)}
    universe = {t: _history(5) for t in target}
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=set(), universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert all(decisions[t].action == "entry" for t in target)


# ── Bug 2: buying power ─────────────────────────────────────────────────────────

def test_buying_power_blocks_unfunded_entries():
    """Fully-invested account ($2k buying power of $100k): 3.33%-weight entries
    don't fit the 2% available → all deferred to watch, no naked buys."""
    target = {f"N{i:02d}": 1.0 / 30 for i in range(5)}
    universe = {t: _history(5) for t in target}
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=set(), universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        account_value=100_000.0, buying_power=2_000.0,
    )
    assert _counts(decisions).get("entry", 0) == 0
    assert all(decisions[t].action == "watch" for t in target)


def test_buying_power_allows_what_fits():
    """$10k buying power of $100k = 10% available → exactly 3 of the 3.33% entries fit."""
    target = {f"N{i:02d}": 1.0 / 30 for i in range(5)}
    universe = {f"N{i:02d}": _history(i + 1) for i in range(5)}  # distinct ranks 1..5
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=set(), universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        account_value=100_000.0, buying_power=10_000.0,
    )
    assert _counts(decisions).get("entry", 0) == 3              # 3 * 3.33% = 10%
    # the best-ranked three enter
    assert decisions["N00"].action == "entry"
    assert decisions["N04"].action == "watch"


def test_exit_proceeds_fund_matched_rotation():
    """A confirmed orphan exit frees cash that funds an equal-weight entry even at
    ~0 buying power — normal rebalancing must keep working. OLD is a confirmed
    orphan (absent from the target for confirmation_days builds)."""
    target = {"NEW": 1.0 / 30}
    held = {"OLD"}
    universe = {"NEW": _history(5), "OLD": _history(50, 50, 50)}
    history = [{"NEW"}, {"NEW"}, {"NEW"}]                        # OLD orphaned 3 builds → exit
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=held, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        account_value=100_000.0, buying_power=0.0,
        actual_weights={"OLD": 1.0 / 30},                        # OLD = 3.33% of equity
        target_history=history,
    )
    assert decisions["OLD"].action == "exit"
    assert decisions["NEW"].action == "entry"                    # funded by the exit


def test_no_cash_gate_when_account_value_missing():
    """Without account_value/buying_power the cash gate is inactive (only capacity)."""
    target = {f"N{i:02d}": 1.0 / 30 for i in range(5)}
    universe = {t: _history(5) for t in target}
    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=set(), universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
    )
    assert all(decisions[t].action == "entry" for t in target)


# ── Combined: the live-confirmed scenario shape ───────────────────────────────

def test_seeded_rotation_scenario_is_bounded_and_funded():
    """Mirror the live repro: target Z01-Z30, broker holds Z20-Z45, $2k buying power.
    Result must be <= 30 positions and emit no entry it can't fund.

    Orphan-exit redesign: with no build history the 15 orphans (Z31-Z45) are
    at_risk (counting down), NOT instantly rotated out. So the book is full of
    holds + at_risk orphans and the new entries (Z01-Z19) are deferred to watch.
    Both original invariants still hold: book ≤ cap, and no unfunded buys."""
    target = {f"Z{i:02d}": 1.0 / 30 for i in range(1, 31)}
    held = {f"Z{i:02d}" for i in range(20, 46)}              # 26 held: 11 in target, 15 orphans
    universe = {f"Z{i:02d}": _history(i) for i in range(1, 51)}

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=held, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        account_value=100_000.0, buying_power=2_000.0,
        actual_weights={t: 1.0 / 30 for t in held},
    )
    c = _counts(decisions)
    exits = c.get("exit", 0)
    entries = c.get("entry", 0)
    retained = len(held) - exits
    assert retained + entries <= 30                          # Bug 1: no over-cap (unchanged)
    # Bug 2 invariant still holds: buys never exceed available cash.
    buys = sum(max(0.0, (d.current_weight or 0.0)) for d in decisions.values() if d.action == "entry")
    proceeds = sum(1.0 / 30 for t, d in decisions.items() if d.action == "exit")
    available = 2_000.0 / 100_000.0 + proceeds
    assert buys <= available + 1e-9                          # funded — no naked buys
    # No instant rotation: orphans are not force-exited on the first build.
    assert exits == 0
    assert all(decisions[f"Z{i:02d}"].action == "at_risk" for i in range(31, 46))


# ── buy_add buying-power gating (extends the cash gate beyond entries) ─────────

def _bb(target, live, universe, *, account_value, buying_power, actual_weights):
    return evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        entry_rank=25, exit_rank=40, confirmation_days=3, max_positions=30,
        account_value=account_value, buying_power=buying_power, actual_weights=actual_weights,
    )


def test_buy_add_blocked_when_no_buying_power():
    """An underweight held name wants a top-up (buy_add), but with ~no buying power
    it must stay a plain hold — not buy more it can't fund."""
    target = {"AAA": 0.10}
    universe = {"AAA": _history(10)}                  # hold zone
    d = _bb(target, {"AAA"}, universe,
            account_value=100_000.0, buying_power=1_000.0,   # 1% available
            actual_weights={"AAA": 0.02})                    # 8% underweight → wants buy_add
    assert d["AAA"].action == "hold"                  # demoted from buy_add
    assert d["AAA"].action != "watch"                 # buy_add demotes to hold, not watch


def test_buy_add_allowed_when_funded():
    target = {"AAA": 0.10}
    universe = {"AAA": _history(10)}
    d = _bb(target, {"AAA"}, universe,
            account_value=100_000.0, buying_power=10_000.0,  # 10% available ≥ 8% top-up
            actual_weights={"AAA": 0.02})
    assert d["AAA"].action == "buy_add"


def test_sell_trim_proceeds_fund_buy_add():
    """A sell_trim frees cash that funds a buy_add at ~0 buying power."""
    target = {"AAA": 0.10, "BBB": 0.10}
    universe = {"AAA": _history(10), "BBB": _history(12)}
    d = _bb(target, {"AAA", "BBB"}, universe,
            account_value=100_000.0, buying_power=0.0,
            actual_weights={"AAA": 0.02, "BBB": 0.20})       # AAA underweight, BBB overweight
    assert d["BBB"].action == "sell_trim"                    # frees ~10% proceeds
    assert d["AAA"].action == "buy_add"                      # funded by the trim


def test_entry_and_buy_add_share_one_budget_by_rank():
    """Entries and buy_adds draw on the same buying-power budget, best-ranked first.
    Budget fits the rank-3 entry but not the additional rank-5 buy_add → buy_add holds."""
    target = {"NEW": 0.10, "OLD": 0.10}
    universe = {"NEW": _history(3), "OLD": _history(5)}
    d = _bb(target, {"OLD"}, universe,
            account_value=100_000.0, buying_power=10_000.0,  # exactly 10% — one full position
            actual_weights={"OLD": 0.02})
    assert d["NEW"].action == "entry"                        # rank 3, funded first
    assert d["OLD"].action == "hold"                         # rank 5 buy_add deferred (budget spent)
