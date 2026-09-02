from __future__ import annotations

import fnmatch
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
TRIAL = WORKFLOW_DIR / "backtester-production-trial-2006-2007.yml"
FINANCIAL_GATE = WORKFLOW_DIR / "backtester-financial-causality-gate.yml"
PYTEST_PIN = "pytest==8.4.2"

# Any sparse checkout that executes the complete tests/backtester suite must
# materialize this closure. Broad patterns are accepted when they cover the
# required path (for example /services/** covers /services/backtester/**).
REQUIRED_FULL_SUITE_CLOSURE = (
    "/.github/workflows/**",
    "/backtester/**",
    "/services/backtester/**",
    "/services/bt-engine/Dockerfile",
    "/tools/**",
    "/tests/conftest.py",
    "/tests/backtester/**",
    "/tests/support/**",
    "/research/sentinel-fastgate/experiments/2026-08-25-pit-vs-full-c/ldrc_ab_replay_20260825.py",
    "/research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz",
    "/PIT input data/SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz",
    "/PIT input data/SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv",
    "/pytest.ini",
)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _root_checkout_sparse_patterns(path: Path) -> tuple[str, ...] | None:
    document = _load(path)
    matches: list[tuple[str, ...] | None] = []
    for job in (document.get("jobs") or {}).values():
        steps = job.get("steps") or []
        runs_full_suite = any(
            "python -m pytest -q tests/backtester" in str(step.get("run") or "")
            for step in steps
        )
        if not runs_full_suite:
            continue
        root_checkout = None
        for step in steps:
            uses = str(step.get("uses") or "")
            if not uses.startswith("actions/checkout@"):
                continue
            options = step.get("with") or {}
            if options.get("path"):
                continue
            root_checkout = options
            break
        if root_checkout is None:
            raise AssertionError(
                f"{path.name}: full backtester suite has no repository-root checkout"
            )
        sparse = root_checkout.get("sparse-checkout")
        if sparse is None:
            matches.append(None)
            continue
        patterns = tuple(
            line.strip()
            for line in str(sparse).splitlines()
            if line.strip()
        )
        matches.append(patterns)
    if not matches:
        raise AssertionError(
            f"{path.name}: expected workflow to execute the complete backtester suite"
        )
    if len(matches) != 1:
        raise AssertionError(
            f"{path.name}: expected one complete-suite job, found {len(matches)}"
        )
    return matches[0]


def _covered(required: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(required, pattern) for pattern in patterns)


class BacktesterWorkflowTestClosureTests(unittest.TestCase):
    def _assert_complete_suite_checkout(self, path: Path) -> None:
        patterns = _root_checkout_sparse_patterns(path)
        if patterns is None:
            return
        missing = [
            required
            for required in REQUIRED_FULL_SUITE_CLOSURE
            if not _covered(required, patterns)
        ]
        self.assertEqual(
            missing,
            [],
            f"{path.name}: complete backtester suite sparse checkout is incomplete; "
            f"missing coverage for {missing}; patterns={patterns}",
        )

    def test_production_trial_materializes_complete_pytest_harness(self) -> None:
        self._assert_complete_suite_checkout(TRIAL)

    def test_financial_gate_materializes_complete_pytest_harness(self) -> None:
        self._assert_complete_suite_checkout(FINANCIAL_GATE)

    def test_financial_gate_watches_production_trial_workflow(self) -> None:
        document = _load(FINANCIAL_GATE)
        watched = set(document["on"]["push"]["paths"])
        self.assertIn(
            ".github/workflows/backtester-production-trial-2006-2007.yml",
            watched,
        )

    def test_complete_suite_workflows_use_same_pinned_pytest(self) -> None:
        for path in (TRIAL, FINANCIAL_GATE):
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                f"python -m pip install {PYTEST_PIN}",
                text,
                f"{path.name}: complete-suite pytest version is not pinned",
            )

    def test_root_conftest_enforces_runtime_backtester_package_identity(self) -> None:
        conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
        self.assertIn('expected = (_ROOT / "backtester" / "__init__.py").resolve()', conftest)
        self.assertIn('runtime = importlib.import_module("backtester")', conftest)
        self.assertIn("backtester package shadowing", conftest)

    def test_cold_boot_postgres_support_is_part_of_required_closure(self) -> None:
        cold_boot = (ROOT / "tests" / "backtester" / "test_cold_boot_identity.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from tests.support.postgres import _EphemeralPostgres", cold_boot)
        self.assertIn("/tests/support/**", REQUIRED_FULL_SUITE_CLOSURE)


if __name__ == "__main__":
    unittest.main()
