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


class ChatRequest(BaseModel):
    system: str | None = None
    messages: list[Message]
    tools: list[ToolDef] = []
    model: str | None = None          # overrides default for the provider
    provider: str | None = None       # "anthropic" | "ollama" | None (use default)
    temperature: float = 0.1
    max_tokens: int = 1024
    response_schema: dict | None = None  # JSON schema for structured output


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


class ProviderInfo(BaseModel):
    name: str
    available: bool
    default_model: str
    models: list[str] = []
