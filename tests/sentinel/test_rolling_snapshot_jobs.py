"""Real PostgreSQL lease, deadline and resumable-component falsifiers."""
from __future__ import annotations

import time
import uuid
from dataclasses import replace

import pytest

from sentinel.feed import rolling_jobs as jobs, rolling_store, runtime_schema
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.feed.store import connect
from tests.support.postgres import _EphemeralPostgres
from test_rolling_snapshot_storage import populated, seal


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    c = connect(server.sync_dsn)
    try:
        runtime_schema.migrate_feed_schema(c)
        yield server
    finally:
        c.close()
        server.stop()


@pytest.fixture
def conn(pg):
    c = connect(pg.sync_dsn)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture
def request_value():
    return jobs.PreparationRequest(
        window=PriceWindow.through("2026-09-14"), cursor=None,
        strategy_sha256=digest(str(uuid.uuid4())), dependencies_sha256=digest({}))


def claimed(conn, request):
    job = jobs.enqueue(conn, request, budget_seconds=120)
    return job, jobs.claim(conn, job)


def test_duplicate_wakes_keep_one_job_and_original_deadline(conn, request_value):
    job = jobs.enqueue(conn, request_value, budget_seconds=120)
    before = jobs.status(conn, job)
    assert jobs.enqueue(conn, request_value, budget_seconds=3600) == job
    after = jobs.status(conn, job)
    assert after["deadline"] == before["deadline"]
    assert 0 < after["remaining_seconds"] <= 120
    assert 0 <= after["phase_elapsed_seconds"] <= after["elapsed_seconds"]
    assert 0 <= after["last_progress_age_seconds"] <= after["elapsed_seconds"]


def test_an_active_owner_excludes_a_second_worker(conn, pg, request_value):
    job, _lease = claimed(conn, request_value)
    conn.commit()
    other = connect(pg.sync_dsn)
    try:
        with pytest.raises(jobs.JobWaiting, match="owned"):
            jobs.claim(other, job)
    finally:
        other.close()


def test_reclaimed_fence_refuses_old_worker_and_keeps_checkpoints(conn, request_value):
    job, old = claimed(conn, request_value)
    jobs.checkpoint(conn, old, component="SEP.2026-08-01.2026-08-31",
                    generation_sha256="a" * 64, artifact_sha256="b" * 64,
                    rows=5000, bytes_=100000)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' "
                    "WHERE job_id=%s", (job,))
    conn.commit()
    new = jobs.claim(conn, job)
    assert new.fence == old.fence + 1 and new.owner != old.owner
    with pytest.raises(jobs.JobRefused, match="fence"):
        jobs.progress(conn, old, rows=10000, bytes_=200000)
    assert len(jobs.components(conn, job)) == 1
    jobs.progress(conn, new, rows=5000, bytes_=100000)


@pytest.mark.parametrize("field", ["owner", "fence"])
def test_each_lease_identity_is_required(conn, request_value, field):
    _job, lease = claimed(conn, request_value)
    invalid = replace(lease, **{field: str(uuid.uuid4()) if field == "owner" else lease.fence - 1})
    with pytest.raises(jobs.JobRefused, match="fence"):
        jobs.progress(conn, invalid, rows=1, bytes_=1)


def test_heartbeat_is_not_meaningful_progress(conn, request_value):
    job, lease = claimed(conn, request_value)
    before = jobs.status(conn, job)
    jobs.heartbeat(conn, lease)
    jobs.progress(conn, lease, rows=0, bytes_=0)
    assert jobs.status(conn, job)["last_progress_at"] == before["last_progress_at"]
    jobs.progress(conn, lease, rows=1, bytes_=100)
    assert jobs.status(conn, job)["last_progress_at"] > before["last_progress_at"]
    with pytest.raises(jobs.JobRefused, match="regress"):
        jobs.progress(conn, lease, rows=0, bytes_=100)


def test_wait_releases_worker_and_resumes_same_stage(conn, request_value):
    job, lease = claimed(conn, request_value)
    deadline = jobs.status(conn, job)["deadline"]
    jobs.wait(conn, lease, state="WAIT_SOURCE", reason="EXPORT_CREATING", retry_seconds=10)
    waiting = jobs.status(conn, job)
    assert waiting["state"] == "WAIT_SOURCE" and waiting["owner"] is None
    with pytest.raises(jobs.JobWaiting, match="waiting"):
        jobs.claim(conn, job)
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp()-interval '1 second' "
                    "WHERE job_id=%s", (job,))
    new = jobs.claim(conn, job)
    assert new.fence == lease.fence + 1
    after = jobs.status(conn, job)
    assert after["state"] == "ACQUIRING" and after["deadline"] == deadline


def test_expired_deadline_cannot_be_extended_or_reclaimed(conn, request_value):
    import psycopg
    job = jobs.enqueue(conn, request_value, budget_seconds=1)
    lease = jobs.claim(conn, job)
    conn.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_snapshot_jobs SET deadline=deadline+interval '1 hour' "
                        "WHERE job_id=%s", (job,))
    conn.rollback()
    time.sleep(1.05)
    with pytest.raises(jobs.JobRefused, match="deadline"):
        jobs.heartbeat(conn, lease)
    with pytest.raises(jobs.JobRefused, match="expired"):
        jobs.claim(conn, job)
    assert jobs.expire(conn, job)
    assert not jobs.expire(conn, job)
    assert jobs.status(conn, job)["reason"] == "DEADLINE_EXHAUSTED"


