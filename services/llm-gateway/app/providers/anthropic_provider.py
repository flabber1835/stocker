"""
Anthropic Claude provider for the LLM gateway.
"""
from __future__ import annotations

import json
import os
import time

import anthropic

from app.providers.base import BaseProvider
from app.schemas import ChatRequest, ChatResponse, ToolCall


class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._model
        t0 = time.monotonic()

        # Build system prompt with optional schema appended
        system_text = request.system or ""
        if request.response_schema is not None:
            schema_suffix = f"\n\nRespond ONLY with valid JSON matching this schema: {json.dumps(request.response_schema)}"
            system_text = system_text + schema_suffix

        # Wrap system with prompt caching
        system_blocks = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ] if system_text else []

        # Convert unified messages to Anthropic format
        anthropic_messages = []
        for msg in request.messages:
            if msg.role == "tool":
                # Tool result → user message with tool_result content block
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    ],
                })
            elif msg.role == "assistant" and msg.tool_calls:
                # Assistant message with tool calls → mixed content blocks
                content_blocks = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})

        # Convert ToolDef list to Anthropic tools format
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in request.tools
        ]

        kwargs: dict = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": anthropic_messages,
            "temperature": request.temperature,
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        latency_ms = round((time.monotonic() - t0) * 1000)

        # Parse response content
        content_text = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        # Map stop reason
        stop_reason_map = {
            "end_turn": "end_turn",
            "tool_use": "tool_use",
            "max_tokens": "max_tokens",
        }
        stop_reason = stop_reason_map.get(response.stop_reason or "", "end_turn")

        # Token usage
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cached_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0

        return ChatResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            provider="anthropic",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            latency_ms=latency_ms,
        )
