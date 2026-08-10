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
import re
import shutil
import subprocess
import sys
import pathlib
from pathlib import Path

import pytest

#: The repository being INSPECTED. In a checkout that is the checkout. Inside
#: the certified test image the runtime code is deliberately NOT copied onto
#: sys.path — pytest must import `/app/sentinel`, not a fresh copy — so the
#: repo lives at a path that is never importable and is named here instead.
ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
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
    """Everything the image installs, wherever the names are actually written.

    Two ways the reading has been wrong, both of which reported a present
    dependency as missing:

    ```text
    line-based filtering    missed a package on the second line of a wrapped
                            install. Fixed by joining `\\` continuations, the
                            way Docker reads it.
    reading only the RUN    the install moved to `-r requirements.txt` when the
                            lines               pins became exact, so the names
                            left the Dockerfile entirely and every dependency
                            read as absent.
    ```

    Both are the same mistake — inferring what an image contains from one
    convenient surface — so this follows the `-r` to the file and reads that
    too.
    """
    text = dockerfile.read_text().replace("\\\n", " ")
    parts = [l for l in text.splitlines() if "pip install" in l]
    for line in list(parts):
        for token in re.findall(r"-r\s+(\S+)", line):
            # The path is the IMAGE's (`/tmp/req/requirements.txt`). Resolved by
            # BASENAME against the repo rather than by matching the COPY
            # destination exactly: the copy is a GLOB into a directory, because
            # requirements.lock does not exist until the first real build and
            # `COPY` fails on a missing source. Matching literal destinations
            # would silently find nothing again.
            # Trailing shell punctuation: the install now sits inside an
            # `if ... fi` block, so the token arrives as `...requirements.txt;`.
            name = Path(token.strip(";&|\"'")).name
            for cand in ROOT.rglob(name):
                if cand.is_file():
                    parts.append(cand.read_text())
    return "\n".join(parts)


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
            # A GLOB source is resolved rather than failed on: the pin file and
            # the lock are copied with one wildcard because the lock does not
            # exist until the first real build.
            if any(ch in src for ch in "*?["):
                matches = sorted(ROOT.glob(src))
                if not matches:
                    pytest.fail(f"Dockerfile.sentinel COPYs {src!r}, which "
                                f"matches nothing")
                for m in matches:
                    tgt = tmp_path / dst.strip("/") / m.name
                    tgt.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(m, tgt)
                continue
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


# ── every COPY source must survive .dockerignore ─────────────────────────────

