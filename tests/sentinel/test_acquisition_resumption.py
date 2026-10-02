"""Production-shaped acquisition recovery; real jobs, source and PostgreSQL."""
from collections import Counter
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from sentinel.feed import rolling_jobs as jobs, rolling_publisher as publisher
from sentinel.feed import rolling_source, sharadar, snapshot_export
from sentinel.feed.rolling_contract import FormationWindow, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source, retry_now

REAL_DOWNLOAD = snapshot_export.download_snapshot
__all__ = ["conn", "pg", "source"]


@pytest.mark.parametrize('large', [False, True])
def test_reference_storage_roundtrip_and_sql_integrity(conn, source, monkeypatch, large):
    import psycopg
    from sentinel.feed import acquisition_parts as parts_module
    from sentinel.feed.rolling_contract import canonical_json
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    monkeypatch.setattr(parts_module, 'JSONB_REFERENCE_BYTES', 32 if large else 4096)
    payload = [{'name': 'canonical \u00e9 reference', 'value': str(i)} for i in range(10)]
    parts = parts_module.Parts(conn, lease)
    manifest, _ = parts.put('ACTIONS', {}, payload=payload, rows=10)
    part_id = digest(manifest)
    row = conn.execute('SELECT reference_payload,canonical_reference FROM sentinel_acquisition_parts '
                       'WHERE part_id=%s', (part_id,)).fetchone()
    assert row == ((None, canonical_json(payload)) if large else (payload, None))
    assert parts.get('ACTIONS', {}) == (manifest, payload)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restarted:
        assert parts_module.Parts(restarted, lease).get('ACTIONS', {}) == (manifest, payload)
    if large:
        # Direct SQL cannot bind different bytes to a valid logical manifest.
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute('INSERT INTO sentinel_acquisition_parts(part_id,manifest,canonical_reference) '
                'VALUES (%s,%s::jsonb,%s)', ('b'*64, canonical_json(manifest), '[]'))
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute('INSERT INTO sentinel_acquisition_parts(part_id,manifest,reference_payload,canonical_reference) '
                'VALUES (%s,%s::jsonb,%s::jsonb,%s)',
                ('b'*64, canonical_json(manifest), canonical_json(payload), canonical_json(payload)))
        conn.rollback()


def test_oversized_reference_refuses_before_part_insert(conn, source, monkeypatch):
    from sentinel.feed import acquisition_parts as parts_module
    from sentinel.feed.acquisition_limits import AcquisitionResourceExceeded
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    monkeypatch.setattr(parts_module, 'MAX_REFERENCE_BYTES', 32)
    with pytest.raises(AcquisitionResourceExceeded, match='ACQUISITION_REFERENCE_BYTES'):
        parts_module.Parts(conn, lease).put('ACTIONS', {}, payload=['x'*40], rows=1)
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_parts').fetchone()[0] == 0


def formation_job(conn, source, *, absolute_deadline=None, operational=False):
    window = FormationWindow.through("2026-09-14")
    source["SEP"] = [dict(ticker=symbol, date=str(day), open="49", close="50",
                          closeunadj="100", volume="10000", lastupdated="2026-09-15")
                     for day in window.sessions for symbol in ("AAA", "BBB")]
    from sentinel.regime.spy import SPY_PRICE_COLUMN
    source["SFP"] = [dict(ticker=symbol, date=str(day), open="50", close="51",
                          closeunadj="51", **{SPY_PRICE_COLUMN: "60"})
                     for day in window.sessions for symbol in ("SPY", "BIL")]
    for row in source["TICKERS"]:
        row["firstpricedate"] = str(window.start)
    strategy = digest(uuid4().hex)
    if operational:
        from sentinel.feed import operational_snapshot as op
        job = op.enqueue(conn, strategy_sha256=strategy,
                         dependencies_sha256=digest({}), budget_seconds=3600)
    else:
        job = jobs.enqueue(conn, jobs.PreparationRequest(window=window,
            strategy_sha256=strategy, dependencies_sha256=digest({})),
            budget_seconds=3600, absolute_deadline=absolute_deadline)
    conn.commit()
    return job


