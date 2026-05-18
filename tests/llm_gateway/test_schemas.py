"""
Tests for llm-gateway Pydantic schemas.
"""
from app.schemas import (
    ChatRequest, ChatResponse, Message, ToolCall, ToolDef, ProviderInfo
)


def test_chat_request_defaults():
    req = ChatRequest(messages=[Message(role="user", content="hello")])
    assert req.provider is None
    assert req.tools == []
    assert req.temperature == 0.1
    assert req.max_tokens == 1024
    assert req.system is None
    assert req.response_schema is None


def test_message_tool_call_round_trip():
    tc = ToolCall(id="call_abc", name="web_search", arguments={"query": "AAPL news"})
    msg = Message(role="assistant", content="Searching...", tool_calls=[tc])
    dumped = msg.model_dump()
    restored = Message(**dumped)
    assert restored.tool_calls[0].id == "call_abc"
    assert restored.tool_calls[0].name == "web_search"
    assert restored.tool_calls[0].arguments == {"query": "AAPL news"}


def test_chat_response_cached_tokens_default_zero():
    resp = ChatResponse(
        content="hello",
        stop_reason="end_turn",
        provider="ollama",
        model="qwen2.5:7b",
        input_tokens=10,
        output_tokens=5,
        latency_ms=100,
    )
    assert resp.cached_tokens == 0
    assert resp.tool_calls == []


def test_tool_def_parameters_is_dict():
    td = ToolDef(
        name="web_search",
        description="Search the web",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    assert isinstance(td.parameters, dict)
    assert td.parameters["type"] == "object"


def test_provider_info_models_default_empty():
    pi = ProviderInfo(name="ollama", available=True, default_model="qwen2.5:7b")
    assert pi.models == []


def test_chat_request_with_tools():
    tool = ToolDef(
        name="web_search",
        description="Search",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    req = ChatRequest(
        system="You are a helper",
        messages=[Message(role="user", content="find news")],
        tools=[tool],
        temperature=0.5,
        max_tokens=512,
    )
    assert len(req.tools) == 1
    assert req.tools[0].name == "web_search"
    assert req.temperature == 0.5
