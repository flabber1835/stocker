"""Exact runtime-only coverage required alongside the host full-suite pass."""
import xml.etree.ElementTree as ET

IMAGE_CLASS = "tests/sentinel/test_runtime_is_the_artifact.py::TestPytestImportsTheRUNTIMECode"
IMAGE_TESTS = tuple(IMAGE_CLASS + "::" + name for name in (
    "test_sentinel_is_imported_from_app",
    "test_wealth_core_comes_from_the_INSTALLED_package",
    "test_the_inspection_copy_is_NOT_importable",
    "test_the_ARTEFACT_matches_the_checkout_it_claims_to_be_built_from",
    "test_WEALTH_CORE_also_matches_its_checkout",
    "test_the_environment_reports_itself_COMPATIBLE",
))


def image_verdict(path, *, exitstatus):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    expected = {node.rsplit("::", 1)[1] for node in IMAGE_TESTS}
    actual = [case.get("name") for case in cases]
    failures = [case.get("name") for case in cases if any(
        child.tag in {"failure", "error", "skipped"} for child in case)]
    correct_class = all(case.get("classname", "").endswith(
        "test_runtime_is_the_artifact.TestPytestImportsTheRUNTIMECode")
                        for case in cases)
    suite_clean = all(int(suite.get(key, "0")) == 0 for suite in root.iter("testsuite")
                      for key in ("errors", "failures", "skipped"))
    passed = (exitstatus == 0 and correct_class and suite_clean and not failures
              and set(actual) == expected and len(actual) == len(expected))
    return {"verdict": "PASS" if passed else "FAIL", "expected": list(IMAGE_TESTS),
            "observed": actual, "failures": failures, "pytest_exitstatus": exitstatus}
