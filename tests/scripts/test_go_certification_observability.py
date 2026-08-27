from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


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
        "BACKTESTER BOUNDARY",
        "BT DATA",
        "BT ENGINE",
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
