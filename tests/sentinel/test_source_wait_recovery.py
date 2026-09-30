"""Real fenced acquisition jobs: repair inputs without deleting useful work."""
from __future__ import annotations

import copy

import pytest

from sentinel.feed import acquisition_parts, acquisition_work, preparation_wait, rolling_jobs as jobs
from sentinel.feed import rolling_publisher as publisher, rolling_source, rolling_store, sharadar
from sentinel.feed import source_corrections as data
from sentinel.feed.source_wait import SourceCoveragePending
from test_rolling_snapshot_publisher import pg, conn, source, enqueue, retry_now, count
from test_source_corrections import installed_state, addition, install


def missing(conn, source):
    row = source["SEP"].pop(0)
    job = enqueue(conn)
    with pytest.raises(SourceCoveragePending):
        publisher.prepare(conn, job)
    assert jobs.status(conn, job)["state"] == "WAIT_SOURCE"
    assert count(conn, "sentinel_price_candidates") == 0
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    return job, row


def filtered_fetch(source, monkeypatch):
    def fetch(table, params=None, **kwargs):
        params = params or {}
        source["calls"].append(("fetch", table, params))
        rows = copy.deepcopy(source[table])
        for key in ("ticker", "contraticker", "permaticker", "table", "action"):
            if key in params:
                rows = [r for r in rows if str(r.get(key)) in params[key].split(",")]
        if "date.gte" in params:
            rows = [r for r in rows if params["date.gte"] <= r["date"] <= params["date.lte"]]
        return iter(rows)
    monkeypatch.setattr(sharadar, "fetch_table", fetch)


def test_missing_repeated_probe_then_reviewed_data_recovers_after_restart(conn, source, installed_state, monkeypatch):
    # Keep the real 90% population guard: one absent observation among 20.
    for index in range(3, 21):
        symbol = "SYN" + str(index)
        source["TICKERS"].append({**source["TICKERS"][1], "permaticker": str(index), "ticker": symbol})
        source["SEP"].extend({**row, "ticker": symbol} for row in list(source["SEP"]) if row["ticker"] == "BBB")
    filtered_fetch(source, monkeypatch)
    job, _ = missing(conn, source)
    deadline = jobs.status(conn, job)["deadline"]
    downloads = [c for c in source["calls"] if c[0] == "download"]
    for _ in range(2):
        retry_now(conn, job)
        with pytest.raises(SourceCoveragePending):
            publisher.prepare(conn, job)
    assert [c for c in source["calls"] if c[0] == "download"] == downloads
    assert jobs.status(conn, job)["deadline"] == deadline
    value = addition()
    install(value)
    retry_now(conn, job)
    from sentinel.feed import store
    with store.connect(conn.info.dsn) as restarted:
        result = publisher.prepare(restarted, job)
    manifest = rolling_store.manifest(conn, result["candidate_id"])
    evidence = rolling_store.load_evidence(conn, manifest.source_evidence_sha256)
    assert evidence["source_corrections"] == value
    assert len(list(rolling_store.read_bars(conn, result["candidate_id"]))) == 5999
    assert [c for c in source["calls"] if c[0] == "download"] == downloads
    assert jobs.status(conn, job)["deadline"] == deadline


@pytest.mark.parametrize("scheduled", [False, True])
def test_provider_repair_only_reacquires_affected_partition_with_original_deadline(conn, source, installed_state, monkeypatch, scheduled):
    filtered_fetch(source, monkeypatch)
    job, absent = missing(conn, source)
    deadline = jobs.status(conn, job)["deadline"]
    before = [c for c in source["calls"] if c[0] == "download"]
    # A cached ZIP must not defeat the successful independent repair probe.
    snapshot = rolling_source.snapshot_export.probe_snapshot("SEP", params=before[2][2])
    with acquisition_work.cached_file(snapshot) as path:
        path.write_bytes(b"stale synthetic ZIP")
    source["SEP"].insert(0, absent)
    retry_now(conn, job)
    if scheduled:
        with pytest.raises(jobs.JobWaiting, match="successor queued"):
            preparation_wait.once(conn, job, prepare=publisher.prepare, check_target=lambda: None)
        request = jobs.PreparationRequest.model_validate(jobs.status(conn, job)["request"])
        child = jobs.enqueue(conn, request, budget_seconds=7200)
        conn.commit()
        assert str(conn.execute("SELECT child_job_id FROM sentinel_acquisition_successors WHERE parent_job_id=%s", (job,)).fetchone()[0]) == child
    else:
        with pytest.raises(acquisition_parts.SourceRevision) as changed:
            publisher.prepare(conn, job)
        child = acquisition_parts.successor(conn, job, changed.value.component)
    assert not path.exists()
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    result = publisher.prepare(conn, child)
    assert jobs.status(conn, child)["deadline"] == deadline
    assert len(list(rolling_store.read_bars(conn, result["candidate_id"]))) == 600
    after = [c for c in source["calls"] if c[0] == "download"]
    assert after == before + [before[2]]


