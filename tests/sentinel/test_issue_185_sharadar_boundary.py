"""Focused falsifiers for the financial-grade Sharadar boundary (#185)."""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.feed import maintenance, recovery, sharadar  # noqa: E402
from stock_strategy_shared.wealth_core.eligibility import (  # noqa: E402
    adv20_dollars,
    signal_day_dollar_volume,
)
from stock_strategy_shared.wealth_core.liquidity import (  # noqa: E402
    raw_compatible_volume,
    split_invariant_dollar_volume,
)


# ── economic domain: the strategy-critical #185 defect ──────────────────────

@pytest.mark.parametrize(("signal", "raw", "reported"), [
    pytest.param(100.0, 100.0, 1_000_000.0, id="no-split"),
    pytest.param(25.0, 100.0, 4_000_000.0, id="4-for-1-history"),
    pytest.param(50.0, 10.0, 200_000.0, id="1-for-5-reverse-history"),
])
def test_raw_volume_is_exactly_compatible_with_vendor_turnover(
        signal, raw, reported):
    volume = raw_compatible_volume(signal, raw, reported)
    assert volume is not None
    assert raw * volume == pytest.approx(
        split_invariant_dollar_volume(signal, reported), rel=1e-12)


@pytest.mark.parametrize(("ticker", "signal", "raw", "reported"), [
    pytest.param("AAPL", 124.808, 499.23, 187_630_000.0,
                 id="AAPL-2020-08-28"),
    pytest.param("TSLA", 147.56, 2_213.40, 301_217_640.0,
                 id="TSLA-2020-08-28"),
    pytest.param("NVDA", 18.966, 758.65, 548_180_000.0,
                 id="NVDA-2021-07-15"),
])
def test_retained_sharadar_split_falsifiers_use_compatible_turnover(
        ticker, signal, raw, reported):
    corrected_volume = raw_compatible_volume(signal, raw, reported)
    assert corrected_volume is not None
    corrected = raw * corrected_volume
    vendor = signal * reported
    old_mixed = raw * reported
    assert corrected == pytest.approx(vendor, rel=1e-12), ticker
    assert old_mixed > corrected * 3.9, ticker


def test_exact_5m_signal_day_boundary_survives_normalization():
    # Vendor domain: $5 * 1M shares = exactly $5M. Raw/as-traded price is $20.
    raw_volume = raw_compatible_volume(5.0, 20.0, 1_000_000.0)
    assert raw_volume == pytest.approx(250_000.0)
    assert signal_day_dollar_volume(20.0, raw_volume) == pytest.approx(5_000_000.0)


def test_exact_20m_adv_boundary_survives_normalization():
    # 20 identical sessions; adjusted $25 x 800k = $20M each. Raw is $100.
    raw_volume = raw_compatible_volume(25.0, 100.0, 800_000.0)
    assert raw_volume == pytest.approx(200_000.0)
    assert adv20_dollars([100.0] * 20, [raw_volume] * 20) == pytest.approx(
        20_000_000.0)


def test_future_split_restatement_cannot_change_historical_liquidity():
    # Same historical raw trade activity represented before and after a later
    # 4:1 split restatement: signal price /4 and reported volume x4.
    before = raw_compatible_volume(100.0, 100.0, 100_000.0)
    after = raw_compatible_volume(25.0, 100.0, 400_000.0)
    assert before == pytest.approx(after)
    assert signal_day_dollar_volume(100.0, before) == pytest.approx(10_000_000.0)
    assert signal_day_dollar_volume(100.0, after) == pytest.approx(10_000_000.0)


@pytest.mark.parametrize(("signal", "raw", "volume"), [
    (None, 10, 10), (10, None, 10), (10, 10, None),
    (0, 10, 10), (10, 0, 10), (10, 10, 0),
    (math.nan, 10, 10), (10, math.inf, 10),
])
def test_liquidity_domain_never_falls_back_to_mixed_basis(signal, raw, volume):
    assert raw_compatible_volume(signal, raw, volume) is None


# ── strict Nasdaq Data Link HTTP-200 protocol ────────────────────────────────

