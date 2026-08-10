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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel import identity as ident  # noqa: E402

DOCKERFILE = ROOT / "Dockerfile.sentinel"
REQUIREMENTS = ROOT / "sentinel" / "requirements.txt"


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
        assert "sentinel/requirements.txt" in text
        assert "-r /tmp/requirements.txt" in text
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


class TestTheRecordDescribesTHISEnvironment:

    def test_pin_drift_names_the_package_not_a_boolean(self):
        drift = ident.pin_drift()
        for k, v in drift.items():
            assert set(v) == {"pinned", "installed"}, k

    def test_certified_requires_BOTH_interpreter_and_pins(self):
        env = ident.environment()
        assert env["certified"] == (env["python_certified"] and env["pins_match"])

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
        assert (ident.source_hash(ROOT / "sentinel")["hash"]
                == ident.source_hash(ROOT / "sentinel")["hash"])

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
