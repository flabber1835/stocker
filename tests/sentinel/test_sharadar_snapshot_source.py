from __future__ import annotations

import pytest

from sentinel.feed import sharadar, snapshot_export, snapshot_source


def _ticker(*, relatedtickers=None):
    return {
        "table": "SEP",
        "permaticker": "P1",
        "ticker": "AAA",
        "category": "Domestic Common Stock",
        "relatedtickers": relatedtickers,
        "firstpricedate": "2000-01-03",
        "lastpricedate": "2026-08-19",
        "sector": "Technology",
        "isdelisted": "N",
        "exchange": "NYSE",
    }


def test_tickers_export_is_key_witness_not_value_source(monkeypatch):
    paged = [_ticker(relatedtickers="")]
    calls = []

    monkeypatch.setattr(
        snapshot_source.sharadar, "fetch_table",
        lambda table, params=None, **kwargs: iter(paged))

    def keys(**kwargs):
        calls.append(kwargs)
        return {("P1", "AAA")}, {"authority": "export"}

    monkeypatch.setattr(
        snapshot_source.snapshot_export, "fetch_complete_ticker_keys", keys)
    rows = list(snapshot_source.fetch_table(sharadar.TICKERS))

    # The exact JSON field value survives; the CSV export is not allowed to
    # collapse authoritative blank into NULL.
    assert rows[0]["relatedtickers"] == ""
    assert calls == [{}]


def test_tickers_key_mismatch_refuses_common_mode_partial_source(monkeypatch):
    monkeypatch.setattr(
        snapshot_source.sharadar, "fetch_table",
        lambda table, params=None, **kwargs: iter([_ticker()]))
    monkeypatch.setattr(
        snapshot_source.snapshot_export, "fetch_complete_ticker_keys",
        lambda **kwargs: ({("P1", "AAA"), ("P2", "BBB")}, {}))

    with pytest.raises(snapshot_export.SharadarSnapshotExportError,
                       match="missing_from_pages"):
        list(snapshot_source.fetch_table(sharadar.TICKERS))


@pytest.mark.parametrize("table", [sharadar.SEP, sharadar.SFP, sharadar.ACTIONS])
def test_non_tickers_remain_on_strict_paginated_transport(monkeypatch, table):
    calls = []

    def paged(got, params=None, **kwargs):
        calls.append((got, params, kwargs))
        return iter([{"table": got}])

    monkeypatch.setattr(snapshot_source.sharadar, "fetch_table", paged)
    monkeypatch.setattr(
        snapshot_source.snapshot_export, "fetch_complete_ticker_keys",
        lambda **kwargs: pytest.fail("non-TICKERS path touched the exporter"))

    assert list(snapshot_source.fetch_table(table)) == [{"table": table}]
    assert calls == [(table, None, {})]
