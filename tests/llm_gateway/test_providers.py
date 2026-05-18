"""
Tests for llm-gateway provider translation logic.

Tests mock the underlying Anthropic and Ollama clients so no API calls are made.
"""
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock the 'anthropic' package before any imports touch it, since it may not be
# installed in the test environment (it lives inside the Docker container only).
_mock_anthropic = MagicMock()
_mock_anthropic.AsyncAnthropic = MagicMock
sys.modules.setdefault("anthropic", _mock_anthropic)

from app.schemas import ChatRequest, ChatResponse, Message, ToolCall, ToolDef


# ── AnthropicProvider tests ──────────────────────────────────────────────────

def _make_anthropic_text_response(text: str, model: str = "claude-haiku-4-5-20251001"):
    """Build a mock Anthropic Messages response with a text block."""
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(
        input_tokens=20,
        output_tokens=10,
        cache_read_input_tokens=5,
    )
    return SimpleNamespace(
        content=[block],
        stop_reason="end_turn",
        model=model,
        usage=usage,
    )


def _make_anthropic_tool_response(tool_id: str, tool_name: str, tool_input: dict, model: str = "claude-haiku-4-5-20251001"):
    """Build a mock Anthropic response with a tool_use block."""
    block = SimpleNamespace(type="tool_use", id=tool_id, name=tool_name, input=tool_input)
    usage = SimpleNamespace(
        input_tokens=30,
        output_tokens=15,
        cache_read_input_tokens=0,
    )
    return SimpleNamespace(
        content=[block],
        stop_reason="tool_use",
        model=model,
        usage=usage,
    )


@pytest.mark.asyncio
async def test_anthropic_simple_response():
    from app.providers.anthropic_provider import AnthropicProvider

    mock_response = _make_anthropic_text_response("This is a test response")

    with patch("anthropic.AsyncAnthropic") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.messages = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_instance

        provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")
        provider._client = mock_instance

        request = ChatRequest(
            messages=[Message(role="user", content="Hello")],
            system="You are helpful",
        )
        resp = await provider.chat(request)

    assert resp.content == "This is a test response"
    assert resp.stop_reason == "end_turn"
    assert resp.provider == "anthropic"
    assert resp.model == "claude-haiku-4-5-20251001"
    assert resp.input_tokens == 20
    assert resp.output_tokens == 10
    assert resp.cached_tokens == 5
    assert resp.tool_calls == []


@pytest.mark.asyncio
async def test_anthropic_tool_use_response():
    from app.providers.anthropic_provider import AnthropicProvider

    mock_response = _make_anthropic_tool_response(
        tool_id="toolu_abc123",
        tool_name="web_search",
        tool_input={"query": "AAPL earnings 2026"},
    )

    with patch("anthropic.AsyncAnthropic") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.messages = AsyncMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_instance

        provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")
        provider._client = mock_instance

        request = ChatRequest(
            messages=[Message(role="user", content="Check AAPL")],
            tools=[ToolDef(
                name="web_search",
                description="Search the web",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            )],
        )
        resp = await provider.chat(request)

    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "toolu_abc123"
    assert tc.name == "web_search"
    assert tc.arguments == {"query": "AAPL earnings 2026"}


