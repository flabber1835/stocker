from __future__ import annotations
import asyncio
import json
import os
import re
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
import httpx

from sqlalchemy.ext.asyncio import create_async_engine
from stock_strategy_shared.db import warm_up_db_in_background
from stock_strategy_shared.tracing import fmt_row
from stock_strategy_shared.order_status import open_status_sql, turnover_status_sql
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.factor_registry import FACTOR_NAMES, FACTOR_LABELS

DATABASE_URL          = os.getenv("DATABASE_URL", "")
# Active strategy file (read-only) — exposes the live factor weights so the screener
# detail card can annotate every (generic-engine) factor with its current weight.
# Mounted into the api the same way as the other strategy consumers.
STRATEGY_CONFIG_PATH  = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/momentum_rotation_v2.yaml")
TRADE_EXECUTOR_URL    = os.getenv("TRADE_EXECUTOR_URL",    "http://trade-executor:8000")
ALPACA_SYNC_URL       = os.getenv("ALPACA_SYNC_URL",       "http://alpaca-sync:8000")
PIPELINE_URL          = os.getenv("PIPELINE_URL",          "http://pipeline:8000")
VETTER_URL            = os.getenv("VETTER_URL",            "http://llm-vetter:8000")
AV_INGESTOR_URL       = os.getenv("AV_INGESTOR_URL",       "http://av-ingestor:8000")
PORTFOLIO_BUILDER_URL = os.getenv("PORTFOLIO_BUILDER_URL", "http://portfolio-builder:8000")
SCHEDULER_URL         = os.getenv("SCHEDULER_URL",         "http://scheduler:8000")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=8, max_overflow=12,
                             pool_timeout=10,
                             connect_args={"timeout": 60}) if DATABASE_URL else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    # Warm up DB in background so /health responds immediately. Blocking here
    # causes docker healthcheck failures + restart loop on slow NAS hardware.
    warm_up_db_in_background(engine, "api")
    yield


app = FastAPI(title="stocker-api", lifespan=lifespan)


_TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')


def _validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker symbol. Raises 400 on invalid format."""
    ticker = ticker.upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker format: {ticker!r}")
    return ticker


def _linear_slope(ranks: list[float]) -> float | None:
    """OLS slope for an ordered sequence of rank values (x = 0, 1, 2, ...).

    Mirrors the SQL REGR_SLOPE(rank, row_number) logic used in /rankings.
    x indices are always equally-spaced integers — actual date gaps (weekends,
    holidays, missed runs) are intentionally collapsed so every recorded
    rank_date counts as one step. Note the SQL collapses multiple runs on the
    SAME rank_date to one point (most recent run wins), so re-running the chain
    any number of times in a day does not flush the trend window — callers should
    pass one rank value per distinct date. Returns None for fewer than 2 points.
    """
    n = len(ranks)
    if n < 2:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ranks) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ranks))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


@app.get("/data-freshness")
async def data_freshness():
    """Return the latest timestamp for each data layer so the UI can display data age."""
    async with engine.connect() as conn:
        prices_row = (await conn.execute(text(
            "SELECT MAX(date) AS max_date, MAX(fetched_at) AS last_fetched FROM daily_prices"
        ))).mappings().first()

        funds_row = (await conn.execute(text(
            "SELECT MAX(as_of_date) AS max_date, MAX(fetched_at) AS last_fetched FROM fundamentals"
        ))).mappings().first()

        factors_row = (await conn.execute(text(
            "SELECT score_date, completed_at FROM factor_runs "
            "WHERE status='success' ORDER BY score_date DESC, completed_at DESC NULLS LAST LIMIT 1"
        ))).mappings().first()

        rankings_row = (await conn.execute(text(
            "SELECT rank_date, completed_at FROM ranking_runs "
            "WHERE status='success' ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
        ))).mappings().first()

    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)

    return {
        "prices": {
            "max_date":     _iso(prices_row["max_date"])     if prices_row else None,
            "last_fetched": _iso(prices_row["last_fetched"]) if prices_row else None,
        },
        "fundamentals": {
            "max_date":     _iso(funds_row["max_date"])     if funds_row else None,
            "last_fetched": _iso(funds_row["last_fetched"]) if funds_row else None,
        },
        "factors": {
            "score_date":   _iso(factors_row["score_date"])   if factors_row else None,
            "completed_at": _iso(factors_row["completed_at"]) if factors_row else None,
        },
        "rankings": {
            "rank_date":    _iso(rankings_row["rank_date"])    if rankings_row else None,
            "completed_at": _iso(rankings_row["completed_at"]) if rankings_row else None,
        },
    }


# ── Regime ────────────────────────────────────────────────────────────────────────────────────

@app.get("/regime")
async def get_regime():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT regime, spy_price, spy_sma_slow, spy_vs_sma, realized_vol, calculated_at "
                "FROM regime_snapshots ORDER BY snapshot_date DESC, calculated_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        return {"regime": None}
    return fmt_row(result)


@app.get("/strategy/factor-weights")
async def get_factor_weights():
    """Active strategy's effective factor weights — lets the detail card annotate
    EVERY generic-engine factor with its current weight (a 0 reads as 'computed,
    not weighted', not broken). regime rotation off → the single static vector;
    on → the latest detected regime's vector. Degrades to {weights:null} if the
    strategy file isn't mounted, so the card just omits the annotation."""
    try:
        cfg, _ = load_strategy(STRATEGY_CONFIG_PATH)
    except Exception:  # noqa: BLE001 — file missing/unreadable → annotation simply absent
        return {"weights": None, "strategy_id": None, "regime_weighting_enabled": None, "regime": None}

    regime = None
    if cfg.regime_weighting_enabled:
        async with engine.connect() as conn:
            r = await conn.execute(text(
                "SELECT regime FROM regime_snapshots ORDER BY snapshot_date DESC, calculated_at DESC LIMIT 1"))
            row = r.fetchone()
        regime = row[0] if row else None
        if regime not in cfg.factor_weights:        # guard against a stale/missing regime key
            regime = next(iter(cfg.factor_weights))
    weights = cfg.effective_factor_weights(regime or "").model_dump()
    return {
        "weights": weights,
        # registry-ordered (key,label) list so the dashboard derives its factor chips
        # from the single source — a new factor appears automatically, no JS edit.
        "factors": [{"key": n, "label": FACTOR_LABELS[n]} for n in FACTOR_NAMES],
        "strategy_id": cfg.strategy_id,
        "regime_weighting_enabled": cfg.regime_weighting_enabled,
        "regime": regime,
    }


# ── Config apply (evaluator Phase 3 — one-click HUMAN-APPROVED apply) ──────────
# The dashboard's Apply click is the human approval. This endpoint is
# deterministic transport: parse the recommendation's literal value, apply the
# SINGLE dotted-path diff, validate the ENTIRE new config through the
# strategy-validator SERVICE (fail-closed: unreachable/invalid → no write),
# archive before+after under /artifacts/config/, atomically replace the active
# YAML, and record a config_changes audit row. The LLM never reaches this path.
# See docs/architecture.md "evaluator Phase 3 — one-click apply".

STRATEGY_VALIDATOR_URL = os.getenv("STRATEGY_VALIDATOR_URL", "http://strategy-validator:8000")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "/artifacts")

_config_apply_lock = asyncio.Lock()


class ConfigApplyRequest(BaseModel):
    config_field: Optional[str] = None
    suggested_value: str | float | int | bool | None = None
    # PAIRED/BATCH apply: {dotted.field: suggested_value, ...} applied in ONE
    # atomic validate+write. Needed for coupled edits that are individually
    # schema-invalid — e.g. the W29 factor reweight (near_high 0.06→0 funds
    # low_volatility 0.08→0.14): either field alone breaks the weights-sum-to-1
    # invariant and is rightly rejected; together they validate. When `changes`
    # is set, config_field/suggested_value are ignored.
    changes: Optional[dict[str, str | float | int | bool | None]] = None
    source_report_run_id: Optional[str] = None
    recommendation_index: Optional[int] = None
    confirm: bool = False


def _hash_raw(raw: str) -> str:
    import hashlib
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _archive_config(subdir: str, stamp: str, cfg_hash: str, raw: str) -> Optional[str]:
    try:
        d = os.path.join(ARTIFACTS_PATH, "config", subdir)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{stamp}_{cfg_hash}.yaml")
        with open(path, "w") as f:
            f.write(raw)
        return path
    except OSError:
        return None


@app.post("/config/apply")
async def config_apply(req: ConfigApplyRequest):
    import yaml as _yaml
    from datetime import datetime as _dt, timezone as _tz

    from stock_strategy_shared.config_values import (get_dotted, parse_suggested_value,
                                                     set_dotted)

    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required — this edits the live strategy config")
    raw_changes = (req.changes if req.changes
                   else {req.config_field or "": req.suggested_value})
    edits: dict[str, Any] = {}
    for field, raw in raw_changes.items():
        if not field:
            raise HTTPException(status_code=422, detail="config_field (or changes) required")
        value, ok = parse_suggested_value(raw)
        if not ok:
            raise HTTPException(status_code=422, detail=(
                f"suggested_value {raw!r} for {field} is not a literal — prose "
                "recommendations cannot be one-click applied; edit the YAML manually"))
        edits[field] = value

    async with _config_apply_lock:
        try:
            with open(STRATEGY_CONFIG_PATH) as f:
                old_raw = f.read()
            cfg = _yaml.safe_load(old_raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"cannot read active config: {exc}")
        old_values = {f: get_dotted(cfg, f) for f in edits}
        if all(old_values[f] == v for f, v in edits.items()):
            raise HTTPException(status_code=409, detail=(
                f"{list(edits)} already at the suggested value(s) — nothing to apply"))
        for field, value in edits.items():
            err = set_dotted(cfg, field, value)
            if err:
                raise HTTPException(status_code=422, detail=err)

        # Hard gate: the WHOLE new config through the strategy-validator service.
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                vr = await client.post(f"{STRATEGY_VALIDATOR_URL}/validate", json=cfg)
        except Exception as exc:  # noqa: BLE001 — fail-closed, no write
            raise HTTPException(status_code=503, detail=(
                f"strategy-validator unreachable ({exc}) — config NOT applied"))
        vbody = {}
        try:
            vbody = vr.json()
        except Exception:  # noqa: BLE001
            pass
        if vr.status_code != 200 or not vbody.get("valid"):
            raise HTTPException(status_code=422, detail={
                "message": "strategy-validator rejected the new config — NOT applied",
                "errors": vbody.get("errors") or [vr.text[:500]]})

        new_raw = _yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False)
        hash_before, hash_after = _hash_raw(old_raw), _hash_raw(new_raw)
        stamp = _dt.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
        _archive_config("history", stamp, hash_before, old_raw)
        applied_path = _archive_config("applied", stamp, hash_after, new_raw)

        tmp = STRATEGY_CONFIG_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(new_raw)
            os.replace(tmp, STRATEGY_CONFIG_PATH)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=(
                f"config write failed ({exc}) — active file unchanged"))

        audit_ok = True
        try:
            async with engine.begin() as conn:
                for field, value in edits.items():
                    await conn.execute(text(
                        "INSERT INTO config_changes (id, config_path, config_field, old_value, "
                        " new_value, config_hash_before, config_hash_after, source_report_run_id, "
                        " recommendation_index, applied_by, validator_status) "
                        "VALUES (CAST(:id AS uuid), :path, :field, CAST(:old AS jsonb), "
                        "        CAST(:new AS jsonb), :hb, :ha, CAST(:rid AS uuid), :ridx, "
                        "        'dashboard', :vst)"
                    ), {"id": str(uuid.uuid4()), "path": STRATEGY_CONFIG_PATH,
                        "field": field, "old": json.dumps(old_values[field]),
                        "new": json.dumps(value), "hb": hash_before, "ha": hash_after,
                        "rid": req.source_report_run_id, "ridx": req.recommendation_index,
                        "vst": f"valid ({vr.status_code})"})
        except Exception:  # noqa: BLE001 — file already applied; surface, don't unwind
            traceback.print_exc()
            audit_ok = False

    return {
        "applied": True,
        "changes": {f: {"old": old_values[f], "new": v} for f, v in edits.items()},
        "config_field": next(iter(edits)),
        "old_value": old_values[next(iter(edits))],
        "new_value": edits[next(iter(edits))],
        "config_hash_before": hash_before,
        "config_hash_after": hash_after,
        "applied_artifact": applied_path,
        "audit_row_written": audit_ok,
        "note": ("takes effect on the NEXT chain run (config reloaded per run). "
                 "Active file is now ahead of git — mirror the applied artifact "
                 "into the repo before the next git-pull deploy."),
    }


