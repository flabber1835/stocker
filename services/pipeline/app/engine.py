"""
Pure-Python buffer-zone delta engine.

Evaluates which tickers should enter or exit the portfolio based on
consecutive-day confirmation in the entry/exit rank zones.
All functions are stateless and fully deterministic.
"""
from dataclasses import dataclass, replace
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class RankObservation:
    run_date: date
    rank: int
    composite_score: float


@dataclass(frozen=True)
class DeltaDecision:
    ticker: str
    action: str          # 'entry' | 'exit' | 'hold' | 'watch' | 'at_risk' | 'buy_add' | 'sell_trim'
    rank: int
    composite_score: float
    confirmation_days_met: int
    current_weight: Optional[float]  # None when not in portfolio
    reason: str
    actual_weight: Optional[float] = None   # actual broker weight (market_value / account_value); None when not held or no sync data
    weight_drift: Optional[float] = None    # actual_weight - target_weight; positive = overweight, negative = underweight


def _consecutive_in_zone(
    observations: list[RankObservation],
    predicate,
    required: int,
) -> int:
    """Count consecutive leading observations (most-recent first) satisfying predicate.

    Only the most recent ``required`` observations are examined (``observations[:required]``).
    Callers must pass observations sorted most-recent-first so that the leading
    slice corresponds to the most recent calendar days.
    """
    count = 0
    for obs in observations[:required]:
        if predicate(obs):
            count += 1
        else:
            break
    return count


def evaluate_ticker(
    ticker: str,
    observations: list[RankObservation],  # sorted date DESC (most recent first)
    current_weight: Optional[float],
    entry_rank: int,
    exit_rank: int,
    confirmation_days: int,
    portfolio_at_capacity: bool,
    actual_weight: Optional[float] = None,   # actual broker weight
    drift_threshold: float = 0.02,
) -> DeltaDecision:
    held = current_weight is not None

    if not observations:
        return DeltaDecision(
            ticker=ticker,
            action="hold" if held else "watch",
            rank=9999, composite_score=0.0,
            confirmation_days_met=0,
            current_weight=current_weight,
            reason="No ranking observations available",
            actual_weight=actual_weight,
            weight_drift=None,
        )

    latest = observations[0]
    entry_days = _consecutive_in_zone(
        observations, lambda o, er=entry_rank: o.rank <= er, confirmation_days
    )
    exit_days = _consecutive_in_zone(
        observations, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
    )

    # Compute drift when we have both actual and target weights
    drift: Optional[float] = None
    if actual_weight is not None and current_weight is not None:
        drift = actual_weight - current_weight

    if not held and entry_days >= confirmation_days:
        if portfolio_at_capacity:
            action = "watch"
            reason = (
                f"Confirmed entry (rank={latest.rank} ≤ {entry_rank} for {entry_days}d) "
                f"but portfolio is at capacity"
            )
        else:
            action = "entry"
            reason = f"Rank={latest.rank} ≤ entry_rank={entry_rank} for {entry_days} consecutive days"
    elif held and exit_days >= confirmation_days:
        # Priority 1: confirmed exit always wins
        action = "exit"
        reason = f"Rank={latest.rank} > exit_rank={exit_rank} for {exit_days} consecutive days"
    elif held and latest.rank > exit_rank:
        # Priority 2: rank above exit_rank but not confirmed — at_risk suppresses drift
        action = "at_risk"
        reason = (
            f"Held, rank={latest.rank} > exit_rank={exit_rank} "
            f"({exit_days}/{confirmation_days}d toward exit confirmation)"
        )
    elif held:
        # Priority 3: rank is good (≤ exit_rank) — check drift
        zone = "entry zone" if latest.rank <= entry_rank else "buffer zone"
        # Only rebalance when there's a real positive target weight. current_weight=0.0
        # is the cold-start sentinel ("held at broker, no portfolio target yet") — drift
        # relative to 0 is meaningless and would generate spurious sell_trim actions.
        # Explicit None/0 check: a NaN target weight (data corruption) is truthy in
        # Python; treat it as missing rather than letting the drift branch consume it.
        has_real_target = (
            current_weight is not None
            and current_weight > 0  # excludes 0.0 sentinel and negatives
            and current_weight == current_weight  # NaN != NaN, so NaN fails this
        )
        if has_real_target and drift is not None and abs(drift) > drift_threshold:
            if drift < 0:
                action = "buy_add"
                reason = (
                    f"Held, rank={latest.rank} in {zone}, underweight: "
                    f"actual={actual_weight:.2%} target={current_weight:.2%} "
                    f"drift={drift:+.2%}"
                )
            else:
                action = "sell_trim"
                reason = (
                    f"Held, rank={latest.rank} in {zone}, overweight: "
                    f"actual={actual_weight:.2%} target={current_weight:.2%} "
                    f"drift={drift:+.2%}"
                )
        else:
            # Priority 4: hold
            action = "hold"
            reason = f"Held, rank={latest.rank} in {zone}"
    else:
        action = "watch"
        reason = (
            f"Not held, rank={latest.rank}, "
            f"needs {confirmation_days}d ≤ {entry_rank} (have {entry_days}d)"
        )

    return DeltaDecision(
        ticker=ticker, action=action,
        rank=latest.rank, composite_score=latest.composite_score,
        confirmation_days_met=entry_days if action in ("entry", "watch") else exit_days,
        current_weight=current_weight,
        reason=reason,
        actual_weight=actual_weight,
        weight_drift=drift,
    )


