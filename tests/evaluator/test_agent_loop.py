"""Phase-2 agent loop: tool_use turns execute tools and feed results back; the
final end_turn parses the same report-JSON contract as Phase 1; budgets force a
tools-stripped final call; prose gets one JSON nudge. Gateway + tools mocked."""
import asyncio
import json

import pytest

import app.agent as agent


_REPORT = {
    "narrative_markdown": "## Verdict\nok",
    "overall_assessment": "healthy",
    "recommendations": [{
        "observation": "o", "evidence": ["backtest run xyz sharpe 1.1"],
        "config_field": "portfolio_builder.max_positions", "current_value": "30",
        "suggested_value": "25", "direction": "decrease",
        "expected_effect": "e", "confidence": "medium",
    }],
    "structural_findings": [],
    "data_gaps": [],
}


def _resp(content="", tool_calls=None, stop="end_turn", raw=None):
    return {"content": content, "tool_calls": tool_calls or [], "stop_reason": stop,
            "provider": "anthropic", "model": "m", "input_tokens": 10,
            "output_tokens": 5, "cached_tokens": 0, "latency_ms": 3,
            "raw_content": raw}


def _run(scripted_responses, executed):
    """Run the loop against a scripted gateway + recording tool executor."""
    responses = list(scripted_responses)

    async def fake_gateway(client, payload):
        # tools stripped on the forced-final turn is asserted by the cap test
        fake_gateway.payloads.append(payload)
        return responses.pop(0)
    fake_gateway.payloads = []

    async def fake_execute(name, args, *, engine, budget):
        executed.append((name, args))
        return json.dumps({"ok": True, "tool": name})

    orig_gw, orig_ex = agent._gateway_chat, agent.execute_tool
    agent._gateway_chat, agent.execute_tool = fake_gateway, fake_execute
    try:
        result, transcript = asyncio.run(
            agent.generate_report_with_tools({"packet": "x"}, engine=None))
    finally:
        agent._gateway_chat, agent.execute_tool = orig_gw, orig_ex
    return result, transcript, fake_gateway.payloads


def test_tool_turn_then_report():
    executed = []
    raw = [{"type": "thinking", "thinking": "…", "signature": "sig"},
           {"type": "tool_use", "id": "t1", "name": "sql_query",
            "input": {"query": "SELECT 1"}}]
    scripted = [
        _resp(content="checking", stop="tool_use", raw=raw, tool_calls=[
            {"id": "t1", "name": "sql_query", "arguments": {"query": "SELECT 1"}}]),
        _resp(content=json.dumps(_REPORT)),
    ]
    result, transcript, payloads = _run(scripted, executed)
    assert executed == [("sql_query", {"query": "SELECT 1"})]
    assert result.overall_assessment == "healthy"
    assert not result.parse_fallback
    assert result.input_tokens == 20 and result.output_tokens == 10  # summed
    assert len(transcript) == 1 and transcript[0]["tool"] == "sql_query"
    # second gateway call carries assistant tool_calls + tool result message,
    # AND echoes the provider's verbatim blocks (signed thinking) back —
    # required by Anthropic when thinking + tools are combined.
    msgs = payloads[1]["messages"]
    assert msgs[1]["role"] == "assistant" and msgs[1]["tool_calls"]
    assert msgs[1]["raw_content"] == raw
    assert msgs[2]["role"] == "tool" and msgs[2]["tool_call_id"] == "t1"


def test_prose_gets_one_json_nudge():
    executed = []
    scripted = [
        _resp(content="here is my thinking, no json"),
        _resp(content=json.dumps(_REPORT)),
    ]
    result, transcript, payloads = _run(scripted, executed)
    assert result.overall_assessment == "healthy" and not result.parse_fallback
    assert "ONLY with the report JSON" in payloads[1]["messages"][-1]["content"]


def test_turn_cap_strips_tools_and_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(agent, "MAX_TOOL_TURNS", 3)
    executed = []
    tc = [{"id": "t1", "name": "read_file", "arguments": {"path": "docs/"}}]
    scripted = [
        _resp(stop="tool_use", tool_calls=tc),
        _resp(stop="tool_use", tool_calls=tc),
        _resp(content="still prose, never json"),   # final turn, tools stripped
    ]
    result, transcript, payloads = _run(scripted, executed)
    # Forced-final call: tools stay DECLARED (the conversation contains tool_use
    # blocks — the API rejects a toolless request then); tool_choice=none is the
    # correct "answer in text now" mechanism.
    assert payloads[-1]["tools"], "tools must remain declared on the final turn"
    assert payloads[-1]["tool_choice"] == "none"
    assert all(p["tool_choice"] == "auto" for p in payloads[:-1])
    assert result.parse_fallback                     # degraded like Phase 1
    assert "still prose" in result.narrative_markdown
    assert len(transcript) == 2


def test_transcript_truncates_big_results():
    executed = []

    async def fake_gateway(client, payload):
        if not fake_gateway.sent:
            fake_gateway.sent = True
            return _resp(stop="tool_use", tool_calls=[
                {"id": "t1", "name": "sql_query", "arguments": {"query": "SELECT 1"}}])
        return _resp(content=json.dumps(_REPORT))
    fake_gateway.sent = False

    async def fake_execute(name, args, *, engine, budget):
        return "x" * 50_000

    orig_gw, orig_ex = agent._gateway_chat, agent.execute_tool
    agent._gateway_chat, agent.execute_tool = fake_gateway, fake_execute
    try:
        _, transcript = asyncio.run(
            agent.generate_report_with_tools({"p": 1}, engine=None))
    finally:
        agent._gateway_chat, agent.execute_tool = orig_gw, orig_ex
    assert len(transcript[0]["result"]) == agent._TRANSCRIPT_RESULT_CAP
    assert transcript[0]["result_chars"] == 50_000
