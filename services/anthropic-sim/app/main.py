"""
Anthropic Claude Messages API simulator.

Simulates POST /v1/messages so the real llm-gateway (which uses
anthropic.AsyncAnthropic(api_key=..., base_url=ANTHROPIC_BASE_URL)) can work
without real API keys during testing.

Decision logic is deterministic: the ticker is extracted from the user message
and a sha256 hash byte drives which of three outcomes to return.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="anthropic-sim")


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_ticker(text: str) -> str:
    """Return the first 1-5 char all-uppercase word found in text, else 'UNKN'."""
    m = re.search(r"\b([A-Z]{1,5})\b", text)
    return m.group(1) if m else "UNKN"


def _decision_for_ticker(ticker: str) -> dict:
    """
    Deterministic vetter decision derived from sha256(ticker).

    seed % 10 == 0  → exclude, earnings risk
    seed % 10 == 1  → exclude, regulatory risk
    else            → keep, no risk
    """
    seed = hashlib.sha256(ticker.encode()).digest()[0]
    mod = seed % 10

    if mod == 0:
        return {
            "exclude": True,
            "reason": f"Upcoming earnings for {ticker} show deteriorating analyst estimates with a guidance cut risk within the risk window.",
            "confidence": "medium",
            "risk_type": "earnings",
            "positive_catalyst": False,
            "positive_reason": "",
        }
    if mod == 1:
        return {
            "exclude": True,
            "reason": f"Active regulatory enforcement action against {ticker} identified; material downside risk within the holding period.",
            "confidence": "high",
            "risk_type": "regulatory",
            "positive_catalyst": False,
            "positive_reason": "",
        }
    return {
        "exclude": False,
        "reason": f"No material risks identified for {ticker}. No adverse news, regulatory action, or earnings concerns within the assessment window.",
        "confidence": "medium",
        "risk_type": "none",
        "positive_catalyst": False,
        "positive_reason": "",
    }


def _extract_user_text(body: dict) -> str:
    """
    Pull the plain text out of the messages array.

    Anthropic messages can be:
      {"role": "user", "content": "plain string"}
      {"role": "user", "content": [{"type": "text", "text": "..."}]}
    """
    parts: list[str] = []
    for msg in body.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return " ".join(parts)


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "anthropic-sim"}


@app.get("/v1/models")
async def list_models():
    """Anthropic SDK may call this during initialisation."""
    return {
        "data": [
            {"id": "claude-haiku-4-5-20251001", "type": "model"},
            {"id": "claude-sonnet-4-5-20251101", "type": "model"},
        ]
    }


@app.post("/v1/messages")
async def create_message(request: Request):
    """
    Simulate POST /v1/messages (Anthropic Messages API).

    Parses the incoming request, extracts the ticker from the user text,
    generates a deterministic vetter decision, and returns it wrapped in
    the Anthropic response envelope.  stop_reason is always 'end_turn' so
    the gateway never triggers a tool-use agentic loop.
    """
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})

    model = body.get("model", "claude-haiku-4-5-20251001")
    max_tokens: int = body.get("max_tokens", 1024)

    # Extract ticker from the combined user message text
    user_text = _extract_user_text(body)
    ticker = _extract_ticker(user_text)

    decision = _decision_for_ticker(ticker)
    response_json = json.dumps(decision)

    # Rough token approximation (good enough for tests)
    input_tokens = max(10, len(user_text) // 4)
    output_tokens = max(10, len(response_json) // 4)

    return {
        "id": f"msg_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": response_json}
        ],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
