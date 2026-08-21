from sentinel import paper
from sentinel.controller.concordance_parent import (
    FAST_DAMAGED_BREADTH_DELTA5, STRATEGY_ID as PARENT_STRATEGY_ID,
)
from sentinel.controller.ldrc import LDRCConfig


def test_default_paper_runtime_is_simplified_three_signal_ldrc_v3():
    config, identity = paper._default_paper_strategy()  # noqa: SLF001
    assert config.strategy_id == PARENT_STRATEGY_ID
    assert config.fast_entry["min_damaged_breadth_delta5"] == FAST_DAMAGED_BREADTH_DELTA5 == 0.30
    assert identity["strategy"] == PARENT_STRATEGY_ID
    assert identity["allocation_overlay"] == "sentinel-concordance-simplified-ldrc"
    assert identity["allocation_overlay_version"] == "3"
    assert identity["allocation_overlay_source_sha256"]
    assert identity["recent_leadership_source_sha256"]


def test_simplified_v3_entry_and_recovery_constants_are_frozen():
    cfg = LDRCConfig()
    assert (
        cfg.divergence_ceiling,
        cfg.wc_drawdown_trigger,
        cfg.recent_r20_trigger,
        cfg.spy_r20_floor,
        cfg.recovery_sessions,
        cfg.spy_v_rebound,
    ) == (0.55, -0.10, -0.08, 0.00, 7, 0.11)


def test_paper_gateway_has_no_legacy_runtime_identity_default():
    source = open(paper.__file__, encoding="utf-8").read()
    assert "runtime_strategy_identity(load_controller())" not in source
    assert source.count("_default_paper_strategy()") >= 6