class TestTheBuildContextCarriesWhatTheDockerfilesCOPY:
    """`.dockerignore` excluded `tests/`, and `Dockerfile.sentinel-test` — whose
    entire purpose is to run the suite INSIDE the certified image — died at

        COPY failed: file not found in build context: stat tests/

    after installing PostgreSQL, pytest and SQLAlchemy. A .dockerignore applies
    to the whole CONTEXT, so hiding a directory hides it from every Dockerfile
    built from this root, including the one that must have it.

    Nothing caught it earlier because the image had never been built: this
    sandbox has a Docker client and no daemon, and review passes ran the suite
    on the host. So the check is static — it reads what the Dockerfiles ask for
    and what the ignore file removes, and needs neither.

    The matcher below implements a deliberate SUBSET of Docker's pattern rules:
    exact names, directory prefixes, and `**/` globs, which is everything this
    repo's ignore file uses. It errs toward reporting a path as EXCLUDED, so it
    cannot go quiet by failing to understand a pattern.
    """

    IGNORE = ROOT / ".dockerignore"

    @staticmethod
    def copy_sources() -> list[tuple[Path, str]]:
        """(dockerfile, source) for every COPY that reads the build context."""
        out = []
        for df in sorted(ROOT.glob("Dockerfile*")) + \
                sorted(ROOT.glob("services/*/Dockerfile")):
            for raw in df.read_text().splitlines():
                line = raw.strip()
                if not line.upper().startswith("COPY "):
                    continue
                parts = line.split()[1:]
                # `COPY --from=<stage>` reads another IMAGE, not the context.
                if any(p.startswith("--from=") for p in parts):
                    continue
                parts = [p for p in parts if not p.startswith("--")]
                for src in parts[:-1]:            # last token is the destination
                    if "$" in src:                # ARG-substituted; not static
                        continue
                    out.append((df, src))
        return out

    def excluded_by(self, path: str) -> str | None:
        """The .dockerignore pattern that removes `path`, if any."""
        import fnmatch
        norm = path.rstrip("/").lstrip("./")
        for raw in self.IGNORE.read_text().splitlines():
            pat = raw.strip()
            if not pat or pat.startswith("#") or pat.startswith("!"):
                continue
            p = pat.rstrip("/")
            if p == norm or norm.startswith(p + "/"):
                return pat
            if fnmatch.fnmatch(norm, p) or fnmatch.fnmatch(norm, p + "/*"):
                return pat
        return None

    def test_there_are_copies_to_check(self):
        """Guard the guard: a parser that silently found nothing would pass.

        The floor is low because this runs in TWO layouts. A checkout has ~27
        Dockerfiles; the certified test image copies only the Sentinel ones into
        /work/repo, and a skip in there is a certification failure — so the
        assertion has to be true in both rather than opting out of one."""
        srcs = self.copy_sources()
        assert len(srcs) >= 8, srcs
        assert any(s == "tests/" for _, s in srcs), (
            "Dockerfile.sentinel-test should COPY tests/ — if that changed, "
            "this whole class needs re-pointing")

    def test_a_full_checkout_covers_the_SERVICE_dockerfiles_too(self):
        """Where the host runs, the sweep must be the wide one.

        Stated as a property of the layout rather than a skip: either the
        service tree is present and every one of its Dockerfiles was swept, or
        this is the image, where that tree is deliberately absent."""
        if not (ROOT / "services").is_dir():
            assert os.environ.get("SENTINEL_IN_IMAGE") == "1", (
                "no services/ tree and not the certified image — the sweep is "
                "narrower than the checkout it is meant to cover")
            return
        seen = {df for df, _ in self.copy_sources()}
        for df in ROOT.glob("services/*/Dockerfile"):
            assert df in seen, df

    def test_no_dockerfile_copies_an_ignored_path(self):
        broken = [(str(df.relative_to(ROOT)), src, self.excluded_by(src))
                  for df, src in self.copy_sources()
                  if self.excluded_by(src)]
        assert not broken, (
            "these COPY sources are removed from the build context by "
            f".dockerignore, so the build fails at that line: {broken}")

    def test_the_context_is_still_pruned(self):
        """The fix is not "delete .dockerignore".

        Un-excluding tests/ is safe only because no Dockerfile does a broad
        `COPY . .`; the file still has work to do on .git and caches."""
        body = self.IGNORE.read_text()
        for pat in (".git", "**/__pycache__", "artifacts/"):
            assert pat in body

    def test_no_dockerfile_copies_the_whole_context(self):
        """The premise the fix rests on.

        If one ever did, every un-excluded directory would land inside that
        image, and `tests/` would be shipping in a service image."""
        offenders = [str(df.relative_to(ROOT))
                     for df, src in self.copy_sources()
                     if src in (".", "./")]
        assert not offenders, offenders


