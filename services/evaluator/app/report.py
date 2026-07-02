"""LLM report generation for the weekly evaluator (Phase 1: read-only).

Calls the llm-gateway (the system's single LLM interface) with provider=anthropic
and an Opus-class model. Output is a strict JSON contract: a markdown narrative plus
structured recommendation objects. Every recommendation's `config_field` is validated
against the real StrategyConfig schema — an unknown field is flagged, not shown as
actionable — so hallucinated knobs can never flow into Phase 3.

LLM boundary (per docs/llm-boundaries.md): this module SUGGESTS only. It never
writes config, never touches the trading path.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import httpx
from pydantic import BaseModel

from stock_strategy_shared.schemas.strategy import StrategyConfig

LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8000")
EVALUATOR_MODEL = os.getenv("EVALUATOR_MODEL", "claude-opus-4-8")
EVALUATOR_PROVIDER = os.getenv("EVALUATOR_PROVIDER", "anthropic")
EVALUATOR_MAX_TOKENS = int(os.getenv("EVALUATOR_MAX_TOKENS", "16000"))
GATEWAY_TIMEOUT_SECS = float(os.getenv("EVALUATOR_GATEWAY_TIMEOUT_SECS", "900"))

REPORT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "narrative_markdown": {
            "type": "string",
            "description": "The full weekly report as markdown: what's working, what isn't, evidence.",
        },
        "overall_assessment": {
            "type": "string",
            "enum": ["healthy", "mixed", "concerning", "insufficient_data"],
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "observation": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "config_field": {"type": "string"},
                    "current_value": {"type": "string"},
                    "suggested_value": {"type": "string"},
                    "direction": {"type": "string", "enum": ["increase", "decrease", "enable", "disable", "change", "investigate"]},
                    "expected_effect": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["observation", "evidence", "config_field", "suggested_value",
                             "direction", "expected_effect", "confidence"],
            },
        },
        "data_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative_markdown", "overall_assessment", "recommendations", "data_gaps"],
}

SYSTEM_PROMPT = """You are the weekly strategy evaluator for a systematic equity trading system \
(daily factor ranking -> LLM vetting -> portfolio construction -> buffer-zone rebalancing -> \
paper trading at the broker). Your single goal: make the system PICK MORE WINNERS.

You receive a deterministic evidence packet: the active strategy YAML, per-factor realized \
IC and MARGINAL IC (signal a factor adds beyond the weighted book), factor correlations, \
realized account performance vs SPY, per-trade realized P&L, counterfactual audits (what \
vetter-excluded names and exited names did AFTERWARD), the current target book, config-change \
history, and system-health caveats.

Rules:
- You are READ-ONLY and advisory. You recommend config tweaks; a human applies them.
- Ground every claim in the packet. Cite the specific numbers (e.g. "momentum marginal IC \
+0.06 over 4 of last 6 weeks"). Never invent data. If evidence is thin, say so and lower \
confidence — with only weeks of live history, most findings are "watch", not "act".
- Recommendations must target REAL fields of the strategy YAML you were given (e.g. \
factor weights in static_factor_weights, portfolio_builder.selection_vol_aversion, \
portfolio_builder.beta_target, vetter thresholds, universe floors). Use dotted paths.
- Prefer FEW, well-evidenced recommendations (0-4) over many speculative ones. "No change \
warranted" is a valid, often correct conclusion — churn in strategy config is itself a cost.
- Distinguish alpha problems from ops problems: check system_health first; a data outage \
week is not evidence against a factor.
- Marginal IC (not raw IC, not correlation-to-composite) is the standard for adding or \
up-weighting a factor. A factor can look good raw and add nothing beyond the book.
- Structure narrative_markdown with: ## Verdict, ## What worked, ## What hurt, \
## Decision audits (vetter/exits), ## Recommendations, ## Watch list.

