from __future__ import annotations

from pathlib import Path

import pytest
from tests.production_composition.test_operator_entry_process import (
    _run as operator_run, private_operator_checkout,  # noqa: F401
)

STAGES = (
    ("bootstrap", "scripts/sentinel_deployment_bootstrap.py"),
    ("host_preflight", "scripts/sentinel_go_host_preflight.py"),
    ("runtime_preflight", "scripts/sentinel_runtime_selection.py"),
    ("account_preflight", "scripts/sentinel_go_account_preflight.py"),
    # output_guard owns certification, Phase C schema/Sharadar/publication work,
    # read-only readiness, and final validation-bundle creation.
    ("validation_phase_c_bundle", "scripts/sentinel_go_output_guard.py"),
    ("promotion_pointer", "in-process:sentinel_go_promote.main"),
    ("panel_handoff", "scripts/sentinel_go_post_validate.py"),
)


def _run(tmp_path: Path, *, kill_script=None, kill_rc=None):
    env = ({'COMPOSITION_FAIL_SCRIPT':kill_script,'COMPOSITION_FAIL_RC':str(kill_rc)}
           if kill_script else {})
    return operator_run(tmp_path, process_env=env)


def _index(calls, script):
    for index, line in enumerate(calls):
        if line.startswith(script):
            return index
    raise AssertionError((script, calls))


@pytest.mark.parametrize("signal_rc", [137, 143])
@pytest.mark.parametrize(("name", "script"), STAGES)
def test_sigkill_or_sigterm_stops_exactly_at_first_boundary(
        tmp_path, name, script, signal_rc):
    completed, calls = _run(tmp_path, kill_script=script, kill_rc=signal_rc)
    assert completed.returncode == signal_rc, (name, completed.stderr)
    killed_at = _index(calls, script)
    stage_scripts = [value for _label, value in STAGES]
    for later in stage_scripts[stage_scripts.index(script) + 1:]:
        assert not any(line.startswith(later) for line in calls), (
            name, signal_rc, later, calls)
    assert killed_at >= 0


@pytest.mark.parametrize(("name", "script"), STAGES)
def test_retry_after_killed_boundary_starts_a_fresh_complete_lifecycle(tmp_path, name, script):
    killed, _calls = _run(tmp_path, kill_script=script, kill_rc=137)
    assert killed.returncode == 137, name

    retried, calls = _run(tmp_path)
    assert retried.returncode == 0, (name, retried.stderr)
    for _label, expected in STAGES:
        _index(calls, expected)
    assert "GO lifecycle completed successfully" in retried.stdout
