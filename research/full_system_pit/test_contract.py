from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from research.full_system_pit.evidence import Evidence, Divergence, verify
from research.full_system_pit.provider import Provider


def fixture(tmp_path):
    path = tmp_path / "truth.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE obs(day TEXT,sid TEXT,ticker TEXT,op REAL,raw REAL,signal REAL,
          volume REAL,raw_volume REAL,split REAL,dividend REAL);
      CREATE TABLE reference(day TEXT,spy REAL,gap REAL,intraday REAL,cash_source TEXT);
      CREATE TABLE meta(day TEXT,sid TEXT,ticker TEXT,body TEXT);
      CREATE TABLE actions(day TEXT,sid TEXT,body TEXT);
      CREATE TABLE identity(body TEXT);
    """)
    for i,day in enumerate(("2006-01-03","2006-01-04","2006-01-05")):
        raw = 100. if i<2 else 50.
        db.execute("INSERT INTO obs VALUES(?,?,?,?,?,?,?,?,?,?)",(day,"1","AAA",raw,raw,50.,2000.,1000. if i<2 else 2000.,2. if i==2 else 1.,0.))
        db.execute("INSERT INTO reference VALUES(?,?,?,?,?)",(day,100.+i,1.,1.001,"proxy"))
    db.execute("INSERT INTO obs VALUES(?,?,?,?,?,?,?,?,?,?)",("2006-01-05","2","IPO",20.,20.,20.,1000.,1000.,1.,0.))
    for sid,ticker,day in (("1","AAA","2006-01-03"),("2","IPO","2006-01-05")):
        body=dict(table="SEP",permaticker=sid,ticker=ticker,category="Domestic Common Stock",relatedtickers=None,
                  firstpricedate=day,sector="OTHER",exchange="NYSE")
        db.execute("INSERT INTO meta VALUES(?,?,?,?)",(day,sid,ticker,json.dumps(body)))
    db.execute("INSERT INTO identity VALUES(?)",(json.dumps({"dataset_sha256":"fixture"}),))
    db.commit()
    db.close()
    return path


def provider(tmp_path, day="2006-01-04"):
    p = Provider(fixture(tmp_path),tmp_path/"exports",page_size=1)
    p.advance(datetime.fromisoformat(day+"T22:00:00+00:00"))
    return p


def request(p, table="SEP", **query):
    return p(httpx.Request("GET",f"https://data.nasdaq.com/api/v3/datatables/SHARADAR/{table}.json",params=query))


def test_future_listing_prices_and_split_revision_are_causal(tmp_path):
    p=provider(tmp_path)
    before=list(p.row_stream("SEP",{}))
    assert len(before)==2 and all(r["date"]<="2006-01-04" for r in before)
    assert all(r["close"]==100. and r["volume"]==1000. for r in before)
    assert [r["ticker"] for r in p.row_stream("TICKERS",{})]==["AAA"]
    p.advance(datetime.fromisoformat("2006-01-05T22:00:00+00:00"))
    after=list(p.row_stream("SEP",{"lastupdated.gte":"2006-01-05"}))
    assert len(after)==4
    aaa=[r for r in after if r["ticker"]=="AAA"]
    assert len(aaa)==3 and all(r["close"]==50. and r["volume"]==2000. for r in aaa)
    assert [r["ticker"] for r in p.row_stream("TICKERS",{})]==["AAA","IPO"]


def test_cursor_is_bound_to_query_and_publication(tmp_path):
    p=provider(tmp_path)
    token=request(p).json()["meta"]["next_cursor_id"]
    assert token
    with pytest.raises(ValueError,match="cursor query"):
        request(p,ticker="OTHER",**{"qopts.cursor_id":token})
    token=request(p).json()["meta"]["next_cursor_id"]
    p.advance(datetime.fromisoformat("2006-01-05T22:00:00+00:00"))
    with pytest.raises(KeyError):
        request(p,**{"qopts.cursor_id":token})


def test_real_tables_client_consumes_all_pages(tmp_path):
    from research.sharadar_replay.runtime import simulated_runtime
    from sentinel.feed import sharadar
    p=provider(tmp_path)
    with simulated_runtime(p,commit="0"*40):
        actual=list(sharadar.fetch_table(sharadar.SEP,{"date.gte":"2006-01-03","date.lte":"2006-01-04"}))
    assert actual==list(p.row_stream("SEP",{}))


def test_export_is_complete_and_future_capped(tmp_path):
    import csv,io,zipfile
    p=provider(tmp_path)
    result=request(p,**{"qopts.export":"true"}).json()
    url=result["datatable_bulk_download"]["file"]["link"]
    response=p(httpx.Request("GET",url))
    with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
        rows=list(csv.DictReader(io.StringIO(archive.read("SEP.csv").decode())))
    assert [r["date"] for r in rows]==["2006-01-03","2006-01-04"]


def test_evidence_retains_payloads_and_first_failure(tmp_path):
    root=tmp_path/"evidence"
    evidence=Evidence(root,{"test":"identity"})
    at=datetime(2006,1,3,22,tzinfo=timezone.utc)
    with pytest.raises(Divergence):
        with evidence.boundary("decision",at=at,session="2006-01-03"):
            raise Divergence("nav",1.,2.)
    evidence.close()
    assert verify(root)["events"]==2
    first=json.loads((root/"FIRST_FAILURE.json").read_text())
    assert first["gate"]=="nav" and first["actual"]==2.
    event=json.loads((root/"events.jsonl").read_text().splitlines()[1])
    (root/"objects"/(event["payload_sha256"]+".json.gz")).write_bytes(gzip.compress(b'{}'))
    with pytest.raises(Divergence,match="retained_payload"):
        verify(root)


def test_clock_rejects_future_sessions_and_reversal(tmp_path):
    evidence=Evidence(tmp_path/"evidence",{})
    at=datetime(2006,1,3,22,tzinfo=timezone.utc)
    with pytest.raises(ValueError,match="future market"):
        evidence.event(at=at,session="2006-01-04",phase="test",payload={})
    evidence.event(at=at,session="2006-01-03",phase="test",payload={})
    with pytest.raises(ValueError,match="backwards"):
        evidence.event(at=at.replace(hour=21),session="2006-01-03",phase="test",payload={})
    evidence.close()


def test_historical_broker_fills_through_real_adapter(tmp_path):
    import asyncio
    from decimal import Decimal
    from research.full_system_pit import broker
    from sentinel.execution.contract import Side
    from research.full_system_pit.run import broker_accounting
    lifecycle, service=broker.manager("2006-01-03T00:00:00+00:00")
    try:
        service.market("2006-01-03T14:31:00+00:00","2006-01-03T14:30:00+00:00",
            [dict(sid="1",ticker="AAA",op=100.,raw=100.,raw_volume=10000.,split=1.,dividend=0.)],opened=True)
        adapter=broker.adapter(service)
        instrument=asyncio.run(adapter.resolve_instrument(security_id="1",symbol="AAA"))
        asyncio.run(adapter.submit(client_key="test-historical",instrument=instrument,side=Side.BUY,quantity=Decimal(2)))
        snapshot=service.snapshot()
        assert snapshot["positions"]["AAA"]=="2"
        broker_accounting(snapshot)
        assert service.drain()
    finally:
        lifecycle.shutdown()
