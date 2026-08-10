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
        assert "the dependency closure MOVED against" in body

    def test_a_MOVED_closure_is_a_failure_not_a_note(self):
        body = text()
        gate = body[body.index("BASELINE_KIND"):body.index("2c/9")]
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


# ── 5. the lock bootstrap has no sequencing hole ─────────────────────────────

class TestTheBootstrapBindsTheLockToTheIMAGE:
    """`--verify-only` does not rebuild. So a check that only asks "does a lock
    file exist?" can pass against the ORIGINAL UNLOCKED image the moment a lock
    appears in the checkout — proving the operator ran the generator, not that
    anything was built from its output."""

    def test_identity_reports_the_lock_INSIDE_the_image(self):
        from sentinel import identity as ident
        assert "image_lock_sha256" in ident.environment()

    def test_the_image_lock_is_read_from_the_BUILD_not_the_checkout(self):
        src = (ROOT / "sentinel" / "identity.py").read_text()
        assert "/tmp/req" in src, (
            "the lock hash is read from the working tree, which says nothing "
            "about the image")

    def test_the_harness_REFUSES_an_image_with_no_lock(self):
        body = text()
        assert "the image carries NO lock file" in body
        assert 'if [ -z "${IMAGE_LOCK}" ]' in body

    def test_the_harness_REFUSES_a_MISMATCHED_lock(self):
        assert "built from a DIFFERENT lock than the checkout holds" in text()

    def test_the_bootstrap_closure_is_recorded_BEFORE_the_exit(self):
        """Without this the first unlocked build leaves nothing behind, and the
        locked rebuild has no earlier value to compare against — so the very
        comparison the bootstrap exists to perform is skipped on the one run
        that needed it."""
        body = text()
        lo = body.index("if [ ! -f sentinel/requirements.lock ]")
        gate = body[lo:body.index("exit 1", lo)]
        assert '> "${BOOT}"' in gate, (
            "the unlocked build exits without recording its closure, so the "
            "locked rebuild has nothing to be compared against")

    def test_the_bootstrap_instructions_do_NOT_say_verify_only(self):
        """--verify-only skips the build, so following it would check a lock in
        the checkout against an image that never consumed one."""
        body = text()
        lo = body.index("NO DEPENDENCY LOCK")
        gate = body[lo:body.index("exit 1", lo)]
        assert "--verify-only" not in gate or "does NOT rebuild" in gate

    def test_the_locked_rebuild_is_compared_against_the_BOOTSTRAP(self):
        body = text()
        assert "the unlocked bootstrap build" in body
        assert "MOVED against" in body

    def test_a_proven_bootstrap_is_RETIRED(self):
        """Once the locked rebuild reproduces it, later runs must compare
        against the last CERTIFIED run — not forever against a build from
        before the lock existed, which would refuse every legitimate future
        dependency change for the wrong reason."""
        assert "${BOOT}.proven" in text()


# ── 6. the Postgres image is NAMED, and mandatory ────────────────────────────

class TestThePostgresImageCannotBeNull:
    """It PRODUCES the corpus being certified. On a clean machine the bare
    `postgres:16` tag resolved to nothing and certification continued; on a
    machine with some other local `postgres:16` it would have recorded an
    unrelated server."""

    def test_the_ref_comes_from_COMPOSE_not_a_bare_tag(self):
        body = text()
        assert "PG_REF" in body and "docker-compose.sentinel.yml" in body

    def test_the_pinned_image_is_RESOLVED_before_the_manifest(self):
        assert line_of("docker pull") < line_of("TRUNCATE TABLE")

    def test_the_manifest_is_run_with_require_images(self):
        assert "--require-images" in text()

    def test_require_images_makes_a_MISSING_image_non_zero(self, tmp_path):
        (tmp_path / "identity-env.json").write_text(json.dumps({
            "identity_hash": "ih",
            "environment": {"distributions_hash": "dh", "distributions_count": 1,
                            "sentinel_source": {"hash": "sh"},
                            "wealth_core_source": {"hash": "wh"},
                            "python": "3.12.13", "calendar_version": "x"}}))
        r = subprocess.run(
            [sys.executable, str(MANIFEST), str(tmp_path), "W", "l",
             "--postgres-ref", "postgres:definitely-not-pulled",
             "--require-images"],
            capture_output=True, text=True, cwd=str(ROOT))
        assert r.returncode == 1, r.stdout
        assert "REFUSED" in r.stdout

    def test_it_still_WRITES_the_manifest_when_refusing(self, tmp_path):
        """So the operator sees which field was missing rather than being told
        a file could not be produced."""
        (tmp_path / "identity-env.json").write_text(json.dumps({
            "identity_hash": "ih",
            "environment": {"distributions_hash": "dh", "distributions_count": 1,
                            "sentinel_source": {"hash": "sh"},
                            "wealth_core_source": {"hash": "wh"},
                            "python": "3.12.13", "calendar_version": "x"}}))
        subprocess.run(
            [sys.executable, str(MANIFEST), str(tmp_path), "W", "l",
             "--postgres-ref", "postgres:nope", "--require-images"],
            capture_output=True, text=True, cwd=str(ROOT))
        assert (tmp_path / "manifest-W.json").exists()

    def test_a_DIRTY_tree_also_refuses(self, tmp_path):
        body = MANIFEST.read_text()
        assert "the working tree is DIRTY" in body
        assert "REQUIRED_IMAGES" in body


# ── 7. the post-rehearsal handoff is automated ───────────────────────────────

