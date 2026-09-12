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
          volume REAL,raw_volume REAL,split REAL,dividend REAL,
          PRIMARY KEY(day,sid)) WITHOUT ROWID;
      CREATE INDEX obs_sid_day ON obs(sid,day);
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
    db.execute("CREATE TABLE splits AS SELECT sid,day,split FROM obs WHERE split<>1")
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


def test_reported_zero_volume_is_present_and_remains_distinct_from_missing(tmp_path):
    from sentinel.feed.coherence import SeedSessionCounts
    path=fixture(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE obs SET volume=0,raw_volume=0 WHERE day='2006-01-03'")
        db.execute("UPDATE obs SET volume=NULL,raw_volume=NULL WHERE day='2006-01-04'")
    p=Provider(path,tmp_path/"exports")
    p.advance(datetime.fromisoformat("2006-01-04T22:00:00+00:00"))
    zero,missing=list(p.row_stream("SEP",{}))
    assert zero["volume"]==0. and missing["volume"] is None
    assert SeedSessionCounts().add(zero,resolved=True).volume==1
    assert SeedSessionCounts().add(missing,resolved=True).volume==0


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


def test_incremental_intersections_preserve_old_split_corrections(tmp_path):
    from itertools import product
    p=provider(tmp_path,"2006-01-05")
    complete=list(p.row_stream("SEP",{}))
    dates=("2006-01-02","2006-01-04","2006-01-05","2006-01-06")
    for start,end,lower,upper in product(dates,repeat=4):
        expected=[r for r in complete if start<=r["date"]<=end
                  and lower<=r["lastupdated"]<=upper]
        actual=list(p.row_stream("SEP",{"date.gte":start,"date.lte":end,
                    "lastupdated.gte":lower,"lastupdated.lte":upper}))
        assert actual==expected,(start,end,lower,upper)


def test_incremental_queries_do_not_scan_unrelated_old_history(tmp_path):
    path=fixture(tmp_path)
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO obs VALUES(?,?,?,?,?,?,?,?,?,?)",
            (("2006-01-03",str(100+i),"OLD"+str(i),10.,10.,10.,1000.,1000.,1.,0.)
             for i in range(50000)))
    p=Provider(path,tmp_path/"exports")
    p.advance(datetime.fromisoformat("2006-01-05T22:00:00+00:00"))
    calls=0
    def budget():
        nonlocal calls
        calls+=1
        return calls>50
    p.db.set_progress_handler(budget,1000)
    try:
        rows=list(p.row_stream("SEP",{"lastupdated.gte":"2006-01-05"}))
    finally:
        p.db.set_progress_handler(None,0)
    assert len(rows)==4 and {r["ticker"] for r in rows}=={"AAA","IPO"}


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


def test_real_source_membrane_proves_ticker_and_export_completeness(tmp_path):
    from research.sharadar_replay.runtime import simulated_runtime
    from sentinel.feed import sharadar,snapshot_source,snapshot_export
    p=provider(tmp_path)
    with simulated_runtime(p,commit="0"*40):
        tickers=list(snapshot_source.fetch_table(sharadar.TICKERS))
        first,_=snapshot_export.fetch_complete_sep(start="2006-01-03",end="2006-01-04")
        second,_=snapshot_export.fetch_complete_sep(start="2006-01-03",end="2006-01-04")
    assert len(tickers)==1 and tickers[0]["ticker"]=="AAA"
    assert len(first)==2 and first==second


def test_special_dividends_follow_the_historical_share_basis(tmp_path):
    path=fixture(tmp_path)
    with sqlite3.connect(path) as db:
        row=dict(action="specialdividend",ticker="AAA",vendor_value="0.5",known_by="2006-01-04T00:00:00+00:00")
        db.execute("INSERT INTO actions VALUES(?,?,?)",("2006-01-04","1",json.dumps(row)))
    p=Provider(path,tmp_path/"exports")
    p.advance(datetime.fromisoformat("2006-01-03T22:00:00+00:00"))
    assert list(p.row_stream("ACTIONS",{}))==[]
    p.advance(datetime.fromisoformat("2006-01-04T22:00:00+00:00"))
    assert next(p.row_stream("ACTIONS",{}))["value"]==1.
    p.advance(datetime.fromisoformat("2006-01-05T22:00:00+00:00"))
    assert next(p.row_stream("ACTIONS",{}))["value"]==.5


def test_cash_return_uses_published_prices_and_their_own_predecessor():
    from types import SimpleNamespace
    from sentinel.core.session import DefensiveBar
    from sentinel.shadow_observation import ShadowObservationRefused
    from research.full_system_pit.run import published_cash_factors
    previous=DefensiveBar("2006-01-03","SENTINEL:BIL","BIL",100.,100.,200.,100.)
    current=DefensiveBar("2006-01-04","SENTINEL:BIL","BIL",101.,102.,204.,102.)
    published=SimpleNamespace(session="2006-01-04",defensive_bar=current,defensive_previous_bar=previous)
    assert published_cash_factors(published)==(1.01,102/101)
    published.defensive_previous_bar=None
    with pytest.raises(ShadowObservationRefused):
        published_cash_factors(published)


