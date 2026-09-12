"""Falsifiers for the narrow expected-xfail execution authority."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

# verify_test_owner_execution.py is also a directly executable CLI and imports its
# sibling helper by module name. Mirror direct-script import semantics here while
# exercising the verifier functions through the package path.
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from tools.test_responsibility_lib import ROOT, junit_case_execution, load_authority
from tools.verify_test_owner_execution import (
    SETTLED_EXPECTED_XFAILS,
    _expected_xfails,
    _require_collection_outcomes,
)


THIS_MODULE = ROOT / "tests/scripts/test_expected_xfail_authority.py"
OWNER = "wealth-core.prospective"


def test_junit_distinguishes_pytest_xfail_from_an_ordinary_skip(tmp_path):
    junit = tmp_path / "outcomes.xml"
    junit.write_text(
        '<testsuite tests="3">'
        '<testcase classname="tests.scripts.test_expected_xfail_authority" name="test_pass"/>'
        '<testcase classname="tests.scripts.test_expected_xfail_authority" name="test_expected">'
        '<skipped type="pytest.xfail" message="known pending pin"/></testcase>'
        '<testcase classname="tests.scripts.test_expected_xfail_authority" name="test_skip">'
        '<skipped message="ordinary skip"/></testcase>'
        '</testsuite>',
        encoding="utf-8",
    )
    _executed, cases = junit_case_execution([junit], [THIS_MODULE])
    assert cases["tests/scripts/test_expected_xfail_authority.py::test_pass"] == "passed"
    assert cases["tests/scripts/test_expected_xfail_authority.py::test_expected"] == "xfailed"
    assert cases["tests/scripts/test_expected_xfail_authority.py::test_skip"] == "skipped"


def test_expected_xfail_inventory_is_exact_and_cannot_expand_from_the_manifest():
    authority = load_authority()
    settled = SETTLED_EXPECTED_XFAILS[OWNER]
    assert _expected_xfails(authority, OWNER) == settled

    widened = deepcopy(authority)
    widened["owners"][OWNER]["execution"]["expected_xfails"].append(
        "tests/wealth_core/test_golden_fixture.py::test_unreviewed_failure"
    )
    with pytest.raises(AssertionError, match="differs from settled inventory"):
        _expected_xfails(widened, OWNER)

    removed = deepcopy(authority)
    removed["owners"][OWNER]["execution"]["expected_xfails"].pop()
    with pytest.raises(AssertionError, match="differs from settled inventory"):
        _expected_xfails(removed, OWNER)


def test_only_exact_declared_xfails_are_authorized_execution_outcomes():
    expected = next(iter(SETTLED_EXPECTED_XFAILS[OWNER]))
    passing = "tests/wealth_core/test_adapter.py::test_ordinary_pass"
    collected = {passing, expected}

    result = _require_collection_outcomes(
        OWNER,
        collected,
        {passing: "passed", expected: "xfailed"},
        {expected},
    )
    assert result["executed_nodes"] == 2
    assert result["passing_nodes"] == 1
    assert result["expected_xfails"] == [expected]

    for bad_status in ("skipped", "failure", "error", "passed"):
        with pytest.raises(AssertionError, match="complete authorized collection"):
            _require_collection_outcomes(
                OWNER,
                collected,
                {passing: "passed", expected: bad_status},
                {expected},
            )

    extra = "tests/wealth_core/test_adapter.py::test_unreviewed_xfail"
    with pytest.raises(AssertionError, match="complete authorized collection"):
        _require_collection_outcomes(
            OWNER,
            collected | {extra},
            {passing: "passed", expected: "xfailed", extra: "xfailed"},
            {expected},
        )
