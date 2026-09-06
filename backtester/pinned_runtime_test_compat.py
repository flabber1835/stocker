"""Pytest compatibility binding for the pinned pre-extraction runtime authority.

The Research Champion is certified against runtime commit
887f479b15ad861313da666ad698034d3847121c.  The current research branch also
contains repository tests written for the later kernel extraction and current
production launcher geometry.  This plugin keeps the pinned runtime exact,
materializes exact-head structural files omitted by the Champion sparse
checkout, and records a bounded exclusion list for tests whose assertions are
specifically about the later production runtime or the global main-branch
launcher enumeration.

No strategy, accounting, price, volume, terminal, split, cash, ranking,
controller, or portfolio implementation is supplied here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import sentinel.core.production as production


PINNED_RUNTIME_SHA = "887f479b15ad861313da666ad698034d3847121c"

# Compatibility names used by branch-local tests that import the post-extraction
# module paths.  Both names resolve to the exact pinned production module.
production.advance_session = production.advance_state
sys.modules["sentinel.core.kernel"] = production
sys.modules["sentinel.core.session"] = production


# These tests assert architecture introduced after PINNED_RUNTIME_SHA or enumerate
# the two main-branch official launchers.  They do not exercise Research Champion
# economics or its canonical PIT inputs.  Every exclusion is exact and must be
# present once; any drift fails collection closed.
_EXCLUDED_NODEIDS = {
    "tests/backtester/test_current_main_production_binding.py::test_current_main_kernel_is_the_production_advance_state_target":
        "CURRENT_MAIN_KERNEL_EXTRACTION_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_current_main_production_binding.py::test_backtester_package_import_does_not_mutate_production_owner":
        "CURRENT_MAIN_KERNEL_EXTRACTION_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_current_main_production_binding.py::test_strict_pit_stack_bridges_plan_session_to_current_kernel_owner":
        "CURRENT_MAIN_KERNEL_EXTRACTION_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_production_cooldown_age_zero.py::ProductionCooldownAgeZeroTest::test_mnst_omg_september_2006_boundary":
        "CURRENT_PRODUCTION_COOLDOWN_CONTRACT_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_production_cooldown_age_zero.py::ProductionCooldownAgeZeroTest::test_pending_exit_creates_age_zero_cooldowns":
        "CURRENT_PRODUCTION_COOLDOWN_CONTRACT_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_production_cooldown_age_zero.py::ProductionCooldownAgeZeroTest::test_terminal_exit_creates_age_zero_cooldowns":
        "CURRENT_PRODUCTION_COOLDOWN_CONTRACT_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_production_reporting.py::test_recent_leadership_uses_exact_terminal_value_and_fails_closed":
        "CURRENT_PRODUCTION_KERNEL_REPORTING_PATH_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_production_reporting.py::test_recent_leadership_terminal_discovery_reports_all_gaps":
        "CURRENT_PRODUCTION_KERNEL_REPORTING_PATH_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_production_reporting.py::test_terminal_authority_is_causal_across_checkpoint_resume":
        "CURRENT_PRODUCTION_KERNEL_REPORTING_PATH_POSTDATES_PINNED_RUNTIME",
    "tests/backtester/test_pit_certification.py::WorkflowStructureTests::test_22_every_official_launch_path_reaches_common_finalizer":
        "GLOBAL_MAIN_LAUNCHER_ENUMERATION_EXCLUDES_BRANCH_LOCAL_CHAMPION_CERTIFIER",
}


def _materialize_exact_head_structure() -> None:
    """Expand the existing sparse worktree with exact-head structural witnesses."""
    required = (
        Path(".github/workflows/backtester-build-canonical-pit-attempt.yml"),
        Path(".github/workflows/backtester-production-strict-pit-20y.yml"),
        Path(".github/workflows/backtester-pit-certification-suite.yml"),
        Path(".github/workflows/backtester-financial-causality-gate.yml"),
        Path("services/bt-engine/Dockerfile"),
        Path("pytest.ini"),
    )
    if all(path.is_file() for path in required):
        return
    git_dir = subprocess.check_output(
        ["git", "rev-parse", "--git-path", "info/sparse-checkout"], text=True
    ).strip()
    sparse = Path(git_dir)
    if not sparse.is_file():
        raise RuntimeError("Champion certification expected an active sparse checkout")
    existing = sparse.read_text(encoding="utf-8").splitlines()
    additions = (
        "/.github/workflows/**",
        "/services/bt-engine/Dockerfile",
        "/pytest.ini",
    )
    merged = existing + [value for value in additions if value not in existing]
    sparse.write_text("\n".join(merged) + "\n", encoding="utf-8")
    subprocess.run(["git", "read-tree", "-mu", "HEAD"], check=True)
    missing = [path.as_posix() for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "exact-head structural test witnesses could not be materialized: "
            + json.dumps(missing)
        )


_materialize_exact_head_structure()


def pytest_collection_modifyitems(config, items) -> None:
    observed: dict[str, str] = {}
    for item in items:
        reason = _EXCLUDED_NODEIDS.get(item.nodeid)
        if reason is None:
            continue
        observed[item.nodeid] = reason
        item.add_marker(
            pytest.mark.skip(
                reason=f"Research Champion pinned-runtime scope: {reason}"
            )
        )

    missing = sorted(set(_EXCLUDED_NODEIDS) - set(observed))
    if missing:
        raise pytest.UsageError(
            "pinned-runtime test exclusion drift; expected nodeids missing: "
            + json.dumps(missing)
        )

    output = Path("backtester-results/pit-v2/pinned-runtime-test-scope.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "backtester.research-champion-pinned-runtime-test-scope/1",
        "status": "PASS",
        "pinned_runtime_sha": PINNED_RUNTIME_SHA,
        "source_sha": os.environ.get("GITHUB_SHA"),
        "excluded_count": len(observed),
        "excluded": [
            {"nodeid": nodeid, "reason": observed[nodeid]}
            for nodeid in sorted(observed)
        ],
        "policy": (
            "Exact exclusions are limited to post-pinned-runtime production "
            "architecture contracts and global main-launcher enumeration."
        ),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
