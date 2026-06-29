"""Single source of truth for the generic engine's factors.

Historically the factor list was duplicated across ~7 sites (rank.FACTORS, the
pipeline's column lists, the api SELECTs, the dashboard, the FactorWeights schema)
plus a DB column per factor — so adding a factor meant editing many places and a
migration. This registry centralizes the *set of factors* so every consumer derives
from one list; the JSONB factor store (migration) removes the per-factor column so
no migration is needed to add one.

Adding a factor:
  1. add a FactorDef here,
  2. implement its compute in services/pipeline/app/factors.py,
  3. add the matching field to FactorWeights (a drift test enforces this), and
  4. give it a weight in a strategy config.
No SQL/migration change required (scores are stored as JSONB).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactorDef:
    name: str          # canonical key (matches FactorWeights field + factor_scores JSONB key)
    label: str         # short display label (dashboard chips)


# Order is the canonical display order.
FACTOR_REGISTRY: tuple[FactorDef, ...] = (
    FactorDef("momentum", "Momentum"),
    FactorDef("quality", "Quality"),
    FactorDef("value", "Value"),
    FactorDef("growth", "Growth"),
    FactorDef("low_volatility", "Low Vol"),
    FactorDef("liquidity", "Liquidity"),
    FactorDef("issuance", "Issuance"),
    FactorDef("small_cap", "Small Cap"),
    FactorDef("volume_surge", "Vol Surge"),
    FactorDef("near_high", "Near High"),
    FactorDef("high_volatility", "High Vol"),
    FactorDef("earnings_surprise", "Earn Surprise"),
)

FACTOR_NAMES: tuple[str, ...] = tuple(f.name for f in FACTOR_REGISTRY)
FACTOR_LABELS: dict[str, str] = {f.name: f.label for f in FACTOR_REGISTRY}
FACTOR_COUNT: int = len(FACTOR_REGISTRY)

# Display-only indicators: computed and surfaced on the screener, but NEVER scoring
# factors (not weighted, not in the composite). Listed here so consumers can treat
# "the engine's outputs" uniformly without hardcoding the set in several places.
DISPLAY_INDICATORS: tuple[str, ...] = (
    "drawdown_21d", "beta", "excess_dd_21d", "idio_vol", "excess_dd_limit",
)
