"""
Pure-Python buffer-zone delta engine.

Evaluates which tickers should enter or exit the portfolio based on
consecutive-day confirmation in the entry/exit rank zones.
All functions are stateless and fully deterministic.
"""
from dataclasses import dataclass, replace
from datetime import date
from typing import Optional

from stock_strategy_shared.investability import below_investability_floor


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


def _orphan_confirm_days(
    ticker: str,
    target_history: list[set[str]] | None,
    required: int,
) -> int:
    """Count consecutive most-recent portfolio builds in which ``ticker`` was
    ABSENT from the target (i.e. an orphan).

    ``target_history`` is most-recent-first; element 0 is the current build's
    target ticker set. A name that is an orphan today contributes at least 1.
    Only the leading ``required`` builds are examined. When history is None or
    shorter than ``required``, the maximum achievable count is bounded by the
    history length, so an orphan cannot reach confirmation until enough builds
    have accumulated — deliberately conservative (no whipsaw on thin history).
    """
    if not target_history:
        return 0
    count = 0
    for tset in target_history[:required]:
        if ticker not in tset:
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


def below_floor_unranked(
    price_rows: dict[str, tuple[Optional[float], Optional[date], Optional[float]]],
    *,
    min_price: float,
    min_avg_dollar_volume: float,
    ref_date: date,
    stale_days: int = 7,
) -> set[str]:
    """Held+unranked tickers that fall BELOW the strategy investability floor and
    therefore must orphan-EXIT (not data-gap-hold).

    price_rows maps ticker → (last_adjusted_close, last_date, avg_dollar_volume_20d).
    A ticker qualifies iff:
      - it has a FRESH price (last_date within `stale_days` of ref_date) — a stale /
        missing price is a genuine data gap and stays HELD (never force-sell a name
        we can't currently price), AND
      - it FAILS the floor: price < min_price OR avg_dollar_volume < min_avg_dollar_volume
        — the SAME test the factor step applies to build the investable universe.

    A fresh name that MEETS the floor but is still unranked (e.g. a transiently NULL
    required factor) is deliberately EXCLUDED here → it stays held, so a temporary
    fundamentals/factor gap never force-exits a legit holding. Pure / deterministic;
    mirrors the factor-step filter so "below floor" means the same on both sides.
    """
    out: set[str] = set()
    for ticker, (last_px, last_date, avg_dv) in price_rows.items():
        if last_date is None or (ref_date - last_date).days > stale_days:
            continue  # no fresh price → genuine data gap → hold
        # SHARED floor test (same one the factor universe filter and the builder use).
        if below_investability_floor(last_px, avg_dv, min_price=min_price,
                                     min_avg_dollar_volume=min_avg_dollar_volume):
            out.add(ticker)
    return out


