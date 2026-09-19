"""Real rolling GO data probes cannot grant legacy strategy authority."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
import sys

import pytest

from sentinel import rolling_checkpoint
from sentinel.feed import rolling_go_inputs as inputs, rolling_go_health as health
from sentinel.feed import operational_snapshot as snapshots, rolling_jobs, publication
from tools import sentinel_operational_parity as parity
from tests.sentinel.test_rolling_initialization import ready, OBS  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

TARGET = "2026-09-14"


@pytest.fixture
def issuer_source(operational_source):
    operational_source["TICKERS"][0]["relatedtickers"] = "AAA BBB"
    return operational_source


@pytest.fixture
def published(issuer_source, ready):
    return ready


def _read_only(conn):
    inputs.require_schemas(conn)
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def test_first_prepare_is_idempotent_without_behavioral_state(conn, issuer_source):
    from sentinel import schema
    schema.ensure_schema(conn)
    first = inputs.prepare(conn, target_session=TARGET)
    calls = list(issuer_source["calls"])
    again = inputs.prepare(conn, target_session=TARGET)
    assert first["status"] == "PUBLISHED" and again["status"] == "ALREADY_CURRENT"
    assert first["snapshot_id"] == again["snapshot_id"]
    assert issuer_source["calls"] == calls
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 1


def test_preparation_retry_reuses_job_and_original_deadline(conn, issuer_source, monkeypatch):
    from sentinel import schema
    schema.ensure_schema(conn)
    seen = []
    def interrupted(conn, job):
        seen.append(rolling_jobs.status(conn, job))
        raise ConnectionError("worker interrupted before claim")
    monkeypatch.setattr(snapshots, "prepare", interrupted)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            inputs.prepare(conn, target_session=TARGET)
    assert seen[0]["job_id"] == seen[1]["job_id"]
    assert seen[0]["deadline"] == seen[1]["deadline"]


def test_source_final_target_cannot_be_selected_by_caller(conn, issuer_source):
    from sentinel import schema
    schema.ensure_schema(conn)
    with pytest.raises(inputs.RollingGoRefused, match="SOURCE_FINAL"):
        inputs.prepare(conn, target_session="2026-09-15")
    assert conn.execute("SELECT COUNT(*) FROM sentinel_snapshot_jobs").fetchone()[0] == 0


def test_failed_attempt_book_is_preserved_and_not_adopted(conn, published):
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('catchup',%s,'{}')", (TARGET,))
    conn.commit()
    with pytest.raises(rolling_checkpoint.RollingColdStartRefused, match="EXISTING_STRATEGY"):
        inputs.prepare(conn, target_session=TARGET)
    assert conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name='catchup'").fetchone()[0] == {}


def test_readiness_reads_snapshot_without_legacy_tables(conn, published, monkeypatch):
    monkeypatch.setattr(publication, "current", lambda *_a, **_k: pytest.fail("legacy reader"))
    _read_only(conn)
    report = inputs.readiness(conn)
    assert report.ready and len(report.checks) >= 10
    assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
    assert all(check.status == "PASS" for check in report.checks)


def test_readiness_refuses_stale_frontier(conn, published, monkeypatch):
    monkeypatch.setattr(inputs.calendar, "latest_closed_session", lambda now=None: "2026-09-15")
    _read_only(conn)
    with pytest.raises(inputs.RollingGoRefused, match="source-final"):
        inputs.readiness(conn, now=datetime(2026, 9, 16, 4, tzinfo=timezone.utc))


@pytest.mark.parametrize("defect", ["domain", "warmup", "population", "issuer", "bil"])
def test_readiness_checks_canonical_current_inputs(conn, published, monkeypatch, defect):
    original = inputs.cold_start_inputs
    def changed(*a, **k):
        material = original(*a, **k)
        if defect == "domain":
            return replace(material, bars=tuple(replace(bar, raw_open=None) for bar in material.bars))
        if defect == "warmup":
            warmup = replace(material.warmup, bars_by_session={
                day: [replace(bar, raw_open=None) for bar in bars]
                for day, bars in material.warmup.bars_by_session.items()})
            return replace(material, warmup=warmup)
        if defect == "population":
            return replace(material, bars=material.bars[:1])
        if defect == "bil":
            return replace(material, benchmarks=tuple(row.model_copy(update={"bil_open_signal": None}) for row in material.benchmarks))
        return replace(material, meta={sid: replace(meta, related_tickers=()) for sid, meta in material.meta.items()})
    monkeypatch.setattr(inputs, "cold_start_inputs", changed)
    _read_only(conn)
    # Exercise material-returning validation explicitly; report-only entrypoints
    # now use the compact reader and have their own real-publication acceptance.
    with inputs.pinned(conn) as pub:
        with pytest.raises(inputs.RollingGoRefused, match="NOT_READY"):
            inputs.validate(conn, pub)


def test_strategy_request_is_bound_to_current_source(conn, published, monkeypatch):
    controller, strategy = inputs.production_strategy()
    monkeypatch.setattr(inputs, "production_strategy", lambda: (controller, {**strategy, "strategy": "wrong"}))
    _read_only(conn)
    with pytest.raises(inputs.RollingGoRefused, match="STRATEGY_CHANGED"):
        inputs.readiness(conn)


def test_sealed_payload_tamper_refuses(conn, published):
    conn.execute("SET LOCAL session_replication_role=replica")
    conn.execute("UPDATE sentinel_snapshot_bars SET close_unadjusted=1 WHERE candidate_id=%s AND session=%s", (published["candidate_id"], TARGET))
    conn.commit()
    _read_only(conn)
    from sentinel.feed.rolling_store import SnapshotStorageRefused
    with pytest.raises(SnapshotStorageRefused, match="manifest"):
        inputs.readiness(conn)


def test_database_health_measures_actual_snapshot_queries_and_pin(conn, published):
    _read_only(conn)
    report = health.inspect(conn)
    assert report["input_contract"] == inputs.SCHEMA
    assert all(report["checks"].values()), report
    assert report["transaction_db_writes"] == 0
    assert report["recent_xnys_sessions"] == 252


def test_database_health_refuses_a_missing_publication_pin(conn, published, monkeypatch):
    from sentinel.feed import rolling_store
    @contextmanager
    def unpinned(conn):
        yield inputs.current(conn)
    monkeypatch.setattr(inputs, "pinned", unpinned)
    # Explicit generation readers now also hold a transaction pin. Remove both
    # ownership paths to actually falsify the measured writer exclusion.
    monkeypatch.setattr(rolling_store, "_pin_reader", lambda _conn: None)
    _read_only(conn)
    assert health.inspect(conn)["checks"]["publication_pin_excludes_writers"] is False


def test_supported_go_preparation_and_readiness_payloads_use_rolling(conn, published, monkeypatch, capsys):
    from pathlib import Path
    from sentinel.feed import store
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import sentinel_go_24x7_entry as entry
    from sentinel import backup_guard
    backup_calls = []
    monkeypatch.setattr(backup_guard, "require_writes_permitted",
                        lambda conn, **kwargs: backup_calls.append(kwargs["operation"]))
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, "connect", lambda dsn: Borrowed())
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "test-connection")
    exec(entry._PREPARATION_CODE, {})
    output = capsys.readouterr().out
    prepared = json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                               if line.startswith("SENTINEL_GO_PREPARATION=")))
    assert prepared["publication_current"] and prepared["bounded_sharadar_daily"]
    assert "NAS validation schema migration" in backup_calls
    exec(entry.go._READINESS_CODE, {})
    output = capsys.readouterr().out
    ready = json.loads(next(line.split("=", 1)[1] for line in output.splitlines()
                           if line.startswith("SENTINEL_GO_READINESS=")))
    assert ready["ready"] and ready["transaction_read_only"]
    assert ready["input_contract"] == inputs.SCHEMA
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions").fetchone()[0] == 0


def test_snapshot_parity_uses_canonical_warmup_without_creating_a_book(conn, published, monkeypatch):
    commit = "a" * 40
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", commit)
    monkeypatch.setattr(parity.identity, "rehearsal_identity", lambda: {
        "identity_hash": "b" * 64, "environment": {
            "compatible": True, "pins_match": True, "sources_known": True, "pin_drift": {}, "lock_present": True,
            "sentinel_source": {"hash": "c" * 64}, "wealth_core_source": {"hash": "d" * 64}}})
    monkeypatch.setattr(parity, "_fresh_seed", lambda *_a, **_k: pytest.fail("legacy warmup"))
    report = parity.run_proof(conn, starting_cash="100000", expected_commit=commit)
    assert report["verdict"] == "PASS"
    assert report["proof"]["scope"] == "ROLLING_STARTUP_AND_RESTART"
    assert all(report["proof"]["checks"].values())
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions").fetchone()[0] == 0
    conn.rollback()
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import sentinel_go_validate as host
    assert host._operational_parity_report_valid(report, commit=commit, starting_cash="100000")