def test_nineteen_partitions_resume_without_repeated_download(conn, source, monkeypatch):
    job = formation_job(conn, source)
    original = snapshot_export.download_snapshot
    downloads = Counter()
    attempted = 0
    def interrupted(snapshot, **kwargs):
        nonlocal attempted
        if snapshot.table == "SEP":
            attempted += 1
            if attempted == 3:
                raise sharadar.SharadarRetryDeferred(1)
        downloads[rolling_source.component(snapshot)] += 1
        return original(snapshot, **kwargs)
    monkeypatch.setattr(snapshot_export, "download_snapshot", interrupted)
    deadline = jobs.status(conn, job)["deadline"]
    with pytest.raises(sharadar.SharadarRetryDeferred):
        publisher.prepare(conn, job)
    retry_now(conn, job)
    publisher.prepare(conn, job)
    assert len([key for key in downloads if key.startswith("SEP.")]) == 19
    assert max(downloads.values()) == 1, downloads
    assert jobs.status(conn, job)["deadline"] == deadline


def drive(conn, job, monkeypatch):
    from sentinel.feed import preparation_wait
    def sleep(_):
        conn.execute("UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() "
                     "WHERE state IN ('WAIT_SOURCE','RETRY_WAIT','INTERRUPTED')")
        conn.commit()
    return preparation_wait.run(conn, job, prepare=publisher.prepare,
                                check_target=lambda: None, sleep=sleep)