class TestNoRepoFileIsReadThroughROOT:
    """The suite runs in TWO layouts, and one of them is the one that counts.

    In a checkout `parents[2]` is the repository. Inside the certified image it
    is /work — tests, an importable backtester copy, tools, and repo/ — while
    the repo SOURCES sit at /work/repo. So `ROOT / "scripts" / "sentinel-certify.sh"`
    reads fine on a developer host and raises FileNotFoundError in the image.

    Not hypothetical: step 5 failed with 85 of them, every one a path that
    resolves on the host. The earlier host-side simulation missed it because it
    overrode SENTINEL_REPO_ROOT only — ROOT still pointed at the real checkout,
    so exactly the broken constants kept working. The simulation now rebuilds
    /work itself.

    Both sides of the rule are read out of Dockerfile.sentinel-test, so neither
    can drift from what is actually copied. Two exemptions, both principled:
    modules whose own ROOT is the env-based repo root are already correct by
    construction, and `sys.path` inserts add an import path rather than opening
    a file — a nonexistent entry there is inert.
    """

    @staticmethod
    def _dests(prefix: str) -> set[str]:
        import re
        out = set()
        for line in (ROOT / "Dockerfile.sentinel-test").read_text().splitlines():
            m = re.match(rf"^COPY\s+(\S+)\s+{prefix}(\S*)", line.strip())
            if m:
                d = m.group(2).strip("/")
                out.add(d or pathlib.PurePosixPath(m.group(1).strip("/")).name)
        return {d for d in out if d}

    def repo_dests(self) -> set[str]:
        """Paths that live under /work/repo — must be read through REPO."""
        return self._dests("/work/repo/")

    def work_dests(self) -> set[str]:
        """Paths that live directly under /work — ROOT is correct for these."""
        return {d for d in self._dests("/work/") if not d.startswith("repo")}

    def test_both_sides_of_the_rule_are_populated(self):
        assert {"scripts", "sentinel", "shared"} <= self.repo_dests()
        assert any(d.startswith("services/backtester") or d == "tests"
                   for d in self.work_dests()), self.work_dests()

    def test_no_test_module_reads_a_repo_file_through_ROOT(self):
        import re
        repo, work = self.repo_dests(), self.work_dests()
        tests_dir = pathlib.Path(__file__).resolve().parent
        offenders = []
        for f in sorted(tests_dir.glob("*.py")):
            body = f.read_text()
            # Modules whose ROOT already IS the repo root are correct as written.
            if re.search(r"^ROOT = Path\(os\.environ", body, re.M):
                continue
            for i, line in enumerate(body.splitlines(), 1):
                if "sys.path" in line:
                    continue
                m = re.search(r'ROOT / "([^"]+)"(?: / "([^"]+)")?', line)
                if not m:
                    continue
                # Only actual filesystem ACCESS, or a constant that will be
                # used for one. `str(ROOT / "shared")` appended to sys.path is
                # neither, and flagging it teaches people to mute the guard.
                touches = any(k in line for k in
                              (".read_text(", ".exists(", ".rglob(", ".glob(",
                               ".is_dir(", ".is_file(", "open("))
                assigns = re.match(r"\s*[A-Z][A-Z_0-9]* = ", line) is not None
                if not (touches or assigns):
                    continue
                rel = "/".join(x for x in m.groups() if x)
                if any(rel == w or rel.startswith(w + "/") or w.startswith(rel + "/")
                       for w in work):
                    continue                      # genuinely under /work
                if any(rel == r or rel.startswith(r + "/") or r.startswith(rel + "/")
                       for r in repo):
                    offenders.append(f"{f.name}:{i}: {line.strip()}")
        assert not offenders, (
            "these read a file the image places under /work/repo, but through "
            "ROOT (=/work in the image), so they raise FileNotFoundError "
            f"there: {offenders}")


class TestEveryBinaryTheSuiteShellsOutToIsInstalled:
    """A missing binary is a FAILURE in this image, never a skip.

    `git` was not installed, so the manifest test that drives
    `sentinel_manifest.py` against a repository dirty by construction raised
    FileNotFoundError at step 5 — after eight minutes of suite — while passing
    on every host, where git is simply present.

    Same shape as the PostgreSQL binaries the image already installs: the test
    image is a lens on the artefact, and a lens missing a tool reports on
    something it could not see. Checked statically so a new `subprocess.run`
    fails here rather than 500 seconds into the certified run."""

    #: Interpreters and helpers that are guaranteed by construction.
    EXEMPT = {"python", "python3", "pytest", "pip"}

    @staticmethod
    def apt_packages() -> set[str]:
        body = (ROOT / "Dockerfile.sentinel-test").read_text()
        i = body.index("apt-get install")
        chunk = body[i:body.index("rm -rf", i)]
        return {tok for tok in chunk.replace("\\", " ").split()
                if tok not in {"apt-get", "install", "-y",
                               "--no-install-recommends", "&&"}}

    def invoked(self) -> set[str]:
        import re
        out = set()
        for f in sorted(pathlib.Path(__file__).resolve().parent.glob("*.py")):
            for m in re.finditer(r'subprocess\.run\(\s*\[\s*"([a-zA-Z0-9_.-]+)"',
                                 f.read_text()):
                out.add(m.group(1))
        return out - self.EXEMPT

    def test_the_parser_sees_the_install_line(self):
        pkgs = self.apt_packages()
        assert "postgresql" in pkgs, pkgs

    def test_every_invoked_binary_is_installed(self):
        missing = sorted(b for b in self.invoked() if b not in self.apt_packages())
        assert not missing, (
            "the suite shells out to these and the certified test image does "
            f"not install them, so they FAIL there rather than skip: {missing}")
