"""The certification harness itself, checked where it can be.

Most of it needs Docker and a corpus. Two properties do not, and both are ones
the harness got WRONG in a way no green test would have shown:

```text
ORDERING     the missing-lock check sat at the END, as a yellow warning, after
             the truncate and the hours-long re-seed and immediately before
             "READY FOR THE REHEARSAL". An unlocked image would therefore have
             destroyed a corpus and spent hours rebuilding one, in order to
             produce evidence nobody could rebuild the environment for. A
             refusal that comes after the irreversible step is not a refusal.

NAMING       the record described the INPUTS to a build — base digest, package
             closure, source hashes — and never the built image. The image is
             the artefact being certified, and a container cannot discover its
             own image id, so the manifest has to be assembled on the host.
```

A shell script is awkward to test and that is not a reason to leave the ordering
unasserted: the cost of getting it wrong is a destroyed corpus.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
SCRIPT = REPO / "scripts" / "sentinel-certify.sh"
LOCKER = REPO / "scripts" / "sentinel-lock.sh"
MANIFEST = ROOT / "scripts" / "sentinel_manifest.py"


def text() -> str:
    return SCRIPT.read_text()


def line_of(needle: str) -> int:
    """First EXECUTABLE line mentioning `needle`.

    Comments are skipped deliberately: the header narrates the order, so a
    comment describing the truncate would otherwise satisfy an assertion about
    where the truncate happens — the test would then be reading the
    documentation rather than the script.
    """
    for i, line in enumerate(text().splitlines()):
        if needle in line and not line.lstrip().startswith("#"):
            return i
    raise AssertionError(f"{needle!r} not found in an executable line")


# ── 1. nothing destructive happens before the gates ──────────────────────────

class TestTheIrreversibleStepComesLAST:

    def test_the_LOCK_CHECK_precedes_the_TRUNCATE(self):
        assert line_of("the dependency closure must be LOCKED") \
            < line_of("TRUNCATE TABLE"), (
            "an unlocked image can wipe and re-seed the corpus, spending hours "
            "to produce evidence whose environment cannot be rebuilt")

    def test_a_MISSING_lock_EXITS_rather_than_warns(self):
        """The old version printed a yellow warning and then printed READY."""
        body = text()
        gate = body[body.index("the dependency closure must be LOCKED"):
                    body.index("2c/9")]
        assert "exit 1" in gate, "the missing-lock branch does not stop the run"
        assert "NOTHING HAS BEEN DESTROYED" in gate

    def test_the_IDENTITY_check_precedes_the_TRUNCATE(self):
        assert line_of("naming the environment") < line_of("TRUNCATE TABLE")

    def test_the_manifest_precedes_the_TRUNCATE(self):
        assert line_of("recording the artefact identity") \
            < line_of("TRUNCATE TABLE")

    def test_READY_is_printed_AFTER_the_work(self):
        lines = text().splitlines()
        ready = max(i for i, l in enumerate(lines)
                    if "READY FOR THE REHEARSAL" in l
                    and not l.lstrip().startswith("#"))
        assert ready > line_of("TRUNCATE TABLE")

    def test_the_truncate_still_FAILS_CLOSED(self):
        body = text()
        assert "to_regclass" in body, (
            "table existence must be handled inside the statement; a blanket "
            "`|| echo` reads a permission error as 'nothing to delete'")
        assert "ON_ERROR_STOP=1" in body

    def test_volumes_are_NEVER_removed(self):
        """The volume also holds the ownership log, and losing that makes the
        next start liquidate a Sentinel-owned book. Scoped to `docker compose
        down`: `psql -v ON_ERROR_STOP=1` is a different flag entirely, and a
        blanket search for ` -v ` would fail on it while proving nothing."""
        code = [l for l in text().splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        for l in code:
            assert "--volumes" not in l, l
            if "down" in l and "compose" in l.lower():
                assert " -v" not in l, l
        # And the reason survives in the file, because the next person to reach
        # for `down --volumes` will be reading comments, not this test.
        assert "never `down --volumes`" in text()


# ── 2. the closure comparison is AUTOMATED ───────────────────────────────────

class TestTheRebuildProvesTheLock:

    def test_the_hash_is_compared_across_runs_by_the_SCRIPT(self):
        body = text()
        assert "distributions_hash.prev" in body, (
            "the before/after comparison is left to the operator — an "
            "instruction people follow the first time")
        assert "the dependency closure MOVED across a rebuild" in body

    def test_a_MOVED_closure_is_a_failure_not_a_note(self):
        body = text()
        gate = body[body.index("distributions_hash.prev"):body.index("2c/9")]
        assert "fail " in gate

    def test_the_operator_is_told_NOT_to_edit_the_lock(self):
        """The one instruction that makes the comparison meaningful: a lock
        edited to match a rebuild records a wish, not what was installed."""
        assert "not edit the lock to agree" in text().lower()

    def test_the_locker_does_not_CLAIM_hashes_it_does_not_produce(self):
        """`--hashes` said in its header that it adds per-artefact digests and
        the implementation explicitly does not. Honest at runtime is not enough
        when the header is what someone reads before trusting the lock."""
        body = LOCKER.read_text()
        assert "PER-ARTEFACT HASHES ARE NOT IMPLEMENTED" in body
        assert "generate-hashes" in body


# ── 3. the artefact is NAMED ─────────────────────────────────────────────────

class TestTheManifestNamesTheBuiltIMAGE:

    def test_the_harness_invokes_it(self):
        assert "sentinel_manifest.py" in text()

    def test_it_records_the_runtime_image_ID(self):
        body = MANIFEST.read_text()
        assert "sentinel:latest" in body and "{{.Id}}" in body

    def test_it_records_REPO_DIGESTS_too(self):
        """Empty until pushed, and recorded as a field rather than omitted:
        deploying elsewhere must go by immutable registry digest, not by
        rebuilding and calling the rebuild equivalent."""
        assert "RepoDigests" in MANIFEST.read_text()

    def test_it_records_the_git_commit_AND_whether_the_tree_was_clean(self):
        body = MANIFEST.read_text()
        assert "git_tree_clean" in body and "rev-parse" in body

    @pytest.mark.parametrize("field", [
        "identity_hash", "distributions_hash", "requirements_lock_sha256",
        "sentinel_source_hash", "wealth_core_source_hash", "corpus_hash",
        "book_artifact_sha256", "rejection_audit_sha256", "rehearsal_hashes",
        "postgres_image", "sentinel_test_image"])
    def test_every_required_field_is_present(self, field):
        assert field in MANIFEST.read_text()

    def test_it_runs_and_produces_a_manifest(self, tmp_path):
        """End to end on a stand-in identity record. Docker may be absent, in
        which case the image fields come back null — which is the behaviour
        being asserted: a missing image is a FACT to record, not a reason to
        abandon the whole record."""
        art = tmp_path
        (art / "identity-env.json").write_text(json.dumps({
            "identity_hash": "ih",
            "environment": {"distributions_hash": "dh", "distributions_count": 3,
                            "sentinel_source": {"hash": "sh"},
                            "wealth_core_source": {"hash": "wh"},
                            "python": "3.12.13", "calendar_version": "XNYS/x"}}))
        rc = subprocess.run(
            [sys.executable, str(MANIFEST), str(art), "W", "locksha"],
            capture_output=True, text=True, cwd=str(ROOT))
        assert rc.returncode == 0, rc.stderr
        m = json.loads((art / "manifest-W.json").read_text())
        assert m["identity_hash"] == "ih"
        assert m["requirements_lock_sha256"] == "locksha"
        assert m["wealth_core_source_hash"] == "wh"
        assert "sentinel_runtime_image" in m

    def test_the_unfilled_fields_are_NULL_not_absent(self, tmp_path):
        """So an incomplete manifest is visibly incomplete rather than a
        differently shaped object a reader has to notice is missing something."""
        art = tmp_path
        (art / "identity-env.json").write_text(json.dumps({
            "identity_hash": "ih",
            "environment": {"distributions_hash": "dh", "distributions_count": 1,
                            "sentinel_source": {"hash": "sh"},
                            "wealth_core_source": {"hash": "wh"},
                            "python": "3.12.13", "calendar_version": "x"}}))
        subprocess.run([sys.executable, str(MANIFEST), str(art), "W", "l"],
                       capture_output=True, text=True, cwd=str(ROOT))
        m = json.loads((art / "manifest-W.json").read_text())
        for k in ("corpus_hash", "book_artifact_sha256", "rehearsal_hashes"):
            assert k in m and m[k] is None


# ── 4. evidence is retained where it can be found ────────────────────────────

class TestEvidenceIsRETAINED:

    def test_nothing_lands_in_tmp(self):
        assert "/tmp/sentinel" not in text(), (
            "/tmp is not certification evidence retention")

    def test_the_artifact_directory_is_used(self):
        assert 'ART="artifacts/sentinel"' in text()

    def test_the_book_is_described_as_EMITTED_not_typed(self):
        body = text()
        assert "book_artifact" in body
        assert "--assert-no-holdings" in body, (
            "the pre-seed run must state the empty book explicitly; supplying "
            "nothing means UNKNOWN")
