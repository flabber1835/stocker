"""Gateway → Anthropic request shaping for Opus 4.7+ family models.

Root cause guarded here: the provider used to pass `temperature` on EVERY request,
but the Opus 4.7/4.8, Sonnet 5, and Fable/Mythos families REJECT sampling params
with HTTP 400 — so the weekly evaluator's Opus-class call would have failed on its
first request. The provider now omits temperature for those models and supports
adaptive thinking (the only on-mode there; budget_tokens is removed).
"""
import os as _os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_GW_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "llm-gateway"))
_app = sys.modules.get("app")
if _app is None or _GW_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]
    if _GW_PATH not in sys.path:
        sys.path.insert(0, _GW_PATH)

_mock_anthropic = MagicMock()
_mock_anthropic.AsyncAnthropic = MagicMock
_mock_anthropic.RateLimitError = type("RateLimitError", (Exception,), {})
_mock_anthropic.InternalServerError = type("InternalServerError", (Exception,), {})
sys.modules.setdefault("anthropic", _mock_anthropic)

from app.providers.anthropic_provider import AnthropicProvider, _accepts_sampling_params
from app.schemas import ChatRequest, Message


def _response():
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        stop_reason="end_turn", model="m",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0),
    )


async def _call(model: str, thinking: bool = False) -> dict:
    provider = AnthropicProvider(api_key="k", model="claude-haiku-4-5-20251001")
    provider._client = MagicMock()
    provider._client.messages.create = AsyncMock(return_value=_response())
    req = ChatRequest(messages=[Message(role="user", content="hi")],
                      model=model, temperature=0.3, thinking=thinking)
    await provider.chat(req)
    return provider._client.messages.create.call_args.kwargs


def test_accepts_sampling_params_matrix():
    assert _accepts_sampling_params("claude-haiku-4-5-20251001")
    assert _accepts_sampling_params("claude-sonnet-4-6")
    assert _accepts_sampling_params("claude-opus-4-6")
    assert not _accepts_sampling_params("claude-opus-4-7")
    assert not _accepts_sampling_params("claude-opus-4-8")
    assert not _accepts_sampling_params("claude-sonnet-5")
    assert not _accepts_sampling_params("claude-fable-5")


@pytest.mark.asyncio
async def test_temperature_omitted_on_opus_48():
    kwargs = await _call("claude-opus-4-8")
    assert "temperature" not in kwargs  # would 400 otherwise
    assert "top_p" not in kwargs and "top_k" not in kwargs


@pytest.mark.asyncio
async def test_temperature_kept_on_haiku():
    kwargs = await _call("claude-haiku-4-5-20251001")
    assert kwargs["temperature"] == 0.3  # vetter behavior unchanged


@pytest.mark.asyncio
async def test_adaptive_thinking_passthrough():
    kwargs = await _call("claude-opus-4-8", thinking=True)
    assert kwargs["thinking"] == {"type": "adaptive"}  # adaptive only — never budget_tokens


@pytest.mark.asyncio
async def test_no_thinking_by_default():
    kwargs = await _call("claude-opus-4-8", thinking=False)
    assert "thinking" not in kwargs
