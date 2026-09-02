#!/usr/bin/env python3
"""Prevent actual-deadline probe failures from being mislabeled as market timing.

The shared GO probe contract emits the sanitized causal subprocess evidence. This
small outer guard owns the final semantic boundary: when preparation is proven
and the actual-deadline observation is unavailable, validation must REFUSE. A
real observed value of zero remains a legitimate "execution open not future"
result and is returned unchanged to the phase controller.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import sentinel_go_phase_controller as controller
import sentinel_go_phase_entry as phase
import sentinel_go_probe_contract as probe_contract


_INSTALLED_MARKER = "_sentinel_go_actual_deadline_guard_installed"


def _failure_evidence(recording: probe_contract.RecordingRunner) -> Mapping[str, Any]:
    child = recording.last_compose_run()
    if child is None:
        return {
            "reason": "ACTUAL_DEADLINE_OBSERVATION_UNAVAILABLE",
            "failure_class": "OBSERVATION_UNAVAILABLE",
            "exit_code": 2,
        }
    if int(child.returncode) != 0:
        return probe_contract.subprocess_evidence(
            child, context="ACTUAL_DEADLINE")
    return probe_contract.malformed_report_evidence(
        child, context="ACTUAL_DEADLINE")


def install() -> None:
    """Refuse unavailable final deadline evidence after typed diagnostics emit."""
    if getattr(controller, _INSTALLED_MARKER, False):
        return
    original = controller._actual_remaining_ms

    def guarded(runner, *, env, runtime_ref) -> Optional[int]:
        recording = probe_contract.RecordingRunner(runner)
        result = original(recording, env=env, runtime_ref=runtime_ref)
        if phase._PHASE.get("prepared") and result is None:
            evidence = _failure_evidence(recording)
            reason = str(evidence.get("reason") or "ACTUAL_DEADLINE_OBSERVATION_UNAVAILABLE")
            raise controller.PhaseRefused(
                "actual deadline observation unavailable (%s)" % reason)
        return result

    controller._actual_remaining_ms = guarded
    setattr(controller, _INSTALLED_MARKER, True)


def main() -> int:
    print(
        "REFUSED: sentinel_go_actual_deadline_guard.py is internal; use scripts/sentinel-go-validate.sh",
        file=__import__("sys").stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
