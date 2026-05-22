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
    action: str          # 'entry' | 'exit' | 'hold' | 'watch'
    rank: int
    composite_score: float
    confirmation_days_met: int
    current_weight: Optional[float]  # None when not in portfolio
    reason: str


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
        )

    latest = observations[0]
    entry_days = _consecutive_in_zone(
        observations, lambda o, er=entry_rank: o.rank <= er, confirmation_days
    )
    exit_days = _consecutive_in_zone(
        observations, lambda o, xr=exit_rank: o.rank > xr, confirmation_days
    )

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
        action = "exit"
        reason = f"Rank={latest.rank} > exit_rank={exit_rank} for {exit_days} consecutive days"
    elif held:
        zone = "entry zone" if latest.rank <= entry_rank else "buffer zone"
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
    )


def evaluate_target_vs_live(
    target_portfolio: dict[str, float],
    live_positions: set[str],
    universe: dict[str, list[RankObservation]],
    entry_rank: int,
    exit_rank: int,
    confirmation_days: int,
    max_positions: int,
) -> dict[str, DeltaDecision]:
    """Diff portfolio_holdings (target) against live_positions (actual broker state).

    entry  — ticker in target but not yet held at broker; current_weight = target weight
             (trade-executor uses this for order sizing — floor(account_value × weight / price))
    exit   — ticker held at broker but removed from target portfolio
    hold   — ticker in both target and broker positions
    watch  — confirmed in entry zone (confirmation_days) but not yet in target;
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
            )
        else:
            # Still in buffer zone — hold rather than force exit
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
            )

    # Holds: in both target and broker positions
    for ticker in live_positions:
        if ticker not in target_portfolio:
            continue
        weight = target_portfolio[ticker]
        obs = universe.get(ticker, [])
        latest = obs[0] if obs else None
        decisions[ticker] = DeltaDecision(
            ticker=ticker,
            action="hold",
            rank=latest.rank if latest else 9999,
            composite_score=latest.composite_score if latest else 0.0,
            confirmation_days_met=0,
            current_weight=weight,
            reason=f"Held at broker and in target portfolio (target weight={weight:.2%})",
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
            )

    return decisions


def evaluate_all(
    universe: dict[str, list[RankObservation]],
    current_portfolio: dict[str, float],
    entry_rank: int,
    exit_rank: int,
    confirmation_days: int,
    max_positions: int,
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
        )

    return decisions
