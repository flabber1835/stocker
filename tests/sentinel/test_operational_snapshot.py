"""Real PostgreSQL publication, receipt and visibility boundary tests."""
from datetime import datetime, timezone

import pytest

from sentinel.feed import operational_snapshot as op, publication, rolling_jobs as jobs
from sentinel.feed import rolling_publisher, rolling_store, runtime_schema, store
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


@pytest.fixture
def operational_source(source, monkeypatch):
    monkeypatch.setattr(op, "_now", lambda: datetime(2026, 9, 15, 4, tzinfo=timezone.utc))
    monkeypatch.setattr(op.calendar, "latest_closed_session", lambda now=None: "2026-09-14")
    return source


def enqueue(conn, *, dependencies="fixture"):
    job = op.enqueue(conn, strategy_sha256=digest("strategy"),
                     dependencies_sha256=digest(dependencies), budget_seconds=120)
    conn.commit()
    return job


def count(conn, table):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM " + table)
        return cur.fetchone()[0]


@pytest.mark.parametrize("instant,expected", [
    ("2026-09-14T23:44:59-04:00", "2026-09-11"),
    ("2026-09-14T23:45:00-04:00", "2026-09-14"),
    ("2026-09-15T08:00:00-04:00", "2026-09-14"),
    ("2026-09-13T12:00:00-04:00", "2026-09-11"),
    ("2026-09-07T12:00:00-04:00", "2026-09-04"),
    ("2026-11-27T14:00:00-05:00", "2026-11-25"),
    ("2026-11-27T23:45:00-05:00", "2026-11-27"),
])
def test_source_final_axis_uses_calendar_and_eastern_cutoff(instant, expected):
    assert op.source_final_session(datetime.fromisoformat(instant)) == expected


def test_cold_publication_uses_real_version_and_receipt_without_legacy_corpus(conn, operational_source):
    job = enqueue(conn)
    result = op.prepare(conn, job)
    assert result["data_version"] > 0 and result["scope"] == "DATA_ONLY"
    assert result["operational_go"] is False
    assert jobs.status(conn, job)["state"] == "PUBLISHED"
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    assert count(conn, "sentinel_publication_validation_receipts") == 1
    for table in ("sentinel_bars", "sentinel_actions", "sentinel_universe"):
        assert count(conn, table) == 0
    with op.pinned(conn) as (pub, pinned):
        assert pinned == result
        assert pub.evidence["pitr"]["schema"] == publication.PITR_EVIDENCE_SCHEMA
        assert pub.evidence["publication_validation"]["schema"] == publication.RECEIPT_SCHEMA
        assert pub.evidence["strategy_history"]["baseline_version"] == pub.version
    calls = list(operational_source["calls"])
    assert op.prepare(conn, job) == result
    assert operational_source["calls"] == calls
    assert count(conn, "sentinel_corpus_publications") == 1
    runtime_schema.require_feed_schema(conn)


def test_legacy_readers_cannot_mislabel_legacy_rows_with_snapshot_version(conn, operational_source):
    op.prepare(conn, enqueue(conn))
    with pytest.raises(publication.CorpusIncoherent, match="VERSIONED_READER"):
        publication.current(conn)
    conn.rollback()
    with pytest.raises(publication.CorpusIncoherent, match="VERSIONED_READER"):
        with publication.pinned(conn):
            pytest.fail("legacy pin admitted a snapshot publication")
    with pytest.raises(publication.CorpusIncoherent, match="VERSIONED_READER"):
        publication.publish(conn, evidence={"test": "cannot switch back"})
    assert count(conn, "sentinel_corpus_publications") == 1


def test_cannot_supply_snapshot_marker_to_legacy_publisher(conn):
    with pytest.raises(publication.CorpusIncoherent, match="dedicated publisher"):
        publication.publish(conn, evidence={"rolling_snapshot": {"schema": op.SCHEMA}})
    assert count(conn, "sentinel_corpus_publications") == 0