class TestTheFinalizerClosesTheLoop:
    FINAL = ROOT / "scripts" / "sentinel-finalize-rehearsal.sh"

    def test_it_exists_and_is_referenced_by_the_harness(self):
        assert self.FINAL.exists()
        assert "sentinel-finalize-rehearsal.sh" in text()

    def test_it_EXTRACTS_the_book_rather_than_asking_for_one(self):
        body = self.FINAL.read_text()
        assert "book_artifact" in body
        assert "bt_wealth_core_runs" in body, (
            "the book is still expected to arrive as a file someone produced")

    def test_it_REFUSES_a_summary_with_no_book(self):
        """An older engine produced the run — one that had the RunResult and
        discarded it. Writing the book by hand is exactly what this removes."""
        assert "carries NO book_artifact" in self.FINAL.read_text()

    def test_it_checks_the_WINDOW_of_the_extracted_book(self):
        """A rehearsal over a different span omits every name held outside it."""
        body = self.FINAL.read_text()
        assert "the rehearsal covered" in body and "Refused" in body

    def test_it_reruns_the_audit_with_the_REAL_book(self):
        body = self.FINAL.read_text()
        assert "rejection-audit" in body and "--book" in body
        code = [l for l in body.splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        assert not [l for l in code if "--assert-no-holdings" in l], (
            "the finalizer must not re-assert an empty book — that claim was "
            "true before the bootstrap and is false of the traded interval")

    def test_it_completes_the_manifest_and_FAILS_when_incomplete(self):
        body = self.FINAL.read_text()
        assert "rehearsal_hashes" in body
        assert "BLOCKED" in body

    def test_it_tells_the_operator_to_read_SETTLEMENT_before_performance(self):
        body = self.FINAL.read_text()
        assert "settlement counters" in body
        assert body.index("settlement counters") < body.index("only then, performance")

    def test_the_BOOK_IS_MOUNTED_into_the_container(self):
        """The sentinel service's only volume is
        `sentinel_state:/var/lib/sentinel` — no /work, no artifacts mount — so
        a host path handed to it as `--book` simply does not exist inside. On
        the real machine step 2 would have reached the container and found
        nothing."""
        body = self.FINAL.read_text()
        assert "certified-book.json:ro" in body, (
            "the book is passed by a path the container cannot see")
        assert not [l for l in body.splitlines()
                    if "--book" in l and "/work/" in l], (
            "a /work path survives; that directory exists only in the TEST "
            "image, not in the runtime service")

    def test_only_ONE_file_is_mounted_not_the_repository(self):
        """A repo mount would also put the source the runtime image must not
        import back onto its filesystem."""
        body = self.FINAL.read_text()
        mounts = [l for l in body.splitlines() if "-v " in l and "compose" in l]
        for m in mounts:
            assert "book.json" in m, m

    def test_it_AUTHENTICATES_the_run_not_only_its_book(self):
        """The book's window rules out the wrong date range and nothing else. A
        different chain rehearsal over exactly the same dates under altered
        configuration would pass a window check, and the manifest would close
        around its hashes."""
        body = self.FINAL.read_text()
        for claim in ("status", "chain_rehearsal", "start_date", "end_date",
                      "parity_hashes"):
            assert claim in body, claim
        assert "mode is" in body and "not 'chain_rehearsal'" in body

    def test_it_records_the_SPEC_the_run_actually_used(self):
        assert "rehearsal_spec" in self.FINAL.read_text()

    def test_it_names_the_BT_ENGINE_image(self):
        """`sentinel:latest` produces the Sentinel corpus; the three-year Wealth
        Core rehearsal is executed by bt-engine, and that image belongs in the
        chain just as much."""
        body = self.FINAL.read_text()
        assert "bt_engine_image" in body and "BT_ENGINE_IMAGE" in body


class TestTheFinalizerGATESRatherThanNarrates:
    """`REHEARSAL FINALIZED` meant evidence exists, not that it passed. The
    conditions were recorded, and then the operator was told what to read."""

    FINAL = ROOT / "scripts" / "sentinel-finalize-rehearsal.sh"

    @pytest.mark.parametrize("condition", [
        "state_hash_matches", "ledger_hash_matches", "final_cash_matches",
        "unreconciled_episodes", "unexplained_episodes", "residual",
        "cash_coverage_fraction"])
    def test_every_certification_condition_is_CHECKED(self, condition):
        assert condition in self.FINAL.read_text(), (
            f"{condition} is not evaluated, so a run violating it still prints "
            f"green")

    def test_a_MISSING_condition_is_a_failure_not_a_pass(self):
        """`unreconciled_episodes` absent and `unreconciled_episodes == []` are
        different statements; only one of them is a reconciliation."""
        body = self.FINAL.read_text()
        assert "is MISSING — the" in body

    def test_the_evidence_is_STILL_written_when_blocked(self):
        body = self.FINAL.read_text()
        assert body.index("mp.write_text") < body.index("failures = [])".rstrip(")")), (
            "the manifest must be written before the gate runs, so a blocked "
            "run still leaves the operator something to read")

    def test_a_nonzero_RESIDUAL_blocks(self):
        assert "not 0 — at" in self.FINAL.read_text()

    def test_the_failure_message_is_BLOCKED_not_finalized(self):
        body = self.FINAL.read_text()
        assert "is not a certified rehearsal" in body


class TestTheLockScriptPointsAtTheREBUILD:

    def test_it_no_longer_tells_the_operator_to_use_verify_only(self):
        """--verify-only skips the build, which is the step the lock is proved
        by. The harness now rejects a stale image on its own, so this could no
        longer false-green — and an instruction that contradicts the corrected
        bootstrap is still worth removing."""
        body = LOCKER.read_text()
        instr = [l for l in body.splitlines()
                 if "--verify-only" in l and "scripts/sentinel-certify.sh" in l
                 and "NOT" not in l]
        assert not instr, instr
        assert "--keep-corpus" in body

