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

    # Gate entries by capacity and buying power, demoting overflow to "watch".
    _cap_entries(
        decisions, live_positions, max_positions,
        actual_weights=actual_weights,
        account_value=account_value, buying_power=buying_power,
    )

    # Walk an over-capacity book back down to the cap by exiting excess orphans.
    _trim_to_cap(decisions, live_positions, target_portfolio, max_positions)

    return decisions


def _cap_entries(
    decisions: dict[str, DeltaDecision],
    live_positions: set[str],
    max_positions: int,
    *,
    actual_weights: dict[str, float] | None = None,
    account_value: float | None = None,
    buying_power: float | None = None,
) -> None:
    """Demote `entry` decisions to `watch` when they would breach the portfolio's
    position cap or available buying power. Mutates ``decisions`` in place.

    Why this exists
    ---------------
    `evaluate_target_vs_live` emits an `entry` for every target ticker not held,
    with no cap. Combined with the buffer-zone logic that *retains* held names not
    in the new target (orphan holds, never exited unless rank>exit_rank is confirmed),
    a rotation produced (a) >max_positions realized positions and (b) a wall of buys
    with no offsetting sells that blew past buying power. Both were confirmed live.

    Two caps, best-ranked entries kept first:
      - capacity:     retained_held + kept_entries <= max_positions, where
                      retained_held = len(live_positions) - confirmed_exits.
      - buying power: cumulative kept-entry weight <= buying_power/account_value
                      + proceeds freed by confirmed exits (in weight space). Only
                      enforced when account_value (>0) and buying_power are supplied;
                      otherwise the executor/risk-service remain the cash backstop.

    Exit proceeds are credited so a normal matched rotation (one name exits, one
    enters) still funds the entry even at ~0 buying power — only naked, unfunded
    buys are deferred.
    """
    entries = sorted(
        (d for d in decisions.values() if d.action == "entry"),
        key=lambda d: d.rank,
    )
    if not entries:
        return

    num_exits = sum(1 for d in decisions.values() if d.action == "exit")
    retained = len(live_positions) - num_exits
    slots = max_positions - retained

    cap_cash = account_value is not None and account_value > 0 and buying_power is not None
    avail_w = 0.0
    if cap_cash:
        exit_proceeds_w = 0.0
        if actual_weights:
            exit_proceeds_w = sum(
                (actual_weights.get(d.ticker) or 0.0)
                for d in decisions.values()
                if d.action == "exit"
            )
        avail_w = max(0.0, buying_power) / account_value + exit_proceeds_w

    cum_w = 0.0
    kept = 0
    EPS = 1e-9
    for d in entries:
        # NaN-safe weight (a corrupt target weight should not silently pass the gate).
        w = d.current_weight if (d.current_weight is not None and d.current_weight == d.current_weight) else 0.0
        fits_count = kept < slots
        fits_cash = (not cap_cash) or (cum_w + w <= avail_w + EPS)
        if fits_count and fits_cash:
            kept += 1
            cum_w += w
            continue

        reasons = []
        if not fits_count:
            reasons.append(
                f"deferred — portfolio at capacity ({retained} retained + {kept} "
                f"entries ≥ max_positions={max_positions})"
            )
        if cap_cash and not fits_cash:
            reasons.append(
                f"deferred — insufficient buying power (this {w:.2%} entry would take "
                f"cumulative entries to {cum_w + w:.2%} > available {avail_w:.2%} of equity)"
            )
        decisions[d.ticker] = replace(
            d, action="watch", current_weight=None, reason="; ".join(reasons),
        )


def _trim_to_cap(
    decisions: dict[str, DeltaDecision],
    live_positions: set[str],
    target_portfolio: dict[str, float],
    max_positions: int,
) -> None:
    """Exit excess **orphans** when the retained book exceeds max_positions. Mutates
    ``decisions`` in place.

    Why this exists
    ---------------
    The buffer-zone exit is rank-based: a held name only exits once rank > exit_rank
    is confirmed. A *well-ranked* orphan (held but covariance-excluded from the
    target) therefore never exits on its own, so the realized book can sit
    permanently above max_positions. Trim-to-cap closes that gap.

    Rules:
      - Fires only when retained + kept-entries > max_positions, so a within-cap
        book is untouched (no churn).
      - Only orphans (held AND not in target_portfolio) are eligible — a name the
        builder still targets is never force-sold here. This is always sufficient,
        since in-target holds <= target_size <= max_positions.
      - Worst-ranked orphans go first (highest rank number), so the best names
        survive and the weakest excess positions are shed.
    """
    exits_now = sum(1 for d in decisions.values() if d.action == "exit")
    entries_now = sum(1 for d in decisions.values() if d.action == "entry")
    retained = len(live_positions) - exits_now
    overflow = retained + entries_now - max_positions
    if overflow <= 0:
        return

    orphans = sorted(
        (
            d for d in decisions.values()
            if d.ticker in live_positions
            and d.ticker not in target_portfolio
            and d.action in ("hold", "at_risk")
            and d.rank < 9999   # never force-exit a position that's only missing
                                # from the ranking universe (data gap, not a sell signal)
        ),
        key=lambda d: -d.rank,   # worst (highest rank number) first
    )
    for d in orphans[:overflow]:
        decisions[d.ticker] = replace(
            d, action="exit",
            reason=(
                f"trim to cap — held book ({retained}) exceeds max_positions="
                f"{max_positions}; exiting untargeted orphan (rank={d.rank})"
            ),
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
