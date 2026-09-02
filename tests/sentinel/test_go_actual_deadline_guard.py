from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_actual_deadline_guard as guard
import sentinel_go_phase_controller as controller
import sentinel_go_phase_entry as phase


class Runner:
    def run(self, argv, *, env=None, cwd=None):
        raise AssertionError("guard-only unit must not create subprocess work")


def _install_with_value(monkeypatch, value):
    state = {"value": value}

    def actual(_runner, *, env, runtime_ref):
        return state["value"]

    monkeypatch.setattr(controller, "_actual_remaining_ms", actual)
    monkeypatch.delattr(controller, guard._INSTALLED_MARKER, raising=False)
    guard.install()
    return state


def test_prepared_missing_actual_deadline_refuses_instead_of_becoming_timing_failure(
        monkeypatch):
    state = _install_with_value(monkeypatch, None)
    monkeypatch.setitem(phase._PHASE, "prepared", True)

    with pytest.raises(
            controller.PhaseRefused,
            match="actual deadline observation unavailable"):
        controller._actual_remaining_ms(
            Runner(), env={}, runtime_ref="sha256:" + "a" * 64)

    # A real observed zero is semantically different: the child did complete and
    # proved that the execution open is no longer future. Preserve that value so
    # the phase controller can emit its legitimate timing failure.
    state["value"] = 0
    assert controller._actual_remaining_ms(
        Runner(), env={}, runtime_ref="sha256:" + "a" * 64) == 0


def test_unprepared_none_remains_guarded_by_existing_phase_contract(monkeypatch):
    _install_with_value(monkeypatch, None)
    monkeypatch.setitem(phase._PHASE, "prepared", False)
    assert controller._actual_remaining_ms(
        Runner(), env={}, runtime_ref=None) is None


def test_verified_entry_installs_deadline_guard_after_probe_contract_before_observability():
    source = (SCRIPT_DIR / "sentinel_go_verified_entry.py").read_text(encoding="utf-8")
    probe = source.index("probe_contract.install(controller=controller, phase=phase)")
    deadline = source.index("actual_deadline_guard.install()")
    observability = source.index("observability.install(go=go, controller=controller)")
    assert probe < deadline < observability
