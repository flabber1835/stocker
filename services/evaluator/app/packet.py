"""Deterministic weekly evidence packet for the LLM evaluator (Phase 1).

Read-only. Assembles EVERYTHING the frontier model needs to judge "does this system
pick winners?" from Postgres. Every section is BEST-EFFORT: a failing section becomes
{"error": "..."} instead of sinking the whole packet, so a partial database (early in
the system's life) still yields a usable report — the LLM is told what's missing.

No LLM calls here; no writes. The packet is persisted verbatim on the report row so
every recommendation can be audited against exactly the data the model saw.
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text

from stock_strategy_shared.loader import load_strategy

TRADE_LOOKBACK_DAYS = int(os.getenv("EVALUATOR_TRADE_LOOKBACK_DAYS", "365"))
WEEKLY_PACKETS = int(os.getenv("EVALUATOR_WEEKLY_PACKETS", "12"))
VETTER_LOOKBACK_DAYS = int(os.getenv("EVALUATOR_VETTER_LOOKBACK_DAYS", "90"))
SELECTION_AUDIT_CANDIDATES = int(os.getenv("EVALUATOR_SELECTION_AUDIT_CANDIDATES", "150"))

# ── System-architecture brief ─────────────────────────────────────────────────
# A concise, versioned description of HOW the system works, given to the LLM so
# it can critique STRUCTURE — missing factors, illogical steps, selection
# pathologies — not just tune knobs. Hand-maintained; update when the pipeline
# changes materially (it is part of the prompt, so edits change prompt_hash).
ARCHITECTURE_BRIEF = """\
PIPELINE (daily, after US close; fully deterministic — no LLM in the chain):
1. INGEST: Alpha Vantage daily adjusted prices + fundamentals for all active US
   equities (universe from AV LISTING_STATUS). Also earnings; news NOT ingested.
2. FACTORS (cross-sectional, per ticker): momentum (12-1 and 6-1 residual,
   market-stripped, NOT vol-scaled), quality, value, growth, low_volatility,
   liquidity, beta, drawdown, issuance; optional (weight-0 unless configured):
   small_cap, volume_surge, near_high, high_volatility, earnings_surprise (PEAD).
   Factors are percentile-scored; composite = weighted sum over non-null factors
   (renormalized); min_non_null_factors gate; investability floors (min_price,
   min 20d dollar volume).
3. RANK: composite ranking of the investable universe. Regime detection exists
   but regime WEIGHT ROTATION IS OFF — one static weight vector.
4. VET (deterministic, drawdown-only mode): beta-adjusted, vol-scaled falling-
   knife veto — excludes any candidate whose idiosyncratic 21d drawdown breaches
   a per-name limit, plus a 25% absolute floor. No news/LLM judgment in-chain.
5. BUILD (the greedy selector = source of truth for membership): from the top
   candidate_count ranked names minus vetter exclusions, greedy_select picks
   max_positions names maximizing score/portfolio-vol^selection_vol_aversion,
   subject to: correlation-cluster weight cap AND count cap, AV-sector weight
   cap, max_position_weight. Weights = score_proportional, then optional
   BETA-TARGET tilt (reweight toward beta_target within caps), then optional
   VOL-TARGET de-leverage (scale gross exposure when ex-ante vol > target).
6. DELTA: diff target vs broker book. Entries = in target, not held (capacity-
   gated to free slots). A held name exits ONLY when the builder drops it from
   the target for orphan_confirmation_days consecutive builds (rank itself never
   forces an exit). Weight drift produces trims/adds.
7. RISK GATE + EXECUTION: deterministic risk service (kill switch, notional/
   turnover/position/count/staleness limits) approves each intent; day orders
   queue for the next open; paper trading via Alpaca.
