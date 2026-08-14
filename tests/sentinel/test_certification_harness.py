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

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.postgres import _EphemeralPostgres

from sentinel.feed import store as feed_store

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
SCRIPT = REPO / "scripts" / "sentinel-certify.sh"
LOCKER = REPO / "scripts" / "sentinel-lock.sh"
MANIFEST = REPO / "scripts" / "sentinel_manifest.py"
TEST_RUN_PRODUCER = REPO / "scripts" / "sentinel_test_run.py"


def manifest_module():
    spec = importlib.util.spec_from_file_location(
        "sentinel_manifest_under_test", MANIFEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def certification_test_run_module():
    spec = importlib.util.spec_from_file_location(
        "sentinel_test_run_under_test", TEST_RUN_PRODUCER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


RESET_TABLES = (
    "sentinel_bar_split_repairs",
    "sentinel_bars",
    "sentinel_spy_total_return",
    "sentinel_actions",
    "sentinel_universe",
    "sentinel_ingest_rejections",
    "sentinel_rejection_truncation",
    "sentinel_corpus_anomalies",
    "sentinel_corpus_publications",
    "sentinel_readiness_snapshots",
    "sentinel_sep_staging",
    "feed_ingest_runs",
)


def corpus_reset_sql() -> str:
    """Read the statement the production certification command actually runs."""
    body = text()
    reset_step = body.index('step "3/9  DISCARDING the corpus tables"')
    start = body.index("\nDO $$", reset_step) + 1
    end = body.index("\nSQL", start)
    return body[start:end]


@pytest.fixture(scope="module")
def certification_reset_pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001 -- unavailable binary skips this tier
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


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

    def test_the_current_feed_schema_resets_in_one_atomic_statement(
            self, certification_reset_pg):
        """Exercise the production DO block against PostgreSQL, not a parser.

        `sentinel_bar_split_repairs` references `sentinel_bars`. PostgreSQL
        rejects sequential TRUNCATEs even in one transaction and even when the
        child is empty, so the former loop stopped certification at step 3.
        Keeping a repair row here makes that FK load-bearing. The second half
        proves an unlisted future child fails closed without partially clearing
        the explicitly named corpus tables.
        """
        conn = feed_store.connect(certification_reset_pg.sync_dsn)
        try:
            feed_store.ensure_schema(conn)
            run_id = "00000000-0000-0000-0000-000000000001"
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE certification_reset_state "
                            "(marker TEXT PRIMARY KEY)")
                cur.execute("INSERT INTO certification_reset_state VALUES "
                            "('durable-state-must-survive')")
                cur.execute("INSERT INTO sentinel_bars (security_id, session, "
                            "ticker, close_unadjusted) VALUES "
                            "('SEC-1', '2026-08-12', 'ONE', 10)")
                cur.execute("INSERT INTO sentinel_bar_split_repairs "
                            "(security_id, session, split_ratio, "
                            "prior_split_ratio, last_written_run_id) VALUES "
                            f"('SEC-1', '2026-08-12', 2, 1, '{run_id}')")
                cur.execute("INSERT INTO sentinel_spy_total_return "
                            "(session, closeadj) VALUES ('2026-08-12', 100)")
                cur.execute("INSERT INTO sentinel_actions "
                            "(ticker, session, action) VALUES "
                            "('ONE', '2026-08-12', 'split')")
                cur.execute("INSERT INTO sentinel_universe "
                            "(permaticker, ticker, snapshot_date) VALUES "
                            "('SEC-1', 'ONE', '2026-08-12')")
                cur.execute("INSERT INTO sentinel_ingest_rejections "
                            "(ticker, session, reason) VALUES "
                            "('BAD', '2026-08-12', 'unresolved')")
                cur.execute("INSERT INTO sentinel_rejection_truncation "
                            "(run_id, chunk, window_start, window_end, retained, "
                            f"truncated) VALUES ('{run_id}', 'chunk', "
                            "'2026-08-12', '2026-08-12', 1, 1)")
                cur.execute("INSERT INTO sentinel_corpus_anomalies "
                            "(kind, ticker, session) VALUES "
                            "('TEST', 'ONE', '2026-08-12')")
                cur.execute("INSERT INTO sentinel_corpus_publications "
                            f"(run_id) VALUES ('{run_id}')")
                cur.execute("INSERT INTO sentinel_readiness_snapshots "
                            "(ready, checks_passed, checks_total) VALUES "
                            "(FALSE, 0, 1)")
                cur.execute("INSERT INTO sentinel_sep_staging "
                            "(run_id, chunk, session, ticker) VALUES "
                            f"('{run_id}', 'chunk', '2026-08-12', 'ONE')")
                cur.execute("INSERT INTO feed_ingest_runs (run_id, kind) "
                            f"VALUES ('{run_id}', 'seed')")
            conn.commit()

            reset_sql = corpus_reset_sql()
            executable = "\n".join(line.split("--", 1)[0]
                                     for line in reset_sql.splitlines())
            assert "CASCADE" not in executable.upper()
            assert executable.upper().count("TRUNCATE TABLE") == 1

            with conn.cursor() as cur:
                cur.execute(reset_sql)
            conn.commit()

            with conn.cursor() as cur:
                for table in RESET_TABLES:
                    cur.execute(f"SELECT count(*) FROM {table}")
                    assert cur.fetchone()[0] == 0, table
                cur.execute("SELECT marker FROM certification_reset_state")
                assert cur.fetchone()[0] == "durable-state-must-survive"

                # Simulate a later schema adding an unreviewed FK child. The
                # explicit reset must refuse it, not acquire CASCADE semantics.
                cur.execute("INSERT INTO sentinel_bars (security_id, session, "
                            "ticker, close_unadjusted) VALUES "
                            "('SEC-2', '2026-08-12', 'TWO', 20)")
                cur.execute("INSERT INTO sentinel_actions "
                            "(ticker, session, action) VALUES "
                            "('TWO', '2026-08-12', 'split')")
                cur.execute("CREATE TABLE unreviewed_feed_child ("
                            "security_id TEXT NOT NULL, session DATE NOT NULL, "
                            "FOREIGN KEY (security_id, session) REFERENCES "
                            "sentinel_bars (security_id, session))")
                cur.execute("INSERT INTO unreviewed_feed_child VALUES "
                            "('SEC-2', '2026-08-12')")
            conn.commit()

            with pytest.raises(Exception):  # driver-specific FK exception
                with conn.cursor() as cur:
                    cur.execute(reset_sql)
            conn.rollback()

            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM sentinel_bars")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT count(*) FROM sentinel_actions")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT count(*) FROM unreviewed_feed_child")
                assert cur.fetchone()[0] == 1
        finally:
            conn.close()


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

    def test_the_locker_generates_and_checks_artifact_hashes(self):
        body = LOCKER.read_text()
        assert "--generate-hashes" in body
        assert "--hash=sha256:" in body
        assert "--no-emit-trusted-host" in body