def test_explicit_refresh_advances_data_not_strategy_history_authority(conn, operational_source):
    from sentinel.core.history import require_history_compatible, HistoryReconstructionRequired
    first_job = enqueue(conn)
    first = op.prepare(conn, first_job)
    second_job = enqueue(conn)
    assert second_job != first_job
    # A changed, independently validated vendor input is a distinct generation.
    for row in operational_source["SEP"]:
        if row["ticker"] == "AAA":
            row["open"] = "50"
    second = op.prepare(conn, second_job)
    assert second["data_version"] > first["data_version"]
    assert op.published(conn, first_job) == first
    with op.pinned(conn) as (pub, _):
        assert pub.previous_version == first["data_version"]
        with pytest.raises(HistoryReconstructionRequired, match="does not cover"):
            require_history_compatible(prior_version=first["data_version"],
                last_processed_session="2026-09-14", version=pub.version,
                proof=pub.evidence["strategy_history"])


def test_publication_cas_rejects_concurrent_job(conn, operational_source):
    first, stale = enqueue(conn), enqueue(conn, dependencies="other")
    result = op.prepare(conn, first)
    with pytest.raises(op.OperationalSnapshotRefused, match="CAS_CHANGED"):
        op.prepare(conn, stale)
    assert count(conn, "sentinel_corpus_publications") == 1
    assert op.published(conn, first) == result
    assert jobs.status(conn, stale)["state"] == "REFUSED"


def test_job_cannot_cross_comparison_boundary(conn, operational_source):
    from tests.sentinel.test_rolling_snapshot_publisher import enqueue as comparison_job
    private = comparison_job(conn)
    with pytest.raises(rolling_publisher.ComparisonRefused, match="different publication path"):
        op.prepare(conn, private)
    job = enqueue(conn)
    with pytest.raises(rolling_publisher.ComparisonRefused, match="different publication path"):
        rolling_publisher.prepare(conn, job)
    assert count(conn, "sentinel_corpus_publications") == 0


def test_target_that_aged_during_validation_cannot_publish(conn, operational_source, monkeypatch):
    original = op.validate
    def validate(*args):
        original(*args)
        monkeypatch.setattr(op, "source_final_session", lambda: "2026-09-15")
    monkeypatch.setattr(op, "validate", validate)
    job = enqueue(conn)
    with pytest.raises(op.OperationalSnapshotRefused, match="SOURCE_FINAL_TARGET_CHANGED"):
        op.prepare(conn, job)
    assert count(conn, "sentinel_corpus_publications") == 0


def test_missing_operational_validation_cannot_publish(conn, operational_source, monkeypatch):
    monkeypatch.setattr(op, "validate", lambda *args: None)
    with pytest.raises(op.OperationalSnapshotRefused, match="BOUND_OPERATIONAL_VALIDATION_REQUIRED"):
        op.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_corpus_publications") == 0


def test_receipt_work_cannot_outlive_publication_lease(conn, operational_source, monkeypatch):
    original = publication._insert_receipted_publication
    def insert(conn, **kwargs):
        original(conn, **kwargs)
        conn.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' "
                     "WHERE job_id=%s", (job,))
    monkeypatch.setattr(publication, "_insert_receipted_publication", insert)
    job = enqueue(conn)
    with pytest.raises(jobs.JobRefused, match="lease, fence or deadline"):
        op.prepare(conn, job)
    assert count(conn, "sentinel_corpus_publications") == 0
    assert count(conn, "sentinel_publication_validation_receipts") == 0


def test_lost_commit_acknowledgement_returns_original_publication(conn, operational_source, monkeypatch):
    original = op.publish
    def lost_ack(conn, *args, **kwargs):
        original(conn, *args, **kwargs)
        conn.commit()
        raise ConnectionError("publication commit reply lost")
    monkeypatch.setattr(op, "publish", lost_ack)
    job = enqueue(conn)
    with pytest.raises(ConnectionError, match="reply lost"):
        op.prepare(conn, job)
    assert jobs.status(conn, job)["state"] == "PUBLISHED"
    expected = op.published(conn, job)
    calls = list(operational_source["calls"])
    monkeypatch.setattr(op, "publish", original)
    assert op.prepare(conn, job) == expected
    assert operational_source["calls"] == calls
    assert count(conn, "sentinel_corpus_publications") == 1


