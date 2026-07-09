"""Thinking + tool-use loop support in the Anthropic provider (the evaluator
Phase-2 incident): signed thinking blocks must round-trip verbatim on the turn
after a tool call, tools stay declared with tool_choice=none on the forced-final
turn, upstream API rejections surface with their real status+message, and SDK
parameter drift degrades gracefully instead of failing every call."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock the anthropic package before provider import (same pattern as
# test_providers.py; setdefault shares the instance when both files load).
_anth = sys.modules.get("anthropic")
if _anth is None or isinstance(_anth, MagicMock) is False and not hasattr(_anth, "AsyncAnthropic"):
    _anth = MagicMock()
    sys.modules["anthropic"] = _anth
if not isinstance(getattr(_anth, "RateLimitError", None), type):
    _anth.RateLimitError = type("RateLimitError", (Exception,), {})
if not isinstance(getattr(_anth, "InternalServerError", None), type):
    _anth.InternalServerError = type("InternalServerError", (Exception,), {})
if not isinstance(getattr(_anth, "APIStatusError", None), type):
    _anth.APIStatusError = type("APIStatusError", (Exception,), {})
_anth.AsyncAnthropic = MagicMock

from app.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from app.schemas import ChatRequest, Message, ToolCall, ToolDef  # noqa: E402


class _Block:
    """Content block that supports model_dump (like real SDK pydantic blocks)."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _usage():
    return SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)


def _provider(create_mock) -> AnthropicProvider:
    p = AnthropicProvider(api_key="k", model="claude-fable-5")
    inst = AsyncMock()
    inst.messages = AsyncMock()
    inst.messages.create = create_mock
    p._client = inst
    return p


_TOOL = ToolDef(name="sql_query", description="d", parameters={"type": "object"})


@pytest.mark.asyncio
async def test_raw_content_round_trip_preserves_thinking_blocks():
    """Response carries verbatim blocks; a continuation echoing them via
    Message.raw_content sends EXACTLY those blocks as the assistant content —
    the API requirement when thinking + tools are combined."""
    thinking = {"type": "thinking", "thinking": "let me check…", "signature": "sig123"}
    tool_use = {"type": "tool_use", "id": "t1", "name": "sql_query", "input": {"query": "SELECT 1"}}
    resp1 = SimpleNamespace(
        content=[_Block(**thinking), _Block(**tool_use)],
        stop_reason="tool_use", model="claude-fable-5", usage=_usage())
    create = AsyncMock(return_value=resp1)
    p = _provider(create)

    out = await p.chat(ChatRequest(
        messages=[Message(role="user", content="go")],
        tools=[_TOOL], thinking=True))
    assert out.raw_content == [thinking, tool_use]     # verbatim capture

    # Continuation: assistant turn echoed via raw_content + tool result.
    resp2 = SimpleNamespace(content=[_Block(type="text", text="done")],
                            stop_reason="end_turn", model="claude-fable-5", usage=_usage())
    create.return_value = resp2
    await p.chat(ChatRequest(
        messages=[
            Message(role="user", content="go"),
            Message(role="assistant", content="",
                    tool_calls=[ToolCall(id="t1", name="sql_query",
                                         arguments={"query": "SELECT 1"})],
                    raw_content=out.raw_content),
            Message(role="tool", content="rows", tool_call_id="t1", name="sql_query"),
        ],
        tools=[_TOOL], thinking=True))
    sent = create.call_args.kwargs["messages"]
    assert sent[1] == {"role": "assistant", "content": [thinking, tool_use]}, \
        "assistant turn must be the VERBATIM blocks (incl. signed thinking), not rebuilt"


@pytest.mark.asyncio
async def test_tool_choice_none_keeps_tools_declared():
    resp = SimpleNamespace(content=[_Block(type="text", text="{}")],
                           stop_reason="end_turn", model="m", usage=_usage())
    create = AsyncMock(return_value=resp)
    p = _provider(create)
    await p.chat(ChatRequest(messages=[Message(role="user", content="x")],
                             tools=[_TOOL], tool_choice="none"))
    kw = create.call_args.kwargs
    assert kw["tools"], "tools must stay declared"
    assert kw["tool_choice"] == {"type": "none"}


@pytest.mark.asyncio
async def test_api_status_error_surfaces_status_and_message():
    exc = _anth.APIStatusError("bad request")
    exc.status_code = 400
    exc.message = "messages.1.content: expected thinking block"
    p = _provider(AsyncMock(side_effect=exc))
    with pytest.raises(RuntimeError) as ei:
        await p.chat(ChatRequest(messages=[Message(role="user", content="x")]))
    assert "anthropic 400" in str(ei.value)
    assert "expected thinking block" in str(ei.value)


@pytest.mark.asyncio
async def test_sdk_drift_guard_retries_without_optional_kwargs():
    """A client-side TypeError on 'thinking' (SDK drift after a rebuild) retries
    once without thinking/tool_choice instead of failing every call."""
    resp = SimpleNamespace(content=[_Block(type="text", text="ok")],
                           stop_reason="end_turn", model="m", usage=_usage())
    create = AsyncMock(side_effect=[
        TypeError("create() got an unexpected keyword argument 'thinking'"), resp])
    p = _provider(create)
    out = await p.chat(ChatRequest(messages=[Message(role="user", content="x")],
                                   thinking=True))
    assert out.content == "ok"
    assert "thinking" in create.call_args_list[0].kwargs
    assert "thinking" not in create.call_args_list[1].kwargs


@pytest.mark.asyncio
async def test_unrelated_type_error_not_swallowed_by_drift_guard():
    p = _provider(AsyncMock(side_effect=TypeError("something else entirely")))
    with pytest.raises(TypeError):
        await p.chat(ChatRequest(messages=[Message(role="user", content="x")],
                                 thinking=True))
