from __future__ import annotations

import math

import pytest

from sentinel.feed.domains import normalise_sep_rows
from sentinel.feed import sharadar
from stock_strategy_shared.wealth_core.sharadar_domains import raw_compatible_volume


def test_split_adjusted_volume_is_converted_to_raw_liquidity_domain() -> None:
    # Real shape seen in the supplied 2007 SEP corpus: the two price domains are
    # six times apart. Multiplying closeunadj by reported volume is therefore a
    # six-fold liquidity understatement.
    adjusted_close = 8.52
    raw_close = 1.42
    reported_volume = 254_133.3

    raw_volume = raw_compatible_volume(adjusted_close, raw_close, reported_volume)

    assert raw_volume == pytest.approx(1_524_799.8)
    assert raw_close * raw_volume == pytest.approx(adjusted_close * reported_volume)


def test_non_split_volume_is_unchanged() -> None:
    assert raw_compatible_volume(28.35, 28.35, 3_200_000) == pytest.approx(3_200_000)


def test_invalid_volume_domain_inputs_fail_closed() -> None:
    for values in [
        (None, 10, 100),
        (10, None, 100),
        (10, 10, None),
        (10, 0, 100),
        (10, 10, 0),
        (math.inf, 10, 100),
        (10, math.nan, 100),
    ]:
        assert raw_compatible_volume(*values) is None


def test_normaliser_emits_only_raw_compatible_liquidity_volume() -> None:
    row = {
        "ticker": "MGRM1",
        "date": "2007-12-31",
        "open": 7.92,
        "close": 8.52,
        "closeunadj": 1.42,
        "volume": 254_133.3,
    }

    [bar] = list(normalise_sep_rows([row]))

    assert bar.vendor.raw_close == pytest.approx(1.42)
    assert bar.vendor.volume == pytest.approx(1_524_799.8)
    assert bar.vendor.raw_close * bar.vendor.volume == pytest.approx(
        row["close"] * row["volume"]
    )
    assert bar.vendor.tradeable is True


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, payload) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, owner, timeout) -> None:
        self.owner = owner
        owner.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, _url, *, params):
        self.owner.calls += 1
        self.owner.last_params = params
        return _Response(self.owner.payload)


class _Http:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = 0
        self.timeout = None
        self.last_params = None

    def Client(self, *, timeout):  # noqa: N802 - mirrors httpx API
        return _Client(self, timeout)


def test_malformed_200_response_is_protocol_failure_without_retry(monkeypatch) -> None:
    monkeypatch.setenv("SHARADAR_API_KEY", "secret-that-must-not-leak")
    http = _Http({})

    with pytest.raises(sharadar.SharadarProtocolError, match="datatable"):
        list(sharadar.fetch_table("SEP", http=http, sleep=lambda _delay: None))

    assert http.calls == 1
    assert http.timeout == sharadar.FETCH_TIMEOUT_SECS


def test_row_width_mismatch_is_protocol_failure(monkeypatch) -> None:
    monkeypatch.setenv("SHARADAR_API_KEY", "secret-that-must-not-leak")
    http = _Http({
        "datatable": {
            "columns": [{"name": "ticker"}, {"name": "date"}],
            "data": [["AAPL"]],
        },
        "meta": {"next_cursor_id": None},
    })

    with pytest.raises(sharadar.SharadarProtocolError, match="1 values for 2 columns"):
        list(sharadar.fetch_table("SEP", http=http, sleep=lambda _delay: None))

    assert http.calls == 1