def evaluate_target_vs_live(
    target_portfolio: dict[str, float],
    live_positions: set[str],
    universe: dict[str, list[RankObservation]],
    entry_rank: int,
    exit_rank: int,
    confirmation_days: int,
    max_positions: int,
    actual_weights: dict[str, float] | None = None,
    drift_threshold: float = 0.02,
    account_value: float | None = None,
    buying_power: float | None = None,
) -> dict[str, DeltaDecision]:
    """Diff portfolio_holdings (target) against live_positions (actual broker state).

    entry     — ticker in target but not yet held at broker; current_weight = target weight
                (trade-executor uses this for order sizing — floor(account_value × weight / price))
    exit      — ticker held at broker but removed from target portfolio
    at_risk   — ticker held at broker and in target, rank > exit_rank but not yet confirmed exit
    hold      — ticker in both target and broker positions, rank good, weight on target
    buy_add   — ticker held, rank good, actual weight < target - drift_threshold
    sell_trim — ticker held, rank good, actual weight > target + drift_threshold
    watch     — confirmed in entry zone (confirmation_days) but not yet in target;
                informational — portfolio-builder will add on next build
    """
    decisions: dict[str, DeltaDecision] = {}

    # Entries: target says hold but broker doesn't yet
    for ticker, weight in target_portfolio.items():
        if ticker in live_positions:
            continue  # handled in holds below
        obs = universe.get(ticker, [])
        latest = obs[0] if obs else None
        decisions[ticker] = DeltaDecision(
            ticker=ticker,
            action="entry",
            rank=latest.rank if latest else 9999,
            composite_score=latest.composite_score if latest else 0.0,
            confirmation_days_met=confirmation_days,
            current_weight=weight,  # target weight → trade-executor sizes from this
            reason=f"In target portfolio (weight={weight:.2%}) but not held at broker",
            actual_weight=None,
            weight_drift=None,
        )

    # Exits: broker holds but target no longer includes.
    #
    # The portfolio-builder may exclude a well-ranked ticker for covariance /
    # capacity reasons (e.g. already holds 3 correlated names in the same
    # sector). In that case the rank is still good and an immediate exit would
    # sell the position only to re-buy it a few days later — pure churn.
    #
    # Rule: apply the same buffer-zone confirmation logic used for held
    # positions.  Only exit once rank > exit_rank for confirmation_days
    # consecutive days.  If rank ≤ exit_rank, classify as "hold" so the
    # position stays put until the rank actually deteriorates.
    #
    # Safeguard for the degraded case: if target_portfolio is completely
    # empty, portfolio-builder may have failed transiently or filtered all
    # candidates. Same confirmation logic applies — only the confirmed-bad-rank
    # branch exits in degraded mode.
    target_is_empty = not target_portfolio
    for ticker in live_positions:
        if ticker in target_portfolio:
            continue  # handled in holds below
        obs = universe.get(ticker, [])
        latest = obs[0] if obs else None
        if not obs:
            # No ranking history — could be a data gap (av-ingestor hasn't
            # fetched yet) or a position added directly at the broker. Hold
            # rather than force-exit; the next pipeline run will reconsider
            # once ranking data is available.
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="hold",
                rank=9999,
                composite_score=0.0,
                confirmation_days_met=0,
                current_weight=0.0,
                reason=(
                    "Held at broker but absent from ranking universe — "
                    "awaiting price/fundamentals data from av-ingestor"
                ),
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
            continue

        if target_is_empty:
            # Degraded mode — use the original buffer-zone logic so a single
            # empty portfolio build doesn't trigger a wholesale liquidation.
            exit_days_empty = _consecutive_in_zone(
                obs, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
            )
            if exit_days_empty >= confirmation_days:
                action_empty = "exit"
                reason_empty = (
                    f"Rank={latest.rank} > exit_rank={exit_rank} for {exit_days_empty} "
                    f"consecutive days (target portfolio is empty — degraded mode)"
                )
            elif latest.rank > exit_rank:
                action_empty = "at_risk"
                reason_empty = (
                    f"Held at broker, target portfolio empty, rank={latest.rank} > "
                    f"exit_rank={exit_rank} "
                    f"({exit_days_empty}/{confirmation_days}d toward exit confirmation)"
                )
            else:
                zone = "entry zone" if latest.rank <= entry_rank else "buffer zone"
                action_empty = "hold"
                reason_empty = (
                    f"Held at broker, target portfolio empty, but rank={latest.rank} "
                    f"in {zone} — holding pending non-empty target"
                )
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action=action_empty,
                rank=latest.rank,
                composite_score=latest.composite_score,
                confirmation_days_met=exit_days_empty,
                current_weight=0.0,
                reason=reason_empty,
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
            continue

        # Has ranking data, non-empty target, ticker not in target.
        # Apply buffer-zone confirmation: only exit after rank > exit_rank
        # for confirmation_days consecutive days.  A well-ranked orphan stays
        # as "hold" — don't sell rank-11 MU because the covariance optimizer
        # preferred NVDA+WDC+TSM for semiconductor exposure.
        exit_days = _consecutive_in_zone(
            obs, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
        )
        if latest.rank > exit_rank:
            if exit_days >= confirmation_days:
                orphan_action = "exit"
                orphan_reason = (
                    f"Held at broker, not in target portfolio, rank={latest.rank} > "
                    f"exit_rank={exit_rank} for {exit_days} consecutive days — exiting"
                )
            else:
                orphan_action = "at_risk"
                orphan_reason = (
                    f"Held at broker, not in target portfolio, rank={latest.rank} > "
                    f"exit_rank={exit_rank} "
                    f"({exit_days}/{confirmation_days}d toward exit confirmation)"
                )
        else:
            zone = "entry zone" if latest.rank <= entry_rank else "buffer zone"
            orphan_action = "hold"
            orphan_reason = (
                f"Held at broker, not in target portfolio (rank={latest.rank} in {zone}) — "
                "portfolio-builder excluded on covariance/capacity grounds; "
                "holding until rank falls below exit_rank"
            )
        decisions[ticker] = DeltaDecision(
            ticker=ticker,
            action=orphan_action,
            rank=latest.rank,
            composite_score=latest.composite_score,
            confirmation_days_met=exit_days,
            current_weight=0.0,
            reason=orphan_reason,
            actual_weight=actual_weights.get(ticker) if actual_weights else None,
            weight_drift=None,
        )

    # Holds: in both target and broker positions
    for ticker in live_positions:
        if ticker not in target_portfolio:
            continue
        target_weight = target_portfolio[ticker]
        obs = universe.get(ticker, [])
        latest = obs[0] if obs else None

        actual_w = actual_weights.get(ticker) if actual_weights else None
        drift = (actual_w - target_weight) if actual_w is not None else None

        # Determine rank-based action first
        if obs:
            exit_days = _consecutive_in_zone(
                obs, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
            )
            current_rank = latest.rank
            if exit_days >= confirmation_days:
                # Confirmed exit overrides everything
                rank_action = "exit"
            elif current_rank > exit_rank:
                # At risk — suppress drift
                rank_action = "at_risk"
            else:
                rank_action = "hold"
        else:
            exit_days = 0
            current_rank = 9999
            rank_action = "hold"

        # Layer drift on top only when rank-based action is "hold" and there is a real
        # positive target weight. Explicit None/positive check rejects 0.0 (cold-start
        # sentinel), negatives, and NaN (which is truthy in Python but breaks drift math).
        has_real_target = (
            target_weight is not None
            and target_weight > 0
            and target_weight == target_weight  # NaN-safe
        )
        if rank_action == "hold" and has_real_target and drift is not None and abs(drift) > drift_threshold:
            if drift < 0:
                action = "buy_add"
            else:
                action = "sell_trim"
        else:
            action = rank_action

        # Build reason
        zone = "entry zone" if (latest and latest.rank <= entry_rank) else "buffer zone"
        if action == "exit":
            reason = (
                f"Rank={current_rank} > exit_rank={exit_rank} for {exit_days} consecutive days"
            )
        elif action == "at_risk":
            reason = (
                f"Held, rank={current_rank} > exit_rank={exit_rank} "
                f"({exit_days}/{confirmation_days}d toward exit confirmation)"
            )
        elif action == "buy_add":
            reason = (
                f"Held, rank={current_rank} in {zone}, underweight: "
                f"actual={actual_w:.2%} target={target_weight:.2%} "
                f"drift={drift:+.2%}"
            )
        elif action == "sell_trim":
            reason = (
                f"Held, rank={current_rank} in {zone}, overweight: "
                f"actual={actual_w:.2%} target={target_weight:.2%} "
                f"drift={drift:+.2%}"
            )
        else:
            reason = f"Held at broker and in target portfolio (target weight={target_weight:.2%})"

        decisions[ticker] = DeltaDecision(
            ticker=ticker,
            action=action,
            rank=current_rank,
            composite_score=latest.composite_score if latest else 0.0,
            confirmation_days_met=exit_days,
            current_weight=target_weight,
            reason=reason,
            actual_weight=actual_w,
            weight_drift=drift,
        )

    # Watches: universe tickers confirmed in entry zone but not yet in target
    in_target_or_live = set(target_portfolio.keys()) | live_positions
    pending_entries = sum(1 for d in decisions.values() if d.action == "entry")
    current_held = len(live_positions)

    for ticker, obs in universe.items():
        if ticker in in_target_or_live or not obs:
            continue
        entry_days = _consecutive_in_zone(
            obs, lambda o, er=entry_rank: o.rank <= er, confirmation_days
        )
        if entry_days >= confirmation_days:
            latest = obs[0]
            at_capacity = (current_held + pending_entries) >= max_positions
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="watch",
                rank=latest.rank,
                composite_score=latest.composite_score,
                confirmation_days_met=entry_days,
                current_weight=None,
                reason=(
                    f"Confirmed entry (rank={latest.rank} ≤ {entry_rank} for {entry_days}d)"
                    f" — pending portfolio-builder to add to target"
                    + (" [at capacity]" if at_capacity else "")
                ),
                actual_weight=None,
                weight_drift=None,
            )

    # Capacity: fill the book with the best-ranked names, rotating weak orphans
    # out for strictly higher-ranked new entries (replaces the old cap-then-trim
    # ordering that let a held orphan permanently block a better new entry).
    _allocate_capacity(decisions, live_positions, target_portfolio, max_positions)

    # Buying-power: defer any buys the available cash (incl. sell proceeds) can't fund.
    _cap_buys(
        decisions, live_positions, max_positions,
        actual_weights=actual_weights,
        account_value=account_value, buying_power=buying_power,
    )

    return decisions


