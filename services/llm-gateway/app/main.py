"""
LLM Gateway — provider abstraction layer for Anthropic and Ollama.

Routes /v1/chat requests to the configured provider.
Services should call this instead of talking to Anthropic or Ollama directly.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from app.providers.base import BaseProvider
from app.schemas import ChatRequest, ChatResponse, ProviderInfo

log = logging.getLogger("llm-gateway")

# ── Env vars ─────────────────────────────────────────────────────────────────

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT_SECS = int(os.getenv("OLLAMA_TIMEOUT_SECS", "600"))

# ── Provider registry ────────────────────────────────────────────────────────

_providers: dict[str, BaseProvider] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _providers

    # Always try to build Ollama provider
    try:
        from app.providers.ollama_provider import OllamaProvider
        ollama_provider = OllamaProvider(
            host=OLLAMA_HOST,
            model=OLLAMA_MODEL,
            timeout=OLLAMA_TIMEOUT_SECS,
        )
        _providers["ollama"] = ollama_provider
        log.info("[llm-gateway] Ollama provider registered (host=%s model=%s)", OLLAMA_HOST, OLLAMA_MODEL)
    except Exception as exc:
        log.warning("[llm-gateway] Could not initialize Ollama provider: %s", exc)

    # Try Anthropic if key is set
    if ANTHROPIC_API_KEY:
        try:
            from app.providers.anthropic_provider import AnthropicProvider
            anthropic_provider = AnthropicProvider(
                api_key=ANTHROPIC_API_KEY,
                model=ANTHROPIC_MODEL,
            )
            _providers["anthropic"] = anthropic_provider
            log.info("[llm-gateway] Anthropic provider registered (model=%s)", ANTHROPIC_MODEL)
        except Exception as exc:
            log.warning("[llm-gateway] Could not initialize Anthropic provider: %s", exc)

    if not _providers:
        log.error("[llm-gateway] No providers available! Set ANTHROPIC_API_KEY or ensure Ollama is reachable.")
    else:
        log.info("[llm-gateway] Default provider: %s  Available: %s", LLM_PROVIDER, list(_providers))

    yield
    _providers.clear()


app = FastAPI(title="llm-gateway", lifespan=lifespan)


def _get_provider(name: str | None) -> BaseProvider:
    """Resolve a provider by name, falling back to LLM_PROVIDER default."""
    target = name or LLM_PROVIDER
    provider = _providers.get(target)
    if provider is None:
        available = list(_providers)
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{target}' is not available. Available: {available}",
        )
    return provider


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """LIVENESS ONLY — the container healthcheck's target. No I/O.

    This endpoint used to `await provider.health_check()` for every registered
    provider. The Ollama provider is registered unconditionally, but `ollama`
    lives behind `--profile ollama` and normally does not exist, so every probe
    made a real network call to an unresolvable host with a 5.0s inner timeout —
    exactly the compose healthcheck's own 5s timeout. On a cold `up` (network
    being created, 17 containers attaching, images still building) the lookup
    could take that long, the probe expired, and five expiries marked the
    container unhealthy. llm-vetter declared `service_healthy` on it, so the
    whole live stack failed with rc=1 — and a second `up -d` "fixed" it because
    by then DNS returned NXDOMAIN instantly.

    Nothing was ever actually wrong: this returned {"status": "ok"} either way.
    It was only too SLOW. A liveness probe that performs external I/O reports
    someone else's outage as its own death.

    Live provider state moved to /health/providers.
    """
    return {
        "status": "ok",
        "service": "llm-gateway",
        "default_provider": LLM_PROVIDER,
        # Names only — which providers are CONFIGURED is process-local state and
        # costs nothing. Whether each one ANSWERS is a network question.
        "configured_providers": sorted(_providers),
    }


@app.get("/health/providers")
async def health_providers():
    """READINESS — live probe of every provider. For humans and the dashboard.

    Deliberately NOT the container healthcheck target: it makes network calls
    whose latency is governed by hosts this service does not control."""
    provider_statuses = []
    for name, p in _providers.items():
        try:
            ok = await p.health_check()
        except Exception:
            ok = False
        provider_statuses.append({"name": name, "available": ok,
                                  "default_model": p.default_model})

    return {
        "status": "ok",
        "service": "llm-gateway",
        "default_provider": LLM_PROVIDER,
        "providers": provider_statuses,
    }


@app.get("/providers")
async def list_providers():
    result = []
    for name, p in _providers.items():
        try:
            ok = await p.health_check()
        except Exception:
            ok = False
        models: list[str] = []
        if hasattr(p, "list_models"):
            models = await p.list_models()
        result.append(ProviderInfo(
            name=name,
            available=ok,
            default_model=p.default_model,
            models=models,
        ))
    return result


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    provider = _get_provider(request.provider)

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = await provider.chat(request)
            log.info(
                "[llm-gateway] %s %s → %din/%dout/%dcached %dms",
                provider.name,
                response.model,
                response.input_tokens,
                response.output_tokens,
                response.cached_tokens,
                response.latency_ms,
            )
            return response
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt < 2:
                backoff = 2.0 ** attempt  # attempt 0 → 1s, attempt 1 → 2s (3 attempts total)
                log.warning("[llm-gateway] Transient error on attempt %d: %s — retrying in %.0fs", attempt + 1, exc, backoff)
                await asyncio.sleep(backoff)
        except HTTPException:
            raise
        except RuntimeError as exc:
            # Provider-wrapped UPSTREAM rejection (e.g. "anthropic 400: <reason>").
            # 502 + the real message so the caller's error_message is diagnosable
            # instead of an opaque "500 Internal Server Error".
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Provider error: {exc}") from exc

    raise HTTPException(
        status_code=503,
        detail=f"Provider '{provider.name}' failed after 3 attempts: {last_exc}",
    )