def test_wait_hint_corruption_never_waives_source_coverage(conn, source, installed_state):
    job, _ = missing(conn, source)
    conn.execute("UPDATE sentinel_acquisition_source_wait SET payload='{}'::jsonb WHERE job_id=%s", (job,))
    conn.commit()
    retry_now(conn, job)
    with pytest.raises(acquisition_parts.PartCorrupt):
        publisher.prepare(conn, job)
    assert jobs.status(conn, job)["state"] == "REFUSED"
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_wait_deadline_is_terminal_without_republishing_or_extending(conn, source, installed_state, monkeypatch):
    filtered_fetch(source, monkeypatch)
    job, _ = missing(conn, source)
    def expire(_seconds):
        # Simulate elapsed server time; production forbids deadline mutation.
        conn.execute("ALTER TABLE sentinel_snapshot_jobs DISABLE TRIGGER snapshot_job_guard")
        conn.execute("UPDATE sentinel_snapshot_jobs SET created_at=clock_timestamp()-interval '2 hours', "
                     "deadline=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        conn.commit()
        conn.execute("ALTER TABLE sentinel_snapshot_jobs ENABLE TRIGGER snapshot_job_guard")
        conn.commit()
    with pytest.raises(jobs.JobDeadlineExceeded):
        preparation_wait.run(conn, job, prepare=publisher.prepare, check_target=lambda: None, sleep=expire)
    assert jobs.status(conn, job)["reason"] == "DEADLINE_EXHAUSTED"
    assert count(conn, "sentinel_snapshot_comparisons") == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_ready_resume_uses_sealed_corrections_even_if_active_install_is_unavailable(conn, source, installed_state, monkeypatch, legacy):
    original = rolling_source.SharadarSource.corroborate
    payload = rolling_source.SharadarSource.source_payload
    if legacy:
        def old_payload(self):
            value = payload(self)
            value.pop("source_corrections")
            return value
        monkeypatch.setattr(rolling_source.SharadarSource, "source_payload", old_payload)
    def interrupted(self):
        raise KeyboardInterrupt()
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", interrupted)
    job = enqueue(conn)
    with pytest.raises(KeyboardInterrupt):
        publisher.prepare(conn, job)
    before = rolling_store.manifest(conn, jobs.status(conn, job)["candidate_id"])
    monkeypatch.setattr(rolling_source.SharadarSource, "source_payload", payload)
    install(addition())
    (data.root() / "current.json").unlink()
    retry_now(conn, job)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", original)
    result = publisher.prepare(conn, job)
    assert result["snapshot_id"] == before.snapshot_id


def test_reviewed_record_with_wrong_listing_context_cannot_waive_missing_data(conn, source, installed_state, monkeypatch):
    filtered_fetch(source, monkeypatch)
    job, _ = missing(conn, source)
    install(addition(first_observed="2025-07-09"))
    retry_now(conn, job)
    with pytest.raises(SourceCoveragePending):
        publisher.prepare(conn, job)
    assert count(conn, "sentinel_price_candidates") == 0
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_probe_success_but_stale_export_never_publishes_or_resets_retry_bound(conn, source, installed_state, monkeypatch):
    filtered_fetch(source, monkeypatch)
    job, absent = missing(conn, source)
    deadline = jobs.status(conn, job)["deadline"]
    fetch = sharadar.fetch_table
    def corrected_json(table, params=None, **kwargs):
        rows = list(fetch(table, params, **kwargs))
        if table == "SEP":
            rows.append(absent)
        return iter(rows)
    monkeypatch.setattr(sharadar, "fetch_table", corrected_json)
    for index in range(acquisition_parts.MAX_SUCCESSORS + 1):
        retry_now(conn, job)
        with pytest.raises(acquisition_parts.SourceRevision) as changed:
            publisher.prepare(conn, job)
        if index == acquisition_parts.MAX_SUCCESSORS:
            with pytest.raises(acquisition_parts.SourceRecoveryExhausted):
                acquisition_parts.successor(conn, job, changed.value.component)
            conn.rollback()
            break
        job = acquisition_parts.successor(conn, job, changed.value.component)
        with pytest.raises(SourceCoveragePending):
            publisher.prepare(conn, job)  # Independent full export is still missing.
        assert jobs.status(conn, job)["deadline"] == deadline
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    assert count(conn, "sentinel_acquisition_successors") == acquisition_parts.MAX_SUCCESSORS


def test_wait_table_remains_feed_owned_during_behavioral_bootstrap(conn):
    from sentinel import schema
    from sentinel.feed import runtime_schema
    schema.ensure_schema(conn)
    runtime_schema.require_feed_schema(conn)


def test_changed_listing_generation_revalidates_without_requiring_old_missing_price(conn, source, installed_state, monkeypatch):
    from dataclasses import replace
    from datetime import timedelta
    from sentinel.feed import snapshot_export, source_probe
    job, _ = missing(conn, source)
    source["TICKERS"][0]["firstpricedate"] = "2025-07-08"
    probe = snapshot_export.probe_snapshot
    def revised(table, **kwargs):
        result = probe(table, **kwargs)
        return replace(result, refreshed=result.refreshed + timedelta(days=1)) if table == "TICKERS" else result
    monkeypatch.setattr(snapshot_export, "probe_snapshot", revised)
    def should_not_probe(*args, **kwargs):
        pytest.fail("changed listing generation must earn a new full proof first")
    monkeypatch.setattr(source_probe, "require_recovery_probe", should_not_probe)
    retry_now(conn, job)
    with pytest.raises(acquisition_parts.SourceRevision) as caught:
        publisher.prepare(conn, job)
    assert caught.value.component == "TICKERS"
    assert count(conn, "sentinel_snapshot_comparisons") == 0