# ── 3. the artefact is NAMED ─────────────────────────────────────────────────

class TestTheManifestNamesTheBuiltIMAGE:

    def test_the_harness_invokes_it(self):
        assert "sentinel_manifest.py" in text()

    def test_it_records_the_runtime_image_ID(self):
        body = MANIFEST.read_text()
        assert "sentinel-authorized:latest" in body and "{{.Id}}" in body

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
        "postgres_image", "bt_data_image", "sentinel_test_image"])
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
        assert m["schema"] == "sentinel.certification_manifest/2"
        assert m["lifecycle"] == "FROZEN"

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
        for k in ("corpus_hash", "parity_generations",
                  *manifest_module().COMPLETION_FIELDS,
                  "last_finalization_attempt"):
            assert k in m and m[k] is None


class TestSourceBytesBindTheImage:

    def test_operator_activation_runbook_is_a_certification_input(self):
        module = manifest_module()
        sources = {Path(source).relative_to(ROOT).as_posix()
                   for source, _logical in
                   module._certification_input_spec(ROOT)}
        assert "docs/sentinel-paper-activation.md" in sources

    def test_overlay_hash_matches_docker_copy_semantics(self, tmp_path):
        module = manifest_module()
        base = tmp_path / "base"
        overlay = tmp_path / "overlay"
        (base / "live").mkdir(parents=True)
        overlay.mkdir()
        (base / "live" / "reader.py").write_text("old\n")
        (overlay / "reader.py").write_text("new\n")
        spec = [(base, ""), (overlay, "live")]
        digest = module.bundle_source_hash(spec, python_only=True)

        (base / "live" / "reader.py").write_text("shadowed bytes\n")
        assert module.bundle_source_hash(spec, python_only=True) == digest
        (overlay / "reader.py").write_text("changed final bytes\n")
        assert module.bundle_source_hash(spec, python_only=True) != digest

    def test_matching_revision_label_does_not_excuse_dirty_image_bytes(
            self, tmp_path, monkeypatch, capsys):
        module = manifest_module()
        commit = "a" * 40
        images = {
            key: {"ref": key, "id": "sha256:" + "b" * 64,
                  "source_revision": commit, "repo_digests": []}
            for key in module.REQUIRED_IMAGES
        }
        record = {
            "git_commit": commit,
            "git_tree_clean": True,
            "git_dirty_paths": [],
            **images,
            "checkout_source_hashes": {"sentinel": "clean"},
            "image_source_hashes": {"sentinel": "dirty"},
            "distributions_hash": "d" * 64,
            "requirements_lock_sha256": "l" * 64,
        }
        monkeypatch.setattr(module, "build", lambda *a, **k: record)
        rc = module.main([
            str(tmp_path), "W", "lock", "--require-images"])
        assert rc == 1
        assert "source differs between the clean checkout" in capsys.readouterr().out