def _finite(x) -> float:
    """NaN/None-safe float (a corrupt weight must not silently pass a gate)."""
    return x if (x is not None and x == x) else 0.0


def _cap_buys(
    decisions: dict[str, DeltaDecision],
    live_positions: set[str],
    max_positions: int,
    *,
    actual_weights: dict[str, float] | None = None,
    account_value: float | None = None,
    buying_power: float | None = None,
) -> None:
    """Buying-power (cash) gate: defer buys the available cash can't fund. Mutates
    ``decisions`` in place. The position-count cap is handled separately, upstream,
    by ``_allocate_capacity``; this runs after it on the already-capped book.

    Entries AND buy_adds share one budget, best-ranked first across both:
      Σ kept buy cost <= buying_power/account_value + sell-side proceeds, where
        - entry cost    = full target weight
        - buy_add cost  = top-up increment (target − actual) = −weight_drift
        - proceeds      = Σ exit market value + Σ sell_trim overweight (weight space)
                          (exit proceeds now include orphans rotated out by
                          _allocate_capacity, so a rotation funds its own entry)
      Demotion: entry → watch; buy_add → hold (keep the position, defer the top-up).
      Only enforced when account_value (>0) and buying_power are supplied; otherwise
      the executor/risk-service remain the cash backstop.

    Sell-side proceeds are credited so normal same-open rotation/rebalance still
    funds its buys at ~0 buying power — only unfunded buys are deferred.
    """
    kept_entries = [d for d in decisions.values() if d.action == "entry"]

    # ── Buying-power gate: entries + buy_adds share one budget ────────────────
    cap_cash = account_value is not None and account_value > 0 and buying_power is not None
    if not cap_cash:
        return

    aw = actual_weights or {}
    exit_proceeds = sum(
        _finite(aw.get(d.ticker)) for d in decisions.values() if d.action == "exit"
    )
    trim_proceeds = sum(
        max(0.0, _finite(d.weight_drift)) for d in decisions.values() if d.action == "sell_trim"
    )
    available = max(0.0, buying_power) / account_value + exit_proceeds + trim_proceeds

    def _cost(d: DeltaDecision) -> float:
        if d.action == "entry":
            return max(0.0, _finite(d.current_weight))
        # buy_add top-up increment: prefer the explicit drift, else (target − actual)
        if d.weight_drift is not None and d.weight_drift == d.weight_drift:
            return max(0.0, -d.weight_drift)
        return max(0.0, _finite(d.current_weight) - _finite(d.actual_weight))

    buys = sorted(kept_entries + [d for d in decisions.values() if d.action == "buy_add"],
                  key=lambda d: d.rank)
    cum = 0.0
    EPS = 1e-9
    for d in buys:
        cost = _cost(d)
        if cum + cost <= available + EPS:
            cum += cost
            continue
        left = max(0.0, available - cum)
        if d.action == "entry":
            decisions[d.ticker] = replace(
                d, action="watch", current_weight=None,
                reason=(f"deferred — insufficient buying power (needs {cost:.2%}, "
                        f"{left:.2%} of equity left)"),
            )
        else:  # buy_add → keep the position at its current weight, defer the top-up
            decisions[d.ticker] = replace(
                d, action="hold",
                reason=(f"top-up deferred — insufficient buying power (needs {cost:.2%}, "
                        f"{left:.2%} of equity left); holding at current weight"),
            )


