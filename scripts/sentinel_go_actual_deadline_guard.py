#!/usr/bin/env python3
"""Prevent actual-deadline probe failures from being mislabeled as market timing.

The shared GO probe contract emits the sanitized causal subprocess evidence. This
small outer guard owns the final semantic boundary: when preparation is proven
and the actual-deadline observation is unavailable, validation must REFUSE. A
real observed value of zero remains a legitimate "execution open not future"
result and is returned unchanged to the phase controller.
"""
from __future__ import annotations

from typing import Optional

import sentinel_go_phase_controller as controller
import sentinel_go_phase_entry as phase


_INSTALLED_MARKER = "_sentinel_go_actual_deadline_guard_installed"


def install() -> None:
    """Refuse unavailable final deadline evidence after typed diagnostics emit."""
    if getattr(controller, _INSTALLED_MARKER, False):
        return
    original = controller._actual_remaining_ms

    def guarded(runner, *, env, runtime_ref) -> Optional[int]:
        # Preserve the exact production runner. The inner probe-contract wrapper
        # already records the compose child and emits typed causal diagnostics.
        # Wrapping here would hide run_with_timeout/_run from that inner wrapper
        # and make a healthy prepared run look like an unbounded runner.
        result = original(runner, env=env, runtime_ref=runtime_ref)
        if phase._PHASE.get("prepared") and result is None:
            raise controller.PhaseRefused(
                "actual deadline observation unavailable "
                "(ACTUAL_DEADLINE_OBSERVATION_UNAVAILABLE)")
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