@app.get("/config/changes")
async def config_changes(limit: int = 50):
    """Recent one-click config applies (audit) — dashboard badges + evaluator packet."""
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT id::text AS id, applied_at, config_field, old_value, new_value, "
                "       config_hash_before, config_hash_after, "
                "       source_report_run_id::text AS source_report_run_id, "
                "       recommendation_index, applied_by "
                "FROM config_changes ORDER BY applied_at DESC LIMIT :lim"
            ), {"lim": max(1, min(limit, 200))})).mappings().fetchall()
    except Exception:  # noqa: BLE001 — table may predate migration 0042 on old DBs
        return {"changes": []}
    return {"changes": [fmt_row(r) for r in rows]}


# ── Rankings ─────────────────────────────────────────────────────────────────────────────────

@app.get("/rankings")
async def get_rankings(limit: int = 50, run_id: str | None = None):
    if limit < 0:
        raise HTTPException(status_code=422, detail="limit must be >= 0")
    async with engine.connect() as conn:
        if run_id:
            rows = await conn.execute(
                text(
                    "WITH recent_runs AS ("
                    "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                    "  FROM ("
                    "    SELECT run_id, rank_date FROM ("
                    "      SELECT DISTINCT ON (rank_date) run_id, rank_date"
                    "      FROM ranking_runs WHERE status='success'"
                    "      ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                    "    ) latest_per_date"
                    "    ORDER BY rank_date DESC LIMIT 5"
                    "  ) recent_dates"
                    "),"
                    "ticker_slopes AS ("
                    "  SELECT r.ticker,"
                    "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                    "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                    "  GROUP BY r.ticker"
                    ")"
                    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, r.rank_date,"
                    "  r.factor_scores, ts.rank_slope "
                    "FROM rankings r LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                    "WHERE r.run_id = :run_id ORDER BY r.rank ASC LIMIT :limit"
                ),
                {"run_id": run_id, "limit": limit},
            )
        else:
            rows = await conn.execute(
                text(
                    "WITH recent_runs AS ("
                    "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                    "  FROM ("
                    "    SELECT run_id, rank_date FROM ("
                    "      SELECT DISTINCT ON (rank_date) run_id, rank_date"
                    "      FROM ranking_runs WHERE status='success'"
                    "      ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                    "    ) latest_per_date"
                    "    ORDER BY rank_date DESC LIMIT 5"
                    "  ) recent_dates"
                    "),"
                    "ticker_slopes AS ("
                    "  SELECT r.ticker,"
                    "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                    "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                    "  GROUP BY r.ticker"
                    ")"
                    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, r.rank_date,"
                    "  r.factor_scores, ts.rank_slope "
                    "FROM rankings r LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                    "WHERE r.run_id = ("
                    "  SELECT run_id FROM ranking_runs WHERE status='success'"
                    "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
                    ") ORDER BY r.rank ASC LIMIT :limit"
                ),
                {"limit": limit},
            )
        results = [dict(r) for r in rows.mappings()]
    if not results:
        return {"count": 0, "rankings": []}
    return {"count": len(results), "rankings": results}


def _intent_in_target(action: str, current_weight) -> bool:
    """Whether a delta intent represents an actual BUILDER-TARGET member — the signal
    the dashboard's "Target ✓" tick uses.

    Derived from the intent's OWN fields (delta-native), NOT a re-query of the latest
    portfolio_holdings: re-querying risks reading a portfolio build newer than the one
    THIS delta consumed (mid-chain / partial re-run), so the tick could desync from the
    delta it's shown next to. The delta engine encodes membership directly:
      - entry / buy_add / sell_trim → in target (target weight > 0)
      - watch                       → in target (a capacity-deferred entry)
      - hold with current_weight>0  → in-target hold (engine sets current_weight =
                                      target_weight for in-target holds)
      - hold with current_weight 0/None, exit, at_risk → held/orphan, NOT a target
        member (data-gap / degraded / dropped) → no tick.
    """
    if action in ("entry", "buy_add", "sell_trim", "watch"):
        return True
    if action == "hold":
        try:
            return current_weight is not None and float(current_weight) > 0.0
        except (TypeError, ValueError):
            return False
    return False


def _match_ticker_prefix(ticker: str, query: str) -> bool:
    """Case-insensitive prefix match — mirrors SQL UPPER(ticker) LIKE UPPER(:q) || '%'."""
    return ticker.upper().startswith(query.upper())


def _apply_overlays(
    ranking_rows: list[dict],
    vetter_by_ticker: dict[str, dict],
    all_broker_positions: dict[str, dict],
    *,
    inject_unranked: bool = True,
    query_prefix: str | None = None,
    held_rank_lookup: dict[str, dict] | None = None,
    cluster_by_ticker: dict[str, str] | None = None,
) -> list[dict]:
    """Decorate ranking rows with vetter and holdings overlays.

    inject_unranked: when True (default), broker-held tickers absent from rankings
        are appended. Tickers present in held_rank_lookup get their real rank/score;
        tickers absent from held_rank_lookup get rank=9999 / not_in_universe=True.
    held_rank_lookup: real DB rank rows for held tickers that fall outside the
        display window but ARE ranked (e.g. a small-cap at rank 489 when only the
        top 150 are shown). Keyed by ticker.
    query_prefix: when inject_unranked is True and a query is active, only inject
        positions whose ticker matches the prefix so search results stay on-topic.
    cluster_by_ticker: correlation-cluster id per ticker from the latest portfolio
        build (portfolio_holdings.cluster_id). Informational overlay; None when the
        ticker wasn't selected into the target or is a singleton cluster.
    """
    cluster_by_ticker = cluster_by_ticker or {}
    # Copy the list AND each row dict so the caller's `ranking_rows` is never
    # mutated: no injected broker rows appended to its list, and no overlay keys
    # written onto its row objects. Callers derive the `run`/`rank_date` metadata
    # from their ORIGINAL ranked rows (run_rows[0].rank_date), so an injected row
    # that happens to sort to index 0 of this output can never drift the reported
    # run_id/rank_date away from the actual latest run.
    out_rows = [dict(r) for r in ranking_rows]
    ranked_set = {r["ticker"] for r in out_rows}
    run_date_val = out_rows[0]["rank_date"] if out_rows else None

    if inject_unranked:
        for broker_ticker, pos in all_broker_positions.items():
            if broker_ticker in ranked_set:
                continue
            if query_prefix and not _match_ticker_prefix(broker_ticker, query_prefix):
                continue
            # Use the real rank if this ticker is ranked but simply outside the
            # current display window (e.g. a small-cap at rank 489 when top-150
            # is loaded). Fall back to 9999 only if the ticker has no ranking at
            # all (genuinely not in universe or never ranked).
            real = (held_rank_lookup or {}).get(broker_ticker)
            out_rows.append({
                "ticker": broker_ticker,
                "rank": real["rank"] if real else 9999,
                "composite_score": real.get("composite_score") if real else None,
                "percentile": real.get("percentile") if real else None,
                "regime": real.get("regime") if real else None,
                "rank_date": run_date_val,
                "factor_scores": real.get("factor_scores") if real else None,
                "rank_slope": None,
                "prior_rank": real.get("prior_rank") if real else None,
                "name": pos.get("name"),
                "sector": pos.get("sector"),
                "market_cap": pos.get("market_cap"),
                "not_in_universe": real is None,
                "cluster_id": cluster_by_ticker.get(broker_ticker),
            })

    for r in out_rows:
        t = r["ticker"]
        v = vetter_by_ticker.get(t)
        if v:
            r["vetter_excluded"] = bool(v["exclude"])
            r["vetter_confidence"] = v["confidence"]
            r["vetter_risk_type"] = v["risk_type"]
            r["vetter_reason"] = v["reason"]
            r["vetter_crashed"] = bool(v.get("crashed", False))
            r["positive_catalyst"] = bool(v["positive_catalyst"])
            r["positive_reason"] = v["positive_reason"]
        else:
            r["vetter_excluded"] = False
            r["vetter_confidence"] = None
            r["vetter_risk_type"] = None
            r["vetter_reason"] = None
            r["vetter_crashed"] = False
            r["positive_catalyst"] = False
            r["positive_reason"] = None
        pos = all_broker_positions.get(t)
        r["held"] = pos is not None
        if pos:
            r["qty"] = pos["qty"]
            r["market_value"] = pos["market_value"]
            r["unrealized_plpc"] = pos["unrealized_plpc"]
        r.setdefault("not_in_universe", False)
        # Correlation-cluster overlay (informational). setdefault so injected rows
        # that already set it above keep their value.
        r.setdefault("cluster_id", cluster_by_ticker.get(t))

    return out_rows


# ── /rankings/with-overlays caching (per ranking/vetter/sync run) ──────────────
# The overlay query is expensive (rank_slope REGR + prior_rank over the ~187k-row
# rankings table) and its result only changes when a NEW ranking, vetter, or sync
# run lands. Without caching it ran on EVERY page load/refresh, taking ~60s, which
# tripped the dashboard proxy's 60s timeout ("no data") and held a DB connection
# the whole time → the 10-conn pool exhausted under a couple of refreshes
# (QueuePool timeout). We cache the assembled payload keyed by (limit, run-key) and
# serve it instantly; a single-flight lock means concurrent refreshes share ONE
# computation; and if a stale payload exists while a fresh one is being computed we
# serve the stale one immediately (stale-while-revalidate) so a refresh never blocks
# on the recompute. Single uvicorn worker → a process-local dict is sufficient.
_overlay_cache: dict[int, dict] = {}            # limit -> {"key": run_key, "payload": dict}
_overlay_locks: dict[int, asyncio.Lock] = {}


async def _current_overlay_run_key(conn) -> tuple:
    """The identity of the data the overlay payload depends on: latest successful
    ranking run + latest vetter run + latest successful sync + latest successful
    PORTFOLIO run (cluster_id overlays come from its candidate_clusters — omitting
    it served stale cluster columns after a manual rebuild until some other run
    changed; audit finding). All four are cheap indexed LIMIT-1 reads."""
    rk = (await conn.execute(text(
        "SELECT run_id FROM ranking_runs WHERE status='success' "
        "ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"))).fetchone()
    vt = (await conn.execute(text(
        "SELECT run_id FROM vetter_runs ORDER BY completed_at DESC NULLS LAST, "
        "started_at DESC LIMIT 1"))).fetchone()
    sy = (await conn.execute(text(
        "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"))).fetchone()
    pf = (await conn.execute(text(
        "SELECT run_id FROM portfolio_runs WHERE status='success' "
        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"))).fetchone()
    return (
        str(rk.run_id) if rk else None,
        str(vt.run_id) if vt else None,
        str(sy.run_id) if sy else None,
        str(pf.run_id) if pf else None,
    )


@app.get("/rankings/with-overlays")
async def get_rankings_with_overlays(limit: int = 100, tickers: str | None = None):
    if limit < 0:
        raise HTTPException(status_code=422, detail="limit must be >= 0")
    if engine is None:
        return {"count": 0, "run": None, "prior_run": None, "rankings": []}
    # `tickers` (CSV) scopes the (expensive) overlay CTEs to a specific set instead
    # of the top-`limit`. The Target tab needs overlays for only its ~30-60
    # target+held names (some ranked far below 100); without this it fetched
    # limit=5000 — running rank_slope/prior_rank/joins over the WHOLE universe (the
    # screener's old slow-load problem, ~30x worse). Cache key includes the set.
    only_tickers = None
    if tickers:
        only_tickers = sorted({t.strip().upper() for t in tickers.split(",") if t.strip()})
        if not only_tickers:
            only_tickers = None
    cache_key = ("tickers", tuple(only_tickers)) if only_tickers else ("limit", limit)

    async with engine.connect() as conn:
        run_key = await _current_overlay_run_key(conn)

    cached = _overlay_cache.get(cache_key)
    if cached and cached["key"] == run_key:
        return cached["payload"]

    lock = _overlay_locks.setdefault(cache_key, asyncio.Lock())
    # Stale-while-revalidate: if someone is already computing and we have ANY prior
    # payload, return it now rather than queueing behind a ~60s recompute.
    if lock.locked() and cached is not None:
        return cached["payload"]

    async with lock:
        # Re-check: a prior waiter may have just populated the fresh payload.
        cached = _overlay_cache.get(cache_key)
        if cached and cached["key"] == run_key:
            return cached["payload"]
        payload = await _compute_with_overlays(limit, only_tickers)
        _overlay_cache[cache_key] = {"key": run_key, "payload": payload}
        return payload


async def _compute_with_overlays(limit: int = 100, only_tickers: list[str] | None = None):
    """
    Latest rank run, top `limit` tickers, plus per-ticker overlay flags:
    - prior_rank: rank in the immediately-prior successful rank run (for arrows)
    - rank_slope: REGR_SLOPE over the last 5 runs (existing momentum metric)
    - vetter_excluded: bool, with reason/confidence/risk_type if true
    - positive_catalyst: bool, with positive_reason if true
    - held: bool, with qty and market_value if true

    Single round-trip — assembled in one CTE-based query so the dashboard can
    drop the separate /universe + /rankings calls. Powers the consolidated
    Rankings panel.
    """
    async with engine.connect() as conn:
        # Find the latest successful rank run + its prior peer
        run_rows = (await conn.execute(text(
            "SELECT run_id, rank_date FROM ("
            "  SELECT DISTINCT ON (rank_date) run_id, rank_date"
            "  FROM ranking_runs WHERE status='success'"
            "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
            ") latest_per_date "
            "ORDER BY rank_date DESC LIMIT 2"
        ))).fetchall()
        if not run_rows:
            return {"count": 0, "run": None, "prior_run": None, "rankings": []}
        latest_run_id = str(run_rows[0].run_id)
        prior_run_id = str(run_rows[1].run_id) if len(run_rows) > 1 else None
        # rank_date of the ACTUAL latest ranked run (authoritative for run_id).
        # Captured from run_rows (not from a post-overlay list) so an injected
        # broker row sorting ahead of index 0 can never drift the reported date.
        latest_rank_date = run_rows[0].rank_date

        # Latest vetter run (any status — UI surfaces in-progress info too)
        vetter_row = (await conn.execute(text(
            "SELECT run_id FROM vetter_runs "
            "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
        ))).fetchone()
        vetter_run_id = str(vetter_row.run_id) if vetter_row else None

        # Latest successful alpaca-sync (for live positions)
        sync_row = (await conn.execute(text(
            "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ))).fetchone()
        sync_run_id = str(sync_row.run_id) if sync_row else None

        # Main rankings query.
        #
        # Scope the overlay CTEs to ONLY the top-`limit` tickers that will be
        # returned (the `displayed` CTE), mirroring /rankings/search's `matched`
        # CTE. Without this, ticker_slopes (REGR_SLOPE over all rankings × 5
        # runs), names (DISTINCT ON over the whole universe snapshot), and caps
        # (DISTINCT ON over the entire fundamentals table) are computed for the
        # FULL universe and then LEFT JOINed down to ~100 rows — O(universe)
        # work that blew past the dashboard proxy timeout on a Russell-3000-
        # scale DB (the real screener "no data" root cause). The held-but-
        # outside-window tickers injected by _apply_overlays are decorated
        # entirely from the separate live_positions query + held_rank_lookup,
        # so they don't depend on these CTEs and the `displayed` scoping does
        # not change any returned row.
        # `displayed` bounds every overlay CTE. Default = top-`limit`; when
        # only_tickers is given, scope to exactly that set (no limit) so the heavy
        # work runs over ~30 names, not the whole universe.
        _scoped = bool(only_tickers)
        _disp_filter = ("WHERE run_id = :run_id AND ticker = ANY(:only_tickers)"
                        if _scoped else
                        "WHERE run_id = :run_id ORDER BY rank ASC LIMIT :limit")
        _main_filter = ("WHERE r.run_id = :run_id AND r.ticker = ANY(:only_tickers) "
                        "ORDER BY r.rank ASC"
                        if _scoped else
                        "WHERE r.run_id = :run_id ORDER BY r.rank ASC LIMIT :limit")
        _params = {"run_id": latest_run_id, "prior_run_id": prior_run_id or latest_run_id,
                   "limit": limit}
        if _scoped:
            _params["only_tickers"] = only_tickers
        rows = await conn.execute(
            text(
                "WITH displayed AS ("
                "  SELECT ticker FROM rankings "
                + _disp_filter +
                "),"
                "recent_runs AS ("
                "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                "  FROM ("
                "    SELECT run_id, rank_date FROM ("
                "      SELECT DISTINCT ON (rank_date) run_id, rank_date"
                "      FROM ranking_runs WHERE status='success'"
                "      ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                "    ) latest_per_date"
                "    ORDER BY rank_date DESC LIMIT 5"
                "  ) recent_dates"
                "),"
                "ticker_slopes AS ("
                "  SELECT r.ticker,"
                "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                "  WHERE r.ticker IN (SELECT ticker FROM displayed)"
                "  GROUP BY r.ticker"
                "),"
                "prior_ranks AS ("
                "  SELECT ticker, rank AS prior_rank FROM rankings"
                "  WHERE run_id = :prior_run_id AND ticker IN (SELECT ticker FROM displayed)"
                "),"
                "names AS ("
                # Prefer the latest row with a NON-NULL sector: fresh weekly snapshots
                # insert sector=NULL everywhere (LISTING_STATUS has no sector).
                "  SELECT DISTINCT ON (ticker) ticker, name, sector FROM universe_tickers"
                "  WHERE ticker IN (SELECT ticker FROM displayed)"
                "  ORDER BY ticker, (sector IS NULL), snapshot_id DESC"
                "),"
                "caps AS ("
                "  SELECT DISTINCT ON (ticker) ticker, market_cap FROM fundamentals"
                "  WHERE ticker IN (SELECT ticker FROM displayed)"
                "  ORDER BY ticker, as_of_date DESC"
                ")"
                "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, r.rank_date,"
                "  r.factor_scores, ts.rank_slope, pr.prior_rank, n.name, n.sector, c.market_cap "
                "FROM rankings r "
                "LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                "LEFT JOIN prior_ranks pr ON pr.ticker = r.ticker "
                "LEFT JOIN names n ON n.ticker = r.ticker "
                "LEFT JOIN caps c ON c.ticker = r.ticker "
                + _main_filter
            ),
            _params,
        )
        ranking_rows = [dict(r) for r in rows.mappings()]
        tickers = [r["ticker"] for r in ranking_rows]
        if not tickers:
            return {"count": 0, "run": None, "prior_run": None, "rankings": []}

        # Vetter overlay (only for ranked tickers — broker-injected rows get overlaid below)
        vetter_by_ticker = {}
        if vetter_run_id:
            vd_rows = await conn.execute(
                text(
                    "SELECT ticker, exclude, confidence, risk_type, reason, "
                    "  positive_catalyst, positive_reason, crashed "
                    "FROM vetter_decisions WHERE run_id = :rid AND ticker = ANY(:tickers)"
                ),
                {"rid": vetter_run_id, "tickers": tickers},
            )
            for v in vd_rows.mappings():
                vetter_by_ticker[v["ticker"]] = dict(v)

        # Cluster overlay — correlation-cluster id per ticker from the latest
        # successful portfolio build. Informational; only the selected target names
        # carry a (multi-member) cluster, everything else is None.
        cluster_by_ticker: dict[str, str] = {}
        cl_rows = await conn.execute(text(
            "SELECT ticker, cluster_id FROM candidate_clusters "
            "WHERE run_id = (SELECT run_id FROM portfolio_runs WHERE status='success' "
            "                ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
        ))
        for c in cl_rows.mappings():
            cluster_by_ticker[c["ticker"]] = c["cluster_id"]

        # Holdings overlay — load ALL live broker positions, not just those in rankings.
        # Broker-held tickers that failed universe/ranking filters are injected below
        # so the user can always see what they hold, even if the system can't rank it.
        all_broker_positions: dict[str, dict] = {}
        if sync_run_id:
            pos_rows = await conn.execute(
                text(
                    "SELECT lp.ticker, lp.qty, lp.market_value, lp.unrealized_plpc, "
                    "  ut.name, ut.sector, fc.market_cap "
                    "FROM live_positions lp "
                    "LEFT JOIN (SELECT DISTINCT ON (ticker) ticker, name, sector "
                    "           FROM universe_tickers "
                    "           ORDER BY ticker, (sector IS NULL), snapshot_id DESC) ut "
                    "  ON ut.ticker = lp.ticker "
                    "LEFT JOIN LATERAL ("
                    "  SELECT market_cap FROM fundamentals f "
                    "  WHERE f.ticker = lp.ticker ORDER BY f.as_of_date DESC LIMIT 1"
                    ") fc ON true "
                    "WHERE lp.sync_run_id = :rid"
                ),
                {"rid": sync_run_id},
            )
            for p in pos_rows.mappings():
                all_broker_positions[p["ticker"]] = {
                    "qty": float(p["qty"]) if p["qty"] is not None else None,
                    "market_value": float(p["market_value"]) if p["market_value"] is not None else None,
                    "unrealized_plpc": float(p["unrealized_plpc"]) if p["unrealized_plpc"] is not None else None,
                    "name": p["name"],
                    "sector": p["sector"],
                    "market_cap": float(p["market_cap"]) if p["market_cap"] is not None else None,
                }

        # For held tickers outside the display window, fetch their real rank so
        # the screener shows rank 489 instead of the sentinel 9999.
        ranked_tickers = {r["ticker"] for r in ranking_rows}
        missing_held = [t for t in all_broker_positions if t not in ranked_tickers]
        held_rank_lookup: dict[str, dict] = {}
        if missing_held:
            hr_rows = await conn.execute(
                text(
                    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, "
                    "  r.factor_scores, pr.prior_rank "
                    "FROM rankings r "
                    "LEFT JOIN (SELECT ticker, rank AS prior_rank FROM rankings "
                    "           WHERE run_id = :prior_run_id) pr ON pr.ticker = r.ticker "
                    "WHERE r.run_id = :run_id AND r.ticker = ANY(:tickers)"
                ),
                {"run_id": latest_run_id, "prior_run_id": prior_run_id or latest_run_id,
                 "tickers": missing_held},
            )
            for hr in hr_rows.mappings():
                held_rank_lookup[hr["ticker"]] = dict(hr)

        ranking_rows = _apply_overlays(ranking_rows, vetter_by_ticker, all_broker_positions,
                                       held_rank_lookup=held_rank_lookup,
                                       cluster_by_ticker=cluster_by_ticker)

    return {
        "count": len(ranking_rows),
        "run": {"run_id": latest_run_id, "rank_date":
                latest_rank_date.isoformat() if hasattr(latest_rank_date, "isoformat")
                else str(latest_rank_date)},
        "prior_run": {"run_id": prior_run_id} if prior_run_id else None,
        "vetter_run_id": vetter_run_id,
        "sync_run_id": sync_run_id,
        "rankings": ranking_rows,
    }


@app.get("/rankings/search")
async def search_rankings(q: str = ""):
    """Search all rankings for tickers matching the given prefix (case-insensitive).

    Unlike /rankings/with-overlays, there is no row limit — every ranked ticker
    whose symbol starts with `q` is returned. This lets the dashboard surface
    tickers ranked below the display window (e.g. rank 151+).

    Also injects broker-held positions that match `q` but are absent from rankings
    (rank=9999, not_in_universe=True), so held-but-unranked tickers are always findable.

    Returns the same overlay schema as /rankings/with-overlays.
    """
    q = q.upper().strip()
    if not q:
        return {"count": 0, "run": None, "prior_run": None, "rankings": []}
    if not re.match(r'^[A-Z0-9.\-]{1,10}$', q):
        raise HTTPException(status_code=400, detail=f"Invalid ticker query: {q!r}")

    async with engine.connect() as conn:
        run_rows = (await conn.execute(text(
            "SELECT run_id, rank_date FROM ("
            "  SELECT DISTINCT ON (rank_date) run_id, rank_date"
            "  FROM ranking_runs WHERE status='success'"
            "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
            ") latest_per_date "
            "ORDER BY rank_date DESC LIMIT 2"
        ))).fetchall()
        if not run_rows:
            return {"count": 0, "run": None, "prior_run": None, "rankings": []}
        latest_run_id = str(run_rows[0].run_id)
        prior_run_id = str(run_rows[1].run_id) if len(run_rows) > 1 else None
        # rank_date of the ACTUAL latest ranked run (authoritative for run_id).
        # Captured here so run metadata can never be drifted by an injected
        # broker row that _apply_overlays sorts ahead of index 0.
        latest_rank_date = run_rows[0].rank_date

        vetter_row = (await conn.execute(text(
            "SELECT run_id FROM vetter_runs "
            "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
        ))).fetchone()
        vetter_run_id = str(vetter_row.run_id) if vetter_row else None

        sync_row = (await conn.execute(text(
            "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ))).fetchone()
        sync_run_id = str(sync_row.run_id) if sync_row else None

        # Scope every CTE to the tickers matching the prefix FIRST. Without this,
        # ticker_slopes (REGR_SLOPE over all rankings × 5 runs) and caps
        # (DISTINCT ON over the entire fundamentals table) are computed for the
        # whole universe on every keystroke — on a Russell-3000-scale DB that
        # blows past the dashboard proxy's 10s timeout, and the client silently
        # falls back to filtering only the loaded top-100. Filtering to `matched`
        # up front keeps search fast and full-universe.
        rows = await conn.execute(
            text(
                "WITH matched AS ("
                "  SELECT ticker, rank, composite_score, percentile, regime, rank_date, factor_scores"
                "  FROM rankings WHERE run_id = :run_id AND UPPER(ticker) LIKE :pattern"
                "),"
                "recent_runs AS ("
                "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                "  FROM ("
                "    SELECT run_id, rank_date FROM ("
                "      SELECT DISTINCT ON (rank_date) run_id, rank_date"
                "      FROM ranking_runs WHERE status='success'"
                "      ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                "    ) latest_per_date"
                "    ORDER BY rank_date DESC LIMIT 5"
                "  ) recent_dates"
                "),"
                "ticker_slopes AS ("
                "  SELECT r.ticker,"
                "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                "  WHERE r.ticker IN (SELECT ticker FROM matched)"
                "  GROUP BY r.ticker"
                "),"
                "prior_ranks AS ("
                "  SELECT ticker, rank AS prior_rank FROM rankings"
                "  WHERE run_id = :prior_run_id AND ticker IN (SELECT ticker FROM matched)"
                "),"
                "names AS ("
                "  SELECT DISTINCT ON (ticker) ticker, name, sector FROM universe_tickers"
                "  WHERE ticker IN (SELECT ticker FROM matched)"
                "  ORDER BY ticker, (sector IS NULL), snapshot_id DESC"
                "),"
                "caps AS ("
                "  SELECT DISTINCT ON (ticker) ticker, market_cap FROM fundamentals"
                "  WHERE ticker IN (SELECT ticker FROM matched)"
                "  ORDER BY ticker, as_of_date DESC"
                ")"
                "SELECT m.ticker, m.rank, m.composite_score, m.percentile, m.regime, m.rank_date,"
                "  m.factor_scores, ts.rank_slope, pr.prior_rank, n.name, n.sector, c.market_cap "
                "FROM matched m "
                "LEFT JOIN ticker_slopes ts ON ts.ticker = m.ticker "
                "LEFT JOIN prior_ranks pr ON pr.ticker = m.ticker "
                "LEFT JOIN names n ON n.ticker = m.ticker "
                "LEFT JOIN caps c ON c.ticker = m.ticker "
                "ORDER BY m.rank ASC"
            ),
            {"run_id": latest_run_id, "prior_run_id": prior_run_id or latest_run_id,
             "pattern": q + "%"},
        )
        ranking_rows = [dict(r) for r in rows.mappings()]
        tickers = [r["ticker"] for r in ranking_rows]

        vetter_by_ticker: dict[str, dict] = {}
        if vetter_run_id and tickers:
            vd_rows = await conn.execute(
                text(
                    "SELECT ticker, exclude, confidence, risk_type, reason, "
                    "  positive_catalyst, positive_reason, crashed "
                    "FROM vetter_decisions WHERE run_id = :rid AND ticker = ANY(:tickers)"
                ),
                {"rid": vetter_run_id, "tickers": tickers},
            )
            for v in vd_rows.mappings():
                vetter_by_ticker[v["ticker"]] = dict(v)

        all_broker_positions: dict[str, dict] = {}
        if sync_run_id:
            pos_rows = await conn.execute(
                text(
                    "SELECT lp.ticker, lp.qty, lp.market_value, lp.unrealized_plpc, "
                    "  ut.name, ut.sector, fc.market_cap "
                    "FROM live_positions lp "
                    "LEFT JOIN (SELECT DISTINCT ON (ticker) ticker, name, sector "
                    "           FROM universe_tickers "
                    "           ORDER BY ticker, (sector IS NULL), snapshot_id DESC) ut "
                    "  ON ut.ticker = lp.ticker "
                    "LEFT JOIN LATERAL ("
                    "  SELECT market_cap FROM fundamentals f "
                    "  WHERE f.ticker = lp.ticker ORDER BY f.as_of_date DESC LIMIT 1"
                    ") fc ON true "
                    "WHERE lp.sync_run_id = :rid"
                ),
                {"rid": sync_run_id},
            )
            for p in pos_rows.mappings():
                all_broker_positions[p["ticker"]] = {
                    "qty": float(p["qty"]) if p["qty"] is not None else None,
                    "market_value": float(p["market_value"]) if p["market_value"] is not None else None,
                    "unrealized_plpc": float(p["unrealized_plpc"]) if p["unrealized_plpc"] is not None else None,
                    "name": p["name"],
                    "sector": p["sector"],
                    "market_cap": float(p["market_cap"]) if p["market_cap"] is not None else None,
                }

        # Fetch real ranks for held tickers that are outside the search result set
        # (e.g. held but their ticker doesn't match the search prefix, so they'd be
        # injected as 9999 even though they're ranked).
        ranked_tickers_search = {r["ticker"] for r in ranking_rows}
        missing_held_search = [
            t for t in all_broker_positions
            if t not in ranked_tickers_search and _match_ticker_prefix(t, q)
        ]
        held_rank_lookup_search: dict[str, dict] = {}
        if missing_held_search:
            hr_rows2 = await conn.execute(
                text(
                    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, "
                    "  r.factor_scores, pr.prior_rank "
                    "FROM rankings r "
                    "LEFT JOIN (SELECT ticker, rank AS prior_rank FROM rankings "
                    "           WHERE run_id = :prior_run_id) pr ON pr.ticker = r.ticker "
                    "WHERE r.run_id = :run_id AND r.ticker = ANY(:tickers)"
                ),
                {"run_id": latest_run_id, "prior_run_id": prior_run_id or latest_run_id,
                 "tickers": missing_held_search},
            )
            for hr in hr_rows2.mappings():
                held_rank_lookup_search[hr["ticker"]] = dict(hr)

        cluster_by_ticker_search: dict[str, str] = {}
        cl_rows2 = await conn.execute(text(
            "SELECT ticker, cluster_id FROM candidate_clusters "
            "WHERE run_id = (SELECT run_id FROM portfolio_runs WHERE status='success' "
            "                ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
        ))
        for c in cl_rows2.mappings():
            cluster_by_ticker_search[c["ticker"]] = c["cluster_id"]

        ranking_rows = _apply_overlays(
            ranking_rows, vetter_by_ticker, all_broker_positions,
            inject_unranked=True, query_prefix=q,
            held_rank_lookup=held_rank_lookup_search,
            cluster_by_ticker=cluster_by_ticker_search,
        )

    run_meta = None
    if ranking_rows:
        rd = latest_rank_date
        run_meta = {"run_id": latest_run_id,
                    "rank_date": rd.isoformat() if hasattr(rd, "isoformat") else str(rd)}
    return {
        "count": len(ranking_rows),
        "query": q,
        "run": run_meta,
        "prior_run": {"run_id": prior_run_id} if prior_run_id else None,
        "vetter_run_id": vetter_run_id,
        "sync_run_id": sync_run_id,
        "rankings": ranking_rows,
    }


@app.get("/rankings/suggest")
async def suggest_rankings(q: str = "", limit: int = 20):
    """Lightweight typeahead for the Screener search box.

    Matches the query against ticker symbol (contains) OR company name (contains),
    case-insensitive, within the latest successful ranking run. Returns just
    {ticker, name, rank} per match — NO overlay CTEs (rank_slope / prior_rank /
    vetter / caps), so it's cheap enough to fire on every keystroke. Ordering:
    exact-ticker match first, then ticker-prefix, then everything else; ties broken
    by rank ascending.

    This drives the navigate-typeahead dropdown (helper list under the search box);
    the main rankings list is NOT filtered. An empty/whitespace query returns no
    matches without touching the DB.
    """
    q = (q or "").strip()
    if not q:
        return {"q": q, "matches": []}
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    async with engine.connect() as conn:
        run_rows = (await conn.execute(text(
            "SELECT run_id, rank_date FROM ("
            "  SELECT DISTINCT ON (rank_date) run_id, rank_date"
            "  FROM ranking_runs WHERE status='success'"
            "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
            ") latest_per_date "
            "ORDER BY rank_date DESC LIMIT 1"
        ))).fetchall()
        if not run_rows:
            return {"q": q, "matches": []}
        latest_run_id = str(run_rows[0].run_id)

        # Match ticker-contains OR name-contains. names CTE = latest universe snapshot.
        # Order: exact ticker → ticker-prefix → other, then rank asc. The pattern is
        # bound as a param (no SQL injection) and we LIKE on UPPER() for case-insens.
        rows = await conn.execute(
            text(
                "WITH names AS ("
                "  SELECT DISTINCT ON (ticker) ticker, name FROM universe_tickers"
                "  WHERE snapshot_id = (SELECT MAX(id) FROM universe_snapshots)"
                "  ORDER BY ticker, id ASC"
                ")"
                "SELECT r.ticker, n.name, r.rank "
                "FROM rankings r "
                "LEFT JOIN names n ON n.ticker = r.ticker "
                "WHERE r.run_id = :run_id "
                "  AND (UPPER(r.ticker) LIKE '%' || UPPER(:q) || '%' "
                "       OR UPPER(n.name) LIKE '%' || UPPER(:q) || '%') "
                "ORDER BY "
                "  (UPPER(r.ticker) = UPPER(:q)) DESC, "
                "  (UPPER(r.ticker) LIKE UPPER(:q) || '%') DESC, "
                "  r.rank ASC "
                "LIMIT :limit"
            ),
            {"run_id": latest_run_id, "q": q, "limit": limit},
        )
        matches = [
            {"ticker": m["ticker"], "name": m["name"], "rank": m["rank"]}
            for m in rows.mappings()
        ]

    return {"q": q, "matches": matches}


@app.get("/rankings/universe")
async def get_rankings_universe(limit: int = 5000):
    """Full ranked-universe list for the Screener — LIGHT columns only.

    Returns the ENTIRE latest-run ranking with cheap columns (rank, ticker, name,
    sector, composite_score, percentile, prior_rank for the ▲▼ arrows, cluster_id,
    held + qty/market_value) and NO expensive overlays — no rank_slope REGR, no
    vetter, no market_cap. The screener renders this full list (virtualized); the
    per-row detail card fetches the heavy overlays on demand via
    /rankings/with-overlays?tickers=. Held-but-unranked broker positions are
    injected so a holding always appears. Cheap enough to skip the per-run cache
    (indexed rank scan + small indexed joins), unlike with-overlays.
    """
    if limit < 1:
        limit = 1
    if engine is None:
        return {"count": 0, "run": None, "prior_run": None, "rankings": []}
    async with engine.connect() as conn:
        run_rows = (await conn.execute(text(
            "SELECT run_id, rank_date FROM ("
            "  SELECT DISTINCT ON (rank_date) run_id, rank_date"
            "  FROM ranking_runs WHERE status='success'"
            "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
            ") latest_per_date ORDER BY rank_date DESC LIMIT 2"
        ))).fetchall()
        if not run_rows:
            return {"count": 0, "run": None, "prior_run": None, "rankings": []}
        latest_run_id = str(run_rows[0].run_id)
        prior_run_id = str(run_rows[1].run_id) if len(run_rows) > 1 else None
        latest_rank_date = run_rows[0].rank_date

        rows = await conn.execute(
            text(
                "WITH prior AS ("
                "  SELECT ticker, rank AS prior_rank FROM rankings WHERE run_id = :prior_run_id"
                "),"
                "names AS ("
                "  SELECT DISTINCT ON (ticker) ticker, name, sector FROM universe_tickers"
                "  ORDER BY ticker, (sector IS NULL), snapshot_id DESC"
                "),"
                "cl AS ("
                "  SELECT ticker, cluster_id FROM candidate_clusters"
                "  WHERE run_id = (SELECT run_id FROM portfolio_runs WHERE status='success'"
                "                  ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
                ")"
                "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.rank_date, r.regime,"
                "  n.name, n.sector, p.prior_rank, cl.cluster_id "
                "FROM rankings r "
                "LEFT JOIN prior p ON p.ticker = r.ticker "
                "LEFT JOIN names n ON n.ticker = r.ticker "
                "LEFT JOIN cl ON cl.ticker = r.ticker "
                "WHERE r.run_id = :run_id "
                "ORDER BY r.rank ASC LIMIT :limit"
            ),
            {"run_id": latest_run_id, "prior_run_id": prior_run_id or latest_run_id,
             "limit": limit},
        )
        ranking_rows = [dict(m) for m in rows.mappings()]
        for r in ranking_rows:
            if r.get("composite_score") is not None:
                r["composite_score"] = float(r["composite_score"])
            if r.get("percentile") is not None:
                r["percentile"] = float(r["percentile"])
            if r.get("prior_rank") is not None:
                r["prior_rank"] = int(r["prior_rank"])
            rd = r.get("rank_date")
            r["rank_date"] = rd.isoformat() if hasattr(rd, "isoformat") else (str(rd) if rd else None)

        # Held overlay (light): flag held rows + inject held-but-unranked positions.
        sync_row = (await conn.execute(text(
            "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"))).fetchone()
        held: dict[str, dict] = {}
        if sync_row:
            pos = await conn.execute(text(
                "SELECT lp.ticker, lp.qty, lp.market_value, ut.name, ut.sector "
                "FROM live_positions lp "
                "LEFT JOIN (SELECT DISTINCT ON (ticker) ticker, name, sector "
                "           FROM universe_tickers "
                "           ORDER BY ticker, (sector IS NULL), snapshot_id DESC) ut "
                "  ON ut.ticker = lp.ticker "
                "WHERE lp.sync_run_id = :rid"), {"rid": str(sync_row.run_id)})
            for p in pos.mappings():
                held[p["ticker"]] = {
                    "qty": float(p["qty"]) if p["qty"] is not None else None,
                    "market_value": float(p["market_value"]) if p["market_value"] is not None else None,
                    "name": p["name"], "sector": p["sector"],
                }
        present = set()
        for r in ranking_rows:
            r["held"] = r["ticker"] in held
            if r["held"]:
                r["qty"] = held[r["ticker"]]["qty"]
                r["market_value"] = held[r["ticker"]]["market_value"]
            present.add(r["ticker"])
        for t, h in held.items():
            if t not in present:
                ranking_rows.append({
                    "ticker": t, "rank": 9999, "composite_score": None, "percentile": None,
                    "rank_date": None, "regime": None, "name": h["name"], "sector": h["sector"],
                    "prior_rank": None, "cluster_id": None, "held": True,
                    "qty": h["qty"], "market_value": h["market_value"], "not_in_universe": True,
                })

    return {
        "count": len(ranking_rows),
        "run": {"run_id": latest_run_id,
                "rank_date": (latest_rank_date.isoformat()
                              if hasattr(latest_rank_date, "isoformat") else str(latest_rank_date))},
        "prior_run": ({"run_id": prior_run_id} if prior_run_id else None),
        "rankings": ranking_rows,
    }


# ── Universe ───────────────────────────────────────────────────────────────────────────────────

@app.get("/universe")
async def get_universe():
    async with engine.connect() as conn:
        snap = await conn.execute(
            text(
                "SELECT id, etf_ticker, snapshot_date, ticker_count, fetched_at "
                "FROM universe_snapshots ORDER BY fetched_at DESC LIMIT 1"
            )
        )
        snapshot = snap.mappings().first()
        if snapshot is None:
            raise HTTPException(404, "No universe data yet. Run: make universe")
        tickers = await conn.execute(
            text(
                "SELECT ticker, name, weight_pct, sector "
                "FROM universe_tickers WHERE snapshot_id = :sid ORDER BY weight_pct DESC NULLS LAST"
            ),
            {"sid": snapshot["id"]},
        )
        ticker_list = [dict(r) for r in tickers.mappings()]
    return {"snapshot": dict(snapshot), "tickers": ticker_list}


@app.get("/universe/investable")
async def get_investable_universe():
    """Return the investable universe — tickers that passed price/liquidity filters in the
    latest successful factor run.  These are the exact tickers whose z-scores were computed
    cross-sectionally together, so this list is the true peer group for ranking purposes.
    Returns 404 when no successful factor run exists yet (cold start)."""
    async with engine.connect() as conn:
        run_row = await conn.execute(
            text(
                "SELECT run_id, score_date, ticker_count, regime "
                "FROM factor_runs WHERE status='success' "
                "ORDER BY score_date DESC, completed_at DESC NULLS LAST LIMIT 1"
            )
        )
        run = run_row.mappings().first()
        if run is None:
            raise HTTPException(
                404,
                "No successful factor run yet — run fetch-data then factor-calculate first.",
            )
        tickers_row = await conn.execute(
            text(
                "SELECT fs.ticker, ut.name, ut.sector "
                "FROM factor_scores fs "
                "LEFT JOIN (SELECT DISTINCT ON (ticker) ticker, name, sector "
                "           FROM universe_tickers "
                "           ORDER BY ticker, (sector IS NULL), snapshot_id DESC) ut "
                "  ON ut.ticker = fs.ticker "
                "WHERE fs.run_id = :rid "
                "ORDER BY fs.ticker ASC"
            ),
            {"rid": run["run_id"]},
        )
        ticker_list = [dict(r) for r in tickers_row.mappings()]
    return {
        "source": "factor_scores",
        "factor_run_id": str(run["run_id"]),
        "score_date": str(run["score_date"]) if run["score_date"] else None,
        "regime": run["regime"],
        "ticker_count": len(ticker_list),
        "tickers": ticker_list,
    }


# ── Factor scores ────────────────────────────────────────────────────────────────────────────

@app.get("/factors/{ticker}")
async def get_factors(ticker: str):
    ticker = _validate_ticker(ticker)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                # Canonical `scores` JSONB carries ALL factors (generic); legacy columns
                # are still selected as a fallback for any pre-migration row.
                "SELECT run_id, ticker, score_date, scores, momentum, quality, value, growth, "
                "low_volatility, liquidity, issuance, small_cap, volume_surge, near_high, "
                "high_volatility, earnings_surprise, calculated_at "
                "FROM factor_scores WHERE ticker = :ticker ORDER BY calculated_at DESC LIMIT 5"
            ),
            {"ticker": ticker.upper()},
        )
        results = []
        for r in rows.mappings():
            d = dict(r)
            scores = d.pop("scores", None)
            if scores:
                s = scores if isinstance(scores, dict) else json.loads(scores)
                d.update(s)   # all factors top-level from the canonical store
            results.append(d)
    if not results:
        raise HTTPException(404, f"No factor scores for {ticker}")
    return results


# ── Factor runs ─────────────────────────────────────────────────────────────────────────────

@app.get("/factor-runs")
async def list_factor_runs(limit: int = 20):
    limit = max(1, min(limit, 200))   # clamp: negative/huge input must not 500
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, trace_id, strategy_id, config_hash, status, regime, "
                "       score_date, ticker_count, warning_count, universe_snapshot_id, "
                "       price_data_max_date, started_at, completed_at, error_message "
                "FROM factor_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.mappings().fetchall()
    return [
        {
            "run_id": str(r["run_id"]),
            "trace_id": str(r["trace_id"]) if r["trace_id"] else None,
            "strategy_id": r["strategy_id"],
            "config_hash": r["config_hash"],
            "status": r["status"],
            "regime": r["regime"],
            "score_date": str(r["score_date"]) if r["score_date"] else None,
            "ticker_count": r["ticker_count"],
            "warning_count": r["warning_count"],
            "universe_snapshot_id": r["universe_snapshot_id"],
            "price_data_max_date": str(r["price_data_max_date"]) if r["price_data_max_date"] else None,
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "error_message": r["error_message"],
        }
        for r in results
    ]


# ── Ranking runs ─────────────────────────────────────────────────────────────────────────────

@app.get("/ranking-runs")
async def list_ranking_runs(limit: int = 20):
    limit = max(1, min(limit, 200))   # clamp: negative/huge input must not 500
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, trace_id, source_factor_run_id, strategy_id, config_hash, "
                "       regime, rank_date, status, universe_count, ranked_count, dropped_count, "
                "       started_at, completed_at, error_message "
                "FROM ranking_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.mappings().fetchall()
    return [
        {
            "run_id": str(r["run_id"]),
            "trace_id": str(r["trace_id"]) if r["trace_id"] else None,
            "source_factor_run_id": str(r["source_factor_run_id"]),
            "strategy_id": r["strategy_id"],
            "config_hash": r["config_hash"],
            "regime": r["regime"],
            "rank_date": str(r["rank_date"]) if r["rank_date"] else None,
            "status": r["status"],
            "universe_count": r["universe_count"],
            "ranked_count": r["ranked_count"],
            "dropped_count": r["dropped_count"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "error_message": r["error_message"],
        }
        for r in results
    ]


# ── Execution traces ───────────────────────────────────────────────────────────────────────────

@app.get("/traces")
async def list_traces(limit: int = 20):
    limit = max(1, min(limit, 200))   # clamp: negative/huge input must not 500
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT trace_id, job_type, status, root_run_id, strategy_id, config_hash, "
                "       started_at, completed_at, notes "
                "FROM execution_traces ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.mappings().fetchall()
    return [
        {
            "trace_id": str(r["trace_id"]),
            "job_type": r["job_type"],
            "status": r["status"],
            "root_run_id": str(r["root_run_id"]) if r["root_run_id"] else None,
            "strategy_id": r["strategy_id"],
            "config_hash": r["config_hash"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "notes": r["notes"],
        }
        for r in results
    ]


@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    try:
        uuid.UUID(trace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid trace_id format: {trace_id!r}")
    async with engine.connect() as conn:
        trace_row = await conn.execute(
            text(
                "SELECT trace_id, job_type, status, root_run_id, strategy_id, config_hash, "
                "       started_at, completed_at, notes "
                "FROM execution_traces WHERE trace_id = :tid"
            ),
            {"tid": trace_id},
        )
        trace = trace_row.mappings().first()
        if trace is None:
            raise HTTPException(404, f"Trace {trace_id} not found")

        steps_rows = await conn.execute(
            text(
                "SELECT step_id, service, step_name, status, started_at, completed_at, "
                "       input_summary, output_summary, warnings, error_message "
                "FROM execution_steps WHERE trace_id = :tid ORDER BY started_at ASC"
            ),
            {"tid": trace_id},
        )
        steps = steps_rows.mappings().fetchall()

        linked_factor_run = None
        linked_ranking_run = None
        linked_portfolio_run = None
        root_run_id = trace["root_run_id"]

        if root_run_id and trace["job_type"] == "factor_run":
            fr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, score_date, ticker_count, warning_count, "
                    "       config_hash, universe_snapshot_id, price_data_max_date "
                    "FROM factor_runs WHERE run_id = :rid"
                ),
                {"rid": str(root_run_id)},
            )
            row = fr.mappings().first()
            if row:
                linked_factor_run = fmt_row(row)
            # Find the ranking run that consumed this factor run as input
            rr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, rank_date, universe_count, ranked_count, dropped_count "
                    "FROM ranking_runs WHERE source_factor_run_id = :frid "
                    "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                ),
                {"frid": str(root_run_id)},
            )
            rr_row = rr.mappings().first()
            if rr_row:
                linked_ranking_run = fmt_row(rr_row)

        if root_run_id and trace["job_type"] == "rank_run":
            rr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, rank_date, universe_count, ranked_count, "
                    "       dropped_count, source_factor_run_id "
                    "FROM ranking_runs WHERE run_id = :rid"
                ),
                {"rid": str(root_run_id)},
            )
            row = rr.mappings().first()
            if row:
                linked_ranking_run = fmt_row(row)

        if root_run_id and trace["job_type"] == "portfolio_run":
            pr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, portfolio_date, candidate_count, selected_count, "
                    "       avg_pairwise_correlation, portfolio_estimated_vol, source_ranking_run_id "
                    "FROM portfolio_runs WHERE run_id = :rid"
                ),
                {"rid": str(root_run_id)},
            )
            row = pr.mappings().first()
            if row:
                linked_portfolio_run = fmt_row(row)

    def _fmt_step(s):
        return {
            "step_id": str(s["step_id"]),
            "service": s["service"],
            "step_name": s["step_name"],
            "status": s["status"],
            "started_at": s["started_at"].isoformat() if s["started_at"] else None,
            "completed_at": s["completed_at"].isoformat() if s["completed_at"] else None,
            "input_summary": s["input_summary"],
            "output_summary": s["output_summary"],
            "warnings": s["warnings"],
            "error_message": s["error_message"],
        }

    return {
        "trace_id": str(trace["trace_id"]),
        "job_type": trace["job_type"],
        "status": trace["status"],
        "root_run_id": str(trace["root_run_id"]) if trace["root_run_id"] else None,
        "strategy_id": trace["strategy_id"],
        "config_hash": trace["config_hash"],
        "started_at": trace["started_at"].isoformat() if trace["started_at"] else None,
        "completed_at": trace["completed_at"].isoformat() if trace["completed_at"] else None,
        "notes": trace["notes"],
        "factor_run": linked_factor_run,
        "ranking_run": linked_ranking_run,
        "portfolio_run": linked_portfolio_run,
        "steps": [_fmt_step(s) for s in steps],
    }


# ── Portfolio ─────────────────────────────────────────────────────────────────────────────────

def _portfolio_risk_summary(holdings: list[dict], beta_map: dict[str, float]) -> dict:
    """Compute the Target-tab risk numbers from target holdings + per-name betas.

      sleeve_beta       — weight-weighted beta over beta-COVERED holdings, normalized
                          (÷ their weight sum). The beta of the STOCKS as if fully
                          invested — EXCLUDES the cash buffer.
      coverage          — how many holdings had a beta (so a missing-beta name
                          doesn't silently drag the average toward 0).
      invested_fraction — Σ ALL target weights (= 1 − cash_reserve − any vol-target
                          de-lever; the target weights already encode the cash buffer).
      cash_pct          — 1 − invested_fraction (clamped ≥ 0): the target cash buffer.
      effective_beta    — sleeve_beta × invested_fraction: the book's REAL market
                          sensitivity (cash contributes zero beta) — what tracks SPY.

    Pure (no DB) so it's unit-tested directly.
    """
    covered = [h for h in holdings if h["ticker"] in beta_map]
    wsum = sum(float(h["weight"]) for h in covered)
    sleeve_beta = (
        sum(float(h["weight"]) * beta_map[h["ticker"]] for h in covered) / wsum
        if wsum > 0 else None
    )
    invested_fraction = sum(float(h["weight"]) for h in holdings) if holdings else None
    cash_pct = max(0.0, 1.0 - invested_fraction) if invested_fraction is not None else None
    effective_beta = (
        sleeve_beta * invested_fraction
        if (sleeve_beta is not None and invested_fraction is not None) else None
    )
    return {
        "sleeve_beta": sleeve_beta,
        "coverage": len(covered),
        "invested_fraction": invested_fraction,
        "cash_pct": cash_pct,
        "effective_beta": effective_beta,
    }


@app.get("/portfolio")
async def get_portfolio(run_id: str | None = None):
    async with engine.connect() as conn:
        if run_id:
            run_row = await conn.execute(
                text(
                    "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, config_hash, "
                    "       regime, portfolio_date, status, candidate_count, selected_count, "
                    "       covariance_window_days, avg_pairwise_correlation, portfolio_estimated_vol, "
                    "       error_message, started_at, completed_at "
                    "FROM portfolio_runs WHERE run_id = :rid"
                ),
                {"rid": run_id},
            )
        else:
            run_row = await conn.execute(
                text(
                    "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, config_hash, "
                    "       regime, portfolio_date, status, candidate_count, selected_count, "
                    "       covariance_window_days, avg_pairwise_correlation, portfolio_estimated_vol, "
                    "       error_message, started_at, completed_at "
                    # G5: skip a build superseded by a newer one for the same ranking.
                    "FROM portfolio_runs WHERE status = 'success' AND superseded_at IS NULL "
                    "ORDER BY portfolio_date DESC, completed_at DESC NULLS LAST LIMIT 1"
                )
            )
        run = run_row.mappings().first()
        if run is None:
            return {"run": None, "holdings": []}
        holdings_rows = await conn.execute(
            text(
                "SELECT ticker, position, weight, composite_score, original_rank, "
                "       adj_score, portfolio_vol_at_add "
                "FROM portfolio_holdings WHERE run_id = :rid ORDER BY position ASC"
            ),
            {"rid": str(run["run_id"])},
        )
        holdings = [dict(r) for r in holdings_rows.mappings()]

        # Per-holding market beta (display-only) from the SAME ranking run that
        # produced this target (rankings.factor_scores->'beta', 120d vs SPY).
        # Used to surface the weight-weighted PORTFOLIO beta — observability for
        # how much of the book's return is just market exposure.
        beta_map: dict[str, float] = {}
        if holdings and run["source_ranking_run_id"]:
            beta_rows = await conn.execute(
                text(
                    "SELECT ticker, (factor_scores->>'beta')::float AS beta "
                    "FROM rankings WHERE run_id = :rid AND ticker = ANY(:tickers)"
                ),
                {
                    "rid": str(run["source_ranking_run_id"]),
                    "tickers": [h["ticker"] for h in holdings],
                },
            )
            beta_map = {
                r["ticker"]: float(r["beta"])
                for r in beta_rows.mappings()
                if r["beta"] is not None
            }

    risk = _portfolio_risk_summary(holdings, beta_map)
    portfolio_beta = risk["sleeve_beta"]
    effective_beta = risk["effective_beta"]
    invested_fraction = risk["invested_fraction"]
    cash_pct = risk["cash_pct"]
    covered = risk["coverage"]

    return {
        "run": {
            "run_id": str(run["run_id"]),
            "trace_id": str(run["trace_id"]) if run["trace_id"] else None,
            "source_ranking_run_id": str(run["source_ranking_run_id"]),
            "strategy_id": run["strategy_id"],
            "config_hash": run["config_hash"],
            "regime": run["regime"],
            "portfolio_date": str(run["portfolio_date"]) if run["portfolio_date"] else None,
            "status": run["status"],
            "candidate_count": run["candidate_count"],
            "selected_count": run["selected_count"],
            "covariance_window_days": run["covariance_window_days"],
            "avg_pairwise_correlation": float(run["avg_pairwise_correlation"]) if run["avg_pairwise_correlation"] is not None else None,
            "portfolio_estimated_vol": float(run["portfolio_estimated_vol"]) if run["portfolio_estimated_vol"] is not None else None,
            "portfolio_beta": round(portfolio_beta, 3) if portfolio_beta is not None else None,
            "portfolio_beta_coverage": covered,
            "effective_beta": round(effective_beta, 3) if effective_beta is not None else None,
            "invested_fraction": round(invested_fraction, 4) if invested_fraction is not None else None,
            "cash_pct": round(cash_pct, 4) if cash_pct is not None else None,
            "error_message": run["error_message"],
            "started_at": run["started_at"].isoformat() if run["started_at"] else None,
            "completed_at": run["completed_at"].isoformat() if run["completed_at"] else None,
        },
        "holdings": [
            {
                "ticker": h["ticker"],
                "position": h["position"],
                "weight": float(h["weight"]),
                "beta": beta_map.get(h["ticker"]),
                "composite_score": float(h["composite_score"]) if h["composite_score"] is not None else None,
                "original_rank": h["original_rank"],
                "adj_score": float(h["adj_score"]) if h["adj_score"] is not None else None,
                "portfolio_vol_at_add": float(h["portfolio_vol_at_add"]) if h["portfolio_vol_at_add"] is not None else None,
            }
            for h in holdings
        ],
    }


# ── Live portfolio (broker positions via alpaca-sync) ─────────────────────────

@app.get("/live-portfolio")
async def get_live_portfolio():
    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)

    def _f(v):
        return float(v) if v is not None else None

    try:
        async with engine.connect() as conn:
            sync_row = (await conn.execute(text(
                "SELECT run_id, status, account_value, buying_power, cash, "
                "position_count, completed_at "
                "FROM alpaca_sync_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
            ))).mappings().first()

            if sync_row is None:
                return {"connected": False, "positions": [], "sync": None}

            pos_rows = (await conn.execute(text(
                "SELECT ticker, qty, avg_entry_price, current_price, market_value, "
                "cost_basis, unrealized_pl, unrealized_plpc, side, "
                "lastday_price, change_today "
                "FROM live_positions WHERE sync_run_id = :rid "
                "ORDER BY market_value DESC NULLS LAST"
            ), {"rid": str(sync_row["run_id"])})).mappings().fetchall()

        positions = []
        for p in pos_rows:
            qty = _f(p["qty"])
            current_price = _f(p["current_price"])
            lastday_price = _f(p.get("lastday_price"))
            change_today  = _f(p.get("change_today"))
            day_pl = None
            if qty is not None and current_price is not None and lastday_price is not None:
                day_pl = qty * (current_price - lastday_price)
            positions.append({
                "ticker":          p["ticker"],
                "qty":             qty,
                "avg_entry_price": _f(p["avg_entry_price"]),
                "current_price":   current_price,
                "market_value":    _f(p["market_value"]),
                "cost_basis":      _f(p["cost_basis"]),
                "unrealized_pl":   _f(p["unrealized_pl"]),
                "unrealized_plpc": _f(p["unrealized_plpc"]),
                "lastday_price":   lastday_price,
                "change_today":    change_today,
                "day_pl":          day_pl,
                "weight":          None,
                "side":            p["side"],
            })
        total_long_mv = sum(p["market_value"] for p in positions if p["market_value"] is not None and p["market_value"] > 0)
        total_short_mv = sum(abs(p["market_value"]) for p in positions if p["market_value"] is not None and p["market_value"] < 0)
        for p in positions:
            mv = p["market_value"]
            if mv is None:
                p["weight"] = None
            elif mv >= 0:
                p["weight"] = mv / total_long_mv if total_long_mv > 0 else 0.0
            else:
                p["weight"] = -abs(mv) / total_short_mv if total_short_mv > 0 else 0.0
        return {
            "connected": True,
            "sync": {
                "synced_at":     _iso(sync_row["completed_at"]),
                "account_value": _f(sync_row["account_value"]),
                "buying_power":  _f(sync_row["buying_power"]),
                "cash":          _f(sync_row["cash"]),
                "position_count": sync_row["position_count"],
            },
            "positions": positions,
        }
    except Exception:
        print(f"[api] get_live_portfolio error: {traceback.format_exc()}")
        return {"connected": False, "positions": [], "sync": None}


# ── Delta engine intents ───────────────────────────────────────────────────────

@app.get("/delta/latest")
async def get_delta_latest():
    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)
    def _f(v):
        return float(v) if v is not None else None

    try:
        async with engine.connect() as conn:
            run_row = (await conn.execute(text(
                "SELECT run_id, status, run_date, entry_rank, exit_rank, "
                "confirmation_days, max_positions, current_portfolio_size, "
                "entries_count, exits_count, holds_count, watches_count, "
                "at_risk_count, buy_add_count, sell_trim_count, "
                "triggered_by, manual, started_at, completed_at, error_message "
                "FROM delta_runs "
                # G5: a superseded run was replaced by a newer one for the same session
                # (e.g. manual re-run over a cron run) — never surface it as "latest".
                "WHERE superseded_at IS NULL "
                "ORDER BY run_date DESC, started_at DESC LIMIT 1"
            ))).mappings().first()

            if run_row is None:
                return {"run": None, "intents": []}

            run_id = str(run_row["run_id"])
            # Match each intent's order by TICKER+SIDE within the same trading
            # SESSION (run_date), NOT by di.id. delta_intents ids are re-minted on
            # every delta run, so a re-run (manual RUN / scheduler) produces fresh
            # intent ids; an intent_id-keyed join would then show every
            # already-submitted trade as un-actioned again, letting the whole set be
            # re-approved. Keying on ticker + side + run_date makes a re-run's intent
            # resolve to the order already placed today, so it correctly reads as
            # submitted/pending and drops out of the approvable set.
            intent_rows = (await conn.execute(text(
                "SELECT di.id, di.ticker, di.action, di.rank, di.composite_score, "
                "di.confirmation_days_met, di.current_weight, di.actual_weight, "
                "di.weight_drift, di.reason, di.rejected_at, di.approved_at, "
                "ao.status AS order_status, ao.error_message AS order_error_message, "
                "ao.deferred_until AS order_deferred_until "
                "FROM delta_intents di "
                "LEFT JOIN LATERAL ("
                "  SELECT ao2.status, ao2.error_message, ao2.deferred_until "
                "  FROM alpaca_orders ao2 "
                "  JOIN delta_intents di2 ON di2.id = ao2.intent_id "
                "  JOIN delta_runs dr2 ON dr2.run_id = di2.run_id "
                "  WHERE ao2.ticker = di.ticker "
                "    AND ao2.side = CASE WHEN di.action IN ('entry','buy_add') "
                "                        THEN 'buy' ELSE 'sell' END "
                "    AND dr2.run_date = :rdate "
                # Prefer a LIVE/DONE order (open or filled) over a DEAD attempt
                # (risk_rejected/failed/expired/canceled). The ticker+side+run_date
                # join exists so a re-run resolves to a trade already PLACED today —
                # but a DEAD order from earlier in the same session must NOT stick to
                # a fresh re-run's intent and make it look un-actionable. So a real
                # open/filled order always wins; only when none exists does the latest
                # dead one show (status badge stays, but _isApprovable lets it retry).
                # "live or done" = OPEN_ORDER_STATUSES + 'filled' (= turnover set).
                # Uses the canonical DB tokens (e.g. 'partial_fill', NOT the broker
                # 'partially_filled' which is never persisted) — see order_status.py.
                f"  ORDER BY (CASE WHEN ao2.status IN ({turnover_status_sql()}) "
                "             THEN 0 ELSE 1 END), "
                "           ao2.created_at DESC LIMIT 1"
                ") ao ON true "
                "WHERE di.run_id = :rid "
                "ORDER BY di.action, di.rank ASC NULLS LAST, di.ticker"
            ), {"rid": run_id, "rdate": run_row["run_date"]})).mappings().fetchall()

            # Vetter overlay — join most recent successful vetter run onto each intent.
            vetter_by_ticker: dict[str, dict] = {}
            tickers = [r["ticker"] for r in intent_rows]
            if tickers:
                vr = (await conn.execute(text(
                    "SELECT run_id FROM vetter_runs WHERE status='success' "
                    # canonical "latest successful run" ordering — matches every
                    # other vetter_runs selector in this file (completed-time wins;
                    # started_at only breaks ties). started_at-alone could pick a
                    # later-started run that completed before an earlier-started one.
                    "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                ))).mappings().first()
                if vr:
                    vd_rows = (await conn.execute(text(
                        "SELECT ticker, exclude, confidence, risk_type, reason, "
                        "  positive_catalyst, positive_reason, crashed "
                        "FROM vetter_decisions WHERE run_id = :rid AND ticker = ANY(:tickers)"
                    ), {"rid": str(vr["run_id"]), "tickers": tickers})).mappings().fetchall()
                    for v in vd_rows:
                        vetter_by_ticker[v["ticker"]] = dict(v)

        return {
            "run": {
                "run_id":                str(run_row["run_id"]),
                "status":                run_row["status"],
                "run_date":              str(run_row["run_date"]) if run_row["run_date"] else None,
                "entry_rank":            run_row["entry_rank"],
                "exit_rank":             run_row["exit_rank"],
                "confirmation_days":     run_row["confirmation_days"],
                "max_positions":         run_row["max_positions"],
                "current_portfolio_size": run_row["current_portfolio_size"],
                "entries_count":         run_row["entries_count"],
                "exits_count":           run_row["exits_count"],
                "holds_count":           run_row["holds_count"],
                "watches_count":         run_row["watches_count"],
                "at_risk_count":         run_row["at_risk_count"],
                "buy_add_count":         run_row["buy_add_count"],
                "sell_trim_count":       run_row["sell_trim_count"],
                "triggered_by":          run_row["triggered_by"],
                "manual":                run_row["manual"],
                "started_at":            _iso(run_row["started_at"]),
                "completed_at":          _iso(run_row["completed_at"]),
                "error_message":         run_row["error_message"],
            },
            "intents": [
                {
                    "id":                    str(r["id"]),
                    "ticker":                r["ticker"],
                    "action":                r["action"],
                    "rank":                  r["rank"],
                    "composite_score":       _f(r["composite_score"]),
                    "confirmation_days_met": r["confirmation_days_met"],
                    "in_target":             _intent_in_target(r["action"], r["current_weight"]),
                    "current_weight":        _f(r["current_weight"]),
                    "actual_weight":         _f(r["actual_weight"]),
                    "weight_drift":          _f(r["weight_drift"]),
                    "reason":                r["reason"],
                    "order_status":          r["order_status"],
                    "order_error_message":   r["order_error_message"],
                    "order_deferred_until":  _iso(r["order_deferred_until"]) if r["order_deferred_until"] else None,
                    "rejected_at":           _iso(r["rejected_at"]) if r["rejected_at"] else None,
                    "approved_at":           _iso(r["approved_at"]) if r["approved_at"] else None,
                    "vetter_excluded":       vetter_by_ticker.get(r["ticker"], {}).get("exclude"),
                    "vetter_confidence":     vetter_by_ticker.get(r["ticker"], {}).get("confidence"),
                    "vetter_risk_type":      vetter_by_ticker.get(r["ticker"], {}).get("risk_type"),
                    "vetter_reason":         vetter_by_ticker.get(r["ticker"], {}).get("reason"),
                    "vetter_crashed":        bool(vetter_by_ticker.get(r["ticker"], {}).get("crashed", False)),
                    "vetter_positive_catalyst": vetter_by_ticker.get(r["ticker"], {}).get("positive_catalyst"),
                    "vetter_positive_reason":   vetter_by_ticker.get(r["ticker"], {}).get("positive_reason"),
                }
                for r in intent_rows
            ],
        }
    except Exception:
        print(f"[api] get_delta_latest error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch delta data")


# ── System status aggregation ─────────────────────────────────────────────────

@app.get("/system/status")
async def system_status():
    """Aggregate status from pipeline, vetter, av-ingestor, portfolio-builder, and scheduler.

    Each sub-call is independent: one failure does not affect the others.
    Returns a dict with keys: pipeline, vetter, ingestor, portfolio_builder, scheduler.
    Each value is the parsed JSON from the service's status endpoint, or
    {"error": "unavailable"} on any exception or non-200 response.
    """
    async def _fetch(url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.json()
                return {"error": "unavailable"}
        except Exception:
            return {"error": "unavailable"}

    pipeline_result, vetter_result, ingestor_result, portfolio_builder_result, scheduler_result = \
        await asyncio.gather(
            _fetch(f"{PIPELINE_URL}/runs/latest"),
            _fetch(f"{VETTER_URL}/runs/latest"),
            _fetch(f"{AV_INGESTOR_URL}/runs/latest"),
            _fetch(f"{PORTFOLIO_BUILDER_URL}/runs/latest"),
            _fetch(f"{SCHEDULER_URL}/status"),
        )

    return {
        "pipeline":         pipeline_result,
        "vetter":           vetter_result,
        "ingestor":         ingestor_result,
        "portfolio_builder": portfolio_builder_result,
        "scheduler":        scheduler_result,
    }


@app.get("/health/chain")
async def health_chain():
    """Proxy the scheduler's chain-liveness check.

    External monitors (Pingdom, GitHub Actions, k8s liveness probes) hit this
    endpoint on the api service to know whether the daily pipeline is still
    running on schedule. Returns 200 healthy or 503 with details from the
    scheduler. The body is the scheduler's response verbatim; status code is
    passed through.
    """
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{SCHEDULER_URL}/health/chain")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(
            content={
                "status": "unhealthy",
                "service": "scheduler",
                "reason": f"scheduler unreachable: {exc}",
            },
            status_code=503,
        )


# ── Alpaca sync proxy ──────────────────────────────────────────────────────────
# Routes the dashboard's sync request through the API so the dashboard doesn't
# need its own ALPACA_SYNC_URL env var. Internal services still call alpaca-sync
# directly when they need to.

@app.post("/alpaca/sync")
async def trigger_alpaca_sync():
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{ALPACA_SYNC_URL}/jobs/sync")
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"alpaca-sync unavailable: {exc}")


# ── Trade approval (thin proxy) ───────────────────────────────────────────────
# All sizing, risk-checking, Alpaca submission, and audit logging live in the
# trade-executor service. The API only validates the request, performs an early
# idempotency check (so duplicate clicks fail fast with a 409 instead of
# touching downstream services), and forwards.

class TradeApproveRequest(BaseModel):
    intent_id: str    # delta_intents.id (UUID)
    mode: Literal["immediate", "scheduled"]


class TradeApproveBatchRequest(BaseModel):
    intent_ids: list[str]
    mode: Literal["immediate", "scheduled"]


async def _approval_ineligibility(conn, intent_id: str) -> Optional[tuple[int, str]]:
    """Return (http_status, detail) if the intent may NOT be approved, else None.

    Two gates, shared by the single- and batch-approve paths:
      - an OPEN order already exists (idempotency). A DEAD attempt
        (risk_rejected/failed/expired/canceled) placed no live order, so it does NOT
        block — the operator retries once the cause is fixed (see docs).
      - the ticker was excluded by the latest successful vetter run AND this is a
        buy-side action (entry/buy_add). Exits/sells are never blocked — closing a
        position must always be allowed."""
    existing = (await conn.execute(text(
        "SELECT status FROM alpaca_orders "
        f"WHERE intent_id = :iid AND status IN ({open_status_sql()}) LIMIT 1"
    ), {"iid": intent_id})).mappings().first()
    if existing:
        return (409, f"Intent {intent_id} already has an open order ({existing['status']})")

    # Canonical latest-vetter selector (completed_at DESC NULLS LAST, started_at
    # DESC) — the SAME ordering /delta/latest and the overlay endpoints use. It
    # previously keyed on MAX(started_at) alone, so when two successful runs'
    # started/completed orderings diverged (retry, overlap) the UI showed run
    # A's exclusions while this gate enforced run B's — an intent presented as
    # vetter-excluded could pass approval, or vice versa (audit finding).
    excluded = (await conn.execute(text(
        "SELECT di.ticker, ve.reason "
        "FROM delta_intents di "
        "JOIN vetter_exclusions ve ON ve.ticker = di.ticker "
        "WHERE di.id = :iid "
        "  AND di.action IN ('entry', 'buy_add') "
        "  AND ve.run_id = ("
        "    SELECT run_id FROM vetter_runs WHERE status='success' "
        "    ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
        "  ) "
        "LIMIT 1"
    ), {"iid": intent_id})).mappings().first()
    if excluded:
        return (409, f"{excluded['ticker']} excluded by LLM vetter: {excluded['reason'] or 'no reason'}")
    return None


@app.post("/trade/approve")
async def approve_trade(req: TradeApproveRequest):
    """Durably enqueue ONE approval (fast). The trade-executor's single-consumer
    worker sizes/risk-checks/submits it off the request path — so this returns in
    milliseconds and no HTTP-timeout cascade can strand it."""
    try:
        uuid.UUID(req.intent_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="intent_id must be a UUID")

    try:
        async with engine.connect() as conn:
            bad = await _approval_ineligibility(conn, req.intent_id)
        if bad:
            raise HTTPException(status_code=bad[0], detail=bad[1])

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{TRADE_EXECUTOR_URL}/jobs/enqueue",
                json={"intent_id": req.intent_id, "mode": req.mode},
            )
        return JSONResponse(content=r.json(), status_code=r.status_code)

    except HTTPException:
        raise
    except Exception:
        print(f"[api] approve_trade error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Trade approval failed")


@app.post("/trade/approve-batch")
async def approve_trade_batch(req: TradeApproveBatchRequest):
    """Durably enqueue a SET of approvals in one call (the dashboard "Approve
    Selected" path). Per-intent eligibility is checked here; only eligible intents
    are forwarded to the executor's atomic enqueue-batch. Refresh-durable: the whole
    selection is persisted server-side, so a browser refresh can't strand the tail."""
    results: list[dict] = []
    eligible: list[str] = []
    try:
        async with engine.connect() as conn:
            for iid in req.intent_ids:
                try:
                    uuid.UUID(iid)
                except (ValueError, AttributeError):
                    results.append({"intent_id": iid, "status": "invalid",
                                    "reason": "intent_id must be a UUID"})
                    continue
                bad = await _approval_ineligibility(conn, iid)
                if bad:
                    results.append({"intent_id": iid, "status": "rejected",
                                    "reason": bad[1]})
                else:
                    eligible.append(iid)

        enqueued: list[dict] = []
        if eligible:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{TRADE_EXECUTOR_URL}/jobs/enqueue-batch",
                    json={"intent_ids": eligible, "mode": req.mode},
                )
            enqueued = (r.json() or {}).get("results", [])
        results.extend(enqueued)
        return {"results": results,
                "queued": sum(1 for x in results if x.get("status") == "queued")}

    except HTTPException:
        raise
    except Exception:
        print(f"[api] approve_trade_batch error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Batch trade approval failed")


class TradeRejectRequest(BaseModel):
    intent_id: str


@app.post("/trade/reject")
async def reject_trade(req: TradeRejectRequest):
    try:
        uuid.UUID(req.intent_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid intent_id")

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE delta_intents SET rejected_at = NOW() "
                "WHERE id = :iid AND rejected_at IS NULL "
                "RETURNING id, ticker, action"
            ),
            {"iid": req.intent_id},
        )
        row = result.mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="intent not found or already rejected")
        print(f"[api] rejected intent {req.intent_id} ({row['ticker']} {row['action']})", flush=True)
        return {"status": "rejected", "intent_id": req.intent_id, "ticker": row["ticker"]}