def real_exports(source, monkeypatch, tmp_path):
    """Keep actual ZIP parsing, checksum/cache, source validation and staging."""
    import csv
    import io
    import zipfile
    from sentinel.feed import acquisition_work
    monkeypatch.setenv("SENTINEL_STATE_DIR", str(tmp_path))
    downloads = Counter()
    def transfer(client, link, *, details, **kwargs):
        table = details["table"]
        rows = source[table]
        if table == "SEP":
            rows = [r for r in rows if details["date_from"] <= r["date"] <= details["date_to"]]
        key = (table, details["date_from"], details["date_to"])
        downloads[key] += 1
        body = io.StringIO(newline="")
        writer = csv.DictWriter(body, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(table + ".csv", body.getvalue())
        return blob.getvalue()
    monkeypatch.setattr(snapshot_export, "_safe_download", transfer)
    monkeypatch.setattr(snapshot_export, "download_snapshot", REAL_DOWNLOAD)
    return downloads, acquisition_work.cache_root()


def test_repeated_pauses_cache_eviction_and_repackaging_do_not_redownload(conn, source, monkeypatch, tmp_path):
    from dataclasses import replace
    from datetime import timedelta
    job = formation_job(conn, source)
    downloads, cache = real_exports(source, monkeypatch, tmp_path)
    probe = snapshot_export.probe_snapshot
    epoch = [0]
    monkeypatch.setattr(snapshot_export, "probe_snapshot", lambda *a, **kw:
        replace(probe(*a, **kw), snapshot=probe(*a, **kw).snapshot + timedelta(seconds=epoch[0])))
    calls = [0]
    def interrupted(snapshot, **kwargs):
        if snapshot.table == "SEP":
            calls[0] += 1
            if calls[0] % 4 == 0:
                epoch[0] += 1  # Provider repackages unchanged-generation exports.
                for path in cache.glob("*.zip"):
                    path.unlink()  # Retained parts must survive ZIP eviction.
                raise sharadar.SharadarRetryDeferred(1)
        return REAL_DOWNLOAD(snapshot, **kwargs)
    monkeypatch.setattr(snapshot_export, "download_snapshot", interrupted)
    result = drive(conn, job, monkeypatch)
    assert result and epoch[0] >= 5
    assert len(downloads) == 21 and set(downloads.values()) == {1}
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_prices").fetchone()[0] == 758
    assert conn.execute("SELECT COUNT(*) FROM sentinel_snapshot_comparisons").fetchone()[0] == 1


@pytest.mark.parametrize("component", ["TICKERS", "SFP"])
def test_reference_revision_reuses_prices_and_preserves_deadline(conn, source, monkeypatch, component):
    job = formation_job(conn, source)
    deadline = jobs.status(conn, job)["deadline"]
    original = rolling_source.SharadarSource.corroborate
    calls = [0]
    def revised(self):
        calls[0] += 1
        if calls[0] == 1:
            if component == "TICKERS":
                source[component][0]["sector"] = "Healthcare"
            else:
                source[component][0]["open"] = "50.01"
        return original(self)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", revised)
    result = drive(conn, job, monkeypatch)
    child = str(conn.execute("SELECT child_job_id FROM sentinel_acquisition_successors").fetchone()[0])
    assert result and jobs.status(conn, job)["state"] == "REFUSED"
    assert jobs.status(conn, child)["deadline"] == deadline
    downloads = Counter((table, str(params)) for kind, table, params in source["calls"] if kind == "download")
    assert len([key for key in downloads if key[0] == "SEP"]) == 19
    assert all(count == 1 for key, count in downloads.items() if key[0] != component)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_prices").fetchone()[0] == 758


@pytest.mark.parametrize("microsecond", [0, 100000, 123450, 123456])
def test_persistent_reference_instability_stops_at_durable_restart_limit(conn, source, monkeypatch, microsecond):
    from sentinel.feed.acquisition_parts import MAX_SUCCESSORS
    # Exercise PostgreSQL JSON's trimmed fractional seconds independently of
    # whichever microsecond the database clock happens to return in CI.
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    expected_deadline = (now + timedelta(hours=1)).replace(microsecond=microsecond)
    job = formation_job(conn, source, absolute_deadline=expected_deadline)
    deadline = datetime.fromisoformat(jobs.status(conn, job)["deadline"])
    assert deadline == expected_deadline
    original = rolling_source.SharadarSource.corroborate
    counter = [0]
    def revised(self):
        counter[0] += 1
        source["TICKERS"][0]["sector"] = "Healthcare" if counter[0] % 2 else "Technology"
        return original(self)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", revised)
    with pytest.raises(jobs.JobRefused, match="restart limit"):
        drive(conn, job, monkeypatch)
    assert counter[0] == MAX_SUCCESSORS + 1
    states = conn.execute("SELECT state,deadline FROM sentinel_snapshot_jobs").fetchall()
    assert len(states) == MAX_SUCCESSORS + 1
    assert all(state == "REFUSED" for state, _ in states), states
    assert all(stamp == deadline for _, stamp in states), states
    assert conn.execute("SELECT COUNT(*) FROM sentinel_snapshot_comparisons").fetchone()[0] == 0


def test_partial_part_write_and_lost_fence_never_become_reusable(conn, source, monkeypatch):
    from sentinel.feed.acquisition_parts import Parts
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    parts = Parts(conn, lease)
    original = parts._bind
    def killed(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(parts, "_bind", killed)
    with pytest.raises(KeyboardInterrupt):
        parts.put("SEP.2025-03-12.2025-03-31", {}, prices=source["SEP"][:2], rows=2)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_parts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_prices").fetchone()[0] == 0
    monkeypatch.setattr(parts, "_bind", original)
    conn.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
    conn.commit()
    with pytest.raises(jobs.JobRefused, match="fence"):
        parts.put("TICKERS", {}, payload={}, rows=0)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_bindings").fetchone()[0] == 0


@pytest.mark.parametrize("component", ["SEP.2025-03-12.2025-03-31", "TICKERS"])
def test_corrupt_retained_payload_refuses_before_source_io(conn, source, monkeypatch, component):
    from sentinel.feed.acquisition_parts import Parts, PartCorrupt
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    parts = Parts(conn, lease)
    if component == "TICKERS":
        parts.put(component, {}, payload={"value": 1}, rows=1)
        conn.execute("ALTER TABLE sentinel_acquisition_parts DISABLE TRIGGER acquisition_no_update")
        conn.execute("UPDATE sentinel_acquisition_parts SET reference_payload='{}'")
        conn.execute("ALTER TABLE sentinel_acquisition_parts ENABLE TRIGGER acquisition_no_update")
    else:
        parts.put(component, {}, prices=source["SEP"][:2], rows=2)
        conn.execute("ALTER TABLE sentinel_acquisition_prices DISABLE TRIGGER acquisition_no_update")
        conn.execute("UPDATE sentinel_acquisition_prices SET payload=replace(payload,'10000','90000')")
        conn.execute("ALTER TABLE sentinel_acquisition_prices ENABLE TRIGGER acquisition_no_update")
    conn.commit()
    with pytest.raises(PartCorrupt, match="checksum"):
        parts.get(component, {})
    assert source["calls"] == []


def test_sep_refresh_invalidates_old_prices_but_reuses_references(conn, source, monkeypatch):
    from dataclasses import replace
    from datetime import timedelta
    job = formation_job(conn, source)
    download = snapshot_export.download_snapshot
    probe = snapshot_export.probe_snapshot
    revised = [False]
    counts = Counter()
    def refresh(table, **kwargs):
        value = probe(table, **kwargs)
        return replace(value, refreshed=value.refreshed + timedelta(days=1)) if revised[0] and table == "SEP" else value
    def fetch(snapshot, **kwargs):
        counts[rolling_source.component(snapshot)] += 1
        if snapshot.table == "SEP" and sum(v for k, v in counts.items() if k.startswith("SEP.")) == 3:
            revised[0] = True
            raise sharadar.SharadarRetryDeferred(1)
        rows, proof = download(snapshot, **kwargs)
        proof["last_refreshed_time"] = snapshot.refreshed.isoformat()
        return rows, proof
    monkeypatch.setattr(snapshot_export, "probe_snapshot", refresh)
    monkeypatch.setattr(snapshot_export, "download_snapshot", fetch)
    assert drive(conn, job, monkeypatch)
    assert counts["TICKERS"] == counts["ACTIONS.1900-01-01.2026-09-14"] == 1
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_successors").fetchone()[0] == 1
    child = str(conn.execute("SELECT child_job_id FROM sentinel_acquisition_successors").fetchone()[0])
    gens = conn.execute("SELECT DISTINCT a.manifest->'generation'->>'refreshed' "
        "FROM sentinel_acquisition_bindings b JOIN sentinel_acquisition_parts a USING(part_id) "
        "WHERE b.job_id=%s AND b.component LIKE 'SEP.%%'", (child,)).fetchall()
    assert gens == [("2026-09-16T00:00:00+00:00",)]


def test_committed_part_survives_lost_ack_and_new_connection(conn, source, monkeypatch):
    from sentinel.feed.acquisition_parts import Parts
    from sentinel.feed import store
    job = formation_job(conn, source)
    original = Parts.put
    interrupted = [False]
    def after_commit(self, component, *a, **kw):
        value = original(self, component, *a, **kw)
        if component.startswith("SEP.") and not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt()
        return value
    monkeypatch.setattr(Parts, "put", after_commit)
    with pytest.raises(KeyboardInterrupt):
        publisher.prepare(conn, job)
    retry_now(conn, job)
    with store.connect(conn.info.dsn) as restarted:
        assert publisher.prepare(restarted, job)
    counts = Counter((table, str(params)) for kind, table, params in source["calls"] if kind == "download")
    assert set(counts.values()) == {1}


def test_write_rechecks_fence_after_copy(conn, source, monkeypatch):
    from sentinel.feed.acquisition_parts import Parts
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    parts = Parts(conn, lease)
    original = parts._bind
    def expired(component, part_id):
        conn.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' "
                     "WHERE job_id=%s", (job,))
        return original(component, part_id)
    monkeypatch.setattr(parts, "_bind", expired)
    with pytest.raises(jobs.JobRefused, match="fence"):
        parts.put("SEP.2025-03-12.2025-03-31", {}, prices=source["SEP"][:2], rows=2)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_parts").fetchone()[0] == 0


def test_successor_never_renews_exhausted_deadline(conn, source):
    from sentinel.feed.acquisition_parts import successor
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    jobs.finish(conn, lease, state="REFUSED", reason="SOURCE_GENERATION_CHANGED")
    # Simulate elapsed database time without modifying the immutable request in production.
    conn.commit()
    conn.execute("ALTER TABLE sentinel_snapshot_jobs DISABLE TRIGGER snapshot_job_guard")
    conn.execute("UPDATE sentinel_snapshot_jobs SET created_at=clock_timestamp()-interval '2 hours', "
                 "deadline=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
    conn.commit()
    conn.execute("ALTER TABLE sentinel_snapshot_jobs ENABLE TRIGGER snapshot_job_guard")
    conn.commit()
    with pytest.raises(jobs.JobRefused, match="deadline"):
        successor(conn, job, "TICKERS")
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM sentinel_snapshot_jobs").fetchone()[0] == 1


def test_retention_pins_parts_until_successor_finishes(conn, source):
    from sentinel.feed.acquisition_parts import Parts, successor
    from sentinel.feed import retention
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    parts = Parts(conn, lease)
    manifest, _ = parts.put("SEP.2025-03-12.2025-03-31", {}, prices=source["SEP"][:2], rows=2)
    part_id = digest(manifest)
    jobs.finish(conn, lease, state="REFUSED", reason="SOURCE_GENERATION_CHANGED")
    conn.commit()
    # Even cleanup in the publisher's finally cannot race successor creation.
    assert retention.maintain(conn)["status"] == "COMPLETE"
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_prices").fetchone()[0] == 2
    child = successor(conn, job, "TICKERS")
    conn.commit()
    assert retention.maintain(conn)["status"] == "COMPLETE"
    assert conn.execute("SELECT sentinel_acquisition_part_pinned(%s)", (part_id,)).fetchone()[0]
    child_lease = jobs.claim(conn, child, lease_seconds=600)
    jobs.finish(conn, child_lease, state="ABORTED", reason="TEST_FINISHED")
    # Parent remains eligible only until its original deadline passes.
    conn.commit()
    conn.execute("ALTER TABLE sentinel_snapshot_jobs DISABLE TRIGGER snapshot_job_guard")
    conn.execute("UPDATE sentinel_snapshot_jobs SET created_at=clock_timestamp()-interval '2 hours', "
                 "deadline=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
    conn.commit()
    conn.execute("ALTER TABLE sentinel_snapshot_jobs ENABLE TRIGGER snapshot_job_guard")
    conn.commit()
    result = retention.maintain(conn, batch_rows=1)
    assert result["status"] == "COMPLETE" and result["deleted_acquisition_rows"] == 1
    result = retention.maintain(conn, batch_rows=1)
    assert result["status"] == "COMPLETE" and result["deleted_acquisition_rows"] == 1
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_parts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_bindings").fetchone()[0] == 1


def test_price_payload_is_immutable_after_binding(conn, source):
    from sentinel.feed.acquisition_parts import Parts
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    manifest, _ = Parts(conn, lease).put("SEP.2025-03-12.2025-03-31", {}, prices=source["SEP"][:2], rows=2)
    with pytest.raises(Exception, match="cannot receive"):
        conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2025-03-13','CCC','{}')", (digest(manifest),))
    conn.rollback()
    with pytest.raises(Exception, match="immutable"):
        conn.execute("UPDATE sentinel_acquisition_prices SET payload='{}'")
    conn.rollback()


@pytest.mark.parametrize("damage", ["manifest", "binding", "price_key"])
def test_retained_identity_corruption_refuses(conn, source, damage):
    from sentinel.feed.acquisition_parts import Parts, PartCorrupt
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    parts = Parts(conn, lease)
    name = "SEP.2025-03-12.2025-03-31"
    manifest, _ = parts.put(name, {}, prices=source["SEP"][:2], rows=2)
    conn.execute("SET LOCAL session_replication_role=replica")
    if damage == "manifest":
        conn.execute("UPDATE sentinel_acquisition_parts SET manifest="
                     "jsonb_set(manifest,'{evidence}','{}'::jsonb)")
    elif damage == "binding":
        name = "SEP.2025-04-01.2025-04-30"
        conn.execute("INSERT INTO sentinel_acquisition_bindings VALUES(%s,%s,%s)",
                     (job, name, digest(manifest)))
    else:
        conn.execute("UPDATE sentinel_acquisition_prices SET ticker='CORRUPT' WHERE ticker='AAA'")
    conn.commit()
    with pytest.raises(PartCorrupt):
        parts.get(name, {})
    conn.rollback()


def test_repackaged_zip_has_same_content_commitment():
    import hashlib
    from sentinel.feed.acquisition_parts import fingerprint
    from tests.sentinel.test_sharadar_snapshot_export import _zip_csv
    first = _zip_csv("one.csv", "ticker,date,close", [["AAA", "2026-09-14", "50"], ["BBB", "2026-09-14", "51"]])
    second = _zip_csv("two.csv", "ticker,date,close", [["BBB", "2026-09-14", "51"], ["AAA", "2026-09-14", "50"]])
    assert hashlib.sha256(first).digest() != hashlib.sha256(second).digest()
    rows = [snapshot_export._csv_rows(blob, required={"ticker", "date", "close"}) for blob in (first, second)]
    assert fingerprint(rows[0]) == fingerprint(rows[1])
    rows[1][0]["close"] = "52"
    assert fingerprint(rows[0]) != fingerprint(rows[1])


def test_reordered_ticker_export_has_same_content_commitment(conn, source):
    from sentinel.feed.retained_source import RetainedSource
    commitments = []
    for _ in range(2):
        job = formation_job(conn, source)
        lease = jobs.claim(conn, job, lease_seconds=600)
        conn.commit()
        acquired = RetainedSource(FormationWindow.through("2026-09-14"), conn, lease)
        acquired.preflight()
        acquired.references(lambda *args: None)
        commitments.append(conn.execute("SELECT manifest->>'content_sha256' "
            "FROM sentinel_acquisition_parts a JOIN sentinel_acquisition_bindings b USING(part_id) "
            "WHERE b.job_id=%s AND b.component='TICKERS'", (job,)).fetchone()[0])
        source["TICKERS"].reverse()
    assert commitments[0] == commitments[1]


def test_progress_distinguishes_reuse_from_download(conn, source, monkeypatch, capsys):
    import os
    import runpy
    from pathlib import Path
    job = formation_job(conn, source)
    original = snapshot_export.download_snapshot
    calls = [0]
    def pause(snapshot, **kwargs):
        if snapshot.table == "SEP":
            calls[0] += 1
            if calls[0] == 2:
                raise sharadar.SharadarRetryDeferred(1)
        return original(snapshot, **kwargs)
    monkeypatch.setattr(snapshot_export, "download_snapshot", pause)
    drive(conn, job, monkeypatch)
    root = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
    collect = runpy.run_path(str(root / "scripts/sentinel_go_feed_progress.py"))["collect"]
    events = collect(capsys.readouterr().err)
    assert any(e.get("reason") == "RETAINED_PART_REUSED" and e.get("part") == 1 for e in events)
    assert any(e.get("reason") == "PART_COMMITTED" and e.get("part") == 19 for e in events)


def test_retained_price_reader_preserves_exact_source_decimals(conn, source):
    from sentinel.feed.acquisition_parts import Parts, price_rows
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    rows = [{**source["SEP"][0], "open": "49.123456789123456789", "volume": "10000.000000001"}]
    Parts(conn, lease).put("SEP.2025-03-12.2025-03-31", {}, prices=rows, rows=1)
    recovered = list(price_rows(conn, job))
    assert len(recovered) == 1
    assert str(recovered[0]["open"]) == rows[0]["open"]
    assert str(recovered[0]["volume"]) == rows[0]["volume"]


def test_retained_equity_reader_excludes_total_return_price(conn, source):
    from sentinel.feed.acquisition_parts import Parts, price_rows
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    conn.commit()
    rows = [{**source["SEP"][0], "closeadj": "987654321.123456789"}]
    Parts(conn, lease).put("SEP.2025-03-12.2025-03-31", {}, prices=rows, rows=1)
    recovered = list(price_rows(conn, job))
    assert len(recovered) == 1
    assert set(recovered[0]) == {"date", "ticker", "open", "close", "closeunadj", "volume"}
    assert str(recovered[0]["close"]) == rows[0]["close"]
    assert str(recovered[0]["closeunadj"]) == rows[0]["closeunadj"]


def test_old_hash_only_job_is_preserved_and_superseded_without_operator_reset(conn, source, monkeypatch):
    job = formation_job(conn, source)
    lease = jobs.claim(conn, job, lease_seconds=600)
    snapshot = snapshot_export.probe_snapshot("ACTIONS", params={"date.gte": "1900-01-01", "date.lte": "2026-09-14"})
    jobs.checkpoint(conn, lease, component=rolling_source.component(snapshot),
                    generation_sha256=digest(rolling_source.generation(snapshot)),
                    artifact_sha256="a" * 64, rows=len(source["ACTIONS"]), bytes_=0)
    jobs.wait(conn, lease, state="INTERRUPTED", reason="WORKER_INTERRUPTED", retry_seconds=1)
    conn.commit()
    retry_now(conn, job)
    assert drive(conn, job, monkeypatch)
    assert jobs.status(conn, job)["state"] == "REFUSED"
    assert jobs.components(conn, job)[0]["artifact_sha256"] == "a" * 64
    assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_successors").fetchone()[0] == 1


@pytest.mark.parametrize("script", ["sentinel_go_validate_entry", "sentinel_go_24x7_entry"])
def test_go_reports_specific_acquisition_failures(script, monkeypatch):
    import importlib
    import os
    from pathlib import Path
    from sentinel.feed.acquisition_parts import PartCorrupt, SourceRecoveryExhausted, SourceRevision
    root = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
    monkeypatch.syspath_prepend(str(root / "scripts"))
    module = importlib.import_module(script)
    # Exercise the same embedded child reason mapper as the production process.
    import ast
    constants = [getattr(module, name) for name in dir(module)
                 if name.endswith("CODE") and isinstance(getattr(module, name), str)]
    program = next(text for text in constants if "def reason_code(" in text)
    parsed = ast.parse(program)
    definition = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "reason_code")
    namespace = {}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "reason-code", "exec"), namespace)
    classify = namespace["reason_code"]
    assert classify("DAILY_CATCHUP", PartCorrupt("bad checksum")) == "ACQUISITION_PART_CORRUPT"
    assert classify("DAILY_CATCHUP", SourceRevision("TICKERS", "a" * 64, "b" * 64)) == "SOURCE_PUBLICATION_UNSTABLE"
    assert classify("DAILY_CATCHUP", SourceRecoveryExhausted("limit")) == "SOURCE_RECOVERY_EXHAUSTED"


