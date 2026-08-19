from __future__ import annotations

import io
import zipfile

import pytest

from sentinel.feed import sharadar, snapshot_source as S


def _meta(*, status="fresh", snapshot="2026-08-19 22:00:00 UTC",
          refreshed="2026-08-19 21:59:00 UTC", link="https://files.example/x.zip"):
    return {
        "datatable_bulk_download": {
            "file": {
                "link": link,
                "status": status,
                "data_snapshot_time": snapshot,
            },
            "datatable": {"last_refreshed_time": refreshed},
        }
    }


def _zip_csv(name: str, text: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(name, text)
    return out.getvalue()


def test_fresh_export_requires_snapshot_at_or_after_table_refresh():
    status, link = S._decode_export(_meta(), table=sharadar.ACTIONS)
    assert status == "fresh"
    assert link == "https://files.example/x.zip"

    with pytest.raises(sharadar.SharadarProtocolError,
                       match="snapshot predates"):
        S._decode_export(
            _meta(snapshot="2026-08-19 21:58:00 UTC"),
            table=sharadar.ACTIONS)


def test_regenerating_export_never_exposes_old_link_as_authority():
    status, link = S._decode_export(
        _meta(status="regenerating"), table=sharadar.TICKERS)
    assert status == "regenerating"
    assert link is None


def test_actions_export_requires_complete_consumed_schema():
    good = _zip_csv(
        "SHARADAR_ACTIONS.csv",
        "date,action,ticker,name,value,contraticker,contraname\n"
        "2026-08-18,dividend,AAA,AAA Inc,0.25,,\n")
    rows = S._rows_from_zip(sharadar.ACTIONS, good)
    assert rows == [{
        "date": "2026-08-18", "action": "dividend", "ticker": "AAA",
        "name": "AAA Inc", "value": "0.25", "contraticker": "",
        "contraname": "",
    }]

    missing = _zip_csv(
        "SHARADAR_ACTIONS.csv",
        "date,action,ticker,value\n2026-08-18,dividend,AAA,0.25\n")
    with pytest.raises(sharadar.SharadarProtocolError,
                       match="lacks required column"):
        S._rows_from_zip(sharadar.ACTIONS, missing)


def test_reference_export_requires_exactly_one_csv():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("a.csv", "table,permaticker,ticker,category,relatedtickers,firstpricedate,lastpricedate,sector,isdelisted,exchange\n")
        archive.writestr("b.csv", "table,permaticker,ticker,category,relatedtickers,firstpricedate,lastpricedate,sector,isdelisted,exchange\n")
    with pytest.raises(sharadar.SharadarProtocolError,
                       match="exactly one CSV"):
        S._rows_from_zip(sharadar.TICKERS, payload.getvalue())


def test_authoritative_dispatch_uses_export_only_for_negative_space_tables(monkeypatch):
    calls = []

    def exported(table, params=None, **kwargs):
        calls.append(("export", table, params, kwargs))
        return iter([{"source": "export"}])

    def paged(table, params=None, **kwargs):
        calls.append(("paged", table, params, kwargs))
        return iter([{"source": "paged"}])

    monkeypatch.setattr(S, "fetch_export", exported)
    monkeypatch.setattr(S.sharadar, "fetch_table", paged)

    assert list(S.fetch_table(sharadar.TICKERS)) == [{"source": "export"}]
    assert list(S.fetch_table(sharadar.ACTIONS)) == [{"source": "export"}]
    assert list(S.fetch_table(sharadar.SEP)) == [{"source": "paged"}]
    assert list(S.fetch_table(sharadar.SFP)) == [{"source": "paged"}]
