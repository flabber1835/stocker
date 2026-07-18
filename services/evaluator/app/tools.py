"""Evaluator Phase-2 tools — the read-only instruments the LLM may call mid-review.

Design (docs/architecture.md "Design Decision: evaluator tools (Phase 2)"):
the llm-gateway stays a pure provider abstraction; TOOL EXECUTION lives here, in
deterministic Python. The LLM only chooses WHICH tool to call with WHAT arguments —
every implementation below enforces its own hard safety property regardless of what
the model asks for:

  run_backtest — candidate config = a DIFF over the ACTIVE config, validated
                 through StrategyConfig before anything runs; capped per review.
  sql_query    — executes inside SET TRANSACTION READ ONLY (the DB-level hard
                 guarantee: any write fails), single SELECT/WITH statement only,
                 statement_timeout + row cap.
  read_file    — rooted at /repo (compose mounts selected dirs READ-ONLY; the repo
                 root — and therefore .env — is deliberately never mounted),
                 path-traversal guarded, size-capped.
  web_search   — Tavily; absent from the toolset when TAVILY_API_KEY is unset.

Every call is recorded in the transcript by the agent loop (agent.py) for audit.
Tools never raise to the loop — errors come back as strings so the LLM can adapt.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

import httpx

from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig

BACKTESTER_URL = os.getenv("BACKTESTER_URL", "http://backtester:8000")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_BASE = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com/search")
REPO_ROOT = os.getenv("EVALUATOR_REPO_ROOT", "/repo")

MAX_BACKTESTS = int(os.getenv("EVALUATOR_MAX_BACKTESTS", "3"))
BACKTEST_POLL_SECS = float(os.getenv("EVALUATOR_BACKTEST_POLL_SECS", "5"))
BACKTEST_TIMEOUT_SECS = float(os.getenv("EVALUATOR_BACKTEST_TIMEOUT_SECS", "900"))
SQL_STATEMENT_TIMEOUT_MS = int(os.getenv("EVALUATOR_SQL_TIMEOUT_MS", "15000"))
SQL_MAX_ROWS = int(os.getenv("EVALUATOR_SQL_MAX_ROWS", "200"))
# Per-tool-result cap fed back to the LLM (a runaway SELECT * must not blow the
# context); the transcript stores the same truncated form.
RESULT_CHAR_CAP = int(os.getenv("EVALUATOR_TOOL_RESULT_CHAR_CAP", "20000"))
FILE_MAX_LINES = 400


# ── Tool definitions (gateway ToolDef shape) ──────────────────────────────────

def tool_definitions() -> list[dict]:
    """ToolDef dicts for the gateway. web_search included only when a key exists."""
    tools = [
        {
            "name": "run_backtest",
            "description": (
                "Config-replay a CANDIDATE strategy config over history: re-ranks and "
                "re-selects every historical rebalance date with the live chain's own "
                "deterministic code, de-biased (t+1 fills, no survivorship, 10bps cost). "
                "Express the candidate as a DIFF over the ACTIVE config: "
                "config_changes = {dotted.path: value}, e.g. "
                "{\"static_factor_weights.momentum\": 0.5, \"portfolio_builder.max_positions\": 25}. "
                "Weights you change must still satisfy schema rules (factor weights sum to 1.0). "
                "Returns summary (returns/sharpe/drawdown/distribution) + validation "
                "(Deflated Sharpe, sample-adequacy warnings) + caveats. Each run counts as a "
                "TRIAL: the DSR you see already deflates by how many configs have been tried, "
                "so running many and citing the best is self-penalizing. The date range is "
                "CLAMPED to the available persisted factor history (a young deployment may "
                "only have weeks — expect DIRECTIONAL small-sample warnings, not 3y of "
                f"results). Takes minutes; budget: {MAX_BACKTESTS} per review. An empty "
                "config_changes replays the active config as a baseline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "config_changes": {
                        "type": "object",
                        "description": "dotted.path -> new value, applied to the active config",
                    },
                    "date_from": {"type": "string", "description": "ISO date, default 3y ago"},
                    "date_to": {"type": "string", "description": "ISO date, default today"},
                    "tx_cost_bps": {"type": "integer", "default": 10},
                },
                "required": ["config_changes"],
            },
        },
        {
            "name": "sql_query",
            "description": (
                "Run ONE read-only SQL SELECT against the live Postgres (enforced "
                "read-only at the DB; writes fail). Key tables: ranking_runs/rankings "
                "(rank, composite_score, factor_scores jsonb), factor_runs/factor_scores "
                "(scores jsonb, per-factor columns), daily_prices (ticker,date,adjusted_close,"
                "close,volume), fundamentals, universe_snapshots/universe_tickers (sector), "
                "portfolio_runs/portfolio_holdings (target book), delta_runs/delta_intents "
                "(actions/approvals), alpaca_orders (status,notional,filled_at), "
                "live_positions + alpaca_sync_runs (broker state), vetter_runs/"
                "vetter_decisions/vetter_exclusions, risk_decisions (rule_triggered), "
                "backtest_runs (summary/validation jsonb, sim_mode)/backtest_trials, "
                "evaluator_reports. "
                f"Row cap {SQL_MAX_ROWS}, timeout {SQL_STATEMENT_TIMEOUT_MS // 1000}s. "
                "Prefer aggregates over raw dumps."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        {
            "name": "read_file",
            "description": (
                "Read a file (or list a directory) from the read-only repo mount. "
                "Available roots: services/ (all service source), shared/ (shared library "
                "+ strategy schema), docs/ (design docs — architecture.md is the source of "
                "truth for intent), strategies/ (all strategy YAMLs), db/ (migrations). "
                "Use this to critique the REAL implementation instead of guessing. "
                f"Returns up to {FILE_MAX_LINES} lines per call; use start_line to page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "e.g. services/pipeline/app/factors.py or strategies/"},
                    "start_line": {"type": "integer", "default": 1},
                    "max_lines": {"type": "integer", "default": FILE_MAX_LINES},
                },
                "required": ["path"],
            },
        },
    ]
    tools.append({
        "name": "preview_ranking",
        "description": (
            "FAST thesis triage (seconds, cheap — use BEFORE spending a run_backtest "
            "slot): re-rank the latest scored universe under a candidate config "
            "(config_changes = {dotted.path: value} DIFF over the active config, same "
            "shape as run_backtest) and diff it against the ACTIVE ranking. Returns "
            "the top-N membership changes (entered/left), the biggest rank movers, "
            "and rank-correlation. RANK-LEVEL ONLY: the builder's covariance/cluster/"
            "sector caps and the vetter are NOT applied — if the preview looks "
            "promising, confirm with run_backtest."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "config_changes": {
                    "type": "object",
                    "description": "dotted.path -> new value, applied to the active config",
                },
                "top_n": {"type": "integer", "default": 30,
                          "description": "membership window to compare (default max_positions-ish)"},
            },
            "required": ["config_changes"],
        },
    })
    tools.append({
        "name": "hypothesis_ledger",
        "description": (
            "Your durable cross-week memory: thesis -> planned test -> outcome. The "
            "packet's hypothesis_ledger section shows current entries; this tool "
            "WRITES them (the only write you have; its own table, nothing else). "
            "action='create' opens a new hypothesis (hypothesis + planned_test). "
            "action='update' resolves/annotates one by id (status: open|confirmed|"
            "refuted|abandoned, plus outcome text citing the evidence). Discipline: "
            "check the packet's open entries FIRST each review; resolve what this "
            "week's evidence settles; open entries for theses that need future data "
            "instead of re-deriving them next week."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update"]},
                "id": {"type": "integer", "description": "required for update"},
                "hypothesis": {"type": "string"},
                "planned_test": {"type": "string"},
                "status": {"type": "string",
                           "enum": ["open", "confirmed", "refuted", "abandoned"]},
                "outcome": {"type": "string"},
            },
            "required": ["action"],
        },
    })
    if TAVILY_API_KEY:
        tools.append({
            "name": "web_search",
            "description": (
                "Web search (Tavily) for EXTERNAL context: macro backdrop, factor "
                "literature, sector news. Results are logged verbatim in the audit "
                "transcript. Do not use it as a substitute for packet/SQL evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        })
    return tools


# ── run_backtest ──────────────────────────────────────────────────────────────

def apply_config_changes(base: dict, changes: dict[str, Any]) -> tuple[dict | None, str | None]:
    """Apply {dotted.path: value} onto a config dict and validate through
    StrategyConfig. Returns (validated_dict, None) or (None, error). Pure —
    unit-testable without the backtester."""
    import copy
    cfg = copy.deepcopy(base)
    for path, value in (changes or {}).items():
        parts = [p for p in str(path).split(".") if p]
        if not parts:
            return None, f"invalid config path: {path!r}"
        node = cfg
        for p in parts[:-1]:
            if not isinstance(node, dict):
                return None, f"config path {path!r} traverses a non-object at {p!r}"
            node = node.setdefault(p, {})
        if not isinstance(node, dict):
            return None, f"config path {path!r} traverses a non-object"
        node[parts[-1]] = value
    try:
        validated = StrategyConfig(**cfg)
    except Exception as exc:  # noqa: BLE001 — pydantic error text goes back to the LLM
        return None, f"candidate config INVALID (nothing was run): {exc}"
    return validated.model_dump(mode="json"), None


MAX_LEDGER_WRITES = int(os.getenv("EVALUATOR_MAX_LEDGER_WRITES", "6"))
MAX_PREVIEWS = int(os.getenv("EVALUATOR_MAX_PREVIEWS", "8"))


class BacktestBudget:
    """Per-review tool budgets (the agent loop owns one instance). Name kept from
    the original backtest-only version; it now also carries the cheap-tool caps
    (ledger writes, rank previews) so a looping model stays bounded."""
    def __init__(self, limit: int = MAX_BACKTESTS):
        self.limit = limit
        self.used = 0
        self.ledger_limit = MAX_LEDGER_WRITES
        self.ledger_used = 0
        self.preview_limit = MAX_PREVIEWS
        self.preview_used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    def take_ledger(self) -> bool:
        if self.ledger_used >= self.ledger_limit:
            return False
        self.ledger_used += 1
        return True

    def take_preview(self) -> bool:
        if self.preview_used >= self.preview_limit:
            return False
        self.preview_used += 1
        return True


async def run_backtest(args: dict, *, engine, budget: BacktestBudget) -> str:
    """Submit a config-replay for (active config + diff), poll to completion, and
    return summary+validation read from backtest_runs (the self-describing row)."""
    if not budget.take():
        return (f"BACKTEST BUDGET EXHAUSTED ({budget.limit} per review). Base further "
                "reasoning on the runs already completed; recommend follow-up tests for "
                "next week instead of running more now.")

    try:
        base_cfg, _hash = load_strategy(STRATEGY_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        return f"error: could not load active strategy config: {exc}"
    candidate, err = apply_config_changes(base_cfg.model_dump(mode="json"),
                                          args.get("config_changes") or {})
    if err:
        budget.used -= 1  # a rejected config never ran — don't burn the budget
        return err

    payload: dict[str, Any] = {"config": candidate,
                               "tx_cost_bps": int(args.get("tx_cost_bps") or 10)}
    if args.get("date_from"):
        payload["date_from"] = str(args["date_from"])
    if args.get("date_to"):
        payload["date_to"] = str(args["date_to"])

    async with httpx.AsyncClient(timeout=60.0) as client:
        # The backtester runs one job at a time (409 while busy) — wait politely.
        started = None
        deadline = time.monotonic() + BACKTEST_TIMEOUT_SECS
        while time.monotonic() < deadline:
            r = await client.post(f"{BACKTESTER_URL}/jobs/backtest-config", json=payload)
            if r.status_code == 409:
                await asyncio.sleep(BACKTEST_POLL_SECS)
                continue
            if r.status_code == 400:
                budget.used -= 1
                return f"backtester rejected the config: {r.text[:500]}"
            r.raise_for_status()
            started = r.json()
            break
        if not started:
            return "error: backtester stayed busy past the timeout — try later in the review"
        run_id = started["run_id"]

    # Poll the DB row (summary/validation live there; the HTTP run view omits them).
    from sqlalchemy import text as _sql
    deadline = time.monotonic() + BACKTEST_TIMEOUT_SECS
    while time.monotonic() < deadline:
        await asyncio.sleep(BACKTEST_POLL_SECS)
        async with engine.connect() as conn:
            row = (await conn.execute(_sql(
                "SELECT status, error_message, summary, validation, sim_mode, "
                "n_rebalances, date_from, date_to FROM backtest_runs "
                "WHERE run_id = CAST(:rid AS uuid)"), {"rid": run_id})
            ).mappings().first()
        if row and row["status"] in ("success", "failed"):
            if row["status"] == "failed":
                return f"backtest FAILED: {row['error_message']}"
            out = {
                "run_id": run_id,
                "sim_mode": row["sim_mode"],
                "date_from": str(row["date_from"]), "date_to": str(row["date_to"]),
                "n_rebalances": row["n_rebalances"],
                "summary": row["summary"],
                "validation": row["validation"],
                "config_changes_applied": args.get("config_changes") or {},
            }
            return _truncate(json.dumps(out, default=str))
    return f"error: backtest {run_id} still running after {BACKTEST_TIMEOUT_SECS:.0f}s — check backtest_runs later"


# ── sql_query ─────────────────────────────────────────────────────────────────

_SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"call|do|execute|listen|notify|refresh|reindex|cluster|comment|security|"
    r"lock|prepare|deallocate|import|set)\b", re.IGNORECASE)
# Dangerous FUNCTIONS a bare keyword scan misses (underscores defeat \b...\b):
# set_config could bump our statement_timeout; pg_sleep burns the loop's clock;
# the file/large-object functions read server files. The READ ONLY transaction
# already blocks writes — this keeps the tool from being a nuisance vector.
_SQL_FORBIDDEN_FUNCS = re.compile(
    r"\b(set_config|pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|"
    r"pg_write_file|lo_import|lo_export|dblink|pg_terminate_backend|"
    r"pg_cancel_backend|pg_reload_conf)\b", re.IGNORECASE)


def sql_guard(query: str) -> str | None:
    """Static pre-check (defense in depth — the READ ONLY transaction is the hard
    guarantee). Returns an error string or None when acceptable."""
    q = (query or "").strip().rstrip(";").strip()
    if not q:
        return "empty query"
    if ";" in q:
        return "one statement only (no semicolons)"
    if not re.match(r"^(select|with)\b", q, re.IGNORECASE):
        return "read-only: query must start with SELECT or WITH"
    m = _SQL_FORBIDDEN.search(q)
    if m:
        return f"read-only: keyword {m.group(0)!r} not allowed"
    m = _SQL_FORBIDDEN_FUNCS.search(q)
    if m:
        return f"read-only: function {m.group(0)!r} not allowed"
    return None


async def sql_query(args: dict, *, engine) -> str:
    query = str(args.get("query") or "")
    err = sql_guard(query)
    if err:
        return f"query rejected: {err}"
    q = query.strip().rstrip(";")
    from sqlalchemy import text as _sql
    try:
        async with engine.connect() as conn:
            # First statements of the tx: read-only + timeout. READ ONLY makes any
            # write fail at Postgres regardless of what slipped past the regex.
            await conn.execute(_sql("SET TRANSACTION READ ONLY"))
            await conn.execute(_sql(f"SET LOCAL statement_timeout = {SQL_STATEMENT_TIMEOUT_MS}"))
            result = await conn.execute(_sql(q))
            rows = result.mappings().fetchmany(SQL_MAX_ROWS + 1)
            await conn.rollback()
    except Exception as exc:  # noqa: BLE001 — DB error text is useful to the LLM
        return f"query error: {str(exc)[:800]}"
    capped = len(rows) > SQL_MAX_ROWS
    out_rows = [dict(r) for r in rows[:SQL_MAX_ROWS]]
    payload = {"rows": out_rows, "row_count": len(out_rows),
               "truncated_at_row_cap": capped}
    return _truncate(json.dumps(payload, default=str))


# ── read_file ─────────────────────────────────────────────────────────────────

# Never serve credential-shaped files even if someone mounts too much later.
_BLOCKED_BASENAMES = re.compile(r"^\.env|\.pem$|\.key$|secret", re.IGNORECASE)


def resolve_repo_path(path: str, root: str = REPO_ROOT) -> tuple[str | None, str | None]:
    """Resolve a user path under the read-only repo root. (abs_path, None) or
    (None, error). Pure — unit-testable."""
    rel = (path or "").strip().lstrip("/")
    if not rel:
        rel = "."
    abs_path = os.path.realpath(os.path.join(root, rel))
    root_real = os.path.realpath(root)
    if abs_path != root_real and not abs_path.startswith(root_real + os.sep):
        return None, f"path {path!r} escapes the repo root"
    if _BLOCKED_BASENAMES.search(os.path.basename(abs_path)):
        return None, "credential-shaped files are not readable"
    return abs_path, None


async def read_file(args: dict) -> str:
    abs_path, err = resolve_repo_path(str(args.get("path") or ""))
    if err:
        return f"read rejected: {err}"
    if not os.path.exists(abs_path):
        return f"not found: {args.get('path')!r} (roots: services/ shared/ docs/ strategies/ db/)"
    if os.path.isdir(abs_path):
        try:
            names = sorted(os.listdir(abs_path))
        except OSError as exc:
            return f"list error: {exc}"
        entries = [n + ("/" if os.path.isdir(os.path.join(abs_path, n)) else "")
                   for n in names if not n.startswith((".", "__pycache__"))]
        return json.dumps({"directory": args.get("path"), "entries": entries[:400]})
    start = max(1, int(args.get("start_line") or 1))
    max_lines = min(FILE_MAX_LINES, max(1, int(args.get("max_lines") or FILE_MAX_LINES)))
    try:
        with open(abs_path, "r", errors="replace") as f:
            all_lines = f.readlines()
    except OSError as exc:
        return f"read error: {exc}"
    chunk = all_lines[start - 1: start - 1 + max_lines]
    body = "".join(f"{i}\t{line}" for i, line in enumerate(chunk, start=start))
    header = (f"{args.get('path')} — lines {start}-{start + len(chunk) - 1} "
              f"of {len(all_lines)}\n")
    return _truncate(header + body)


# ── web_search ────────────────────────────────────────────────────────────────

async def web_search(args: dict) -> str:
    if not TAVILY_API_KEY:
        return "web_search unavailable: TAVILY_API_KEY not configured"
    query = str(args.get("query") or "").strip()
    if not query:
        return "empty query"
    n = min(10, max(1, int(args.get("max_results") or 5)))
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(TAVILY_BASE, json={
                "api_key": TAVILY_API_KEY, "query": query,
                "search_depth": "basic", "max_results": n,
            })
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        return f"search error: {str(exc)[:300]}"
    results = [{"title": it.get("title"), "url": it.get("url"),
                "content": (it.get("content") or "")[:600]}
               for it in (data.get("results") or [])[:n]]
    return _truncate(json.dumps({"query": query, "results": results}))


# ── preview_ranking ───────────────────────────────────────────────────────────

def rank_delta(active_df, candidate_df, top_n: int) -> dict:
    """Pure comparison of two rank_universe outputs. Unit-testable."""
    a = {r.ticker: int(r.rank) for r in active_df.itertuples()}
    c = {r.ticker: int(r.rank) for r in candidate_df.itertuples()}
    top_a = {t for t, r in a.items() if r <= top_n}
    top_c = {t for t, r in c.items() if r <= top_n}
    entered = sorted(top_c - top_a, key=lambda t: c[t])
    left = sorted(top_a - top_c, key=lambda t: a[t])
    movers = sorted(
        ({"ticker": t, "rank_active": a[t], "rank_candidate": c[t],
          "delta": a[t] - c[t]}
         for t in (set(a) & set(c)) if a[t] != c[t]),
        key=lambda m: -abs(m["delta"]))[:20]
    # Spearman-ish agreement over the common set (rank correlation without scipy).
    common = list(set(a) & set(c))
    corr = None
    if len(common) > 2:
        import statistics
        ra = [a[t] for t in common]
        rc = [c[t] for t in common]
        sa, sc = statistics.pstdev(ra), statistics.pstdev(rc)
        if sa > 0 and sc > 0:
            ma, mc = statistics.fmean(ra), statistics.fmean(rc)
            cov = sum((x - ma) * (y - mc) for x, y in zip(ra, rc)) / len(common)
            corr = round(cov / (sa * sc), 4)
    return {
        "top_n": top_n,
        "entered_top_n": [{"ticker": t, "rank_candidate": c[t],
                           "rank_active": a.get(t)} for t in entered[:25]],
        "left_top_n": [{"ticker": t, "rank_active": a[t],
                        "rank_candidate": c.get(t)} for t in left[:25]],
        "membership_change_count": len(entered),
        "biggest_movers": movers,
        "rank_correlation": corr,
        "ranked_active": len(a), "ranked_candidate": len(c),
    }


async def preview_ranking(args: dict, *, engine, budget: BacktestBudget) -> str:
    """Re-rank the latest scored universe under (active config + diff) with the
    vendored production rank_universe, and diff against the active ranking."""
    if not budget.take_preview():
        return f"PREVIEW BUDGET EXHAUSTED ({budget.preview_limit} per review)."
    try:
        base_cfg, _h = load_strategy(STRATEGY_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        return f"error: could not load active strategy config: {exc}"
    candidate_dict, err = apply_config_changes(base_cfg.model_dump(mode="json"),
                                               args.get("config_changes") or {})
    if err:
        budget.preview_used -= 1
        return err

    import asyncio as _asyncio
    import pandas as pd
    from app._vendor.rank import FACTORS, rank_universe

    from sqlalchemy import text as _sql
    async with engine.connect() as conn:
        run_row = (await conn.execute(_sql(
            "SELECT run_id, score_date FROM factor_runs WHERE status='success' "
            "ORDER BY score_date DESC, completed_at DESC NULLS LAST LIMIT 1"
        ))).mappings().first()
        if not run_row:
            return "error: no successful factor run to preview against"
        rows = (await conn.execute(_sql(
            "SELECT ticker, scores FROM factor_scores WHERE run_id = :rid"
        ), {"rid": run_row["run_id"]})).mappings().fetchall()
        regime_row = (await conn.execute(_sql(
            "SELECT regime FROM regime_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        ))).first()
    if not rows:
        return "error: latest factor run has no factor_scores rows"
    regime = regime_row[0] if regime_row else next(iter(base_cfg.regime_detection.regimes))

    def _df():
        recs = []
        for r in rows:
            s = r["scores"]
            if isinstance(s, str):
                s = _loads_json(s)
            s = s or {}
            recs.append({"ticker": r["ticker"],
                         **{f: (float(s[f]) if s.get(f) is not None else float("nan"))
                            for f in FACTORS}})
        return pd.DataFrame(recs)

    candidate_cfg = StrategyConfig(**candidate_dict)
    try:
        df = await _asyncio.to_thread(_df)
        active_ranked = await _asyncio.to_thread(rank_universe, df, regime, base_cfg)
        cand_ranked = await _asyncio.to_thread(rank_universe, df, regime, candidate_cfg)
    except Exception as exc:  # noqa: BLE001
        return f"preview error: {str(exc)[:500]}"
    top_n = max(5, min(100, int(args.get("top_n") or
                                base_cfg.portfolio_builder.max_positions)))
    out = rank_delta(active_ranked, cand_ranked, top_n)
    out["score_date"] = str(run_row["score_date"])
    out["regime"] = regime
    out["note"] = ("rank-level only — builder caps/covariance and vetter NOT applied; "
                   "confirm a promising diff with run_backtest")
    return _truncate(json.dumps(out, default=str))


def _loads_json(raw):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


# ── hypothesis_ledger ─────────────────────────────────────────────────────────

_LEDGER_STATUSES = ("open", "confirmed", "refuted", "abandoned")
_LEDGER_TEXT_CAP = 1200


def ledger_validate(args: dict) -> str | None:
    """Static validation of a ledger write. Returns error or None. Pure."""
    action = args.get("action")
    if action not in ("create", "update"):
        return "action must be 'create' or 'update'"
    if action == "create" and not (args.get("hypothesis") or "").strip():
        return "create requires a non-empty hypothesis"
    if action == "update":
        try:
            int(args.get("id"))
        except (TypeError, ValueError):
            return "update requires an integer id"
        if not any((args.get(k) or "").strip()
                   for k in ("status", "outcome", "hypothesis", "planned_test")):
            return "update must change at least one of status/outcome/hypothesis/planned_test"
    status = args.get("status")
    if status is not None and status not in _LEDGER_STATUSES:
        return f"status must be one of {_LEDGER_STATUSES}"
    return None


async def hypothesis_ledger(args: dict, *, engine, budget: BacktestBudget) -> str:
    """The evaluator's ONE write tool — INSERT/UPDATE on evaluator_hypotheses only."""
    err = ledger_validate(args)
    if err:
        return f"ledger write rejected: {err}"
    if not budget.take_ledger():
        return f"LEDGER BUDGET EXHAUSTED ({budget.ledger_limit} writes per review)."

    def _cap(v):
        return (str(v).strip()[:_LEDGER_TEXT_CAP]) if v is not None else None

    from datetime import datetime, timezone
    from sqlalchemy import text as _sql

    from stock_strategy_shared.trading_tz import resolve_trading_tz
    now = datetime.now(timezone.utc)
    # Week stamped in the TRADING timezone, same as evaluator_reports (the H1
    # fix) — UTC stamping filed a Sunday-evening-ET hypothesis under NEXT ISO
    # week, disagreeing with the report it was opened by (audit finding).
    iso = datetime.now(resolve_trading_tz("SCHEDULE_TZ")).date().isocalendar()
    try:
        if args["action"] == "create":
            async with engine.begin() as conn:
                new_id = (await conn.execute(_sql(
                    "INSERT INTO evaluator_hypotheses "
                    "(status, hypothesis, planned_test, created_iso_year, created_iso_week) "
                    "VALUES ('open', :h, :t, :y, :w) RETURNING id"
                ), {"h": _cap(args.get("hypothesis")), "t": _cap(args.get("planned_test")),
                    "y": iso.year, "w": iso.week})).scalar()
            return json.dumps({"created": True, "id": new_id})
        sets, params = ["updated_at = :now"], {"now": now, "id": int(args["id"])}
        for col in ("status", "outcome", "hypothesis", "planned_test"):
            if (args.get(col) or "").strip():
                sets.append(f"{col} = :{col}")
                params[col] = _cap(args[col])
        async with engine.begin() as conn:
            res = await conn.execute(_sql(
                f"UPDATE evaluator_hypotheses SET {', '.join(sets)} WHERE id = :id"
            ), params)
        if res.rowcount == 0:
            budget.ledger_used -= 1
            return f"no hypothesis with id {args['id']} — check the packet's ledger section"
        return json.dumps({"updated": True, "id": int(args["id"])})
    except Exception as exc:  # noqa: BLE001
        return f"ledger error: {str(exc)[:400]}"


# ── dispatch ──────────────────────────────────────────────────────────────────

def _truncate(s: str, cap: int = RESULT_CHAR_CAP) -> str:
    if len(s) <= cap:
        return s
    return s[:cap] + f"\n…[truncated at {cap} chars]"


async def execute_tool(name: str, args: dict, *, engine, budget: BacktestBudget) -> str:
    """Route one tool call. Never raises — errors return as strings so the LLM can
    adapt (and the loop records them in the transcript)."""
    try:
        if name == "run_backtest":
            return await run_backtest(args, engine=engine, budget=budget)
        if name == "sql_query":
            return await sql_query(args, engine=engine)
        if name == "read_file":
            return await read_file(args)
        if name == "preview_ranking":
            return await preview_ranking(args, engine=engine, budget=budget)
        if name == "hypothesis_ledger":
            return await hypothesis_ledger(args, engine=engine, budget=budget)
        if name == "web_search":
            return await web_search(args)
        return f"unknown tool: {name}"
    except Exception as exc:  # noqa: BLE001 — a tool bug must not kill the review
        return f"tool {name} crashed: {str(exc)[:500]}"
