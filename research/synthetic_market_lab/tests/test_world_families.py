from research.synthetic_market_lab.world_families import WORLD_FAMILIES, family_keys


def test_required_world_family_registry_is_complete_and_unique():
    expected = {
        "broad_persistent_leadership", "rapid_leadership_rotation", "extreme_top_rank_instability", "momentum_crashes",
        "factor_inversion", "small_cap_alpha_disappearance", "liquidity_compression", "prolonged_recession",
        "inflationary_stagnation", "credit_crisis", "pandemic_like_discontinuity", "speculative_bubble_and_collapse",
        "sideways_low_alpha_decade", "high_volatility_no_trend", "low_volatility_high_correlation", "repeated_sector_rotation",
        "commodity_shock", "rate_shock", "productivity_boom", "multiple_interacting_shocks",
    }
    assert set(family_keys()) == expected
    assert len(WORLD_FAMILIES) == len(expected)
    assert all(spec.structural_levers for spec in WORLD_FAMILIES)