KNOWN NON-FEATURES (candidates for structural findings): no news/sentiment
input anywhere (vetter is price-only now); no earnings-proximity entry gate; no
intraday layer; no shorting; no position-level stop-loss (exit hysteresis is
the orphan timer only); backtester exists but is not yet in the weekly loop.
"""


def _f(v) -> float | None:
    return None if v is None else float(v)


def _r(v, nd=4) -> float | None:
    return None if v is None else round(float(v), nd)


async def _section(fn: Callable[[], Awaitable[Any]], conn=None) -> Any:
    """Run one packet section; degrade to an error marker instead of raising.

    ROLLS BACK the shared connection on failure: sections share one connection,
    and without the rollback a single SQL error aborts the transaction and every
    subsequent section dies with InFailedSQLTransactionError — one bug blanked an
    entire live packet (the W27 'largely non-functional' report)."""
    try:
        return await fn()
    except Exception as exc:  # noqa: BLE001 — a missing table must not sink the packet
        traceback.print_exc()
        if conn is not None:
            try:
                await conn.rollback()
            except Exception:  # noqa: BLE001
                pass
        return {"error": f"{type(exc).__name__}: {exc}"}


# ── sections ──────────────────────────────────────────────────────────────────

def _strategy_config_section() -> dict:
    """Active config: raw YAML verbatim + hash. The evaluator recommends edits to
    THIS file, so it sees the source of truth, not a lossy summary."""
    path = os.getenv("STRATEGY_CONFIG_PATH", "")
    cfg, cfg_hash = load_strategy(path)
    raw = ""
    try:
        with open(path) as f:
            raw = f.read()
    except OSError:
        pass
    return {
        "strategy_id": cfg.strategy_id,
        "config_hash": cfg_hash,
        "path": path,
        "yaml": raw,
    }


async def _weekly_evidence(conn) -> list[dict]:
    """The accumulated evaluator_weekly packets (factor IC, marginal IC, factor
    correlations, book-vs-benchmark, hit rate, regret) — newest first."""
    rows = (await conn.execute(text(
        "SELECT iso_year, iso_week, as_of_date, packet FROM evaluator_weekly "
        "ORDER BY as_of_date DESC LIMIT :n"
    ), {"n": WEEKLY_PACKETS})).mappings().all()
    return [{"iso_year": r["iso_year"], "iso_week": r["iso_week"],
             "as_of_date": str(r["as_of_date"]), **(r["packet"] or {})} for r in rows]


async def _prior_reviews(conn) -> dict:
    """The evaluator's own memory: the last few reports it produced, so this
    week's review can ITERATE — check whether last week's recommendations were
    adopted (compare each suggested_value to the CURRENT yaml it also receives),
    self-correct ones that aged badly, and escalate structural findings that
    recur instead of re-discovering them cold every week."""
    # ONE report per ISO week (the latest success). Forced manual re-runs create
    # several same-week reports; feeding them all in made the model count REPORTS
    # as WEEKS ("4th consecutive week flagging beta" after 4 same-week re-runs).
    # Collapsing to the newest per week makes streak arithmetic correct by
    # construction; rerun_count keeps the collapse visible.
    # Authoritative history bounds: the TOTAL distinct review weeks that exist and
    # the first review date. Streak claims are capped by these; without them the
    # model inherited inflated streaks from its OWN prior narratives (pre-dedup
    # reports contain sentences like "4th consecutive week" that re-enter via
    # narrative_excerpt and self-perpetuate).
    hist = (await conn.execute(text(
        "SELECT COUNT(DISTINCT (iso_year, iso_week)) AS weeks, MIN(as_of_date) AS first "
        "FROM evaluator_reports WHERE status='success'"
    ))).mappings().first()
    rows = (await conn.execute(text(
        "SELECT DISTINCT ON (iso_year, iso_week) "
        "       as_of_date, iso_year, iso_week, config_hash, report_markdown, "
        "       recommendations, data_gaps, "
        "       (SELECT COUNT(*) FROM evaluator_reports r2 "
        "        WHERE r2.status='success' AND r2.iso_year=evaluator_reports.iso_year "
        "        AND r2.iso_week=evaluator_reports.iso_week) AS week_report_count "
        "FROM evaluator_reports WHERE status='success' "
        "ORDER BY iso_year DESC, iso_week DESC, started_at DESC "
        "LIMIT 4"
    ))).mappings().all()
    out = []
    for r in rows:
        rj = r["recommendations"] or {}
        out.append({
            "as_of_date": str(r["as_of_date"]),
            "iso_week": f"{r['iso_year']}-W{r['iso_week']:02d}",
            "same_week_rerun_count": int(r["week_report_count"]),
            "config_hash_at_review": r["config_hash"],
            "overall_assessment": rj.get("overall_assessment"),
            "recommendations": rj.get("items") or [],
            "structural_findings": rj.get("structural") or [],
            "data_gaps": r["data_gaps"] or [],
            "narrative_excerpt": (r["report_markdown"] or "")[:1500],
        })
    return {
        "reports": out,
        "distinct_weeks_covered": len(out),
        # HARD BOUNDS — no streak or "N weeks" claim may exceed these.
        "total_distinct_review_weeks_ever": int(hist["weeks"]) if hist else len(out),
        "first_review_as_of": str(hist["first"]) if hist and hist["first"] else None,
        "note": ("Your own prior output — ONE entry per ISO week (the latest report of "
                 "that week; same_week_rerun_count shows collapsed manual re-runs). "
                 "Streaks MUST be counted in DISTINCT ISO WEEKS from these entries and "
                 "may NEVER exceed total_distinct_review_weeks_ever. WARNING: prior "
                 "narrative excerpts may contain INFLATED streak counts written before "
                 "same-week re-runs were collapsed — treat any streak number found "
                 "inside prior narrative TEXT as unreliable and RECOUNT from the "
                 "entries listed here; never copy it forward. For each prior "
                 "recommendation: compare its suggested_value to the CURRENT strategy "
                 "YAML in this packet — adopted, ignored, or superseded? Say so, and "
                 "judge how adopted ones played out. Re-raise unadopted recommendations "
                 "only if the evidence still supports them (claim 'recommended N weeks "
                 "running' only with N distinct weeks). Escalate structural findings "
                 "that recur; retract ones that aged badly."),
    }


async def _spy_closes(conn) -> list[tuple[date, float]]:
    rows = (await conn.execute(text(
        "SELECT date, adjusted_close FROM daily_prices WHERE ticker='SPY' "
        "ORDER BY date ASC"
    ))).fetchall()
    return [(r[0], float(r[1])) for r in rows if r[1]]


async def _account_performance(conn) -> dict:
    """Daily account equity (last successful sync per day) vs SPY, since inception.
    This is the realized ground truth the whole system is judged against."""
    rows = (await conn.execute(text(
        "SELECT DISTINCT ON (started_at::date) started_at::date AS d, account_value "
        "FROM alpaca_sync_runs WHERE status='success' AND account_value IS NOT NULL "
        "ORDER BY started_at::date ASC, started_at DESC"
    ))).fetchall()
    curve = [{"date": str(r[0]), "equity": _r(r[1], 2)} for r in rows]
    if not curve:
        return {"note": "no broker sync history yet", "equity_curve": []}

    spy = dict(await _spy_closes(conn))

    def _ret(series: list[dict], days: int | None) -> float | None:
        if len(series) < 2:
            return None
        end = series[-1]
        start = series[0]
        if days is not None:
            cutoff = date.fromisoformat(end["date"]) - timedelta(days=days)
            prior = [p for p in series if date.fromisoformat(p["date"]) <= cutoff]
            if not prior:
                return None
            start = prior[-1]
        if not start["equity"]:
            return None
        return round(end["equity"] / start["equity"] - 1.0, 4)

    def _spy_ret(days: int | None) -> float | None:
        """SPY leg anchored EXACTLY like the account leg — start at the LAST
        close on-or-before the cutoff (audit finding: it previously used the
        first close on-or-AFTER the cutoff while the account used last-≤, so
        for the same label the account window was weakly longer than SPY's and
        'excess vs SPY' — the headline ground truth — biased upward in an
        uptrend, materially so across sync gaps)."""
        if not spy or len(curve) < 2:
            return None
        items = sorted(spy.items())
        end_d = date.fromisoformat(curve[-1]["date"])
        cutoff = (end_d - timedelta(days=days) if days is not None
                  else date.fromisoformat(curve[0]["date"]))
        start_px = next((c for d, c in reversed(items) if d <= cutoff), None)
        end_px = next((c for d, c in reversed(items) if d <= end_d), None)
        if days is None and start_px is None:
            # inception predates SPY history — fall back to first available
            start_px = items[0][1] if items else None
        if not start_px or not end_px:
            return None
        return round(end_px / start_px - 1.0, 4)

    horizons = {}
    for label, days in (("1w", 7), ("4w", 28), ("12w", 84), ("inception", None)):
        acct, bench = _ret(curve, days), _spy_ret(days)
        horizons[label] = {
            "account_return": acct,
            "spy_return": bench,
            "excess": (round(acct - bench, 4) if acct is not None and bench is not None else None),
        }
    # thin the curve for token economy: keep weekly points + last 30 days daily
    keep_daily_after = date.fromisoformat(curve[-1]["date"]) - timedelta(days=30)
    thinned = [p for i, p in enumerate(curve)
               if i % 5 == 0 or date.fromisoformat(p["date"]) >= keep_daily_after]
    return {"inception_date": curve[0]["date"], "as_of": curve[-1]["date"],
            "returns": horizons, "equity_curve": thinned}


async def _closed_trades(conn) -> dict:
    """Realized per-ticker P&L from filled orders (average-cost method) + open
    residuals. The decision-level ground truth: which picks made money."""
    rows = (await conn.execute(text(
        "SELECT ticker, side, action, filled_qty, avg_fill_price, filled_at "
        "FROM alpaca_orders "
        "WHERE filled_qty > 0 AND avg_fill_price IS NOT NULL AND filled_at IS NOT NULL "
        "  AND filled_at >= NOW() - make_interval(days => :lb) "
        "ORDER BY filled_at ASC"
    ), {"lb": TRADE_LOOKBACK_DAYS})).mappings().all()

    book: dict[str, dict] = {}
    closed: list[dict] = []
    for r in rows:
        t = r["ticker"]
        qty, px = float(r["filled_qty"]), float(r["avg_fill_price"])
        pos = book.setdefault(t, {"qty": 0.0, "cost": 0.0})
        if r["side"] == "buy":
            pos["cost"] = pos["cost"] + qty * px
            pos["qty"] = pos["qty"] + qty
        else:  # sell — realize against average cost
            if pos["qty"] <= 0:
                continue  # sell with no tracked basis (pre-window entry) — skip
            avg_cost = pos["cost"] / pos["qty"]
            sell_qty = min(qty, pos["qty"])
            pnl = (px - avg_cost) * sell_qty
            closed.append({
                "ticker": t, "action": r["action"], "qty": round(sell_qty, 2),
                "avg_cost": _r(avg_cost, 2), "sell_price": _r(px, 2),
                "realized_pnl": _r(pnl, 2),
                "return_pct": _r((px / avg_cost - 1.0) if avg_cost else None, 4),
                "closed_at": str(r["filled_at"].date()),
            })
            pos["qty"] -= sell_qty
            pos["cost"] -= avg_cost * sell_qty

    wins = [c for c in closed if (c["realized_pnl"] or 0) > 0]
    losses = [c for c in closed if (c["realized_pnl"] or 0) <= 0]
    return {
        "lookback_days": TRADE_LOOKBACK_DAYS,
        "closed_count": len(closed),
        "hit_rate": round(len(wins) / len(closed), 3) if closed else None,
        "total_realized_pnl": _r(sum(c["realized_pnl"] or 0 for c in closed), 2),
        "avg_win": _r(sum(c["realized_pnl"] for c in wins) / len(wins), 2) if wins else None,
        "avg_loss": _r(sum(c["realized_pnl"] for c in losses) / len(losses), 2) if losses else None,
        "trades": sorted(closed, key=lambda c: c["realized_pnl"] or 0)[:60],
    }


async def _open_positions(conn) -> list[dict]:
    rows = (await conn.execute(text(
        "SELECT lp.ticker, lp.qty, lp.avg_entry_price, lp.current_price, "
        "       lp.market_value, lp.unrealized_pl, lp.unrealized_plpc "
        "FROM live_positions lp "
        "WHERE lp.sync_run_id = (SELECT run_id FROM alpaca_sync_runs "
        "                        WHERE status='success' ORDER BY started_at DESC LIMIT 1) "
        "ORDER BY lp.market_value DESC NULLS LAST"
    ))).mappings().all()
    return [{"ticker": r["ticker"], "qty": _f(r["qty"]),
             "avg_entry": _r(r["avg_entry_price"], 2), "price": _r(r["current_price"], 2),
             "market_value": _r(r["market_value"], 2),
             "unrealized_pl": _r(r["unrealized_pl"], 2),
             "unrealized_plpc": _r(r["unrealized_plpc"], 4)} for r in rows]


async def _forward_return_since(conn, ticker: str, since: date) -> float | None:
    row = (await conn.execute(text(
        "WITH b AS (SELECT adjusted_close FROM daily_prices "
        "           WHERE ticker=:t AND date <= :d ORDER BY date DESC LIMIT 1), "
        "     n AS (SELECT adjusted_close FROM daily_prices "
        "           WHERE ticker=:t ORDER BY date DESC LIMIT 1) "
        "SELECT b.adjusted_close, n.adjusted_close FROM b, n"
    ), {"t": ticker, "d": since})).fetchone()
    if not row or not row[0] or not row[1] or float(row[0]) == 0:
        return None
    return round(float(row[1]) / float(row[0]) - 1.0, 4)


SHADOW_LOOKBACK_DAYS = 90
SHADOW_MAX_ROWS = 40
SHADOW_HORIZON_SESSIONS = 20


async def _shadow_vs_champion(conn) -> dict:
    """Closed-loop item 4 (audit-3 fixed-horizon redesign): each day's
    CHALLENGER shadow target vs the CHAMPION target built the same day, both
    scored as the weighted forward return over the SAME fixed 20-session span
    from the same anchor session. Days whose horizon has not fully elapsed are
    EXCLUDED (no mixed-horizon averaging; note consecutive daily spans still
    overlap, so n_days_compared overstates the independent sample — read the
    edge as a trend, not a t-stat). Honest scope: the shadow is an ALTERNATIVE
    THEORETICAL CONSTRUCTION USING THE CHAMPION'S FACTOR INPUTS — it skips the
    vetter, falling-knife veto and beta overlay that shaped the champion
    target, so the edge includes those mechanism differences, not purely the
    config knobs. Consistent positive edge = promotion evidence; promotion
    itself stays a human config change."""
    srows = (await conn.execute(text(
        "SELECT run_date, config_hash, strategy_id, target, n_positions "
        "FROM shadow_runs WHERE status='success' AND target IS NOT NULL "
        "AND run_date >= CURRENT_DATE - make_interval(days => :lb) "
        "ORDER BY run_date"), {"lb": SHADOW_LOOKBACK_DAYS})).mappings().all()
    if not srows:
        return {"note": ("no shadow runs — set CHALLENGER_CONFIG_PATH on the "
                         "pipeline to enable the shadow challenger")}
    crows = (await conn.execute(text(
        "WITH latest AS ("
        "  SELECT DISTINCT ON (portfolio_date) run_id, portfolio_date "
        "  FROM portfolio_runs WHERE status='success' "
        "    AND portfolio_date >= CURRENT_DATE - make_interval(days => :lb) "
        "  ORDER BY portfolio_date, started_at DESC) "
        "SELECT l.portfolio_date AS run_date, "
        "       json_object_agg(ph.ticker, ph.weight) AS target "
        "FROM latest l JOIN portfolio_holdings ph ON ph.run_id = l.run_id "
        "GROUP BY l.portfolio_date"),
        {"lb": SHADOW_LOOKBACK_DAYS})).mappings().all()
    champ_by_date = {r["run_date"]: r["target"] for r in crows}

    spy = await _spy_closes(conn)
    sessions = [d for d, _ in spy]
    from bisect import bisect_right

    async def _weighted_span(target: dict, d0: date, d1: date) -> float | None:
        """Weight-averaged return of `target` from last close ≤ d0 to last
        close ≤ d1 (held-at-last-price for names that stop printing)."""
        if not target:
            return None
        rows = (await conn.execute(text(
            "WITH b AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close AS p0 "
            "           FROM daily_prices WHERE ticker = ANY(:ts) "
            "           AND date <= :d0 AND date >= :d0f ORDER BY ticker, date DESC), "
            "     f AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close AS p1 "
            "           FROM daily_prices WHERE ticker = ANY(:ts) AND date <= :d1 "
            "           ORDER BY ticker, date DESC) "
            "SELECT b.ticker, b.p0, f.p1 FROM b JOIN f USING (ticker) WHERE b.p0 > 0"
        ), {"ts": list(target), "d0": d0, "d0f": d0 - timedelta(days=14),
            "d1": d1})).all()
        rets = {t: float(p1) / float(p0) - 1.0 for t, p0, p1 in rows if p0 and p1}
        pairs = [(float(w), rets[t]) for t, w in target.items() if t in rets]
        wsum = sum(w for w, _ in pairs)
        if wsum <= 0:
            return None
        return sum(w * r for w, r in pairs) / wsum

    rows_out, edges = [], []
    n_pending = 0
    for s in srows:
        i = bisect_right(sessions, s["run_date"]) - 1
        if i < 0 or i + SHADOW_HORIZON_SESSIONS >= len(sessions):
            n_pending += 1          # horizon not elapsed — excluded, never mixed in
            continue
        d0, d1 = sessions[i], sessions[i + SHADOW_HORIZON_SESSIONS]
        st = s["target"] if isinstance(s["target"], dict) else json.loads(s["target"])
        ct = champ_by_date.get(s["run_date"])
        if isinstance(ct, str):
            ct = json.loads(ct)
        ch_ret = await _weighted_span(st, d0, d1)
        cp_ret = await _weighted_span(ct or {}, d0, d1)
        if ch_ret is None:
            continue
        edge = (ch_ret - cp_ret) if cp_ret is not None else None
        if edge is not None:
            edges.append(edge)
        rows_out.append({"date": str(s["run_date"]),
                         "challenger_fwd_20d": round(ch_ret, 4),
                         "champion_fwd_20d": round(cp_ret, 4) if cp_ret is not None else None,
                         "edge_20d": round(edge, 4) if edge is not None else None,
                         "challenger_n": s["n_positions"]})
    return {
        "description": (
            "Fixed-horizon comparison: each day's challenger shadow target vs the "
            "champion target built the same day, both scored over the SAME "
            f"{SHADOW_HORIZON_SESSIONS}-session span. Scope caveat: the shadow is an "
            "alternative theoretical construction using the champion's factor inputs "
            "(no vetter / falling-knife / beta overlay on the shadow side), so the "
            "edge includes those mechanism differences, not purely config knobs. "
            "Daily spans overlap — treat the edge as a trend, not a t-stat. For a "
            "full turnover/cost-aware equity curve, run the challenger config "
            "through run_backtest (the wind tunnel)."),
        "horizon_sessions": SHADOW_HORIZON_SESSIONS,
        "challenger_strategy": srows[-1]["strategy_id"],
        "challenger_config_hash": srows[-1]["config_hash"],
        "n_days_compared": len(edges),
        "n_pending_horizon": n_pending,
        "avg_edge_20d": round(sum(edges) / len(edges), 4) if edges else None,
        "pct_days_challenger_ahead": (
            round(sum(1 for e in edges if e > 0) / len(edges), 3) if edges else None),
        "rows": rows_out[-SHADOW_MAX_ROWS:],
    }


CALIB_HORIZON_SESSIONS = 20
CALIB_MAX_RUNS = 6


def _calibration_deciles(pairs: list[tuple[int, float]], n_bins: int = 10) -> list[float | None]:
    """pairs = (rank, fwd_excess_return); contiguous rank bins best-first →
    per-decile mean. [] when fewer scored names than bins."""
    if len(pairs) < n_bins:
        return []
    pairs = sorted(pairs, key=lambda x: x[0])
    n = len(pairs)
    out = []
    for d in range(n_bins):
        chunk = [r for _, r in pairs[(d * n) // n_bins:((d + 1) * n) // n_bins]]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


async def _score_calibration(conn) -> dict:
    """Closed-loop item 3: does a better rank actually predict a better forward
    return, and is the relationship monotone? Decile-of-rank (decile 1 = best)
    → mean forward EXCESS return vs SPY over 20 sessions, averaged over up to
    CALIB_MAX_RUNS persisted ranking runs old enough (21–90d) to have forward
    data. A flat/non-monotone curve = the ordering carries no information in
    that band; top-decile-only lift with a flat middle supports concentration."""
    spy = await _spy_closes(conn)
    if len(spy) < CALIB_HORIZON_SESSIONS + 2:
        return {"note": "insufficient SPY history"}
    sessions = [d for d, _ in spy]
    spy_px = dict(spy)
    runs = (await conn.execute(text(
        "SELECT DISTINCT ON (rank_date) rank_date, run_id, regime "
        "FROM ranking_runs WHERE status='success' "
        "AND rank_date BETWEEN CURRENT_DATE - 90 AND CURRENT_DATE - 21 "
        "ORDER BY rank_date, started_at DESC"))).all()
    if not runs:
        return {"note": "no ranking runs 21-90 days old yet — needs history to accrue"}
    if len(runs) > CALIB_MAX_RUNS:
        step = (len(runs) - 1) / (CALIB_MAX_RUNS - 1)
        runs = [runs[round(i * step)] for i in range(CALIB_MAX_RUNS)]

    from bisect import bisect_right
    per_run, sampled = [], []
    for rank_date, run_id, regime in runs:
        i = bisect_right(sessions, rank_date) - 1
        if i < 0 or i + CALIB_HORIZON_SESSIONS >= len(sessions):
            continue
        d0, d1 = sessions[i], sessions[i + CALIB_HORIZON_SESSIONS]
        if d0 not in spy_px or d1 not in spy_px or spy_px[d0] <= 0:
            continue
        spy_ret = spy_px[d1] / spy_px[d0] - 1.0
        rows = (await conn.execute(text(
            "WITH r AS (SELECT ticker, rank FROM rankings WHERE run_id=CAST(:rid AS uuid)), "
            "b AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close AS p0 FROM daily_prices "
            "      WHERE ticker IN (SELECT ticker FROM r) AND date <= :d0 AND date >= :d0f "
            "      ORDER BY ticker, date DESC), "
            "f AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close AS p1 FROM daily_prices "
            "      WHERE ticker IN (SELECT ticker FROM r) AND date <= :d1 "
            "      ORDER BY ticker, date DESC) "
            "SELECT r.rank, b.p0, f.p1 FROM r "
            "JOIN b USING (ticker) JOIN f USING (ticker) WHERE b.p0 > 0"
        ), {"rid": str(run_id), "d0": d0, "d1": d1,
            "d0f": d0 - timedelta(days=14)})).all()
        pairs = [(int(rk), float(p1) / float(p0) - 1.0 - spy_ret)
                 for rk, p0, p1 in rows if p0 and p1]
        deciles = _calibration_deciles(pairs)
        if deciles:
            per_run.append(deciles)
            sampled.append({"rank_date": str(rank_date), "regime": regime,
                            "n_tickers": len(pairs),
                            "spy_ret_20d": round(spy_ret, 4)})
    if not per_run:
        return {"note": "no sampled run produced a usable decile curve"}
    n_bins = 10
    avg = []
    for d in range(n_bins):
        vals = [run[d] for run in per_run if run[d] is not None]
        avg.append(round(sum(vals) / len(vals), 6) if vals else None)
    adj = [(a, b) for a, b in zip(avg, avg[1:]) if a is not None and b is not None]
    return {
        "description": (
            "Decile 1 = best-ranked tenth. avg_excess_20d = mean forward return "
            "minus SPY over the same 20 sessions, averaged across sampled runs."),
        "horizon_sessions": CALIB_HORIZON_SESSIONS,
        "deciles": [{"decile": i + 1, "avg_excess_20d": avg[i]} for i in range(n_bins)],
        "top_minus_bottom": (round(avg[0] - avg[-1], 6)
                             if avg[0] is not None and avg[-1] is not None else None),
        "monotone_fraction": (round(sum(1 for a, b in adj if a >= b) / len(adj), 4)
                              if adj else None),
        "sampled_runs": sampled,
    }


async def _decision_outcomes(conn) -> dict:
    """Decision-ledger aggregates (decision_outcomes, closed-loop item 1):
    per-action fixed-horizon outcome stats over the ledgered history. How to
    read: excess = ticker fwd return − SPY over the SAME session span. Positive
    avg excess on 'exit'/'vetter_exclude' means the names we SHED went on to
    OUTPERFORM (the decision cost money). 'watch' (capacity-deferred entries)
    beating 'entry' means the capacity gate defers the wrong names. mae_20d is
    the average worst drawdown within 20 sessions of the decision."""
    # Staleness guard (audit-3 fix #2): a label whose forward price is > 5
    # sessions stale (name stopped printing — delisted/halted) is EXCLUDED
    # from the headline averages and COUNTED instead, so hold-at-last-price
    # optimism can't silently leak into the stats the review reasons from.
    rows = (await conn.execute(text(
        "SELECT action, COUNT(*) AS n, COUNT(fwd_20d) AS n_labeled_20d, "
        "       COUNT(*) FILTER (WHERE fwd_20d IS NOT NULL "
        "                        AND COALESCE(stale_20d, 0) > 5) AS n_stale_20d, "
        "       AVG(fwd_20d) FILTER (WHERE COALESCE(stale_20d, 0) <= 5) "
        "           AS avg_fwd_20d, "
        "       AVG(fwd_20d - spy_fwd_20d) FILTER (WHERE COALESCE(stale_20d, 0) <= 5) "
        "           AS avg_excess_20d, "
        "       AVG(fwd_60d - spy_fwd_60d) FILTER (WHERE COALESCE(stale_60d, 0) <= 5) "
        "           AS avg_excess_60d, "
        "       AVG(CASE WHEN fwd_20d > spy_fwd_20d THEN 1.0 ELSE 0.0 END) "
        "           FILTER (WHERE fwd_20d IS NOT NULL AND spy_fwd_20d IS NOT NULL "
        "                   AND COALESCE(stale_20d, 0) <= 5) "
        "           AS hit_rate_20d, "
        "       AVG(mae_20d) FILTER (WHERE COALESCE(stale_20d, 0) <= 5) AS avg_mae_20d, "
        "       MIN(decision_date) AS first_decision, MAX(decision_date) AS last_decision "
        "FROM decision_outcomes GROUP BY action ORDER BY action"
    ))).mappings().all()
    if not rows:
        return {"note": "ledger empty — /jobs/label-outcomes has not harvested yet"}
    return {
        "description": (
            "Durable decision ledger: every entry/exit/trim/at_risk/watch intent and "
            "vetter exclusion, labeled with forward returns at fixed session horizons. "
            "excess = ticker − SPY over the same span. Averages exclude labels whose "
            "forward price was > 5 sessions stale (delisted/halted names held at last "
            "print — counted in n_stale_20d; a large stale count on exit/vetter_exclude "
            "means those counterfactuals are structurally optimistic, since names that "
            "stopped trading usually did so badly)."),
        "by_action": [{
            "action": r["action"], "n": r["n"], "n_labeled_20d": r["n_labeled_20d"],
            "n_stale_20d": r["n_stale_20d"],
            "avg_fwd_20d": _r(r["avg_fwd_20d"]),
            "avg_excess_20d": _r(r["avg_excess_20d"]),
            "avg_excess_60d": _r(r["avg_excess_60d"]),
            "hit_rate_20d_vs_spy": _r(r["hit_rate_20d"], 3),
            "avg_mae_20d": _r(r["avg_mae_20d"]),
            "first_decision": str(r["first_decision"]),
            "last_decision": str(r["last_decision"]),
        } for r in rows],
    }


async def _vetter_outcomes(conn) -> dict:
    """Counterfactual audit of vetter exclusions: what did the excluded names do
    AFTER the veto? Negative forward return = the veto added value."""
    rows = (await conn.execute(text(
        "SELECT DISTINCT ON (ve.ticker) ve.ticker, ve.reason, ve.risk_type, "
        "       ve.confidence, ve.created_at::date AS d "
        "FROM vetter_exclusions ve "
        "WHERE ve.created_at >= NOW() - make_interval(days => :lb) "
        "ORDER BY ve.ticker, ve.created_at ASC"
    ), {"lb": VETTER_LOOKBACK_DAYS})).mappings().all()
    # Aggregate over ALL exclusions; truncate only the per-name DISPLAY list.
    # (Audit finding: slicing rows[:80] BEFORE aggregating biased
    # pct_fell_after_veto to an alphabetical head of the ticker list and
    # misreported excluded_count whenever >80 names were vetoed.)
    out = []
    for r in rows:
        fwd = await _forward_return_since(conn, r["ticker"], r["d"])
        out.append({"ticker": r["ticker"], "risk_type": r["risk_type"],
                    "confidence": r["confidence"], "excluded_on": str(r["d"]),
                    "fwd_return_since": fwd,
                    "reason": (r["reason"] or "")[:200]})
    scored = [o for o in out if o["fwd_return_since"] is not None]
    saved = [o for o in scored if o["fwd_return_since"] < 0]
    return {
        "lookback_days": VETTER_LOOKBACK_DAYS,
        "excluded_count": len(out),
        "pct_fell_after_veto": round(len(saved) / len(scored), 3) if scored else None,
        "avg_fwd_return_of_excluded": (
            round(sum(o["fwd_return_since"] for o in scored) / len(scored), 4) if scored else None),
        "exclusions": out[:80],
        "exclusions_truncated": len(out) > 80,
    }


async def _exit_outcomes(conn) -> dict:
    """What did names we EXITED do after the exit? Positive forward return = we
    sold winners too early (or the orphan timer fired on a still-good name)."""
    rows = (await conn.execute(text(
        "SELECT DISTINCT ON (di.ticker) di.ticker, di.reason, dr.run_date AS d "
        "FROM delta_intents di JOIN delta_runs dr ON dr.run_id = di.run_id "
        "WHERE di.action='exit' "
        "  AND dr.run_date >= CURRENT_DATE - make_interval(days => :lb) "
        "ORDER BY di.ticker, dr.run_date DESC"
    ), {"lb": VETTER_LOOKBACK_DAYS})).mappings().all()
    # Same aggregate-then-truncate rule as _vetter_outcomes (audit finding).
    out = []
    for r in rows:
        fwd = await _forward_return_since(conn, r["ticker"], r["d"])
        out.append({"ticker": r["ticker"], "exited_on": str(r["d"]),
                    "fwd_return_since": fwd, "reason": (r["reason"] or "")[:200]})
    scored = [o for o in out if o["fwd_return_since"] is not None]
    return {
        "lookback_days": VETTER_LOOKBACK_DAYS,
        "exit_count": len(out),
        "avg_fwd_return_after_exit": (
            round(sum(o["fwd_return_since"] for o in scored) / len(scored), 4) if scored else None),
        "exits": out[:60],
        "exits_truncated": len(out) > 60,
    }


async def _invisible_bench(conn) -> dict:
    """Absence-blindness fix: forward returns of the cohorts that never enter
    the evidence funnel, so a costly gate can be SEEN instead of suspected.

      unranked_priced — in the universe with fresh prices at rank time, but
        absent from that ranking run entirely (below the investability floor or
        factor-gapped). If this bench persistently beats `selected`, a
        universe/factor gate is excluding winners.
      deferred_watch — capacity-deferred entries (delta action='watch'): the
        planner WANTED them but the book was full. Their forward return is the
        realized cost/benefit of defer-don't-rotate.
      selected — the book cohort over the same window, as the baseline.

    Anchored on the newest ranking run ≥7 days old so returns are realized
    (same convention as the selection audit). Averages are over the WHOLE
    cohort; only display lists are truncated."""
    anchor = (await conn.execute(text(
        "SELECT run_id, rank_date FROM ranking_runs "
        "WHERE status='success' AND rank_date <= CURRENT_DATE - 7 "
        "ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
    ))).mappings().first()
    if not anchor:
        return {"note": "no ranking run >=7 days old yet — bench needs realized forward returns"}
    rid, rdate = anchor["run_id"], anchor["rank_date"]

    unranked = [r[0] for r in (await conn.execute(text(
        "SELECT ut.ticker FROM universe_tickers ut "
        "WHERE ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
        "  AND ut.ticker <> 'SPY' "
        "  AND ut.ticker NOT IN (SELECT ticker FROM rankings WHERE run_id = :rid) "
        "  AND EXISTS (SELECT 1 FROM daily_prices dp WHERE dp.ticker = ut.ticker "
        "              AND dp.date BETWEEN CAST(:rd AS date) - 7 AND CAST(:rd AS date))"
    ), {"rid": rid, "rd": rdate})).fetchall()]

    selected = [r[0] for r in (await conn.execute(text(
        "SELECT ph.ticker FROM portfolio_holdings ph "
        "JOIN portfolio_runs pr ON pr.run_id = ph.run_id "
        "WHERE pr.source_ranking_run_id = :rid AND pr.status = 'success'"
    ), {"rid": rid})).fetchall()]

    def _agg(fwd: dict) -> dict:
        vals = [v for v in fwd.values() if v is not None]
        ranked_names = sorted(((t, v) for t, v in fwd.items() if v is not None),
                              key=lambda x: x[1])
        return {
            "count": len(fwd), "scored": len(vals),
            "avg_fwd_return": round(sum(vals) / len(vals), 4) if vals else None,
            "worst": [{"ticker": t, "fwd": round(v, 4)} for t, v in ranked_names[:5]],
            "best": [{"ticker": t, "fwd": round(v, 4)} for t, v in ranked_names[-5:][::-1]],
        }

    out = {
        "anchor_rank_date": str(rdate),
        "unranked_priced": _agg(await _forward_returns_bulk(conn, unranked, rdate)),
        "selected": _agg(await _forward_returns_bulk(conn, selected, rdate)),
    }

    # capacity-deferred entries: per-ticker dates, latest watch per ticker (90d)
    watch_rows = (await conn.execute(text(
        "SELECT DISTINCT ON (di.ticker) di.ticker, dr.run_date AS d "
        "FROM delta_intents di JOIN delta_runs dr ON dr.run_id = di.run_id "
        "WHERE di.action = 'watch' "
        "  AND dr.run_date >= CURRENT_DATE - make_interval(days => :lb) "
        "ORDER BY di.ticker, dr.run_date DESC"
    ), {"lb": VETTER_LOOKBACK_DAYS})).mappings().all()
    watch_fwd = {}
    for r in watch_rows:
        watch_fwd[r["ticker"]] = await _forward_return_since(conn, r["ticker"], r["d"])
    out["deferred_watch"] = _agg(watch_fwd)
    out["note"] = (
        "cohorts the funnel never audits elsewhere. unranked_priced beating "
        "`selected` persistently implicates a universe/factor GATE (cross-check "
        "the wind tunnel's liquidity-floor dimension before recommending a "
        "floor change); deferred_watch beating selected = capacity defer-don't-"
        "rotate is leaving returns on the table. One window is noise — trend it.")
    return out


# SPY's largest weights — PINNED list (holdings are not ingested anywhere).
# Update occasionally; the as-of is surfaced so staleness is visible evidence.
_SPY_TOP_AS_OF = "2026-07"
_SPY_TOP = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK-B",
    "LLY", "JPM", "V", "XOM", "UNH", "MA", "COST", "HD", "PG", "NFLX", "JNJ",
    "WMT", "ABBV", "CRM", "BAC", "ORCL",
]


async def _benchmark_coverage(conn) -> dict:
    """Where do the INDEX's engines sit in OUR funnel? A mega-cap-led SPY rally
    the book structurally cannot participate in shows up here as index leaders
    ranked deep or unranked — separating benchmark-composition drag from
    stock-picking error when judging the SPY hurdle."""
    run = (await conn.execute(text(
        "SELECT run_id FROM ranking_runs WHERE status='success' "
        "ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
    ))).mappings().first()
    if not run:
        return {"note": "no ranking run yet"}
    rank_map = {r["ticker"]: r["rank"] for r in (await conn.execute(text(
        "SELECT ticker, rank FROM rankings WHERE run_id = :rid AND ticker = ANY(:tk)"
    ), {"rid": run["run_id"], "tk": _SPY_TOP})).mappings().all()}
    held = {r[0] for r in (await conn.execute(text(
        "SELECT lp.ticker FROM live_positions lp "
        "WHERE lp.sync_run_id = (SELECT run_id FROM alpaca_sync_runs "
        "  WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
    ))).fetchall()}
    rows = [{"ticker": t, "rank": rank_map.get(t), "held": t in held}
            for t in _SPY_TOP]
    ranked_in_top100 = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 100)
    return {
        "spy_top_as_of": _SPY_TOP_AS_OF,
        "constituents": rows,
        "ranked_in_top100": ranked_in_top100,
        "unranked_count": sum(1 for r in rows if r["rank"] is None),
        "note": (
            "static SPY top-25 list (as-of above; update if stale). Many index "
            "leaders unranked/deep-ranked means SPY-hurdle gaps in index-led "
            "rallies are partly COMPOSITION, not stock-picking — weigh that "
            "before blaming the factor model, and vice versa."),
    }


async def _forward_returns_bulk(conn, tickers: list[str], since: date) -> dict[str, float]:
    """{ticker: return from last close <= since to latest close} in ONE query."""
    if not tickers:
        return {}
    rows = (await conn.execute(text(
        "WITH b AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close FROM daily_prices "
        "           WHERE ticker = ANY(:tk) AND date <= :d ORDER BY ticker, date DESC), "
        "     n AS (SELECT DISTINCT ON (ticker) ticker, adjusted_close FROM daily_prices "
        "           WHERE ticker = ANY(:tk) ORDER BY ticker, date DESC) "
        "SELECT b.ticker, b.adjusted_close AS base, n.adjusted_close AS now "
        "FROM b JOIN n USING (ticker) WHERE b.adjusted_close > 0"
    ), {"tk": list(tickers), "d": since})).mappings().all()
    return {r["ticker"]: round(float(r["now"]) / float(r["base"]) - 1.0, 4) for r in rows}


def classify_candidates(candidates: list[dict], selected: set[str],
                        excluded: dict[str, str], worst_selected_rank: int | None) -> list[dict]:
    """Pure classification of the builder's candidate pool. Reasons:
      selected        — in the target book
      vetter_excluded — vetoed before selection (risk_type attached)
      cap_blocked     — ranked BETTER than the worst selected name yet not picked:
                        greedy skipped it for diversification (cluster/sector/count
                        cap or vol-adjusted score) — a BUILDER decision
      out_ranked      — ranked worse than the last pick: never reached — a RANK
                        decision
    The selected-vs-class forward-return spreads built on this are the evidence
    for whether misses are factor problems or construction problems."""
    out = []
    for c in candidates:
        t = c["ticker"]
        if t in selected:
            reason = "selected"
        elif t in excluded:
            reason = "vetter_excluded"
        elif worst_selected_rank is not None and c["rank"] < worst_selected_rank:
            reason = "cap_blocked"
        else:
            reason = "out_ranked"
        out.append({**c, "outcome": reason,
                    **({"risk_type": excluded[t]} if t in excluded else {})})
    return out


FWD_MIN_DAYS = int(os.getenv("EVALUATOR_FWD_MIN_DAYS", "5"))


async def _latest_price_date(conn) -> date | None:
    return (await conn.execute(text(
        "SELECT MAX(date) FROM daily_prices WHERE ticker='SPY'"))).scalar()


async def _selection_audit(conn) -> dict:
    """Picked vs not-picked, with WHY and what each did afterward — the evidence
    that separates 'the rank missed winners' from 'the builder's caps rejected
    winners the rank found'.

    Anchored on the newest build with a REAL forward window (>= FWD_MIN_DAYS of
    prices after it), falling back to the newest build. Auditing yesterday's
    build gives fwd_return == 0.0 for every name (zero elapsed sessions) — the
    W27 report correctly read that as 'no realized-outcome signal'."""
    px_date = await _latest_price_date(conn)
    run = None
    if px_date:
        run = (await conn.execute(text(
            "SELECT run_id, source_ranking_run_id, portfolio_date FROM ("
            "  SELECT pr.run_id, ph.source_ranking_run_id, pr.portfolio_date, pr.started_at "
            "  FROM portfolio_runs pr JOIN portfolio_holdings ph ON ph.run_id = pr.run_id "
            "  WHERE pr.status='success' AND pr.portfolio_date <= :cutoff "
            "  ORDER BY pr.started_at DESC LIMIT 1) x"
        ), {"cutoff": px_date - timedelta(days=FWD_MIN_DAYS)})).mappings().first()
    if not run:
        run = (await conn.execute(text(
            "SELECT run_id, source_ranking_run_id, portfolio_date FROM ("
            "  SELECT pr.run_id, ph.source_ranking_run_id, pr.portfolio_date, pr.started_at "
            "  FROM portfolio_runs pr JOIN portfolio_holdings ph ON ph.run_id = pr.run_id "
            "  WHERE pr.status='success' ORDER BY pr.started_at DESC LIMIT 1) x"
        ))).mappings().first()
    if not run:
        return {"note": "no successful portfolio run yet"}

    cands = (await conn.execute(text(
        # Latest NON-NULL sector per ticker across snapshots — a fresh weekly
        # snapshot inserts sector=NULL everywhere, so scoping to the newest snapshot
        # showed the whole book as sector-unknown right after a refresh (W29 finding).
        "SELECT r.ticker, r.rank, r.composite_score, n.sector "
        "FROM rankings r "
        "LEFT JOIN (SELECT DISTINCT ON (ticker) ticker, sector FROM universe_tickers "
        "           WHERE sector IS NOT NULL "
        "           ORDER BY ticker, snapshot_id DESC) n ON n.ticker = r.ticker "
        "WHERE r.run_id = :rid ORDER BY r.rank ASC LIMIT :n"
    ), {"rid": run["source_ranking_run_id"], "n": SELECTION_AUDIT_CANDIDATES})).mappings().all()
    candidates = [{"ticker": c["ticker"], "rank": c["rank"],
                   "score": _r(c["composite_score"]), "sector": c["sector"]} for c in cands]

    sel_rows = (await conn.execute(text(
        "SELECT ticker, original_rank FROM portfolio_holdings WHERE run_id = :rid"
    ), {"rid": run["run_id"]})).mappings().all()
    selected = {r["ticker"] for r in sel_rows}
    ranks = [r["original_rank"] for r in sel_rows if r["original_rank"] is not None]
    worst_rank = max(ranks) if ranks else None

    exc_rows = (await conn.execute(text(
        "SELECT ve.ticker, ve.risk_type FROM vetter_exclusions ve "
        "JOIN vetter_runs vr ON vr.run_id = ve.run_id "
        "WHERE vr.source_ranking_run_id = :srid"
    ), {"srid": run["source_ranking_run_id"]})).mappings().all()
    excluded = {r["ticker"]: r["risk_type"] for r in exc_rows}

    audit = classify_candidates(candidates, selected, excluded, worst_rank)
    fwd = await _forward_returns_bulk(conn, [a["ticker"] for a in audit], run["portfolio_date"])
    for a in audit:
        a["fwd_return"] = fwd.get(a["ticker"])

    def _avg(cls):
        v = [a["fwd_return"] for a in audit if a["outcome"] == cls and a["fwd_return"] is not None]
        return round(sum(v) / len(v), 4) if v else None

    return {
        "portfolio_date": str(run["portfolio_date"]),
        "fwd_window_days": (px_date - run["portfolio_date"]).days if px_date else None,
        "candidate_count": len(audit),
        "selected_count": len(selected),
        "worst_selected_rank": worst_rank,
        "avg_fwd_return_by_outcome": {c: _avg(c) for c in
                                      ("selected", "cap_blocked", "vetter_excluded", "out_ranked")},
        "note": ("cap_blocked = ranked above the last pick but skipped by the builder "
                 "(diversification caps / vol-adjusted score) — if this class beats "
                 "'selected', construction is rejecting winners the rank found. "
                 "out_ranked beating selected implicates the FACTOR MODEL instead."),
        "candidates": audit,
    }


async def _universe_snapshot(conn) -> dict:
    """Shape of the investable universe feeding the rank — so pool-size or
    coverage problems are visible (a great rank over a broken pool still loses)."""
    rr = (await conn.execute(text(
        "SELECT universe_count, ranked_count, dropped_count, rank_date "
        "FROM ranking_runs WHERE status='success' ORDER BY started_at DESC LIMIT 1"
    ))).mappings().first()
    snap = (await conn.execute(text(
        "SELECT COUNT(*) AS n FROM universe_tickers "
        "WHERE snapshot_id = (SELECT MAX(id) FROM universe_snapshots)"
    ))).mappings().first()
    return {
        "active_listed_tickers": snap["n"] if snap else None,
        "latest_rank_date": str(rr["rank_date"]) if rr else None,
        "scored_universe": rr["universe_count"] if rr else None,
        "ranked_after_gates": rr["ranked_count"] if rr else None,
        "dropped_by_gates": rr["dropped_count"] if rr else None,
    }


async def _gate_audit(conn) -> dict:
    """What the universe FILTERS cost us — the stage BEFORE selection_audit.
    Names that were factor-scored but never ranked (dropped by
    min_non_null_factors / required_factors / investability gates), with their
    null-factor lists, forward returns since rank_date, and first-price dates
    (a recent first-price date on a big dropped mover = the young-listing /
    recent-IPO blind spot: history-hungry factors exclude it for ~a year)."""
    px_date = await _latest_price_date(conn)
    run = None
    if px_date:
        run = (await conn.execute(text(
            "SELECT run_id, source_factor_run_id, rank_date FROM ranking_runs "
            "WHERE status='success' AND rank_date <= :cutoff "
            "ORDER BY started_at DESC LIMIT 1"
        ), {"cutoff": px_date - timedelta(days=FWD_MIN_DAYS)})).mappings().first()
    if not run:
        run = (await conn.execute(text(
            "SELECT run_id, source_factor_run_id, rank_date FROM ranking_runs "
            "WHERE status='success' ORDER BY started_at DESC LIMIT 1"
        ))).mappings().first()
    if not run:
        return {"note": "no successful ranking run yet"}

    dropped_rows = (await conn.execute(text(
        "SELECT fs.ticker, fs.scores FROM factor_scores fs "
        "WHERE fs.run_id = :frid AND fs.ticker NOT IN "
        "  (SELECT ticker FROM rankings WHERE run_id = :rrid)"
    ), {"frid": run["source_factor_run_id"], "rrid": run["run_id"]})).mappings().all()

    no_factor_row = (await conn.execute(text(
        "SELECT COUNT(*) FROM universe_tickers ut "
        "WHERE ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
        "  AND ut.ticker NOT IN (SELECT ticker FROM factor_scores WHERE run_id = :frid)"
    ), {"frid": run["source_factor_run_id"]})).scalar()

    dropped = []
    for r in dropped_rows:
        scores = r["scores"] or {}
        nulls = sorted(k for k, v in scores.items() if v is None)
        dropped.append({"ticker": r["ticker"], "null_factors": nulls})

    fwd = await _forward_returns_bulk(conn, [d["ticker"] for d in dropped], run["rank_date"])
    for d in dropped:
        d["fwd_return"] = fwd.get(d["ticker"])
    scored = [d["fwd_return"] for d in dropped if d["fwd_return"] is not None]

    top = sorted((d for d in dropped if d["fwd_return"] is not None),
                 key=lambda d: -d["fwd_return"])[:15]
    if top:
        fp = (await conn.execute(text(
            "SELECT ticker, MIN(date) AS first_d FROM daily_prices "
            "WHERE ticker = ANY(:tk) GROUP BY ticker"
        ), {"tk": [d["ticker"] for d in top]})).mappings().all()
        first_price = {r["ticker"]: str(r["first_d"]) for r in fp}
        for d in top:
            d["first_price_date"] = first_price.get(d["ticker"])

    return {
        "rank_date": str(run["rank_date"]),
        "fwd_window_days": (px_date - run["rank_date"]).days if px_date else None,
        "dropped_after_scoring": len(dropped),
        "no_factor_row_count": no_factor_row,
        "dropped_with_price_data": len(scored),
        "avg_fwd_return_of_dropped": round(sum(scored) / len(scored), 4) if scored else None,
        "top_dropped_movers": top,
        "note": ("Names the gates excluded BEFORE ranking. null_factors shows which "
                 "factor(s) were missing (momentum/low_volatility null on a name with a "
                 "recent first_price_date = young listing starved of history). Big "
                 "positive fwd_return here = the filter mechanism cost us a winner; "
                 "no_factor_row_count = names with no price/fundamental coverage at all."),
    }


async def _risk_gate_stats(conn) -> dict:
    """How the hard safety gate actually behaved (last 30d) — evidence for
    critiquing risk limits (e.g. a cap that repeatedly blocks planned entries)."""
    totals = (await conn.execute(text(
        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE approved) AS approved "
        "FROM risk_decisions WHERE created_at >= NOW() - INTERVAL '30 days'"
    ))).mappings().first()
    by_rule = (await conn.execute(text(
        "SELECT rule_triggered, COUNT(*) AS n, COUNT(DISTINCT ticker) AS tickers "
        "FROM risk_decisions "
        "WHERE NOT approved AND created_at >= NOW() - INTERVAL '30 days' "
        "GROUP BY rule_triggered ORDER BY n DESC"
    ))).mappings().all()
    samples = (await conn.execute(text(
        "SELECT ticker, action, rule_triggered, reason, created_at::date AS d "
        "FROM risk_decisions WHERE NOT approved "
        "ORDER BY created_at DESC LIMIT 5"
    ))).mappings().all()
    return {
        "window_days": 30,
        "checks": totals["total"], "approved": totals["approved"],
        "rejected": (totals["total"] or 0) - (totals["approved"] or 0),
        "rejections_by_rule": [dict(r) for r in by_rule],
        "recent_rejections": [{**dict(s), "d": str(s["d"]),
                               "reason": (s["reason"] or "")[:150]} for s in samples],
    }


async def _factor_coverage(conn) -> dict:
    """Per-factor non-null coverage in the latest factor run — evidence for
    ingestion gaps (a factor can't earn IC on names where its inputs are missing)."""
    run = (await conn.execute(text(
        "SELECT run_id FROM factor_runs WHERE status='success' "
        "ORDER BY started_at DESC LIMIT 1"
    ))).mappings().first()
    if not run:
        return {"note": "no factor run yet"}
    # NB: jsonb_each outputs columns (key, value) and factor_scores ALSO has a
    # `value` column (the value factor) — unqualified refs are ambiguous, so the
    # lateral MUST be aliased and every ref qualified (the W27 packet-killer).
    rows = (await conn.execute(text(
        "SELECT kv.key AS factor, "
        "       COUNT(*) FILTER (WHERE kv.value <> 'null'::jsonb) AS non_null, "
        "       COUNT(*) AS total "
        "FROM factor_scores fs, LATERAL jsonb_each(fs.scores) AS kv "
        "WHERE fs.run_id = :rid GROUP BY kv.key ORDER BY kv.key"
    ), {"rid": run["run_id"]})).mappings().all()
    return {k["factor"]: {"coverage": round(k["non_null"] / k["total"], 3) if k["total"] else None,
                          "non_null": k["non_null"], "total": k["total"]} for k in rows}


def _system_architecture() -> dict:
    """The static brief + the LIVE factor surface (registry vs actually-weighted),
    so 'missing factor' findings are grounded in what exists vs what is dormant."""
    from stock_strategy_shared.factor_registry import FACTOR_NAMES
    weights: dict | None = {}
    weights_error: str | None = None
    try:
        cfg, _ = load_strategy(os.getenv("STRATEGY_CONFIG_PATH", ""))
        w = cfg.static_factor_weights
        if w is None:
            w = next(iter(cfg.factor_weights.values()))
        weights = {k: v for k, v in w.model_dump().items() if v}
    except Exception as exc:  # noqa: BLE001
        # Audit finding: a swallowed load failure used to leave weights={} and
        # therefore report EVERY factor as dormant — fabricated structural
        # evidence the prompt explicitly reasons from ("candidates for
        # activation"). Surface the failure; never claim dormancy we can't know.
        weights = None
        weights_error = str(exc)[:300]
    out = {
        "brief": ARCHITECTURE_BRIEF,
        "factors_computed": sorted(FACTOR_NAMES),
        "factors_weighted": weights,
        "factors_dormant": (sorted(set(FACTOR_NAMES) - set(weights))
                            if weights is not None else None),
    }
    if weights_error:
        out["factor_weights_error"] = (
            f"active strategy config failed to load ({weights_error}) — "
            "weighted/dormant factor lists UNAVAILABLE this review, do not "
            "infer dormancy")
    return out


async def _current_book(conn) -> dict:
    """Latest successful target portfolio: holdings + per-name beta/sector +
    weighted book beta. What the strategy WANTS to hold right now."""
    run = (await conn.execute(text(
        "SELECT run_id, portfolio_date, config_hash FROM portfolio_runs "
        "WHERE status='success' ORDER BY started_at DESC LIMIT 1"
    ))).mappings().first()
    if not run:
        return {"note": "no successful portfolio run yet"}
    holdings = (await conn.execute(text(
        "SELECT ph.ticker, ph.weight, ph.original_rank, ph.composite_score, "
        "       r.factor_scores, n.sector "
        "FROM portfolio_holdings ph "
        "LEFT JOIN rankings r ON r.run_id = ph.source_ranking_run_id AND r.ticker = ph.ticker "
        "LEFT JOIN (SELECT DISTINCT ON (ticker) ticker, sector FROM universe_tickers "
        "           WHERE sector IS NOT NULL "
        "           ORDER BY ticker, snapshot_id DESC) n ON n.ticker = ph.ticker "
        "WHERE ph.run_id = :rid ORDER BY ph.weight DESC"
    ), {"rid": run["run_id"]})).mappings().all()

    out, book_beta, beta_w = [], 0.0, 0.0
    sector_weights: dict[str, float] = {}
    for h in holdings:
        fs = h["factor_scores"] or {}
        beta = fs.get("beta")
        w = float(h["weight"])
        if beta is not None:
            book_beta += w * float(beta)
            beta_w += w
        sector = h["sector"] or "Unknown"
        sector_weights[sector] = round(sector_weights.get(sector, 0.0) + w, 4)
        out.append({"ticker": h["ticker"], "weight": _r(w), "rank": h["original_rank"],
                    "score": _r(h["composite_score"]), "beta": beta, "sector": sector})
    return {
        "portfolio_date": str(run["portfolio_date"]),
        "config_hash": run["config_hash"],
        "position_count": len(out),
        "weighted_beta": round(book_beta / beta_w, 3) if beta_w > 0 else None,
        "sector_weights": dict(sorted(sector_weights.items(), key=lambda kv: -kv[1])),
        "holdings": out,
    }


async def _config_history(conn) -> list[dict]:
    """When did the effective config change? (distinct config_hash spans over
    portfolio runs — lets the LLM attribute behavior changes to config changes)."""
    rows = (await conn.execute(text(
        "SELECT config_hash, MIN(portfolio_date) AS first_d, MAX(portfolio_date) AS last_d, "
        "       COUNT(*) AS runs "
        "FROM portfolio_runs WHERE status='success' AND config_hash IS NOT NULL "
        "GROUP BY config_hash ORDER BY MIN(portfolio_date) DESC LIMIT 12"
    ))).mappings().all()
    return [{"config_hash": r["config_hash"], "first_seen": str(r["first_d"]),
             "last_seen": str(r["last_d"]), "runs": r["runs"]} for r in rows]


async def _applied_config_changes(conn) -> list[dict]:
    """One-click applies (evaluator Phase 3, config_changes audit): which of
    YOUR past recommendations the human actually applied, when, and what
    changed — ground truth for the 'was it adopted' scoring, no YAML-diff
    guessing needed."""
    rows = (await conn.execute(text(
        "SELECT applied_at, config_field, old_value, new_value, "
        "       config_hash_before, config_hash_after, "
        "       source_report_run_id::text AS source_report_run_id "
        "FROM config_changes ORDER BY applied_at DESC LIMIT 20"
    ))).mappings().all()
    return [{"applied_at": str(r["applied_at"]), "config_field": r["config_field"],
             "old_value": r["old_value"], "new_value": r["new_value"],
             "config_hash_before": r["config_hash_before"],
             "config_hash_after": r["config_hash_after"],
             "source_report_run_id": r["source_report_run_id"]} for r in rows]


async def _error_digest(conn) -> dict:
    """Actual failure TEXT from the last 14 days, deduped — not just counts.
    system_health tells the model THAT runs failed; this tells it WHY without
    spending a sql_query tool call. Only DB-persisted errors appear (container
    stdout is ingested nowhere); a run that dies before writing its row is
    still invisible — treat absence of errors here as weak evidence only."""
    rows = (await conn.execute(text(
        "SELECT source, msg, ts FROM ("
        "  SELECT 'ingest_runs' AS source, error_message AS msg, started_at AS ts "
        "    FROM ingest_runs WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'factor_runs', error_message, started_at FROM factor_runs "
        "    WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'ranking_runs', error_message, started_at FROM ranking_runs "
        "    WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'portfolio_runs', error_message, started_at FROM portfolio_runs "
        "    WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'vetter_runs', error_message, started_at FROM vetter_runs "
        "    WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'delta_runs', error_message, started_at FROM delta_runs "
        "    WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'alpaca_sync_runs', error_message, started_at FROM alpaca_sync_runs "
        "    WHERE error_message IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'alpaca_orders:' || status, COALESCE(error_message, risk_reason), "
        "         created_at FROM alpaca_orders "
        "    WHERE status IN ('failed', 'risk_rejected') "
        "      AND COALESCE(error_message, risk_reason) IS NOT NULL "
        "  UNION ALL "
        "  SELECT 'risk_rejection:' || COALESCE(rule_triggered, '?'), reason, "
        "         created_at FROM risk_decisions "
        "    WHERE approved = FALSE AND reason IS NOT NULL"
        ") e WHERE ts >= NOW() - INTERVAL '14 days' ORDER BY ts DESC LIMIT 300"
    ))).mappings().all()
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r["source"], str(r["msg"])[:200])
        if key in seen:
            seen[key]["occurrences"] += 1
        else:
            seen[key] = {"source": r["source"], "last_seen": str(r["ts"]),
                         "occurrences": 1, "message": str(r["msg"])[:400]}
    digest = list(seen.values())[:20]
    return {
        "window_days": 14,
        "distinct_errors": len(seen),
        "errors": digest,
        "note": ("DB-persisted failure text only (deduped, newest first; "
                 "RESTART_ABORTED: prefixes are recovered restarts, usually "
                 "benign). Container-log-only exceptions are NOT captured — "
                 "absence of errors here is weak evidence of health; "
                 "cross-check system_health counts."),
    }


