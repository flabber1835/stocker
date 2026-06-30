"""Phase 1 — deterministic WEEKLY evidence packet for the LLM evaluator.

Read-only, no LLM, no look-ahead. From accumulated rankings + realized forward returns
it computes, per horizon:
  - realized IC (Spearman) for EVERY factor in rankings.factor_scores — weighted,
    dormant (weight 0), AND display indicators (drawdown/excess_dd/idio_vol/beta) — plus
    the composite. This is what lets the evaluator recommend activating/promoting a
    factor on evidence.
  - each factor's correlation to the composite + the pairwise factor correlation matrix
    (the IC×(1−corr) "does it add signal?" inputs).
  - book-vs-benchmark forward return, hit rate, and regret (top non-selected movers).

Realized IC needs FORWARD returns, so this is a weekly DERIVED view (base run ~1 horizon
ago, return measured to as_of) — NOT something the per-run health record can hold.
Persisted one row per ISO week in evaluator_weekly. Best-effort; never raises.
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from stock_strategy_shared.factor_registry import FACTOR_NAMES
from stock_strategy_shared.loader import load_strategy

# display-only indicators carried in rankings.factor_scores (not scored, but their IC
# tells the evaluator whether to PROMOTE one to a factor — e.g. falling-knife).
DISPLAY_KEYS = ("drawdown_21d", "excess_dd_21d", "idio_vol", "beta")
_MIN_OBS = 10            # minimum tickers for a meaningful cross-sectional IC
_REGRET_TOP = 10         # how many top non-selected movers to surface


def _spearman(a: pd.Series, b: pd.Series):
    """Spearman rank correlation as Pearson-on-ranks (no scipy dependency)."""
    return a.rank().corr(b.rank())


def _active_weighted_factors() -> set[str]:
    """The currently-weighted factor set (the 'existing book') — marginal IC is computed
    relative to THIS. Best-effort: empty set if the config can't be loaded → marginal IC
    falls back to None (no controls)."""
    try:
        cfg, _ = load_strategy(os.getenv("STRATEGY_CONFIG_PATH", ""))
        w = cfg.static_factor_weights
        if w is None:  # regime rotation on → use the bull_calm vector as a representative book
            w = next(iter(cfg.factor_weights.values()))
        return {f for f, val in w.model_dump().items() if (val or 0) > 0}
    except Exception:  # noqa: BLE001
        return set()


def _marginal_ic(fs: pd.DataFrame, factor: str, controls: list[str], fwd: pd.Series):
    """IC of `factor` AFTER residualizing it on `controls` (the weighted book) via OLS —
    i.e. the signal it adds BEYOND what's already traded. A factor that duplicates a
    control (e.g. drawdown vs near_high) residualizes to ~0 → low marginal IC, even when
    its raw IC and its corr_to_composite both look favourable."""
    ctrl = [c for c in controls if c != factor and c in fs.columns]
    if not ctrl:
        return None, 0
    d = pd.concat([fs[[factor, *ctrl]], fwd.rename("fwd")], axis=1).dropna()
    if len(d) < _MIN_OBS:
        return None, len(d)
    X = np.column_stack([np.ones(len(d)), d[ctrl].to_numpy(dtype=float)])
    y = d[factor].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ysd = float(np.std(y))
    # Fully explained by the controls (collinear) → residual is numerical noise; ranking
    # that noise yields a SPURIOUS IC. Treat it as zero marginal signal (adds nothing).
    if ysd == 0.0 or float(np.std(resid)) / ysd < 1e-6:
        return 0.0, len(d)
    ic = _spearman(pd.Series(resid, index=d.index), d["fwd"])
    return (None if pd.isna(ic) else round(float(ic), 4)), len(d)


def _spearman_ic(scores: pd.Series, fwd: pd.Series) -> tuple[float | None, int]:
    """Cross-sectional rank IC between a factor's scores and forward returns."""
    df = pd.concat([scores.rename("s"), fwd.rename("f")], axis=1).dropna()
    n = len(df)
    if n < _MIN_OBS:
        return None, n
    ic = _spearman(df["s"], df["f"])
    return (None if pd.isna(ic) else round(float(ic), 4)), n


async def _base_ranking_run(conn, as_of: date, lookback_days: int):
    cutoff = as_of - timedelta(days=lookback_days)   # bind a date — avoids SQL interval math
    return (await conn.execute(text(
        "SELECT run_id::text AS rid, rank_date FROM ranking_runs "
        "WHERE status='success' AND rank_date <= :cutoff "
        "ORDER BY rank_date DESC LIMIT 1"
    ), {"cutoff": cutoff})).mappings().first()


