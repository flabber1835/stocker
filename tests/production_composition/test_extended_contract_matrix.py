from __future__ import annotations

import pytest

from tests.production_composition.extended_contract import (
    EXTENDED_CASES,
    EXTENDED_VARIANTS,
    FAULT_CATEGORIES,
)


@pytest.mark.parametrize(
    ("category", "variant"),
    EXTENDED_CASES,
    ids=[f"{category.name}-{variant}" for category, variant in EXTENDED_CASES],
)
def test_every_extended_fault_contract_is_canonical(category, variant):
    assert category.name
    assert category.description
    assert category.requires_real_boundary is True
    assert variant in EXTENDED_VARIANTS


def test_extended_campaign_has_exactly_eighty_distinct_cases():
    keys = {(category.name, variant) for category, variant in EXTENDED_CASES}
    assert len(FAULT_CATEGORIES) == 10
    assert len(EXTENDED_VARIANTS) == 8
    assert len(EXTENDED_CASES) == 80
    assert len(keys) == 80


def test_extended_categories_are_exactly_the_reviewed_seams():
    assert tuple(category.name for category in FAULT_CATEGORIES) == (
        "cold_reboot",
        "restore_upgrade_go",
        "phase_boundary_kill",
        "filesystem_nas_fault",
        "docker_lifecycle_fault",
        "concurrency_cross_actor",
        "clock_calendar_boundary",
        "network_auth_partial",
        "promotion_handoff_atomicity",
        "evidence_survivability",
    )
