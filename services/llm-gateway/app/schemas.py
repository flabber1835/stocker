"""
Unified request/response types that both Anthropic and Ollama map to.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ToolDef(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = []   # assistant messages only
    tool_call_id: str | None = None   # tool result messages only
    name: str | None = None           # tool name for tool result messages
    # Provider-opaque verbatim content blocks for an assistant message, echoed
    # back from ChatResponse.raw_content when CONTINUING a conversation. Required
    # for Anthropic tool-use with thinking enabled: the API demands the signed
    # thinking blocks be resent on the turn after a tool call, and the unified
    # text+tool_calls shape cannot carry them. When present on an assistant
    # message, providers that understand it use it verbatim; others ignore it.
    raw_content: list | None = None


class ChatRequest(BaseModel):
    system: str | None = None
    messages: list[Message]
    tools: list[ToolDef] = []
    # "auto" (default) | "none" (tools stay declared — REQUIRED when the
    # conversation already contains tool_use blocks — but the model must answer
    # in text). Ignored by providers without the concept.
    tool_choice: Literal["auto", "none"] = "auto"
    model: str | None = None          # overrides default for the provider
    provider: str | None = None       # "anthropic" | "ollama" | None (use default)
    temperature: float = 0.1
    max_tokens: int = 1024
    response_schema: dict | None = None  # JSON schema for structured output
    thinking: bool = False            # adaptive thinking (Anthropic 4.6+ models; ignored by Ollama)


class ChatResponse(BaseModel):
    content: str
    tool_calls: list[ToolCall] = []
    stop_reason: str   # "end_turn" | "tool_use" | "max_tokens" | "stop"
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    latency_ms: int
    # Verbatim provider content blocks (thinking/text/tool_use) for this
    # assistant turn — echo into Message.raw_content when continuing. None when
    # the provider has nothing beyond content/tool_calls (e.g. Ollama).
    raw_content: list | None = None


class ProviderInfo(BaseModel):
    name: str
    available: bool
    default_model: str
    models: list[str] = []
