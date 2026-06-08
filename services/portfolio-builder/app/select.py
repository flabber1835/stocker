import numpy as np
import pandas as pd


def apply_theme_tilt(
    scores: dict[str, float],
    theme_members: dict[str, float],
    tilt_lambda: float,
) -> dict[str, float]:
    """Thematic TILT (pure). Multiply each theme member's composite score by
    (1 + tilt_lambda * exposure); non-members and missing exposures are unchanged.

    Leans selection toward theme names while preserving the quant ordering as the
    base signal — a member only out-ranks a non-member if the bounded boost closes
    the score gap. tilt_lambda <= 0 or empty membership → identity (no behavior
    change). Returns a NEW dict; never mutates the input. Unit-testable in isolation.
    """
    if tilt_lambda <= 0.0 or not theme_members:
        return dict(scores)
    out: dict[str, float] = {}
    for t, s in scores.items():
        ex = theme_members.get(t)
        out[t] = s * (1.0 + tilt_lambda * ex) if ex is not None else s
    return out


def restrict_to_theme(
    candidate_tickers: list[str],
    scores: dict[str, float],
    rank: dict[str, int],
    theme_members: dict[str, float],
) -> tuple[list[str], dict[str, float], dict[str, int]]:
    """Thematic RESTRICT (pure). Keep only theme-universe members, preserving order
    and their quant score/rank. Empty membership → empty result (caller must guard
    and fall back to no-theme rather than build an empty portfolio). Unit-testable.
    """
    keep = [t for t in candidate_tickers if t in theme_members]
    return (keep,
            {t: scores[t] for t in keep if t in scores},
            {t: rank[t] for t in keep if t in rank})


def compute_excluded_set(
    vetter_excluded: list[str],
    held_now: set[str],
    excluded_risk_type: dict[str, str],
) -> set[str]:
    """Held-aware vetter exclusion (source-of-truth / falling-knife-sells redesign).

    The LLM has no sell authority, so an LLM-judgement exclusion of a name we
    already HOLD stays buy-side only — it is NOT removed from the candidate pool
    (so it remains in the fresh target and is not orphan-exited). ONLY the
    deterministic falling-knife backstop (risk_type='drawdown') may drop a held
    name from the target, which the delta engine then orphan-exits. A non-held
    name is excluded on any reason (you simply don't buy a vetoed name).

    Pure function (no DB / no network) so the rule is unit-testable in isolation.
    """
    return {
        t for t in vetter_excluded
        if t not in held_now or excluded_risk_type.get(t) == "drawdown"
    }


def correlation_clusters(
    matrix: pd.DataFrame,
    threshold: float = 0.70,
) -> dict[str, str]:
    """
    Group tickers into correlation clusters.

    `matrix` is a Pearson CORRELATION matrix (NOT a covariance matrix). Pass the
    RAW correlation from build_covariance — never one derived from the shrunk
    covariance, which deflates every off-diagonal correlation by the shrinkage
    factor and would drop genuine co-movers below the threshold. (A correlation
    matrix has a unit diagonal, so dividing by sqrt(diag) here would be a no-op
    anyway; we use the off-diagonals directly.)

    Two tickers join the same cluster when their absolute correlation is
    >= threshold. Clustering is single-linkage via union-find: A~B and B~C puts
    A, B, C in one cluster even if |corr(A,C)| is below threshold (they co-move
    through B). This is the data-driven replacement for provider sector labels,
    which are unreliable for risk grouping (e.g. GOOG is "Communication Services";
    gold miners span several sectors).

    Returns a {ticker: cluster_id} map where cluster_id is the
    lexicographically-smallest ticker in the cluster (stable, deterministic).
    A ticker with no high-correlation peer maps to itself (singleton cluster).
    """
    tickers = list(matrix.index)
    if not tickers:
        return {}

    corr = matrix.values

    # Union-find with path compression.
    parent = {t: t for t in tickers}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # Attach the larger ticker's root under the smaller so the final root is
        # the lexicographically-smallest member (deterministic cluster_id).
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    n = len(tickers)
    for i in range(n):
        for j in range(i + 1, n):
            if abs(corr[i, j]) >= threshold:
                union(tickers[i], tickers[j])

    return {t: find(t) for t in tickers}