Respond ONLY with the JSON object matching the response schema."""


class ReportResult(BaseModel):
    narrative_markdown: str
    overall_assessment: str = "insufficient_data"
    recommendations: list[dict] = []
    data_gaps: list[str] = []
    provider: str = ""
    model: str = ""
    prompt_hash: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    parse_fallback: bool = False


def valid_config_fields() -> set[str]:
    """Dotted paths of every real StrategyConfig field (2 levels deep) — the
    whitelist recommendations are validated against."""
    fields: set[str] = set()

    def _walk(model: type[BaseModel], prefix: str, depth: int) -> None:
        for name, f in model.model_fields.items():
            path = f"{prefix}{name}"
            fields.add(path)
            if depth <= 0:
                continue
            ann = f.annotation
            # unwrap Optional[X] / X | None
            for cand in getattr(ann, "__args__", [ann]):
                if isinstance(cand, type) and issubclass(cand, BaseModel):
                    _walk(cand, f"{path}.", depth - 1)

    _walk(StrategyConfig, "", 2)
    return fields


def validate_recommendations(recs: list[dict]) -> list[dict]:
    """Stamp each recommendation with config_field_valid. Factor-weight paths like
    static_factor_weights.momentum are validated against the FactorWeights model
    via the same walk; unknown fields are flagged (shown but not actionable)."""
    known = valid_config_fields()
    out = []
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        field = str(rec.get("config_field", "")).strip()
        rec["config_field_valid"] = field in known
        out.append(rec)
    return out


def build_user_prompt(packet: dict) -> str:
    return (
        "Weekly evidence packet follows as JSON. Evaluate the system and produce "
        "the report JSON.\n\n" + json.dumps(packet, default=str)
    )


async def generate_report(packet: dict) -> ReportResult:
    """One gateway call -> validated ReportResult. Parse failures degrade to a
    narrative-only report (raw text preserved) instead of raising."""
    user_prompt = build_user_prompt(packet)
    prompt_hash = hashlib.sha256((SYSTEM_PROMPT + user_prompt).encode()).hexdigest()[:16]

    payload = {
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "provider": EVALUATOR_PROVIDER,
        "model": EVALUATOR_MODEL,
        "max_tokens": EVALUATOR_MAX_TOKENS,
        "thinking": True,
        "response_schema": REPORT_SCHEMA,
    }
    async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT_SECS) as client:
        r = await client.post(f"{LLM_GATEWAY_URL}/v1/chat", json=payload)
        r.raise_for_status()
        data = r.json()

    raw = data.get("content", "") or ""
    meta = {
        "provider": data.get("provider", ""),
        "model": data.get("model", ""),
        "prompt_hash": prompt_hash,
        "input_tokens": data.get("input_tokens", 0),
        "output_tokens": data.get("output_tokens", 0),
        "latency_ms": data.get("latency_ms", 0),
    }
    parsed = _parse_report_json(raw)
    if parsed is None:
        return ReportResult(
            narrative_markdown=raw or "(empty LLM response)",
            overall_assessment="insufficient_data",
            recommendations=[],
            data_gaps=["LLM output was not valid report JSON — raw text shown verbatim"],
            parse_fallback=True,
            **meta,
        )
    return ReportResult(
        narrative_markdown=str(parsed.get("narrative_markdown", "")),
        overall_assessment=str(parsed.get("overall_assessment", "insufficient_data")),
        recommendations=validate_recommendations(list(parsed.get("recommendations") or [])),
        data_gaps=[str(g) for g in (parsed.get("data_gaps") or [])],
        **meta,
    )


def _parse_report_json(raw: str) -> dict | None:
    """Tolerant JSON extraction: direct parse, then fenced block, then outermost
    braces. Returns None when nothing parses to a dict."""
    for candidate in _json_candidates(raw):
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and "narrative_markdown" in obj:
            return obj
    return None


def _json_candidates(raw: str):
    yield raw
    if "```" in raw:
        for chunk in raw.split("```")[1::2]:
            yield chunk.removeprefix("json").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        yield raw[start:end + 1]
