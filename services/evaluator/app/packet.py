"""Deterministic weekly evidence packet for the LLM evaluator (Phase 1).

Read-only. Assembles EVERYTHING the frontier model needs to judge "does this system
pick winners?" from Postgres. Every section is BEST-EFFORT: a failing section becomes
{"error": "..."} instead of sinking the whole packet, so a partial database (early in
the system's life) still yields a usable report — the LLM is told what's missing.

No LLM calls here; no writes. The packet is persisted verbatim on the report row so
every recommendation can be audited against exactly the data the model saw.
"""
from __future__ import annotations

import os
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text

from stock_strategy_shared.loader import load_strategy

TRADE_LOOKBACK_DAYS = int(os.getenv("EVALUATOR_TRADE_LOOKBACK_DAYS", "365"))
WEEKLY_PACKETS = int(os.getenv("EVALUATOR_WEEKLY_PACKETS", "12"))
VETTER_LOOKBACK_DAYS = int(os.getenv("EVALUATOR_VETTER_LOOKBACK_DAYS", "90"))


def _f(v) -> float | None:
    return None if v is None else float(v)


def _r(v, nd=4) -> float | None:
    return None if v is None else round(float(v), nd)


async def _section(fn: Callable[[], Awaitable[Any]]) -> Any:
    """Run one packet section; degrade to an error marker instead of raising."""
    try:
        return await fn()
    except Exception as exc:  # noqa: BLE001 — a missing table must not sink the packet
        traceback.print_exc()
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


async def _hypotheses(conn) -> list[dict]:
    rows = (await conn.execute(text(
        "SELECT id, statement, status, config_diff, economic_rationale, "
        "weeks_supported, weeks_total, confidence FROM evaluator_hypotheses "
        "ORDER BY last_updated DESC LIMIT 50"
    ))).mappings().all()
    return [dict(r) for r in rows]


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
        if not spy or len(curve) < 2:
            return None
        end_d = date.fromisoformat(curve[-1]["date"])
        start_d = date.fromisoformat(curve[0]["date"])
        if days is not None:
            start_d = max(start_d, end_d - timedelta(days=days))
        s = [c for d, c in sorted(spy.items()) if start_d <= d <= end_d]
        if len(s) < 2:
            return None
        return round(s[-1] / s[0] - 1.0, 4)

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
    out = []
    for r in rows[:80]:
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
        "exclusions": out,
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
    out = []
    for r in rows[:60]:
        fwd = await _forward_return_since(conn, r["ticker"], r["d"])
        out.append({"ticker": r["ticker"], "exited_on": str(r["d"]),
                    "fwd_return_since": fwd, "reason": (r["reason"] or "")[:200]})
    scored = [o for o in out if o["fwd_return_since"] is not None]
    return {
        "lookback_days": VETTER_LOOKBACK_DAYS,
        "exit_count": len(out),
        "avg_fwd_return_after_exit": (
            round(sum(o["fwd_return_since"] for o in scored) / len(scored), 4) if scored else None),
        "exits": out,
    }


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
        "           WHERE snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
        "           ORDER BY ticker, id ASC) n ON n.ticker = ph.ticker "
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


async def _system_health(conn) -> dict:
    """Ops caveats so the LLM doesn't misread an outage as alpha decay."""
    out: dict[str, Any] = {}
    for tbl, datecol in (("ranking_runs", "started_at"), ("portfolio_runs", "started_at"),
                         ("ingest_runs", "started_at"), ("delta_runs", "started_at")):
        row = (await conn.execute(text(
            f"SELECT COUNT(*) FILTER (WHERE status='failed') AS failed, "
            f"       COUNT(*) FILTER (WHERE status='success') AS ok "
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
            "strategy_config": await _section(lambda: _async_wrap(_strategy_config_section)),
            "factor_evidence_weekly": await _section(lambda: _weekly_evidence(conn)),
            "hypotheses_ledger": await _section(lambda: _hypotheses(conn)),
            "account_performance": await _section(lambda: _account_performance(conn)),
            "closed_trades": await _section(lambda: _closed_trades(conn)),
            "open_positions": await _section(lambda: _open_positions(conn)),
            "vetter_outcomes": await _section(lambda: _vetter_outcomes(conn)),
            "exit_outcomes": await _section(lambda: _exit_outcomes(conn)),
            "current_target_book": await _section(lambda: _current_book(conn)),
            "config_history": await _section(lambda: _config_history(conn)),
            "system_health": await _section(lambda: _system_health(conn)),
        }
    return packet


async def _async_wrap(fn):
    return fn()
