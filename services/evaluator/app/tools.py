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
                "so running many and citing the best is self-penalizing. Takes minutes; "
                f"budget: {MAX_BACKTESTS} per review. An empty config_changes replays the "
                "active config as a baseline."
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


class BacktestBudget:
    """Per-review backtest counter (the agent loop owns one instance)."""
    def __init__(self, limit: int = MAX_BACKTESTS):
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
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
        if name == "web_search":
            return await web_search(args)
        return f"unknown tool: {name}"
    except Exception as exc:  # noqa: BLE001 — a tool bug must not kill the review
        return f"tool {name} crashed: {str(exc)[:500]}"
