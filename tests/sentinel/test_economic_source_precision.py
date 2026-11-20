"""Exact source decimals survive the provider and bounded-memory SEP sorter."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import zipfile
import uuid

import pytest

from sentinel.feed import acquisition_work, domains, snapshot_export, staging, store
from tests.support.postgres import _EphemeralPostgres


def test_archive_preserves_exact_source_decimals(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_STATE_DIR", str(tmp_path))
    observed = datetime(2026, 1, 3, tzinfo=timezone.utc)
    snapshot = snapshot_export.ExportSnapshot("SEP", {}, "", observed, observed)
    fields = ("ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated")
    csv = (",".join(fields) + "\n"
           "AAA,2026-01-02,123456789.123456,130549280.66335685,"
           "391647841.990070551,21438648,2026-01-03\n")
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("prices.csv", csv)
    path = acquisition_work.cache_root() / (acquisition_work.file_key(snapshot) + ".zip")
    path.write_bytes(blob.getvalue())
    digest = hashlib.sha256(blob.getvalue()).hexdigest()
    path.with_suffix(".sha256").write_text(digest)

    rows, evidence = snapshot_export.download_snapshot(snapshot, required=set(fields))
    row, = rows
    assert evidence["file_sha256"] == digest
    assert Decimal(row["open"]) == Decimal("123456789.123456")
    assert Decimal(row["close"]) == Decimal("130549280.66335685")
    assert Decimal(row["closeunadj"]) == Decimal("391647841.990070551")
    assert int(row["volume"]) == 21438648


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


def test_staging_preserves_exact_source_values_and_normalized_economics(pg):
    conn = store.connect(pg.sync_dsn)
    try:
        store.require_feed_schema(conn)
        run_id = str(uuid.uuid4())
        row = {
            "date": "2026-01-02", "ticker": "AAA",
            "open": Decimal("24691357.8246912"),
            "close": Decimal("78329568.39801411"),
            "closeunadj": Decimal("391647841.99007055"),
            "closeadj": Decimal("78329568.39801411"),
            "volume": 35_731_080,
        }
        assert staging.stage(conn, [row], run_id=run_id, chunk="precision") == 1
        recovered = list(staging.staged(
            conn, run_id=run_id, chunk="precision"))
        assert len(recovered) == 1
        back = recovered[0]
        assert back["date"] == "2026-01-02"
        assert back["ticker"] == "AAA"
        for field in ("open", "close", "closeunadj", "closeadj", "volume"):
            assert isinstance(back[field], float)
            assert back[field] == float(row[field])
        assert str(back["open"]) == "24691357.8246912"
        assert str(back["close"]) == "78329568.39801411"
        assert str(back["closeunadj"]) == "391647841.99007055"
        assert str(back["closeadj"]) == "78329568.39801411"
        assert str(back["volume"]) == "35731080"

        normalized = list(domains.normalise_sep_rows(
            recovered, resolve_identity=lambda _ticker, _day: "1"))
        assert len(normalized) == 1
        bar = normalized[0].vendor
        assert bar.volume == 7_146_216.0
        assert bar.raw_open == 123_456_789.123456
    finally:
        conn.close()


def test_direct_and_staged_equivalent_publications_match(pg):
    conn = store.connect(pg.sync_dsn)
    try:
        store.require_feed_schema(conn)
        raw = {
            "date": "2026-01-02", "ticker": "AAA",
            "open": Decimal("123456789.123456"),
            "close": Decimal("391647841.99007055"),
            "closeunadj": Decimal("391647841.99007055"),
            "closeadj": Decimal("391647841.99007055"),
            "volume": 7_146_216,
        }
        rebased = {
            "date": "2026-01-02", "ticker": "AAA",
            "open": Decimal("24691357.8246912"),
            "close": Decimal("78329568.39801411"),
            "closeunadj": Decimal("391647841.99007055"),
            "closeadj": Decimal("78329568.39801411"),
            "volume": 35_731_080,
        }

        outputs = []
        for source in (raw, rebased):
            run_id = str(uuid.uuid4())
            staging.stage(conn, [source], run_id=run_id, chunk="equivalent")
            staged_rows = staging.staged(
                conn, run_id=run_id, chunk="equivalent")
            outputs.append(list(domains.normalise_sep_rows(
                staged_rows, resolve_identity=lambda _ticker, _day: "1"))[0])

        left, right = outputs
        assert left.vendor.raw_close == right.vendor.raw_close
        assert left.vendor.raw_open == right.vendor.raw_open
        assert left.vendor.volume == right.vendor.volume
    finally:
        conn.close()