def greedy_select(
    scores: pd.Series,
    cov: pd.DataFrame,
    target: int = 30,
    sector_map: dict[str, str] | None = None,
    max_sector_weight: float = 1.0,
    current_holdings: set[str] | None = None,
    turnover_penalty: float = 0.0,
    max_tickers_per_sector: int | None = None,
    av_sector_map: dict[str, str] | None = None,
    max_av_sector_weight: float = 1.0,
) -> list[dict]:
    """
    Greedy portfolio construction: pick tickers that maximise
    candidate_score / hypothetical_portfolio_vol one at a time.

    Group cap (primary): when sector_map and max_sector_weight are provided, any
    candidate that would push a group past the cap under equal-weight assumptions
    is skipped. The builder passes the correlation-CLUSTER map here. The cap is a
    hard constraint during selection, not post-hoc.

    AV-sector cap (secondary, independent): when av_sector_map and
    max_av_sector_weight are provided, the SAME count-proxy cap is applied on the
    data-provider's sector label. This bounds a whole sector that is spread across
    several correlation clusters (e.g. energy = tankers + refiners + E&P), which
    the cluster cap alone cannot see. Both caps apply; either can block a pick.

    Count cap: when max_tickers_per_sector is set, a candidate is skipped once its
    cluster already has that many members selected — an absolute count cap
    independent of the weighting scheme and `target` (vs max_sector_weight's
    count/target weight proxy). Both caps apply; whichever binds first wins.

    Turnover penalty: when current_holdings and turnover_penalty > 0, candidates
    NOT in current_holdings have their adjusted score reduced by turnover_penalty
    fraction before the greedy selection loop. This gives continuity holdings a
    slight preference to reduce unnecessary churn on regime transitions.

    Two traps handled:
      1. Negative z-scores: shift all scores to be strictly positive before
         the loop so division never flips the sign of the ranking.
      2. Negative marginal vol: use total hypothetical portfolio vol (not the
         delta) as the denominator — adding a perfectly hedging asset would
         give negative marginal vol and flip a great diversifier to the bottom.
    """
    min_s = float(scores.min())
    base = (scores - min_s + 1.0) if min_s <= 0 else scores.copy()

    # Apply turnover penalty: discount new positions to prefer continuity holdings
    if current_holdings is not None and turnover_penalty > 0.0:
        base = base * pd.Series(
            {t: (1.0 if t in current_holdings else 1.0 - turnover_penalty)
             for t in base.index}
        )

    portfolio: list[str] = []
    sector_counts: dict[str, int] = {}
    av_sector_counts: dict[str, int] = {}
    available = list(base.index)
    result: list[dict] = []

    def _group_ok(candidate: str, gmap: dict[str, str] | None,
                  gcounts: dict[str, int], gmax: float,
                  gcount_cap: int | None) -> bool:
        if gmap is None:
            return True
        g = gmap.get(candidate)
        if not g:
            return True
        current = gcounts.get(g, 0)
        # Hard count cap: absolute, independent of weighting scheme and target.
        if gcount_cap is not None and current >= gcount_cap:
            return False
        # Weight-proxy cap: count/target as a proxy for weight. Use target as the
        # denominator so the cap is evaluated against the intended portfolio size,
        # not the current (growing) one (else "pick 2 from any group" fails early
        # at 1/2=50%). Tradeoff: if the final portfolio is smaller than target, the
        # actual group weight may exceed gmax — accepted, since the alternative is
        # failing to build a portfolio. compute_weights enforces the true weight cap.
        if gmax < 1.0:
            return (current + 1) / target <= gmax
        return True

    def _sector_ok(candidate: str) -> bool:
        # Primary grouping (cluster) carries the count cap; AV-sector is weight-only.
        return (
            _group_ok(candidate, sector_map, sector_counts, max_sector_weight, max_tickers_per_sector)
            and _group_ok(candidate, av_sector_map, av_sector_counts, max_av_sector_weight, None)
        )

    def _record_pick(candidate: str) -> None:
        if sector_map:
            s = sector_map.get(candidate)
            if s:
                sector_counts[s] = sector_counts.get(s, 0) + 1
        if av_sector_map:
            a = av_sector_map.get(candidate)
            if a:
                av_sector_counts[a] = av_sector_counts.get(a, 0) + 1

    # First pick: highest standalone score — no covariance context yet
    first_candidates = [t for t in base.sort_values(ascending=False).index
                        if _sector_ok(t)]
    if not first_candidates:
        return result
    first = first_candidates[0]

    standalone_var = max(float(cov.loc[first, first]), 1e-12)
    standalone_vol = float(np.sqrt(standalone_var))
    portfolio.append(first)
    _record_pick(first)
    available.remove(first)
    result.append({
        "ticker": first,
        "position": 1,
        "composite_score": float(scores[first]),
        "adj_score": float(base[first]) / standalone_vol,
        "portfolio_vol_at_add": standalone_vol,
    })

    while len(portfolio) < target and available:
        best_adj = -np.inf
        best_candidate: str | None = None
        best_vol: float = 0.0
        n = len(portfolio) + 1
        # Equal-weight assumption during selection: using actual weights here would
        # require re-solving the weighting problem for every candidate on every step,
        # which makes selection order depend on the weighting method. Equal weight
        # is a consistent and fast proxy; the final portfolio vol is recomputed from
        # actual weights in main.py after selection.
        w = np.ones(n) / n

        for candidate in available:
            if not _sector_ok(candidate):
                continue
            test = portfolio + [candidate]
            sub = cov.loc[test, test].values
            port_vol = float(np.sqrt(max(float(w @ sub @ w), 1e-12)))
            adj = float(base[candidate]) / port_vol
            if adj > best_adj:
                best_adj = adj
                best_candidate = candidate
                best_vol = port_vol

        if best_candidate is None:
            break

        portfolio.append(best_candidate)
        _record_pick(best_candidate)
        available.remove(best_candidate)
        result.append({
            "ticker": best_candidate,
            "position": len(portfolio),
            "composite_score": float(scores[best_candidate]),
            "adj_score": best_adj,
            "portfolio_vol_at_add": best_vol,
        })

    return result


