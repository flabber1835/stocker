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


#: Modules that satisfy each other, so installing ONE is enough.
#: `store.connect` prefers psycopg3 and accepts psycopg2 — pinning both would
#: put a driver in the image that is never imported.
_ALTERNATIVES = {"psycopg": {"psycopg", "psycopg2"},
                 "psycopg2": {"psycopg", "psycopg2"}}

_LOCAL_ROOTS = {"sentinel", "stock_strategy_shared"}


def _module_file(mod: str) -> Path | None:
    p = mod.replace(".", "/")
    for cand in (ROOT / f"{p}.py", ROOT / p / "__init__.py",
                 ROOT / "shared" / f"{p}.py", ROOT / "shared" / p / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _reachable_third_party() -> dict[str, set[str]]:
    """Third-party modules reachable from Sentinel's entry points.

    AST rather than importing: an import-based walk would need every dependency
    already installed, which is precisely the condition being tested. It also
    walks the FULL tree of each module, so an import nested inside a function —
    how every one of these dependencies is written — is found exactly like a
    top-level one.

    Follows local imports into `shared/`, because `shared/` is copied into the
    image and Sentinel reaches the broker adapter through it. It deliberately
    does NOT scan all of `shared/`: most of that package is retired Stocker
    code Sentinel never executes, and requiring pandas/sqlalchemy/redis in this
    image would be requiring the retired platform.
    """
    import ast
    import sys
    from collections import deque

    std = set(sys.stdlib_module_names)
    out: dict[str, set[str]] = {}
    seen: set[str] = set()

    queue: deque[str] = deque()
    for p in (ROOT / "sentinel").rglob("*.py"):
        rel = p.relative_to(ROOT).with_suffix("")
        queue.append(str(rel).replace("/", ".").removesuffix(".__init__"))

    while queue:
        mod = queue.popleft()
        if mod in seen:
            continue
        seen.add(mod)
        f = _module_file(mod)
        if f is None:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:                                # pragma: no cover
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in _LOCAL_ROOTS:
                    queue.append(name)
                elif root not in std:
                    out.setdefault(root, set()).add(
                        f"{f.relative_to(ROOT)}:{node.lineno}")
    return out


def _pip_installs(dockerfile: Path) -> str:
    """Every `pip install` line, with `\\` continuations joined first.

    A line-based filter misses a package on the second line of a wrapped
    install, and reports a dependency as missing when it is present — which is
    how this test failed the moment the install list grew past one line. The
    guard has to read the Dockerfile the way Docker does.
    """
    text = dockerfile.read_text().replace("\\\n", " ")
    return "\n".join(l for l in text.splitlines() if "pip install" in l)


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

    def test_EVERY_reachable_third_party_import_is_installed(self):
        """Walk Sentinel's real import graph and require the image to carry it.

        The general form of the bug, and it had to be general: the first version
        of this test asserted "psycopg is installed", which was true and still
        missed `httpx` an hour later. EVERY dependency this image needs is
        imported lazily — that is the deliberate design that keeps the package
        testable — so no top-level import list and no import-time failure will
        ever reveal them. Only walking the graph does.

        httpx is the case that shows why this matters beyond tonight: it is
        reachable from `feed/sharadar.py` AND from `broker/base.py`, so the
        missing dependency would have surfaced first as a failed corpus fetch
        and second as a failed `establish-ownership` — during a liquidation.
        """
        deps = _reachable_third_party()
        assert deps, "the walk found nothing — it is broken, not the image"
        installs = _pip_installs(DOCKERFILE)
        shared_declares = (ROOT / "shared" / "pyproject.toml").read_text()

        missing = []
        for mod, sites in sorted(deps.items()):
            group = _ALTERNATIVES.get(mod, {mod})
            if any(g in installs or g in shared_declares for g in group):
                continue
            missing.append(f"{mod} (imported at {sorted(sites)[0]})")
        assert not missing, (
            "Dockerfile.sentinel does not install: " + ", ".join(missing) +
            ". These are imported LAZILY, so the image builds clean, `status` "
            "works, and the command that needs them dies at its first call — "
            "silently, if it was launched detached.")

    def test_shared_still_does_not_declare_the_driver(self):
        """The reason the assertion above cannot be relaxed. If `shared/` ever
        DOES declare a driver this test fails, and whoever changed it gets to
        decide deliberately whether the explicit install is now redundant —
        rather than discovering the coupling by removing it."""
        deps = (ROOT / "shared" / "pyproject.toml").read_text()
        assert "psycopg" not in deps, (
            "shared/ now declares a Postgres driver; re-evaluate whether "
            "Dockerfile.sentinel still needs its explicit install")

    def test_the_walk_actually_reaches_the_BROKER(self):
        """The walk is only worth anything if it covers the code paths that run
        LATEST. `establish-ownership` is the last thing to be exercised and the
        most expensive to get wrong, so assert the traversal reaches the broker
        adapter rather than stopping inside `sentinel/`."""
        deps = _reachable_third_party()
        sites = {s for v in deps.values() for s in v}
        assert any("broker/base.py" in s for s in sites), (
            "the import walk never reached the broker adapter, so it cannot "
            "vouch for the liquidation path")


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
