"""
Anthropic Claude provider for the LLM gateway.
"""
from __future__ import annotations

import json
import os
import time

import anthropic
import httpx

from app.providers.base import BaseProvider
from app.schemas import ChatRequest, ChatResponse, ToolCall


# Models that REJECT sampling parameters (temperature/top_p/top_k return HTTP 400):
# the Opus 4.7+ / Sonnet 5 / Fable-Mythos families removed them. For these, the
# request's temperature is silently omitted (prompting is the steering mechanism).
_NO_SAMPLING_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-fable",
    "claude-mythos",
)


def _accepts_sampling_params(model: str) -> bool:
    return not model.startswith(_NO_SAMPLING_PREFIXES)


class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str) -> None:
        base_url = os.getenv("ANTHROPIC_BASE_URL") or None
        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        # Readiness check: verify the API key is configured without making a
        # billed API call. Actual auth errors surface on the first chat() call.
        return bool(self._api_key)

    async def _create_with_drift_guard(self, kwargs: dict):
        """messages.create with a one-shot degrade for SDK parameter drift.

        The `anthropic` pin is a floor (>=0.25.0), so an image rebuild can pull an
        SDK whose client-side validation no longer accepts an optional kwarg we
        send (observed risk: `thinking` / `tool_choice` shapes). A client-side
        TypeError on such a kwarg would otherwise fail EVERY call — including the
        packet-only fallback — turning a param rename into a total outage. Retry
        once without the optional kwargs, loudly logged; the review survives with
        thinking disabled rather than dying."""
        try:
            return await self._client.messages.create(**kwargs)
        except TypeError as exc:
            msg = str(exc)
            degraded = {k: v for k, v in kwargs.items()
                        if k not in ("thinking", "tool_choice")}
            if degraded.keys() == kwargs.keys() or not any(
                    w in msg for w in ("thinking", "tool_choice", "unexpected keyword")):
                raise
            print(f"[llm-gateway] WARNING: SDK rejected optional kwargs ({msg}) — "
                  f"retrying once without thinking/tool_choice (SDK drift guard)",
                  flush=True)
            return await self._client.messages.create(**degraded)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._model
        t0 = time.monotonic()

        # Build system prompt with optional schema appended.
        # NOTE: Unlike Ollama's format= param (grammar-constrained), this is
        # advisory — Anthropic may still produce non-JSON. The caller must
        # handle json.JSONDecodeError with a safe fallback.
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
            elif msg.role == "assistant" and msg.raw_content:
                # Verbatim echo of a prior assistant turn (ChatResponse.raw_content).
                # With extended thinking + tools the API REQUIRES the signed
                # thinking blocks be resent after a tool call — rebuilding the turn
                # from text+tool_calls drops them and the request 400s.
                anthropic_messages.append({"role": "assistant",
                                           "content": msg.raw_content})
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
        }
        if _accepts_sampling_params(model):
            kwargs["temperature"] = request.temperature
        if getattr(request, "thinking", False):
            # Adaptive thinking (4.6+ models). budget_tokens is deprecated/removed —
            # adaptive is the only supported on-mode on Opus 4.7+/Sonnet 5.
            kwargs["thinking"] = {"type": "adaptive"}
        if system_blocks:
            kwargs["system"] = system_blocks
        if tools:
            kwargs["tools"] = tools
            if request.tool_choice == "none":
                # Tools stay DECLARED (required when the conversation already
                # contains tool_use blocks) but the model must answer in text.
                kwargs["tool_choice"] = {"type": "none"}

        try:
            response = await self._create_with_drift_guard(kwargs)
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            # 429 rate-limit and 529 overloaded are transient — re-raise as
            # httpx.ConnectError so the gateway retry loop handles them.
            raise httpx.ConnectError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            # Non-transient API rejection (400 invalid request, 401/403 auth, …).
            # Surface the REAL upstream status + message instead of letting a bare
            # exception become an opaque "500 Internal Server Error" downstream —
            # the caller records this text in its error_message (diagnosable).
            raise RuntimeError(
                f"anthropic {exc.status_code}: {getattr(exc, 'message', str(exc))[:500]}"
            ) from exc

        latency_ms = round((time.monotonic() - t0) * 1000)

        # Parse response content. raw_content keeps the VERBATIM blocks (incl.
        # signed thinking blocks) so a tool-loop caller can echo them back via
        # Message.raw_content on the next turn — required by the API when
        # thinking + tools are combined.
        content_text = ""
        tool_calls: list[ToolCall] = []
        raw_content: list = []
        for block in response.content:
            try:
                raw_content.append(block.model_dump(exclude_none=True))
            except Exception:  # noqa: BLE001 — raw echo is best-effort
                pass
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
            raw_content=raw_content or None,
        )
