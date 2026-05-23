"""
Pure-Python buffer-zone delta engine.

Evaluates which tickers should enter or exit the portfolio based on
consecutive-day confirmation in the entry/exit rank zones.
All functions are stateless and fully deterministic.
"""
from dataclasses import dataclass
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
        if drift is not None and abs(drift) > drift_threshold:
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

    # Exits: broker holds but target no longer includes — only exit if rank has been
    # outside the buffer zone for confirmation_days; otherwise hold (buffer-zone logic).
    for ticker in live_positions:
        if ticker in target_portfolio:
            continue  # handled in holds below
        obs = universe.get(ticker, [])
        latest = obs[0] if obs else None
        if not obs:
            # No ranking history for this broker position — hold rather than force-exit.
            # Could be a data gap (av-ingestor hasn't fetched this ticker yet) or a new
            # position added directly at the broker. Delisted positions are handled by
            # Alpaca automatically; the next alpaca-sync will reflect their actual state.
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
        exit_days = _consecutive_in_zone(
            obs, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
        )
        if exit_days >= confirmation_days:
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="exit",
                rank=latest.rank,
                composite_score=latest.composite_score,
                confirmation_days_met=exit_days,
                current_weight=0.0,
                reason=(
                    f"Rank={latest.rank} > exit_rank={exit_rank} for {exit_days} consecutive days"
                    f" (not in target portfolio)"
                ),
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
        elif latest.rank > exit_rank:
            # Rank above exit_rank but not confirmed — at_risk
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="at_risk",
                rank=latest.rank,
                composite_score=latest.composite_score,
                confirmation_days_met=exit_days,
                current_weight=0.0,
                reason=(
                    f"Held at broker, not in target portfolio, rank={latest.rank} > exit_rank={exit_rank}"
                    f" ({exit_days}/{confirmation_days}d toward exit confirmation)"
                ),
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
        else:
            # Still in buffer zone (rank ≤ exit_rank) — hold rather than force exit
            zone = "entry zone" if latest.rank <= entry_rank else "buffer zone"
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="hold",
                rank=latest.rank,
                composite_score=latest.composite_score,
                confirmation_days_met=exit_days,
                current_weight=0.0,
                reason=(
                    f"Held at broker, not in target portfolio, but rank={latest.rank} in {zone}"
                    f" (exit needs {confirmation_days}d > {exit_rank}, have {exit_days}d)"
                ),
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

        # Layer drift on top only when rank-based action is "hold"
        if rank_action == "hold" and drift is not None and abs(drift) > drift_threshold:
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

    return decisions


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

    for ticker, obs in universe.items():
        confirmed_entries_so_far = sum(1 for d in decisions.values() if d.action == "entry")
        at_capacity = (projected_base + confirmed_entries_so_far) >= max_positions
        decisions[ticker] = evaluate_ticker(
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