async def _forward_returns(conn, tickers, base_date, as_of) -> pd.Series:
    """{ticker: realized return} from base_date close to the latest close <= as_of."""
    if not tickers:
        return pd.Series(dtype=float)
    rows = (await conn.execute(text(
        "WITH b AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close FROM daily_prices "
        "           WHERE ticker = ANY(:tk) AND date <= :bd ORDER BY ticker, date DESC), "
        "     n AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close FROM daily_prices "
        "           WHERE ticker = ANY(:tk) AND date <= :asof ORDER BY ticker, date DESC) "
        "SELECT b.ticker, b.adjusted_close AS base, n.adjusted_close AS now FROM b "
        "JOIN n USING (ticker) WHERE b.adjusted_close > 0"
    ), {"tk": list(tickers), "bd": base_date, "asof": as_of})).mappings().all()
    return pd.Series({r["ticker"]: float(r["now"]) / float(r["base"]) - 1.0 for r in rows}, dtype=float)


async def _horizon_block(conn, as_of: date, lookback_days: int, weighted: set[str]) -> dict | None:
    base = await _base_ranking_run(conn, as_of, lookback_days)
    if not base:
        return None
    base_date = base["rank_date"]
    rk = (await conn.execute(text(
        "SELECT ticker, composite_score, factor_scores FROM rankings WHERE run_id = CAST(:rid AS uuid)"
    ), {"rid": base["rid"]})).mappings().all()
    if not rk:
        return None

    fs = pd.DataFrame([{
        "ticker": r["ticker"],
        "composite": (None if r["composite_score"] is None else float(r["composite_score"])),
        **{k: (r["factor_scores"] or {}).get(k) for k in (*FACTOR_NAMES, *DISPLAY_KEYS)},
    } for r in rk]).set_index("ticker")
    for c in fs.columns:
        fs[c] = pd.to_numeric(fs[c], errors="coerce")

    fwd = await _forward_returns(conn, list(fs.index), base_date, as_of)
    spy = await _forward_returns(conn, ["SPY"], base_date, as_of)
    bench = float(spy.get("SPY")) if not spy.empty and pd.notna(spy.get("SPY")) else None

    # per-factor IC (+composite); only columns with data. marginal_ic = IC after
    # residualizing on the weighted book (controls drop any all-null weighted factor,
    # e.g. earnings_surprise before its ingest). composite has no marginal (it IS the book).
    cols = [c for c in fs.columns if fs[c].notna().any()]
    controls = [c for c in weighted if c in fs.columns and fs[c].notna().any()]
    ic = {}
    for c in cols:
        val, n = _spearman_ic(fs[c], fwd)
        entry = {"ic": val, "n": n}
        if c != "composite":
            mic, _mn = _marginal_ic(fs, c, controls, fwd)
            entry["marginal_ic"] = mic
        ic[c] = entry

    # correlation to composite + a compact pairwise factor-correlation matrix
    corr_to_composite, corr_matrix = {}, {}
    factor_cols = [c for c in cols if c != "composite"]
    if "composite" in fs.columns and fs["composite"].notna().any():
        for c in factor_cols:
            d = fs[[c, "composite"]].dropna()
            cc = _spearman(d[c], d["composite"]) if len(d) >= _MIN_OBS else None
            corr_to_composite[c] = (None if cc is None or pd.isna(cc) else round(float(cc), 3))
    if len(factor_cols) >= 2:
        cm = fs[factor_cols].rank().corr().round(3)   # Spearman matrix via ranks (no scipy)
        corr_matrix = {a: {b: (None if pd.isna(cm.loc[a, b]) else float(cm.loc[a, b])) for b in factor_cols}
                       for a in factor_cols}

    # book vs benchmark + hit rate + regret (from the base portfolio's target holdings)
    book = {"benchmark_fwd_return": bench}
    ph = (await conn.execute(text(
        "SELECT h.ticker FROM portfolio_holdings h JOIN portfolio_runs pr ON pr.run_id = h.run_id "
        "WHERE pr.portfolio_date = :bd AND pr.status='success' "
        "ORDER BY pr.started_at DESC"
    ), {"bd": base_date})).mappings().all()
    selected = {r["ticker"] for r in ph}
    if selected:
        sel_fwd = fwd[fwd.index.isin(selected)].dropna()
        non_fwd = fwd[~fwd.index.isin(selected)].dropna()
        book["selected_count"] = int(len(sel_fwd))
        book["book_fwd_return"] = round(float(sel_fwd.mean()), 4) if len(sel_fwd) else None
        book["hit_rate"] = round(float((sel_fwd > 0).mean()), 4) if len(sel_fwd) else None
        book["excess_vs_benchmark"] = (round(book["book_fwd_return"] - bench, 4)
                                       if book.get("book_fwd_return") is not None and bench is not None else None)
        book["regret_top_non_selected"] = [
            {"ticker": t, "fwd_return": round(float(v), 4)}
            for t, v in non_fwd.sort_values(ascending=False).head(_REGRET_TOP).items()
        ]

    return {
        "base_rank_date": str(base_date),
        "lookback_days": lookback_days,
        "universe_n": int(len(fs)),
        "factor_ic": ic,
        "corr_to_composite": corr_to_composite,
        "factor_correlation_matrix": corr_matrix,
        "book": book,
    }


