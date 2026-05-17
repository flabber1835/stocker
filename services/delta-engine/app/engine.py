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
    """Count consecutive leading observations (most-recent first) satisfying predicate."""
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


def evaluate_all(
    universe: dict[str, list[RankObservation]],
    current_portfolio: dict[str, float],
    entry_rank: int,
    exit_rank: int,
    confirmation_days: int,
    max_positions: int,
) -> dict[str, DeltaDecision]:
    """
    Evaluate all tickers. Portfolio tickers absent from universe are force-exited.
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
    # Tickers held but missing from universe are force-exited (delisted)
    missing_from_universe = [t for t in current_portfolio if t not in universe]
    pending_exits += len(missing_from_universe)

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
            ticker=ticker, action="exit",
            rank=9999, composite_score=0.0,
            confirmation_days_met=confirmation_days,
            current_weight=current_portfolio[ticker],
            reason="Ticker missing from ranking universe — likely delisted or removed",
        )

    return decisions
