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


class TestTheImageCarriesItsRUNTIME_DEPENDENCIES:
    """The image must install what the code imports at RUN time.

    This class exists because of a real outage on the first operational night
    (2026-08-09): the image installed only `/shared/`, which declares pydantic
    and pyyaml and NO Postgres driver — every Stocker service had installed its
    own, so nothing in `shared/` ever pulled one in and Sentinel inherited the
    gap. Every feed command died on `ModuleNotFoundError: psycopg`.

    Three things conspired to hide it, and each is individually reasonable:

      * `store.connect` imports the driver LAZILY, so the package imports fine
        and the whole test suite passes without a driver present;
      * the image's default command is `status`, which deliberately touches no
        database, so the container looked healthy;
      * the seed was launched DETACHED, so it died into a log nobody was
        watching and was indistinguishable from a seed still running.

    A checkout-side "can I import psycopg" test would be worse than nothing: it
    passes whenever the developer's machine happens to have the driver, which is
    exactly the condition under which the image is broken and the test is green.
    So this asserts a property of the IMAGE SPEC instead.
    """

    def test_the_dockerfile_installs_a_POSTGRES_DRIVER(self):
        body = DOCKERFILE.read_text()
        installs = "\n".join(l for l in body.splitlines()
                             if "pip install" in l)
        assert "psycopg" in installs, (
            "Dockerfile.sentinel installs no Postgres driver. `shared/` does "
            "not declare one, so every feed command will die on "
            "ModuleNotFoundError at its first connection — including a detached "
            "feed-seed, which fails silently and looks like a running seed.")

    def test_shared_still_does_not_declare_the_driver(self):
        """The reason the assertion above cannot be relaxed. If `shared/` ever
        DOES declare a driver this test fails, and whoever changed it gets to
        decide deliberately whether the explicit install is now redundant —
        rather than discovering the coupling by removing it."""
        deps = (ROOT / "shared" / "pyproject.toml").read_text()
        assert "psycopg" not in deps, (
            "shared/ now declares a Postgres driver; re-evaluate whether "
            "Dockerfile.sentinel still needs its explicit install")

    def test_every_LAZY_driver_import_is_covered_by_the_image(self):
        """Generalises past psycopg. `store.connect` names its drivers in an
        import that only runs when a database is touched, so the set of things
        the image must carry is not visible to any import graph."""
        src = (ROOT / "sentinel" / "feed" / "store.py").read_text()
        named = {n for n in ("psycopg", "psycopg2") if f"import {n}" in src}
        assert named, "store.py names no driver — this test needs updating"
        installs = DOCKERFILE.read_text()
        assert any(n in installs for n in named), (
            f"store.py can import {sorted(named)} but the image installs none "
            f"of them")


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