def build_covariance(
    prices_df: pd.DataFrame,
    window_days: int,
    min_observations: int = 126,
    shrinkage: float = 0.20,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Build an annualised daily-return covariance matrix from a long-format
    price DataFrame with columns [ticker, date, adjusted_close].

    Tickers with fewer than min_observations non-NaN return observations are
    dropped (returned as the second element of the tuple so callers can log them).

    Ledoit-Wolf-style shrinkage blends the sample covariance with its diagonal:
        shrunk = (1 - shrinkage) * sample_cov + shrinkage * diag(sample_variances)
    This reduces estimation error without requiring a full optimizer.

    NaN covariances (ticker pairs with no overlapping history) are filled
    with 0 (zero-correlation assumption). Zero or negative variances on the
    diagonal are replaced with the ticker's empirical variance or a small
    floor so the greedy loop never divides by zero.

    Returns (cov_matrix, tickers_dropped_insufficient_obs).
    """
    # Deduplicate (date, ticker) pairs before pivoting — keep the last ingested
    # row so duplicate prices surface as an explicit choice rather than a silent
    # average (pivot_table would silently average duplicates).
    prices_df = prices_df.drop_duplicates(subset=["date", "ticker"], keep="last")
    pivot = prices_df.pivot(
        index="date", columns="ticker", values="adjusted_close"
    ).sort_index().astype(float)  # Decimal from DB → float64 before log returns

    if len(pivot) > window_days:
        pivot = pivot.iloc[-window_days:]

    log_returns = np.log(pivot / pivot.shift(1)).dropna(how="all")

    # Drop tickers that don't have enough observations for stable covariance estimates
    obs_counts = log_returns.count()
    valid = obs_counts[obs_counts >= min_observations].index.tolist()
    dropped = [t for t in log_returns.columns if t not in valid]
    log_returns = log_returns[valid]

    cov = log_returns.cov() * 252  # annualise daily covariance
    cov = cov.fillna(0.0)

    # Ensure positive diagonal (variance must be > 0)
    for t in cov.index:
        if cov.loc[t, t] <= 0:
            col = log_returns[t].dropna() if t in log_returns.columns else pd.Series(dtype=float)
            cov.loc[t, t] = float(col.var() * 252) if len(col) > 1 else 1e-6

    # Raw (pre-shrinkage) Pearson correlation — derived from the SAMPLE covariance
    # before shrinkage. Shrinkage toward the diagonal scales off-diagonal
    # covariances by (1 - shrinkage) but leaves the diagonal (variances) full-size,
    # so deriving correlation from the shrunk matrix deflates every pairwise
    # correlation by the shrinkage factor (e.g. a true 0.86 reads 0.69 at
    # shrinkage=0.20) — which wrongly drops genuine co-movers below the clustering
    # threshold. The correlation cluster step must use THIS matrix, not the shrunk
    # cov. (Shrinkage stays applied to the cov returned for the optimizer.)
    _std = np.sqrt(np.clip(np.diag(cov.values), 1e-18, None))
    corr = pd.DataFrame(
        cov.values / np.outer(_std, _std),
        index=cov.index, columns=cov.columns,
    )

    # Ledoit-Wolf-style shrinkage toward the diagonal (optimizer stability only)
    if shrinkage > 0:
        diag_cov = pd.DataFrame(
            np.diag(np.diag(cov.values)),
            index=cov.index,
            columns=cov.columns,
        )
        cov = (1.0 - shrinkage) * cov + shrinkage * diag_cov

    return cov, dropped, corr


def compute_weights(
    selected: list[dict],
    cov: pd.DataFrame,
    method: str,
    max_position_weight: float = 1.0,
    sector_map: dict[str, str] | None = None,
    max_sector_weight: float = 1.0,
    av_sector_map: dict[str, str] | None = None,
    max_av_sector_weight: float = 1.0,
) -> dict[str, float]:
    """
    Compute portfolio weights for the selected tickers.

    Methods:
      equal_weight           — 1/N for every position
      adj_score_proportional — proportional to adj_score (score/portfolio-vol ratio
                               from the greedy loop); rewards high-conviction + low-vol
      score_proportional     — proportional to composite_score (shifted positive)
      inverse_vol            — proportional to 1/σ_i (individual vol from diagonal of cov)

    max_position_weight is enforced via iterative capping: excess weight from capped
    positions is redistributed proportionally to uncapped positions until stable.

    max_sector_weight is enforced after the position cap: over-cap sectors are scaled
    down proportionally, excess is redistributed to tickers in under-cap sectors, then
    the position cap is re-applied. The sector cap and position cap are iterated until
    both constraints are simultaneously satisfied (typically 2-3 rounds).

    Returns weights that sum to 1.0.
    """
    tickers = [s["ticker"] for s in selected]
    n = len(tickers)

    if method == "equal_weight":
        raw = {t: 1.0 / n for t in tickers}

    elif method == "adj_score_proportional":
        vals = {s["ticker"]: s["adj_score"] for s in selected}
        total = sum(vals.values())
        if total <= 0:
            raise ValueError(
                f"adj_score_proportional: sum of adj_scores is {total:.6f}; "
                "all adj_scores must be positive (greedy_select base-shifts scores before dividing)"
            )
        raw = {t: vals[t] / total for t in tickers}

    elif method == "score_proportional":
        vals = {s["ticker"]: s["composite_score"] for s in selected}
        min_s = min(vals.values())
        if min_s <= 0:
            vals = {t: v - min_s + 1.0 for t, v in vals.items()}
        total = sum(vals.values())
        raw = {t: vals[t] / total for t in tickers}

    elif method == "inverse_vol":
        inv = {t: 1.0 / max(float(np.sqrt(cov.loc[t, t])), 1e-6) for t in tickers}
        total = sum(inv.values())
        raw = {t: inv[t] / total for t in tickers}

    else:
        raise ValueError(f"Unknown weighting method: {method!r}")

    def _apply_position_cap(w: dict[str, float]) -> dict[str, float]:
        """Redistribute excess from over-cap positions to under-cap ones (iterative)."""
        w = dict(w)
        ever_capped: set[str] = set()
        for _ in range(n):
            over = {t: v for t, v in w.items() if v > max_position_weight + 1e-9 and t not in ever_capped}
            if not over:
                break
            ever_capped.update(over.keys())
            excess = sum(v - max_position_weight for v in over.values())
            for t in over:
                w[t] = max_position_weight
            under = {t: v for t, v in w.items() if t not in ever_capped}
            total_under = sum(under.values())
            if total_under < 1e-12:
                break
            for t in under:
                w[t] += excess * (w[t] / total_under)
        return w

    weights = _apply_position_cap(raw)

    def _apply_group_cap(w: dict[str, float], group_map: dict[str, str],
                         max_group_weight: float) -> dict[str, float]:
        """Redistribute weight away from over-cap groups (one grouping dimension).

        The greedy_select count cap prevents too many picks from one group but doesn't
        bound the combined weight when adj_score_proportional gives high-conviction
        names in the same group much larger weights. This loop is the hard weight gate.

        ever_capped tracking: once a group is brought to max_group_weight it never
        receives redistributed weight again, preventing oscillation when two groups
        take turns pushing each other over. If the constraint is infeasible
        (n_groups * max < 1.0) the loop breaks when no uncapped receivers remain; the
        caller's final normalization restores sum-to-1.
        """
        w = dict(w)
        ever_capped: set[str] = set()
        for _round in range(n * 2):
            totals: dict[str, float] = {}
            for t, wt in w.items():
                g = group_map.get(t, "")
                if g:
                    totals[g] = totals.get(g, 0.0) + wt
            over = {g for g, tot in totals.items()
                    if tot > max_group_weight + 1e-9 and g not in ever_capped}
            if not over:
                break
            ever_capped.update(over)
            total_excess = 0.0
            for t in list(w.keys()):
                g = group_map.get(t, "")
                if g in over:
                    scale = max_group_weight / totals[g]
                    total_excess += w[t] * (1.0 - scale)
                    w[t] *= scale
            under = {t: wt for t, wt in w.items() if group_map.get(t, "") not in ever_capped}
            total_under = sum(under.values())
            if total_under < 1e-12:
                break
            for t in under:
                w[t] += total_excess * (w[t] / total_under)
            # Group redistribution can push positions above max_position_weight;
            # re-apply the position cap before the next group check.
            if max_position_weight < 1.0:
                w = _apply_position_cap(w)
        return w

    # Active group constraints: the correlation-cluster cap and the independent
    # AV-sector cap. With two groupings, iterate them to a mutual fixpoint (capping
    # one redistributes weight that may violate the other) — bounded and convergent
    # because each group, once capped, never receives weight back.
    constraints: list[tuple[dict[str, str], float]] = []
    if sector_map is not None and max_sector_weight < 1.0:
        constraints.append((sector_map, max_sector_weight))
    if av_sector_map is not None and max_av_sector_weight < 1.0:
        constraints.append((av_sector_map, max_av_sector_weight))

    for _outer in range(2 * len(constraints) + 1):
        changed = False
        for gmap, gmax in constraints:
            new_w = _apply_group_cap(weights, gmap, gmax)
            if any(abs(new_w[t] - weights[t]) > 1e-9 for t in new_w):
                changed = True
            weights = new_w
        if not changed:
            break

    # Normalise to exactly 1.0 (guard against floating-point drift)
    total = sum(weights.values())
    return {t: round(weights[t] / total, 6) for t in tickers}
