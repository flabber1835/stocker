"""Phase-2 tool-use loop for the weekly evaluator.

The packet stays the deterministic opening brief (Phase 1 unchanged); this loop
lets the model INVESTIGATE before concluding: it may call the read-only tools in
app/tools.py (backtest a candidate config, query Postgres, read source/docs,
web-search) and must then produce the SAME report-JSON contract Phase 1 uses.

Flow: send packet + tool defs via the llm-gateway → while stop_reason=="tool_use"
execute each call and append tool_result messages → on end_turn parse the report.
Hard budgets (EVALUATOR_MAX_TOOL_TURNS gateway calls, EVALUATOR_MAX_BACKTESTS
replays) force a final tools-stripped answer when exhausted, so a looping model
costs bounded tokens and always yields a report. Every tool call is returned in a
transcript the caller persists to evaluator_reports.tool_transcript (audit: any
number the narrative cites traces to the exact query/backtest that produced it).

Boundary: identical to Phase 1 — advisory-only, read-only tools, LLM reached
exclusively through the llm-gateway.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import httpx

from app.report import (
    EVALUATOR_MAX_TOKENS,
    EVALUATOR_MODEL,
    EVALUATOR_PROVIDER,
    GATEWAY_TIMEOUT_SECS,
    LLM_GATEWAY_URL,
    REPORT_SCHEMA,
    SYSTEM_PROMPT,
    ReportResult,
    _parse_report_json,
    build_user_prompt,
    validate_recommendations,
)
import app.tools as _tools_mod
from app.tools import BacktestBudget, MAX_BACKTESTS, execute_tool, tool_definitions

MAX_TOOL_TURNS = int(os.getenv("EVALUATOR_MAX_TOOL_TURNS", "24"))
# Stored-transcript caps (the DB row must stay bounded even if a tool returns 20k chars).
_TRANSCRIPT_RESULT_CAP = 8000
_TRANSCRIPT_ARGS_CAP = 2000

TOOLS_ADDENDUM = """

TOOLS. You can now INVESTIGATE before concluding. Available tools:
- run_backtest: config-replay a candidate config (a {dotted.path: value} DIFF over the
  active config) through the live chain's own code, de-biased. USE THIS to test any
  YAML-edit recommendation you are about to make with medium/high confidence — cite the
  resulting sharpe/DSR/distribution in the recommendation's evidence. Consider one
  baseline replay of the ACTIVE config (empty diff) for comparison. The budget is small;
  spend it on your top thesis, not a parameter sweep. The DSR you see already deflates
  by every config tried, so cherry-picking the best run is self-defeating.
- preview_ranking: FAST (seconds) rank-level triage of a config diff — top-N membership
  changes + biggest movers vs the active ranking. Use it BEFORE spending a run_backtest
  slot; a diff that barely moves the ranking is not worth a backtest. Rank-level only
  (no builder caps / vetter) — a promising preview still needs run_backtest to confirm.
- sql_query: read-only SELECTs on the live DB — drill into any packet anomaly (a factor's
  IC, a specific trade, what a dropped name did next) instead of speculating.
- read_file: read the actual source/docs/strategies — ground structural findings in the
  REAL implementation (e.g. read services/pipeline/app/factors.py before claiming a
  factor computation is flawed).
- hypothesis_ledger: your DURABLE cross-week memory (the packet's hypothesis_ledger
  section shows current entries). START each review by checking open entries: resolve
  the ones this week's evidence settles (action=update, status confirmed/refuted/
  abandoned, outcome citing the evidence). When a thesis needs future data — "watch
  momentum IC two more weeks", "re-test beta_target once 4w of live equity exists" —
  CREATE an entry instead of re-deriving it next week. Its own table, nothing else.
- queue_experiment: queue a single-knob diff for the ISOLATED wind-tunnel sweep
  (decades of data, walk-forward OOS) WITHOUT recommending it — for theses you want
  tested but are not ready to put in front of the owner: refuting your own hunches,
  knob-sensitivity probes. Runs in the NEXT weekly sweep; results arrive in a future
  packet's backtest_lab.experiment_queue (1-2 weeks). Changes you DO recommend are
  queued automatically — never queue those twice. Pair important ones with a ledger
  entry so the thesis survives until results arrive.
- web_search: external context (macro, factor literature). Sparing use; packet/SQL
  evidence outranks it.

run_backtest is ASYNC: a full replay takes ~10-20 min on this host. If the result says
status "running", that is NOT an error — do other investigation (SQL drilling, previews,
ledger) and read the result later exactly as the note instructs. Submit backtests EARLY
in the review so they finish while you work.

