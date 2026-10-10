"""Bounded discovery and draining beside a much larger live generation."""
from uuid import uuid4

from sentinel.execution import journal
from sentinel.feed import retention, store
from tests.sentinel.test_rolling_history_retention import (
    conn, pg, source, operational_source, publish, MAINTAIN,
)


def _nodes(plan):
    yield plan
    for child in plan.get('Plans', []):
        yield from _nodes(child)


def test_empty_and_benchmark_only_retirements_use_index_probes_and_drain(
        conn, operational_source, monkeypatch):
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    first, second, third, current = [publish(conn) for _ in range(4)]
    conn.commit()
    # A real unsealed, unowned candidate is pinned and cannot be retired.
    # Populate it through the production insert guard; no trigger is disabled.
    large = uuid4()
    conn.execute('INSERT INTO sentinel_price_candidates '
        '(candidate_id,window_start,window_end,session_axis,reference_sha256,'
        'source_evidence_sha256,expected_publication_version,dependencies_sha256) '
        'SELECT %s,window_start,window_end,session_axis,reference_sha256,'
        'source_evidence_sha256,expected_publication_version,dependencies_sha256 '
        'FROM sentinel_price_candidates WHERE candidate_id=%s',
        (large, current['candidate_id']))
    conn.execute('INSERT INTO sentinel_snapshot_bars '
        '(candidate_id,session,security_id,ticker,close_signal,close_unadjusted,'
        'open_unadjusted,volume,split_ratio,dividend_per_share) '
        "SELECT %s,window_end,i::text,'X',50,50,50,100,1,0 "
        'FROM sentinel_price_candidates CROSS JOIN generate_series(1,20000) i '
        'WHERE candidate_id=%s', (large, large))
    conn.commit()
    with journal.writer_lock(conn), store.corpus_write_lock(conn):
        for result in (first, second, third):
            conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)',
                         (result['candidate_id'],))
        for table in ('sentinel_snapshot_bars','sentinel_snapshot_benchmarks'):
            conn.execute(f'DELETE FROM {table} WHERE candidate_id=%s', (first['candidate_id'],))
        conn.execute('DELETE FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                     (second['candidate_id'],))
    conn.execute('ANALYZE sentinel_snapshot_bars')
    conn.execute('ANALYZE sentinel_snapshot_benchmarks')
    conn.commit()

    assert str(conn.execute(retention.RETIRED_PAYLOAD_QUERY).fetchone()[0]) == second['candidate_id']
    plan = conn.execute('EXPLAIN (ANALYZE, TIMING FALSE, FORMAT JSON) ' +
                        retention.RETIRED_PAYLOAD_QUERY).fetchone()[0][0]['Plan']
    bulk = [node for node in _nodes(plan) if node.get('Relation Name') in {
        'sentinel_snapshot_bars','sentinel_snapshot_benchmarks'}]
    assert {node['Relation Name'] for node in bulk} == {
        'sentinel_snapshot_bars','sentinel_snapshot_benchmarks'}
    assert all(node['Node Type'] in {'Index Scan','Index Only Scan'} for node in bulk)
    conn.commit()

    # One hundred rows per wake; benchmark-only work must precede newer bars.
    monkeypatch.setattr(retention, 'maintain', MAINTAIN)
    deleted = 0
    visited = []
    for _ in range(15):
        step = retention.maintain(conn, batch_rows=100)
        assert step['status'] == 'COMPLETE'
        assert 0 <= step['deleted_rows'] <= 100
        deleted += step['deleted_rows']
        if step['candidate_id']:
            visited.append(step['candidate_id'])
        if not step['more_work']:
            break
    assert deleted == 1200
    assert visited[:3] == [second['candidate_id']]*3
    assert set(visited[3:]) == {third['candidate_id']}
    assert conn.execute(retention.RETIRED_PAYLOAD_QUERY).fetchone() is None
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                        (large,)).fetchone()[0] == 20000
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                        (current['candidate_id'],)).fetchone()[0] == 600
    assert conn.execute('SELECT sentinel_snapshot_pins(%s)', (large,)).fetchone()[0] == ['UNOWNED_CANDIDATE']