async def _system_health(conn) -> dict:
    """Ops caveats so the LLM doesn't misread an outage as alpha decay."""
    out: dict[str, Any] = {}
    for tbl, datecol in (("ranking_runs", "started_at"), ("portfolio_runs", "started_at"),
                         ("ingest_runs", "started_at"), ("delta_runs", "started_at")):
        # 'partial_success' counts as ok: av-ingestor stamps it whenever ANY
        # ticker errored during a fetch, which is nearly every night on a
        # full-universe run. Counting only 'success' made ingest read 0/0 while
        # the chain ran fine (the W29 report's "run-accounting artifact").
        row = (await conn.execute(text(
            f"SELECT COUNT(*) FILTER (WHERE status='failed') AS failed, "
            f"       COUNT(*) FILTER (WHERE status IN ('success','partial_success')) AS ok "
            f"FROM {tbl} WHERE {datecol} >= NOW() - INTERVAL '14 days'"
        ))).fetchone()
        out[tbl] = {"failed_14d": row[0], "success_14d": row[1]}
    deg = (await conn.execute(text(
        "SELECT COUNT(*) FROM ranking_runs "
        "WHERE degraded IS TRUE AND started_at >= NOW() - INTERVAL '14 days'"
    ))).scalar()
    out["degraded_rankings_14d"] = deg
    return out