@pytest.mark.asyncio
async def test_anthropic_tool_result_message():
    """role='tool' messages should be converted to Anthropic user messages with tool_result blocks."""
    from app.providers.anthropic_provider import AnthropicProvider

    mock_response = _make_anthropic_text_response("Done")
    captured_kwargs = {}

    async def capture_create(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    with patch("anthropic.AsyncAnthropic") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.messages = AsyncMock()
        mock_instance.messages.create = capture_create
        MockClient.return_value = mock_instance

        provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")
        provider._client = mock_instance

        request = ChatRequest(
            messages=[
                Message(role="user", content="Check AAPL"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "AAPL"})],
                ),
                Message(
                    role="tool",
                    content="AAPL earnings beat Q1 2026",
                    tool_call_id="call_1",
                    name="web_search",
                ),
            ],
        )
        await provider.chat(request)

    anthropic_msgs = captured_kwargs["messages"]
    # The tool result message should be a user message with tool_result content block
    tool_result_msg = anthropic_msgs[-1]
    assert tool_result_msg["role"] == "user"
    assert isinstance(tool_result_msg["content"], list)
    block = tool_result_msg["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_1"
    assert block["content"] == "AAPL earnings beat Q1 2026"


@pytest.mark.asyncio
async def test_anthropic_system_prompt_cached():
    """System prompt should be sent as cache_control ephemeral block."""
    from app.providers.anthropic_provider import AnthropicProvider

    mock_response = _make_anthropic_text_response("ok")
    captured_kwargs = {}

    async def capture_create(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    with patch("anthropic.AsyncAnthropic") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.messages = AsyncMock()
        mock_instance.messages.create = capture_create
        MockClient.return_value = mock_instance

        provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")
        provider._client = mock_instance

        request = ChatRequest(
            system="You are a helpful assistant",
            messages=[Message(role="user", content="Hello")],
        )
        await provider.chat(request)

    assert "system" in captured_kwargs
    system_blocks = captured_kwargs["system"]
    assert isinstance(system_blocks, list)
    assert len(system_blocks) == 1
    block = system_blocks[0]
    assert block["type"] == "text"
    assert block["text"] == "You are a helpful assistant"
    assert block["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_anthropic_response_schema_appended_to_system():
    """response_schema should be appended to the system prompt text."""
    from app.providers.anthropic_provider import AnthropicProvider

    schema = {"type": "object", "properties": {"exclude": {"type": "boolean"}}, "required": ["exclude"]}
    mock_response = _make_anthropic_text_response('{"exclude": false}')
    captured_kwargs = {}

    async def capture_create(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    with patch("anthropic.AsyncAnthropic") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.messages = AsyncMock()
        mock_instance.messages.create = capture_create
        MockClient.return_value = mock_instance

        provider = AnthropicProvider(api_key="test-key", model="claude-haiku-4-5-20251001")
        provider._client = mock_instance

        request = ChatRequest(
            system="You are an analyst",
            messages=[Message(role="user", content="Assess AAPL")],
            response_schema=schema,
        )
        await provider.chat(request)

    system_blocks = captured_kwargs["system"]
    system_text = system_blocks[0]["text"]
    assert "Respond ONLY with valid JSON matching this schema:" in system_text
    assert json.dumps(schema) in system_text


# ── OllamaProvider tests ──────────────────────────────────────────────────────

def _make_ollama_response(content: str, tool_calls=None, prompt_eval_count=25, eval_count=12):
    """Build a mock Ollama chat response."""
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(
        message=message,
        prompt_eval_count=prompt_eval_count,
        eval_count=eval_count,
    )


def _make_ollama_tool_call(name: str, arguments: dict):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(function=fn)


@pytest.mark.asyncio
async def test_ollama_simple_response():
    from app.providers.ollama_provider import OllamaProvider

    mock_resp = _make_ollama_response("AAPL looks fine", tool_calls=None, prompt_eval_count=25, eval_count=12)

    with patch("ollama.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.chat = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_instance

        provider = OllamaProvider(host="http://localhost:11434", model="qwen2.5:7b")
        provider._client = mock_instance

        request = ChatRequest(
            messages=[Message(role="user", content="Assess AAPL")],
        )
        resp = await provider.chat(request)

    assert resp.content == "AAPL looks fine"
    assert resp.stop_reason == "end_turn"
    assert resp.provider == "ollama"
    assert resp.input_tokens == 25
    assert resp.output_tokens == 12
    assert resp.cached_tokens == 0
    assert resp.tool_calls == []


@pytest.mark.asyncio
async def test_ollama_tool_calls_response():
    """Ollama tool calls should map to unified ToolCall with synthetic IDs."""
    from app.providers.ollama_provider import OllamaProvider

    tc0 = _make_ollama_tool_call("web_search", {"query": "AAPL earnings"})
    tc1 = _make_ollama_tool_call("web_search", {"query": "AAPL SEC filing"})
    mock_resp = _make_ollama_response("", tool_calls=[tc0, tc1])

    with patch("ollama.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.chat = AsyncMock(return_value=mock_resp)
        MockClient.return_value = mock_instance

        provider = OllamaProvider(host="http://localhost:11434", model="qwen2.5:7b")
        provider._client = mock_instance

        request = ChatRequest(
            messages=[Message(role="user", content="Check AAPL")],
            tools=[ToolDef(name="web_search", description="Search", parameters={})],
        )
        resp = await provider.chat(request)

    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].id == "call_0"
    assert resp.tool_calls[0].name == "web_search"
    assert resp.tool_calls[0].arguments == {"query": "AAPL earnings"}
    assert resp.tool_calls[1].id == "call_1"


@pytest.mark.asyncio
async def test_ollama_system_as_first_message():
    """System prompt should be injected as first message with role='system'."""
    from app.providers.ollama_provider import OllamaProvider

    mock_resp = _make_ollama_response("ok", tool_calls=None)
    captured_kwargs = {}

    async def capture_chat(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_resp

    with patch("ollama.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.chat = capture_chat
        MockClient.return_value = mock_instance

        provider = OllamaProvider(host="http://localhost:11434", model="qwen2.5:7b")
        provider._client = mock_instance

        request = ChatRequest(
            system="You are a financial analyst",
            messages=[Message(role="user", content="Assess stock")],
        )
        await provider.chat(request)

    msgs = captured_kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "You are a financial analyst"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "Assess stock"


@pytest.mark.asyncio
async def test_ollama_tool_result_message():
    """role='tool' messages should become {'role': 'tool', 'content': ...} in Ollama messages."""
    from app.providers.ollama_provider import OllamaProvider

    mock_resp = _make_ollama_response("ok", tool_calls=None)
    captured_kwargs = {}

    async def capture_chat(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_resp

    with patch("ollama.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.chat = capture_chat
        MockClient.return_value = mock_instance

        provider = OllamaProvider(host="http://localhost:11434", model="qwen2.5:7b")
        provider._client = mock_instance

        request = ChatRequest(
            messages=[
                Message(role="user", content="Check MSFT"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="call_0", name="web_search", arguments={"query": "MSFT"})],
                ),
                Message(
                    role="tool",
                    content="MSFT earnings beat estimates",
                    tool_call_id="call_0",
                    name="web_search",
                ),
            ],
        )
        await provider.chat(request)

    msgs = captured_kwargs["messages"]
    # Last message should be the tool result
    tool_msg = msgs[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == "MSFT earnings beat estimates"