async def build_weekly_packet(engine, as_of_date: date, lookbacks=(7, 30)) -> dict | None:
    """Assemble the weekly evidence packet; None if no horizon has a base run + forward data."""
    weighted = _active_weighted_factors()
    horizons: dict = {}
    async with engine.connect() as conn:
        for lb in lookbacks:
            try:
                blk = await _horizon_block(conn, as_of_date, lb, weighted)
            except Exception:  # noqa: BLE001 — one horizon failing must not sink the packet
                blk = None
            if blk:
                horizons[f"{lb}d"] = blk
    if not horizons:
        return None
    return {
        "schema_version": 2,
        "as_of_date": str(as_of_date),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weighted_factors": sorted(weighted),
        "horizons": horizons,
        "notes": "Deterministic evidence (Phase 1). IC = cross-sectional Spearman of factor "
                 "score vs realized forward return (weighted, dormant, display factors). "
                 "marginal_ic = IC after residualizing on the weighted book — the signal a "
                 "factor adds BEYOND what's already traded (use THIS, not IC×(1−corr_to_"
                 "composite), to judge adding a factor: a factor can be ~orthogonal to the "
                 "blended composite yet duplicate one weighted factor, e.g. drawdown↔near_high).",
    }


async def backfill_weekly_packets(engine, latest_as_of: date, weeks: int = 8,
                                  artifacts_path: str = "") -> int:
    """Backfill prior weeks' packets from EXISTING history (no look-ahead — each as_of's
    forward returns only read prices <= that as_of). Steps back one ISO week at a time
    from `latest_as_of`; each week is idempotent (skipped if already present) and weeks
    with no base run / insufficient forward data simply don't write. Returns the count
    actually written. Lets you stand up real evidence immediately instead of waiting."""
    written = 0
    for k in range(1, weeks + 1):
        as_of = latest_as_of - timedelta(days=7 * k)   # k weeks ago (distinct ISO weeks)
        if await maybe_write_weekly_packet(engine, as_of, artifacts_path):
            written += 1
    print(f"[evaluator] backfill wrote {written} weekly packet(s) over the last {weeks} weeks")
    return written


async def maybe_write_weekly_packet(engine, as_of_date: date, artifacts_path: str = "") -> bool:
    """Build + persist the weekly packet ONCE per ISO week (idempotent). Returns True if
    a packet was written this call. Best-effort: logs and returns False on any failure."""
    try:
        iso = as_of_date.isocalendar()
        async with engine.connect() as conn:
            exists = (await conn.execute(text(
                "SELECT 1 FROM evaluator_weekly WHERE iso_year=:y AND iso_week=:w"
            ), {"y": iso.year, "w": iso.week})).first()
        if exists:
            return False
        packet = await build_weekly_packet(engine, as_of_date)
        if packet is None:
            print(f"[evaluator] weekly packet skipped {as_of_date}: no base run with forward data yet")
            return False
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO evaluator_weekly (iso_year, iso_week, as_of_date, packet) "
                "VALUES (:y,:w,:asof, CAST(:p AS jsonb)) ON CONFLICT (iso_year, iso_week) DO NOTHING"
            ), {"y": iso.year, "w": iso.week, "asof": as_of_date, "p": json.dumps(packet, default=str)})
        if artifacts_path:
            import os
            d = os.path.join(artifacts_path, "evaluator")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"week_{iso.year}_{iso.week:02d}.json"), "w") as f:
                json.dump(packet, f, indent=2, default=str)
        print(f"[evaluator] weekly packet written for {iso.year}-W{iso.week:02d} (as_of {as_of_date})")
        return True
    except Exception as exc:  # noqa: BLE001 — never break the chain on the evidence packet
        print(f"[evaluator] WARNING: weekly packet failed for {as_of_date}: {exc}")
        traceback.print_exc()
        return False
