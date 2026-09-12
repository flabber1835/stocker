"""Exact source decimals survive the provider and bounded-memory SEP sorter."""
from __future__ import annotations

from decimal import Decimal
import json
import uuid

import pytest

from sentinel.feed import domains, sharadar, staging, store
from tests.support.postgres import _EphemeralPostgres


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class _Http:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass

    response_content = b""

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url, params):
            assert "api_key" in params
            return _Response(_Http.response_content)


def _sep_payload_raw() -> bytes:
    columns = [
        "ticker", "date", "open", "close", "closeunadj", "volume",
        "lastupdated",
    ]
    # Literal JSON number spellings are deliberate. json.dumps(float(...)) here
    # would perform the precision loss this test exists to prevent.
    return (
        '{"datatable":{"columns":['
        + ",".join('{"name":' + json.dumps(name) + '}' for name in columns)
        + '],"data":[["AAA","2026-01-02",123456789.123456,'
          '130549280.66335685,391647841.99007055,21438648,'
          '"2026-01-03"]]},"meta":{"next_cursor_id":null}}'
    ).encode("utf-8")


def test_provider_decodes_fractional_source_numbers_as_decimal(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "redacted-test-key")
    _Http.response_content = _sep_payload_raw()

    rows = list(sharadar.fetch_table(
        sharadar.SEP, http=_Http, sleep=lambda _seconds: None))

    assert len(rows) == 1
    row = rows[0]
    assert row["open"] == Decimal("123456789.123456")
    assert row["close"] == Decimal("130549280.66335685")
    assert row["closeunadj"] == Decimal("391647841.99007055")
    assert row["volume"] == 21438648


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
        assert recovered == [{
            "date": "2026-01-02", "ticker": "AAA",
            "open": "24691357.8246912",
            "close": "78329568.39801411",
            "closeunadj": "391647841.99007055",
            "closeadj": "78329568.39801411",
            "volume": "35731080",
        }]

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