def _page(table=sharadar.SEP, *, data=None, cursor=None, columns=None):
    names = list(columns or sorted(sharadar._REQUIRED_COLUMNS[table]))
    return {
        "datatable": {
            "columns": [{"name": name} for name in names],
            "data": [] if data is None else data,
        },
        "meta": {"next_cursor_id": cursor},
    }


def test_terminal_empty_page_is_well_formed_success():
    schema, rows, cursor = sharadar._decode_page(
        _page(), table=sharadar.SEP, expected_schema=None)
    assert set(schema) == set(sharadar._REQUIRED_COLUMNS[sharadar.SEP])
    assert rows == []
    assert cursor is None


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda p: p.pop("datatable"), id="missing-datatable"),
    pytest.param(lambda p: p["datatable"].pop("columns"), id="missing-columns"),
    pytest.param(lambda p: p["datatable"].pop("data"), id="missing-data"),
    pytest.param(lambda p: p.pop("meta"), id="missing-meta"),
    pytest.param(lambda p: p["meta"].pop("next_cursor_id"), id="missing-cursor-field"),
])
def test_malformed_200_envelopes_refuse(mutate):
    payload = _page()
    mutate(payload)
    with pytest.raises(sharadar.SharadarProtocolError):
        sharadar._decode_page(payload, table=sharadar.SEP, expected_schema=None)


def test_duplicate_column_refuses():
    columns = sorted(sharadar._REQUIRED_COLUMNS[sharadar.SEP])
    with pytest.raises(sharadar.SharadarProtocolError, match="duplicate column"):
        sharadar._decode_page(
            _page(columns=columns + [columns[0]]),
            table=sharadar.SEP, expected_schema=None)


@pytest.mark.parametrize("delta", [-1, 1])
def test_row_width_mismatch_refuses(delta):
    columns = sorted(sharadar._REQUIRED_COLUMNS[sharadar.SEP])
    width = len(columns) + delta
    with pytest.raises(sharadar.SharadarProtocolError, match="width"):
        sharadar._decode_page(
            _page(columns=columns, data=[[None] * width]),
            table=sharadar.SEP, expected_schema=None)


def test_schema_cannot_change_mid_traversal():
    columns = tuple(sorted(sharadar._REQUIRED_COLUMNS[sharadar.SEP]))
    mutated = list(columns) + ["unexpected"]
    with pytest.raises(sharadar.SharadarProtocolError, match="schema changed"):
        sharadar._decode_page(
            _page(columns=mutated), table=sharadar.SEP,
            expected_schema=columns)


def test_required_table_column_cannot_disappear():
    columns = sorted(sharadar._REQUIRED_COLUMNS[sharadar.SFP] - {"closeadj"})
    with pytest.raises(sharadar.SharadarProtocolError, match="closeadj"):
        sharadar._decode_page(
            _page(sharadar.SFP, columns=columns),
            table=sharadar.SFP, expected_schema=None)


@pytest.mark.parametrize("cursor", ["", "   ", 123, [], {}])
def test_invalid_cursor_shapes_refuse(cursor):
    with pytest.raises(sharadar.SharadarProtocolError, match="next_cursor_id"):
        sharadar._decode_page(
            _page(cursor=cursor), table=sharadar.SEP, expected_schema=None)


def test_empty_page_cannot_claim_more_pages():
    with pytest.raises(sharadar.SharadarProtocolError, match="empty page"):
        sharadar._decode_page(
            _page(cursor="more"), table=sharadar.SEP, expected_schema=None)


class _BadJsonResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        raise ValueError("truncated json")


class _OneResponseHttp:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url, _params):
            return _BadJsonResponse()


def test_invalid_json_200_is_typed_protocol_failure(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "not-rendered")
    with pytest.raises(sharadar.SharadarProtocolError, match="not valid JSON"):
        list(sharadar.fetch_table(
            sharadar.SEP, http=_OneResponseHttp,
            sleep=lambda _seconds: None))


def test_reserved_auth_and_cursor_params_refuse_before_transport(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "safe")
    for name in ("api_key", "qopts.cursor_id"):
        with pytest.raises(ValueError, match="transport-owned"):
            list(sharadar.fetch_table(sharadar.SEP, {name: "owned-by-caller"}))


