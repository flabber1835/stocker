"""Private PG work-count and atomic-progress proof, separate from retirement authority.

The small regular relations below exercise the actual retention access SQL and
transaction protocol. They deliberately are not a replacement for the production
pin/ownership/backup acceptance tests: their retired set is synthetic and fixed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
import inspect
import json
import math
import textwrap
import time
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel.feed import retention
from tests.support.postgres import _EphemeralPostgres


CID = '00000000-0000-0000-0000-000000000001'
LIVE_CID = '00000000-0000-0000-0000-000000000002'
SCHEMA = 'sentinel.retention-progress/1'


@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@dataclass
class Storage:
    conn: object
    dsn: str
    schema: str

    def peer(self):
        connection = psycopg.connect(self.dsn)
        connection.execute(sql.SQL('SET search_path TO {},public').format(sql.Identifier(self.schema)))
        connection.commit()
        return connection


@pytest.fixture
def storage(pg):
    conn = psycopg.connect(pg.sync_dsn)
    schema = 'bounded_retention_' + uuid.uuid4().hex
    conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    conn.execute(sql.SQL('SET search_path TO {},public').format(sql.Identifier(schema)))
    conn.execute('CREATE TABLE sentinel_snapshot_retirements('
                 'candidate_id uuid PRIMARY KEY,retired_at timestamptz DEFAULT clock_timestamp())')
    conn.execute('CREATE TABLE sentinel_snapshot_bars('
                 'candidate_id uuid NOT NULL,session date NOT NULL,security_id text NOT NULL,'
                 'payload text,PRIMARY KEY(candidate_id,session,security_id)) '
                 'WITH(autovacuum_enabled=false)')
    conn.execute('CREATE TABLE sentinel_snapshot_benchmarks('
                 'candidate_id uuid NOT NULL,session date NOT NULL,payload text,'
                 'PRIMARY KEY(candidate_id,session)) WITH(autovacuum_enabled=false)')
    conn.execute('CREATE TABLE sentinel_snapshot_maintenance('
                 'id boolean PRIMARY KEY,diagnostic jsonb NOT NULL,'
                 'updated_at timestamptz DEFAULT clock_timestamp())')
    conn.execute("INSERT INTO sentinel_snapshot_maintenance(id,diagnostic) VALUES(TRUE,'{}')")
    conn.execute('CREATE TABLE class_effects(class_id integer,label text)')
    conn.commit()
    try:
        yield Storage(conn=conn, dsn=pg.sync_dsn, schema=schema)
    finally:
        conn.rollback()
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def raw_progress(**changes):
    value = dict(schema=SCHEMA, known_retirement_count=0, metadata_cursor=None,
                 next_class=0, legacy=None, active=None)
    value.update(changes)
    return value


def saved_diagnostic(conn):
    value = conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance WHERE id').fetchone()[0]
    conn.rollback()
    return value


def set_diagnostic(conn, value):
    conn.execute('UPDATE sentinel_snapshot_maintenance SET diagnostic=%s::jsonb WHERE id',
                 (json.dumps(value),))
    conn.commit()


def count_rows(conn, table='sentinel_snapshot_bars'):
    count = conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
    conn.rollback()
    return count


@contextmanager
def old_snapshot(storage):
    peer = storage.peer()
    try:
        peer.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        peer.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()
        yield peer
    finally:
        peer.rollback()
        peer.close()


def relation_blocks(conn, table='sentinel_snapshot_bars'):
    value = conn.execute('SELECT pg_relation_size(%s::regclass),'
                         "current_setting('block_size')::integer", (table,)).fetchone()
    conn.rollback()
    return math.ceil(value[0] / value[1])


def seed_bars(conn, *, total, retired=True, candidate=CID):
    conn.execute('INSERT INTO sentinel_snapshot_bars '
                 "SELECT %s::uuid,'2026-11-06'::date,lpad(g::text,8,'0'),repeat('x',64) "
                 'FROM generate_series(1,%s)g', (candidate, total))
    if retired:
        conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (candidate,))
    conn.commit()


def plan_scans(plan, table='sentinel_snapshot_bars'):
    found = []
    def walk(node):
        if node.get('Relation Name') == table and 'Scan' in node.get('Node Type', ''):
            found.append(node)
        for child in node.get('Plans', []):
            walk(child)
    walk(plan['Plan'])
    return found


def plan_nodes(plan):
    found = []
    def walk(node):
        found.append(node)
        for child in node.get('Plans', []):
            walk(child)
    walk(plan['Plan'])
    return found


class MeasuredConnection:
    """Measure exact production SQL in a rolled-back savepoint, then run it normally."""

    def __init__(self, conn):
        self.conn = conn
        self.plans = []
        self.physical_select_plans = []
        self.physical_select_calls = []
        self.physical_delete_calls = []
        self.logical_plans = []
        self.seek_plans = []

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, query, parameters=None):
        physical_select = isinstance(query, str) and query.startswith('WITH physical AS MATERIALIZED')
        physical_delete = (isinstance(query, str) and query.startswith('WITH deleted AS')
                           and 'DELETE FROM sentinel_snapshot_' in query)
        logical = (isinstance(query, str) and query.startswith('DELETE FROM sentinel_snapshot_')
                   and 'ctid' in query and 'ANY' in query)
        seek = (isinstance(query, str) and query.startswith('SELECT ctid,')
                and 'FROM sentinel_snapshot_' in query)
        if seek:
            self.seek_plans.append(self.conn.execute(
                'EXPLAIN (ANALYZE,BUFFERS,TIMING OFF,FORMAT JSON) ' + query,
                parameters).fetchone()[0][0])
        if physical_select:
            self.physical_select_calls.append((query, parameters))
        if physical_delete:
            self.physical_delete_calls.append((query, parameters))
        if physical_select or physical_delete or logical:
            self.conn.execute('SAVEPOINT measured_physical_delete')
            value = self.conn.execute(
                'EXPLAIN (ANALYZE,BUFFERS,TIMING OFF,FORMAT JSON) ' + query,
                parameters).fetchone()[0][0]
            self.conn.execute('ROLLBACK TO SAVEPOINT measured_physical_delete')
            self.conn.execute('RELEASE SAVEPOINT measured_physical_delete')
            if physical_select:
                self.physical_select_plans.append(value)
            elif physical_delete:
                self.plans.append(value)
            else:
                self.logical_plans.append(value)
        return self.conn.execute(query, parameters)


@pytest.mark.parametrize('change', [
    {'schema': 'sentinel.retention-progress/2'},
    {'known_retirement_count': -1}, {'known_retirement_count': True},
    {'next_class': -1}, {'next_class': 7},
    {'metadata_cursor': 'not-a-uuid'}, {'completed_candidates': [CID]},
])
def test_progress_rejects_unknown_or_impossible_state(change):
    with pytest.raises(ValueError):
        retention.RetentionProgress.model_validate(raw_progress(**change))


def test_legacy_metadata_cursor_never_claims_retired_payload_was_traversed(storage):
    conn = storage.conn
    seed_bars(conn, total=1)
    set_diagnostic(conn, {'scan_cursor': LIVE_CID, 'status': 'RETRY'})
    assert retention._read_progress(conn) is None
    progress = retention._initial_progress(conn)
    assert str(progress.metadata_cursor) == LIVE_CID
    assert progress.known_retirement_count == 1
    assert progress.legacy.phase == 'BARS'
    assert (progress.legacy.position_block, progress.legacy.position_offset) == (0, 0)
    assert progress.active is None
    conn.rollback()
    assert count_rows(conn) == 1


def test_malformed_saved_progress_is_not_treated_as_an_empty_heap(storage):
    conn = storage.conn
    seed_bars(conn, total=1)
    original = {'status': 'COMPLETE', 'progress': raw_progress(known_retirement_count=-1)}
    set_diagnostic(conn, original)
    with pytest.raises(ValueError):
        retention._read_progress(conn)
    conn.rollback()
    assert saved_diagnostic(conn) == original
    assert count_rows(conn) == 1


def vacuum(conn, table, *, full=False):
    conn.rollback()
    conn.autocommit = True
    try:
        conn.execute(sql.SQL('VACUUM {} ANALYZE {}').format(
            sql.SQL('FULL') if full else sql.SQL(''), sql.Identifier(table)))
    finally:
        conn.autocommit = False


def save_step(conn, progress, stats):
    retention._write_result(conn, {'status': 'COMPLETE', **stats}, progress)
    conn.commit()


def assert_depleted_prefix_converges(storage, metrics_path=None):
    conn = storage.conn
    seed_bars(conn, total=41000)
    seed_bars(conn, total=17, retired=False, candidate=LIVE_CID)
    vacuum(conn, 'sentinel_snapshot_bars')
    with old_snapshot(storage) as peer:
        assert peer.execute("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() "
                            "AND locktype='advisory'").fetchone()[0] == 0
        conn.execute("DELETE FROM sentinel_snapshot_bars WHERE candidate_id=%s "
                     "AND security_id<='00040000'", (CID,))
        conn.commit()
        baseline = conn.execute(
            'EXPLAIN (ANALYZE,BUFFERS,TIMING OFF,FORMAT JSON) '
            'SELECT TRUE FROM sentinel_snapshot_bars WHERE candidate_id=%s '
            'ORDER BY session,security_id LIMIT 1', (CID,)).fetchone()[0][0]
        assert max(node.get('Heap Fetches', 0) for node in plan_scans(baseline)) >= 40000
        conn.rollback()
        blocks = relation_blocks(conn)
        progress = retention._initial_progress(conn)
        measured = MeasuredConnection(conn)
        batch = 127
        quantum = progress.legacy.page_quantum
        maximum_steps = math.ceil(blocks / quantum) + math.ceil(1000 / batch) + 6
        deleted = 0
        for _ in range(maximum_steps):
            if progress.legacy is None:
                break
            previous_selects = len(measured.physical_select_calls)
            updated, stats = retention._bootstrap_step(measured, progress, batch_rows=batch)
            calls = measured.physical_select_calls[previous_selects:]
            assert len(calls) == len({(query, tuple(parameters[:2])) for query, parameters in calls}), (
                'one extent repeated its bounded payload selection')
            assert 0 <= stats.get('deleted_rows', 0) <= batch
            deleted += stats.get('deleted_rows', 0)
            save_step(conn, updated, stats)
            # Restart from the actual committed JSON rather than a cached object.
            progress = retention._read_progress(conn)
        assert progress.legacy is None, 'physical traversal failed to converge past the depleted prefix'
        assert deleted == 1000
        remaining = conn.execute('SELECT candidate_id::text,count(*) FROM sentinel_snapshot_bars '
                                 'GROUP BY candidate_id').fetchall()
        conn.rollback()
        assert remaining == [(LIVE_CID, 17)], 'retired tail remained or active payload was deleted'
        assert measured.plans
        cumulative = 0
        assert measured.physical_select_plans
        for plan in [*measured.physical_select_plans, *measured.plans]:
            scans = plan_scans(plan)
            assert scans
            assert all(node['Node Type'] in {'Tid Range Scan', 'Tid Scan'} for node in scans), scans
            ranges = [node for node in scans if node['Node Type'] == 'Tid Range Scan']
            if plan in measured.physical_select_plans:
                assert ranges, 'physical discovery lost its bounded range scan'
            for node in ranges:
                buffers = node.get('Shared Hit Blocks', 0) + node.get('Shared Read Blocks', 0)
                assert buffers <= quantum + 2, 'one extent scanned beyond its physical page cap'
                assert 'ctid >' in node.get('TID Cond', '')
                assert 'ctid <' in node.get('TID Cond', '')
                cumulative += buffers
        for query, parameters in measured.physical_delete_calls:
            assert 'ctid>%s::tid' in query and 'ctid<%s::tid' in query
            assert 'ctid=ANY(%s::tid[])' in query
            assert len(parameters[2]) <= batch
        bound = 2 * blocks + 2 * quantum * math.ceil(1000 / batch) + 64
        assert cumulative <= bound, 'cumulative work repeated the deleted prefix'
        if metrics_path is not None:
            metrics_path.write_text(json.dumps(dict(
                heap_blocks=blocks, page_quantum=quantum, batch_rows=batch,
                physical_select_statements=len(measured.physical_select_plans),
                physical_delete_statements=len(measured.plans), deleted_tail=deleted,
                preserved_active_rows=17, cumulative_range_buffers=cumulative,
                cumulative_range_buffer_bound=bound,
            ), indent=2))
        # The old ordinary snapshot remains genuinely older than every batch.
        assert peer.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0] == 41017


def test_actual_extent_delete_converges_with_cumulative_bounded_work(storage, tmp_path):
    assert_depleted_prefix_converges(storage, tmp_path/'physical-access-work.json')


def test_removed_physical_advancement_fails_convergence(storage, monkeypatch):
    original = retention._bootstrap_step
    def no_advancement(conn, progress, *, batch_rows):
        updated, stats = original(conn, progress, batch_rows=batch_rows)
        if (progress.legacy is not None and updated.legacy is not None
                and progress.legacy.phase == updated.legacy.phase == 'BARS'):
            position = updated.legacy.model_copy(update={
                'position_block': progress.legacy.position_block,
                'position_offset': progress.legacy.position_offset,
            })
            updated = updated.model_copy(update={'legacy': position})
        return updated, stats
    monkeypatch.setattr(retention, '_bootstrap_step', no_advancement)
    with pytest.raises(AssertionError, match='failed to converge'):
        assert_depleted_prefix_converges(storage)


def test_full_batch_keeps_the_unhandled_remainder_of_its_extent(storage):
    conn = storage.conn
    seed_bars(conn, total=300)
    progress = retention._initial_progress(conn)
    initial_upper = progress.legacy.upper_block
    updated, stats = retention._bootstrap_step(conn, progress, batch_rows=17)
    assert stats['deleted_rows'] == 17
    assert updated.legacy.phase == 'BARS'
    assert updated.legacy.position_block < initial_upper
    assert updated.legacy.position_offset > 0
    save_step(conn, updated, stats)
    assert count_rows(conn) == 283
    assert retention._read_progress(conn).legacy == updated.legacy
    conn.rollback()


def test_direct_bootstrap_caps_large_caller_selection_and_delete_at_5000(storage):
    conn = storage.conn
    conn.execute('INSERT INTO sentinel_snapshot_bars '
                 "SELECT %s::uuid,'2026-11-06'::date,g::text,NULL "
                 'FROM generate_series(1,12000)g', (CID,))
    conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (CID,))
    conn.commit()
    progress = retention._initial_progress(conn)
    measured = MeasuredConnection(conn)
    _updated, stats = retention._bootstrap_step(measured, progress, batch_rows=50000)
    assert stats['deleted_rows'] == 5000
    assert len(measured.physical_select_calls) == 1
    assert measured.physical_select_calls[0][1][-1] == 5001
    assert len(measured.physical_delete_calls[0][1][-1]) == 5000
    conn.rollback()
    assert count_rows(conn) == 12000


def algorithm_owner(monkeypatch):
    """Keep real PG locks/transactions; isolate backup/probe admission dependencies."""
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, 'require', lambda *_a, **_k: None)
    monkeypatch.setattr(retention, 'opening_execution_due', lambda _: False)
    monkeypatch.setattr(retention, '_possible_work', lambda _: True)
    original = retention._run_class
    def payload_only(conn, class_id, progress, *, batch_rows):
        if class_id == 2:
            return original(conn, class_id, progress, batch_rows=batch_rows)
        return progress, retention._stats()
    monkeypatch.setattr(retention, '_run_class', payload_only)


def test_publication_failure_rolls_back_payload_and_scan_position(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=40)
    progress = retention._initial_progress(conn)
    save_step(conn, progress, {'deleted_rows': 0})
    before = saved_diagnostic(conn)
    algorithm_owner(monkeypatch)
    observed = []
    def failed_publication(*args, **kwargs):
        observed.append(conn.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0])
        raise OSError('private simulated progress write failure')
    monkeypatch.setattr(retention, '_write_result', failed_publication)
    result = retention.maintain(conn, batch_rows=7)
    assert result['status'] == 'RETRY'
    assert observed == [33], 'failure was not injected after the real DELETE'
    assert count_rows(conn) == 40
    assert saved_diagnostic(conn)['progress'] == before['progress']


def test_lost_commit_acknowledgement_keeps_committed_delete_and_exact_progress(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=40)
    progress = retention._initial_progress(conn)
    save_step(conn, progress, {'deleted_rows': 0})
    algorithm_owner(monkeypatch)
    pending, lost = [False], [False]
    original = retention._write_result
    def publication(connection, result, updated):
        original(connection, result, updated)
        pending[0] = True
    monkeypatch.setattr(retention, '_write_result', publication)
    class LostAcknowledgement:
        def __getattr__(self, name):
            return getattr(conn, name)
        def commit(self):
            conn.commit()
            if pending[0] and not lost[0]:
                pending[0] = False
                lost[0] = True
                raise OSError('private commit acknowledgement lost after durability')
    result = retention.maintain(LostAcknowledgement(), batch_rows=7)
    assert lost[0] and result['status'] == 'RETRY'
    assert count_rows(conn) == 33
    updated = retention._read_progress(conn)
    conn.rollback()
    assert (updated.legacy.position_block, updated.legacy.position_offset) > (
        progress.legacy.position_block, progress.legacy.position_offset)
    assert retention.maintain(conn, batch_rows=7)['deleted_rows'] == 7
    assert count_rows(conn) == 26


def assert_retry_preserves_latest(storage):
    conn = storage.conn
    first = retention.RetentionProgress.model_validate(raw_progress())
    save_step(conn, first, {'status': 'COMPLETE', 'owner': 'first'})
    latest = first.model_copy(update={'next_class': 4, 'metadata_cursor': LIVE_CID})
    with storage.peer() as peer:
        retention._write_result(peer, {'status': 'COMPLETE', 'owner': 'later'}, latest)
        peer.commit()
    retention._record_retry(conn, {'status': 'RETRY', 'reason': 'synthetic observation unavailable'})
    result = saved_diagnostic(conn)
    assert 'progress' in result, 'newer committed progress was erased'
    assert result['progress'] == latest.model_dump(mode='json', by_alias=True)
    assert result['owner'] == 'later'
    assert result['status'] == 'RETRY'


def test_retry_diagnostic_merges_only_outcome_with_newer_committed_progress(storage):
    assert_retry_preserves_latest(storage)


def test_replacing_retry_progress_has_an_executed_falsifier(storage, monkeypatch):
    source = textwrap.dedent(inspect.getsource(retention._record_retry))
    guard = 'sentinel_snapshot_maintenance.diagnostic || EXCLUDED.diagnostic'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'EXCLUDED.diagnostic'), 'replaced-retention-progress', 'exec'),
         retention.__dict__, namespace)
    monkeypatch.setattr(retention, '_record_retry', namespace['_record_retry'])
    with pytest.raises(AssertionError, match='newer committed progress was erased'):
        assert_retry_preserves_latest(storage)


def test_cancelled_class_rolls_back_itself_and_commits_independent_class_progress(storage, monkeypatch):
    conn = storage.conn
    algorithm_owner(monkeypatch)
    attempted = []
    def classes(connection, class_id, progress, *, batch_rows):
        attempted.append(class_id)
        if class_id in {0, 1, 2}:
            connection.execute('INSERT INTO class_effects VALUES(%s,%s)', (class_id, 'changed'))
            if class_id == 1:
                connection.execute('SELECT pg_sleep(.8)')
            return progress, retention._stats(progress_made=True)
        return progress, retention._stats()
    monkeypatch.setattr(retention, '_run_class', classes)
    result = retention.maintain(conn, batch_rows=7)
    assert result['status'] == 'RETRY' and result['progress_made'] is True
    assert attempted[:3] == [0, 1, 2]
    rows = conn.execute('SELECT class_id FROM class_effects ORDER BY class_id').fetchall()
    conn.rollback()
    assert rows == [(0,), (2,)], 'one cancelled class rolled back independent completed work'
    assert result['class_errors'] == {'1': 'QueryCanceled'}
    assert 0 <= retention._read_progress(conn).next_class <= 6
    conn.rollback()


def test_traversal_beyond_current_eof_and_tail_vacuum_remains_conservative(storage):
    conn = storage.conn
    seed_bars(conn, total=200)
    progress = retention._initial_progress(conn)
    extent = progress.legacy
    conn.execute('DELETE FROM sentinel_snapshot_bars')
    conn.commit()
    vacuum(conn, 'sentinel_snapshot_bars')
    assert relation_blocks(conn) <= extent.upper_block
    progress = progress.model_copy(update={'legacy': extent.model_copy(update={
        'position_block': max(0, extent.upper_block - 1), 'position_offset': 0,
    })})
    updated, stats = retention._bootstrap_step(conn, progress, batch_rows=7)
    assert stats.get('deleted_rows', 0) == 0
    if updated.legacy is not None and updated.legacy.phase == 'BARS':
        updated, stats = retention._bootstrap_step(conn, updated, batch_rows=7)
        assert stats.get('deleted_rows', 0) == 0
    assert updated.legacy is None or updated.legacy.phase == 'BENCHMARKS'
    conn.rollback()


def test_heap_rewrite_invalidates_the_saved_physical_position(storage):
    conn = storage.conn
    seed_bars(conn, total=200)
    progress = retention._initial_progress(conn)
    old = progress.legacy
    # A stale high position must not be accepted after tuples acquire new CTIDs.
    progress = progress.model_copy(update={'legacy': old.model_copy(update={
        'position_block': max(0, old.upper_block - 1), 'position_offset': 0,
    })})
    conn.commit()
    vacuum(conn, 'sentinel_snapshot_bars', full=True)
    node = conn.execute("SELECT pg_relation_filenode('sentinel_snapshot_bars')").fetchone()[0]
    conn.rollback()
    assert node != old.relation_filenode
    updated, stats = retention._bootstrap_step(conn, progress, batch_rows=7)
    assert updated.legacy.relation_filenode == node
    if not stats['deleted_rows']:
        assert (updated.legacy.position_block, updated.legacy.position_offset) == (0, 0)
        updated, stats = retention._bootstrap_step(conn, updated, batch_rows=7)
    assert stats['deleted_rows'] == 7, 'rewritten heap was mistaken for a completed old scan'
    conn.rollback()


def logical_progress(conn, *, last_session=None, last_security_id=None, quantum=5000):
    progress = retention._initial_progress(conn)
    cursor = retention.CandidateCursor.model_validate_json(json.dumps(dict(
        candidate_id=CID, phase='BARS', last_session=last_session,
        last_security_id=last_security_id, row_quantum=quantum,
    )))
    return progress.model_copy(update={'legacy': None, 'active': cursor})


def test_logical_delete_5000_tid_array_has_no_candidate_prefix_scan(storage, tmp_path):
    conn = storage.conn
    seed_bars(conn, total=45001)
    seed_bars(conn, total=3, retired=False, candidate=LIVE_CID)
    vacuum(conn, 'sentinel_snapshot_bars')
    with old_snapshot(storage):
        conn.execute("DELETE FROM sentinel_snapshot_bars WHERE candidate_id=%s "
                     "AND security_id<='00040000'", (CID,))
        conn.commit()
        progress = logical_progress(conn, last_session='2026-11-06',
                                    last_security_id='00040000', quantum=5000)
        measured = MeasuredConnection(conn)
        updated, stats = retention._logical_step(measured, progress, batch_rows=5000)
        assert stats['deleted_rows'] == 5000
        assert measured.logical_plans, 'actual logical DELETE was not measured'
        (tmp_path/'logical-delete-5000-plan.json').write_text(json.dumps(measured.logical_plans, indent=2))
        scans = [node for plan in measured.logical_plans for node in plan_scans(plan)]
        candidate_index_visits = sum(node.get('Actual Rows', 0) * node.get('Actual Loops', 0)
            for plan in measured.logical_plans for node in plan_nodes(plan)
            if 'Index' in node.get('Node Type', ''))
        assert candidate_index_visits <= 5000, (
            'candidate prefix work exceeded selected TIDs', candidate_index_visits)
        summary = [{name: node.get(name) for name in (
            'Node Type', 'Index Name', 'Actual Rows', 'Actual Loops',
            'Rows Removed by Filter', 'Heap Fetches', 'Shared Hit Blocks', 'Shared Read Blocks',
        )} for node in scans]
        assert scans and all(node['Node Type'] == 'Tid Scan' for node in scans), (
            'logical DELETE revisited a candidate prefix instead of selected CTIDs', summary)
        save_step(conn, updated, stats)
        assert count_rows(conn) == 4


def test_removed_uuid_residual_has_a_work_amplification_falsifier(storage, tmp_path):
    actual = storage.conn
    class RemovedResidual:
        @property
        def autocommit(self):
            return actual.autocommit
        @autocommit.setter
        def autocommit(self, value):
            actual.autocommit = value
        def __getattr__(self, name):
            return getattr(actual, name)
        def execute(self, query, parameters=None):
            if isinstance(query, str):
                query = query.replace('WHERE candidate_id::text=%s::uuid::text AND ctid=ANY',
                                      'WHERE candidate_id=%s AND ctid=ANY')
            return actual.execute(query, parameters)
    storage.conn = RemovedResidual()
    with pytest.raises(AssertionError, match='candidate prefix work exceeded selected TIDs'):
        test_logical_delete_5000_tid_array_has_no_candidate_prefix_scan(storage, tmp_path)


def assert_logical_seek_work(storage, metrics_path=None):
    conn = storage.conn
    seed_bars(conn, total=45001)
    vacuum(conn, 'sentinel_snapshot_bars')
    with old_snapshot(storage):
        conn.execute("DELETE FROM sentinel_snapshot_bars WHERE security_id<='00040000'")
        conn.commit()
        progress = logical_progress(conn, last_session='2026-11-06',
                                    last_security_id='00040000', quantum=127)
        measured = MeasuredConnection(conn)
        removed = 0
        ceiling = math.ceil(5001 / 127) + 2
        first_work = None
        work = []
        for _ in range(ceiling):
            if progress.active is None or progress.active.phase != 'BARS':
                break
            updated, stats = retention._logical_step(measured, progress, batch_rows=127)
            assert stats['deleted_rows'] <= 127
            removed += stats['deleted_rows']
            plan = measured.seek_plans[-1]
            observed = sum(node.get('Shared Hit Blocks', 0) + node.get('Shared Read Blocks', 0)
                           for node in plan_scans(plan))
            if first_work is None:
                first_work = observed
            # The fixture's immutable key-ordered heap has a fixed index height
            # and contiguous row placement. Sixteen buffers permit leaf/page
            # boundaries; a growing dead prefix must not become a new cost term.
            assert observed <= first_work + 16, (
                'logical seek repeated its deleted prefix', observed, first_work)
            work.append(observed)
            save_step(conn, updated, stats)
            progress = retention._read_progress(conn)
        assert removed == 5001 and count_rows(conn) == 0
        assert len(work) <= ceiling
        assert sum(work) <= (first_work + 16) * ceiling
        if metrics_path is not None:
            metrics_path.write_text(json.dumps(dict(
                deleted_prefix=40000, deleted_tail=removed, batch_rows=127,
                statements=len(work), first_seek_buffers=first_work,
                cumulative_seek_buffers=sum(work), maximum_seek_buffers=max(work),
            ), indent=2))


def test_logical_seek_advances_without_repeating_dead_key_work(storage, tmp_path):
    assert_logical_seek_work(storage, tmp_path/'logical-seek-work.json')


def test_removed_logical_seek_advancement_has_a_work_falsifier(storage, monkeypatch):
    original = retention._logical_step
    def no_advancement(conn, progress, *, batch_rows):
        updated, stats = original(conn, progress, batch_rows=batch_rows)
        if (progress.active is not None and updated.active is not None
                and progress.active.phase == updated.active.phase == 'BARS'):
            cursor = updated.active.model_copy(update={
                'last_session': progress.active.last_session,
                'last_security_id': progress.active.last_security_id,
            })
            updated = updated.model_copy(update={'active': cursor})
        return updated, stats
    monkeypatch.setattr(retention, '_logical_step', no_advancement)
    with pytest.raises(AssertionError, match='logical seek repeated its deleted prefix'):
        assert_logical_seek_work(storage)


def test_unsupported_physical_tid_setting_retains_payload_and_cannot_hot_loop(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=40)
    progress = retention._initial_progress(conn)
    save_step(conn, progress, {'deleted_rows': 0})
    prior = conn.execute("SELECT current_setting('enable_tidscan')").fetchone()[0]
    conn.rollback()
    algorithm_owner(monkeypatch)
    try:
        conn.execute("SELECT set_config('enable_tidscan','off',false)")
        conn.commit()
        result = retention.maintain(conn, batch_rows=7)
        assert result['status'] == 'RETRY'
        assert result['class_errors'] == {'2': 'RetentionProgressRefused'}
        assert result['progress_made'] is False
        assert count_rows(conn) == 40
        after = retention._read_progress(conn)
        conn.rollback()
        assert after.legacy == progress.legacy
        assert conn.execute("SELECT current_setting('enable_tidscan')").fetchone() == ('off',)
        conn.rollback()
    finally:
        conn.execute("SELECT set_config('enable_tidscan',%s,false)", (prior,))
        conn.commit()


@pytest.mark.parametrize('settings', [('on', 'off', 'on', 'on'), ('off', 'on', 'on', 'on')])
def test_logical_delete_restores_actual_prior_planner_settings(storage, settings):
    conn = storage.conn
    seed_bars(conn, total=10)
    progress = logical_progress(conn, quantum=3)
    names = ('enable_seqscan', 'enable_tidscan', 'enable_indexscan', 'enable_bitmapscan')
    query = "SELECT " + ','.join("current_setting('" + name + "')" for name in names)
    prior = conn.execute(query).fetchone()
    conn.rollback()
    try:
        for name, value in zip(names, settings):
            conn.execute('SELECT set_config(%s,%s,false)', (name, value))
        conn.commit()
        _updated, stats = retention._logical_step(conn, progress, batch_rows=3)
        assert stats['deleted_rows'] == 3
        assert conn.execute(query).fetchone() == settings
        conn.rollback()
    finally:
        for name, value in zip(names, prior):
            conn.execute('SELECT set_config(%s,%s,false)', (name, value))
        conn.commit()


@pytest.mark.parametrize('disabled', ['enable_indexscan', 'enable_bitmapscan'])
def test_unsupported_metadata_planner_setting_retains_payload_and_progress(storage, monkeypatch, disabled):
    conn = storage.conn
    seed_bars(conn, total=40)
    progress = logical_progress(conn, quantum=7)
    save_step(conn, progress, {'deleted_rows': 0})
    prior = conn.execute('SELECT current_setting(%s)', (disabled,)).fetchone()[0]
    conn.rollback()
    algorithm_owner(monkeypatch)
    try:
        conn.execute('SELECT set_config(%s,%s,false)', (disabled, 'off'))
        conn.commit()
        result = retention.maintain(conn, batch_rows=7)
        assert result['status'] == 'RETRY'
        assert result['class_errors'] == {'2': 'RetentionProgressRefused'}
        assert result['progress_made'] is False
        assert count_rows(conn) == 40
        after = retention._read_progress(conn)
        conn.rollback()
        assert after.active == progress.active
        assert conn.execute('SELECT current_setting(%s)', (disabled,)).fetchone() == ('off',)
        conn.rollback()
    finally:
        conn.execute('SELECT set_config(%s,%s,false)', (disabled, prior))
        conn.commit()


def test_logical_seek_preserves_nonascii_keys_and_resets_at_benchmark_phase(storage):
    conn = storage.conn
    keys = ['z', 'A', 'Å', 'á', 'Ω', 'x😀']
    for key in keys:
        conn.execute('INSERT INTO sentinel_snapshot_bars VALUES(%s,%s,%s,%s)',
                     (CID, date(2026, 11, 6), key, 'payload'))
    conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (CID,))
    conn.execute("INSERT INTO sentinel_snapshot_benchmarks VALUES(%s,'2026-11-05','old'),"
                 "(%s,'2026-11-06','new')", (CID, CID))
    conn.commit()
    progress = logical_progress(conn, quantum=3)
    removed = 0
    for _ in range(10):
        if progress.active is None:
            break
        updated, stats = retention._logical_step(conn, progress, batch_rows=3)
        assert 0 <= stats.get('deleted_rows', 0) <= 3
        removed += stats.get('deleted_rows', 0)
        save_step(conn, updated, stats)
        progress = retention._read_progress(conn)
    assert progress.active is None, 'logical seek did not converge across both payload phases'
    assert removed == len(keys) + 2
    assert count_rows(conn) == 0
    assert count_rows(conn, 'sentinel_snapshot_benchmarks') == 0


def test_unexplained_new_retirement_restarts_shared_bootstrap(storage, monkeypatch):
    conn = storage.conn
    conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (CID,))
    conn.commit()
    completed = retention.RetentionProgress.model_validate(raw_progress(known_retirement_count=1))
    save_step(conn, completed, {'deleted_rows': 0})
    seed_bars(conn, total=1, candidate=LIVE_CID)
    algorithm_owner(monkeypatch)
    result = retention.maintain(conn, batch_rows=7)
    assert result['deleted_rows'] == 1
    progress = retention._read_progress(conn)
    conn.rollback()
    assert progress.known_retirement_count == 2
    assert count_rows(conn) == 0


def test_decreasing_retirement_count_refuses_without_erasing_progress(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=1)
    impossible = retention.RetentionProgress.model_validate(raw_progress(known_retirement_count=2))
    save_step(conn, impossible, {'deleted_rows': 0})
    algorithm_owner(monkeypatch)
    result = retention.maintain(conn, batch_rows=7)
    assert result['status'] == 'RETRY' and result['reason'] == 'RetentionProgressRefused'
    assert result['progress_made'] is False
    assert count_rows(conn) == 1
    assert retention._read_progress(conn) == impossible
    conn.rollback()


def assert_late_class_is_rolled_back(storage, monkeypatch):
    conn = storage.conn
    algorithm_owner(monkeypatch)
    def classes(connection, class_id, progress, *, batch_rows):
        if class_id in {0, 1}:
            connection.execute('INSERT INTO class_effects VALUES(%s,%s)', (class_id, 'changed'))
            if class_id == 0:
                # This is Python-side delay after successful bounded SQL, not a
                # database statement whose cancellation could enforce the guard.
                time.sleep(.55)
            return progress, retention._stats(progress_made=True)
        return progress, retention._stats()
    monkeypatch.setattr(retention, '_run_class', classes)
    result = retention.maintain(conn, batch_rows=7)
    assert result['status'] == 'RETRY', 'late class result was admitted'
    assert result['class_errors'] == {'0': 'RetentionBudgetExpired'}
    rows = conn.execute('SELECT class_id FROM class_effects ORDER BY class_id').fetchall()
    conn.rollback()
    assert rows == [(1,)], 'late class result was committed with independent progress'


def test_python_side_late_class_result_is_rejected(storage, monkeypatch):
    assert_late_class_is_rolled_back(storage, monkeypatch)


def test_removed_class_deadline_check_has_an_executed_falsifier(storage, monkeypatch):
    source = textwrap.dedent(inspect.getsource(retention._pass))
    assert source.count('work.check()') == 1
    namespace = {}
    exec(compile(source.replace('work.check()', 'None'), 'removed-class-deadline', 'exec'),
         retention.__dict__, namespace)
    monkeypatch.setattr(retention, '_pass', namespace['_pass'])
    with pytest.raises(AssertionError, match='late class result was admitted'):
        assert_late_class_is_rolled_back(storage, monkeypatch)


def assert_late_publication_is_rolled_back(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=40)
    progress = retention._initial_progress(conn)
    save_step(conn, progress, {'deleted_rows': 0})
    original = saved_diagnostic(conn)
    algorithm_owner(monkeypatch)
    monkeypatch.setattr(retention, 'PASS_SECONDS', .8)
    publication = retention._write_result
    observed = []
    def late_write(connection, result, updated):
        publication(connection, result, updated)
        observed.append(True)
        time.sleep(.85)
    monkeypatch.setattr(retention, '_write_result', late_write)
    result = retention.maintain(conn, batch_rows=7)
    assert observed == [True], 'test never reached progress publication'
    assert result['status'] == 'RETRY', 'late progress publication was committed'
    assert result['reason'] == 'RetentionBudgetExpired'
    assert count_rows(conn) == 40
    assert saved_diagnostic(conn)['progress'] == original['progress']


def test_late_progress_publication_rolls_back_outer_mutation(storage, monkeypatch):
    assert_late_publication_is_rolled_back(storage, monkeypatch)


def test_removed_publication_deadline_check_has_an_executed_falsifier(storage, monkeypatch):
    source = textwrap.dedent(inspect.getsource(retention._pass))
    assert source.count('publication.check()') == 1
    namespace = {}
    exec(compile(source.replace('publication.check()', 'None'), 'removed-publication-deadline', 'exec'),
         retention.__dict__, namespace)
    monkeypatch.setattr(retention, '_pass', namespace['_pass'])
    with pytest.raises(AssertionError, match='late progress publication was committed'):
        assert_late_publication_is_rolled_back(storage, monkeypatch)


def add_category_tables(storage):
    """Minimal real SQL inputs for checkpoint-gate ordering, not pin authority."""
    conn = storage.conn
    definitions = {
        'sentinel_snapshot_jobs': 'job_id text,candidate_id uuid,state text,reason text,deadline timestamptz,owner text',
        'sentinel_price_candidates': 'candidate_id uuid PRIMARY KEY,reference_sha256 text,source_evidence_sha256 text',
        'sentinel_snapshot_evidence': 'evidence_sha256 text PRIMARY KEY,payload jsonb,canonical_payload text',
        'sentinel_snapshot_validations': 'validation_sha256 text',
        'sentinel_operational_snapshot_validations': 'validation_sha256 text',
        'sentinel_snapshot_comparisons': 'candidate_id uuid,version integer,job_id text,producer_sha256 text',
        'sentinel_operational_snapshots': 'candidate_id uuid,publication_version integer,job_id text',
        'sentinel_corpus_publications': 'version integer',
        'sentinel_action_coverage': 'publication_version integer',
        'sentinel_sep_staging': 'run_id text',
        'sentinel_snapshot_workers': 'owner text,job_id text',
        'sentinel_acquisition_parts': 'part_id text PRIMARY KEY,manifest jsonb,created_at timestamptz DEFAULT clock_timestamp()',
        'sentinel_acquisition_prices': 'part_id text,session date,security_id text,payload text',
        'sentinel_normalized_blocks': 'block_sha256 text PRIMARY KEY,canonical_payload text',
        'sentinel_candidate_blocks': 'candidate_id uuid,block_sha256 text',
        'sentinel_processed_sessions': 'cursor_name text PRIMARY KEY,session date,state jsonb',
    }
    for name, fields in definitions.items():
        conn.execute(sql.SQL('CREATE TABLE {} ({})').format(sql.Identifier(name), sql.SQL(fields)))
    conn.execute(sql.SQL('CREATE FUNCTION {}.sentinel_snapshot_pins(target uuid) RETURNS text[] '
                         "LANGUAGE SQL STABLE AS $$ SELECT ARRAY[]::text[] $$").format(sql.Identifier(storage.schema)))
    conn.execute(sql.SQL('CREATE FUNCTION {}.sentinel_acquisition_part_pinned(target text) RETURNS boolean '
                         'LANGUAGE SQL STABLE AS $$ SELECT FALSE $$').format(sql.Identifier(storage.schema)))
    conn.commit()


def seed_category(conn, class_id):
    job = '00000000-0000-0000-0000-000000000010'
    if class_id == 0:
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES(%s,NULL,'ACQUIRING','WAIT',"
                     "clock_timestamp()-interval '1 second','new-owner')", (job,))
    elif class_id == 1:
        seed_bars(conn, total=1, retired=False)
        conn.execute('INSERT INTO sentinel_price_candidates VALUES(%s,%s,%s)', (CID, 'e'*64, 'e'*64))
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES(%s,%s,'PUBLISHED','DONE',NULL,'owner')", (job, CID))
    elif class_id == 2:
        seed_bars(conn, total=1)
    elif class_id == 3:
        conn.execute('INSERT INTO sentinel_price_candidates VALUES(%s,%s,%s)', (CID, 'e'*64, 'e'*64))
        conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (CID,))
        conn.execute("INSERT INTO sentinel_snapshot_evidence VALUES(%s,'{\"preserved\":true}','preserved')", ('e'*64,))
    elif class_id == 4:
        conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES(%s,NULL,'PUBLISHED','DONE',NULL,'new-owner')", (job,))
        conn.execute("INSERT INTO sentinel_snapshot_workers VALUES('old-owner',%s)", (job,))
        conn.execute("INSERT INTO sentinel_sep_staging VALUES('old-owner')")
    elif class_id == 5:
        conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES(%s,'{}')", ('a'*64,))
        conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-11-06','security','preserved')", ('a'*64,))
    elif class_id == 6:
        conn.execute("INSERT INTO sentinel_normalized_blocks VALUES(%s,'preserved')", ('b'*64,))
    else:
        raise AssertionError(class_id)
    conn.commit()


@pytest.mark.parametrize('class_id', range(7))
@pytest.mark.parametrize('checkpoint_kind', ['origin', 'daily'])
def test_malformed_checkpoint_blocks_each_actual_mutation_category(
        storage, monkeypatch, class_id, checkpoint_kind):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    from sentinel.feed import normalized_layout
    conn = storage.conn
    add_category_tables(storage)
    seed_category(conn, class_id)
    cursor = rolling_checkpoint.CURSOR if checkpoint_kind == 'origin' else rolling_daily_checkpoint.CURSOR
    conn.execute("INSERT INTO sentinel_processed_sessions VALUES(%s,'2026-11-06','{\"bad\":true}')", (cursor,))
    conn.commit()
    watched = ('sentinel_snapshot_jobs', 'sentinel_snapshot_retirements', 'sentinel_snapshot_bars',
               'sentinel_sep_staging', 'sentinel_acquisition_parts', 'sentinel_acquisition_prices')
    before = {name: count_rows(conn, name) for name in watched}
    real_class = retention._run_class
    algorithm_owner(monkeypatch)
    # Use the real handler for exactly this positive category. Other categories
    # are outside this ordering test and do not require synthetic negative tables.
    def selected(connection, selected_id, progress, *, batch_rows):
        if selected_id == class_id:
            return real_class(connection, selected_id, progress, batch_rows=batch_rows)
        return progress, retention._stats()
    monkeypatch.setattr(retention, '_run_class', selected)
    monkeypatch.setattr(normalized_layout, 'available', lambda _: True)
    monkeypatch.setattr(normalized_layout, 'release_retired', lambda _: pytest.fail('normalized mutation escaped checkpoint refusal'))
    monkeypatch.setattr(retention.rolling_jobs, 'expire', lambda *_: pytest.fail('job mutation escaped checkpoint refusal'))
    calls = []
    authenticate = retention._authenticate_checkpoints
    def observed(connection):
        calls.append(True)
        return authenticate(connection)
    monkeypatch.setattr(retention, '_authenticate_checkpoints', observed)
    result = retention.maintain(conn, batch_rows=7)
    assert calls == [True], 'positive mutation skipped or repeated current checkpoint authentication'
    assert result['status'] == 'RETRY' and str(class_id) in result['class_errors']
    assert {name: count_rows(conn, name) for name in watched} == before
    assert conn.execute('SELECT payload,canonical_payload FROM sentinel_snapshot_evidence').fetchall() in (
        [], [({'preserved': True}, 'preserved')])
    assert conn.execute('SELECT canonical_payload FROM sentinel_normalized_blocks').fetchall() in (
        [], [('preserved',)])
    conn.rollback()


def assert_empty_extents_do_not_authenticate(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=40000)
    with old_snapshot(storage):
        conn.execute('DELETE FROM sentinel_snapshot_bars')
        conn.commit()
        algorithm_owner(monkeypatch)
        calls = []
        monkeypatch.setattr(retention, '_authenticate_checkpoints', lambda _: calls.append(True))
        blocks = relation_blocks(conn)
        assert blocks > 64
        result = retention.maintain(conn, batch_rows=127)
        assert result['status'] == 'COMPLETE'
        assert result['traversed_blocks'] == blocks
        assert result['deleted_rows'] == 0
        after = retention._read_progress(conn)
        conn.rollback()
        assert after.legacy is None
        assert calls == [], 'empty extents re-authenticated the unchanged checkpoint'


def test_multiple_empty_extents_advance_without_checkpoint_authentication(storage, monkeypatch):
    assert_empty_extents_do_not_authenticate(storage, monkeypatch)


def test_public_maintain_stops_at_finite_64_extent_cap_without_authentication(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=20000)
    with old_snapshot(storage):
        conn.execute('DELETE FROM sentinel_snapshot_bars')
        conn.commit()
        assert relation_blocks(conn) > 64
        progress = retention._initial_progress(conn)
        progress = progress.model_copy(update={
            'legacy': progress.legacy.model_copy(update={'page_quantum': 1})})
        save_step(conn, progress, {'deleted_rows': 0})
        algorithm_owner(monkeypatch)
        calls = []
        monkeypatch.setattr(retention, '_authenticate_checkpoints', lambda _: calls.append(True))
        result = retention.maintain(conn, batch_rows=127)
        assert result['status'] == 'COMPLETE'
        assert result['traversed_blocks'] == 64 and result['deleted_rows'] == 0
        after = retention._read_progress(conn)
        conn.rollback()
        assert after.legacy.position_block == 64 and result['more_work'] is True
        assert calls == []


def test_short_public_class_deadline_checkpoints_prior_empty_extent(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=20000)
    with old_snapshot(storage):
        conn.execute('DELETE FROM sentinel_snapshot_bars')
        conn.commit()
        progress = retention._initial_progress(conn)
        save_step(conn, progress, {'deleted_rows': 0})
        algorithm_owner(monkeypatch)
        monkeypatch.setattr(retention, 'CLASS_SECONDS', .15)
        monkeypatch.setattr(retention, 'PASS_SECONDS', .5)
        monkeypatch.setattr(retention, 'CHECKPOINT_RESERVE', .05)
        calls, auth = [], []
        original = retention._bootstrap_step
        def delayed_extent(connection, before, *, batch_rows, **kwargs):
            calls.append(before.legacy.position_block)
            if len(calls) == 2:
                connection.execute('SELECT pg_sleep(.3)')
            return original(connection, before, batch_rows=batch_rows, **kwargs)
        monkeypatch.setattr(retention, '_bootstrap_step', delayed_extent)
        monkeypatch.setattr(retention, '_authenticate_checkpoints', lambda _: auth.append(True))
        started = time.monotonic()
        result = retention.maintain(conn, batch_rows=127)
        assert time.monotonic() - started < 2
        assert len(calls) == 2 and calls[0] == 0 and calls[1] > 0
        assert result['status'] == 'RETRY'
        assert result['class_errors'] == {'2': 'QueryCanceled'}
        assert result['progress_made'] is True and result['traversed_blocks'] == calls[1]
        after = retention._read_progress(conn)
        conn.rollback()
        assert after.legacy.position_block == calls[1]
        assert count_rows(conn) == 0 and auth == []


def test_public_multi_extent_payload_deletes_share_one_caller_row_cap(storage, monkeypatch):
    conn = storage.conn
    seed_bars(conn, total=20000)
    with old_snapshot(storage):
        conn.execute('DELETE FROM sentinel_snapshot_bars WHERE security_id::integer%100<>0')
        conn.commit()
        assert count_rows(conn) == 200 and relation_blocks(conn) > 128
        algorithm_owner(monkeypatch)
        observed = []
        original = retention._bootstrap_step
        def tracked_extent(connection, before, *, batch_rows, **kwargs):
            after, stats = original(connection, before, batch_rows=batch_rows, **kwargs)
            observed.append((batch_rows, stats['deleted_rows']))
            return after, stats
        monkeypatch.setattr(retention, '_bootstrap_step', tracked_extent)
        result = retention.maintain(conn, batch_rows=127)
        assert result['status'] == 'COMPLETE' and result['deleted_rows'] == 127
        assert len(observed) > 1
        assert sum(deleted for _, deleted in observed) == 127
        remaining = 127
        for admitted, deleted in observed:
            assert admitted == remaining and deleted <= admitted
            remaining -= deleted
        assert count_rows(conn) == 73


def test_eager_empty_extent_auth_has_an_executed_call_count_falsifier(storage, monkeypatch):
    original = retention._bootstrap_step
    def eager(connection, progress, *, batch_rows, **kwargs):
        retention._authorize(connection)
        return original(connection, progress, batch_rows=batch_rows, **kwargs)
    monkeypatch.setattr(retention, '_bootstrap_step', eager)
    with pytest.raises(AssertionError, match='empty extents re-authenticated'):
        assert_empty_extents_do_not_authenticate(storage, monkeypatch)


def test_authentication_is_once_per_pass_with_fresh_mutation_slice_and_no_cross_pass_cache(storage, monkeypatch):
    conn = storage.conn
    algorithm_owner(monkeypatch)
    calls = []
    def authenticate(_):
        calls.append(True)
        time.sleep(.65)  # Larger than the500 ms mutation slice; below the5 s pass.
    monkeypatch.setattr(retention, '_authenticate_checkpoints', authenticate)
    def positive(connection, class_id, progress, *, batch_rows):
        if class_id in {0, 2, 4}:
            retention._authorize(connection)
            if class_id == 0:
                connection.execute('SELECT pg_sleep(.3)')
            connection.execute('INSERT INTO class_effects VALUES(%s,%s)', (class_id, 'authorized'))
            return progress, retention._stats(progress_made=True)
        return progress, retention._stats()
    monkeypatch.setattr(retention, '_run_class', positive)
    for expected in (1, 2):
        result = retention.maintain(conn, batch_rows=7)
        assert result['status'] == 'COMPLETE' and not result['class_errors']
        assert len(calls) == expected
    rows = conn.execute('SELECT class_id FROM class_effects ORDER BY class_id').fetchall()
    conn.rollback()
    assert rows == [(0,), (0,), (2,), (2,), (4,), (4,)]


def test_failed_same_pass_authentication_is_not_retried_for_other_positive_classes(storage, monkeypatch):
    conn = storage.conn
    algorithm_owner(monkeypatch)
    calls = []
    def authenticate(_):
        calls.append(True)
        raise ValueError('private malformed checkpoint')
    monkeypatch.setattr(retention, '_authenticate_checkpoints', authenticate)
    def positive(connection, class_id, progress, *, batch_rows):
        if class_id in {0, 2, 4}:
            retention._authorize(connection)
            connection.execute('INSERT INTO class_effects VALUES(%s,%s)', (class_id, 'must not occur'))
        return progress, retention._stats()
    monkeypatch.setattr(retention, '_run_class', positive)
    result = retention.maintain(conn, batch_rows=7)
    assert calls == [True]
    assert set(result['class_errors']) == {'0', '2', '4'}
    assert conn.execute('SELECT count(*) FROM class_effects').fetchone() == (0,)
    conn.rollback()


def install_exact_delete_guard(conn):
    from sentinel.feed.retention_schema import DDL
    for name in ('sentinel_retention_locks', 'sentinel_snapshot_delete_guard'):
        statements = [value for value in DDL if value.startswith('CREATE OR REPLACE FUNCTION ' + name + '(')]
        assert len(statements) == 1
        conn.execute(statements[0])
    conn.execute('CREATE TRIGGER snapshot_delete_guard AFTER DELETE ON sentinel_snapshot_bars '
                 'REFERENCING OLD TABLE AS retired_payload FOR EACH STATEMENT '
                 'EXECUTE FUNCTION sentinel_snapshot_delete_guard()')
    conn.commit()


def writer_locks(conn):
    from sentinel.execution.journal import WRITER_LOCK_KEY
    from sentinel.feed.publication import CORPUS_LOCK_KEY
    conn.execute('SELECT pg_advisory_lock(%s),pg_advisory_lock(%s)',
                 (WRITER_LOCK_KEY, CORPUS_LOCK_KEY))
    conn.commit()


class PrototypePlannerPort:
    """Private A/B port only; production source and frozen trigger stay unchanged."""
    def __init__(self, conn, mode):
        self.conn, self.mode = conn, mode
    def __getattr__(self, name):
        return getattr(self.conn, name)
    def execute(self, query, parameters=None):
        if isinstance(query, str):
            if self.mode == 'residual':
                for name in ('enable_indexscan', 'enable_bitmapscan'):
                    query = query.replace("set_config('" + name + "','off',true)",
                                          "set_config('" + name + "','on',true)")
                query = query.replace('WHERE candidate_id=%s AND ctid=ANY',
                                      'WHERE candidate_id::text=%s::uuid::text AND ctid=ANY')
            elif self.mode == 'four_guc':
                query = query.replace('WHERE candidate_id::text=%s::uuid::text AND ctid=ANY',
                                      'WHERE candidate_id=%s AND ctid=ANY')
                if query.startswith('WITH prior AS MATERIALIZED'):
                    query = query.replace(' FROM prior',
                        ",set_config('enable_indexscan','off',true),"
                        "set_config('enable_bitmapscan','off',true) FROM prior")
        return self.conn.execute(query, parameters)


def observe_guard_variant(storage, mode, *, bounded=False):
    conn = storage.peer()
    notices = []
    conn.add_notice_handler(lambda value: notices.append(value.message_primary))
    try:
        writer_locks(conn)
        conn.execute("LOAD 'auto_explain'")
        for setting, value in (
            ('log_min_duration', '0'), ('log_analyze', 'on'), ('log_buffers', 'on'),
            ('log_timing', 'off'), ('log_nested_statements', 'on'),
            ('log_format', 'json'), ('log_level', 'notice'),
        ):
            conn.execute(sql.SQL('SET auto_explain.{}={}').format(
                sql.Identifier(setting), sql.Literal(value)))
        conn.execute("SET LOCAL statement_timeout='5s'")
        progress = logical_progress(conn, last_session='2026-11-06',
                                    last_security_id='00040000', quantum=5000)
        port = PrototypePlannerPort(conn, mode)
        if bounded:
            guard = retention._Authorization(port, time.monotonic()+retention.PASS_SECONDS)
            port = retention._Budget(port, time.monotonic()+retention.CLASS_SECONDS,
                                     ceiling_ms=500, authorization=guard)
        started = time.monotonic()
        _updated, stats = retention._logical_step(port, progress, batch_rows=5000)
        if bounded:
            port.check()
        elapsed = time.monotonic()-started
        assert stats['deleted_rows'] == 5000
        conn.rollback()
        assert count_rows(conn) == 5002, 'A/B evidence escaped its rollback'
        plans = []
        for message in notices:
            if 'plan:' in message and '{' in message:
                plans.append(json.JSONDecoder().raw_decode(message[message.index('{'):])[0])
        metadata = [value for value in plans if 'retired_payload' in value.get('Query Text', '')]
        targets = [value for value in plans
                   if value.get('Query Text', '').startswith('DELETE FROM sentinel_snapshot_bars')]
        assert metadata and targets, 'nested exact-trigger or outer DELETE plan was not captured'
        jit = sum(value.get('JIT', {}).get('Functions', 0) for value in metadata)
        nodes = [node for value in metadata for node in plan_nodes(value)]
        indexes = [node.get('Index Name') for node in nodes if 'Index' in node.get('Node Type', '')]
        target_nodes = [node for value in targets for node in plan_scans(value)]
        summary = dict(mode=mode, deleted_rows=stats['deleted_rows'], elapsed_seconds=elapsed,
                       metadata_jit_functions=jit, metadata_indexes=indexes,
                       metadata_maximum_cost=max(value['Plan']['Total Cost'] for value in metadata),
                       target_scans=[{name: node.get(name) for name in (
                           'Node Type', 'Actual Rows', 'Actual Loops', 'Shared Hit Blocks',
                           'Shared Read Blocks')} for node in target_nodes])
        return summary, plans
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def guarded_depleted_fixture(storage):
    conn = storage.conn
    seed_bars(conn, total=45001)
    nil = '00000000-0000-0000-0000-000000000000'
    seed_bars(conn, total=1, candidate=nil)
    install_exact_delete_guard(conn)
    vacuum(conn, 'sentinel_snapshot_bars')
    with old_snapshot(storage):
        writer_locks(conn)
        conn.execute("DELETE FROM sentinel_snapshot_bars WHERE candidate_id=%s "
                     "AND security_id<='00040000'", (CID,))
        conn.commit()
        conn.execute('SELECT pg_advisory_unlock_all()')
        conn.commit()
        yield


def test_private_exact_guard_spi_planner_ab_proof(storage, tmp_path):
    with guarded_depleted_fixture(storage):
        unsafe, unsafe_plans = observe_guard_variant(storage, 'four_guc')
        proposed, proposed_plans = observe_guard_variant(storage, 'residual')
    (tmp_path/'exact-guard-spi-ab.json').write_text(json.dumps(dict(
        four_guc=unsafe, proposed_residual=proposed,
        four_guc_plans=unsafe_plans, proposed_residual_plans=proposed_plans,
    ), indent=2))
    assert unsafe['metadata_maximum_cost'] >= 1e9
    assert unsafe['metadata_jit_functions'] > 0
    assert proposed['metadata_jit_functions'] == 0
    assert 'sentinel_snapshot_retirements_pkey' in proposed['metadata_indexes']
    assert all(node['Node Type'] == 'Tid Scan' and node['Actual Rows'] == 5000
               for node in proposed['target_scans'])


def test_actual_guard_keeps_metadata_indexing_within_fresh_mutation_slice(storage, tmp_path):
    with guarded_depleted_fixture(storage):
        actual, plans = observe_guard_variant(storage, 'actual', bounded=True)
    (tmp_path/'actual-guard-spi.json').write_text(json.dumps(dict(summary=actual, plans=plans), indent=2))
    assert actual['deleted_rows'] == 5000
    assert actual['metadata_jit_functions'] == 0
    assert actual['metadata_maximum_cost'] < 1e9
    assert 'sentinel_snapshot_retirements_pkey' in actual['metadata_indexes']
    assert all(node['Node Type'] == 'Tid Scan' and node['Actual Rows'] == 5000
               for node in actual['target_scans'])


def test_proposed_uuid_residual_preserves_nil_null_and_foreign_tid_identity(storage):
    conn = storage.conn
    nil = '00000000-0000-0000-0000-000000000000'
    seed_bars(conn, total=3)
    seed_bars(conn, total=1, candidate=nil)
    seed_bars(conn, total=1, candidate=LIVE_CID, retired=False)
    install_exact_delete_guard(conn)
    writer_locks(conn)
    rows = conn.execute('SELECT candidate_id::text,ctid::text FROM sentinel_snapshot_bars').fetchall()
    tids = dict(rows)
    query = ('DELETE FROM sentinel_snapshot_bars WHERE candidate_id::text=%s::uuid::text '
             'AND ctid=ANY(%s::tid[])')
    for target, selected in ((nil, CID), (None, CID), (CID, nil), (CID, LIVE_CID)):
        assert conn.execute(query, (target, [tids[selected]])).rowcount == 0
    progress = logical_progress(conn, quantum=5)
    progress = progress.model_copy(update={'active': progress.active.model_copy(update={'candidate_id': nil})})
    _updated, stats = retention._logical_step(PrototypePlannerPort(conn, 'residual'),
                                             progress, batch_rows=5)
    assert stats['deleted_rows'] == 1
    counts = dict(conn.execute('SELECT candidate_id::text,count(*) FROM sentinel_snapshot_bars '
                               'GROUP BY candidate_id').fetchall())
    assert counts == {CID: 3, LIVE_CID: 1}
    conn.rollback()
    assert count_rows(conn) == 5


@pytest.mark.parametrize('made_progress', [False, True])
def test_idle_loop_requires_real_progress_not_only_possible_work(monkeypatch, made_progress):
    class Connection:
        def execute(self, *_args):
            return self
        def fetchone(self):
            return (1,)
        def rollback(self):
            pass
        def close(self):
            self.closed = True
    connection = Connection()
    monkeypatch.setattr(retention.store, 'connect', lambda *_a, **_k: connection)
    monkeypatch.setattr(retention, 'maintain', lambda _: {
        'status': 'COMPLETE', 'more_work': True, 'progress_made': made_progress,
    })
    assert retention.idle_pass('private-unit-placeholder') is made_progress
    assert connection.closed