SCHEMA CHEAT-SHEET (saves guessing; sql_query these directly):
  backtest_runs(run_id, status, sim_mode, date_from, date_to, n_rebalances,
    summary jsonb, validation jsonb, error_message, started_at, completed_at)
  ranking_runs(run_id, rank_date, status, config_hash) / rankings(run_id, ticker, rank,
    composite_score, percentile, factor_scores jsonb)
  portfolio_runs(run_id, source_ranking_run_id, vetter_run_id, portfolio_date, status) /
    portfolio_holdings(run_id, ticker, weight, original_rank)
  delta_runs(run_id, run_date, status) / delta_intents(run_id, ticker, action, rank, reason)
  vetter_runs(run_id, source_ranking_run_id, status) / vetter_exclusions(run_id, ticker,
    risk_type, reason, created_at)
  alpaca_sync_runs(run_id, status, account_value, completed_at) /
    live_positions(sync_run_id, ticker, qty, avg_entry_price, current_price,
    market_value, unrealized_pl, unrealized_plpc)
  alpaca_orders(ticker, action, side, qty, status, filled_at, avg_fill_price)
  daily_prices(ticker, date, adjusted_close) / factor_scores(run_id, ticker, score_date, ...)
  config_changes(config_field, old_value, new_value, applied_at) /
    evaluator_hypotheses(id, status, hypothesis, outcome)

live_positions is a SNAPSHOT PER SYNC RUN (a new copy of the book every few minutes —
the table holds hundreds of thousands of historical rows). ALWAYS scope it:
  WHERE sync_run_id = (SELECT run_id FROM alpaca_sync_runs WHERE status='success'
                       ORDER BY completed_at DESC NULLS LAST LIMIT 1)
An unscoped aggregate over live_positions mixes weeks of snapshots and is meaningless.

Discipline:
- Investigate FIRST, then produce the final report JSON in a message WITHOUT tool calls.
- A recommendation whose thesis was backtest-CONFIRMED should say so in evidence and may
  carry higher confidence; an untested edit stays low/medium confidence.
- A backtest that REFUTES your thesis is a finding — report it (saves a bad config churn).
- Tool errors are data: adapt the call or move on; never fabricate a result.
- Every tool turn is budgeted: no connectivity pings (SELECT 1), no shape-test queries —
  run the real query; if it errors, the error text tells you how to fix it.
- Budgets are enforced; when told the budget is exhausted, finalize with what you have."""

# Appended when a tool exists but is disabled — the model can't miss what it was
# never told about, so disabled tools are named explicitly and routed to the
# "tooling_gap" structural-finding channel instead of disappearing silently.
WEB_SEARCH_UNAVAILABLE_NOTE = """

