"""scripts/down.sh — the two safety properties that must never regress.

The script's whole reason to exist is refusing two specific accidents:
  1. --volumes / -v (would delete the trading DB and the 35M-row corpus)
  2. tearing the backtest stack down while a backfill/experiment is running

Both are asserted by running the REAL script with docker/curl stubbed out on
PATH, so the tests exercise the actual argument parsing and guard logic without
touching any container.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "down.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")


def _stub(dirpath: Path, name: str, body: str):
    p = dirpath / name
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _run(tmp_path, *args, running=False):
    """Run down.sh with stubbed docker + curl. `running` fakes an in-flight job."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "docker.log"
    _stub(bindir, "docker", f'echo "$@" >> "{log}"; exit 0')
    if running:
        _stub(bindir, "curl", 'echo \'{"runs":[{"status": "running"}]}\'; exit 0')
    else:
        _stub(bindir, "curl", 'echo \'{"runs":[{"status": "success"}]}\'; exit 0')
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    res = subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    res.docker_log = log.read_text() if log.exists() else ""
    return res


# ── property 1: --volumes can never happen ───────────────────────────────────

@pytest.mark.parametrize("flag", ["-v", "--volumes"])
def test_volumes_flag_is_refused_and_nothing_runs(tmp_path, flag):
    res = _run(tmp_path, flag)
    assert res.returncode == 2
    assert "REFUSED" in res.stdout
    assert res.docker_log == "", "docker must not be invoked at all"


def test_down_never_passes_volumes_to_docker(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 0
    assert "--volumes" not in res.docker_log and " -v" not in res.docker_log


# ── property 2: no teardown while the wind tunnel is working ─────────────────

def test_blocked_when_a_backtest_job_is_running(tmp_path):
    res = _run(tmp_path, running=True)
    assert res.returncode == 3
    assert "BLOCKED" in res.stdout
    assert "down" not in res.docker_log, "must not stop anything while busy"


def test_force_overrides_the_in_flight_guard(tmp_path):
    res = _run(tmp_path, "--force", running=True)
    assert res.returncode == 0
    assert "down" in res.docker_log


def test_live_only_is_allowed_while_a_backtest_job_runs(tmp_path):
    """The stacks are independent: a running experiment must not stop you
    restarting the live trading stack."""
    res = _run(tmp_path, "live", running=True)
    assert res.returncode == 0
    # the trailing status listing DOES `ps` both stacks (read-only) — what must
    # not happen is a `down` aimed at the backtest stack
    downs = [ln for ln in res.docker_log.splitlines() if " down" in ln]
    assert downs and all("docker-compose.backtest.yml" not in ln for ln in downs)


# ── targeting + passthrough ──────────────────────────────────────────────────

def test_both_stacks_by_default(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 0
    assert "docker-compose.backtest.yml down" in res.docker_log
    # the live `down` is the bare form (no -f file argument)
    assert any(line.strip() == "compose down" for line in res.docker_log.splitlines())


def test_backtest_only_leaves_the_live_stack_alone(tmp_path):
    res = _run(tmp_path, "backtest")
    assert res.returncode == 0
    lines = [ln for ln in res.docker_log.splitlines() if " down" in ln]
    assert lines and all("docker-compose.backtest.yml" in ln for ln in lines)


def test_remove_orphans_is_passed_through(tmp_path):
    res = _run(tmp_path, "--remove-orphans")
    assert res.returncode == 0
    assert "--remove-orphans" in res.docker_log


def test_unknown_argument_is_rejected(tmp_path):
    res = _run(tmp_path, "--wipe-everything")
    assert res.returncode == 2
    assert res.docker_log == ""
