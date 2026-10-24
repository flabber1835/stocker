"""Shared physical blocks preserve independent logical snapshots on real PG."""
from __future__ import annotations

import copy

import pytest

from sentinel.feed import calendar, normalized_layout as layout, rolling_store as storage
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark, PriceWindow, RestartRequirement, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401

NORMALIZATION = 'normalized-layout-qualification/1'


def rows(window):
    return [CanonicalBar(security_id='asset-A',session=day,ticker='AAA',close_signal=50,
        close_unadjusted=100,open_unadjusted=99,volume=1000,split_ratio=1,dividend_per_share=0)
        for day in window.sessions]


def benchmarks(window):
    return [CanonicalBenchmark(session=day,spy_total_return=600,bil_open_signal=90,
        bil_close_signal=91,bil_close_adjusted=92,bil_close_unadjusted=93) for day in window.sessions]


def candidate(conn, *, shared=True, bars=None, evidence=None):
    window = PriceWindow.through('2026-09-14')
    ref = storage.put_evidence(conn,{'schema':'test-layout-reference','securities':['asset-A']})
    source = storage.put_evidence(conn,evidence or {'schema':'test-layout-source','observation':'same'})
    identity = storage.begin(conn,window=window,reference_sha256=ref,source_evidence_sha256=source,
        expected_publication_version=None,dependencies_sha256=digest({}))
    bars = rows(window) if bars is None else bars
    writer = None
    if shared:
        writer = layout.SessionBlockWriter(conn,identity,normalization_version=NORMALIZATION,
            calendar_version=calendar.calendar_version())
        assert writer.write_bars(iter(bars)) == len(bars)
        writer.write_benchmarks(benchmarks(window))
    else:
        storage.write_bars(conn,identity,bars)
        storage.write_benchmarks(conn,identity,benchmarks(window))
    manifest = storage.seal(conn,identity,expected_keys=((str(day),'asset-A') for day in window.sessions),
        normalization_version=NORMALIZATION,requirements=RestartRequirement())
    return identity,manifest,writer


def test_shared_and_legacy_rows_have_exact_same_logical_identity(conn):
    old, before, _ = candidate(conn,shared=False)
    new, after, writer = candidate(conn)
    assert old != new and before == after and before.snapshot_id == after.snapshot_id
    assert list(storage.read_bars(conn,old)) == list(storage.read_bars(conn,new))
    assert list(storage.read_benchmarks(conn,old)) == list(storage.read_benchmarks(conn,new))
    assert storage.verify_content(conn,new).snapshot_id == before.snapshot_id
    assert writer.rows == [] and writer.reused_blocks == 0
    assert conn.execute('SELECT COUNT(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',(new,)).fetchone()[0] == 0
    physical = conn.execute('SELECT layout FROM sentinel_candidate_layouts WHERE candidate_id=%s',(new,)).fetchone()[0]
    assert physical['snapshot_id'] == before.snapshot_id
    assert len(physical['references']) == 600


def test_reuse_requires_complete_identical_content_not_overlapping_dates(conn):
    first, old, _ = candidate(conn)
    second, same, reused = candidate(conn,evidence={'schema':'test-layout-source','observation':'new'})
    assert old.snapshot_id != same.snapshot_id  # New observed source authority remains distinct.
    assert old.bars_sha256 == same.bars_sha256
    assert reused.reused_blocks == 600
    changed = rows(old.window)
    changed[17] = changed[17].model_copy(update={'dividend_per_share':1.25})
    third, updated, partly = candidate(conn,bars=changed)
    assert partly.reused_blocks == 599
    assert updated.bars_sha256 != old.bars_sha256
    assert conn.execute('SELECT COUNT(*) FROM sentinel_normalized_blocks').fetchone()[0] == 601
    assert storage.manifest(conn,first) == old
    assert storage.manifest(conn,second) == same
    assert list(storage.read_bars(conn,third))[17].dividend_per_share == 1.25


def test_single_session_limit_and_order_are_enforced_without_full_window_buffer(conn, monkeypatch):
    window = PriceWindow.through('2026-09-14')
    values = rows(window)
    seen = []
    writer = object.__new__(layout.SessionBlockWriter)
    writer.rows,writer.references,writer.session = [],[],None
    writer._store = lambda kind,day,block: seen.append((kind,day,len(block)))
    assert writer.write_bars(iter(values)) == 300
    assert len(seen) == 300 and max(count for _,_,count in seen) == 1
    assert not writer.rows and writer.session is None
    with pytest.raises(layout.LayoutRefused,match='ORDER_CHANGED'):
        writer.write_bars(iter(values[:2][::-1]))
    monkeypatch.setattr(layout,'MAX_SESSION_ROWS',1)
    writer.rows,writer.session = [],None
    with pytest.raises(layout.LayoutRefused,match='BLOCK_LIMIT'):
        writer.write_bars([values[0],values[0].model_copy(update={'security_id':'asset-B'})])


