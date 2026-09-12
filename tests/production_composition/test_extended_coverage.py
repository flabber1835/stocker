from __future__ import annotations

from pathlib import Path

from tests.production_composition.extended_contract import FAULT_CATEGORIES
from tests.production_composition.extended_coverage import EXTENDED_EVIDENCE

ROOT = Path(__file__).resolve().parents[2]


def test_every_extended_category_has_executable_evidence():
    names = {category.name for category in FAULT_CATEGORIES}
    assert set(EXTENDED_EVIDENCE) == names
    for category in FAULT_CATEGORIES:
        evidence = EXTENDED_EVIDENCE[category.name]
        assert len(evidence) >= 2, (category.name, evidence)
        assert any(path.startswith("tests/production_composition/test_") for path in evidence), (
            category.name, evidence)
        for relative in evidence:
            assert (ROOT / relative).exists(), (category.name, relative)


def test_restore_upgrade_is_a_real_postgres_gate_in_composition_ci():
    workflow = (ROOT / ".github" / "workflows" /
                "production-composition-harness.yml").read_text(encoding="utf-8")
    assert "postgresql" in workflow
    assert "ALPACA_HARNESS_REQUIRE_POSTGRES:" in workflow
    assert "'1'" in workflow
    assert "tests/internal_state/test_physical.py" in workflow
    assert "physical-restore.xml" in workflow


def test_extended_fault_campaign_is_additive_to_original_authority_matrix():
    from tests.production_composition.contract import scenarios
    from tests.production_composition.extended_contract import EXTENDED_CASES

    base_cases = scenarios()
    assert len(base_cases) >= 160
    assert len(EXTENDED_CASES) == 80
    assert len(base_cases) + len(EXTENDED_CASES) >= 240
