from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_install_entry as install_go  # noqa: E402


def _validation(*failures):
    return {
        "dual_run_verdict": install_go.go.DUAL_RUN_NO_GO,
        "machine_failures": {
            "shadow": [],
            "dual_run": list(failures),
            "paper_execution": [],
        },
    }


def test_waiting_install_accepts_only_session_readiness_failure_vocabulary():
    assert install_go._wait_failures_safe(_validation(
        "GATE_SHARADAR_READINESS_NOT_PASS",
        "SESSION_TIMING_NOT_READY",
        "SHADOW_STATE_NOT_FRESH",
    )) is True
    assert install_go._wait_failures_safe(_validation(
        "SESSION_TIMING_NOT_READY")) is True


def test_waiting_install_rejects_mutation_or_structural_failure_codes():
    for failure in (
            "BROKER_MUTATION_BOUNDARY_BREACHED",
            "PRODUCTION_DB_WRITE_BOUNDARY_BREACHED",
            "GATE_WEALTH_CORE_NAS_PARITY_NOT_PASS",
            "DATABASE_FINANCIAL_HEALTH_NOT_PASS",
            "PREVALIDATION_PREPARATION_NOT_PASS"):
        value = _validation(failure)
        assert install_go._wait_failures_safe(value) is False
        # The installation-target adapter must fail before consulting any
        # missing lower-level fields when the failure vocabulary is unsafe.
        assert install_go._document_install_safe(value, {}) is False


def test_waiting_install_rejects_empty_duplicate_or_malformed_failures():
    assert install_go._wait_failures_safe(_validation()) is False
    assert install_go._wait_failures_safe(_validation(
        "SESSION_TIMING_NOT_READY", "SESSION_TIMING_NOT_READY")) is False
    malformed = _validation("SESSION_TIMING_NOT_READY")
    malformed["machine_failures"]["dual_run"] = [None]
    assert install_go._wait_failures_safe(malformed) is False
