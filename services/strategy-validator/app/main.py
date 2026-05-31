from __future__ import annotations

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from stock_strategy_shared.schemas.strategy import StrategyConfig

app = FastAPI(title="strategy-validator")

# Hard safety limits that are enforced regardless of what the schema allows.
# These values represent maximums that no strategy should exceed safely.
_SAFETY_LIMITS = {
    "max_positions": 200,
    "max_position_weight": 0.5,
    "max_sector_weight": 0.75,
    "max_cluster_weight": 0.75,
}


def _check_safety(cfg: StrategyConfig) -> list[str]:
    """Return a list of safety violations. Empty list means safe."""
    violations: list[str] = []

    pb = cfg.portfolio_builder
    if pb.max_positions > _SAFETY_LIMITS["max_positions"]:
        violations.append(
            f"portfolio_builder.max_positions={pb.max_positions} exceeds safety limit of {_SAFETY_LIMITS['max_positions']}"
        )

    de = cfg.delta_engine
    if de.max_positions > _SAFETY_LIMITS["max_positions"]:
        violations.append(
            f"delta_engine.max_positions={de.max_positions} exceeds safety limit of {_SAFETY_LIMITS['max_positions']}"
        )

    if pb.max_position_weight > _SAFETY_LIMITS["max_position_weight"]:
        violations.append(
            f"portfolio_builder.max_position_weight={pb.max_position_weight} "
            f"exceeds safety limit of {_SAFETY_LIMITS['max_position_weight']}"
        )

    if pb.max_sector_weight > _SAFETY_LIMITS["max_sector_weight"]:
        violations.append(
            f"portfolio_builder.max_sector_weight={pb.max_sector_weight} "
            f"exceeds safety limit of {_SAFETY_LIMITS['max_sector_weight']}"
        )

    if pb.max_cluster_weight > _SAFETY_LIMITS["max_cluster_weight"]:
        violations.append(
            f"portfolio_builder.max_cluster_weight={pb.max_cluster_weight} "
            f"exceeds safety limit of {_SAFETY_LIMITS['max_cluster_weight']}"
        )

    return violations


@app.get("/health")
async def health():
    return {"status": "ok", "service": "strategy-validator"}


@app.post("/validate")
async def validate(request: Request):
    """
    Validate a strategy config supplied as YAML or JSON.

    Content-Type: application/json  → parse as JSON
    Content-Type: application/yaml (or text/yaml) → parse as YAML
    Anything else → try JSON first, then YAML.

    Returns:
        200  { valid: true, strategy_id, warnings: [] }
        422  { valid: false, errors: [...], warnings: [] }
    """
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    raw: dict
    try:
        if "yaml" in content_type:
            raw = yaml.safe_load(body)
        else:
            import json
            try:
                raw = json.loads(body)
            except Exception:
                raw = yaml.safe_load(body)
    except Exception as exc:
        return JSONResponse(
            status_code=422,
            content={"valid": False, "errors": [f"Could not parse body: {exc}"], "warnings": []},
        )

    if not isinstance(raw, dict):
        return JSONResponse(
            status_code=422,
            content={"valid": False, "errors": ["Body must be a JSON object or YAML mapping"], "warnings": []},
        )

    try:
        cfg = StrategyConfig(**raw)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"valid": False, "errors": errors, "warnings": []},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=422,
            content={"valid": False, "errors": [str(exc)], "warnings": []},
        )

    safety_violations = _check_safety(cfg)
    if safety_violations:
        return JSONResponse(
            status_code=422,
            content={"valid": False, "errors": safety_violations, "warnings": []},
        )

    warnings: list[str] = []

    return {
        "valid": True,
        "strategy_id": cfg.strategy_id,
        "warnings": warnings,
    }