def test_unknown_table_is_not_a_provider_escape_hatch(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "safe")
    with pytest.raises(ValueError, match="unsupported Sharadar table"):
        list(sharadar.fetch_table("SF1"))


def test_direct_provider_is_not_a_base_url_alias():
    with pytest.raises(NotImplementedError, match="different provider protocol"):
        list(sharadar.DirectSharadarSource().fetch_table(sharadar.SEP))


# ── Retry-After semantics ────────────────────────────────────────────────────

NOW = dt.datetime(2026, 8, 18, 12, 0, 0, tzinfo=dt.timezone.utc)


def test_numeric_retry_after_honored_for_429_and_503():
    assert sharadar.retry_delay(0, 429, "120", now=lambda: NOW) == 120
    assert sharadar.retry_delay(0, 503, "120", now=lambda: NOW) == 120


def test_http_date_retry_after_is_parsed():
    future = "Tue, 18 Aug 2026 12:02:00 GMT"
    assert sharadar.retry_delay(0, 503, future, now=lambda: NOW) == 120


def test_past_retry_after_falls_back_to_local_backoff():
    past = "Tue, 18 Aug 2026 11:59:00 GMT"
    assert sharadar.retry_delay(0, 503, past, now=lambda: NOW) == pytest.approx(
        sharadar.FETCH_BACKOFF_BASE)


def test_malformed_retry_after_falls_back_without_crashing():
    assert sharadar.retry_delay(
        0, 503, "not-a-date", now=lambda: NOW) == pytest.approx(
            sharadar.FETCH_BACKOFF_BASE)


def test_wait_above_local_ceiling_defers_instead_of_retrying_early(monkeypatch):
    monkeypatch.setattr(sharadar, "RATE_LIMIT_BACKOFF_CAP", 90.0)
    with pytest.raises(sharadar.SharadarRetryDeferred) as caught:
        sharadar.retry_delay(0, 503, "120", now=lambda: NOW)
    assert caught.value.delay == 120


# ── CDC / crash convergence pure contracts ──────────────────────────────────


def test_lastupdated_tracker_records_vendor_mutation_clock():
    rows = [
        {"ticker": "A", "lastupdated": "2026-08-16"},
        {"ticker": "B", "lastupdated": "2026-08-18"},
        {"ticker": "C", "lastupdated": "2026-08-17"},
    ]
    tracker = maintenance.LastUpdatedTrackingFetch(
        lambda table, params=None, **kwargs: iter(rows))
    assert list(tracker(sharadar.SEP)) == rows
    assert tracker.max_sep_lastupdated == dt.date(2026, 8, 18)


def test_mutation_fingerprint_is_order_independent_but_multiplicity_sensitive():
    a = {"date": "2020-01-02", "ticker": "A", "open": 1, "close": 1,
         "closeunadj": 1, "volume": 10, "lastupdated": "2026-08-18"}
    b = {"date": "2020-01-02", "ticker": "B", "open": 2, "close": 2,
         "closeunadj": 2, "volume": 20, "lastupdated": "2026-08-18"}
    assert maintenance._mutation_digest([a, b]) == maintenance._mutation_digest([b, a])
    assert maintenance._mutation_digest([a, b]) != maintenance._mutation_digest([a, b, b])
    changed = dict(b, close=2.01)
    assert maintenance._mutation_digest([a, b]) != maintenance._mutation_digest([a, changed])


def test_failed_physical_frontier_expands_retry_back_to_visible_authority(monkeypatch):
    from sentinel.feed import store
    monkeypatch.setattr(store, "latest_session", lambda conn: "2026-08-18")
    monkeypatch.setattr(store, "latest_visible_session", lambda conn: "2026-08-14")
    assert recovery.extended_overlap_days(object(), 14) == 18


def test_normal_frontier_keeps_requested_overlap(monkeypatch):
    from sentinel.feed import store
    monkeypatch.setattr(store, "latest_session", lambda conn: "2026-08-18")
    monkeypatch.setattr(store, "latest_visible_session", lambda conn: "2026-08-18")
    assert recovery.extended_overlap_days(object(), 14) == 14