class TestCertificationManifestLifecycle:

    @staticmethod
    def ready(module):
        return {
            "lifecycle": "READY_FOR_REHEARSAL",
            "verdict": None,
            "failures": [],
            "last_finalization_attempt": None,
            **{key: "stale" for key in module.COMPLETION_FIELDS},
        }

    def test_a_failed_attempt_retains_evidence_but_not_completion(self):
        module = manifest_module()
        manifest = self.ready(module)
        module.begin_finalization(manifest)
        assert manifest["lifecycle"] == "FINALIZING"
        assert all(manifest[key] is None for key in module.COMPLETION_FIELDS)

        attempt = {key: f"attempt-{key}"
                   for key in module.COMPLETION_FIELDS}
        module.finish_finalization(manifest, attempt, ["generation moved"])
        assert manifest["lifecycle"] == "BLOCKED"
        assert manifest["verdict"] == "BLOCKED"
        assert all(manifest[key] is None for key in module.COMPLETION_FIELDS)
        assert manifest["last_finalization_attempt"][
            "book_artifact_sha256"] == "attempt-book_artifact_sha256"
        assert manifest["failures"] == ["generation moved"]

        module.block_finalization(manifest, ["finalizer exited non-zero"])
        assert manifest["failures"] == [
            "generation moved", "finalizer exited non-zero"]
        assert manifest["last_finalization_attempt"][
            "book_artifact_sha256"] == "attempt-book_artifact_sha256"

    def test_interrupted_finalizing_state_is_restartable(self):
        module = manifest_module()
        manifest = self.ready(module)
        prior = {"book_artifact_sha256": "prior", "failures": ["prior"]}
        manifest["lifecycle"] = "FINALIZING"
        manifest["last_finalization_attempt"] = prior
        module.begin_finalization(manifest)
        assert manifest["lifecycle"] == "FINALIZING"
        assert manifest["last_finalization_attempt"] == prior
        assert all(manifest[key] is None for key in module.COMPLETION_FIELDS)

        attempt = {key: f"restart-{key}"
                   for key in module.COMPLETION_FIELDS}
        module.finish_finalization(manifest, attempt, [])
        assert manifest["lifecycle"] == "FINALIZED"
        assert manifest["last_finalization_attempt"][
            "book_artifact_sha256"] == "restart-book_artifact_sha256"
        assert manifest["failures"] == []

    def test_only_a_gate_clean_attempt_publishes_completion(self):
        module = manifest_module()
        manifest = self.ready(module)
        module.begin_finalization(manifest)
        attempt = {key: f"attempt-{key}"
                   for key in module.COMPLETION_FIELDS}
        module.finish_finalization(manifest, attempt, [])
        assert manifest["lifecycle"] == "FINALIZED"
        assert manifest["verdict"] == "PASS"
        assert manifest["failures"] == []
        assert all(manifest[key] == attempt[key]
                   for key in module.COMPLETION_FIELDS)

    def test_missing_settlement_evidence_cannot_finalize(self):
        module = manifest_module()
        manifest = self.ready(module)
        module.begin_finalization(manifest)
        attempt = {key: f"attempt-{key}"
                   for key in module.COMPLETION_FIELDS}
        attempt["settlement_counters"] = None
        module.finish_finalization(manifest, attempt, [])
        assert manifest["lifecycle"] == "BLOCKED"
        assert manifest["settlement_counters"] is None
        assert "attempted settlement_counters is null" in manifest["failures"]

    def test_shell_exit_is_derived_from_the_authoritative_lifecycle(self):
        body = (REPO / "scripts" /
                "sentinel-finalize-rehearsal.sh").read_text()
        assert 'authoritative_failures = list(m.get("failures") or [])' in body
        assert 'm.get("lifecycle") == "FINALIZED"' in body
        assert 'm.get("verdict") == "PASS"' in body
        assert "sys.exit(1 if failures else 0)" not in body

    @pytest.mark.parametrize("mutation", [
        "run_generation", "source_mode", "run_status", "sentinel_generation",
        "identity", "corpus_hash"])
    def test_exact_parity_and_run_provenance_are_required(self, mutation):
        module = manifest_module()
        manifest = {
            "identity_hash": "identity-1",
            "corpus_hash": "corpus-1",
            "parity_generations": {
                "sentinel_data_version": "sentinel-g1",
                "canonical_data_version": "bt-g1",
                "canonical_source_mode": "real",
            },
        }
        final_identity = {
            "identity_hash": "identity-1",
            "corpus": {"data_version": "sentinel-g1",
                       "corpus_hash": "corpus-1"},
        }
        summary = {"provenance": {
            "bt_data_version": "bt-g1",
            "bt_data_source_mode": "real",
            "bt_data_status": "READY",
        }}
        targets = {
            "run_generation": (summary["provenance"], "bt_data_version"),
            "source_mode": (summary["provenance"], "bt_data_source_mode"),
            "run_status": (summary["provenance"], "bt_data_status"),
            "sentinel_generation": (final_identity["corpus"], "data_version"),
            "identity": (final_identity, "identity_hash"),
            "corpus_hash": (final_identity["corpus"], "corpus_hash"),
        }
        target, key = targets[mutation]
        target[key] = "different"
        _, failures = module.finalization_provenance_failures(
            manifest, final_identity, summary)
        assert failures, mutation


class TestParityAuthoritiesAreExplicit:

    def test_certification_has_no_known_password_dsn_fallback(self):
        body = text()
        assert '[ -n "${SENTINEL_DATABASE_URL:-}" ] || fail' in body
        assert '[ -n "${BT_DATABASE_URL:-}" ] || fail' in body
        parity = body[body.index("Both authorities are explicit"):]
        assert "postgresql://sentinel:sentinel@" not in parity
        assert "postgresql://btuser:btpass@" not in parity
        assert '-e SENTINEL_DATABASE_URL="${SENTINEL_DATABASE_URL}"' in parity
        assert '-e BT_DATABASE_URL="${BT_DATABASE_URL}"' in parity


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


