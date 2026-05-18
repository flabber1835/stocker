"""
Ollama provider for the LLM gateway.
"""
from __future__ import annotations

import time

import ollama

from app.providers.base import BaseProvider
from app.schemas import ChatRequest, ChatResponse, ToolCall


class OllamaProvider(BaseProvider):
    def __init__(self, host: str, model: str, timeout: int = 600) -> None:
        self._host = host
        self._model = model
        self._timeout = timeout
        self._client = ollama.AsyncClient(host=host, timeout=timeout)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        try:
            await self._client.list()
            return True
        except Exception:
            return False

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._model
        t0 = time.monotonic()

        # Build messages list for Ollama
        ollama_messages = []

        # System prompt goes as first message
        if request.system:
            ollama_messages.append({"role": "system", "content": request.system})

        for msg in request.messages:
            if msg.role == "tool":
                ollama_messages.append({"role": "tool", "content": msg.content})
            elif msg.role == "assistant" and msg.tool_calls:
                ollama_messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            }
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                ollama_messages.append({"role": msg.role, "content": msg.content})

        # Convert ToolDef to Ollama tool format
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ] if request.tools else None

        kwargs: dict = {
            "model": model,
            "messages": ollama_messages,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if tools:
            kwargs["tools"] = tools
        if request.response_schema is not None:
            kwargs["format"] = request.response_schema

        resp = await self._client.chat(**kwargs)

        latency_ms = round((time.monotonic() - t0) * 1000)

        content = resp.message.content or ""
        tool_calls: list[ToolCall] = []

        if resp.message.tool_calls:
            for i, tc in enumerate(resp.message.tool_calls):
                args = tc.function.arguments
                if not isinstance(args, dict):
                    args = {}
                tool_calls.append(ToolCall(
                    id=f"call_{i}",
                    name=tc.function.name,
                    arguments=args,
                ))

        stop_reason = "tool_use" if tool_calls else "end_turn"

        input_tokens = getattr(resp, "prompt_eval_count", None) or 0
        output_tokens = getattr(resp, "eval_count", None) or 0

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            provider="ollama",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=0,
            latency_ms=latency_ms,
        )
