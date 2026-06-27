"""F3 + F4 — cross-service GATE THRESHOLD ordering invariants.

Two places enforce the same notion with different thresholds. They are correct
TODAY but unguarded: a future env/config change could silently invert them and
reintroduce the "planner builds something the gate rejects" class. These tests
read the REAL defaults from source (so they can't drift) and lock the ordering.

F3: risk-service MAX_POSITION_PCT (price-drift backstop) must be >= every
    strategy's portfolio_builder.max_position_weight (construction cap). If the
    backstop were tighter, a freshly-built position would trip the gate on its
    first buy_add.
F4: trade-executor EXIT_SYNC_MAX_AGE_HOURS must be <= risk-service
    MAX_SYNC_AGE_HOURS. The executor refuses to SIZE on a stale sync; the risk
    gate refuses to APPROVE on one. If the executor tolerated a STALER sync than
    the gate, it could size an order the gate then rejects (or worse, size off
    data the gate considers too old).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RISK_MAIN = ROOT / "services" / "risk-service" / "app" / "main.py"
TE_MAIN = ROOT / "services" / "trade-executor" / "app" / "main.py"


def _default_float(src: str, name: str) -> float:
    """Extract the default from `NAME = _safe_float("NAME", <default>)` or a
    plain `getenv("NAME", "<default>")` assignment."""
    m = re.search(rf'{name}\s*=\s*_safe_float\(\s*"{name}"\s*,\s*([0-9.]+)\s*\)', src)
    if not m:
        m = re.search(rf'getenv\(\s*"{name}"\s*,\s*"([0-9.]+)"\s*\)', src)
    assert m, f"could not find default for {name}"
    return float(m.group(1))


def _strategy_max_position_weights() -> dict[str, float]:
    out = {}
    for f in sorted((ROOT / "strategies").glob("*.yaml")):
        cfg = yaml.safe_load(f.read_text())
        pb = (cfg or {}).get("portfolio_builder") or {}
        if "max_position_weight" in pb:
            out[f.name] = float(pb["max_position_weight"])
    return out


def test_f3_risk_position_pct_not_tighter_than_any_builder_cap():
    risk_pct = _default_float(RISK_MAIN.read_text(), "MAX_POSITION_PCT")
    weights = _strategy_max_position_weights()
    assert weights, "no strategy configs found"
    for name, w in weights.items():
        assert w <= risk_pct + 1e-9, (
            f"{name}: builder max_position_weight {w} exceeds risk MAX_POSITION_PCT "
            f"backstop {risk_pct} — a freshly-built position would trip the gate."
        )


def test_f4_executor_sync_age_not_looser_than_risk_sync_age():
    risk_sync = _default_float(RISK_MAIN.read_text(), "MAX_SYNC_AGE_HOURS")
    exec_sync = _default_float(TE_MAIN.read_text(), "EXIT_SYNC_MAX_AGE_HOURS")
    assert exec_sync <= risk_sync + 1e-9, (
        f"trade-executor EXIT_SYNC_MAX_AGE_HOURS {exec_sync} is looser than "
        f"risk MAX_SYNC_AGE_HOURS {risk_sync} — executor could size on a sync the "
        f"gate rejects."
    )