def _allocate_capacity(
    decisions: dict[str, DeltaDecision],
    live_positions: set[str],
    target_portfolio: dict[str, float],
    max_positions: int,
) -> None:
    """Fill the position book (max_positions slots) with the best-ranked names,
    rotating weak orphans out for strictly higher-ranked new entries. Mutates
    ``decisions`` in place. Capacity only — the cash gate runs after, in _cap_buys.

    Slot allocation:
      1. Mandatory holds occupy a slot unconditionally and cannot be displaced:
         - in-target held names (the builder still wants them; buy_adds are these)
         - data-gap orphans (rank 9999: held but missing from the ranking universe
           — never force-sold on a data gap; that is not a sell signal)
      2. The remaining slots are contested, best rank first, by:
         - new entries (target, not held)
         - trimmable orphans (held, not target, action hold/at_risk, rank < 9999)
         Winners keep their action (entry / hold); losers are demoted:
           entry  -> watch  (deferred — out-ranked for the open slots)
           orphan -> exit   (rotated out for a better-ranked entry, or over cap)

    Why this exists / what it replaces
    ----------------------------------
    The buffer-zone exit is rank-based, so a *well-ranked* orphan (held but
    covariance-excluded from the target) never exits on its own. The previous
    cap-then-trim ordering computed entry slots against the pre-trim book, so a
    held orphan permanently blocked a strictly higher-ranked new entry once the
    book was full — a steady-state lockout where the realized book stayed
    rank-worse than the target indefinitely. Contesting entries and trimmable
    orphans in one ranked allocation closes that: a vacated orphan slot goes to
    the best deferred entry, and the orphan it displaced is credited as exit
    proceeds for the cash gate. Mandatory holds and data-gap orphans are still
    never force-sold, so a within-cap book with no better entries is untouched.
    """
    exited = {d.ticker for d in decisions.values() if d.action == "exit"}
    held_remaining = [t for t in live_positions if t not in exited]

    def _trimmable(t: str) -> bool:
        d = decisions.get(t)
        return (
            d is not None
            and t not in target_portfolio
            and d.action in ("hold", "at_risk")
            and d.rank < 9999
        )

    mandatory = [t for t in held_remaining if not _trimmable(t)]
    contenders = sorted(
        [d for d in decisions.values() if d.action == "entry"]
        + [decisions[t] for t in held_remaining if _trimmable(t)],
        key=lambda d: d.rank,   # best (lowest rank number) first
    )

    slots = max(0, max_positions - len(mandatory))
    winners = {d.ticker for d in contenders[:slots]}

    for d in contenders:
        if d.ticker in winners:
            continue  # entry stays entry; orphan stays hold/at_risk
        if d.action == "entry":
            decisions[d.ticker] = replace(
                d, action="watch", current_weight=None,
                reason=(f"deferred — portfolio at capacity; out-ranked for the open "
                        f"slots (rank={d.rank}, max_positions={max_positions})"),
            )
        else:  # trimmable orphan displaced / over cap
            decisions[d.ticker] = replace(
                d, action="exit",
                reason=(f"rotated out — untargeted orphan (rank={d.rank}) displaced by "
                        f"higher-ranked entries / over max_positions={max_positions}"),
            )