class TestCanonicalCertificationTestRun:
    """A free-form pytest summary is not execution-authority evidence."""

    @staticmethod
    def manifest(tmp_path: Path, **overrides) -> Path:
        record = {
            "schema": "sentinel.certification_manifest/2",
            "lifecycle": "FROZEN",
            "identity_hash": "a" * 64,
            "git_commit": "b" * 40,
            "image_source_hashes": {"certification_inputs": "c" * 64},
            "sentinel_runtime_image": {
                "repo_digests": [f"registry/sentinel@sha256:{'d' * 64}"]},
            "sentinel_test_image": {
                "repo_digests": [f"registry/sentinel-test@sha256:{'e' * 64}"]},
        }
        record.update(overrides)
        path = tmp_path / "manifest-W.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True))
        return path

    @staticmethod
    def inputs(tmp_path: Path) -> tuple[Path, Path]:
        inventory = tmp_path / "inventory.txt"
        inventory.write_text(
            "tests/sentinel/test_z.py::test_second\n"
            "tests/sentinel/test_a.py::test_first\n"
            "tests/sentinel/test_x.py::test_debt[one]\n"
            "tests/sentinel/test_x.py::test_debt[two]\n"
            "tests/sentinel/test_x.py::test_debt[three]\n"
            "5 tests collected in 0.03s\n"
        )
        log = tmp_path / "suite.txt"
        log.write_text("..xxx [100%]\n2 passed, 3 xfailed in 0.21s\n")
        return inventory, log

    def test_the_harness_emits_the_record_from_the_actual_command(self):
        body = text()
        assert 'test-run-${RUNSTAMP}.json' in body
        assert 'manifest-frozen-${RUNSTAMP}.json' in body
        assert "sentinel_test_run.py retain-manifest" in body
        assert 'SUITE_CMD=(docker run --rm --network none "${TEST_IMAGE_REF}"' \
            in body
        assert '"${SUITE_CMD[@]}" 2>&1' in body
        assert "sentinel_test_run.py publish" in body
        assert 'INVENTORY_CMD=(docker run --rm --network none' in body
        assert line_of("sentinel_test_run.py validate-manifest") \
            < line_of("TRUNCATE TABLE")
        assert line_of("sentinel_test_run.py retain-manifest") \
            < line_of("TRUNCATE TABLE")
        assert line_of("sentinel_test_run.py publish") \
            > line_of('SUITE=$("${SUITE_CMD[@]}"')

    def test_it_binds_exact_bytes_images_command_inventory_and_xfail_debt(
            self, tmp_path):
        module = certification_test_run_module()
        manifest = self.manifest(tmp_path)
        inventory, log = self.inputs(tmp_path)
        command = ["docker", "run", "--rm", "--network", "none",
                   f"registry/sentinel-test@sha256:{'e' * 64}",
                   "tests/sentinel", "-q", "-rs"]
        record = module.build_record(
            manifest_path=manifest, inventory_path=inventory, log_path=log,
            exit_code=0, command=command)
        assert record["schema"] == "sentinel.certification-test-run/1"
        assert record["status"] == "PASS"
        assert record["producer_sha256"] == hashlib.sha256(
            TEST_RUN_PRODUCER.read_bytes()).hexdigest()
        assert record["base_manifest"]["sha256"] == hashlib.sha256(
            manifest.read_bytes()).hexdigest()
        assert record["base_manifest"]["runtime_image_digest"] == \
            f"sha256:{'d' * 64}"
        assert record["base_manifest"]["test_image_digest"] == \
            f"sha256:{'e' * 64}"
        assert record["command"]["argv"] == command
        assert record["inventory"]["nodeids"] == sorted(
            record["inventory"]["nodeids"])
        assert record["inventory"]["count"] == 5
        assert base64.b64decode(
            record["inventory_log_base64"], validate=True
        ) == inventory.read_bytes()
        assert base64.b64decode(
            record["pytest_log_base64"], validate=True
        ) == log.read_bytes()
        assert record["pytest_log_sha256"] == hashlib.sha256(
            log.read_bytes()).hexdigest()
        assert record["passed"] == 2 and record["xfailed"] == 3
        assert record["failed"] == record["skipped"] == 0
        assert record["xpassed"] == record["errors"] == 0
        assert set(record) == {
            "schema", "status", "producer_sha256", "base_manifest",
            "command", "inventory", "inventory_log_base64",
            "pytest_log_base64", "pytest_log_sha256", "exit_code", "passed",
            "failed", "skipped", "xfailed", "xpassed", "errors",
        }

    def test_publish_is_canonical_atomic_and_no_clobber(self, tmp_path):
        module = certification_test_run_module()
        manifest = self.manifest(tmp_path)
        inventory, log = self.inputs(tmp_path)
        output = tmp_path / "test-run-W.json"
        args = [
            "publish", "--manifest", str(manifest),
            "--inventory-log", str(inventory), "--pytest-log", str(log),
            "--exit-code", "0", "--output", str(output), "--",
            "docker", "run", "--rm", "--network", "none",
            f"registry/sentinel-test@sha256:{'e' * 64}",
            "tests/sentinel", "-q", "-rs",
        ]
        assert module.main(args) == 0
        raw = output.read_bytes()
        parsed = json.loads(raw)
        assert raw == module._canonical(parsed)
        assert module.main(args) == 1
        assert output.read_bytes() == raw

    def test_retained_frozen_bytes_do_not_follow_mutable_manifest(self, tmp_path):
        module = certification_test_run_module()
        manifest = self.manifest(tmp_path)
        original = manifest.read_bytes()
        retained = tmp_path / "manifest-frozen-W.json"
        assert module.main([
            "retain-manifest", "--manifest", str(manifest),
            "--output", str(retained)]) == 0
        manifest.write_text('{"lifecycle":"READY_FOR_REHEARSAL"}')
        assert retained.read_bytes() == original
        assert module.main([
            "retain-manifest", "--manifest", str(retained),
            "--output", str(retained)]) == 1
        assert retained.read_bytes() == original

    def test_post_link_failure_removes_the_authoritative_name(
            self, tmp_path, monkeypatch):
        module = certification_test_run_module()
        output = tmp_path / "record.json"

        def refuse_directory_fsync(_path):
            raise OSError("injected directory fsync failure")

        monkeypatch.setattr(module, "_fsync_directory", refuse_directory_fsync)
        with pytest.raises(OSError, match="injected"):
            module._write_no_clobber(output, b"evidence")
        assert not output.exists()

    @pytest.mark.parametrize(
        ("summary", "exit_code"), [
            ("1 passed, 1 skipped in 0.1s", 0),
            ("1 passed, 1 xpassed in 0.1s", 0),
            ("1 passed, 1 failed in 0.1s", 1),
            ("1 passed, 1 error in 0.1s", 1),
            ("1 passed in 0.1s", 4),
            ("1 xfailed in 0.1s", 0),
        ])
    def test_no_failed_partial_or_vacuous_result_can_publish(
            self, tmp_path, summary, exit_code):
        module = certification_test_run_module()
        manifest = self.manifest(tmp_path)
        inventory, log = self.inputs(tmp_path)
        log.write_text(summary + "\n")
        output = tmp_path / "refused.json"
        rc = module.main([
            "publish", "--manifest", str(manifest),
            "--inventory-log", str(inventory), "--pytest-log", str(log),
            "--exit-code", str(exit_code), "--output", str(output), "--",
            "docker", "run", "--rm", "--network", "none",
            f"registry/sentinel-test@sha256:{'e' * 64}",
            "tests/sentinel", "-q", "-rs",
        ])
        assert rc == 1
        assert not output.exists()

    @pytest.mark.parametrize("mutation", [
        "missing_runtime_digest", "ambiguous_runtime_digest",
        "same_image_digest", "wrong_lifecycle", "missing_input_hash",
    ])
    def test_manifest_provenance_falsifiers(self, tmp_path, mutation):
        module = certification_test_run_module()
        manifest = self.manifest(tmp_path)
        value = json.loads(manifest.read_text())
        if mutation == "missing_runtime_digest":
            value["sentinel_runtime_image"]["repo_digests"] = []
        elif mutation == "ambiguous_runtime_digest":
            value["sentinel_runtime_image"]["repo_digests"].append(
                f"other/sentinel@sha256:{'f' * 64}")
        elif mutation == "same_image_digest":
            value["sentinel_test_image"]["repo_digests"] = [
                f"other/test@sha256:{'d' * 64}"]
        elif mutation == "wrong_lifecycle":
            value["lifecycle"] = "READY_FOR_REHEARSAL"
        else:
            value["image_source_hashes"].pop("certification_inputs")
        manifest.write_text(json.dumps(value))
        with pytest.raises(module.TestRunRefused):
            module.manifest_binding(manifest)

    @pytest.mark.parametrize("collection", [
        "tests/sentinel/test_a.py::test_first\n2 tests collected in 0.1s\n",
        ("tests/sentinel/test_a.py::test_first\n"
         "tests/sentinel/test_a.py::test_first\n"
         "2 tests collected in 0.1s\n"),
        "2 tests collected in 0.1s\n",
    ])
    def test_inventory_must_match_sorted_unique_nodeids(self, collection):
        module = certification_test_run_module()
        with pytest.raises(module.TestRunRefused):
            module.inventory_from_log(collection.encode())

    def test_inventory_preserves_parameter_ids_with_spaces(self):
        module = certification_test_run_module()
        inventory = module.inventory_from_log(
            b"tests/sentinel/test_a.py::test_first[buy sell]\n"
            b"1 test collected in 0.1s\n")
        assert inventory["nodeids"] == [
            "tests/sentinel/test_a.py::test_first[buy sell]"]

    def test_the_producer_is_valid_python_and_the_harness_is_valid_bash(self):
        compile(TEST_RUN_PRODUCER.read_text(), str(TEST_RUN_PRODUCER), "exec")
        bash = (r"C:\Program Files\Git\bin\bash.exe"
                if os.name == "nt" else "bash")
        result = subprocess.run(
            [bash, "-n", str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


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
        src = (REPO / "sentinel" / "identity.py").read_text()
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
    FINAL = REPO / "scripts" / "sentinel-finalize-rehearsal.sh"

    def test_it_exists_and_is_referenced_by_the_harness(self):
        assert self.FINAL.exists()
        assert "sentinel-finalize-rehearsal.sh" in text()

    def test_it_EXTRACTS_the_book_rather_than_asking_for_one(self):
        body = self.FINAL.read_text()
        assert "book_artifact" in body
        assert "bt_wealth_core_runs" in body, (
            "the book is still expected to arrive as a file someone produced")

    VALIDATOR = REPO / "scripts" / "sentinel_rehearsal.py"

    def test_it_REFUSES_a_summary_with_no_book(self):
        """An older engine produced the run — one that had the RunResult and
        discarded it. Writing the book by hand is exactly what this removes.

        The check moved into the shared validator when both entry paths were
        converged; `tests/sentinel/test_rehearsal_envelope.py` exercises it
        directly rather than by reading a script."""
        assert "no book_artifact" in self.VALIDATOR.read_text()

    def test_it_checks_the_WINDOW_of_the_extracted_book(self):
        """A rehearsal over a different span omits every name held outside it.
        Checked in the validator, on BOTH entry paths."""
        body = self.VALIDATOR.read_text()
        assert "the run covered" in body and "the book covers" in body

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
        body = self.VALIDATOR.read_text()
        for claim in ("status", "chain_rehearsal", "start_date", "end_date",
                      "parity_hashes", "engine_identity"):
            assert claim in body, claim
        assert "mode is" in body and "not 'chain_rehearsal'" in body

    def test_only_a_fresh_database_read_can_finalize(self):
        body = self.FINAL.read_text()
        assert "sentinel_rehearsal.py finalize" in body
        assert "--run-id" in body and "BT_DATABASE_URL" in body
        assert "--from-json" not in body
        assert "sentinel_rehearsal.py authenticate" not in body

    def test_it_records_the_SPEC_the_run_actually_used(self):
        assert "rehearsal_spec" in self.FINAL.read_text()

    def test_it_names_the_BT_ENGINE_image(self):
        """`sentinel:latest` produces the Sentinel corpus; the three-year Wealth
        Core rehearsal is executed by bt-engine, and that image belongs in the
        chain just as much.

        The image is now named by the MANIFEST at freeze time — see
        `TestTheEngineIsFrozenNotJustSelfReported`. The finalizer compares the
        run against that frozen value rather than inspecting a live tag, so it
        no longer reads BT_ENGINE_IMAGE itself."""
        assert "bt_engine_image" in self.FINAL.read_text()
        assert "bt_engine_image" in MANIFEST.read_text()


class TestTheFinalizerGATESRatherThanNarrates:
    """`REHEARSAL FINALIZED` meant evidence exists, not that it passed. The
    conditions were recorded, and then the operator was told what to read."""

    FINAL = REPO / "scripts" / "sentinel-finalize-rehearsal.sh"

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
        assert "last_finalization_attempt" in MANIFEST.read_text()
        assert body.index("finish_finalization") < body.rindex("mp.write_text"), (
            "the blocked/finalized lifecycle result is not persisted")

    def test_a_nonzero_RESIDUAL_blocks(self):
        assert "not 0 — at" in self.FINAL.read_text()

    def test_the_failure_message_is_BLOCKED_not_finalized(self):
        body = self.FINAL.read_text()
        assert "the certification conditions were NOT met" in body
        assert "attempted evidence and failure list are retained" in body

    def test_the_exact_parity_generation_and_source_mode_are_gates(self):
        body = MANIFEST.read_text()
        for field in ("sentinel_data_version", "canonical_data_version",
                      "canonical_source_mode", "bt_data_version",
                      "bt_data_source_mode", "bt_data_status"):
            assert field in body


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



# ── 6. the engine that runs the rehearsal ────────────────────────────────────

class TestTheBaseIsRebuiltBeforeTheEngine:
    """`services/bt-engine/Dockerfile` begins `FROM stocker-base:latest` — a
    MUTABLE tag holding `shared/`, and therefore Wealth Core. Building
    bt-engine without rebuilding it layers a fresh engine on whatever base is
    lying around: yesterday's on one machine, nothing at all on a clean one.

    The deploy scripts already carry this forced rebuild for the same reason
    (the editable install caches the module list, so a NEW shared file is
    invisible until the base is rebuilt). Certification needs it more, not
    less: the rehearsal would expose a stale Wealth Core as a source-hash
    mismatch only after the seed and three hours of simulation."""

    @staticmethod
    def build_step() -> str:
        """Just the build step.

        Scoped deliberately: the remediation text inside a later `fail` message
        also contains the base-build command, and an unscoped search finds it
        there — so removing the real build entirely would still have satisfied
        an assertion that the command 'appears'. A test that a fix is DESCRIBED
        is not a test that it is DONE."""
        body = text()
        return body[body.index('step "1/9'):body.index('step "2/9')]

    def test_the_base_is_built_UNCONDITIONALLY(self):
        step1 = self.build_step()
        assert "-t stocker-base:latest -f Dockerfile.base" in step1
        command = step1[step1.rindex("docker build", 0,
                                     step1.index("Dockerfile.base")):
                        step1.index("Dockerfile.base")]
        assert "if " not in command

    def test_it_is_built_BEFORE_bt_engine(self):
        step1 = self.build_step()
        assert step1.index("-t stocker-base:latest -f Dockerfile.base") \
            < step1.index("docker-compose.backtest.yml build")

    def test_it_is_a_BUILD_and_starts_nothing(self):
        """Stocker is retired. A certification step may rebuild the image that
        packages `shared/` — a build artefact — but must not bring a Stocker
        service up."""
        for line in text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "docker-compose.backtest.yml" in line:
                assert " up" not in line, line

    def test_bt_engine_is_built_before_anything_is_destroyed(self):
        assert line_of("bt-data bt-engine") \
            < line_of("TRUNCATE TABLE")

    def test_every_source_image_is_labeled_with_the_frozen_commit(self):
        certify = text()
        assert 'SOURCE_GIT_SHA="$(git rev-parse HEAD)"' in certify
        assert certify.count("--build-arg SOURCE_GIT_SHA") >= 3
        for path in ("Dockerfile.sentinel", "Dockerfile.base",
                     "Dockerfile.sentinel-authorized",
                     "Dockerfile.sentinel-test",
                     "services/bt-engine/Dockerfile",
                     "services/bt-data/Dockerfile"):
            body = (REPO / path).read_text()
            assert "org.opencontainers.image.revision" in body, path

    def test_verify_only_refuses_a_stale_source_revision(self):
        body = MANIFEST.read_text()
        assert "SOURCE_IMAGES" in body
        assert 'revision != m["git_commit"]' in body
        assert "was built from" in body


class TestTheEngineWealthCoreIsComparedBeforeTruncate:
    """Defence in depth over the forced rebuild, because the two fail
    differently: a skipped rebuild is an operator mistake, a mismatched result
    is a build that did not do what it was told."""

    def test_the_engine_is_ASKED_for_its_wealth_core_hash(self):
        body = text()
        assert "wealth_core_source_hash()" in body
        assert "docker run --rm --entrypoint python" in body

    def test_the_comparison_happens_BEFORE_the_truncate(self):
        assert line_of("BT_WC=") < line_of("TRUNCATE TABLE")
        assert line_of("SENTINEL_WC=") < line_of("TRUNCATE TABLE")

    def test_a_MISMATCH_blocks_certification(self):
        body = text()
        i = body.index('"${BT_WC}" != "${SENTINEL_WC}"')
        assert "fail " in body[i:i + 400]

    def test_an_UNREADABLE_hash_also_blocks(self):
        """Absent is not equal. An engine that cannot name the engine source it
        carries cannot produce certification evidence, and an empty string
        compared against an empty string would have passed."""
        body = text()
        i = body.index('-z "${BT_WC}"')
        assert "fail " in body[i:i + 400]

    def test_the_step_runs_before_the_manifest_freezes_the_image(self):
        assert line_of("BT_WC=") < line_of("sentinel_manifest.py")

    def test_the_manifest_is_given_the_RESOLVED_ref(self):
        """Not a second opinion about the image name."""
        body = text().replace("\\\n", " ")
        assert "--bt-engine-ref \"${BT_REF}\"" in body


class TestTheCertifiedLauncherDoesNotRebuild:
    """After a freeze the manifest already names the engine. Rebuilding can
    only produce a different artefact, and the finalizer would refuse the run
    — after three hours."""

    LAUNCH = REPO / "scripts" / "bt-engine-up.sh"

    def test_no_build_skips_the_build(self):
        body = self.LAUNCH.read_text()
        assert "--no-build) BUILD=0" in body
        i = body.index('if [ "${BUILD}" -eq 1 ]')
        assert "build bt-engine" in body[i:i + 200]

    def test_the_manifest_is_chosen_by_INTERVAL_not_mtime(self):
        body = self.LAUNCH.read_text()
        assert 'manifest-${START}_${END}.json' in body
        # The mtime path survives only as a warned default.
        i = body.index("ls -1t artifacts/sentinel/manifest-")
        assert "--start/--end" in body[i:i + 400]

    def test_a_named_interval_with_no_manifest_REFUSES(self):
        body = self.LAUNCH.read_text()
        assert 'manifest-${START}_${END}.json' in body
        i = body.index('manifest-${START}_${END}.json')
        window = body[i:i + 400]
        assert "REFUSED" in window and "exit 1" in window

    def test_a_drifted_image_is_refused_before_the_run(self):
        body = self.LAUNCH.read_text()
        assert '"${FROZEN}" != "${ID}"' in body
        i = body.index('"${FROZEN}" != "${ID}"')
        assert "REFUSED" in body[i:i + 800]

    def test_the_refusal_names_the_certified_way_to_start(self):
        body = self.LAUNCH.read_text()
        assert "--no-build --start" in body


class TestTheDirtyTreeRefusalNamesTheFILES:
    """A gate that stops the run without saying what to look at sends the
    operator hunting through a repo they have not edited.

    It fired for real on the NAS at step 2d: "the working tree is DIRTY" and
    nothing else — after two clean gates and a successful locked rebuild, with
    no indication of which path was responsible."""

    def test_the_manifest_records_the_paths(self):
        assert "git_dirty_paths" in MANIFEST.read_text()

    def test_the_refusal_prints_them(self, tmp_path):
        (tmp_path / "identity-env.json").write_text(json.dumps({
            "identity_hash": "ih",
            "environment": {"distributions_hash": "dh", "distributions_count": 1,
                            "sentinel_source": {"hash": "sh"},
                            "wealth_core_source": {"hash": "wh"},
                            "python": "3.12.13", "calendar_version": "x"}}))
        # A repo whose tree is dirty by construction.
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "tracked.txt").write_text("v1\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "init"], cwd=repo, check=True)
        (repo / "tracked.txt").write_text("v2\n")
        (repo / "stray.txt").write_text("untracked\n")

        r = subprocess.run(
            [sys.executable, str(MANIFEST), str(tmp_path), "W", "l",
             "--require-images"], capture_output=True, text=True, cwd=str(repo))
        assert r.returncode == 1
        assert "tracked.txt" in r.stdout, r.stdout
        assert "stray.txt" in r.stdout, r.stdout

    def test_it_names_the_fileMode_case(self):
        """The likeliest cause on a NAS: a filesystem that rewrites permission
        bits, so every entry is a MODE change on a file nobody touched."""
        assert "core.fileMode" in MANIFEST.read_text()


MEASURE = REPO / "scripts" / "sentinel-measure.sh"


class TestTheResourceMeasurementHarness:
    """Finding #15 measures an envelope, and the measurement is EVIDENCE.

    `docker-compose.sentinel.yml` sets `mem_limit: 1g` under a comment that says
    the value is provisional and will be "tightened to the measured envelope
    later". A limit tightened from a figure someone read off a terminal is a
    limit nobody can re-derive, and the failure it produces is an OOM kill
    partway through a seed — which, as the 8b incident showed, presents as a
    silent exit and gets inferred rather than measured.

    So the harness is checked the way the rest of the certification machinery
    is: statically, for the properties whose absence would make a green run
    meaningless.
    """

    def body(self) -> str:
        return MEASURE.read_text()

    def test_it_exists_and_is_executable(self):
        assert MEASURE.exists(), "scripts/sentinel-measure.sh is missing"
        assert os.access(MEASURE, os.X_OK), "not executable"

    def test_it_NEVER_removes_volumes(self):
        """The same rule the certify script follows. The Sentinel volume holds
        the ownership log, and losing it makes the next start liquidate a
        Sentinel-owned book — a measurement run must not be able to cause that.

        Matched as COMMANDS, not as the substring `-v `. The first version did
        the latter and had to carve out an exception for `psql -v
        ON_ERROR_STOP=1`, which left it pinned to that one line's exact
        formatting: reflow the psql call and the guard silently stops checking
        anything. That is the same shape as the `fetchall()` test that matched
        its own docstring.
        """
        import re
        body = self.body()
        hazards = [
            (r"compose[^\n|&;]*\bdown\b[^\n|&;]*(--volumes|\s-v\b)",
             "`compose down` with volume removal"),
            (r"\bdocker\s+volume\s+rm\b", "docker volume rm"),
            (r"\bdocker\s+(system|volume)\s+prune\b", "a prune"),
            (r"\brm\s+-rf\s+/var/lib/postgresql", "deleting the data directory"),
            (r"\bTRUNCATE\b", "truncating the corpus — measurement is READ-ONLY "
                              "about state; step 3 of the certify script owns that"),
        ]
        found = [why for pat, why in hazards
                 if re.search(pat, body, re.I | re.M)]
        assert not found, f"scripts/sentinel-measure.sh can destroy state: {found}"

    def test_the_volume_guard_can_FAIL(self):
        """Guard the guard, on the one that would be catastrophic to have
        silently disabled. Five patterns and a real string for each."""
        import re
        pats = [r"compose[^\n|&;]*\bdown\b[^\n|&;]*(--volumes|\s-v\b)",
                r"\bdocker\s+volume\s+rm\b",
                r"\bdocker\s+(system|volume)\s+prune\b",
                r"\brm\s+-rf\s+/var/lib/postgresql",
                r"\bTRUNCATE\b"]
        samples = ["${COMPOSE} down --volumes",
                   "docker volume rm sentinel_pgdata",
                   "docker system prune -af",
                   "rm -rf /var/lib/postgresql/data",
                   "TRUNCATE TABLE sentinel_bars"]
        for pat, s in zip(pats, samples):
            assert re.search(pat, s, re.I | re.M), (pat, s)
        # And the live text of the psql call must NOT trip any of them.
        psql = ("psql -U sentinel -d sentinel -tAq -v ON_ERROR_STOP=1 -c "
                "\"SELECT temp_bytes FROM pg_stat_database\"")
        assert not any(re.search(p, psql, re.I | re.M) for p in pats)

    def test_the_limits_are_READ_from_compose_not_transcribed(self):
        """A hardcoded `1073741824` would keep reporting headroom after
        somebody changed the file it is supposed to be comparing against —
        the same failure shape as a transcribed threshold."""
        body = self.body()
        assert "docker-compose.sentinel.yml" in body
        assert "mem_limit" in body
        for literal in ("1073741824", "2147483648", "536870912"):
            assert literal not in body, (
                f"{literal} is a compose limit transcribed into the harness")

    def test_it_samples_WITHOUT_streaming(self):
        """Streaming `docker stats` redraws with control codes: a tee'd log is
        neither readable nor parseable, and its first CPU frame is meaningless.
        Sampled on a timer instead, one complete CSV row per frame."""
        body = self.body()
        assert "--no-stream" in body
        assert "docker stats --no-stream" in body

    def test_it_records_what_docker_stats_CANNOT_see(self):
        """Peak RSS alone passes a run that spilled 40GB to disk, swapped the
        host, or was OOM-killed and restarted into apparent health."""
        body = self.body()
        for probe in ("temp_bytes",          # the sort spill
                      "MemAvailable",        # host pressure
                      "OOMKilled",           # the kill itself
                      "RestartCount",        # and the recovery that hides it
                      "elapsed_seconds"):    # a phase that fits by taking a day
            assert probe in body, f"the harness never looks at {probe}"

    def test_an_UNMEASURED_run_is_not_a_pass(self):
        """The failure this class most needs to prevent: a sampler that never
        started, a phase that exited non-zero, or an OOM — each reported as a
        clean envelope."""
        body = self.body()
        for verdict in ("UNMEASURED", "PHASE FAILED", "OOM KILLED", "TIGHT"):
            assert verdict in body, f"no {verdict} verdict"
        assert 'case "${VERDICT}" in' in body

    def test_it_is_valid_bash(self):
        r = subprocess.run(["bash", "-n", str(MEASURE)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_every_example_phase_names_a_REAL_cli_verb(self):
        """Two of the first examples were `sentinel run --dry-run` and
        `sentinel catch-up`. Neither is a verb — argparse would have answered
        "invalid choice" to an operator who had just SSH'd to the NAS to start
        an hours-long job. Examples in a runbook are instructions, and an
        instruction nobody executed is an instruction nobody checked."""
        import re
        verbs = set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"',
                               (REPO / "sentinel" / "__main__.py").read_text()))
        assert "feed-seed" in verbs, "the verb scrape is broken, not the script"
        used = re.findall(r"sentinel-measure\.sh\s+\S+\s+--\s+sentinel\s+([a-z-]+)",
                          self.body())
        assert used, "no example invocations found to check"
        bogus = sorted({v for v in used if v not in verbs})
        assert not bogus, (
            f"the harness documents phases that are not CLI verbs: {bogus}. "
            f"Available: {sorted(verbs)}")

    def test_it_runs_the_phase_with_T(self):
        """Without -T compose allocates a TTY whenever stdin is one, which over
        SSH it is, and the tee'd phase log fills with cursor control codes. The
        certify script passes -T for the same reason.

        Matched WITHOUT `--rm`, which moved: the phase container is kept until
        its final `.State` has been read, so an OOM can be attributed to the
        measured workload rather than to whatever else was running."""
        code = "\n".join(l for l in self.body().splitlines()
                          if l.strip() and not l.strip().startswith("#"))
        assert "run -T --name" in code

    def test_the_production_catchup_entry_point_is_measurable(self):
        """Measure the real transactional preparation command, not a proxy."""
        import re
        verbs = set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"',
                               (REPO / "sentinel" / "__main__.py").read_text()))
        if "catch-up" in verbs or "catchup" in verbs:
            return
        assert "prepare-paper-plan" in verbs
        body = self.body()
        assert "prepare-paper-plan" in body
        assert "production catch-up entry point" in body

    # ── the evidence must not be broader than what was measured ─────────────

    def test_the_phase_container_is_INSPECTED_before_removal(self):
        """The phase used to run with `--rm`, so it was GONE by the time the
        OOM scan looked — and the scan then swept surviving `sentinel*`
        containers, which are the database and the panel, not the workload. A
        non-zero exit still prevented a false PASS, but "the OOM killer
        specifically" was lost while the comments claimed otherwise."""
        body = self.body()
        # EXECUTABLE lines only. The first version scanned the whole file and
        # tripped on the usage comment describing the command — reading the
        # documentation instead of the script, which is the trap this
        # repository keeps re-finding.
        code = "\n".join(l for l in body.splitlines()
                          if l.strip() and not l.strip().startswith("#"))
        assert "--name" in code and "PHASE_CONTAINER" in code
        assert "run --rm" not in code, (
            "the measured container is removed before its final .State can be "
            "read, so an OOM cannot be attributed to the phase")
        assert code.index("docker inspect -f") < code.index("docker rm -f"), (
            "the container is removed before it is inspected")

    def test_an_OOM_is_ATTRIBUTED(self):
        """`something was OOM-killed` and `the seed was OOM-killed` are
        different findings — the database being killed during a seed says
        something else entirely."""
        body = self.body()
        assert "OOM KILLED (the measured phase)" in body
        assert "OOM KILLED (another container)" in body

    def test_host_memory_is_its_OWN_verdict(self):
        """A container inside its ceiling on a host whose MemAvailable
        collapsed is not a passing envelope, and no per-container headroom
        figure can see that."""
        body = self.body()
        assert "host_memory_verdict" in body
        assert "host_min_mem_available_basis_points" in body

    def test_IO_and_RUNTIME_are_reported_too(self):
        """This host reports no blkio throttle support at all, so disk pressure
        is in the same category as CPU: observable, not boundable. And a phase
        that fits in 1g by taking nine hours has not passed either."""
        body = self.body()
        assert "io_limit_enforcement" in body
        assert "runtime_verdict" in body

    def test_every_axis_is_PRINTED_whatever_the_memory_verdict(self):
        """A reader who sees only "MEMORY ENVELOPE MEASURED" would reasonably
        assume the rest were bounded. On this hardware three of them are not,
        so the summary is unconditional rather than an else-branch."""
        body = self.body()
        block = body[body.index("what this run actually proves"):]
        for axis in ("container memory", "host memory", "CPU", "disk I/O",
                     "runtime"):
            assert axis in block, axis
        # BEFORE the memory verdict's case statement, so it is never skipped by
        # an early `die`.
        assert body.index("what this run actually proves") < \
            body.index('case "${VERDICT}" in')