def test_retry_cannot_hide_budget_exhaustion(conn, request_value):
    job, lease = claimed(conn, request_value)
    with pytest.raises(jobs.JobRefused, match="exhaust"):
        jobs.wait(conn, lease, state="RETRY_WAIT", reason="RATE_LIMITED", retry_seconds=120)
    assert jobs.status(conn, job)["state"] == "ACQUIRING"


def test_component_is_idempotent_but_changed_generation_refuses(conn, request_value):
    job, lease = claimed(conn, request_value)
    values = dict(component="TICKERS", generation_sha256="a" * 64,
                  artifact_sha256="b" * 64, rows=20000, bytes_=2000000)
    jobs.checkpoint(conn, lease, **values)
    jobs.checkpoint(conn, lease, **values)
    with pytest.raises(jobs.JobRefused, match="changed generation"):
        jobs.checkpoint(conn, lease, **{**values, "generation_sha256": "c" * 64})
    assert len(jobs.components(conn, job)) == 1
    assert jobs.components(conn, job)[0]["generation_sha256"] == "a" * 64


@pytest.mark.parametrize("value", ["https://vendor.invalid/secret", "C:/private/file.zip",
                                   "SEP?api_key=secret", "account-123"])
def test_checkpoint_names_cannot_persist_urls_paths_or_arbitrary_ids(conn, request_value, value):
    _job, lease = claimed(conn, request_value)
    with pytest.raises(jobs.JobRefused, match="safe component"):
        jobs.checkpoint(conn, lease, component=value, generation_sha256="a" * 64,
                        artifact_sha256="b" * 64, rows=1, bytes_=1)


def test_ready_requires_exact_sealed_candidate_and_does_not_publish(conn, request_value):
    job, lease = claimed(conn, request_value)
    candidate = populated(conn, request_value.window)
    jobs.advance(conn, lease, "STAGING", candidate_id=candidate)
    jobs.progress(conn, lease, rows=300, bytes_=30000)
    jobs.advance(conn, lease, "VALIDATING")
    assert jobs.status(conn, job)["rows_done"] == 0
    with pytest.raises(rolling_store.SnapshotStorageRefused, match="no sealed manifest"):
        jobs.advance(conn, lease, "READY")
    seal(conn, candidate, request_value.window)
    jobs.advance(conn, lease, "READY")
    ready = jobs.status(conn, job)
    assert ready["state"] == "READY" and ready["publication_version"] is None
    with pytest.raises(jobs.JobRefused, match="only the publisher"):
        jobs.finish(conn, lease, state="PUBLISHED", reason="PUBLISHED")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sentinel_corpus_publications")
        assert cur.fetchone()[0] == 0


def test_candidate_with_different_window_refuses(conn, request_value):
    _job, lease = claimed(conn, request_value)
    candidate = populated(conn, PriceWindow.through("2026-09-15"))
    with pytest.raises(jobs.JobRefused, match="frozen"):
        jobs.advance(conn, lease, "STAGING", candidate_id=candidate)


def test_ready_rechecks_lease_after_loading_evidence(conn, request_value, monkeypatch):
    job, lease = claimed(conn, request_value)
    candidate = populated(conn, request_value.window)
    seal(conn, candidate, request_value.window)
    jobs.advance(conn, lease, "STAGING", candidate_id=candidate)
    jobs.advance(conn, lease, "VALIDATING")
    original = rolling_store.manifest

    def expired_during_validation(*args):
        result = original(*args)
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' "
                        "WHERE job_id=%s", (job,))
        return result

    monkeypatch.setattr(rolling_store, "manifest", expired_during_validation)
    with pytest.raises(jobs.JobRefused, match="lease"):
        jobs.advance(conn, lease, "READY")
    assert jobs.status(conn, job)["state"] == "VALIDATING"


def test_terminal_outcomes_are_retained_and_cannot_reopen(conn, request_value):
    import psycopg
    job, lease = claimed(conn, request_value)
    jobs.finish(conn, lease, state="REFUSED", reason="SOURCE_GENERATION_CHANGED")
    conn.commit()
    with pytest.raises(jobs.JobRefused, match="terminal"):
        jobs.claim(conn, job)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_snapshot_jobs SET state='ACQUIRING' WHERE job_id=%s", (job,))
    conn.rollback()
    assert jobs.enqueue(conn, request_value, budget_seconds=120) != job
    assert jobs.status(conn, job)["state"] == "REFUSED"


def test_source_checkpoint_bytes_and_request_cannot_be_rewritten(conn, request_value):
    import psycopg
    job, lease = claimed(conn, request_value)
    jobs.checkpoint(conn, lease, component="TICKERS", generation_sha256="a" * 64,
                    artifact_sha256="b" * 64, rows=1, bytes_=1)
    conn.commit()
    for query in (
        "UPDATE sentinel_snapshot_job_components SET rows_done=2 WHERE job_id=%s",
        "DELETE FROM sentinel_snapshot_job_components WHERE job_id=%s",
        "UPDATE sentinel_snapshot_jobs SET request='{}' WHERE job_id=%s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            with conn.cursor() as cur:
                cur.execute(query, (job,))
        conn.rollback()


def test_job_schema_validation_is_read_only(conn):
    runtime_schema.require_feed_schema(conn)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE sentinel_snapshot_job_components DISABLE TRIGGER snapshot_immutable")
    conn.commit()
    try:
        with pytest.raises(runtime_schema.FeedSchemaRefused, match="not enabled"):
            runtime_schema.require_feed_schema(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE sentinel_snapshot_job_components ENABLE TRIGGER snapshot_immutable")
        conn.commit()
