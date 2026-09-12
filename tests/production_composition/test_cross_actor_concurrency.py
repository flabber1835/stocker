from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_HELPER = ROOT / "scripts" / "sentinel_go_lock.py"


def _clean_env():
    env = dict(os.environ)
    for key in (
        "SENTINEL_GO_LOCK_HELD", "SENTINEL_GO_LOCK_FD", "SENTINEL_GO_RUN_TOKEN",
    ):
        env.pop(key, None)
    return env


def _holder(tmp_path: Path, actor: str):
    marker = tmp_path / (actor + ".ready")
    code = (
        "from pathlib import Path; import time; "
        f"Path({str(marker)!r}).write_text('ready'); "
        "time.sleep(0.8)"
    )
    process = subprocess.Popen(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c", code],
        cwd=ROOT, env=_clean_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), process.stderr.read() if process.stderr else actor
    return process


def _try_second_go():
    return subprocess.run(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c", "raise SystemExit(0)"],
        cwd=ROOT, env=_clean_env(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
    )


@pytest.mark.parametrize("actor", ["backup", "ingest", "automation", "panel_restart"])
def test_cross_actor_overlap_cannot_start_a_second_go_lifecycle(tmp_path, actor):
    holder = _holder(tmp_path, actor)
    try:
        blocked = _try_second_go()
        assert blocked.returncode == 2
        assert "already running" in blocked.stderr
    finally:
        holder.wait(timeout=10)


@pytest.mark.parametrize("actor", ["backup", "ingest", "automation", "panel_restart"])
def test_go_is_retryable_after_cross_actor_overlap_finishes(tmp_path, actor):
    holder = _holder(tmp_path, actor)
    holder.wait(timeout=10)
    retried = _try_second_go()
    assert retried.returncode == 0, retried.stderr


def test_plain_environment_marker_cannot_forge_concurrent_go_authority(tmp_path):
    env = _clean_env()
    env["SENTINEL_GO_LOCK_HELD"] = "1"
    env["SENTINEL_GO_LOCK_FD"] = "999999"
    code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
        "import sentinel_go_lock as g; raise SystemExit(0 if not g.lifecycle_lock_is_held() else 9)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=10, check=False,
    )
    assert completed.returncode == 0


def test_retry_gets_a_new_one_run_capability(tmp_path):
    marker1 = tmp_path / "token1"
    marker2 = tmp_path / "token2"
    code = (
        "import os; from pathlib import Path; "
        "Path(os.environ['TOKEN_OUT']).write_text(os.environ['SENTINEL_GO_RUN_TOKEN'])"
    )
    env = _clean_env()
    env["TOKEN_OUT"] = str(marker1)
    first = subprocess.run(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c", code],
        cwd=ROOT, env=env, timeout=10, check=False)
    assert first.returncode == 0
    env["TOKEN_OUT"] = str(marker2)
    second = subprocess.run(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c", code],
        cwd=ROOT, env=env, timeout=10, check=False)
    assert second.returncode == 0
    token1 = marker1.read_text()
    token2 = marker2.read_text()
    assert len(token1) == len(token2) == 64
    assert token1 != token2
