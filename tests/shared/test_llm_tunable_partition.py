"""LLM-tunable partition: which strategy-file fields an automated tuner may change.

PROTECTED_PATHS are human-only (identity / data-source / crash-protection). Everything
else is LLM-tunable. validate_llm_tunable_diff(baseline, proposed) returns the
protected paths that changed — empty == safe to consider.
"""
import copy

from stock_strategy_shared.schemas.strategy import (
    PROTECTED_PATHS,
    is_protected_path,
    validate_llm_tunable_diff,
)


def _baseline() -> dict:
    return {
        "strategy_id": "core_v1",
        "universe": {"source": "av_listing", "min_price": 5.0},
        "static_factor_weights": {"momentum": 0.5, "quality": 0.3, "value": 0.2,
                                  "growth": 0.0, "low_volatility": 0.0},
        "vetter": {"candidate_count": 50,
                   "falling_knife": {"excess_pct": 0.15, "backstop_pct": 0.25}},
        "portfolio_builder": {"max_positions": 30, "max_position_weight": 0.1},
    }


def test_protected_paths_are_the_expected_set():
    assert PROTECTED_PATHS == frozenset({"strategy_id", "universe.source", "vetter.falling_knife"})


def test_is_protected_path_prefix_match():
    assert is_protected_path("strategy_id")
    assert is_protected_path("universe.source")
    assert is_protected_path("vetter.falling_knife")          # the subtree root
    assert is_protected_path("vetter.falling_knife.excess_pct")  # under the subtree
    assert not is_protected_path("universe.min_price")
    assert not is_protected_path("vetter.candidate_count")
    assert not is_protected_path("static_factor_weights.momentum")


def test_identical_config_has_no_violations():
    b = _baseline()
    assert validate_llm_tunable_diff(b, copy.deepcopy(b)) == []


def test_tunable_change_is_allowed():
    b = _baseline()
    p = copy.deepcopy(b)
    p["static_factor_weights"]["momentum"] = 0.4   # reweight (tunable)
    p["static_factor_weights"]["value"] = 0.3
    p["universe"]["min_price"] = 10.0              # universe filter (tunable)
    p["vetter"]["candidate_count"] = 80            # vetter scope (tunable)
    assert validate_llm_tunable_diff(b, p) == []


def test_strategy_id_change_is_flagged():
    b = _baseline()
    p = copy.deepcopy(b); p["strategy_id"] = "core_v2"
    assert validate_llm_tunable_diff(b, p) == ["strategy_id"]


def test_universe_source_change_is_flagged():
    b = _baseline()
    p = copy.deepcopy(b); p["universe"]["source"] = "sharadar"
    assert validate_llm_tunable_diff(b, p) == ["universe.source"]


def test_falling_knife_change_is_flagged():
    b = _baseline()
    p = copy.deepcopy(b); p["vetter"]["falling_knife"]["excess_pct"] = 0.30  # loosen the veto
    assert validate_llm_tunable_diff(b, p) == ["vetter.falling_knife.excess_pct"]


def test_introducing_a_protected_subtree_is_flagged():
    # Baseline omits falling_knife (env fallback); proposal adds it → loosening attempt.
    b = _baseline(); b["vetter"].pop("falling_knife")
    p = copy.deepcopy(b); p["vetter"]["falling_knife"] = {"backstop_pct": 0.9}
    assert validate_llm_tunable_diff(b, p) == ["vetter.falling_knife.backstop_pct"]


def test_multiple_violations_sorted():
    b = _baseline()
    p = copy.deepcopy(b)
    p["strategy_id"] = "x"
    p["vetter"]["falling_knife"]["backstop_pct"] = 0.9
    assert validate_llm_tunable_diff(b, p) == ["strategy_id", "vetter.falling_knife.backstop_pct"]
