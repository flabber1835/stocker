"""Direct source-to-candidate integration and failure isolation on real Postgres."""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from sentinel.feed import (
    coherence, rolling_builder as builder, rolling_jobs as jobs,
    rolling_publisher as publisher, rolling_source, rolling_store,
    runtime_schema, sharadar, snapshot_export, store,
)
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.regime.spy import SPY_PRICE_COLUMN
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg):
    import psycopg
    from psycopg import sql
    database = "rolling_" + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    c = store.connect(pg.sync_dsn.rsplit("/", 1)[0] + "/" + database)
    runtime_schema.migrate_feed_schema(c)
    try:
        yield c
    finally:
        c.close()
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


@pytest.fixture
def source(monkeypatch):
    window = PriceWindow.through("2026-09-14")
    tickers = [{"table": "SEP", "permaticker": str(index), "ticker": symbol,
                "category": "Domestic Common Stock", "relatedtickers": None,
                "firstpricedate": str(window.start), "lastpricedate": str(window.end),
                "isdelisted": "N", "sector": "Technology"}
               for index, symbol in enumerate(("AAA", "BBB"), 1)]
    prices = [{"ticker": symbol, "date": str(day), "open": "49", "close": "50",
               "closeunadj": "100", "volume": "10000", "lastupdated": "2026-09-15"}
              for day in window.sessions for symbol in ("AAA", "BBB")]
    sfp = [{"ticker": symbol, "date": str(day), "open": "50", "close": "51",
            "closeunadj": "51", SPY_PRICE_COLUMN: "60"}
           for day in window.sessions for symbol in ("SPY", "BIL")]
    data = {"SEP": prices, "TICKERS": tickers, "SFP": sfp,
            "ACTIONS": [{"ticker": "AAA", "date": str(window.sessions[5]),
                         "action": "dividend", "name": "Alpha", "value": "1",
                         "contraticker": None, "contraname": None}]}
    from sentinel.feed.source_authority.corporate_action_data import CASH_ADJUDICATION_AUTHORITIES
    data["ACTIONS"].extend({"ticker": record["ticker"], "date": record["source_action_date"],
                            "action": record["source_action"], "name": "reviewed fixture",
                            "value": record["stale_source_amount"], "contraticker": None,
                            "contraname": None} for record in CASH_ADJUDICATION_AUTHORITIES)
    data["calls"] = []
    refreshed = datetime(2026, 9, 15, tzinfo=timezone.utc)

    def probe(table, *, params=None, **kwargs):
        data["calls"].append(("probe", table, params))
        return snapshot_export.ExportSnapshot(table, dict(params or {}), "redacted-test-url",
                                               refreshed, refreshed)

    def fetch(table, params=None, **kwargs):
        data["calls"].append(("fetch", table, params))
        return iter(copy.deepcopy(data[table]))

    def download(snapshot, **kwargs):
        data["calls"].append(("download", snapshot.table, snapshot.params))
        rows = copy.deepcopy(data[snapshot.table])
        if snapshot.table == "SEP":
            rows = [r for r in rows if snapshot.params["date.gte"] <= r["date"]
                    <= snapshot.params["date.lte"]]
        return rows, {"last_refreshed_time": refreshed.isoformat(),
                      "window": dict(snapshot.params), "file_sha256": digest(rows)}

    monkeypatch.setattr(snapshot_export, "probe_snapshot", probe)
    monkeypatch.setattr(snapshot_export, "download_snapshot", download)
    monkeypatch.setattr(sharadar, "fetch_table", fetch)
    monkeypatch.setattr(rolling_source.calendar, "latest_closed_session", lambda: "2026-09-14")
    # Tiny universe only; every domain/structural/negative-space guard stays on.
    monkeypatch.setattr(coherence, "MIN_SEED_SESSION_ROWS", 1)
    monkeypatch.setattr(publisher.identity, "require_feed_producer_identity",
                        lambda: {"schema": "test-producer", "commit": "fixture"})
    return data


