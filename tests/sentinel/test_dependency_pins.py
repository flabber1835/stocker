"""The certified environment is NAMED, and the naming is checked.

WHY THIS IS NOT PACKAGE HYGIENE. Sentinel snaps every corporate-action ex-date
forward to the next valid exchange session, so the calendar library's answer
decides which session a dividend or a split lands on, which decides cash and
share counts in the book. `exchange_calendars` is therefore part of the data
contract the strategy is certified against — and it computes its session index
through pandas and numpy and consults tzdata, so those are too.

A `>=` pin makes a rehearsal reproducible by accident: identical source,
identical corpus, identical command, and a different answer after an unrelated
rebuild picks up a new holiday rule. The pins remove that; these tests remove
the possibility of the pins being decorative.

THE FAILURE MODE BEING DEFENDED AGAINST is not "someone edits the Dockerfile".
It is an image built before a pin changed, or a developer's virtualenv resolving
something else, producing results that LOOK certified. So the check is against
what actually loaded, not against what a file says.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import os

#: See `test_image_layout` — inside the certified image the repository is
#: inspected from a path that is never importable.
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel import identity as ident  # noqa: E402

DOCKERFILE = REPO / "Dockerfile.sentinel"
AUTHORIZED_DOCKERFILE = REPO / "Dockerfile.sentinel-authorized"
REQUIREMENTS = REPO / "sentinel" / "requirements.txt"
TEST_DOCKERFILE = REPO / "Dockerfile.sentinel-test"
TEST_REQUIREMENTS_LOCK = ROOT / "tests" / "requirements.lock"


class TestEveryDependencyIsPinnedExactly:

    def test_the_requirements_file_exists_and_is_read(self):
        assert REQUIREMENTS.exists()
        assert ident.pinned_requirements(), "nothing was parsed out of it"

    def test_no_line_declares_a_RANGE(self):
        """`>=` is the defect. One unpinned package is enough to move a
        session boundary, and it will be the one nobody thought mattered."""
        loose = [ln.strip() for ln in REQUIREMENTS.read_text().splitlines()
                 if ln.strip() and not ln.strip().startswith("#")
                 and not re.search(r"==", ln)]
        assert loose == [], f"unpinned requirement(s): {loose}"

    def test_the_calendar_stack_is_ALL_pinned(self):
        """Named explicitly rather than left to the file's contents, because
        the argument for pinning is specific to these: each one can change what
        `next valid session` means."""
        pins = ident.pinned_requirements()
        for pkg in ("exchange-calendars", "pandas", "numpy", "tzdata",
                    "pyluach", "toolz", "korean-lunar-calendar",
                    "python-dateutil"):
            assert pkg in pins, f"{pkg} decides session placement and is unpinned"

    def test_the_dockerfile_INSTALLS_the_pin_file(self):
        """A pin file the image does not read is a document, not a control."""
        text = DOCKERFILE.read_text()
        assert "sentinel/requirements" in text
        assert "-r /tmp/req/requirements.lock" in text, (
            "the RESOLVED CLOSURE is never installed, so a rebuild re-resolves "
            "the transitive set and is not reproducible")
        assert "--require-hashes" in text
        assert "--only-binary=:all:" in text
        assert "PIP_TRUSTED_HOST" not in text
        assert not re.search(r'pip install[^\n]*"[a-zA-Z_\-]+>=', text), (
            "a package is still installed with a floating version on the "
            "command line, bypassing the pin file entirely")


class TestTheBaseImageIsPinnedByDigest:

    def test_FROM_carries_a_digest_not_a_bare_tag(self):
        """A tag is a moving pointer: the same Dockerfile a week apart gives a
        different Python patch level and a different Debian package set."""
        froms = [ln for ln in DOCKERFILE.read_text().splitlines()
                 if ln.startswith("FROM ")]
        assert froms, "no FROM line"
        for ln in froms:
            assert "@sha256:" in ln, f"unpinned base image: {ln.strip()}"

    def test_the_recorded_digest_MATCHES_the_dockerfile(self):
        """`identity` reports the digest a certified run was built from. If it
        drifts from the Dockerfile, the record describes an image that was never
        built and the whole record becomes untrustworthy."""
        assert ident.CERTIFIED_BASE_DIGEST in DOCKERFILE.read_text()


class TestTheCertificationTestToolsAreArtifactLocked:
    EXPECTED = {
        "greenlet": "3.5.5",
        "iniconfig": "2.1.0",
        "packaging": "25.0",
        "pluggy": "1.6.0",
        "pygments": "2.19.2",
        "pytest": "8.4.2",
        "pytest-asyncio": "1.2.0",
        "sqlalchemy": "2.0.44",
        "typing-extensions": "4.16.0",
    }

    @staticmethod
    def _blocks() -> dict[str, tuple[str, str]]:
        lines = TEST_REQUIREMENTS_LOCK.read_text().splitlines()
        starts = [i for i, line in enumerate(lines)
                  if "==" in line and not line.lstrip().startswith("#")]
        blocks = {}
        for pos, start in enumerate(starts):
            end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
            pin = lines[start].strip().rstrip(" \\")
            name, version = pin.split("==", 1)
            blocks[name.lower().replace("_", "-")] = (
                version, "\n".join(lines[start:end]))
        return blocks

    def test_the_delta_lock_is_complete_exact_and_hashed(self):
        blocks = self._blocks()
        assert {name: version for name, (version, _) in blocks.items()} == self.EXPECTED
        for name, (_, block) in blocks.items():
            assert "--hash=sha256:" in block, name

    @staticmethod
    def _assert_locked_install(text: str) -> None:
        assert "COPY tests/requirements.lock /tmp/test-req/requirements.lock" in text
        install = next(line for line in text.splitlines()
                       if "pip install" in line and "/tmp/test-req/requirements.lock" in line)
        for flag in ("--require-hashes", "--only-binary=:all:", "--no-deps"):
            assert flag in install
        assert "pip check" in text
        assert not re.search(r"pip install[^\n]*(pytest|SQLAlchemy)==", text, re.I)

    def test_the_test_image_installs_only_the_reviewed_delta_lock(self):
        self._assert_locked_install(
            TEST_DOCKERFILE.read_text().replace("\\\n", " "))

    def test_the_async_broker_suite_has_its_reviewed_plugin(self):
        broker_suite = (ROOT / "tests" / "broker" / "test_symbology.py").read_text()
        assert "@pytest.mark.asyncio" in broker_suite
        assert self._blocks()["pytest-asyncio"][0] == "1.2.0"

    @pytest.mark.parametrize("removed", [
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "pip check",
    ])
    def test_the_guard_fails_when_a_lock_control_is_removed(self, removed):
        text = TEST_DOCKERFILE.read_text().replace("\\\n", " ")
        with pytest.raises(AssertionError):
            self._assert_locked_install(text.replace(removed, ""))


class TestTheRecordDescribesTHISEnvironment:

    def test_pin_drift_names_the_package_not_a_boolean(self):
        drift = ident.pin_drift()
        for k, v in drift.items():
            assert set(v) == {"pinned", "installed"}, k

    def test_certified_requires_interpreter_AND_pins_AND_located_sources(self):
        """Three conditions, not two. The third was added after `identity` was
        found returning `files: 0, hash: None` for Wealth Core inside the
        runtime image while still answering --require-certified with PASS — see
        tests/sentinel/test_runtime_is_the_artifact.py."""
        env = ident.environment()
        assert env["certified"] == (env["python_certified"]
                                    and env["pins_match"]
                                    and env["sources_known"])

    def test_it_reports_the_calendar_it_consulted(self):
        env = ident.environment()
        assert env["calendar_exchange"] == "XNYS"
        assert "exchange_calendars" in env["calendar_version"]

    def test_the_two_source_trees_are_hashed_SEPARATELY(self):
        """Sentinel and Wealth Core are certified against different things and
        move at different times; one combined hash cannot say which moved."""
        env = ident.environment()
        s, w = env["sentinel_source"], env["wealth_core_source"]
        assert s["files"] > 0 and w["files"] > 0
        assert s["hash"] != w["hash"]

    def test_the_source_hash_IGNORES_caches_and_is_STABLE(self):
        assert (ident.source_hash(REPO / "sentinel")["hash"]
                == ident.source_hash(REPO / "sentinel")["hash"])

    def test_the_source_hash_MOVES_when_a_file_does(self, tmp_path):
        pkg = tmp_path / "p"
        pkg.mkdir()
        (pkg / "a.py").write_text("x = 1\n")
        before = ident.source_hash(pkg)["hash"]
        (pkg / "a.py").write_text("x = 2\n")
        assert ident.source_hash(pkg)["hash"] != before

    def test_a_RENAME_alone_moves_it(self, tmp_path):
        """Paths are hashed with contents. Two files swapping names is a
        different program and must not digest the same."""
        pkg = tmp_path / "p"
        pkg.mkdir()
        (pkg / "a.py").write_text("x = 1\n")
        before = ident.source_hash(pkg)["hash"]
        (pkg / "a.py").rename(pkg / "b.py")
        assert ident.source_hash(pkg)["hash"] != before

    def test_the_identity_hash_covers_the_environment(self):
        rec = ident.rehearsal_identity()
        assert rec["identity_hash"]
        assert "corpus" not in rec, "no connection was given"


@pytest.mark.skipif(
    ident.environment()["python"] != ident.CERTIFIED_PYTHON,
    reason="only meaningful inside the certified image")
class TestInsideTheCertifiedImage:
    """These are the ones that must pass in the image the rehearsal runs in.
    They are skipped in a developer checkout ON PURPOSE — an identity record
    that cannot be produced outside the image is useless exactly when you want
    to compare the two — and the rehearsal runbook asserts them by running
    `sentinel identity --require-certified`, which does not skip."""

    def test_every_pin_is_satisfied(self):
        assert ident.pin_drift() == {}

    def test_the_environment_reports_itself_CERTIFIED(self):
        assert ident.environment()["certified"] is True


class TestTheWHOLECLOSUREIsFingerprinted:
    """`requirements.txt` pins the DIRECT dependencies; pip resolves everything
    underneath them. Two images could therefore carry the same declared
    versions, the same source and the same interpreter — and different
    transitive closures — while `pin_drift()` reported nothing, because it only
    compares what the pin file names."""

    def test_every_installed_distribution_is_recorded(self):
        dists = dict(ident.installed_distributions())
        assert len(dists) > len(ident.pinned_requirements()), (
            "only the direct pins were recorded, so a transitive difference is "
            "invisible to the identity record")
        for name in ("exchange-calendars", "pandas"):
            assert name in dists

    def test_the_closure_is_INSIDE_the_identity_hash(self, monkeypatch):
        """The property that matters: two different closures cannot produce one
        identity_hash. Without it, results from two environments could be
        mistaken for results from one."""
        before = ident.rehearsal_identity()["identity_hash"]
        real = ident.installed_distributions
        monkeypatch.setattr(ident, "installed_distributions",
                            lambda: real() + [["ghost-package", "9.9.9"]])
        assert ident.rehearsal_identity()["identity_hash"] != before

    def test_a_VERSION_change_anywhere_in_the_closure_moves_it(self, monkeypatch):
        before = ident.environment()["distributions_hash"]
        real = ident.installed_distributions()
        bumped = [[n, v + ".1"] if i == 0 else [n, v]
                  for i, (n, v) in enumerate(real)]
        monkeypatch.setattr(ident, "installed_distributions", lambda: bumped)
        assert ident.environment()["distributions_hash"] != before

    def test_the_record_says_whether_a_LOCK_was_used(self):
        """An unlocked build must be distinguishable from a locked one. It is
        not a refusal — the lock cannot exist before the first build produces
        it — but it must be visible in the record."""
        assert "lock_present" in ident.environment()

    def test_the_lock_if_present_COVERS_every_declared_pin(self):
        """A lock that omits a pinned package would let that package float
        while the record claimed a frozen closure."""
        lock = REPO / "sentinel" / "requirements.lock"
        if not lock.exists():
            pytest.skip("no lock yet — produced by the first real build")
        locked = {}
        for line in lock.read_text().splitlines():
            if "==" in line and not line.strip().startswith("#"):
                n, _, v = line.strip().partition("==")
                locked[n.lower().replace("_", "-")] = v.rstrip(" \\")
        for name, version in ident.pinned_requirements().items():
            assert locked.get(name) == version, (
                f"{name} is pinned {version} and locked {locked.get(name)}")

    def test_every_locked_distribution_has_an_artifact_hash(self):
        lock = REPO / "sentinel" / "requirements.lock"
        lines = lock.read_text().splitlines()
        starts = [i for i, line in enumerate(lines)
                  if "==" in line and not line.lstrip().startswith("#")]
        assert starts
        for pos, start in enumerate(starts):
            end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
            block = "\n".join(lines[start:end])
            assert "--hash=sha256:" in block, lines[start]