# ── Recent orders ─────────────────────────────────────────────────────────────

@app.get("/orders/recent")
async def get_recent_orders():
    """Return orders from the last 48 hours (at most 100 rows).

    Includes:
    - pending / submitted / risk_rejected / failed orders (regardless of age)
    - filled orders only if filled_at > NOW() - INTERVAL '2 hours' (so fills fade naturally)
    """
    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)

    def _f(v):
        return float(v) if v is not None else None

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT id, intent_id, ticker, action, side, qty, notional, status, "
            "  alpaca_status, submitted_at, filled_at, avg_fill_price, filled_qty, "
            "  error_message, created_at "
            "FROM alpaca_orders "
            "WHERE created_at > NOW() - INTERVAL '48 hours' "
            "  AND ( "
            # open orders (canonical set) + recent dead attempts kept for visibility
            f"    status IN ({open_status_sql()}, 'risk_rejected','failed','expired') "
            "    OR (status = 'filled' AND filled_at > NOW() - INTERVAL '2 hours') "
            "  ) "
            "ORDER BY created_at DESC "
            "LIMIT 100"
        ))).mappings().fetchall()

    return [
        {
            "id":             str(r["id"]),
            "intent_id":      str(r["intent_id"]) if r["intent_id"] else None,
            "ticker":         r["ticker"],
            "action":         r["action"],
            "side":           r["side"],
            "qty":            _f(r["qty"]),
            "notional":       _f(r["notional"]),
            "status":         r["status"],
            "alpaca_status":  r["alpaca_status"],
            "submitted_at":   _iso(r["submitted_at"]),
            "filled_at":      _iso(r["filled_at"]),
            "avg_fill_price": _f(r["avg_fill_price"]),
            "filled_qty":     _f(r["filled_qty"]),
            "error_message":  r["error_message"],
            "created_at":     _iso(r["created_at"]),
        }
        for r in rows
    ]
