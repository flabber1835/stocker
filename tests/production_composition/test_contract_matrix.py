from __future__ import annotations

import pytest

from .contract import EDGES, VARIANTS, missing_anchors, require_complete_catalog, scenarios


SCENARIOS = scenarios()


def test_matrix_is_exact_and_large_enough():
    require_complete_catalog(SCENARIOS)
    assert len(EDGES) >= 20
    assert len(VARIANTS) == 8
    assert len(SCENARIOS) >= 160
    assert sum(edge.p0 for edge in EDGES) >= 12


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.scenario_id)
def test_every_authority_edge_has_adversarial_outcome_contract(scenario):
    assert scenario.edge.execution_class in {
        "host_subprocess", "external_network", "docker", "docker_postgres",
        "filesystem",
    }
    assert scenario.edge.source
    assert scenario.edge.target
    assert scenario.edge.authority
    if scenario.variant in {"happy", "retry"}:
        assert scenario.must_advance
        assert not scenario.must_have_reason
    else:
        assert not scenario.must_advance
        assert scenario.must_have_reason


@pytest.mark.parametrize("edge", EDGES, ids=lambda item: item.name)
def test_production_authority_edge_is_still_wired_in_source(edge):
    assert not missing_anchors(edge), (
        edge.name,
        edge.source_path,
        missing_anchors(edge),
    )


def test_p0_edges_include_full_operator_and_post_validation_chain():
    names = {edge.name for edge in EDGES if edge.p0}
    assert {
        "operator_to_lock",
        "lock_to_verified_entry",
        "env_file_to_shell",
        "shell_to_ci_verifier",
        "ci_artifact_to_registry",
        "registry_to_local_image",
        "certification_to_preparation",
        "lock_to_preparation",
        "backup_to_database_mutation",
        "certified_identity_to_feed_binding",
        "preparation_to_publication",
        "readiness_to_target_proof",
        "target_proof_to_promotion",
        "promotion_to_pointer",
        "pointer_to_panel",
        "failure_to_bundle",
        "restore_upgrade_to_go",
    }.issubset(names)
