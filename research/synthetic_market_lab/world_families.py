from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldFamilySpec:
    """Strategy-independent structural research family definition.

    Phase 1 records the family semantics and intended generator levers. Full
    family-specific calibration/generation is intentionally deferred until the
    reference generator is frozen and validated.
    """

    key: str
    description: str
    structural_levers: tuple[str, ...]


WORLD_FAMILIES: tuple[WorldFamilySpec, ...] = (
    WorldFamilySpec("broad_persistent_leadership", "Long-lived cross-sectional leadership across several sectors.", ("lower factor reversion", "persistent sector premia", "moderate idiosyncratic noise")),
    WorldFamilySpec("rapid_leadership_rotation", "Frequent changes in sector and factor leadership.", ("higher factor reversion", "higher sector-state noise", "shorter regime persistence")),
    WorldFamilySpec("extreme_top_rank_instability", "High cross-sectional rank churn with weak persistence.", ("higher idiosyncratic volatility", "weak factor persistence", "strong crowding reversal")),
    WorldFamilySpec("momentum_crashes", "Persistent momentum interrupted by sharp sign reversals.", ("momentum crowding state", "rare reversal shocks", "stress-dependent correlation")),
    WorldFamilySpec("factor_inversion", "Extended intervals in which conventional factor premia reverse sign.", ("signed factor target bias", "slow sign-state transitions", "cross-factor correlation shifts")),
    WorldFamilySpec("small_cap_alpha_disappearance", "Size premium weakens to zero for long intervals.", ("size-premium suppression state", "liquidity equalization", "cross-sectional noise")),
    WorldFamilySpec("liquidity_compression", "Market and security liquidity contract persistently.", ("negative macro liquidity", "higher spreads", "lower turnover", "higher common correlation")),
    WorldFamilySpec("prolonged_recession", "Long low-growth/high-distress macro episodes.", ("recession transition persistence", "weak growth target", "wide credit spreads")),
    WorldFamilySpec("inflationary_stagnation", "Weak real growth with persistent inflation and restrictive policy.", ("inflation persistence", "high policy-rate target", "low productivity")),
    WorldFamilySpec("credit_crisis", "Rapid credit-spread widening, defaults, and liquidity stress.", ("credit shock intensity", "bankruptcy hazard multiplier", "liquidity shock overlap")),
    WorldFamilySpec("pandemic_like_discontinuity", "Abrupt supply/demand interruption followed by uneven normalization.", ("supply shock", "growth shock", "volatility shock", "sector heterogeneity")),
    WorldFamilySpec("speculative_bubble_and_collapse", "Risk-appetite and valuation expansion followed by a crash.", ("bubble pressure state", "risk-appetite persistence", "crowding reversal")),
    WorldFamilySpec("sideways_low_alpha_decade", "Long interval with low aggregate drift and weak cross-sectional premia.", ("near-zero factor targets", "mean reversion", "low trend persistence")),
    WorldFamilySpec("high_volatility_no_trend", "Large daily moves with little persistent directional structure.", ("high volatility target", "low momentum persistence", "fast mean reversion")),
    WorldFamilySpec("low_volatility_high_correlation", "Calm individual prices dominated by common movement.", ("low idiosyncratic volatility", "high common-factor loading", "compressed sector noise")),
    WorldFamilySpec("repeated_sector_rotation", "Multiple cycles of sector leadership changes.", ("sector macro-loading rotation", "moderate regime persistence", "sector-specific shocks")),
    WorldFamilySpec("commodity_shock", "Large commodity impulse with heterogeneous sector effects.", ("commodity shock intensity", "energy/materials loadings", "inflation pass-through")),
    WorldFamilySpec("rate_shock", "Abrupt policy/rate repricing with duration-sensitive dispersion.", ("policy-rate shock", "yield-curve shift", "duration exposure dispersion")),
    WorldFamilySpec("productivity_boom", "Persistent productivity acceleration and growth leadership.", ("productivity shock persistence", "growth-factor target", "technology sector loading")),
    WorldFamilySpec("multiple_interacting_shocks", "Several simultaneous persistent shocks with nonlinear stress interaction.", ("multi-shock arrival rate", "overlapping decay", "stress correlation multiplier")),
)


def family_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in WORLD_FAMILIES)
