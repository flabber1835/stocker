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
        # `ownership` rather than `state`: the binding is the authority now.
        assert json.loads(proc.stdout)["ownership"] == "UNKNOWN"

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
            group = (_ALTERNATIVES.get(mod, {mod}) |
                     {mod.replace("_", "-"), mod.replace("-", "_")})
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
        assert any("broker/base.py" in s.replace("\\", "/") for s in sites), (
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
    exact names, directory prefixes, `**/` globs, and `!` exceptions, which is
    everything this repo's ignore file uses. It errs toward reporting a path as
    EXCLUDED, so it cannot go quiet by failing to understand a pattern.
    """

    IGNORE = ROOT / ".dockerignore"

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        """Does `pattern` cover `path`, as a file or as a parent directory?"""
        import fnmatch
        p = pattern.rstrip("/")
        if p == path or path.startswith(p + "/"):
            return True
        return fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p + "/*")

    @staticmethod
    def copy_sources() -> list[tuple[Path, str]]:
        """(dockerfile, source) for every COPY that reads the build context."""
        out = []
        for df in sorted(ROOT.glob("Dockerfile*")) + \
                sorted(ROOT.glob("services/*/Dockerfile*")):
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
        """The .dockerignore pattern that removes `path`, if any.

        LAST MATCH WINS, which is Docker's rule and not git's. `docs/` followed
        by `!docs/sentinel-handoff/00_README/` excludes the tree and re-includes
        that subdirectory; the earlier version of this method skipped every `!`
        line, so it read the negated path as excluded and failed a build that
        works. (Docker re-includes beneath an excluded parent — the archiver
        keeps descending into a skipped directory whenever any exception pattern
        exists. Git does not, and conflating the two is why the `!` lines look
        wrong to a reader who knows .gitignore.)

        A negation NESTED under the queried path counts as well: `COPY docs/`
        with only `!docs/x/` re-included still succeeds, because the context
        carries `docs/x`. Reporting the partial case as broken would be a false
        failure of exactly the kind that gets a guard deleted.
        """
        norm = path.rstrip("/").lstrip("./")
        hit: str | None = None
        for raw in self.IGNORE.read_text().splitlines():
            pat = raw.strip()
            if not pat or pat.startswith("#"):
                continue
            if pat.startswith("!"):
                body = pat[1:].strip().rstrip("/")
                if self._matches(body, norm) or body.startswith(norm + "/"):
                    hit = None                     # re-included, wholly or partly
                continue
            if self._matches(pat, norm):
                hit = pat
        return hit

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
        for df in ROOT.glob("services/*/Dockerfile*"):
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

    def test_the_matcher_understands_re_inclusion(self):
        """Guard the guard, on the half that can only fail SILENTLY.

        `excluded_by` returning None too eagerly turns the class above into a
        test that passes for every input. Both directions are pinned against
        the live ignore file: `docs/` excludes, and the negations beneath it
        re-include — which is Docker's rule and NOT git's, so a reviewer who
        knows .gitignore would reasonably expect the opposite.

        The question this method answers is narrow and worth stating: "would a
        COPY of this path FAIL?" — not "is every byte under it present". So a
        directory with anything re-included beneath it is reported as fine,
        because Docker copies the surviving subtree and the build succeeds.
        """
        # Re-included, exactly and beneath.
        assert self.excluded_by("docs/sentinel-handoff/00_README/") is None
        assert self.excluded_by("docs/sentinel-handoff/00_README/"
                                "FROZEN_SENTINEL_1P1_RULE.json") is None
        # Parents of a re-inclusion survive as a COPY source, partially filled.
        assert self.excluded_by("docs/") is None
        assert self.excluded_by("docs/sentinel-handoff/") is None
        # But a leaf with NO negation beneath it is still gone. Without these
        # the three above are equally satisfied by "any `!` line disables the
        # pattern", which is the way this method fails silently.
        assert self.excluded_by("docs/wealth-core-v1.md") == "docs/"
        assert self.excluded_by("docs/sentinel-handoff/09_GAPS/") == "docs/"
        assert self.excluded_by("artifacts/run-1.json") == "artifacts/"

    def test_no_dockerfile_copies_the_whole_context(self):
        """The premise the fix rests on.

        If one ever did, every un-excluded directory would land inside that
        image, and `tests/` would be shipping in a service image."""
        offenders = [str(df.relative_to(ROOT))
                     for df, src in self.copy_sources()
                     if src in (".", "./")]
        assert not offenders, offenders


# ── every repo path the code NAMES must be in the image that reads it ────────

#: The suite runs under TWO roots and this walk has to know which is which.
#: On a host both are the checkout. In the certified image `sentinel/` is
#: inspected at /work/repo (SENTINEL_REPO_ROOT) while `tests/` lives at /work —
#: the split `TestNoRepoFileIsReadThroughROOT` documents.
#:
#: Getting this wrong is not hypothetical: the first version walked
#: `ROOT / "tests/sentinel"`, which in the image is /work/repo/tests/sentinel
#: and does not exist. The early-out returned [], the coverage assertions went
#: vacuous, and only `test_the_extractor_still_finds_the_known_ones` caught it —
#: seventeen minutes into the certified run, which is precisely the job that
#: guard was written for.
PKG_ROOT = ROOT                                       # holds sentinel/
SUITE_ROOT = Path(__file__).resolve().parents[2]      # holds tests/


class TestTheCleanCertificationImageInspectionBundle:
    """The image carries every input used by its own certification tests.

    Host tests previously passed because these files existed in the checkout;
    the clean image failed only after its expensive setup because `/work/repo`
    contained a smaller tree. Pin both halves of the deliberate split here.
    """

    REPO_INPUTS = {
        ".dockerignore",
        ".env.example",
        "Dockerfile.base",
        "Dockerfile.sentinel",
        "Dockerfile.sentinel-authorized",
        "Dockerfile.sentinel-test",
        "Makefile",
        "README.md",
        "docker-compose.backtest.yml",
        "docker-compose.sentinel-automation.yml",
        "docker-compose.sentinel-backup.yml",
        "docker-compose.sentinel.yml",
        "docs/main-review-remediation.md",
        "docs/sentinel-deployment.md",
        "docs/sentinel-paper-activation.md",
        "docs/sentinel-stage-4-automation.md",
        "deploy/sentinel-authorized-runtime-v1",
        "scripts/",
        "sentinel/",
        "shared/",
        "services/backtester/",
        "services/bt-data/",
        "services/bt-engine/",
        "tools/",
    }
    WORK_INPUTS = {
        "scripts/sentinel-measure.sh": "/work/scripts/sentinel-measure.sh",
        "scripts/sentinel_forward_run.py": "/work/scripts/sentinel_forward_run.py",
        "scripts/sentinel_test_run.py": "/work/scripts/sentinel_test_run.py",
        "services/backtester/": "/work/services/backtester/",
        "tests/": "/work/tests/",
        "tools/": "/work/tools/",
    }

    @staticmethod
    def _copy_pairs() -> set[tuple[str, str]]:
        pairs = set()
        for line in (ROOT / "Dockerfile.sentinel-test").read_text().splitlines():
            match = re.match(r"^COPY\s+(\S+)\s+(\S+)$", line.strip())
            if match:
                pairs.add(match.groups())
        return pairs

    def test_every_repository_inspection_input_is_copied_to_the_nonimportable_root(self):
        pairs = self._copy_pairs()
        missing = []
        for source in sorted(self.REPO_INPUTS):
            destination = "/work/repo/" + source
            if (source, destination) not in pairs:
                missing.append((source, destination))
        assert not missing, missing

    def test_runnable_suite_inputs_stay_on_the_work_root(self):
        pairs = self._copy_pairs()
        missing = [(source, destination)
                   for source, destination in self.WORK_INPUTS.items()
                   if (source, destination) not in pairs]
        assert not missing, missing
        for relative in (
            "tests/requirements.lock",
            "tests/sentinel/test_backup_contract.py",
            "tests/sentinel/test_operational_surface.py",
        ):
            assert (SUITE_ROOT / relative).is_file(), relative

    def test_the_inspected_docs_survive_the_pruned_build_context(self):
        ignored = (ROOT / ".dockerignore").read_text().splitlines()
        for path in ("docs/main-review-remediation.md",
                     "docs/sentinel-deployment.md",
                     "docs/sentinel-paper-activation.md"):
            assert f"!{path}" in ignored


def _repo_paths_named_by(tree_dir: str, base: Path) -> list[tuple[str, int, str, Path]]:
    """(file, line, path relative to `base`) for every repo file the code names.

    `base` is the root that `tree_dir` hangs off, and it is also what the
    resulting paths are relative to — so a tests module naming
    `ROOT / "docs" / ...` yields `docs/...` against /work, and the package
    naming the same thing yields `docs/...` against /work/repo. Both are then
    comparable to a Dockerfile COPY source, which is what they must be.

    Two extractors, because the code writes these two ways and either alone
    leaves a hole:

    ```text
    AST      module-level `X = Path(__file__).resolve().parents[N] / "a" / "b"`,
             following names already bound in the same module, so `RULE_PATH =
             _HANDOFF / "00_README" / "..."` resolves through `_HANDOFF`
    regex    inline `ROOT / "scripts" / "sentinel-certify.sh"` inside a function
    ```

    Both are conservative in the same direction: an expression they cannot
    resolve is DROPPED, never guessed. That makes this a lower bound on what
    the code reads, which is why `test_the_extractor_still_finds_the_known_ones`
    exists below — a lower bound of zero is a test that always passes.
    """
    import ast

    root = base / tree_dir
    if not root.is_dir():                              # narrower image layout
        return []

    def _resolve(node: ast.AST, f: Path, syms: dict[str, Path]) -> Path | None:
        """Evaluate a path expression to an ABSOLUTE path, or give up.

        Absolute rather than repo-relative throughout, because `.parent` and
        `parents[N]` are only meaningful against a real location. The first
        version carried repo-relative strings and got `HERE.parents[1]` wrong
        by one — it assumed every `parents[N]` hung off `Path(__file__)`, so a
        base that was already a directory resolved one level too deep and
        `conftest.ROOT` came out as `tests/`.
        """
        if isinstance(node, ast.Name):
            # `__file__` is a NAME, not a string constant. Reading it as one
            # made every `Path(__file__)` unresolvable and the whole walk
            # returned an empty set — which is precisely the vacuous pass
            # `test_the_extractor_still_finds_the_known_ones` is here to catch.
            return f if node.id == "__file__" else syms.get(node.id)
        if isinstance(node, ast.Attribute):
            base = _resolve(node.value, f, syms)
            if base is not None and node.attr == "parent":
                return base.parent
            return None
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                and node.value.attr == "parents" \
                and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, int):
            base = _resolve(node.value.value, f, syms)
            if base is None:
                return None
            for _ in range(node.slice.value + 1):
                base = base.parent
            return base
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = _resolve(node.left, f, syms)
            if left is not None and isinstance(node.right, ast.Constant) \
                    and isinstance(node.right.value, str):
                return left / node.right.value
            return None
        # `REPO = os.environ.get("SENTINEL_REPO_ROOT") or Path(...).parents[N]`
        # resolves to PKG_ROOT, not to the literal fallback. On a host the two
        # are the same directory. In the image they are NOT: the fallback is
        # /work and the env var says /work/repo, so taking the literal branch
        # reported `scripts/sentinel-certify.sh` and `sentinel/identity.py` as
        # missing — they are there, one level down.
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any("os.environ" in ast.unparse(v) for v in node.values):
                return PKG_ROOT
            for v in node.values:
                r = _resolve(v, f, syms)
                if r is not None:
                    return r
            return None
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "Path" \
                    and node.args:
                return _resolve(node.args[0], f, syms)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "resolve":
                return _resolve(node.func.value, f, syms)
        return None

    def _rel(p: Path):
        """(root, path-relative-to-it), or None if it escapes both.

        A single base is not enough: one MODULE can name paths under both
        roots. `tests/sentinel/test_certification_harness.py` reads
        `REPO / "scripts" / ...` (=/work/repo) on one line and
        `ROOT / "tools" / ...` (=/work) on another, and the coverage question
        differs — /work/repo/ COPY destinations for the first, /work/ for the
        second. PKG_ROOT is checked FIRST because /work/repo is itself under
        /work, so the other order would tag everything /work and relativise
        the repo paths as `repo/scripts/...`, matching no COPY source at all.
        """
        rp = p.resolve()
        for cand in (PKG_ROOT, SUITE_ROOT):
            try:
                return cand, rp.relative_to(cand).as_posix()
            except ValueError:
                continue
        return None

    #: Inline uses, resolved through the module's OWN bindings rather than
    #: assumed to hang off the repo root — `_HANDOFF / "00_README" / ...` is
    #: two levels down, and reading it as repo-relative invented a path that
    #: has never existed.
    inline = re.compile(
        r'\b([A-Z_][A-Z_0-9]*)\s*/\s*'
        r'"([\w.\-]+)"(?:\s*/\s*"([\w.\-]+)")?(?:\s*/\s*"([\w.\-]+)")?')

    out: list[tuple[str, int, str, Path]] = []
    for f in sorted(root.rglob("*.py")):
        body = f.read_text()
        rel_f = f.relative_to(base).as_posix()
        tree = ast.parse(body)
        syms: dict[str, Path] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name):
                p = _resolve(stmt.value, f, syms)
                if p is None:
                    continue
                syms[stmt.targets[0].id] = p
                hit = _rel(p)
                if hit is not None:
                    out.append((rel_f, stmt.lineno, hit[1], hit[0]))
        # Lines belonging to a STATEMENT that touches `sys.path`. An entry there
        # is an import path, not a file that gets opened, and a nonexistent one
        # is inert — `TestNoRepoFileIsReadThroughROOT` carves out the same
        # exemption. Computed per STATEMENT rather than per line, because
        # `conftest.py` writes it as
        #
        #     for p in (str(HERE), str(ROOT), str(ROOT / "shared")):
        #         if p not in sys.path:
        #             sys.path.insert(0, p)
        #
        # where the line naming the path contains no `sys.path` at all. A
        # line-level filter missed exactly that one.
        skip_lines: set[int] = set()
        for stmt in ast.walk(tree):
            if not isinstance(stmt, ast.stmt):
                continue
            if "sys.path" not in ast.unparse(stmt):
                continue
            end = getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
            skip_lines.update(range(stmt.lineno, end + 1))

        for i, line in enumerate(body.splitlines(), 1):
            if i in skip_lines:
                continue
            m = inline.search(line)
            # A name this module never bound to a path is somebody else's `/`.
            if not m or m.group(1) not in syms:
                continue
            # `assert not (REPO / ... ).exists()` is a deliberate assertion of
            # ABSENCE — `test_corpus_parity` pins that the SQLAlchemy-importing
            # parity tool stayed out of the runtime image. Naming a path in
            # order to require it gone is not reading it.
            if "assert not" in line:
                continue
            p = syms[m.group(1)]
            for seg in (g for g in m.groups()[1:] if g):
                p = p / seg
            hit = _rel(p)
            if hit is not None:
                out.append((rel_f, i, hit[1], hit[0]))
    # The roots themselves are not COPY sources and need no checking.
    return [(f, n, p, r) for f, n, p, r in out if p not in ("", ".", "./")]


class TestEveryRepoPathTheCodeREADS_IsCopiedIn:
    """`.dockerignore` said `docs/`, and nothing noticed for a week.

    `sentinel/controller/frozen_rule.py` LOADS the certified thresholds from
    `docs/sentinel-handoff/00_README/` and raises rather than falling back to
    transcribed constants — deliberately, because a Sentinel on unverified
    numbers is an uncertified strategy wearing a certified name. That made a
    documentation directory a RUNTIME dependency, and the ignore file had
    excluded documentation since long before the loader existed. Neither image
    copied it, so:

    ```text
    sentinel:latest       every controller call raises FrozenRuleMissing
    sentinel-test:latest  test_system_simulation binds CFG = frozen_rule.load()
                          at MODULE level -> collection error, ~40 tests never
                          run, and in that image a skip is already a failure
    ```

    `sentinel-certify.sh` would have found it at STEP 5 — after step 4's
    hours-long re-seed. Step 2b puts the dependency-closure check ahead of the
    first destructive step precisely because a refusal is only a refusal if it
    arrives before the irreversible thing; this restores that property for a
    dependency added after that script was written.

    The class above checks the OTHER direction — a COPY whose source is ignored
    — and passed throughout, because the failure here was an absence. Nobody
    copied `docs/`, so there was no COPY line to catch. Hence this: start from
    what the CODE names and require the image to carry it.
    """

    #: Every path the production image can read, as build-context sources.
    #: `sentinel/` runs from /app with the repo absent, so this set is the
    #: whole of its filesystem.
    @staticmethod
    def _copy_sources(dockerfile: str) -> list[str]:
        return [src.rstrip("/") for df, src in
                TestTheBuildContextCarriesWhatTheDockerfilesCOPY.copy_sources()
                if df.name == dockerfile]

    @staticmethod
    def _covered(rel: str, sources) -> bool:
        """A named path is carried when a COPY source IS it, CONTAINS it, or
        lies beneath it. The last case is `ROOT / "services"` against
        `COPY services/bt-data/`: partially present, and the callers that do
        that already branch on what exists."""
        rel = rel.rstrip("/")
        return any(rel == s or rel.startswith(s + "/") or s.startswith(rel + "/")
                   for s in sources)

    @classmethod
    def _uncovered(cls, named, sources, only_root=None) -> list[str]:
        """`only_root` restricts to paths belonging to one root, because the
        two roots have different COPY destination sets and mixing them was the
        bug: a `REPO / "scripts" / ...` read is satisfied by
        `COPY scripts/ /work/repo/scripts/` and says nothing about /work."""
        return [f"{f}:{line} reads {rel!r}"
                for f, line, rel, root in named
                if (only_root is None or root == only_root)
                and not cls._covered(rel, sources)]

    def test_the_extractor_still_finds_the_known_ones(self):
        """Guard the guard. Both assertions below are vacuous if the walk
        returns nothing, and an AST walk is exactly the sort of thing that
        quietly returns nothing after a refactor.

        Pinned to the four artefacts whose absence is a certification failure
        rather than to a count, so ordinary churn does not touch this."""
        pkg = {p for _, _, p, _ in _repo_paths_named_by("sentinel", PKG_ROOT)}
        assert "docs/sentinel-handoff/00_README/FROZEN_SENTINEL_1P1_RULE.json" in pkg
        assert "docs/sentinel-handoff/00_README/SHA256SUMS.txt" in pkg

        suite = {p for _, _, p, _ in
                 _repo_paths_named_by("tests/sentinel", SUITE_ROOT)}
        assert ("docs/sentinel-handoff/04_BREADTH_ORACLES/"
                "sentinel_1p1_exact_daily_with_breadth.csv") in suite
        assert ("docs/sentinel-handoff/02_SENTINEL_1P1_FROZEN_ORACLE/"
                "02_recovery_gate_flags.csv") in suite

    def test_the_RUNTIME_image_carries_every_path_sentinel_reads(self):
        bad = self._uncovered(_repo_paths_named_by("sentinel", PKG_ROOT),
                              self._copy_sources("Dockerfile.sentinel"))
        assert not bad, (
            "sentinel/ names these repo paths and Dockerfile.sentinel copies "
            "none of them, so they are absent from /app at run time: "
            + "; ".join(bad))

    @staticmethod
    def _dest_sources(prefix: str, *, exclude_prefix: str | None = None) -> list[str]:
        """COPY sources whose DESTINATION is under ``prefix``.

        A source may deliberately be copied to both the import-side ``/work``
        tree and the inspection-only ``/work/repo`` tree.  Classification is
        therefore by destination, never by deduplicating equal source names.
        """
        out = []
        for line in (ROOT / "Dockerfile.sentinel-test").read_text().splitlines():
            m = re.match(r"^COPY\s+(\S+)\s+(\S+)", line.strip())
            if (m and m.group(2).startswith(prefix)
                    and not (exclude_prefix
                             and m.group(2).startswith(exclude_prefix))):
                out.append(m.group(1).rstrip("/"))
        return out

    def test_the_TEST_image_carries_every_path_the_suite_reads(self):
        """Each root against ITS OWN destinations.

        `/work/repo` is checked first and excluded from the `/work` set,
        because /work/repo is physically inside /work — matching `COPY tests/
        /work/tests/` against a repo-rooted path would pass for the wrong
        reason."""
        named = _repo_paths_named_by("tests/sentinel", SUITE_ROOT)
        repo_side = self._dest_sources("/work/repo/")
        work_side = self._dest_sources(
            "/work/", exclude_prefix="/work/repo/")
        if PKG_ROOT == SUITE_ROOT:
            # A CHECKOUT. There is one tree, `_rel` tags everything with the
            # first root it matches, and the split carries no information — so
            # the only meaningful question is whether the path is copied at
            # all. Splitting anyway put `tests/` and `tools/` in the repo-side
            # bucket, where they are legitimately absent, and failed on a host
            # while passing in the image.
            bad = self._uncovered(named, repo_side + work_side)
        else:
            bad = (self._uncovered(named, work_side, only_root=SUITE_ROOT)
                   + self._uncovered(named, repo_side, only_root=PKG_ROOT))
        assert not bad, (
            "tests/sentinel names these repo paths and Dockerfile.sentinel-test "
            "copies none of them, so the certified run fails on them at step 5, "
            "after the re-seed: " + "; ".join(sorted(set(bad))))

    def test_the_runtime_paths_also_resolve_under_the_TEST_image_repo_root(self):
        """`SENTINEL_REPO_ROOT=/work/repo` and `sentinel/` is copied there for
        inspection, so the reconstruction in `test_sentinel_runs_with_the_repo_ABSENT`
        reads Dockerfile.sentinel's COPY sources out of /work/repo. A path
        present at /work but not /work/repo fails there and nowhere else."""
        repo_side = [src.rstrip("/") for line in
                     (ROOT / "Dockerfile.sentinel-test").read_text().splitlines()
                     for m in [re.match(r"^COPY\s+(\S+)\s+/work/repo/", line.strip())]
                     if m for src in [m.group(1)]]
        bad = self._uncovered(_repo_paths_named_by("sentinel", PKG_ROOT), repo_side)
        assert not bad, (
            "Dockerfile.sentinel-test does not mirror these under /work/repo, "
            "so the image-layout reconstruction cannot find them: " + "; ".join(bad))

    def test_every_named_path_actually_EXISTS(self):
        """The cheapest half, and it catches a different mistake: a COPY set
        that covers a path which is not there.

        Each tree is resolved against ITS OWN root. Checking both against ROOT
        was the second half of the same bug: in the image ROOT is /work/repo,
        so every path a tests module names — `tools/corpus_parity.py`,
        `services/backtester/app` — read as missing, because they live under
        /work. Two roots, and every use of them has to say which.

        `sentinel/requirements.lock` is exempt: it does not exist until the
        first real build.
        """
        missing = []
        for tree, base in (("sentinel", PKG_ROOT),
                           ("tests/sentinel", SUITE_ROOT)):
            for f, n, rel, root in _repo_paths_named_by(tree, base):
                if rel.endswith("requirements.lock"):
                    continue
                if not (root / rel).exists():
                    missing.append(f"{f}:{n} -> {rel} (under {root})")
        assert not missing, sorted(set(missing))


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
    #: `bash` and `sh` are Debian ESSENTIAL packages — present in every Debian
    #: derivative, not installable-away — so listing them in the apt line would
    #: be noise. That reasoning depends entirely on the base staying Debian,
    #: which `test_the_bash_exemption_still_has_its_PREMISE` pins.
    EXEMPT = {"python", "python3", "pytest", "pip", "bash", "sh"}

    def test_the_bash_exemption_still_has_its_PREMISE(self):
        """`bash -n <script>` is how the shell harnesses are syntax-checked, and
        it is exempted above on the grounds that Debian guarantees it. Move to
        Alpine or a distroless base and that guarantee is gone — busybox `sh` is
        not bash and `bash -n` becomes FileNotFoundError at step 5. So the
        exemption is only allowed to stand while the premise does."""
        base = [l.split()[1] for l in
                (ROOT / "Dockerfile.sentinel").read_text().splitlines()
                if l.strip().upper().startswith("FROM ")]
        assert base and all("-slim" in b or "-bookworm" in b or "debian" in b
                            for b in base), (
            f"the image no longer builds on a Debian base ({base}); bash and sh "
            "are no longer guaranteed and must be installed explicitly or "
            "removed from EXEMPT")

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
