"""Every Sentinel container declares a resource ceiling.

The NAS memory ceiling is the binding constraint for the whole deployment, so it
is part of the product contract rather than an operational detail. The rule here
is about ENFORCEMENT existing, not about the numbers being final:

> nothing is certified in an unbounded environment.

That is not a stylistic preference. The 8b OOM is still, in the repository's own
words, "inference from a silent exit with no traceback" — because nothing was
bounded, there was no oom-kill to point at and no measured peak to compare
against. The same shape produced Stocker's pipeline crash-loop, which is why
`PIPELINE_MEM_LIMIT` exists there.

Limits are set EARLY AND GENEROUSLY and tightened once the real envelope has been
measured. A test that demanded arbitrary values would be wrong; a value backed by
a reproduced production OOM is different. On 2026-08-23 the full ACTIONS v5
reconciliation was cgroup-killed just above the former 2 GiB engine ceiling and
completed when that same run was raised to 4 GiB, so 4 GiB is now the reviewed
minimum until issue #235 makes the path memory-bounded and re-measures it.

Contract: docs/sentinel-execution-contract.md §15.4.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
sys.path.insert(0, str(ROOT))

COMPOSE = REPO / "docker-compose.sentinel.yml"


def _compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(COMPOSE.read_text())


_UNITS = {"b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def _bytes(value) -> int:
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([bkmg]?)b?", text)
    if not match:                                             # pragma: no cover
        raise AssertionError(f"unparseable memory limit {value!r}")
    return int(float(match.group(1)) * _UNITS.get(match.group(2) or "b", 1))


def test_the_compose_file_exists():
    assert COMPOSE.exists()


def test_EVERY_service_declares_a_memory_limit():
    services = _compose()["services"]
    missing = [name for name, spec in services.items()
               if not spec.get("mem_limit")
               and not (spec.get("deploy", {}).get("resources", {})
                        .get("limits", {}).get("memory"))]
    assert not missing, (
        f"{missing} run without a memory ceiling. An unbounded container makes "
        f"an OOM unattributable: there is no kill to point at and no measured "
        f"peak to compare against, which is exactly why the 8b failure is still "
        f"recorded as an INFERENCE rather than a measurement.")


def test_EVERY_service_declares_a_cpu_limit():
    services = _compose()["services"]
    missing = [name for name, spec in services.items() if not spec.get("cpus")]
    assert not missing, f"{missing} run without a CPU ceiling"


def test_the_read_only_panel_is_smaller_than_the_engine():
    """A phone refreshing a page every 30 seconds must not be able to compete
    with the trading process for the host's memory."""
    services = _compose()["services"]
    assert _bytes(services["sentinel-panel"]["mem_limit"]) \
        < _bytes(services["sentinel"]["mem_limit"])


def test_engine_covers_measured_actions_reconciliation_peak():
    """The former 2 GiB ceiling killed the real full ACTIONS v5 reconciliation.
    The same NAS run completed at 4 GiB, so do not regress below that measured
    operational envelope until the streaming remediation in issue #235 lands."""
    services = _compose()["services"]
    assert _bytes(services["sentinel"]["mem_limit"]) >= 4 * 1024 ** 3


def test_the_engine_is_bounded_below_a_plausible_NAS():
    """The reservation only means something if the greedy neighbour is bounded
    too — a certification run must not be able to OOM-kill the live process."""
    services = _compose()["services"]
    total = sum(_bytes(spec["mem_limit"]) for spec in services.values())
    assert total <= 8 * 1024 ** 3, (
        f"the declared ceilings sum to {total / 1024 ** 3:.1f} GiB, which is "
        f"more than the deployment host has. Limits that cannot all be honoured "
        f"at once are not limits.")


def test_the_limits_are_documented_as_PROVISIONAL():
    """Early and generous, tightened after measurement. If the comment naming
    that goes away, someone has started treating these as calibrated."""
    text = COMPOSE.read_text()
    assert "tightened to the measured envelope later" in text