@pytest.mark.parametrize('direction',['legacy-first','shared-first'])
def test_storage_guard_forbids_mixed_physical_ownership(conn,direction):
    window = PriceWindow.through('2026-09-14')
    ref = storage.put_evidence(conn,{'test':'mixed-layout'})
    identity = storage.begin(conn,window=window,reference_sha256=ref,source_evidence_sha256=ref,
        expected_publication_version=None,dependencies_sha256=digest({}))
    writer = layout.SessionBlockWriter(conn,identity,normalization_version=NORMALIZATION,
        calendar_version=calendar.calendar_version())
    row = rows(window)[0]
    if direction == 'legacy-first':
        storage.write_bars(conn,identity,[row])
        with pytest.raises(Exception,match='cannot mix'):
            writer.write_bars([row])
    else:
        writer.write_bars([row])
        with pytest.raises(Exception,match='cannot mix'):
            storage.write_bars(conn,identity,[row])


def test_bad_layout_header_is_refused_even_when_record_remains_self_consistent(conn):
    identity,manifest,_ = candidate(conn)
    layout.require_layout(conn,identity,manifest)
    with pytest.raises(layout.LayoutRefused,match='BLOCK_HEADER_CHANGED'):
        layout.require_layout(conn,identity,manifest.model_copy(update={'normalization_version':'unknown'}))


def test_removed_reference_binding_guard_is_detected(conn,monkeypatch):
    identity,manifest,_ = candidate(conn)
    altered = manifest.model_copy(update={'normalization_version':'unknown'})
    monkeypatch.setattr(layout,'_require_references',lambda *_:None)
    # Manifest identity binding still catches a wrong logical snapshot; use the
    # actual header guard directly so the falsifier targets this exact invariant.
    refs = conn.execute('SELECT kind,session,block_sha256 FROM sentinel_candidate_blocks WHERE candidate_id=%s '
        'ORDER BY kind,session',(identity,)).fetchall()
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        with pytest.raises(layout.LayoutRefused,match='BLOCK_HEADER_CHANGED'):
            layout._require_references(conn,refs,altered)


def test_mutation_and_missing_block_remain_visible(conn):
    identity,manifest,_ = candidate(conn)
    conn.commit()
    with pytest.raises(Exception,match='immutable'):
        conn.execute('DELETE FROM sentinel_candidate_blocks WHERE candidate_id=%s',(identity,))
    conn.rollback()
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('DELETE FROM sentinel_candidate_blocks WHERE candidate_id=%s AND session=%s AND kind=%s',
        (identity,manifest.window.sessions[0],'BARS'))
    with pytest.raises(layout.LayoutRefused,match='AXIS_CHANGED'):
        storage.manifest(conn,identity)


def test_candidate_rollback_cannot_leave_orphaned_block_or_reference(conn):
    conn.commit()
    candidate(conn)
    assert conn.execute('SELECT COUNT(*) FROM sentinel_candidate_blocks').fetchone()[0] == 600
    conn.rollback()
    assert conn.execute('SELECT COUNT(*) FROM sentinel_candidate_blocks').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM sentinel_normalized_blocks').fetchone()[0] == 0


def test_shared_payload_cannot_be_released_while_a_live_candidate_references_it(conn):
    identity,manifest,_ = candidate(conn)
    sha = conn.execute('SELECT block_sha256 FROM sentinel_candidate_blocks WHERE candidate_id=%s LIMIT 1',
        (identity,)).fetchone()[0]
    with pytest.raises(Exception,match='immutable|retention'):
        conn.execute('UPDATE sentinel_normalized_blocks SET canonical_payload=NULL WHERE block_sha256=%s',(sha,))


def test_actual_reader_uses_single_registered_view_owner(conn):
    assert layout.candidate_query(conn,'SELECT * FROM sentinel_snapshot_bars WHERE candidate_id=%s') == (
        'SELECT * FROM sentinel_candidate_bars WHERE candidate_id=%s')
    assert layout.read_table(conn,'BENCHMARKS') == 'sentinel_candidate_benchmarks'
    assert layout.available(conn)


def test_query_plan_guard_rejects_shared_payload_full_scan(monkeypatch):
    from sentinel.feed.rolling_go_health import _indexed
    class Conn:
        def __init__(self,node): self.node=node
        def execute(self,*_): return self
        def fetchone(self): return ([{'Plan':self.node}],)
    good = {'Plans':[
        {'Relation Name':'sentinel_candidate_blocks','Node Type':'Index Scan','Index Name':'sentinel_candidate_blocks_pkey'},
        {'Relation Name':'sentinel_normalized_blocks','Node Type':'Index Scan','Index Name':'sentinel_normalized_blocks_pkey'}]}
    assert _indexed(Conn(good),'SELECT fixture',())
    broken = copy.deepcopy(good)
    broken['Plans'][1] = {'Relation Name':'sentinel_normalized_blocks','Node Type':'Seq Scan'}
    assert not _indexed(Conn(broken),'SELECT fixture',())