@pytest.mark.parametrize("boundary", ["receipt", "binding", "job"])
def test_failure_at_each_publication_write_rolls_back_every_visible_fact(conn, operational_source, boundary, monkeypatch):
    table = {"receipt": "sentinel_publication_validation_receipts",
             "binding": "sentinel_operational_snapshots", "job": "sentinel_snapshot_jobs"}[boundary]
    original = op.validate
    def validate(*args):
        original(*args)
        # Install only after admission: runtime schema validation rightly rejects
        # foreign triggers. This fault exercises the final write transaction.
        with conn.cursor() as cur:
            cur.execute("CREATE FUNCTION test_publication_crash() RETURNS trigger LANGUAGE plpgsql AS $$ "
                        "BEGIN RAISE EXCEPTION 'injected publication failure'; END $$")
            event = "UPDATE" if boundary == "job" else "INSERT"
            condition = " WHEN (NEW.state='PUBLISHED')" if boundary == "job" else ""
            cur.execute(f"CREATE TRIGGER publication_crash BEFORE {event} ON {table} FOR EACH ROW{condition} "
                        "EXECUTE FUNCTION test_publication_crash()")
    monkeypatch.setattr(op, "validate", validate)
    job = enqueue(conn)
    with pytest.raises(Exception, match="injected publication failure"):
        op.prepare(conn, job)
    for relation in ("sentinel_corpus_publications", "sentinel_operational_snapshots",
                     "sentinel_publication_validation_receipts"):
        assert count(conn, relation) == 0
    assert jobs.status(conn, job)["state"] == "REFUSED"


def test_deferred_constraint_prevents_unbound_published_job(conn, operational_source):
    job = enqueue(conn)
    # A genuine ordinary version still cannot stand in for a snapshot binding.
    legacy = publication.publish(conn, evidence={"test": "legacy"})
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET state='PUBLISHED',publication_version=%s WHERE job_id=%s",
                    (legacy.version, job))
    with pytest.raises(Exception, match="binding is incomplete"):
        conn.commit()
    conn.rollback()
    assert jobs.status(conn, job)["state"] == "ACQUIRING"


@pytest.mark.parametrize("table", ["sentinel_operational_snapshot_jobs",
    "sentinel_operational_snapshot_validations", "sentinel_operational_snapshots"])
def test_operational_evidence_cannot_be_erased(conn, operational_source, table):
    expected = op.prepare(conn, enqueue(conn))
    with pytest.raises(Exception, match="immutable"):
        conn.execute("DELETE FROM " + table)
    conn.rollback()
    with op.pinned(conn) as (_, current):
        assert current == expected


def test_snapshot_pin_excludes_writer(conn, operational_source):
    op.prepare(conn, enqueue(conn))
    other = store.connect(conn.info.dsn)
    try:
        with op.pinned(conn):
            with pytest.raises(publication.CorpusBusy):
                with store.corpus_write_lock(other):
                    pytest.fail("writer crossed snapshot pin")
    finally:
        other.close()


def test_bad_operational_reference_never_replaces_active_snapshot(conn, operational_source):
    first = op.prepare(conn, enqueue(conn))
    operational_source["ACTIONS"].append({"ticker": "UNKNOWN", "date": "2026-09-14",
        "action": "delisted", "name": "test", "value": None, "contraticker": None, "contraname": None})
    with pytest.raises(Exception, match="UNRESOLVED_SNAPSHOT_TERMINALS"):
        op.prepare(conn, enqueue(conn))
    with op.pinned(conn) as (_, current):
        assert current == first


def test_expired_first_attempt_gets_one_fresh_successor(conn, operational_source):
    import time
    args = dict(strategy_sha256=digest('strategy'), dependencies_sha256=digest('fixture'))
    old = op.enqueue(conn, **args, budget_seconds=1)
    conn.commit()
    time.sleep(1.1)
    fresh = op.enqueue(conn, **args, budget_seconds=120)
    conn.commit()
    assert fresh != old
    assert op.enqueue(conn, **args, budget_seconds=120) == fresh
    conn.commit()
    assert jobs.status(conn, old)['state'] == 'REFUSED'
    assert op.prepare(conn, fresh)['data_version'] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 2
