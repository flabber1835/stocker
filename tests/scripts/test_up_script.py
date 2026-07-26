"""scripts/up.sh — the in-flight guard that was missing.

`down.sh` refused to tear the backtest stack down mid-job from day one. `up.sh`
had no such guard, and a deploy is the MORE common operation — so
`up.sh --build` was the one path that could silently destroy a running
experiment: bt-engine marks every `running` bt_sweeps row
'RESTART_ABORTED: engine restarted mid-sweep' on its OWN startup, so recreating
the container does not pause a sweep, it kills it. Three consecutive nightly
baselines were lost that way (2026-07-23/24/25) and the weekly review reported
the experiment lane as non-functional for a 4th week.

The live stack must still deploy in that situation — skipping the bt stack is not
a failure.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "up.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")


def _stub(dirpath: Path, name: str, body: str):
    p = dirpath / name
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _run(tmp_path, *args, running=False):
    """Run up.sh with docker + curl stubbed. `running` fakes an in-flight sweep."""
    tmp_path = Path(tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "docker.log"
    # `image inspect` must succeed so the stocker-base branch is skipped.
    _stub(bindir, "docker", f'echo "$@" >> "{log}"; exit 0')
    status = "running" if running else "success"
    _stub(bindir, "curl", f"echo '{{\"sweep\": {{\"status\": \"{status}\"}}}}'; exit 0")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    res = subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    res.docker_log = log.read_text() if log.exists() else ""
    return res


def _ups(docker_log: str) -> list[str]:
    return [ln for ln in docker_log.splitlines() if " up " in ln or ln.endswith(" up")]


# ── the guard ────────────────────────────────────────────────────────────────

def test_backtest_stack_is_not_recreated_while_a_sweep_runs(tmp_path):
    res = _run(tmp_path, "--build", running=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "SKIPPED" in res.stdout
    ups = _ups(res.docker_log)
    assert ups, "nothing was brought up at all"
    assert all("docker-compose.backtest.yml" not in ln for ln in ups), \
        "a running sweep was aborted by the deploy"


def test_live_stack_still_deploys_while_a_sweep_runs(tmp_path):
    """The whole point: a busy wind tunnel must not block a trading-stack fix."""
    res = _run(tmp_path, "--build", running=True)
    ups = _ups(res.docker_log)
    assert any("docker-compose.backtest.yml" not in ln and "--build" in ln for ln in ups), \
        "the live stack was skipped too"
    assert "live stack up" in res.stdout and "SKIPPED" in res.stdout


def test_force_overrides_the_guard(tmp_path):
    res = _run(tmp_path, "--build", "--force", running=True)
    assert res.returncode == 0
    ups = _ups(res.docker_log)
    assert any("docker-compose.backtest.yml" in ln for ln in ups)


def test_both_stacks_come_up_when_idle(tmp_path):
    res = _run(tmp_path, "--build")
    assert res.returncode == 0
    ups = _ups(res.docker_log)
    assert any("docker-compose.backtest.yml" in ln for ln in ups)
    assert any("docker-compose.backtest.yml" not in ln for ln in ups)
    assert "both stacks up" in res.stdout


def test_build_flag_is_passed_through(tmp_path):
    # Separate dirs: the stub docker APPENDS to one log per dir, so reusing
    # tmp_path would leak the first run's "--build" into the second assertion.
    assert "--build" in _run(tmp_path / "with", "--build").docker_log
    assert "--build" not in _run(tmp_path / "without").docker_log


def test_unknown_argument_is_rejected(tmp_path):
    res = _run(tmp_path, "--wipe")
    assert res.returncode == 2
    assert res.docker_log == ""


def test_up_and_down_share_the_same_liveness_probes(tmp_path):
    """If the two scripts checked different endpoints, one could believe the
    stack idle while the other saw it busy."""
    up, down = SCRIPT.read_text(), (ROOT / "scripts" / "down.sh").read_text()
    for probe in ("localhost:8030/runs/latest", "localhost:8031/sweeps/latest"):
        assert probe in up, f"up.sh does not probe {probe}"
        assert probe in down, f"down.sh does not probe {probe}"


# ── serial build fallback (NAS IO starvation) ──────────────────────────────

def test_serial_mode_exists_and_builds_one_image_at_a_time():
    """Compose hands all ~17 services to BuildKit at once. On the NAS that
    starves IO and dies with `DeadlineExceeded: context deadline exceeded` while
    a 400-byte .dockerignore takes 15 seconds — not a code error, and not
    obviously a resource one either. Serial finishes; parallel does not."""
    with open(os.path.join(ROOT, "scripts", "up.sh")) as f:
        up = f.read()
    assert "--serial" in up
    assert "build_serially" in up
    assert "config --services" in up, "serial mode must enumerate services itself"


def test_serial_mode_covers_both_stacks():
    with open(os.path.join(ROOT, "scripts", "up.sh")) as f:
        up = f.read()
    assert up.count("build_serially") >= 3, (
        "definition plus a call for each stack — a live-only serial mode leaves "
        "the backtest stack hitting the same wall")


def test_the_deadline_error_is_explained_in_the_failure_hint():
    """The message is opaque. Pointing at --serial where it appears saves the
    next person a diagnosis."""
    with open(os.path.join(ROOT, "scripts", "up.sh")) as f:
        up = f.read()
    assert "DeadlineExceeded" in up