def enqueue(conn, end="2026-09-14"):
    request = jobs.PreparationRequest(window=PriceWindow.through(end),
                                      strategy_sha256=digest(uuid.uuid4().hex),
                                      dependencies_sha256=digest({}))
    job = jobs.enqueue(conn, request, budget_seconds=120)
    conn.commit()
    return job


def retry_now(conn, job):
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s", (job,))
    conn.commit()


def count(conn, table):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM " + table)
        return cur.fetchone()[0]


def test_direct_complete_candidate_is_isolated_and_idempotent(conn, source):
    job = enqueue(conn)
    result = publisher.prepare(conn, job)
    assert result["scope"] == "COMPARISON_ONLY"
    assert count(conn, "sentinel_corpus_publications") == 0
    assert count(conn, "sentinel_bars") == 0
    assert count(conn, "sentinel_actions") == 0
    bars = list(rolling_store.read_bars(conn, result["candidate_id"]))
    assert len(bars) == 600
    assert bars[0].open_unadjusted == 98 and bars[0].volume == 5000
    assert bars[10].dividend_per_share == 2
    assert len(list(rolling_store.read_benchmarks(conn, result["candidate_id"]))) == 300
    assert rolling_store.verify_content(conn, result["candidate_id"]).snapshot_id == result["snapshot_id"]
    state = jobs.status(conn, job)
    assert state["state"] == "READY" and state["reason"] == "COMPARISON_ONLY"
    assert state["publication_version"] is None and state["owner"] is None
    calls = list(source["calls"])
    assert publisher.prepare(conn, job) == result
    assert source["calls"] == calls  # Lost acknowledgement does not refetch or republish.
    with pytest.raises(jobs.JobRefused):
        jobs.claim(conn, job)
    conn.rollback()
    assert not jobs.expire(conn, job)
    prices = [params for kind, table, params in calls if kind == "download" and table == "SEP"]
    assert prices[0]["date.gte"] == str(PriceWindow.through("2026-09-14").start)
    assert prices[-1]["date.lte"] == "2026-09-14"
    assert len(prices) == len({str(params) for params in prices})
    runtime_schema.require_feed_schema(conn)


@pytest.mark.parametrize("defect", ["missing_equity", "missing_benchmark", "duplicate", "raw", "ambiguous_split"])
def test_bad_source_never_publishes(conn, source, defect):
    if defect == "missing_equity":
        # Preserve total count and healthy domains: only the independent
        # eligible denominator can see the missing common-equity observation.
        source["SEP"][40]["ticker"] = "CCC"
        source["TICKERS"].append({**source["TICKERS"][0], "ticker": "CCC", "permaticker": "3",
                                  "category": "ETF"})
    elif defect == "missing_benchmark":
        source["SFP"].pop(40)
    elif defect == "duplicate":
        source["SEP"].append(source["SEP"][40])
    elif defect == "raw":
        source["SEP"][40]["closeunadj"] = None
    else:
        source["ACTIONS"] += [{**source["ACTIONS"][0], "action": "split", "value": value}
                              for value in ("2", "3")]
    job = enqueue(conn)
    match = {"missing_equity": "eligible-set", "missing_benchmark": "SPY/BIL",
             "duplicate": "duplicate", "raw": "raw close", "ambiguous_split": "ambiguous"}[defect]
    with pytest.raises(Exception, match=match):
        publisher.prepare(conn, job)
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    assert count(conn, "sentinel_price_candidates") == 0
    assert jobs.status(conn, job)["state"] == "REFUSED"


def test_pending_export_is_durable_wait_without_new_deadline(conn, source, monkeypatch):
    job = enqueue(conn)
    deadline = jobs.status(conn, job)["deadline"]
    original = snapshot_export.probe_snapshot
    def pending(table, **kwargs):
        raise snapshot_export.ExportPending(table, "creating", kwargs.get("params"))
    monkeypatch.setattr(snapshot_export, "probe_snapshot", pending)
    with pytest.raises(snapshot_export.ExportPending):
        publisher.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state["state"] == "WAIT_SOURCE" and state["owner"] is None
    assert state["deadline"] == deadline and count(conn, "sentinel_price_candidates") == 0
    retry_now(conn, job)
    monkeypatch.setattr(snapshot_export, "probe_snapshot", original)
    publisher.prepare(conn, job)
    assert jobs.status(conn, job)["deadline"] == deadline