# ── assembly ──────────────────────────────────────────────────────────────────

async def build_packet(engine, as_of: date | None = None) -> dict:
    """Assemble the full evaluator packet. Never raises; sections degrade."""
    as_of = as_of or datetime.now(timezone.utc).date()
    async with engine.connect() as conn:
        packet = {
            "schema_version": 1,
            "as_of_date": str(as_of),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "system_architecture": await _section(lambda: _async_wrap(_system_architecture)),
            "strategy_config": await _section(lambda: _async_wrap(_strategy_config_section)),
            "universe_snapshot": await _section(lambda: _universe_snapshot(conn), conn),
            "gate_audit": await _section(lambda: _gate_audit(conn), conn),
            "selection_audit": await _section(lambda: _selection_audit(conn), conn),
            "factor_coverage": await _section(lambda: _factor_coverage(conn), conn),
            "risk_gate_stats": await _section(lambda: _risk_gate_stats(conn), conn),
            "factor_evidence_weekly": await _section(lambda: _weekly_evidence(conn), conn),
            "prior_reviews": await _section(lambda: _prior_reviews(conn), conn),
            "account_performance": await _section(lambda: _account_performance(conn), conn),
            "closed_trades": await _section(lambda: _closed_trades(conn), conn),
            "open_positions": await _section(lambda: _open_positions(conn), conn),
            "decision_outcomes": await _section(lambda: _decision_outcomes(conn), conn),
            "score_calibration": await _section(lambda: _score_calibration(conn), conn),
            "shadow_vs_champion": await _section(lambda: _shadow_vs_champion(conn), conn),
            "vetter_outcomes": await _section(lambda: _vetter_outcomes(conn), conn),
            "exit_outcomes": await _section(lambda: _exit_outcomes(conn), conn),
            "invisible_bench": await _section(lambda: _invisible_bench(conn), conn),
            "benchmark_coverage": await _section(lambda: _benchmark_coverage(conn), conn),
            "current_target_book": await _section(lambda: _current_book(conn), conn),
            "config_history": await _section(lambda: _config_history(conn), conn),
            "applied_config_changes": await _section(lambda: _applied_config_changes(conn), conn),
            "system_health": await _section(lambda: _system_health(conn), conn),
            "error_digest": await _section(lambda: _error_digest(conn), conn),
            "hypothesis_ledger": await _section(lambda: _hypothesis_ledger(conn), conn),
            "backtest_lab": await _section(lambda: _async_wrap(_backtest_lab)),
        }
    return packet


