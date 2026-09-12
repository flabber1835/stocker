from pathlib import Path

from sentinel import paper
from sentinel.paper import execution as paper_execution
from sentinel.paper import preparation as paper_preparation
from sentinel.paper import recovery as paper_recovery
from sentinel.controller.champion_config import STRATEGY_ID, REFERENCE_SOURCE_SHA256
from sentinel.controller.ldrc import LDRCConfig
from sentinel.strategy import production_strategy


def test_default_paper_runtime_is_the_shared_compact_champion():
    config, identity = paper_preparation._default_paper_strategy()  # noqa: SLF001
    assert (config, identity) == production_strategy()
    assert config.strategy_id == identity["strategy"] == STRATEGY_ID
    assert identity["research_reference_source_sha256"] == REFERENCE_SOURCE_SHA256
    assert identity["universe"] == "BROAD_SHARADAR_COMMON_EQUITY"


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
    sources = {
        module.__name__: Path(module.__file__).read_text(encoding="utf-8")
        for module in (paper_preparation, paper_execution, paper_recovery)
    }
    combined = "\n".join(sources.values())
    assert "runtime_strategy_identity(load_controller())" not in combined
    assert sources[paper_preparation.__name__].count("load_controller()") == 1
    assert combined.count("_default_paper_strategy()") >= 7
