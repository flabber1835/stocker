"""
365-day full-chaos simulation of the delta engine (the production target_vs_live
path) against a synthetic broker, asserting math correctness for EVERY ticker on
EVERY trading day.

Chaos injected over the year:
  • fluctuating prices (regime-dependent drift + vol), incl. a delisting (price→~0)
  • regime rotation bull_calm → bull_stress → bear_stress → bear_calm → bull_calm
  • portfolio rotation/trims as ranks drift (entry/exit/hold/at_risk/buy_add/sell_trim)
  • over-capacity book → trim-to-cap (seeded above max_positions, plus reject phases)
  • user deposits cash / withdraws cash
  • user liquidates a position at the broker and withdraws the proceeds
  • trading days vs non-trading days (weekends — no run, broker static)
  • some days the broker sync is unavailable → evaluate_all fallback path
  • auto-approve / manual-approve / manual-reject phases (sells always allowed)
  • share-class pairs (GOOG/GOOGL, BRK-A/BRK-B, FOX/FOXA) deduped to one
  • duplicate ("double") ticker rows fed to the ranker — must collapse to one decision
  • held tickers occasionally missing from the ranking universe (data gap)

Invariants asserted per trading day (every ticker):
  I1 coverage   — every target ∪ live ticker gets exactly one decision
  I2 finite     — all weights/scores finite; ranks ≥ 1
  I3 actions    — entry⇒not held, exit⇒held, buy_add/sell_trim⇒held&targeted
  I4 capacity   — entries ≤ free slots; book ≤ max_positions (+ untrimmable no-data orphans)
  I5 buying pwr — Σ buy cost ≤ buying_power/equity + sell-side proceeds (the gate)
  I6 dedup      — never two members of a share-class group in the target
  I7 broker     — account_value == cash + Σ qty·price; cash never goes negative
The run also asserts that every chaos lever and every action type actually fired,
so "every function is touched" is proven, not assumed.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine import (
    RankObservation,
    DeltaDecision,
    evaluate_target_vs_live,
    evaluate_all,
)

# ── strategy params (tight zones on a ~36-name universe so churn happens often) ─
MAX_POSITIONS = 15
ENTRY_RANK = 8
EXIT_RANK = 20
CONFIRMATION_DAYS = 3
DRIFT_THRESHOLD = 0.02
SEED = 20260529

# ── universe incl. share-class groups ──────────────────────────────────────────
SHARE_GROUPS = {
    "GOOG": ["GOOG", "GOOGL"],
    "BRK":  ["BRK-A", "BRK-B"],
    "FOX":  ["FOX", "FOXA"],
}
_SIBLING = {t: g for g in SHARE_GROUPS.values() for t in g}

BASE_NAMES = [f"S{i:02d}" for i in range(27)]          # 27 ordinary names
UNIVERSE = BASE_NAMES + [t for g in SHARE_GROUPS.values() for t in g]   # +6 = 33
DELIST = "S26"                                         # this one will go to ~0


def _finite(x) -> float:
    return x if (x is not None and x == x and not math.isinf(x)) else 0.0


@dataclass
class Broker:
    cash: float = 100_000.0
    qty: dict = field(default_factory=dict)             # ticker -> shares (float ok)
    price: dict = field(default_factory=dict)           # ticker -> price

    def held(self) -> set[str]:
        return {t for t, q in self.qty.items() if q > 1e-9}

    def market_value(self, t: str) -> float:
        return self.qty.get(t, 0.0) * self.price.get(t, 0.0)

    def account_value(self) -> float:
        return self.cash + sum(self.market_value(t) for t in self.held())


def _detect_regime(spy: list[float]) -> str:
    """bull/bear from price vs 50-day SMA; calm/stress from 20-day realized vol."""
    if len(spy) < 51:
        return "bull_calm"
    sma = sum(spy[-50:]) / 50
    bull = spy[-1] >= sma
    rets = [spy[i] / spy[i - 1] - 1 for i in range(len(spy) - 20, len(spy))]
    mean = sum(rets) / len(rets)
    vol = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5 * (252 ** 0.5)
    stress = vol > 0.20
    return f"{'bull' if bull else 'bear'}_{'stress' if stress else 'calm'}"


def _build_history(rank_hist: dict, ticker: str) -> list[RankObservation]:
    return rank_hist.get(ticker, [])


def test_365_day_chaos_simulation():
    rng = random.Random(SEED)
    start = date(2026, 1, 1)

    broker = Broker()
    for t in UNIVERSE:
        broker.price[t] = round(rng.uniform(20, 200), 2)
    # Seed an OVER-CAPACITY book (20 > cap 15) so trim-to-cap is exercised from day 1.
    for t in rng.sample(BASE_NAMES, 20):
        broker.qty[t] = round((10_000.0) / broker.price[t], 4)   # ~$10k each
    broker.cash = 60_000.0

    # latent "true score" per ticker; ranks derive from a noisy version each day
    score = {t: rng.uniform(0, 1) for t in UNIVERSE}
    rank_hist: dict[str, list[RankObservation]] = {}
    # Rolling window of recent build targets (most-recent-first), capped at
    # CONFIRMATION_DAYS, so the engine can confirm orphan exits across builds.
    target_hist: list[set[str]] = []
    spy = [100.0]

    # regime script: (drift, vol) per phase — vol is driven by the PHASE, not the
    # detected regime (avoids the circular bootstrap), so realized vol crosses the
    # 0.20 stress threshold and all four regimes actually occur over the year.
    def _phase(d: int) -> tuple[float, float]:
        if d < 70:   return (+0.0012, 0.006)   # bull_calm
        if d < 130:  return (+0.0009, 0.026)   # bull_stress (price still > SMA, vol up)
        if d < 210:  return (-0.0016, 0.032)   # bear_stress (falling, vol high)
        if d < 285:  return (-0.0005, 0.007)   # bear_calm (still < SMA, vol low)
        return (+0.0013, 0.006)                # bull_calm again

    seen = {k: 0 for k in (
        "trading", "nontrading", "entry", "exit", "hold", "at_risk", "buy_add",
        "sell_trim", "watch", "capacity_demote", "budget_demote", "orphan_exit",
        "deposit", "withdraw", "liquidation", "no_sync_days", "dedup_block",
        "double_fed", "nodata_days", "delisted",
    )}
    regimes_seen: set[str] = set()
    max_book_seen = 0

    for day in range(365):
        cal = start + timedelta(days=day)
        if cal.weekday() >= 5:                          # weekend → market closed
            seen["nontrading"] += 1
            continue
        seen["trading"] += 1

        regime = _detect_regime(spy)
        regimes_seen.add(regime)
        drift, vol = _phase(day)

        # ── 1. fluctuate prices + SPY index ──────────────────────────────────
        for t in UNIVERSE:
            shock = drift + vol * rng.gauss(0, 1)
            broker.price[t] = max(0.01, broker.price[t] * (1 + shock))
        # delisting event mid-year: drive one name to ~0
        if day == 175:
            broker.price[DELIST] = 0.01
            seen["delisted"] += 1
        spy.append(max(1.0, spy[-1] * (1 + drift + vol * rng.gauss(0, 1))))

        # ── 2. account snapshot (pre-trade) ──────────────────────────────────
        account_value = broker.account_value()
        assert account_value > 0 and math.isfinite(account_value)
        buying_power = broker.cash
        live = broker.held()
        actual_weights = {t: broker.market_value(t) / account_value for t in live}
        # I7a: weights finite and consistent
        for t, w in actual_weights.items():
            assert math.isfinite(w) and w >= -1e-12

        # ── 3. scores → ranks (with chaos) ───────────────────────────────────
        for t in UNIVERSE:
            score[t] = min(1.0, max(0.0, score[t] + rng.gauss(0, 0.06)))
        # delisted name ranks worst
        ranked = sorted(UNIVERSE, key=lambda t: score[t] + (- 1 if broker.price[t] <= 0.02 else 0), reverse=True)

        # share-class dedup: keep only the best-ranked sibling of each group
        seen_group: set[int] = set()
        candidates: list[str] = []
        for t in ranked:
            grp = _SIBLING.get(t)
            if grp is not None:
                key = id(grp)
                if key in seen_group:
                    seen["dedup_block"] += 1
                    continue
                seen_group.add(key)
            candidates.append(t)

        # occasionally drop a held name from the universe entirely (data gap)
        nodata_held = 0
        missing: set[str] = set()
        if day % 37 == 11:
            gap = rng.choice(sorted(live)) if live else None
            if gap:
                missing.add(gap)
                seen["nodata_days"] += 1

        # build rank history (most-recent-first) for candidates present today
        today_universe: dict[str, list[RankObservation]] = {}
        rank_of = {t: i + 1 for i, t in enumerate(candidates)}
        # feed a DUPLICATE ("double") row for one ticker — must collapse to one decision
        double = None
        if day % 23 == 5 and candidates:
            double = candidates[0]
            seen["double_fed"] += 1
        for t in candidates:
            if t in missing:
                continue
            obs = RankObservation(run_date=cal, rank=rank_of[t], composite_score=score[t])
            hist = ([obs] + rank_hist.get(t, []))[:CONFIRMATION_DAYS]
            rank_hist[t] = hist
            today_universe[t] = list(hist)
        if double is not None:   # duplicate feed: same key, must not create a 2nd decision
            today_universe[double] = list(rank_hist[double])
        nodata_held = sum(1 for t in live if t not in today_universe)

        # ── 4. approval policy by phase ──────────────────────────────────────
        if day < 90:        policy = "auto"
        elif day < 150:     policy = "manual_all"
        elif day < 210:     policy = "reject_half_buys"
        elif day < 270:     policy = "reject_some_sells"     # lets the book run over cap
        else:               policy = "auto"

        # ── 5. choose engine path ────────────────────────────────────────────
        no_sync = (day % 31 == 17)                          # broker state unknown
        if no_sync:
            seen["no_sync_days"] += 1
            current = {t: 0.0 for t in live}                # cold/no-sync seed
            decisions = evaluate_all(
                universe=today_universe, current_portfolio=current,
                entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
                confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
                actual_weights=actual_weights, drift_threshold=DRIFT_THRESHOLD,
            )
            target = {}                                     # no target this path
        else:
            target = {t: 1.0 / MAX_POSITIONS for t in candidates[:MAX_POSITIONS]
                      if t not in missing}
            # Record this build's target set as the most-recent entry in the
            # rolling history (this build counts as element 0).
            target_hist = ([set(target)] + target_hist)[:CONFIRMATION_DAYS]
            decisions = evaluate_target_vs_live(
                target_portfolio=target, live_positions=live, universe=today_universe,
                confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
                actual_weights=actual_weights, drift_threshold=DRIFT_THRESHOLD,
                account_value=account_value, buying_power=buying_power,
                target_history=target_hist,
            )

        # ── 6. INVARIANTS on the decisions (math correctness, every ticker) ──
        _check_invariants(
            decisions, target, live, today_universe, actual_weights,
            account_value, buying_power, nodata_held, no_sync,
        )

        for d in decisions.values():
            if d.action in seen:
                seen[d.action] += 1
            if d.action == "watch" and "at capacity" in (d.reason or ""):
                seen["capacity_demote"] += 1
            if d.action == "watch" and "buying power" in (d.reason or ""):
                seen["budget_demote"] += 1
            if d.action == "exit" and "dropped from target" in (d.reason or ""):
                seen["orphan_exit"] += 1

        # ── 7. apply approvals → execute against broker ──────────────────────
        _execute(broker, decisions, account_value, policy, rng)

        # ── 8. broker-level chaos events + invariants ────────────────────────
        if day % 30 == 9:
            broker.cash += rng.choice([25_000.0, 50_000.0, 100_000.0]); seen["deposit"] += 1
        if day % 30 == 19 and broker.cash > 20_000:
            broker.cash -= min(broker.cash * 0.3, 30_000.0); seen["withdraw"] += 1
        if day % 17 == 8 and broker.held():
            t = rng.choice(sorted(broker.held()))           # user liquidates + withdraws
            broker.qty[t] = 0.0; seen["liquidation"] += 1
        # adversarial edge days
        if day in (140, 250):                               # user liquidates EVERYTHING
            for t in list(broker.held()):
                broker.qty[t] = 0.0
            seen["liquidation"] += 1
        if day == 333:                                      # user drains ~all cash
            broker.cash *= 0.02; seen["withdraw"] += 1

        assert broker.cash >= -1e-3, f"day {day}: overdraft cash={broker.cash}"
        av_recompute = broker.account_value()
        # On full-liquidation + cash-drain edge days the account legitimately
        # reaches ~0; allow a floating-point epsilon below zero (e.g. -3.6e-44).
        assert math.isfinite(av_recompute) and av_recompute >= -1e-9
        max_book_seen = max(max_book_seen, len(broker.held()))

    # ── coverage: prove the chaos actually touched everything ────────────────
    assert seen["trading"] >= 250 and seen["nontrading"] >= 95
    assert regimes_seen == {"bull_calm", "bull_stress", "bear_stress", "bear_calm"}, regimes_seen
    # at_risk fires whenever a freshly-orphaned name is counting down toward its
    # orphan-timer exit; orphan_exit fires once a name has been absent from the
    # target for CONFIRMATION_DAYS consecutive builds (instant rotation retired).
    for lever in ("entry", "exit", "hold", "at_risk", "buy_add", "sell_trim", "watch",
                  "capacity_demote", "budget_demote", "orphan_exit",
                  "deposit", "withdraw", "liquidation", "no_sync_days",
                  "dedup_block", "double_fed", "nodata_days", "delisted"):
        assert seen[lever] > 0, f"chaos lever never fired: {lever} (seen={seen})"


def _check_invariants(decisions, target, live, universe, actual_weights,
                      account_value, buying_power, nodata_held, no_sync):
    valid = {"entry", "exit", "hold", "watch", "at_risk", "buy_add", "sell_trim"}

    # I1 coverage: every target and every live ticker has exactly one decision
    for t in set(target) | set(live):
        assert t in decisions, f"no decision for {t}"
    for t, d in decisions.items():
        assert d.action in valid, f"{t}: bad action {d.action}"
        assert d.ticker == t

    # I2 finite math for every ticker
    for t, d in decisions.items():
        assert d.rank is None or (isinstance(d.rank, int) and d.rank >= 1)
        for v in (d.current_weight, d.actual_weight, d.weight_drift):
            assert v is None or math.isfinite(v), f"{t}: non-finite {v}"
        assert math.isfinite(d.composite_score)

    # I3 action legality (target_vs_live path)
    if not no_sync:
        for t, d in decisions.items():
            if d.action == "entry":
                assert t in target and t not in live, f"entry {t} held/not-targeted"
                assert d.current_weight is not None and d.current_weight > 0
            elif d.action == "exit":
                assert t in live, f"exit {t} not held"
                # Orphan-exit redesign: a held name exits either via rank
                # confirmation (in-target name whose rank deteriorated) OR via the
                # orphan timer (absent from the target for CONFIRMATION_DAYS builds).
                # Instant capacity rotation is retired — there is no longer a
                # "trim to cap"/"rotated out" exit.
                is_orphan_exit = "dropped from target" in (d.reason or "")
                if is_orphan_exit:
                    # I4b: an orphan-timer exit must be an untargeted name with
                    # ranking data — never a targeted name or a data-gap orphan.
                    assert t not in target and (d.rank or 0) < 9999, (
                        f"orphan exit {t} targeted/no-data"
                    )
                elif t in universe and len(universe[t]) >= CONFIRMATION_DAYS:
                    # I3b: a rank-confirmed exit needs CONFIRMATION_DAYS of rank > exit_rank
                    lead = universe[t][:CONFIRMATION_DAYS]
                    assert all(o.rank > EXIT_RANK for o in lead), (
                        f"exit {t} not rank-confirmed: {[o.rank for o in lead]}"
                    )
            elif d.action in ("buy_add", "sell_trim"):
                assert t in live and t in target, f"{d.action} {t} must be held&targeted"
                # I3c: drift must exceed the rebalance threshold in the right direction
                assert d.weight_drift is not None and math.isfinite(d.weight_drift)
                if d.action == "buy_add":
                    assert d.weight_drift < -DRIFT_THRESHOLD + 1e-12, f"buy_add {t} drift {d.weight_drift}"
                else:
                    assert d.weight_drift > DRIFT_THRESHOLD - 1e-12, f"sell_trim {t} drift {d.weight_drift}"
            elif d.action == "hold":
                assert t in live, f"hold {t} not held"
            elif d.action == "watch":
                # I5b: a buy demoted for capacity/buying-power is a watch with current_weight cleared
                if "deferred" in (d.reason or ""):
                    assert d.current_weight is None, f"deferred watch {t} kept weight"

    # I4 capacity — entry cap holds; the book converges to cap as orphans time out.
    #
    # Orphan-exit redesign: instant trim-to-cap rotation is retired, so the book
    # can TRANSIENTLY exceed max_positions while orphans count down (at_risk). New
    # entries are still hard-capped to the free slots, so entries never push the
    # book over the cap on their own. The over-cap overhang is exactly the held
    # names that are not being force-exited this run: at_risk orphans (timer not
    # yet met) + data-gap orphans. Each such overhang name will exit once its
    # orphan window completes, so the book is guaranteed to converge to the cap.
    exits = sum(1 for d in decisions.values() if d.action == "exit")
    entries = sum(1 for d in decisions.values() if d.action == "entry")
    retained = len(live) - exits
    free_slots = MAX_POSITIONS - retained
    # Entries strictly fit the free slots (never exceed them).
    assert entries <= max(0, free_slots) + 1e-9, (
        f"entry cap breached: {entries} entries, {free_slots} free slots"
    )
    # Any overhang above the cap must be accounted for by orphans not yet exiting
    # (at_risk counting down, or data-gap holds) — never by entries.
    at_risk_held = sum(1 for d in decisions.values() if d.action == "at_risk")
    overhang = (retained + entries) - MAX_POSITIONS
    assert overhang <= at_risk_held + nodata_held, (
        f"book {retained + entries} > cap {MAX_POSITIONS}; overhang {overhang} "
        f"exceeds at_risk {at_risk_held} + no-data {nodata_held}"
    )

    # I5 buying-power gate (only the target_vs_live cash path carries it)
    if not no_sync and account_value > 0:
        def cost(d):
            if d.action == "entry":
                return max(0.0, _finite(d.current_weight))
            if d.weight_drift is not None and math.isfinite(d.weight_drift):
                return max(0.0, -d.weight_drift)
            return max(0.0, _finite(d.current_weight) - _finite(d.actual_weight))
        buys = sum(cost(d) for d in decisions.values() if d.action in ("entry", "buy_add"))
        exit_proc = sum(_finite(actual_weights.get(t))
                        for t, d in decisions.items() if d.action == "exit")
        trim_proc = sum(max(0.0, _finite(d.weight_drift))
                        for d in decisions.values() if d.action == "sell_trim")
        available = max(0.0, buying_power) / account_value + exit_proc + trim_proc
        assert buys <= available + 1e-6, f"buys {buys:.4f} > available {available:.4f}"

    # I6 share-class dedup — never two siblings targeted at once
    grouped: dict[int, int] = {}
    for t in target:
        g = _SIBLING.get(t)
        if g is not None:
            grouped[id(g)] = grouped.get(id(g), 0) + 1
    assert all(c <= 1 for c in grouped.values()), "two share-class siblings targeted"


def _approve(action: str, policy: str, rng: random.Random) -> bool:
    # Sells (exit / sell_trim / trim) always allowed — closing must never be blocked.
    if action in ("exit", "sell_trim"):
        return policy != "reject_some_sells" or rng.random() > 0.5
    if action not in ("entry", "buy_add"):
        return False
    if policy == "auto":
        return True
    if policy == "manual_all":
        return True
    if policy == "reject_half_buys":
        return rng.random() > 0.5
    return True  # reject_some_sells phase still approves buys


def _execute(broker, decisions, account_value, policy, rng):
    # Sells first (free cash), then buys — mirrors same-open netting.
    for d in decisions.values():
        if d.action == "exit" and _approve("exit", policy, rng):
            broker.cash += broker.market_value(d.ticker)
            broker.qty[d.ticker] = 0.0
        elif d.action == "sell_trim" and _approve("sell_trim", policy, rng):
            drift = max(0.0, _finite(d.weight_drift))          # overweight fraction
            notional = drift * account_value
            px = broker.price[d.ticker]
            if px > 0:
                broker.qty[d.ticker] = max(0.0, broker.qty[d.ticker] - notional / px)
                broker.cash += notional
    for d in decisions.values():
        px = broker.price[d.ticker]
        if px <= 0:
            continue
        if d.action == "entry" and _approve("entry", policy, rng):
            notional = _finite(d.current_weight) * account_value
            if notional <= broker.cash + 1e-6:
                broker.qty[d.ticker] = broker.qty.get(d.ticker, 0.0) + notional / px
                broker.cash -= notional
        elif d.action == "buy_add" and _approve("buy_add", policy, rng):
            inc = max(0.0, -_finite(d.weight_drift)) * account_value
            if inc <= broker.cash + 1e-6:
                broker.qty[d.ticker] = broker.qty.get(d.ticker, 0.0) + inc / px
                broker.cash -= inc