def _backtest_lab() -> dict:
    """Results bridge from the ISOLATED deep-history backtest stack: the latest
    walk-forward sweep leaderboard, exported by bt-scheduler to
    artifacts/bt/latest_sweep.json (one-way file — no network path between the
    stacks). This is the DECISION-GRADE evidence channel: multi-year Sharadar
    data, point-in-time fundamentals, out-of-sample scoring. Prefer it over the
    short live-history config replay when both speak to a thesis."""
    path = os.path.join(os.getenv("ARTIFACTS_PATH", "/artifacts"), "bt", "latest_sweep.json")
    try:
        with open(path) as f:
            art = json.load(f)
    except (OSError, ValueError):
        return {"available": False,
                "experiment_queue": _experiment_queue(),
                "note": ("no wind-tunnel results yet (backtest stack not run / "
                         "bridge artifact absent) — deep-history validation "
                         "unavailable this review")}
    gen = str(art.get("generated_at", ""))
    stale = False
    try:
        age_days = (datetime.now(timezone.utc)
                    - datetime.fromisoformat(gen).astimezone(timezone.utc)).days
        stale = age_days > 21
    except ValueError:
        age_days = None
    return {
        "available": True,
        "generated_at": gen,
        "age_days": age_days,
        "stale": stale,
        "windows": art.get("windows"),
        "n_configs": art.get("n_configs"),
        "leaderboard_top": (art.get("leaderboard") or [])[:15],
        "experiment_queue": _experiment_queue(),
        "note": ("walk-forward sweep from the isolated Sharadar backtester — ranked "
                 "by OUT-OF-SAMPLE sharpe; overfit_gap = in-sample − out-of-sample "
                 "(large gap = fit the tune window, not the market). Decision-grade "
                 "relative to the live replay's short history. Leaderboard rows "
                 "tagged proposal=true are YOUR past recommendations, auto-queued "
                 "as experiments — score them against their OOS results before "
                 "re-recommending or retracting."
                 + (" WARNING: results are STALE (>21d old) — weigh accordingly."
                    if stale else "")),
    }


