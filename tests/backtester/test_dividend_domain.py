"""Canonical backtester must use the same Sharadar dividend domain as Sentinel."""
from __future__ import annotations

import pytest

from app.wealth_core_replay import RawPriceDomainUnavailable, load_bars


class _MappedRows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query, _params=None):
        return _MappedRows(self.rows)


class _Identity:
    unresolved = {}

    def resolve(self, _ticker, _session):
        return "P:1"


def _row(*, close=25.0, raw=100.0):
    return {
        "ticker": "AAPL",
        "date": "2014-08-07",
        "open": close,
        "close": close,
        "close_unadjusted": raw,
        "volume": 1_000_000.0,
    }


def test_canonical_loader_converts_actions_value_to_raw_share_basis():
    bars = load_bars(
        _Conn([_row()]), "2014-08-07", "2014-08-07",
        dividends={("AAPL", "2014-08-07"): 0.1175},
        identity=_Identity(),
    )
    assert bars["2014-08-07"][0].dividend_per_share == pytest.approx(0.47)


def test_canonical_loader_does_not_silently_guess_missing_dividend_basis():
    with pytest.raises(RawPriceDomainUnavailable, match="cannot convert positive"):
        load_bars(
            _Conn([_row(close=None)]), "2014-08-07", "2014-08-07",
            dividends={("AAPL", "2014-08-07"): 0.50},
            identity=_Identity(),
        )
