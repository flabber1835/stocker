"""A full-suite verdict cannot omit the tests that require the runtime image."""
import xml.etree.ElementTree as ET

import pytest

from tests.internal_state.image_gate import IMAGE_TESTS, image_verdict


@pytest.mark.parametrize("fault", ["intact", "missing", "duplicate", "skipped", "failure",
                                   "error", "exit", "wrong_class", "suite_error"])
def test_runtime_image_gate_requires_complete_passing_evidence(tmp_path, fault):
    root = ET.Element("testsuite")
    for node in IMAGE_TESTS:
        ET.SubElement(root, "testcase", name=node.rsplit("::", 1)[1],
                      classname="tests.sentinel.test_runtime_is_the_artifact.TestPytestImportsTheRUNTIMECode")
    if fault == "missing":
        root.remove(root[-1])
    elif fault == "duplicate":
        root[-1].set("name", root[0].get("name"))
    elif fault in {"skipped", "failure", "error"}:
        ET.SubElement(root[-1], fault)
    elif fault == "wrong_class":
        root[-1].set("classname", "unrelated.TestPytestImportsTheRUNTIMECode")
    elif fault == "suite_error":
        root.set("errors", "1")
    path = tmp_path / "runtime.xml"
    ET.ElementTree(root).write(path)
    result = image_verdict(path, exitstatus=1 if fault == "exit" else 0)
    assert result["verdict"] == ("PASS" if fault == "intact" else "FAIL")