@pytest.mark.parametrize("boundaries,renewal_failure", [
    pytest.param(("ACQUIRING",), None, id="acquiring"),
    pytest.param(("READY",), None, id="ready"),
    pytest.param(("ACQUIRING", "READY"), None, id="both"),
    pytest.param(("ACQUIRING",), "copy", id="copy-failed"),
    pytest.param(("ACQUIRING",), "interrupt", id="interrupted"),
])
def test_go_renews_after_real_retained_acquisition_without_redownload(
        conn, source, monkeypatch, tmp_path, boundaries, renewal_failure):
    """Compose the host overlay, real child failure codec and SQL worker resume.

    External provider/backup subprocesses are replaced; persistence, decoding,
    runtime ceiling arithmetic, candidate building and publication are real.
    """
    import io
    import json
    import psycopg
    from contextlib import redirect_stdout, redirect_stderr
    from sentinel import backup_runtime_authority as authority
    from sentinel.feed import operational_snapshot as op, retention
    from tests.sentinel.test_go_backup_refresh import (
        backup, GrowingWalRunner, _cp, TOKEN, run_overlay, successful_child)
    import sentinel_go_24x7_entry as entry
    from sentinel_go_backup_retry import RESUME_ENV

    window = FormationWindow.through("2026-09-14")
    monkeypatch.setattr(op, "source_final_session", lambda: str(window.end))
    monkeypatch.setattr(op, "acquisition_window", lambda *a: window)
    job = formation_job(conn, source, operational=True)
    state = jobs.status(conn, job)
    strategy = state["request"]["strategy_sha256"]
    deadline = state["deadline"]
    downloads, _ = real_exports(source, monkeypatch, tmp_path)
    monkeypatch.setitem(backup.phase._PHASE, "certified", True)
    monkeypatch.setattr(backup.go_lock, "lifecycle_lock_is_held", lambda *a: True)
    monkeypatch.setattr(backup.go_lock, "current_run_token", lambda *a: TOKEN)
    monkeypatch.setattr(backup, "_AUDIT_PATH", tmp_path / "audit.json")
    original_require = authority.require
    renewed = []
    paused = []
    in_failure = [False]

    def horizon(c, *, operation, **kwargs):
        current = jobs.status(c, job)
        # 19 monthly SEP parts plus ACTIONS, TICKERS, SFP, all committed.
        completed = len(jobs.components(c, job)) == 22
        due = len(renewed) < len(boundaries) and current["state"] == boundaries[len(renewed)]
        if completed and due and not in_failure[0]:
            authority._expected_wals("000000010000000000000000", "000000010000000000000040",
                                     segment_size=16 * 1024 * 1024)
        return original_require(c, operation=operation, **kwargs)
    monkeypatch.setattr(authority, "require", horizon)

    class Runner(GrowingWalRunner):
        def run(self, argv, *, env=None, cwd=None):
            if list(argv)[:2] != ["docker", "compose"]:
                if "scripts/sentinel-base-backup.sh" in argv:
                    if renewal_failure == "copy":
                        return _cp(4)
                    if renewal_failure == "interrupt":
                        raise KeyboardInterrupt
                result = super().run(argv, env=env, cwd=cwd)
                if "--backup" in argv and result.returncode == 0:
                    renewed.append(True)
                return result
            self.preparations.append((list(argv), dict(env)))
            out, err = io.StringIO(), io.StringIO()
            with psycopg.connect(conn.info.dsn) as worker, redirect_stdout(out), redirect_stderr(err):
                if RESUME_ENV in env:
                    selected = op.enqueue(worker, strategy_sha256=strategy,
                        dependencies_sha256=digest({}), resume_job_id=env[RESUME_ENV])
                    assert selected == job
                    worker.commit()
                    retry_now(worker, job)
                try:
                    result = op.prepare(worker, job)
                except authority.BackupHorizonExceeded as exc:
                    held = jobs.status(worker, job)
                    assert held["state"] == "RETRY_WAIT"
                    assert held["resume_state"] == boundaries[len(renewed)]
                    assert held["owner"] is None and held["deadline"] == deadline
                    assert exc.resume_job_id == job
                    paused.append(held["resume_state"])
                    worker.rollback()
                    # Successful maintenance while waiting must not retire parts.
                    in_failure[0] = True
                    assert retention.maintain(worker)["deleted_acquisition_parts"] == 0
                    in_failure[0] = False
                    namespace = {}
                    exec(entry._PREPARATION_CODE.split("\nc = None", 1)[0], namespace)
                    namespace.update(schema_attempted=True, daily_attempted=True)
                    namespace["emit_failure"]("DAILY_CATCHUP", exc)
                    return _cp(1, out=out.getvalue(), err=err.getvalue())
                assert result["scope"] == "DATA_ONLY"
                success = successful_child()
                success.stderr = err.getvalue()
                return success

    runner = Runner([])
    if renewal_failure is not None:
        if renewal_failure == "interrupt":
            with pytest.raises(KeyboardInterrupt):
                run_overlay(monkeypatch, runner)
        else:
            assert not run_overlay(monkeypatch, runner).complete
        held = jobs.status(conn, job)
        assert held["state"] == "RETRY_WAIT" and held["deadline"] == deadline
        assert held["owner"] is None and len(runner.preparations) == 1
        assert len(jobs.components(conn, job)) == 22
        assert conn.execute("SELECT COUNT(*) FROM sentinel_acquisition_prices").fetchone()[0] == 758
        # A later host invocation can still use the exact durable work.
        renewal_failure = None
        retry_now(conn, job)
    summary = run_overlay(monkeypatch, runner)
    assert summary.complete
    assert paused[-len(boundaries):] == list(boundaries) and len(renewed) == len(boundaries)
    assert jobs.status(conn, job)["state"] == "PUBLISHED"
    assert jobs.status(conn, job)["deadline"] == deadline
    assert conn.execute("SELECT COUNT(*) FROM sentinel_snapshot_jobs").fetchone()[0] == 1
    assert len(downloads) == 21 and set(downloads.values()) == {1}, downloads
    assert "RETAINED_PART_REUSED" in runner.last_preparation_output
    audit = json.loads((tmp_path / "audit.json").read_text())
    assert audit["status"] == "PASS"