def _experiment_queue() -> dict:
    """State of the auto-fed proposal queue (artifacts/bt/proposals.json):
    every actionable recommendation from past reviews and where it is in the
    pipeline — pending (awaiting the weekly sweep), testing (in the running
    sweep), tested (results in the leaderboard)."""
    path = os.path.join(os.getenv("ARTIFACTS_PATH", "/artifacts"), "bt", "proposals.json")
    try:
        with open(path) as f:
            entries = (json.load(f) or {}).get("proposals") or []
    except (OSError, ValueError):
        return {"available": False}
    by_status: dict[str, int] = {}
    for e in entries:
        by_status[str(e.get("status"))] = by_status.get(str(e.get("status")), 0) + 1
    # origin/hypothesis: exploratory entries queued by the queue_experiment tool
    # carry the thesis they test — shown so results can be scored against it.
    recent = [{k: v for k in
               ("config_field", "value", "status", "iso_week", "confidence",
                "origin", "hypothesis")
               if (v := e.get(k)) is not None}
              for e in entries[-15:]]
    return {"available": True, "counts": by_status, "recent": recent}


async def _hypothesis_ledger(conn) -> dict:
    """The evaluator's own cross-week memory (written by its hypothesis_ledger
    tool): open theses + recently resolved ones. Read deterministically here so
    every review starts from the same ledger state without needing a tool call."""
    open_rows = (await conn.execute(text(
        "SELECT id, status, hypothesis, planned_test, outcome, "
        "created_iso_year, created_iso_week, created_at::date AS created, "
        "updated_at::date AS updated FROM evaluator_hypotheses "
        "WHERE status = 'open' ORDER BY created_at ASC LIMIT 20"
    ))).mappings().all()
    closed_rows = (await conn.execute(text(
        "SELECT id, status, hypothesis, outcome, updated_at::date AS resolved "
        "FROM evaluator_hypotheses WHERE status <> 'open' "
        "ORDER BY updated_at DESC LIMIT 10"
    ))).mappings().all()
    return {
        "open": [dict(r) for r in open_rows],
        "recently_resolved": [dict(r) for r in closed_rows],
        "note": ("your durable memory — resolve open entries this week's evidence "
                 "settles (hypothesis_ledger tool, action=update); open new ones for "
                 "theses that need future data instead of re-deriving them next week"),
    }


async def _async_wrap(fn):
    return fn()
