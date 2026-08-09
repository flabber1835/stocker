"""Sentinel's IMAGE, checked without Docker.

Same bug class the service smoke test exists for: code that imports fine from the
checkout and dies inside the image because the layout differs. Sentinel is run as
`python -m sentinel` from WORKDIR /app with `sentinel/` copied in and the repo
absent — so any module reaching for a repo-relative path works here and fails
there, at the moment it is liquidating an account.

Two deployment properties are asserted alongside it, because both are safety
claims made in comments and comments do not fail builds:

  * the image does not build FROM stocker-base — an image that pulls in the
    retired platform is not a retirement;
  * the ownership log path is backed by a VOLUME — losing that file makes the
    next start liquidate a Sentinel-owned book.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile.sentinel"
COMPOSE = ROOT / "docker-compose.sentinel.yml"


def _copy_directives(dockerfile: Path) -> list[tuple[str, str]]:
    out = []
    for line in dockerfile.read_text().splitlines():
        line = line.strip()
        if not line.upper().startswith("COPY "):
            continue
        parts = line.split()[1:]
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


class TestTheImageLayout:
    def test_sentinel_runs_with_the_repo_ABSENT(self, tmp_path):
        """Reconstruct the image's filesystem and run the real entrypoint.

        A fresh interpreter, not an import in this process: pytest's module cache
        would hide exactly the failure being hunted.
        """
        app = tmp_path / "app"          # the image's /app
        app.mkdir()
        for src, dst in _copy_directives(DOCKERFILE):
            source = ROOT / src.rstrip("/")
            if not source.exists():
                pytest.fail(f"Dockerfile.sentinel COPYs {src!r}, which does not exist")
            target = (app / "sentinel") if dst.rstrip("/").endswith("sentinel") \
                else (tmp_path / dst.strip("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, target)

        state = tmp_path / "state"
        env = {
            **os.environ,
            # `shared/` is pip-installed in the image; PYTHONPATH is the
            # equivalent here. Note the REPO ROOT is deliberately NOT on it.
            "PYTHONPATH": str(ROOT / "shared"),
            "SENTINEL_STATE_DIR": str(state),
            "ALPACA_API_KEY": "",
            "ALPACA_SECRET_KEY": "",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        }
        proc = subprocess.run(
            [sys.executable, "-m", "sentinel", "status"],
            cwd=app, env=env, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, (
            f"`python -m sentinel status` failed under the image layout:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
        assert json.loads(proc.stdout)["state"] == "UNINITIALIZED"

    def test_the_default_command_does_not_TRADE(self):
        """A restart policy must not be able to trigger a liquidation. The image's
        CMD is the read-only view; the handover is an explicit `run`.

        DIRECTIVES only — the first version scanned the whole file and tripped on
        the word appearing in a comment, which would have made the guard
        unmaintainable the moment anyone documented the command it guards.
        """
        directives = [
            l.strip() for l in DOCKERFILE.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        cmd = [l for l in directives if l.upper().startswith(("CMD ", "ENTRYPOINT "))]
        assert 'CMD ["status"]' in cmd
        assert not any("establish-ownership" in l for l in cmd), (
            "the image's default command must not liquidate an account")


class TestRetirementProperties:
    def test_the_image_does_not_build_FROM_stocker_base(self):
        froms = [l.split()[1] for l in DOCKERFILE.read_text().splitlines()
                 if l.strip().upper().startswith("FROM ")]
        assert froms, "Dockerfile.sentinel has no FROM"
        assert not any("stocker-base" in f for f in froms), (
            "Sentinel must not inherit the retired platform's image")

    def test_no_stocker_SERVICE_is_imported_by_sentinel(self):
        """Components are carried forward; services are not. `services/...` in an
        import is the retirement being violated in the one way that compiles."""
        offenders = []
        for py in (ROOT / "sentinel").rglob("*.py"):
            for n, line in enumerate(py.read_text().splitlines(), 1):
                s = line.strip()
                if s.startswith(("import ", "from ")) and (
                        "services." in s or "services/" in s):
                    offenders.append(f"{py.relative_to(ROOT)}:{n}: {s}")
        assert not offenders, "sentinel/ imports a retired Stocker service:\n" + \
            "\n".join(offenders)


@pytest.fixture(scope="module")
def compose():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(COMPOSE.read_text())


class TestComposeSafety:
    def test_the_ownership_log_is_on_a_NAMED_VOLUME(self, compose):
        """The single most safety-critical byte Sentinel writes. In the image's
        ephemeral layer it vanishes on recreation, and the next start liquidates
        a Sentinel-owned book."""
        svc = compose["services"]["sentinel"]
        state_dir = svc["environment"]["SENTINEL_STATE_DIR"]
        mounts = [m.split(":") for m in svc["volumes"]]
        named = [src for src, dst, *_ in mounts if dst == state_dir]
        assert named, f"nothing is mounted at {state_dir}"
        assert named[0] in (compose.get("volumes") or {}), (
            f"{named[0]} is not a declared named volume")

    def test_it_has_its_OWN_compose_project(self, compose):
        """A shared project means `down --remove-orphans` on either side can evict
        the other's containers — the accident `name: stocker-bt` exists to stop."""
        assert compose["name"] == "sentinel"

    def test_up_does_not_start_a_liquidation(self, compose):
        assert "cli" in compose["services"]["sentinel"].get("profiles", [])

    def test_the_default_endpoint_is_PAPER(self, compose):
        assert "paper-api.alpaca.markets" in \
            compose["services"]["sentinel"]["environment"]["ALPACA_BASE_URL"]