def evaluate_all(
    universe: dict[str, list[RankObservation]],
    current_portfolio: dict[str, float],
    entry_rank: int,
    exit_rank: int,
    confirmation_days: int,
    max_positions: int,
    actual_weights: dict[str, float] | None = None,
    drift_threshold: float = 0.02,
) -> dict[str, DeltaDecision]:
    """
    Evaluate all tickers. Portfolio tickers absent from universe are held (not exited) —
    they await ranking data rather than being force-sold.
    Capacity is checked dynamically as entries are approved.
    """
    # Pre-compute exits so capacity projection is correct before iterating entries
    pending_exits = sum(
        1 for ticker, obs in universe.items()
        if ticker in current_portfolio
        and _consecutive_in_zone(
            obs, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
        ) >= confirmation_days
    )
    # Tickers held but missing from universe → hold (not force-exit).
    # Could be a data gap rather than a true delisting. Delisted positions are handled
    # by Alpaca automatically; we hold until ranking data is available.
    missing_from_universe = [t for t in current_portfolio if t not in universe]
    # Do not add missing_from_universe to pending_exits — they stay in portfolio count

    projected_base = len(current_portfolio) - pending_exits
    decisions: dict[str, DeltaDecision] = {}

    confirmed_entries_so_far = 0
    for ticker, obs in universe.items():
        at_capacity = (projected_base + confirmed_entries_so_far) >= max_positions
        dec = evaluate_ticker(
            ticker=ticker,
            observations=obs,
            current_weight=current_portfolio.get(ticker),
            entry_rank=entry_rank,
            exit_rank=exit_rank,
            confirmation_days=confirmation_days,
            portfolio_at_capacity=at_capacity,
            actual_weight=actual_weights.get(ticker) if actual_weights else None,
            drift_threshold=drift_threshold,
        )
        decisions[ticker] = dec
        if dec.action == "entry":
            confirmed_entries_so_far += 1

    for ticker in missing_from_universe:
        decisions[ticker] = DeltaDecision(
            ticker=ticker, action="hold",
            rank=9999, composite_score=0.0,
            confirmation_days_met=0,
            current_weight=current_portfolio[ticker],
            reason=(
                "Held in portfolio but absent from ranking universe — "
                "awaiting price/fundamentals data from av-ingestor"
            ),
            actual_weight=actual_weights.get(ticker) if actual_weights else None,
            weight_drift=None,
        )

    return decisions
