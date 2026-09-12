from __future__ import annotations

from pathlib import Path

from .contract import EDGES
from .coverage import ADJACENT_GO_SUITE, EDGE_EVIDENCE, REQUIRED_EXTERNAL_WORKFLOWS

ROOT = Path(__file__).resolve().parents[2]


def test_every_authority_edge_has_executable_evidence_not_just_a_catalog_entry():
    names = {edge.name for edge in EDGES}
    assert set(EDGE_EVIDENCE) == names
    for edge in EDGES:
        evidence = EDGE_EVIDENCE[edge.name]
        assert len(evidence) >= 2, edge.name
        assert any("tests/production_composition/" in path for path in evidence) \
            or edge.execution_class == "docker_postgres", edge.name
        assert all((ROOT / path).is_file() for path in evidence), (edge.name, evidence)
        assert "tests/production_composition/test_contract_matrix.py" not in evidence


def test_every_p0_edge_has_multiple_independent_evidence_surfaces():
    for edge in EDGES:
        if not edge.p0:
            continue
        evidence = EDGE_EVIDENCE[edge.name]
        families = {
            path.split("/", 2)[0:2][1] if path.startswith("tests/") else path
            for path in evidence
        }
        assert len(evidence) >= 3, (edge.name, evidence)
        assert len(families) >= 2, (edge.name, evidence)


def test_adjacent_go_suite_is_present_and_not_empty():
    assert len(ADJACENT_GO_SUITE) >= 8
    for path in ADJACENT_GO_SUITE:
        file = ROOT / path
        assert file.is_file(), path
        assert file.stat().st_size > 500, path


def test_external_harness_workflows_remain_present():
    for path in REQUIRED_EXTERNAL_WORKFLOWS:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "workflow_dispatch" in text, path
        assert "pull_request" in text, path


def test_coverage_ledger_names_the_live_restore_and_backup_harnesses():
    restore = EDGE_EVIDENCE["restore_upgrade_to_go"]
    backup = EDGE_EVIDENCE["backup_to_database_mutation"]
    assert any("internal_state" in path for path in restore)
    assert any("backup" in path for path in restore)
    assert any("backup" in path for path in backup)


def test_credential_and_registry_edges_are_bound_to_new_host_composition_tests():
    assert "tests/production_composition/test_operator_entry_process.py" in \
        EDGE_EVIDENCE["shell_to_ci_verifier"]
    assert "tests/production_composition/test_ci_runtime_boundary.py" in \
        EDGE_EVIDENCE["ci_artifact_to_registry"]
    assert "tests/production_composition/test_ci_runtime_boundary.py" in \
        EDGE_EVIDENCE["registry_to_local_image"]


def test_failure_evidence_edge_is_bound_to_exact_diagnostic_regression():
    assert "tests/production_composition/test_preparation_diagnostics.py" in \
        EDGE_EVIDENCE["failure_to_bundle"]
