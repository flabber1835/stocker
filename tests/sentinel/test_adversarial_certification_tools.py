"""Contract tests for the system evidence and mutation harnesses."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from tools import sentinel_adversarial_evidence as evidence
from tools import sentinel_mutation_certify as mutation


def test_every_reviewed_mutant_has_one_source_anchor_and_one_test():
    for mutant in mutation.MUTANTS:
        source = mutation.RUNTIME / mutant.relative_path
        assert source.is_file()
        assert source.read_text(encoding="utf-8").count(mutant.original) == 1
        relative_test = mutant.test.split("::", 1)[0]
        assert (mutation.TEST_SOURCE / relative_test).is_file()


def test_junit_errors_and_skips_can_never_be_reported_as_passes():
    for child_name in ("failure", "error", "skipped"):
        case = ET.fromstring(
            f'<testcase classname="suite" name="case" time="0.1">'
            f'<{child_name} message="proof" /></testcase>')
        record = evidence._case_record(case)  # noqa: SLF001
        assert record["status"] == child_name
        assert record["detail_tail"] == "proof"


def test_required_evidence_layers_name_real_test_surfaces():
    all_tests = "\n".join(
        str(path) for path in Path(
            mutation.TEST_SOURCE / "tests/sentinel").glob("test_*.py"))
    for layer, patterns in evidence.LAYERS.items():
        assert any(pattern in all_tests for pattern in patterns), layer


def test_safety_workflow_retains_junit_system_and_mutation_evidence():
    workflow = (
        mutation.REPO / ".github/workflows/sentinel-safety.yml"
    ).read_text(encoding="utf-8")
    assert "--junitxml=/evidence/sentinel.xml" in workflow
    assert "sentinel_adversarial_evidence.py" in workflow
    assert "sentinel_mutation_certify.py" in workflow
    assert workflow.count(
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    ) >= 3
