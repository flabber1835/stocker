from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
OBSERVABILITY = ROOT / "scripts" / "sentinel_go_observability.py"
LAUNCHER = ROOT / "scripts" / "sentinel-go-validate.sh"

spec = importlib.util.spec_from_file_location(
    "sentinel_go_observability_test_module", OBSERVABILITY)
obs = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = obs
spec.loader.exec_module(obs)


def test_certification_runs_short_surfaces_before_long_sentinel_suite():
    assert obs.CERTIFICATION_SUITE_LABELS == (
        "GO SCRIPT TESTS",
        "WEALTH CORE",
        "SENTINEL",
    )


def test_failure_node_capture_is_bounded_sanitized_and_color_safe():
    text = (
        "\x1b[31mFAILED\x1b[0m "
        "tests/scripts/test_sentinel_go_validate.py::"
        "test_shell_launcher_never_sources_dotenv_or_echoes_credentials - assert x\n"
        "ERROR tests/sentinel/test_example.py::test_case[param-1] - RuntimeError\n"
        "FAILED /volume1/private/test_secret.py::test_nope - should-not-leak\n"
        "FAILED https://example.invalid/test.py::test_nope - should-not-leak\n"
    )

    assert obs.extract_failure_nodes(text) == (
        "tests/scripts/test_sentinel_go_validate.py::"
        "test_shell_launcher_never_sources_dotenv_or_echoes_credentials",
        "tests/sentinel/test_example.py::test_case[param-1]",
    )


def test_failed_check_diagnostics_are_bounded_and_name_only():
    checks = ["recent XNYS axis", "warmup_revision_input_complete",
              "recent XNYS axis", "password=must-not-appear",
              "https://example.invalid/private"]
    checks.extend("safe-check-%02d" % index for index in range(40))

    result = obs.safe_failed_checks(checks)

    assert result[:2] == (
        "recent XNYS axis", "warmup_revision_input_complete")
    assert len(result) == 32
    assert not any("password" in item or "http" in item for item in result)


def test_failed_check_reason_diagnostics_require_safe_names_and_opaque_codes():
    result = obs.safe_failed_check_reasons([
        {"name": "SEP mutation watermark", "reason": "BEHIND_FRONTIER"},
        {"name": "password=must-not-appear", "reason": "CHECK_FAILED"},
        {"name": "issuer keys", "reason": "unsafe-detail"},
        {"name": "issuer keys", "reason": "MISSING_AUTHORITY"},
    ])

    assert result == (
        "SEP mutation watermark [BEHIND_FRONTIER]",
        "issuer keys [MISSING_AUTHORITY]",
    )


def test_only_networkless_test_runs_and_builds_stream_raw_output():
    assert obs._raw_stream_is_safe([
        "docker", "build", "-t", "candidate", "."])
    assert obs._raw_stream_is_safe([
        "docker", "run", "--rm", "--network", "none", "sha256:" + "a" * 64,
        "tests/sentinel", "-vv"])
    assert not obs._raw_stream_is_safe([
        "docker", "compose", "run", "sentinel", "python", "secret-probe"])


def test_command_labels_do_not_echo_arbitrary_command_payloads():
    label = obs._command_label([
        "python3", "-c", "password=should-never-appear"])
    assert label == "python3 subprocess"
    assert "password" not in label


def test_shell_launcher_routes_through_verified_entry_and_not_lower_level():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert '"$PYTHON" scripts/sentinel_go_verified_entry.py "$@"' in source
    executable_lines = [
        line.strip() for line in source.splitlines()
        if line.strip().startswith('"$PYTHON"')
    ]
    assert not any(
        "scripts/sentinel_go_validate.py" in line for line in executable_lines)


def test_shell_launcher_defines_colored_status_classes():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "GO_GREEN='\\033[1;32m'" in source
    assert "GO_YELLOW='\\033[1;33m'" in source
    assert "GO_RED='\\033[1;31m'" in source
    assert "[WARN]" in source
    assert "[ERROR]" in source


def test_heartbeat_reports_real_phase_rows_and_idle_time(capsys, monkeypatch):
    monkeypatch.setenv("SENTINEL_GO_COLOR", "never")
    event = {"stage": "source_download", "status": "working", "rows": 100000,
             "elapsed_ms": 50, "table": "SEP", "date_from": "2026-08-01", "date_to": "2026-08-19"}
    obs._working("certified financial preparation", 80, event, 12)
    output = capsys.readouterr().out
    assert "SEP 2026-08-01..2026-08-19" in output
    assert "100,000 rows" in output and "12s since last progress" in output
    assert "still running" not in output.lower()
    obs._working("read-only financial probe", 10)
    assert "subprocess supplied no internal progress" in capsys.readouterr().out


@pytest.mark.parametrize("startup_delay", [0, 0.6], ids=["normal", "delayed-reader-startup"])
def test_streaming_heartbeat_uses_progress_and_hides_sensitive_output(
        capsys, monkeypatch, tmp_path, startup_delay):
    from types import SimpleNamespace
    monkeypatch.setenv("SENTINEL_GO_COLOR", "never")
    monkeypatch.setattr(obs, "_HEARTBEAT_SECONDS", 0.01)
    release = tmp_path / "heartbeat-observed"
    original_working = obs._working

    def working(text, elapsed, event=None, idle=None):
        original_working(text, elapsed, event, idle)
        if event is not None:
            release.touch()

    monkeypatch.setattr(obs, "_working", working)
    if startup_delay:
        original_start = obs.threading.Thread.start
        started = 0

        def delayed_start(thread, *args, **kwargs):
            nonlocal started
            result = original_start(thread, *args, **kwargs)
            started += 1
            if started == 2:
                time.sleep(startup_delay)
            return result

        monkeypatch.setattr(obs.threading.Thread, "start", delayed_start)

    event = 'SENTINEL_FEED_PROGRESS={"stage":"source_download","status":"started","rows":0,"elapsed_ms":0,"table":"SEP","date_from":"2026-08-18","date_to":"2026-08-19"}'
    # Child lifetime depends on an observed heartbeat, not the CI scheduler.
    child = (
        "import sys,time\nfrom pathlib import Path\n"
        f"print({event!r}, file=sys.stderr, flush=True)\n"
        "print('password=hidden', flush=True)\n"
        f"release = Path({str(release)!r})\n"
        "while not release.exists():\n    time.sleep(0.01)\n"
    )
    command = [sys.executable, "-c", child]
    controller = SimpleNamespace(_safe_int_env=lambda name, default: 5)
    result = obs._streaming_run(controller, SimpleNamespace(MAX_BOUNDED_INGEST_MS=5000),
                                command, env=None, cwd=ROOT, raw_stream=False)
    output = capsys.readouterr().out
    assert result.returncode == 0 and "password=hidden" in result.stdout
    assert "password=hidden" not in output
    assert "[WORK]" in output and "SEP 2026-08-18..2026-08-19" in output