def evaluate_target_vs_live(
    target_portfolio: dict[str, float],
    live_positions: set[str],
    universe: dict[str, list[RankObservation]],
    confirmation_days: int,
    max_positions: int,
    actual_weights: dict[str, float] | None = None,
    drift_threshold: float = 0.02,
    account_value: float | None = None,
    buying_power: float | None = None,
    target_history: list[set[str]] | None = None,
    orphan_confirmation_days: int | None = None,
    dedup_survivors: dict[str, str] | None = None,
    cash_fraction: float | None = None,
    unranked_below_floor: set[str] | None = None,
) -> dict[str, DeltaDecision]:
    """Diff portfolio_holdings (target) against live_positions (actual broker state).

    The portfolio-builder is the SOURCE OF TRUTH for which names belong in the
    book. This function does NOT apply any rank-based entry/exit buffer to the
    live book: a held name that is in the target is HELD (rank is irrelevant — the
    builder already decided to keep it), and a held name the builder DROPPED from
    the target is exited via the orphan timer (orphan_confirmation_days). Entries
    come from target membership. (Rank-based entry/exit hysteresis is retired here;
    it survives only in the cold-start fallback evaluate_all, which has no target
    to diff against.)

    entry     — ticker in target but not yet held at broker; current_weight = target weight
                (trade-executor uses this for order sizing — floor(account_value × weight / price))
    exit      — ticker held at broker but removed from target (orphan, confirmed over builds)
    at_risk   — ticker held at broker, dropped from target, orphan timer counting down
    hold      — ticker in both target and broker positions, on target weight
    buy_add   — ticker held and in target, actual weight < target - drift_threshold
    sell_trim — ticker held and in target, actual weight > target + drift_threshold
    watch     — an entry deferred by capacity / buying power (not a rank signal)

    dedup_survivors maps a held broker ticker that was SUPPRESSED by share-class
    dedup (it lost to a higher-ranked sibling, so it has no ranking row → no
    `universe` obs) to its surviving sibling ticker. This distinguishes a
    deliberately-suppressed dedup loser from a GENUINE data gap (no ranking AND
    not a dedup loser). For a dedup loser:
      - survivor IS in the target  → treat the held loser as in-target (HOLD —
        same company, the builder kept the class). It NEVER consumes a phantom
        slot via the data-gap exemption.
      - survivor NOT in target     → route the held loser through the NORMAL
        orphan path (orphan-exits after orphan_confirmation_days), borrowing the
        survivor's rank obs for reporting, instead of holding forever.
    Genuine data-gap names (not in dedup_survivors) keep the data-gap exemption.

    cash_fraction — the portfolio-builder's ``cash_reserve``. When the builder
    holds back a cash buffer it scales every persisted target weight DOWN by
    ``(1 - cash_reserve)`` (e.g. a fully-invested book's targets sum to ~0.975 at
    cash_reserve=0.025). But the actual broker weights here are computed as
    ``market_value / account_value`` and, for a fully-invested book, sum to ~1.0.
    Diffing those two directly would read every held name as structurally
    overweight by ~cash_reserve/N — a uniform positive drift bias that, once it
    crosses ``drift_threshold`` (raise cash_reserve or concentrate the book),
    fires phantom ``sell_trim`` intents every run that bleed the book toward cash.
    To put actual and target on the SAME basis for the drift COMPARISON ONLY, we
    scale the comparison target UP by ``1 / (1 - cash_fraction)`` so it sums to 1
    like the actual weights. The PERSISTED target weight (``current_weight``,
    which the trade-executor sizes orders against) is left untouched — only the
    drift number and the buy_add/sell_trim/hold classification change. None or 0
    ⇒ no rescale (back-compat: every existing caller / test is byte-for-byte
    unaffected).
    """
    decisions: dict[str, DeltaDecision] = {}
    dedup_survivors = dedup_survivors or {}
    # Held names that are unranked but fall BELOW the strategy's investability floor
    # (price < min_price OR avg_dollar_volume < min_avg_dollar_volume_20d) — i.e. the
    # SAME reason the factor step drops them from the universe. They trade (fresh
    # price) but the strategy no longer wants them (typically after a config/strategy
    # switch), so they must ORPHAN-EXIT, not get the never-force-sell data-gap hold
    # (which would strand them forever and burn a slot — breaking unattended
    # operation). Computed precisely by the pipeline via `below_floor_unranked()`.
    # NOT in this set (→ still held): genuine no-price data gaps, AND fresh names that
    # MEET the floor but are unranked for a transient factor/data reason (a null
    # required factor) — exiting those would be a false-exit of a legit holding.
    unranked_below_floor = unranked_below_floor or set()

    # Drift-comparison basis fix: gross the target back up to the sum-to-1 basis
    # the actual broker weights live on, so the cash_reserve hold-back is not
    # misread as a universal overweight. Comparison-only — current_weight stays
    # the persisted (cash-scaled) target the executor sizes against. Guard the
    # divisor: cash_fraction is validated in [0,1) upstream (PortfolioBuilderConfig),
    # but be defensive against an out-of-range value reaching here.
    _cf = cash_fraction if (cash_fraction is not None and cash_fraction == cash_fraction) else 0.0
    drift_basis = (1.0 - _cf) if (0.0 < _cf < 1.0) else 1.0

    def _drift(actual_w: Optional[float], target_w: float) -> Optional[float]:
        """actual − (target grossed up to the invested basis). drift_basis==1.0
        (no cash reserve) reduces to the plain actual − target diff."""
        if actual_w is None:
            return None
        return actual_w - (target_w / drift_basis)

    # Orphan exits confirm over their OWN window, separate from the rank-based
    # entry/exit buffer (confirmation_days). Defaults to confirmation_days when not
    # supplied so callers that don't set it keep the old behavior. A held name
    # dropped from the target is flagged at_risk on its first orphaned build and
    # exits once it has been absent for orphan_confirmation_days consecutive builds
    # (default 2: flagged build 1, sold build 2).
    orphan_conf = orphan_confirmation_days if orphan_confirmation_days is not None else confirmation_days

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

    # Exits: broker holds but target no longer includes (ORPHANS).
    #
    # The portfolio-builder may drop a well-ranked ticker for covariance /
    # capacity reasons (e.g. already holds 3 correlated names in the same
    # cluster). Rank is irrelevant here: the builder is the source of truth, and a
    # name it dropped is an orphan. To avoid churn we don't snap-sell — the orphan
    # exits only once it has been ABSENT from the target for orphan_confirmation_days
    # consecutive builds (target_history). A single build that re-includes it resets
    # the count.
    #
    # Degraded case: if target_portfolio is completely empty (builder failed
    # transiently or filtered all candidates), HOLD every position — an empty target
    # is "no information", never a liquidation signal.
    target_is_empty = not target_portfolio
    for ticker in live_positions:
        if ticker in target_portfolio:
            continue  # handled in holds below
        obs = universe.get(ticker, [])
        latest = obs[0] if obs else None
        survivor = dedup_survivors.get(ticker)
        forced_orphan = False
        if not obs and survivor is not None:
            # This held position is a share-class dedup LOSER: it was suppressed
            # from the rankings in favour of a higher-ranked sibling, so it has
            # no ranking obs. This is NOT a data gap — do not grant the data-gap
            # hold exemption (which would strand it forever AND burn a slot).
            if survivor in target_portfolio:
                # Survivor (same company) is in the target → the company IS
                # wanted; hold the class we actually own. Counts as occupied, but
                # legitimately so (it's a real in-target holding, not a phantom).
                decisions[ticker] = DeltaDecision(
                    ticker=ticker,
                    action="hold",
                    rank=9999,
                    composite_score=0.0,
                    confirmation_days_met=0,
                    current_weight=0.0,
                    reason=(
                        f"Held at broker; share-class dedup loser whose survivor "
                        f"{survivor} is in target — holding (same company)"
                    ),
                    actual_weight=actual_weights.get(ticker) if actual_weights else None,
                    weight_drift=None,
                )
                continue
            # Survivor NOT in target → the company was dropped by the builder.
            # Route through the NORMAL orphan path so the held loser orphan-exits
            # after orphan_confirmation_days. Borrow the survivor's obs (if any)
            # purely for rank/score reporting; the orphan logic below is identical.
            # `forced_orphan` keeps it out of the genuine-data-gap hold even when
            # the survivor itself has no obs (then it orphan-exits as rank 9999).
            forced_orphan = True
            obs = universe.get(survivor, [])
            latest = obs[0] if obs else RankObservation(
                run_date=date.min, rank=9999, composite_score=0.0,
            )
        if not obs and not forced_orphan and ticker in unranked_below_floor and not target_is_empty:
            # Held name with NO ranking obs that falls BELOW the investability floor
            # (price/liquidity) — the same reason the factor step excluded it. It
            # trades, the strategy just no longer wants it (typically after a
            # config/strategy switch). This is NOT a data gap, so it must NOT get the
            # never-force-sell exemption (which would strand it forever and burn a
            # slot). Route it through the orphan-exit timer so a strategy switch
            # self-cleans unattended. rank=9999 here means "below universe / unranked",
            # not "missing data".
            orphan_days = _orphan_confirm_days(ticker, target_history, orphan_conf) or 1
            if orphan_days >= orphan_conf:
                pnr_action, pnr_reason = "exit", (
                    f"Held at broker, below strategy universe floor (unranked but "
                    f"trades) for {orphan_days} consecutive builds — exiting "
                    f"(target is binding)"
                )
            else:
                pnr_action, pnr_reason = "at_risk", (
                    f"Held at broker, below strategy universe floor (unranked but "
                    f"trades) — orphaned for {orphan_days}/{orphan_conf} builds toward exit"
                )
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action=pnr_action,
                rank=9999,
                composite_score=0.0,
                confirmation_days_met=orphan_days,
                current_weight=0.0,
                reason=pnr_reason,
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
            continue

        if not obs and not forced_orphan:
            # No ranking history, not a dedup loser, and NO recent price data — a
            # GENUINE data gap (av-ingestor hasn't fetched yet, a position added
            # directly at the broker, or a delisted name with no market). Hold
            # rather than force-exit: a missing-data name is not a sell signal, and
            # we won't try to trade a name with no price. The next pipeline run
            # reconsiders once ranking/price data is available.
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="hold",
                rank=9999,
                composite_score=0.0,
                confirmation_days_met=0,
                current_weight=0.0,
                reason=(
                    "Held at broker but absent from ranking universe with no recent "
                    "price data — awaiting price/fundamentals data from av-ingestor"
                ),
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
            continue

        if target_is_empty:
            # Degraded mode: the builder produced an EMPTY target this build
            # (transient failure or all candidates filtered). The builder is the
            # source of truth, so an empty target is treated as "no information",
            # NOT "sell everything": hold every live position until a non-empty
            # target appears. No rank is consulted (the rank buffer is retired).
            decisions[ticker] = DeltaDecision(
                ticker=ticker,
                action="hold",
                rank=latest.rank,
                composite_score=latest.composite_score,
                confirmation_days_met=0,
                current_weight=0.0,
                reason=(
                    f"Held at broker; target portfolio empty (degraded build) — "
                    f"holding pending a non-empty target"
                ),
                actual_weight=actual_weights.get(ticker) if actual_weights else None,
                weight_drift=None,
            )
            continue

        # Has ranking data, non-empty target, ticker not in target → ORPHAN.
        #
        # The target is binding on the live book: a position the builder dropped
        # is exited once it has been absent from the target for confirmation_days
        # consecutive builds, REGARDLESS of rank. This is what makes a strategy
        # change (e.g. the correlation-cluster cap thinning the golds) actually
        # reach the realized portfolio — a well-ranked name the builder no longer
        # wants no longer lingers indefinitely just because its rank holds up.
        #
        # Deterministic, no whipsaw: the confirmation window is counted over
        # successive portfolio builds (target_history, most-recent-first). A single
        # build that re-includes the ticker resets the count. Data-gap orphans
        # (no ranking obs) are handled above and never reach here, so they are
        # never force-sold on missing data.
        orphan_days = _orphan_confirm_days(ticker, target_history, orphan_conf)
        # Fall back to today-only when no build history is available yet: an orphan
        # today counts as 1 (cannot confirm until orphan_conf builds exist).
        if orphan_days == 0:
            orphan_days = 1
        if orphan_days >= orphan_conf:
            orphan_action = "exit"
            orphan_reason = (
                f"Held at broker, dropped from target for {orphan_days} consecutive "
                f"builds (rank={latest.rank}) — exiting (target is binding)"
            )
        else:
            orphan_action = "at_risk"
            orphan_reason = (
                f"Held at broker, not in target portfolio (rank={latest.rank}) — "
                f"orphaned for {orphan_days}/{orphan_conf} builds toward exit"
            )
        decisions[ticker] = DeltaDecision(
            ticker=ticker,
            action=orphan_action,
            rank=latest.rank,
            composite_score=latest.composite_score,
            confirmation_days_met=orphan_days,
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
        # Drift on a common basis: gross the (cash-scaled) target up to the
        # sum-to-1 basis the broker weights live on (drift_basis), so the cash
        # reserve is not misread as a universal overweight (phantom sell_trims).
        drift = _drift(actual_w, target_weight)
        current_rank = latest.rank if latest else 9999

        # The builder is the source of truth: a held name that is IN the target is
        # held, regardless of rank. No rank-based exit / at_risk here — exits flow
        # only from the orphan path (builder dropped the name). The only action layered
        # on a hold is a weight-drift rebalance, and only when there is a real positive
        # target weight (reject the 0.0 cold-start sentinel, negatives, and NaN).
        has_real_target = (
            target_weight is not None
            and target_weight > 0
            and target_weight == target_weight  # NaN-safe
        )
        if has_real_target and drift is not None and abs(drift) > drift_threshold:
            if drift < 0:
                action = "buy_add"
            else:
                action = "sell_trim"
        else:
            action = "hold"

        # Build reason. When a cash reserve grosses the comparison basis up, show
        # the grossed-up target so actual − target visibly equals the drift.
        cmp_target = target_weight / drift_basis
        if action == "buy_add":
            reason = (
                f"Held and in target (rank={current_rank}), underweight: "
                f"actual={actual_w:.2%} target={cmp_target:.2%} "
                f"drift={drift:+.2%}"
            )
        elif action == "sell_trim":
            reason = (
                f"Held and in target (rank={current_rank}), overweight: "
                f"actual={actual_w:.2%} target={cmp_target:.2%} "
                f"drift={drift:+.2%}"
            )
        else:
            reason = f"Held at broker and in target portfolio (target weight={target_weight:.2%})"

        decisions[ticker] = DeltaDecision(
            ticker=ticker,
            action=action,
            rank=current_rank,
            composite_score=latest.composite_score if latest else 0.0,
            confirmation_days_met=0,
            current_weight=target_weight,
            reason=reason,
            actual_weight=actual_w,
            weight_drift=drift,
        )

    # (No rank-based "watch" generation: a name not in the target is simply not
    # acted on — the builder owns membership. "watch" now arises only from capacity
    # / buying-power deferral of an entry, below.)

    # Capacity: defer entries that don't fit the position book (never force-exits a
    # held position — orphans leave only via the time-based orphan path).
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
    """Defer new entries that don't fit the position book (max_positions slots).
    Mutates ``decisions`` in place. Capacity only — the cash gate runs after, in
    _cap_buys.

    Slot accounting:
      - Occupied slots = every held name NOT already exiting this run (in-target
        holds, buy_adds, at_risk orphans counting down, data-gap orphans) PLUS any
        orphan confirmed-exiting (those free their slot and are excluded).
      - Free slots = max_positions − occupied. New entries fill free slots best
        rank first; entries that don't fit are demoted to ``watch``.

    Why instant rotation was retired
    --------------------------------
    Previously a higher-ranked new entry could rotate a weaker orphan out
    immediately ("always rotate"). That reintroduced rank-driven churn and raced
    the orphan-exit timer. The orphan-exit path is now solely time-based: an
    orphan leaves only after confirmation_days consecutive builds absent from the
    target (see evaluate_target_vs_live). So capacity here NEVER force-exits a
    held position — it only defers entries that can't fit. When the book is full
    of not-yet-confirmed orphans, a better entry waits (``watch``) until an orphan
    times out and frees its slot. Deterministic, no whipsaw — the trade-off is
    higher latency to rank-align the book, accepted per the orphan-exit redesign.
    """
    exiting = {d.ticker for d in decisions.values() if d.action == "exit"}
    occupied = len([t for t in live_positions if t not in exiting])

    free_slots = max(0, max_positions - occupied)
    entries = sorted(
        [d for d in decisions.values() if d.action == "entry"],
        key=lambda d: d.rank,   # best (lowest rank number) first
    )
    winners = {d.ticker for d in entries[:free_slots]}

    for d in entries:
        if d.ticker in winners:
            continue  # entry fits a free slot
        decisions[d.ticker] = replace(
            d, action="watch", current_weight=None,
            reason=(f"deferred — portfolio at capacity; out-ranked for the open "
                    f"slots (rank={d.rank}, max_positions={max_positions})"),
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