@pytest.mark.parametrize("boundary", ["seal", "ready"])
def test_crash_restarts_from_durable_components_or_ready(conn, source, monkeypatch, boundary):
    job = enqueue(conn)
    deadline = jobs.status(conn, job)["deadline"]
    owner = rolling_store if boundary == "seal" else rolling_source.SharadarSource
    name = "seal" if boundary == "seal" else "corroborate"
    original = getattr(owner, name)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(owner, name, crash)
    with pytest.raises(KeyboardInterrupt):
        publisher.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state["state"] == "INTERRUPTED"
    assert state["resume_state"] == ("ACQUIRING" if boundary == "seal" else "READY")
    assert len(jobs.components(conn, job)) > 10
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    assert count(conn, "sentinel_price_candidates") == (0 if boundary == "seal" else 1)
    retry_now(conn, job)
    monkeypatch.setattr(owner, name, original)
    publisher.prepare(conn, job)
    assert count(conn, "sentinel_price_candidates") == 1
    assert jobs.status(conn, job)["deadline"] == deadline


def test_corroboration_refuses_changed_ticker_fields(conn, source, monkeypatch):
    original = rolling_source.SharadarSource.corroborate
    def changed(self):
        source["TICKERS"][0]["relatedtickers"] = ""  # NULL is not observed empty.
        return original(self)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", changed)
    job = enqueue(conn)
    with pytest.raises(rolling_source.authority.VendorPublicationUnstable, match="TICKERS"):
        publisher.prepare(conn, job)
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    assert count(conn, "sentinel_price_candidates") == 1  # Sealed but invisible.


