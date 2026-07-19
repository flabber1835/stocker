"""scripts/deploy.sh — the NAS deploy wrapper that makes the 'dirty
strategies/ tree blocks git pull' trap impossible to hit by hand.

Each test builds a throwaway git repo (with a bare 'origin') containing a copy
of the real script, then exercises the four contract points:
  - clean tree → rebase + push succeed, exit 0
  - dirty strategies file that byte-matches an applied/ artifact → auto
    mirror-commit, pushed to origin
  - dirty strategies file matching NO artifact (stray manual edit) → abort,
    nothing committed
  - dirty TRACKED file outside strategies/ → abort (would break the rebase)
  - refuses to run off main
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check,
                          capture_output=True, text=True)


def _run_deploy(repo, *services, env=None):
    import os
    full_env = {**os.environ, "DEPLOY_BACKOFF": "0", **(env or {})}
    return subprocess.run(["bash", str(repo / "scripts" / "deploy.sh"), *services],
                          cwd=repo, capture_output=True, text=True, env=full_env)


@pytest.fixture
def repo(tmp_path):
    """A working clone with a bare origin, seeded with a strategy file and the
    real deploy script (artifacts/ gitignored, mirroring production)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                   check=True, capture_output=True)
    work = tmp_path / "nas"
    subprocess.run(["git", "clone", str(origin), str(work)],
                   check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    _git(work, "checkout", "-b", "main", check=False)

    (work / "strategies").mkdir()
    (work / "strategies" / "active.yaml").write_text("strategy_id: v1\nmax_positions: 30\n")
    (work / "scripts").mkdir()
    shutil.copy(SCRIPT, work / "scripts" / "deploy.sh")
    (work / ".gitignore").write_text("artifacts/\n")
    (work / "docker-compose.yml").write_text("services: {}\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "-u", "origin", "main")

    (work / "artifacts" / "config" / "applied").mkdir(parents=True)
    return work


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _origin_head(repo):
    return _git(repo, "ls-remote", "origin", "main").stdout.split()[0]


def test_clean_tree_rebases_and_pushes(repo):
    r = _run_deploy(repo)
    assert r.returncode == 0, r.stderr
    assert "no services passed" in r.stdout
    assert _head(repo) == _origin_head(repo)


def test_applied_config_is_auto_mirrored_and_pushed(repo):
    new_yaml = "strategy_id: v1\nmax_positions: 25\n"
    (repo / "strategies" / "active.yaml").write_text(new_yaml)
    # the Apply endpoint archives the byte-canonical copy
    (repo / "artifacts" / "config" / "applied" / "20260718T105800_active.yaml").write_text(new_yaml)

    r = _run_deploy(repo)
    assert r.returncode == 0, r.stderr
    assert "mirroring 'strategies/active.yaml'" in r.stdout
    # committed, clean tree, and origin has it
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    log = _git(repo, "log", "-1", "--format=%s").stdout
    assert "mirror applied config change" in log
    assert _head(repo) == _origin_head(repo)


def test_stray_manual_edit_aborts_without_commit(repo):
    (repo / "strategies" / "active.yaml").write_text("strategy_id: hacked\n")
    before = _head(repo)
    r = _run_deploy(repo)
    assert r.returncode != 0
    assert "byte-matches NO artifact" in r.stderr
    assert _head(repo) == before
    assert "strategies/active.yaml" in _git(repo, "status", "--porcelain").stdout


def test_dirty_tracked_file_outside_strategies_aborts(repo):
    (repo / "docker-compose.yml").write_text("services: {changed: {}}\n")
    r = _run_deploy(repo)
    assert r.returncode != 0
    assert "outside strategies/" in r.stderr


def test_untracked_file_outside_strategies_is_tolerated(repo):
    (repo / "notes.txt").write_text("scratch\n")
    r = _run_deploy(repo)
    assert r.returncode == 0, r.stderr


def test_refuses_to_run_off_main(repo):
    _git(repo, "checkout", "-b", "feature")
    r = _run_deploy(repo)
    assert r.returncode != 0
    assert "main only" in r.stderr


def test_nothing_to_push_skips_push(repo):
    r = _run_deploy(repo)
    assert r.returncode == 0, r.stderr
    assert "nothing to push" in r.stdout


def test_push_failure_warns_but_does_not_block_deploy(repo, tmp_path):
    """A pull-only clone (no write credentials) must still deploy: the mirror
    commit stays local with a loud warning instead of hanging at a credential
    prompt or aborting before the build step."""
    new_yaml = "strategy_id: v1\nmax_positions: 20\n"
    (repo / "strategies" / "active.yaml").write_text(new_yaml)
    (repo / "artifacts" / "config" / "applied" / "20260719T083000_active.yaml").write_text(new_yaml)
    # fetch keeps working (origin url), but pushes go to a nonexistent path → fail fast
    _git(repo, "remote", "set-url", "--push", "origin", str(tmp_path / "no-such-remote.git"))

    r = _run_deploy(repo)
    assert r.returncode == 0, r.stderr
    assert "mirroring 'strategies/active.yaml'" in r.stdout
    assert "WARNING: git push failed" in r.stdout
    # the mirror commit exists locally even though origin never got it
    assert "mirror applied config change" in _git(repo, "log", "-1", "--format=%s").stdout
    assert _head(repo) != _origin_head(repo)
