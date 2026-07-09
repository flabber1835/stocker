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
- sql_query: read-only SELECTs on the live DB — drill into any packet anomaly (a factor's
  IC, a specific trade, what a dropped name did next) instead of speculating.
- read_file: read the actual source/docs/strategies — ground structural findings in the
  REAL implementation (e.g. read services/pipeline/app/factors.py before claiming a
  factor computation is flawed).
- web_search: external context (macro, factor literature). Sparing use; packet/SQL
  evidence outranks it.

Discipline:
- Investigate FIRST, then produce the final report JSON in a message WITHOUT tool calls.
- A recommendation whose thesis was backtest-CONFIRMED should say so in evidence and may
  carry higher confidence; an untested edit stays low/medium confidence.
- A backtest that REFUTES your thesis is a finding — report it (saves a bad config churn).
- Tool errors are data: adapt the call or move on; never fabricate a result.
- Budgets are enforced; when told the budget is exhausted, finalize with what you have."""


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
    r.raise_for_status()
    return r.json()


async def generate_report_with_tools(packet: dict, engine) -> tuple[ReportResult, list[dict]]:
    """Tool-use review. Returns (ReportResult, tool_transcript). Raises only on a
    hard gateway failure — the caller falls back to the packet-only Phase-1 path."""
    system = SYSTEM_PROMPT + TOOLS_ADDENDUM
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
                "tools": [] if final_turn else tools,
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
                messages.append({"role": "assistant", "content": content,
                                 "tool_calls": tool_calls})
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
                messages.append({"role": "assistant", "content": content})
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