NOTE: web_search EXISTS but is UNAVAILABLE this run (no TAVILY_API_KEY configured) —
it is not in your tool list and cannot be called. If external/web evidence would have
materially improved this review, say so in a structural finding with category
"tooling_gap" (name the question it would have answered) rather than working around
it silently."""


def build_system_prompt() -> str:
    """SYSTEM_PROMPT + tool addendum + availability notes for disabled tools.
    Module-attribute read (not a cached import) so tests/env changes are honored."""
    system = SYSTEM_PROMPT + TOOLS_ADDENDUM
    if not _tools_mod.TAVILY_API_KEY:
        system += WEB_SEARCH_UNAVAILABLE_NOTE
    return system


def _transcript_entry(turn: int, name: str, args: dict, result: str, elapsed_ms: int) -> dict:
    args_s = json.dumps(args, default=str)
    return {
        "turn": turn,
        "tool": name,
        "arguments": args_s[:_TRANSCRIPT_ARGS_CAP],
        "result": (result or "")[:_TRANSCRIPT_RESULT_CAP],
        "result_chars": len(result or ""),
        "elapsed_ms": elapsed_ms,
    }


async def _gateway_chat(client: httpx.AsyncClient, payload: dict) -> dict:
    r = await client.post(f"{LLM_GATEWAY_URL}/v1/chat", json=payload)
    if r.status_code >= 400:
        # Include the BODY: the gateway puts the real upstream reason in detail
        # (e.g. "anthropic 400: …"); raise_for_status alone would reduce it to an
        # opaque status line in evaluator_reports.error_message.
        raise RuntimeError(f"llm-gateway {r.status_code}: {r.text[:500]}")
    return r.json()


async def generate_report_with_tools(packet: dict, engine) -> tuple[ReportResult, list[dict]]:
    """Tool-use review. Returns (ReportResult, tool_transcript). Raises only on a
    hard gateway failure — the caller falls back to the packet-only Phase-1 path."""
    system = build_system_prompt()
    user_prompt = build_user_prompt(packet)
    prompt_hash = hashlib.sha256((system + user_prompt).encode()).hexdigest()[:16]
    tools = tool_definitions()
    budget = BacktestBudget(MAX_BACKTESTS)

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    transcript: list[dict] = []
    tot_in = tot_out = tot_latency = 0
    provider = model = ""
    raw_final = ""

    async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT_SECS) as client:
        for turn in range(1, MAX_TOOL_TURNS + 1):
            final_turn = turn == MAX_TOOL_TURNS
            payload = {
                "system": system,
                "messages": messages,
                # Tools stay DECLARED even on the forced-final turn — the
                # conversation already contains tool_use blocks and the API
                # rejects such a request without a tools param. tool_choice=none
                # is the correct "no more tools, answer in text" mechanism.
                "tools": tools,
                "tool_choice": "none" if final_turn else "auto",
                "provider": EVALUATOR_PROVIDER,
                "model": EVALUATOR_MODEL,
                "max_tokens": EVALUATOR_MAX_TOKENS,
                "thinking": True,
                "response_schema": REPORT_SCHEMA,
            }
            data = await _gateway_chat(client, payload)
            provider = data.get("provider", provider)
            model = data.get("model", model)
            tot_in += data.get("input_tokens", 0)
            tot_out += data.get("output_tokens", 0)
            tot_latency += data.get("latency_ms", 0)
            content = data.get("content", "") or ""
            tool_calls = data.get("tool_calls") or []

            if data.get("stop_reason") == "tool_use" and tool_calls and not final_turn:
                # raw_content = the provider's verbatim blocks (incl. SIGNED
                # thinking blocks). Echoing them back is REQUIRED by Anthropic
                # when thinking + tools are combined — without it the next call
                # 400s ("expected thinking block") and the whole review dies.
                messages.append({"role": "assistant", "content": content,
                                 "tool_calls": tool_calls,
                                 "raw_content": data.get("raw_content")})
                for tc in tool_calls:
                    name = tc.get("name", "")
                    args = tc.get("arguments") or {}
                    t0 = time.monotonic()
                    result = await execute_tool(name, args, engine=engine, budget=budget)
                    elapsed = round((time.monotonic() - t0) * 1000)
                    transcript.append(_transcript_entry(turn, name, args, result, elapsed))
                    messages.append({"role": "tool", "content": result,
                                     "tool_call_id": tc.get("id"), "name": name})
                # Nearing the cap: warn the model so it lands the report in time.
                if turn == MAX_TOOL_TURNS - 2:
                    messages.append({
                        "role": "user",
                        "content": ("Tool budget nearly exhausted — finish investigating "
                                    "and produce the final report JSON now."),
                    })
                continue

            # No tool calls → this should be the report.
            raw_final = content
            parsed = _parse_report_json(raw_final)
            if parsed is not None:
                return _to_result(parsed, provider, model, prompt_hash,
                                  tot_in, tot_out, tot_latency, transcript), transcript
            # One nudge: model produced prose instead of the JSON contract.
            if not final_turn:
                messages.append({"role": "assistant", "content": content,
                                 "raw_content": data.get("raw_content")})
                messages.append({"role": "user",
                                 "content": "Respond ONLY with the report JSON object "
                                            "matching the response schema."})
                continue
            break

    # Loop exhausted without valid JSON — degrade exactly like Phase 1's fallback.
    return ReportResult(
        narrative_markdown=raw_final or "(empty LLM response)",
        overall_assessment="insufficient_data",
        recommendations=[],
        data_gaps=["LLM output was not valid report JSON after the tool loop — raw text shown"],
        parse_fallback=True,
        provider=provider, model=model, prompt_hash=prompt_hash,
        input_tokens=tot_in, output_tokens=tot_out, latency_ms=tot_latency,
    ), transcript


def _to_result(parsed: dict, provider: str, model: str, prompt_hash: str,
               tot_in: int, tot_out: int, tot_latency: int,
               transcript: list[dict]) -> ReportResult:
    return ReportResult(
        narrative_markdown=str(parsed.get("narrative_markdown", "")),
        overall_assessment=str(parsed.get("overall_assessment", "insufficient_data")),
        recommendations=validate_recommendations(list(parsed.get("recommendations") or [])),
        structural_findings=[f for f in (parsed.get("structural_findings") or [])
                             if isinstance(f, dict)],
        data_gaps=[str(g) for g in (parsed.get("data_gaps") or [])],
        provider=provider, model=model, prompt_hash=prompt_hash,
        input_tokens=tot_in, output_tokens=tot_out, latency_ms=tot_latency,
    )