@pytest.mark.parametrize("corruption",[None,"quantity_and_mark","lost_lot"])
def test_position_comparison_detects_changes_hidden_by_aggregate_nav(corruption):
    from types import SimpleNamespace
    from research.full_system_pit.compare import compare_composition
    state=SimpleNamespace(wealth_core={"cash":40.,"episodes":{
        "0":dict(security_id="1",ticker="AAA",current_shares=2.),
        "1":dict(security_id="1",ticker="AAA",current_shares=3.)}},
        last_known={"1":10.},ledger={"receivables":[dict(amount=10.)]})
    expected=[]
    for bucket,value,effective,next_target in (("STOCK",50.,27.5,0.),
            ("CORE_CASH",40.,22.,0.),("DIVIDEND_RECEIVABLE",10.,5.5,0.),
            ("TBILL_SLEEVE",0.,45.,100.)):
        expected.append(dict(bucket=bucket,security_id="1" if bucket=="STOCK" else "",
            ticker="AAA",quantity=5.,mark=10.,lot_count=2,reference_value=value,
            shadow_weight_pct=value,effective_model_weight_pct=effective,
            next_target_model_weight_pct=next_target))
    if corruption=="quantity_and_mark":
        for episode in state.wealth_core["episodes"].values():
            episode["current_shares"]*=2
        state.last_known["1"]=5.
    elif corruption=="lost_lot":
        state.wealth_core["episodes"].pop("1")
        state.wealth_core["episodes"]["0"]["current_shares"]=5.
    if corruption is None:
        positions,buckets=compare_composition(expected,state,100.,.55,0.)
        assert positions["1"]["quantity"]==5. and buckets["DIVIDEND_RECEIVABLE"]==10.
    else:
        with pytest.raises(Divergence,match="position"):
            compare_composition(expected,state,100.,.55,0.)


def test_full_book_observer_leaves_economic_replay_hashes_unchanged():
    import math
    from sentinel.feed.calendar import sessions_in_range
    from stock_strategy_shared.wealth_core.feed import SecurityMeta,VendorBar
    from stock_strategy_shared.wealth_core.run import run_with_hashes
    from stock_strategy_shared.wealth_core.v5 import config
    from research.full_system_pit.evidence import encode
    from research.full_system_pit.run import trace_wealth_core
    dates=sessions_in_range("2006-01-03","2006-07-14")
    meta={str(i):SecurityMeta(str(i),"S"+str(i),"Domestic Common Stock",
                             first_session=dates[0]) for i in range(30)}
    bars={}
    for index,day in enumerate(dates):
        rows=[]
        for i in range(30):
            price=(20+i)*(1.002+i/100000)**index*(1+.002*math.sin(index+i/10))
            rows.append(VendorBar(day,str(i),"S"+str(i),price,price,1e8,signal_close=price))
        bars[day]=rows
    def replay():
        return run_with_hashes(sessions=dates,bars_by_session=bars,
                               meta=meta,starting_cash=100000.,cfg=config())
    _,baseline=replay()
    receipts=[]
    with trace_wealth_core(lambda phase,payload:receipts.append((phase,payload))):
        _,observed=replay()
    assert baseline.to_dict()==observed.to_dict()
    assert [p["session"] for _,p in receipts]==dates
    assert any(p["fills"] for _,p in receipts)
    assert any(c["score"] is not None for _,p in receipts for c in p["decision"]["candidates"])
    for phase,payload in receipts:
        assert phase=="wealth_core_transition"
        assert {"decision","fills","terminal_results","cancelled","rank_history"}<=payload.keys()
        encode(payload)


@pytest.mark.parametrize("day,hour",[("2006-01-03",14),("2006-07-03",13)])
def test_exchange_clock_is_normalized_to_utc_for_evidence(tmp_path,day,hour):
    from research.full_system_pit.run import market_window
    opened,closed=market_window(day)
    assert opened.tzinfo==closed.tzinfo==timezone.utc
    assert opened.hour==hour and opened.minute==30
    e=Evidence(tmp_path/"clock",{})
    e.event(at=opened,session=day,phase="open",payload={})
    e.event(at=closed,session=day,phase="close",payload={})
    e.close()
    assert verify(tmp_path/"clock")["events"]==2


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


@pytest.mark.parametrize("symbol",["AAA","AAA-X"])
def test_historical_broker_fills_through_real_adapter(tmp_path,symbol):
    import asyncio
    from decimal import Decimal
    from research.full_system_pit import broker
    from sentinel.execution.contract import Side
    from research.full_system_pit.run import broker_accounting
    lifecycle, service=broker.manager("2006-01-03T00:00:00+00:00")
    try:
        rows=[dict(sid="1",ticker=symbol,op=100.,raw=100.,raw_volume=10000.,split=1.,dividend=0.)]
        service.market("2006-01-03T14:31:00+00:00","2006-01-03T14:30:00+00:00",rows,opened=True)
        adapter=broker.adapter(service)
        instrument=asyncio.run(adapter.resolve_instrument(security_id="1",symbol=symbol))
        asyncio.run(adapter.submit(client_key="test-historical",instrument=instrument,side=Side.BUY,quantity=Decimal(2)))
        snapshot=service.snapshot()
        assert snapshot["positions"][symbol.replace("-",".")]=="2"
        broker_accounting(snapshot)
        asyncio.run(adapter.submit(client_key="test-historical-sell",instrument=instrument,side=Side.SELL,quantity=Decimal(2)))
        assert service.snapshot()["unsettled"]=="200.0"
        service.market("2006-01-04T14:31:00+00:00","2006-01-04T14:30:00+00:00",rows,opened=True)
        snapshot=service.snapshot()
        assert snapshot["unsettled"]=="0" and len(snapshot["settlements"])==1
        broker_accounting(snapshot)
        assert service.drain()
    finally:
        lifecycle.shutdown()
