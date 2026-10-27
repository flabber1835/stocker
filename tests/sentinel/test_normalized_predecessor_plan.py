"""Same prior prices, with a physically bounded shared-block traversal."""
import pytest

from sentinel.feed import calendar, normalized_layout as layout, read_contract, rolling_store as storage
from sentinel.feed.rolling_contract import CanonicalBar, PriceWindow, RestartRequirement, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401
from tests.sentinel.test_normalized_layout import benchmarks


def candidate(conn,shared):
    window=PriceWindow.through('2026-09-14')
    ref=storage.put_evidence(conn,{'schema':'predecessor-reference','securities':['A','B']})
    source=storage.put_evidence(conn,{'schema':'predecessor-source'})
    identity=storage.begin(conn,window=window,reference_sha256=ref,source_evidence_sha256=source,
        expected_publication_version=None,dependencies_sha256=digest({}))
    bars=[CanonicalBar(security_id=sid,session=day,ticker=sid,close_signal=10.25+i,
        close_unadjusted=20.5+i,open_unadjusted=20,volume=1000,split_ratio=1,dividend_per_share=0)
        for i,day in enumerate(window.sessions) for sid in ('A','B') if sid=='B' or i in {0,2,5}]
    if shared:
        writer=layout.SessionBlockWriter(conn,identity,normalization_version='predecessor-test/1',
            calendar_version=calendar.calendar_version())
        writer.write_bars(iter(bars));writer.write_benchmarks(benchmarks(window))
    else:
        storage.write_bars(conn,identity,bars);storage.write_benchmarks(conn,identity,benchmarks(window))
    storage.seal(conn,identity,expected_keys=((str(b.session),b.security_id) for b in bars),
        normalization_version='predecessor-test/1',requirements=RestartRequirement())
    return identity,window


@pytest.mark.parametrize('shared',[False,True])
def test_exact_original_results_for_gaps_domains_and_missing_rows(conn,shared):
    identity,window=candidate(conn,shared)
    original=read_contract.route(layout._PREDECESSOR_POINT,shared=layout.available(conn))
    actual=layout.candidate_query(conn,layout._PREDECESSOR_POINT)
    for index in (0,1,2,5,8,299):
        for sid in ('A','B','missing'):
            args=(identity,sid,str(window.sessions[index]))
            expected=conn.execute(original,args).fetchone()
            assert conn.execute(actual,args).fetchone()==expected
    row=conn.execute(actual,(identity,'A',str(window.sessions[5]))).fetchone()
    assert str(row[0])==str(window.sessions[2]) and row[1:] == (12.25,22.5)


def assert_one_block(conn,identity,window):
    sql=layout.candidate_query(conn,layout._PREDECESSOR_POINT)
    plan=conn.execute('EXPLAIN (ANALYZE,FORMAT JSON) '+sql,
        (identity,'B',str(window.sessions[-1]))).fetchone()[0][0]['Plan']
    def walk(node):
        yield node
        for child in node.get('Plans',[]):yield from walk(child)
    scans=[node for node in walk(plan) if node.get('Function Name')=='jsonb_to_recordset']
    assert scans and max(node['Actual Loops'] for node in scans)==1


def test_yesterday_match_decodes_one_block_on_real_pg(conn):
    identity,window=candidate(conn,True)
    assert_one_block(conn,identity,window)


def test_original_view_route_falsifies_work_bound(conn,monkeypatch):
    identity,window=candidate(conn,True)
    monkeypatch.setattr(layout,'_ORDERED_PREDECESSOR',
        read_contract.route(layout._PREDECESSOR_POINT,shared=True))
    with pytest.raises(AssertionError):assert_one_block(conn,identity,window)


def test_only_exact_point_query_uses_fast_physical_route(monkeypatch):
    monkeypatch.setattr(layout,'available',lambda conn:True)
    assert layout.candidate_query(None,layout._PREDECESSOR_POINT)==layout._ORDERED_PREDECESSOR
    other=layout._PREDECESSOR_POINT.replace('session<%s','session<=%s')
    assert layout.candidate_query(None,other)==read_contract.route(other,shared=True)
    assert layout._ORDERED_PREDECESSOR.count('%s')==3


def test_operation_router_validates_once_and_standalone_calls_remain_fresh(monkeypatch):
    calls=[]
    monkeypatch.setattr(layout,'available',lambda conn:calls.append(conn) or True)
    connection=object()
    route=layout.query_router(connection)
    for _ in range(100):
        assert route(layout._PREDECESSOR_POINT)==layout._ORDERED_PREDECESSOR
    assert calls==[connection]
    layout.candidate_query(connection,layout._PREDECESSOR_POINT)
    assert calls==[connection,connection]
