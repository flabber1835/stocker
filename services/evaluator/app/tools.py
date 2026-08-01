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
  queue_strategy_experiment — enqueue-only append to the wind-tunnel experiment
                 queue (artifacts/bt/proposals.json): a COMPLETE candidate
                 StrategyConfig, schema-validated, with an auto-computed diff vs
                 the active config. The daily lane scores it on tune + a held-out
                 validate window; a winner is auto-applied by deterministic code.
                 A whole config is the ONLY currency — to change one field, send
                 the full YAML with that field changed.

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

# Wind-tunnel results DB (read-only). Unset => the tool is absent, exactly like
# web_search without a Tavily key — a review must never fail because the
# backtest machine is down.
BT_DATABASE_URL = os.getenv("BT_DATABASE_URL", "")

MAX_BACKTESTS = int(os.getenv("EVALUATOR_MAX_BACKTESTS", "3"))
BACKTEST_POLL_SECS = float(os.getenv("EVALUATOR_BACKTEST_POLL_SECS", "5"))
# Submit-phase deadline (waiting out a 409-busy backtester before giving up).
BACKTEST_TIMEOUT_SECS = float(os.getenv("EVALUATOR_BACKTEST_TIMEOUT_SECS", "900"))
# Inline result wait — deliberately SHORT (fast runs return synchronously; slow
# runs return a non-error 'running' handoff with poll instructions instead of
# wedging a tool turn for 15 min; see run_backtest).
BACKTEST_RESULT_WAIT_SECS = float(os.getenv("EVALUATOR_BACKTEST_RESULT_WAIT_SECS", "180"))
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
                "RE-WEIGHT stored factors over history. It re-ranks and re-selects every "
                "historical rebalance date from the PERSISTED point-in-time factor_scores, "
                "de-biased (t+1 fills, no survivorship, 10bps cost). "
                "WHAT IT CANNOT DO, and will REFUSE rather than answer wrongly: it does not "
                "recompute factors, so a change to factor CONSTRUCTION (momentum/volatility "
                "windows, pe_pb_cap, sector-neutralisation) is unmodellable here; it applies "
                "NO exclusions, not even the deterministic falling-knife veto live uses; and "
                "it is holdings-agnostic, so turnover_penalty is inert. For any of those, use "
                "queue_strategy_experiment (the wind tunnel) — it recomputes factors from raw "
                "prices, applies the veto, and models holdings. Use THIS tool for factor "
                "WEIGHTS, position/sector/cluster caps, candidate_count, vol/beta targets. "
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
                "read-only at the DB; writes fail). "
                "THE SCHEMA IS DISCOVERABLE — do not guess column names, and do not "
                "assume a column is absent because the packet never shows it. Many "
                "columns are recorded and never surfaced (the builder persists "
                "portfolio_estimated_vol, avg_pairwise_correlation and "
                "risk_estimate_degraded; alpaca_orders records created_at, "
                "submitted_at, filled_at, qty, filled_qty, avg_fill_price and "
                "risk_reason). Look before concluding evidence does not exist:\n"
                "  SELECT table_name, column_name, data_type FROM "
                "information_schema.columns WHERE table_schema='public' "
                "AND table_name IN (...) ORDER BY table_name, ordinal_position\n"
                "TABLES, by what they answer (columns via the query above):\n"
                "  what was scored/ranked  factor_runs, factor_scores, ranking_runs, "
                "rankings, regime_snapshots\n"
                "  what we wanted to hold  portfolio_runs, portfolio_holdings, "
                "target_history\n"
                "  what we decided to do   delta_runs, delta_intents, "
                "decision_outcomes (forward-labelled outcomes per decision)\n"
                "  vetting                 vetter_runs, vetter_decisions, "
                "vetter_exclusions\n"
                "  execution               risk_decisions, alpaca_orders, "
                "execution_traces, execution_steps\n"
                "  broker truth            alpaca_sync_runs, live_positions\n"
                "  market data             daily_prices, fundamentals, earnings, "
                "universe_snapshots, universe_tickers\n"
                "  counterfactuals         shadow_runs (theoretical targets under "
                "another config)\n"
                "  backtests               backtest_runs, backtest_trials\n"
                "  this loop's own history evaluator_reports, evaluator_hypotheses, "
                "config_changes\n"
                "  operations              ingest_runs, pipeline_runs, scheduler_runs\n"
                f"Row cap {SQL_MAX_ROWS}, timeout {SQL_STATEMENT_TIMEOUT_MS // 1000}s. "
                "Prefer aggregates over raw dumps. Use this to DRILL DOWN when a "
                "packet number looks wrong or incomplete — the packet carries what "
                "every review needs, not everything that exists."
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
        "name": "queue_strategy_experiment",
        "description": (
            "Queue an ENTIRE candidate strategy config (full StrategyConfig JSON, "
            "not a single-field diff) for the wind tunnel's DAILY experiment lane: "
            "one full-history backtest per candidate (earliest viable start → today, "
            "full universe), one at a time, capped per week. Use when your thesis "
            "involves INTERACTING changes (e.g. concentration + knife threshold + "
            "momentum variant together) that single-field diffs can't express. The "
            "config is schema-validated and an AUTO-COMPUTED diff vs the active "
            "config is stored with it, so results stay attributable; the hypothesis "
            "is mandatory and read cold next to the results in a future review "
            "(experiment_lane packet section, typically 1-3 days). Draws from the "
            "per-review experiment budget — the statistical "
            "budget against our one shared history is deliberate; prefer few, "
            "well-motivated candidates over many draws. AUTO-PROMOTION (paper "
            "mode): a candidate whose recent-window CAGR beats the recent-window "
            "baseline by the deterministic gate margin (drawdown within tolerance) "
            "is AUTOMATICALLY validated and applied as the LIVE config — no human "
            "click. Author candidates with that weight: each one is a potential "
            "live strategy, not a thought experiment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "config": {"type": "object",
                           "description": "complete StrategyConfig as JSON (start from the active config and modify)"},
                "hypothesis": {"type": "string",
                               "description": "what you expect and WHY — the thesis this candidate tests"},
                "mechanism": {
                    "type": "string", "enum": sorted(MECHANISMS),
                    "description": (
                        "WHICH assumption this candidate probes. Enforced: only "
                        "ONE candidate per mechanism per review, because four "
                        "variants of one knob is ONE experiment wearing four "
                        "slots. Spend the week's slots on DIFFERENT mechanisms — "
                        "that is where the information is. Also the key results "
                        "are aggregated by, so a future review can read 'this "
                        "class of change has failed 4 for 4' instead of a list "
                        "of unrelated config hashes. "
                        + " | ".join(f"{k}: {v}" for k, v in sorted(MECHANISMS.items()))),
                },
                "predicted_tune_cagr_edge": {
                    "type": "number",
                    "description": (
                        "YOUR PREDICTION, and you are SCORED on it. How much "
                        "should this candidate beat the BASELINE's tune-window "
                        "CAGR by, in absolute terms? 0.02 means '+2 percentage "
                        "points of CAGR'. Negative is a legitimate answer (a "
                        "candidate worth testing can be expected to lose). When "
                        "the run lands, the actual edge is computed and your "
                        "error and directional accuracy are recorded — the "
                        "prediction_scorecard packet section shows your running "
                        "bias across every candidate you have ever queued. "
                        "Guessing high to justify a candidate is self-defeating: "
                        "it makes you measurably over-optimistic. Omit only if "
                        "you genuinely have no expectation."),
                },
                "regime": {"type": "string", "enum": sorted(STRESS_REGIMES),
                           "description": (
                               "OPTIONAL. Score this candidate over a fixed "
                               "historical crisis instead of the rolling recent "
                               "window. DIAGNOSTIC ONLY — a regime run can NEVER "
                               "promote, because its windows are a crash/recovery "
                               "split, not a tune/hold-out pair. Use it to ask "
                               "'how does this behave when the market breaks?'. "
                               "Raw date ranges are deliberately not offered: "
                               "choosing both the config and the period searches "
                               "two dimensions while the DSR penalises one. "
                               + " | ".join(f"{k}: {v['stresses']}"
                                            for k, v in sorted(STRESS_REGIMES.items())))},
            },
            "required": ["config", "hypothesis", "mechanism"],
        },
    })
    if BT_DATABASE_URL:
        tools.append({
            "name": "bt_sql_query",
            "description": (
                "Read-only SELECT against the WIND TUNNEL's own database "
                "(bt-postgres) — the RESULTS of backtests, so you can ask WHY a "
                "candidate won or lost instead of only seeing four summary "
                "numbers. Tables: bt_sweeps (status, windows, error_message, "
                "started_at/completed_at — how long a run lasted and why it "
                "died), bt_sweep_results / bt_sweep_aggregates (per-config, "
                "per-window in_sample/out_sample summaries), bt_runs (single "
                "backtests), bt_equity (the daily equity + spy_value + drawdown "
                "path, INTERACTIVE runs only), bt_sweep_equity (the same daily "
                "path for EXPERIMENT-LANE candidates, keyed sweep_id/config_idx/"
                "window_idx/phase — use this to see WHEN a candidate diverged "
                "from SPY rather than only by how much), bt_positions (what a run "
                "HELD on each rebalance date), bt_trades (every fill with price "
                "and reason). "
                "The raw price/fundamental corpus is deliberately NOT reachable: "
                "ad-hoc mining of 20 years of history would bypass the "
                "backtest_trials accounting that deflates your DSR. "
                f"Row cap {SQL_MAX_ROWS}, timeout {SQL_STATEMENT_TIMEOUT_MS // 1000}s. "
                "Prefer aggregates over raw dumps."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        })
    tools.append({
        "name": "hypothesis_ledger",
        "description": (
            "Your durable cross-week memory: thesis -> planned test -> outcome. The "
            "packet's hypothesis_ledger section shows current entries; this tool "
            "WRITES them (its own table, nothing else; your only other write is "
            "queue_strategy_experiment, which only appends to the experiment queue). "
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


# Mirrors bt-scheduler/app/logic.py STRESS_REGIMES. Duplicated ON PURPOSE: the
# two stacks share no code path (separate compose projects, one-way file
# bridge), so this is the tool-schema copy the LLM sees. A cross-stack test
# (tests/cross_service/) asserts the two tables stay identical — if they drift,
# the evaluator offers a regime the lane will refuse.
STRESS_REGIMES: dict[str, dict] = {
    "gfc_2008": {"stresses": "credit crisis, -55% market, March-2009 momentum crash"},
    "covid_2020": {"stresses": "fastest -34% then a V — worst case for a drawdown veto"},
    "bear_2022": {"stresses": "rate-shock grind, growth->value rotation"},
    "energy_shock_2015": {"stresses": "oil -70% sector blowup — concentration risk"},
    "volmageddon_2018": {"stresses": "Feb-2018 vol spike + Q4 drawdown"},
}

MAX_LEDGER_WRITES = int(os.getenv("EVALUATOR_MAX_LEDGER_WRITES", "6"))
MAX_PREVIEWS = int(os.getenv("EVALUATOR_MAX_PREVIEWS", "8"))
# 5, matching the lane's BT_EXPERIMENTS_PER_WEEK candidate cap exactly (baselines
# fire outside that cap). Raising this further does nothing until the lane cap
# rises too.
MAX_QUEUED_EXPERIMENTS = int(os.getenv("EVALUATOR_MAX_QUEUED_EXPERIMENTS", "5"))

# The mechanism vocabulary. A candidate must name WHICH assumption it probes, so
# (a) the lane cannot be filled with four variants of one hypothesis, and (b)
# failures aggregate into "this CLASS of intervention does not work here" instead
# of a pile of unrelated config hashes. Deliberately coarse: these are the
# distinct places a strategy can be wrong, not a taxonomy of every field.
MECHANISMS: dict[str, str] = {
    "factor_weighting": "which factors the composite score weights, and how much",
    "factor_construction": "how a factor is COMPUTED (windows, definitions, new factors)",
    "entry_selection": "which candidates are eligible / how the pool is formed",
    "exit_hysteresis": "when a held name leaves (orphan timers, confirmation, rank buffers)",
    "portfolio_construction": "how selected names are weighted and sized",
    "concentration_control": "sector / cluster / position caps and book breadth",
    "risk_control": "vol targeting, beta targeting, cash reserve, falling-knife veto",
    "turnover_control": "drift thresholds and churn damping",
    "universe": "investability floors and what is in the pool at all",
}


def experiment_diversity_conflict(pending: list[dict], mechanism: str,
                                  changed_fields: set[str]) -> str | None:
    """Why this candidate is NOT independent of what is already queued, or None.

    Pure. Two deterministic refusals, in order of authority:
      1. the MECHANISM is already being probed this cycle — a second draw on the
         same assumption, which is what "four momentum thresholds" really is;
      2. the FIELD SET is identical — same knobs, different values. This is the
         backstop: config topology only approximates the economic hypothesis
         (two candidates can share a field while testing different mechanisms),
         so the label is authoritative and this catches an unlabelled repeat.
    Partial field overlap is NOT refused — it is legitimate (exit_threshold +
    confirmation_days vs exit_threshold + vol_scaling are different theses) and
    is surfaced to the model instead."""
    for e in pending:
        if e.get("mechanism") and e["mechanism"] == mechanism:
            return (f"mechanism {mechanism!r} is already queued this cycle "
                    f"(candidate {str(e.get('config_hash'))[:12]}: "
                    f"{str(e.get('hypothesis'))[:120]}). Four draws on one "
                    "assumption is ONE experiment — probe a different mechanism, "
                    f"or wait for that result. Mechanisms: {', '.join(sorted(MECHANISMS))}")
    for e in pending:
        if set(e.get("changed_fields") or []) == changed_fields and changed_fields:
            return (f"identical changed-field set to queued candidate "
                    f"{str(e.get('config_hash'))[:12]} "
                    f"({', '.join(sorted(changed_fields))[:200]}) — same knobs, "
                    "different values is a parameter sweep, not an independent "
                    "hypothesis")
    return None


def overlapping_fields(pending: list[dict], changed_fields: set[str]) -> set[str]:
    """Fields this candidate shares with anything already queued. Reported, not
    refused — see experiment_diversity_conflict. Pure."""
    out: set[str] = set()
    for e in pending:
        out |= (set(e.get("changed_fields") or []) & changed_fields)
    return out


class BacktestBudget:
    """Per-review tool budgets (the agent loop owns one instance). Name kept from
    the original backtest-only version; it now also carries the cheap-tool caps
    (ledger writes, rank previews, queued experiments) so a looping model stays
    bounded."""
    def __init__(self, limit: int = MAX_BACKTESTS):
        self.limit = limit
        self.used = 0
        self.ledger_limit = MAX_LEDGER_WRITES
        self.ledger_used = 0
        self.preview_limit = MAX_PREVIEWS
        self.preview_used = 0
        self.experiment_limit = MAX_QUEUED_EXPERIMENTS
        self.experiment_used = 0

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

    def take_experiment(self) -> bool:
        if self.experiment_used >= self.experiment_limit:
            return False
        self.experiment_used += 1
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
            if r.status_code == 422:
                # PARITY REFUSAL, not a malformed request: config-replay cannot
                # model something this diff changes (factor CONSTRUCTION, a
                # nonzero turnover penalty, ...). Do not burn the budget — no run
                # happened — and point the model at the engine that CAN answer,
                # rather than letting it read the refusal as "this idea failed".
                budget.used -= 1
                return (f"config-replay cannot faithfully score this diff: "
                        f"{r.text[:700]}")
            r.raise_for_status()
            started = r.json()
            break
        if not started:
            return "error: backtester stayed busy past the timeout — try later in the review"
        run_id = started["run_id"]

    # Poll the DB row (summary/validation live there; the HTTP run view omits them).
    # SHORT inline wait only: a full config-replay takes ~10-20 min on the NAS
    # (universe-scale re-rank per rebalance date), so waiting for completion here
    # burned a 900s turn and still returned an "error" the model had to recover
    # from by hand-polling (observed in the W29 transcript — twice). Waiting
    # briefly catches fast runs; otherwise the DESIGNED contract is async: return
    # the run_id with poll instructions as a NORMAL (non-error) result.
    from sqlalchemy import text as _sql
    deadline = time.monotonic() + BACKTEST_RESULT_WAIT_SECS
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
    return json.dumps({
        "status": "running",
        "run_id": run_id,
        "config_changes_applied": args.get("config_changes") or {},
        "note": (f"NOT an error — a full replay takes ~10-20 min on this host. The run "
                 f"continues in the background. Do OTHER investigation now, then read the "
                 f"result with sql_query: SELECT status, n_rebalances, summary, validation "
                 f"FROM backtest_runs WHERE run_id = '{run_id}' (status 'success' when done). "
                 "Submitting another backtest before this finishes will queue behind it."),
    })


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


# ── bt_sql_query (wind-tunnel RESULTS, read-only) ─────────────────────────────

# ALLOWLIST, enforced in Python — not a prompt instruction. The raw corpus
# (bt_prices ~35M rows, bt_fundamentals) is excluded on purpose: an unbounded
# query contends with a running sweep (bt-engine is capped at 4g and pegs a core
# mid-run), and ad-hoc mining of 20 years of history is a data-dredging path
# that bypasses the trials accounting entirely — the model could "find" an
# in-sample pattern and author a config from it with no trial registered.
# bt_sweep_equity is the per-session curve for SWEEP legs; bt_equity covers only
# interactive /jobs/run. Without it a candidate's SHAPE is unreadable — only its
# summary — so "did the book fall while SPY held up, and when?" was unanswerable
# for the very runs that decide promotion.
#
# Keep this a PLAIN tuple literal with no inline comments: scripts/purge-void-bt-
# results.sh is cross-checked against it by parsing this expression, and a comment
# containing a ')' truncates that match.
BT_TABLES = ("bt_sweeps", "bt_sweep_results", "bt_sweep_aggregates", "bt_runs",
             "bt_equity", "bt_positions", "bt_trades", "bt_sweep_equity")
_BT_IDENT = re.compile(r"\b(bt_[a-z_]+)\b", re.IGNORECASE)


def bt_table_guard(query: str) -> str | None:
    """Every bt_* relation named in the query must be on the allowlist. Pure."""
    referenced = {m.lower() for m in _BT_IDENT.findall(query or "")}
    forbidden = sorted(referenced - set(BT_TABLES))
    if forbidden:
        return (f"table(s) {', '.join(forbidden)} are not readable — allowed: "
                f"{', '.join(BT_TABLES)}. The raw price/fundamental corpus is "
                "excluded so ad-hoc history mining cannot bypass the "
                "backtest_trials accounting that deflates your DSR.")
    if not referenced:
        return f"query must read one of: {', '.join(BT_TABLES)}"
    return None


_bt_engine = None


async def bt_sql_query(args: dict) -> str:
    """Same hard guarantees as sql_query (single statement, SET TRANSACTION READ
    ONLY, statement_timeout, row cap) plus the table allowlist. Best-effort: an
    unreachable wind tunnel degrades to a message, never an exception."""
    global _bt_engine
    if not BT_DATABASE_URL:
        return ("bt_sql_query unavailable: BT_DATABASE_URL not configured "
                "(the wind-tunnel results DB is not reachable from here)")
    query = str(args.get("query") or "")
    err = sql_guard(query) or bt_table_guard(query)
    if err:
        return f"query rejected: {err}"
    q = query.strip().rstrip(";")
    from sqlalchemy import text as _sql
    from sqlalchemy.ext.asyncio import create_async_engine
    try:
        if _bt_engine is None:
            _bt_engine = create_async_engine(BT_DATABASE_URL, pool_pre_ping=True,
                                             pool_size=1, max_overflow=1)
        async with _bt_engine.connect() as conn:
            await conn.execute(_sql("SET TRANSACTION READ ONLY"))
            await conn.execute(_sql(f"SET LOCAL statement_timeout = {SQL_STATEMENT_TIMEOUT_MS}"))
            result = await conn.execute(_sql(q))
            rows = result.mappings().fetchmany(SQL_MAX_ROWS + 1)
            await conn.rollback()
    except Exception as exc:  # noqa: BLE001 — the bt stack may simply be down
        return (f"wind-tunnel query error (the backtest machine may be down; "
                f"this is not fatal to the review): {str(exc)[:500]}")
    capped = len(rows) > SQL_MAX_ROWS
    return _truncate(json.dumps({"rows": [dict(r) for r in rows[:SQL_MAX_ROWS]],
                                 "row_count": min(len(rows), SQL_MAX_ROWS),
                                 "truncated_at_row_cap": capped}, default=str))


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


# ── queue_strategy_experiment (Phase 6c full-config lane) ─────────────────────

def config_diff(base: dict, cand: dict, prefix: str = "") -> dict:
    """Pure recursive diff of two config dicts → {dotted.path: {'from': x, 'to': y}}.
    Keys only in one side appear with the other side None. Keeps whole-config
    experiments attributable: 'this candidate won, and it differed in these N
    fields'."""
    out: dict = {}
    keys = set(base or {}) | set(cand or {})
    for k in sorted(keys, key=str):
        path = f"{prefix}.{k}" if prefix else str(k)
        b, c = (base or {}).get(k), (cand or {}).get(k)
        # Recurse when both are dicts, AND when one side is a dict and the
        # other absent — so a removed/added subtree still diffs to LEAF dotted
        # paths (universe.min_price: 5.0→None), not one opaque blob.
        if (isinstance(b, dict) or isinstance(c, dict)) and (
                isinstance(b, (dict, type(None))) and isinstance(c, (dict, type(None)))):
            out.update(config_diff(b or {}, c or {}, path))
        elif b != c:
            out[path] = {"from": b, "to": c}
    return out


async def queue_strategy_experiment(args: dict, *, budget: BacktestBudget) -> str:
    """Validate a FULL candidate StrategyConfig, compute its diff vs the active
    config, and append it (kind='full_config') to the shared proposals queue.
    The bt-scheduler's daily experiment lane runs it as one full-history
    backtest (tune + held-out validate)."""
    pred = args.get("predicted_tune_cagr_edge")
    if pred is not None:
        try:
            pred = float(pred)
        except (TypeError, ValueError):
            return "queue rejected: predicted_tune_cagr_edge must be a number (0.02 = +2pp CAGR)"
        if not -1.0 <= pred <= 1.0:
            return (f"queue rejected: predicted_tune_cagr_edge {pred} is outside "
                    "[-1, 1] — it is an absolute CAGR edge (0.02 = +2pp), not a percent")
    regime = str(args.get("regime") or "").strip() or None
    if regime and regime not in STRESS_REGIMES:
        return (f"queue rejected: unknown regime {regime!r} — choose one of "
                f"{', '.join(sorted(STRESS_REGIMES))} (raw date ranges are not offered)")
    hypothesis = str(args.get("hypothesis") or "").strip()
    if not hypothesis:
        return ("queue rejected: state the hypothesis this candidate tests — "
                "future reviews read it cold next to the results")
    mechanism = str(args.get("mechanism") or "").strip()
    if mechanism not in MECHANISMS:
        return (f"queue rejected: mechanism must be one of "
                f"{', '.join(sorted(MECHANISMS))} — it is what stops the week's "
                "slots filling with variants of one hypothesis, and what lets a "
                "future review aggregate failures by CLASS of intervention")
    cand = args.get("config")
    if not isinstance(cand, dict) or not cand:
        return "queue rejected: config must be a complete StrategyConfig JSON object"

    from stock_strategy_shared.schemas.strategy import StrategyConfig
    try:
        validated = StrategyConfig(**cand).model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        return f"queue rejected: config failed schema validation: {str(exc)[:600]}"

    try:
        base_cfg, _hash = load_strategy(STRATEGY_CONFIG_PATH)
        base = base_cfg.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        return f"error: could not load active strategy config: {exc}"
    diff = config_diff(base, validated)
    if not diff:
        return ("queue rejected: candidate is identical to the active config — "
                "the baseline already covers it")

    if not budget.take_experiment():
        return (f"EXPERIMENT BUDGET EXHAUSTED ({budget.experiment_limit} per review). "
                "Note remaining theses in the hypothesis_ledger for next week instead.")

    import hashlib as _hashlib
    import json as _json
    import uuid as _uuid
    from datetime import datetime, timezone

    cfg_hash = _hashlib.sha256(
        _json.dumps(validated, sort_keys=True, default=str).encode()).hexdigest()[:16]

    from app import proposals as _props
    try:
        with _props.proposals_lock():
            content = _props.read_proposals_file() or {"proposals": []}
            entries = content.setdefault("proposals", [])
            # Same config under a DIFFERENT regime is a legitimate new test, so
            # the dedup key is (config_hash, regime), not config_hash alone.
            if any(e.get("kind") == "full_config" and e.get("config_hash") == cfg_hash
                   and (e.get("regime") or None) == regime
                   and e.get("status") in ("pending", "testing", "tested")
                   for e in entries):
                budget.experiment_used -= 1  # dupes never burn budget
                return ("already queued/tested: an identical candidate config "
                        f"(hash {cfg_hash}) exists — argue from its results instead")
            pending_full = [e for e in entries
                            if e.get("kind") == "full_config"
                            and e.get("status") == "pending"]
            if len(pending_full) >= 6:
                budget.experiment_used -= 1
                return "queue rejected: 6 full-config candidates already pending"
            # INDEPENDENCE. Enforced here rather than only asked for in the
            # prompt: breadth is the whole point of the raised budget, and the
            # under-generation it fixes was itself a case of trusting an
            # instruction to carry a property nothing checked.
            changed_fields = set(diff)
            conflict = experiment_diversity_conflict(
                pending_full, mechanism, changed_fields)
            if conflict:
                budget.experiment_used -= 1   # a refused draw costs no budget
                return f"queue rejected: {conflict}"
            overlap = overlapping_fields(pending_full, changed_fields)
            entries.append({
                "id": str(_uuid.uuid4()), "kind": "full_config",
                "status": "pending", "origin": "exploratory",
                "hypothesis": hypothesis, "config": validated,
                "config_hash": cfg_hash, "diff": diff, "regime": regime,
                "mechanism": mechanism,
                # Stored flat so the lane and the packet can aggregate outcomes
                # by mechanism/field without re-deriving them from the diff.
                "changed_fields": sorted(changed_fields),
                "predicted_tune_cagr_edge": pred,
                # The config this candidate (and its diff) was authored against.
                # Auto-promotion can change the live config while this sits
                # pending, which would make promoting it a silent REVERT of the
                # newer champion — the packet flags that as stale_vs_active_config.
                "queued_against_config_hash": _hash,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            })
            _props.write_proposals_file(content)
    except Exception as exc:  # noqa: BLE001
        budget.experiment_used -= 1
        return f"queue error: {str(exc)[:400]}"

    scored = (f" Prediction recorded: you expect {pred:+.4f} CAGR edge vs the "
              "baseline on tune; the actual will be scored against it."
              if pred is not None else
              " NO prediction supplied — this candidate cannot contribute to your "
              "calibration record.")
    where = (f" over stress regime {regime}: {STRESS_REGIMES[regime]['stresses']}"
             " — DIAGNOSTIC ONLY, this run can never promote" if regime else "")
    # Overlap short of an identical field set is legitimate; say so rather than
    # refusing, so the model can judge whether the two theses really differ.
    lap = (f" NOTE: shares field(s) {', '.join(sorted(overlap))[:200]} with an "
           "already-queued candidate — allowed (different mechanisms may touch "
           "the same knob), but the results will be harder to attribute."
           if overlap else "")
    left = max(0, budget.experiment_limit - budget.experiment_used)
    return (f"queued full-config candidate {cfg_hash}{where} ({len(diff)} field(s) differ "
            f"from active; mechanism={mechanism}). Runs in the daily experiment "
            "lane (one full-history backtest); results appear in the "
            f"experiment_lane packet section, typically within days.{scored}{lap} "
            f"{left} experiment slot(s) left this review — use them on DIFFERENT "
            "mechanisms where the evidence supports a thesis, and account for any "
            "you leave unused in your report. "
            f"diff: {_json.dumps(diff, default=str)[:800]}")




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
        if name == "bt_sql_query":
            return await bt_sql_query(args)
        if name == "read_file":
            return await read_file(args)
        if name == "preview_ranking":
            return await preview_ranking(args, engine=engine, budget=budget)
        if name == "hypothesis_ledger":
            return await hypothesis_ledger(args, engine=engine, budget=budget)
        if name == "queue_strategy_experiment":
            return await queue_strategy_experiment(args, budget=budget)
        if name == "web_search":
            return await web_search(args)
        return f"unknown tool: {name}"
    except Exception as exc:  # noqa: BLE001 — a tool bug must not kill the review
        return f"tool {name} crashed: {str(exc)[:500]}"
