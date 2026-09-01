from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_chronological_replay_resolves_main_once_and_propagates_identity() -> None:
    workflow = Path(
        ".github/workflows/backtester-ldrc-nonpit-vs-pit-certified.yml"
    ).read_text(encoding="utf-8")
    launcher = Path("backtester/run_ldrc_current_main.py").read_text(encoding="utf-8")

    # The workflow must not carry the obsolete pre-kernel Production pin that
    # caused ModuleNotFoundError after the replay code migrated to core.kernel.
    assert "887f479b15ad861313da666ad698034d3847121c" not in workflow
    assert "ref: main" in workflow
    assert "BACKTESTER_MAIN_SHA=${ACTUAL}" in workflow
    assert "test -f main-src/sentinel/core/kernel.py" in workflow
    assert "python backtester/run_ldrc_current_main.py" in workflow

    # The exact SHA resolved by checkout is the only Production identity the
    # retained wrappers may advertise or validate during the run.
    assert 'os.environ.get("BACKTESTER_MAIN_SHA"' in launcher
    assert "corrected.prod.EXPECTED_MAIN_SHA = sha" in launcher
    assert "corrected.runner.EXPECTED_MAIN_SHA = sha" in launcher
    assert "Production module escaped exact run-start checkout" in launcher
    assert "sys.path.insert(0, str(ROOT))" in launcher


def test_triggering_backtester_revision_is_immutable() -> None:
    workflow = Path(
        ".github/workflows/backtester-ldrc-nonpit-vs-pit-certified.yml"
    ).read_text(encoding="utf-8")
    assert "ref: ${{ github.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in workflow


def _current_main_fixture() -> tuple[Path, str] | None:
    root = Path("main-src").resolve()
    if not (root / "sentinel" / "core" / "kernel.py").is_file():
        return None
    sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    return root, sha


def test_launcher_imports_and_binds_exact_current_main_runtime(monkeypatch) -> None:
    fixture = _current_main_fixture()
    if fixture is None:
        pytest.skip("exact current-main checkout is supplied by the financial gate")
    root, sha = fixture
    monkeypatch.setenv("BACKTESTER_MAIN_ROOT", str(root))
    monkeypatch.setenv("BACKTESTER_MAIN_SHA", sha)

    launcher = importlib.import_module("backtester.run_ldrc_current_main")
    assert launcher.bind_run_start_main() == sha
    assert launcher.corrected.prod.EXPECTED_MAIN_SHA == sha
    assert launcher.corrected.runner.EXPECTED_MAIN_SHA == sha

    for module in (
        launcher.corrected.prod.production_kernel,
        launcher.corrected.prod.production,
    ):
        assert root in Path(module.__file__).resolve().parents


def test_launcher_is_executable_by_file_path(monkeypatch) -> None:
    fixture = _current_main_fixture()
    if fixture is None:
        pytest.skip("exact current-main checkout is supplied by the financial gate")
    root, sha = fixture
    env = dict(os.environ)
    env["BACKTESTER_MAIN_ROOT"] = str(root)
    env["BACKTESTER_MAIN_SHA"] = sha
    proc = subprocess.run(
        [sys.executable, "backtester/run_ldrc_current_main.py", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout
    assert "chronological Production source bound to run-start main=" in proc.stdout