def test_corroboration_refuses_changed_refresh(conn, source, monkeypatch):
    original = rolling_source.SharadarSource.corroborate
    probe = snapshot_export.probe_snapshot
    def changed(self):
        from dataclasses import replace
        monkeypatch.setattr(snapshot_export, "probe_snapshot", lambda *a, **kw:
                            replace(probe(*a, **kw), refreshed=self.snapshots[0].refreshed + timedelta(days=1)))
        return original(self)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", changed)
    with pytest.raises(rolling_source.authority.VendorPublicationUnstable, match="refresh"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_compare_and_swap_loser_preserves_winner(conn, source, monkeypatch):
    first, second = enqueue(conn), enqueue(conn)
    original = rolling_source.SharadarSource.corroborate
    winner = {}
    def concurrent(self):
        monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", original)
        with store.connect(conn.info.dsn) as other:
            winner.update(publisher.prepare(other, second))
        return original(self)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", concurrent)
    with pytest.raises(publisher.ComparisonRefused, match="expected generation"):
        publisher.prepare(conn, first)
    assert count(conn, "sentinel_snapshot_comparisons") == 1
    assert publisher.published(conn, second) == winner
    assert publisher.published(conn, first) is None


def test_publication_transaction_rolls_back_before_visibility(conn, source, monkeypatch):
    original = publisher.published
    def fail_ack(conn, job):
        value = original(conn, job)
        if value:
            raise RuntimeError("injected before commit")
        return value
    monkeypatch.setattr(publisher, "published", fail_ack)
    with pytest.raises(RuntimeError, match="before commit"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 0
    assert count(conn, "sentinel_corpus_publications") == 0


def test_producer_refusal_happens_before_source_io(conn, source, monkeypatch):
    def refused():
        raise RuntimeError("producer refused")
    monkeypatch.setattr(publisher.identity, "require_feed_producer_identity", refused)
    with pytest.raises(RuntimeError, match="producer refused"):
        publisher.prepare(conn, enqueue(conn))
    assert not source["calls"]
    assert count(conn, "sentinel_price_candidates") == 0


def test_backup_refusal_happens_before_source_io(conn, source, monkeypatch):
    def refused(*a, **kw):
        raise RuntimeError("backup refused")
    monkeypatch.setattr(store.backup_runtime_authority, "require", refused)
    with pytest.raises(RuntimeError, match="backup refused"):
        publisher.prepare(conn, enqueue(conn))
    assert not source["calls"]
    assert count(conn, "sentinel_price_candidates") == 0


def test_legacy_publication_change_invalidates_ready(conn, source, monkeypatch):
    original = rolling_source.SharadarSource.corroborate
    def changed(self):
        original(self)
        monkeypatch.setattr(publisher, "_legacy_version", lambda conn: 42)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", changed)
    with pytest.raises(publisher.ComparisonRefused, match="legacy publication changed during"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_ready_checkpoint_changed_content_refuses(conn, source, monkeypatch):
    original = rolling_source.SharadarSource.corroborate
    def interrupted(self):
        raise KeyboardInterrupt()
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", interrupted)
    job = enqueue(conn)
    with pytest.raises(KeyboardInterrupt):
        publisher.prepare(conn, job)
    source["SEP"][40]["volume"] = "11000"
    retry_now(conn, job)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", original)
    with pytest.raises(publisher.ComparisonRefused, match="checkpoint changed"):
        publisher.prepare(conn, job)
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_acquisition_resume_checks_completed_components(conn, source, monkeypatch):
    original = snapshot_export.download_snapshot
    calls = [0]
    def interrupted(snapshot, **kwargs):
        if snapshot.table == "SEP":
            calls[0] += 1
            if calls[0] == 3:
                raise sharadar.SharadarRetryDeferred(10)
        return original(snapshot, **kwargs)
    monkeypatch.setattr(snapshot_export, "download_snapshot", interrupted)
    job = enqueue(conn)
    with pytest.raises(sharadar.SharadarRetryDeferred):
        publisher.prepare(conn, job)
    assert jobs.status(conn, job)["state"] == "RETRY_WAIT"
    completed = jobs.components(conn, job)
    assert len(completed) == 5
    retry_now(conn, job)
    monkeypatch.setattr(snapshot_export, "download_snapshot", original)
    publisher.prepare(conn, job)
    assert all(item in jobs.components(conn, job) for item in completed)


def test_corroboration_refuses_changed_benchmark(conn, source, monkeypatch):
    original = rolling_source.SharadarSource.corroborate
    def changed(self):
        source["SFP"][40][SPY_PRICE_COLUMN] = "60.01"
        original(self)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", changed)
    with pytest.raises(rolling_source.authority.VendorPublicationUnstable, match="SPY/BIL"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_preflight_refuses_mixed_sep_refreshes(source, monkeypatch):
    from dataclasses import replace
    original = snapshot_export.probe_snapshot
    calls = [0]
    def mixed(table, **kwargs):
        snapshot = original(table, **kwargs)
        if table == "SEP":
            calls[0] += 1
            if calls[0] == 2:
                return replace(snapshot, refreshed=snapshot.refreshed + timedelta(days=1))
        return snapshot
    monkeypatch.setattr(snapshot_export, "probe_snapshot", mixed)
    with pytest.raises(rolling_source.authority.VendorPublicationUnstable, match="partitions"):
        rolling_source.SharadarSource(PriceWindow.through("2026-09-14")).preflight()


def test_source_rejects_unclosed_target(source, monkeypatch):
    monkeypatch.setattr(rolling_source.calendar, "latest_closed_session", lambda: "2026-09-11")
    with pytest.raises(ValueError, match="closed XNYS"):
        rolling_source.SharadarSource(PriceWindow.through("2026-09-14")).preflight()
    assert source["calls"] == []


def test_benchmark_key_guard_is_exact(source):
    with pytest.raises(ValueError, match="every session exactly"):
        list(builder.benchmarks(PriceWindow.through("2026-09-14"), source["SFP"][:-1]))


def test_post_validation_lease_is_rechecked(conn, source, monkeypatch):
    # Expire the real database lease after proof loading; the immutable request
    # deadline is never rewritten to make the fixture convenient.
    original_put = rolling_store.put_evidence
    def put(conn, payload):
        result = original_put(conn, payload)
        if payload.get("schema") == "test-producer":
            conn.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' "
                         "WHERE owner IS NOT NULL")
        return result
    monkeypatch.setattr(rolling_store, "put_evidence", put)
    with pytest.raises(jobs.JobRefused, match="fence"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 0


def test_comparison_catalog_is_immutable(conn, source):
    import psycopg
    publisher.prepare(conn, enqueue(conn))
    for table in ("sentinel_snapshot_comparisons", "sentinel_snapshot_attempts",
                  "sentinel_snapshot_validations"):
        for statement in ("DELETE FROM " + table, "TRUNCATE " + table + " CASCADE"):
            with pytest.raises(psycopg.Error, match="immutable"):
                with conn.transaction():
                    conn.execute(statement)
        assert count(conn, table) == 1


def test_old_comparison_cannot_replace_newer_frontier(conn, source, monkeypatch):
    result = publisher.prepare(conn, enqueue(conn))
    latest = publisher._latest(conn)
    monkeypatch.setattr(publisher, "_latest", lambda conn: (latest[0], latest[1] + timedelta(days=1)))
    with pytest.raises(publisher.ComparisonRefused, match="older window"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 1
    assert publisher.published(conn, result["job_id"]) == result


def test_retry_after_is_not_shortened(conn, source, monkeypatch):
    def rate_limit(*a, **kw):
        raise sharadar.SharadarRetryDeferred(45, 429)
    monkeypatch.setattr(snapshot_export, "probe_snapshot", rate_limit)
    job = enqueue(conn)
    with pytest.raises(sharadar.SharadarRetryDeferred):
        publisher.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state["state"] == "RETRY_WAIT"
    assert (datetime.fromisoformat(state["next_retry"]) - datetime.fromisoformat(state["updated_at"])).total_seconds() >= 45


def test_writer_contention_is_a_durable_retry(conn, source):
    from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusBusy
    job = enqueue(conn)
    with store.connect(conn.info.dsn) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (CORPUS_LOCK_KEY,))
        with pytest.raises(CorpusBusy):
            publisher.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state["state"] == "RETRY_WAIT" and state["reason"] == "CORPUS_WRITER_BUSY"
    assert source["calls"] == []


def test_source_network_is_outside_common_writer_lock(conn, source, monkeypatch):
    from sentinel.feed.publication import CORPUS_LOCK_KEY
    def checked(call):
        def wrapped(*a, **kw):
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' "
                            "AND pid=pg_backend_pid() AND granted AND mode='ExclusiveLock' "
                            "AND ((classid::bigint << 32) | objid::bigint)=%s", (CORPUS_LOCK_KEY,))
                assert cur.fetchone()[0] == 0
            return call(*a, **kw)
        return wrapped
    monkeypatch.setattr(snapshot_export, "probe_snapshot", checked(snapshot_export.probe_snapshot))
    monkeypatch.setattr(snapshot_export, "download_snapshot", checked(snapshot_export.download_snapshot))
    monkeypatch.setattr(sharadar, "fetch_table", checked(sharadar.fetch_table))
    publisher.prepare(conn, enqueue(conn))


def test_missing_independent_ticker_key_refuses(conn, source, monkeypatch):
    original = sharadar.fetch_table
    def partial(table, params=None, **kw):
        rows = list(original(table, params, **kw))
        return iter(rows[:1] if table == "TICKERS" else rows)
    monkeypatch.setattr(sharadar, "fetch_table", partial)
    with pytest.raises(snapshot_export.SharadarSnapshotExportError, match="key set disagrees"):
        publisher.prepare(conn, enqueue(conn))
    assert count(conn, "sentinel_snapshot_comparisons") == 0
