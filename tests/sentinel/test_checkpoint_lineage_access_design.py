"""DEV access-path experiment; synthetic isolated PG16, not release qualification."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import statistics
from threading import Thread
import time
from types import SimpleNamespace

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from tests.sentinel.test_supervisor_dependency_bounds import conn  # noqa: F401
from tests.support.postgres import _EphemeralPostgres

TABLE = 'lineage_access_design'
INDEX_A = 'lineage_design_complete_idx'
INDEX_B = 'lineage_design_json_idx'
MAX_BYTES = 256*1024*1024
NAMES = "(cursor_name LIKE 'shadow-%' OR cursor_name LIKE 'rolling-%' OR cursor_name LIKE 'catchup%')"
KEYS_OR = "(state ? 'wealth_core' OR state ? 'strategy_identity')"
KEYS_ANY = "state ?| ARRAY['wealth_core','strategy_identity']"
STATIC_A = f'CASE WHEN {NAMES} THEN TRUE ELSE {KEYS_OR} END'
STATIC_B = f'CASE WHEN {NAMES} THEN FALSE ELSE {KEYS_ANY} END'
EXCLUDED = ('cursor_name=ANY($1) OR cursor_name LIKE $2 '
            'OR cursor_name LIKE $3 OR cursor_name LIKE $4')
ELIGIBLE = f'(CASE WHEN {EXCLUDED} THEN FALSE ELSE TRUE END)'


# Independent pre-fix control, authenticated against both captured PG statements.
ORIGINAL_SOURCE = (
    'SELECT cursor_name FROM sentinel_processed_sessions WHERE CASE WHEN '
    'cursor_name=ANY($1) OR cursor_name LIKE $2 OR cursor_name LIKE $3 OR cursor_name LIKE $4 THEN FALSE ELSE '
    "(cursor_name LIKE 'shadow-%' OR cursor_name LIKE 'rolling-%' OR cursor_name LIKE 'catchup%'"
    " OR state ? 'wealth_core' OR state ? 'strategy_identity') END LIMIT 1")
assert hashlib.sha256(ORIGINAL_SOURCE.encode()).hexdigest() == '251c144d218a3280db4150a063c7ba6dda3ccd37be5755f2ad066d581e1f1e5e'
ORIGINAL = ORIGINAL_SOURCE.replace('sentinel_processed_sessions', TABLE)
QUERY_A = f'SELECT cursor_name FROM {TABLE} WHERE ({STATIC_A}) AND {ELIGIBLE} LIMIT 1'
NAME_BRANCH = f'SELECT cursor_name FROM {TABLE} WHERE {NAMES} AND {ELIGIBLE}'
JSON_BRANCH = f'SELECT cursor_name FROM {TABLE} WHERE ({STATIC_B}) AND {ELIGIBLE}'
QUERY_B = f'SELECT cursor_name FROM (({NAME_BRANCH} LIMIT 1) UNION ALL ({JSON_BRANCH} LIMIT 1)) suspects LIMIT 1'
QUERY_ORDERED = f'SELECT cursor_name FROM (({NAME_BRANCH} LIMIT 1) UNION ALL ({JSON_BRANCH} ORDER BY cursor_name LIMIT 1)) suspects LIMIT 1'
QUERIES = {'original':ORIGINAL, 'A':QUERY_A, 'B':QUERY_B, 'ordered':QUERY_ORDERED}


def test_production_query_and_predicate_match_executed_design():
    from sentinel import checkpoint_lineage_access as production
    assert production.NAME_PREDICATE == NAMES
    assert production.JSON_PREDICATE == STATIC_B
    normalized = production.QUERY.replace('%%','%')
    for index_, key in enumerate(('allowed_names','session_pattern','input_pattern','authority_pattern'),1):
        normalized = normalized.replace('%('+key+')s','$'+str(index_))
    assert normalized.replace('sentinel_processed_sessions',TABLE) == QUERY_ORDERED
    parts = production.ORIGINAL_QUERY.replace('%%','%').split('%s')
    original = parts[0]
    for index_, rest in enumerate(parts[1:],1):
        original += '$'+str(index_)+rest
    assert original == ORIGINAL_SOURCE
    assert hashlib.sha256(original.encode()).hexdigest() == '251c144d218a3280db4150a063c7ba6dda3ccd37be5755f2ad066d581e1f1e5e'
    assert production.DDL[0] == (f'CREATE INDEX {production.INDEX} ON '
        f'sentinel_processed_sessions(cursor_name) WHERE ({STATIC_B})')


@pytest.fixture(scope='module')
def pg():
    # Only the task-owned network-none Unix-socket DEV runner may select this.
    # Runtime/test DSNs and production environment variables are never read.
    selected = os.environ.get('LINEAGE_DESIGN_ISOLATED_PG16', '')
    if selected:
        assert selected == 'postgresql://postgres@%2Flineage-pg/postgres'
        yield SimpleNamespace(sync_dsn=selected)
        return
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def parameters(observation='primary'):
    return (['rolling-cold-start:v1','rolling-daily-checkpoint:v1',
             f'shadow-observation:v1:{observation}:genesis'],
            f'shadow-observation:v1:{observation}:session:%',
            f'rolling-daily-input:v1:{observation}:%',
            f'shadow-rolling-runtime:v1:{observation}:%')


def render(conn, statement, values=None):
    result = statement
    for index, value in reversed(list(enumerate(values or parameters(), 1))):
        result = result.replace('$'+str(index), sql.Literal(value).as_string(conn))
    return result


def choose_collation(conn):
    # Match the actual database default; the cached deployment PG16 image uses
    # en_US.utf8. Do not substitute ICU or a binary collation to favor a plan.
    return 'default'


def table(conn):
    version = int(conn.execute('SHOW server_version_num').fetchone()[0])
    assert version >= 160000
    expected_major = os.environ.get('LINEAGE_DESIGN_EXPECTED_MAJOR','')
    assert expected_major in {'','16'}
    if os.environ.get('LINEAGE_DESIGN_ISOLATED_PG16') or expected_major:
        assert 160000 <= version < 170000
    conn.execute("SET statement_timeout='3000ms'")
    conn.execute("SET lock_timeout='500ms'")
    collation = choose_collation(conn)
    conn.execute(sql.SQL('CREATE TABLE {} (cursor_name TEXT COLLATE {} PRIMARY KEY, state JSONB, '
        'heartbeat BIGINT NOT NULL DEFAULT 0)').format(
        sql.Identifier(TABLE), sql.Identifier(collation)))
    conn.commit()
    return collation


def insert(conn, name, value):
    conn.execute(f'INSERT INTO {TABLE}(cursor_name,state) VALUES (%s,%s)',
                 (name, None if value is SQL_NULL else Jsonb(value)))


def index(conn, variant):
    for name in (INDEX_A, INDEX_B):
        conn.execute(sql.SQL('DROP INDEX IF EXISTS {}').format(sql.Identifier(name)))
    conn.commit()
    if variant == 'original':
        return {'build_ms':0, 'index_bytes':0}
    name, predicate = (INDEX_A,STATIC_A) if variant == 'A' else (INDEX_B,STATIC_B)
    started = time.perf_counter()
    conn.execute(f'CREATE INDEX {name} ON {TABLE}(cursor_name) WHERE ({predicate})')
    conn.commit()
    return {'build_ms':round((time.perf_counter()-started)*1000,3),
            'index_bytes':conn.execute('SELECT pg_relation_size(%s::regclass)', (name,)).fetchone()[0]}


SQL_NULL = object()


def test_complete_boolean_matrix_and_json_any_equivalence(conn):
    table(conn)
    values = [SQL_NULL, None, False, True, 0, 1, '', 'wealth_core', 'strategy_identity',
        {}, {'wealth_core':None}, {'wealth_core':False}, {'strategy_identity':False},
        {'nested':{'wealth_core':True}}, [], ['wealth_core'], ['strategy_identity'],
        [{'wealth_core':True}], ['unrelated'], [None,False,0,'wealth_core']]
    old = ORIGINAL.split(' WHERE ',1)[1].rsplit(' LIMIT 1',1)[0]
    checked = 0
    for observation in ('primary','a_b','a%b','a\\b'):
        params = parameters(observation)
        names = [*params[0],params[1][:-1]+'2026-11-05',params[2][:-1]+'2026-11-05',
            params[3][:-1]+'2026-11-05','shadow-foreign','rolling-foreign','catchup',
            'catchup-other','shadow','rolling','unknown-paper','ordinary',
            'shadow-observation:v1:a0b:session:2026-11-05',
            'rolling-daily-input:v1:azzzb:2026-11-05']
        for value in values:
            conn.execute(f'TRUNCATE {TABLE}')
            for name in set(names): insert(conn,name,value)
            expression = (f'SELECT cursor_name,({old}) AS old, '
                f'(({STATIC_A}) AND {ELIGIBLE}) AS a, '
                f'(({NAMES} AND {ELIGIBLE}) OR (({STATIC_B}) AND {ELIGIBLE})) AS b, '
                f'({KEYS_OR}) AS old_keys,({KEYS_ANY}) AS any_keys FROM {TABLE}')
            rows = conn.execute(render(conn,expression,params)).fetchall()
            assert all(before is a and before is b and keys is any_keys
                       for _,before,a,b,keys,any_keys in rows)
            expected = {name for name,before,*_ in rows if before is True}
            actual_a = conn.execute(render(conn,QUERY_A.removesuffix(' LIMIT 1'),params)).fetchall()
            all_b = f'SELECT cursor_name FROM (({NAME_BRANCH}) UNION ALL ({JSON_BRANCH})) suspects'
            actual_b = conn.execute(render(conn,all_b,params)).fetchall()
            assert {row[0] for row in actual_a} == expected
            assert {row[0] for row in actual_b} == expected and len(actual_b) == len(expected)
            # Ordering may choose another witness; existence and eligibility
            # remain the same as the independently recorded original query.
            for variant in ('original','B','ordered'):
                witness = conn.execute(render(conn,QUERIES[variant],params)).fetchone()
                assert bool(witness) == bool(expected), variant
                assert witness is None or witness[0] in expected, variant
            checked += len(rows)
    conn.rollback()
    print(json.dumps({'DEV':'lineage-truth-matrix','boolean_rows':checked,
        'sql_null_distinct':True,'json_any_matches_old_or':True,'like_contexts':4,
        'server_version':conn.execute('SHOW server_version').fetchone()[0]}),flush=True)


@pytest.mark.parametrize('variant', ['A','B','ordered'])
def test_membership_insert_update_rollback_and_guard_falsifiers(conn, variant):
    table(conn); index(conn,variant)
    params = parameters()
    with psycopg.connect(conn.info.dsn,autocommit=True) as other:
        assert other.execute(render(other,QUERIES[variant],params)).fetchone() is None
        insert(conn,'unknown-paper',{'wealth_core':False})
        assert conn.execute(render(conn,QUERIES[variant],params)).fetchone() == ('unknown-paper',)
        assert other.execute(render(other,QUERIES[variant],params)).fetchone() is None
        conn.rollback()
        assert other.execute(render(other,QUERIES[variant],params)).fetchone() is None
        insert(conn,'unknown-paper',{});conn.commit()
        conn.execute(f'UPDATE {TABLE} SET state=%s WHERE cursor_name=%s',
                     (Jsonb({'strategy_identity':None}),'unknown-paper'))
        assert conn.execute(render(conn,QUERIES[variant],params)).fetchone() == ('unknown-paper',)
        assert other.execute(render(other,QUERIES[variant],params)).fetchone() is None
        conn.commit()
        assert other.execute(render(other,QUERIES[variant],params)).fetchone() == ('unknown-paper',)
        def rejects(statement):
            assert conn.execute(render(conn,statement,params)).fetchone() is not None, 'foreign JSON lineage admitted'
        rejects(QUERIES[variant])
        with pytest.raises(AssertionError,match='foreign JSON lineage admitted'):
            rejects(NAME_BRANCH+' LIMIT 1')  # Executed removal of the JSON guard.
        conn.execute(f'UPDATE {TABLE} SET state=%s WHERE cursor_name=%s',(Jsonb({}),'unknown-paper'))
        insert(conn,params[0][0],{'wealth_core':False})
        assert conn.execute(render(conn,QUERIES[variant],params)).fetchone() is None
        with pytest.raises(AssertionError,match='current lineage spuriously refused'):
            assert conn.execute(f'SELECT cursor_name FROM {TABLE} WHERE ({STATIC_A}) LIMIT 1').fetchone() is None, 'current lineage spuriously refused'
        conn.rollback()


@pytest.mark.parametrize('variant', ['B','ordered'])
def test_union_one_statement_snapshot_survives_writer_branch_movement(conn, variant):
    table(conn); index(conn,variant)
    insert(conn,'ordinary-moving',{'wealth_core':False});conn.commit()
    with psycopg.connect(conn.info.dsn,autocommit=True) as other:
        reader_pid = other.execute('SELECT pg_backend_pid()').fetchone()[0]
        conn.execute('SELECT pg_advisory_lock(91827461)');conn.commit()
        statement = ('WITH gate AS MATERIALIZED(SELECT pg_advisory_xact_lock(91827461)) '
            'SELECT hit.cursor_name FROM gate CROSS JOIN LATERAL ('+QUERIES[variant]+') hit')
        answer, errors = [], []
        def read():
            try: answer.append(other.execute(render(other,statement)).fetchone())
            except BaseException as exc: errors.append(type(exc).__name__)
        thread = Thread(target=read,daemon=True);thread.start()
        try:
            deadline = time.monotonic()+1.5
            while time.monotonic()<deadline:
                blocked = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s "
                    "AND locktype='advisory' AND NOT granted)",(reader_pid,)).fetchone()[0]
                if blocked: break
                time.sleep(.01)
            assert blocked, 'reader did not enter the statement-snapshot barrier'
            conn.execute(f'UPDATE {TABLE} SET cursor_name=%s,state=%s WHERE cursor_name=%s',
                ('shadow-moving',Jsonb({}),'ordinary-moving'));conn.commit()
        finally:
            conn.execute('SELECT pg_advisory_unlock(91827461)');conn.commit()
            thread.join(4)
        assert not thread.is_alive() and errors == []
        assert answer == [('ordinary-moving',)], 'one statement lost its original suspect'
        # Two independent statement snapshots can miss the exact same transition.
        conn.execute(f'UPDATE {TABLE} SET cursor_name=%s,state=%s WHERE cursor_name=%s',
            ('ordinary-moving',Jsonb({'wealth_core':False}),'shadow-moving'));conn.commit()
        first = other.execute(render(other,NAME_BRANCH+' LIMIT 1')).fetchone()
        conn.execute(f'UPDATE {TABLE} SET cursor_name=%s,state=%s WHERE cursor_name=%s',
            ('shadow-moving',Jsonb({}),'ordinary-moving'));conn.commit()
        suffix = ' ORDER BY cursor_name LIMIT 1' if variant == 'ordered' else ' LIMIT 1'
        second = other.execute(render(other,JSON_BRANCH+suffix)).fetchone()
        with pytest.raises(AssertionError,match='two statements lost moving lineage'):
            assert first or second, 'two statements lost moving lineage'


def payload(seed, size):
    return base64.b64encode(hashlib.shake_256(seed.encode()).digest(size//4*3)).decode()


def load_large(conn):
    for index_ in range(192): insert(conn,f'ordinary-large:{index_:04}',{'payload':payload('ordinary'+str(index_),256*1024)})
    for index_ in range(64): insert(conn,f'shadow-observation:v1:primary:session:large-{index_:04}',{'payload':payload('owned'+str(index_),512*1024)})
    for index_ in range(192): insert(conn,f'ordinary-inline:{index_:04}',{'payload':payload('inline'+str(index_),1024)})
    for index_ in range(64): insert(conn,f'shadow-observation:v1:primary:session:inline-{index_:04}',{'payload':payload('ownedinline'+str(index_),1536)})
    for name in parameters()[0]: insert(conn,name,SQL_NULL)
    insert(conn,'mutable-small',{'payload':'small'})
    conn.commit()
    size = conn.execute('SELECT pg_total_relation_size(%s::regclass)',(TABLE,)).fetchone()[0]
    assert 64*1024*1024 < size < MAX_BYTES
    return size


def vacuum(conn):
    conn.commit()
    with psycopg.connect(conn.info.dsn,autocommit=True) as other:
        other.execute("SET statement_timeout='3000ms'")
        other.execute(f'VACUUM (ANALYZE) {TABLE}')


def nodes(plan):
    yield plan
    for child in plan.get('Plans',[]): yield from nodes(child)


def explained(conn, name):
    arguments = sql.SQL(',').join(sql.Literal(value) for value in parameters())
    value = conn.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) EXECUTE {} ({})').format(
        sql.Identifier(name),arguments)).fetchone()[0][0]
    plan = value['Plan']
    return {'execution_ms':value['Execution Time'],'planning_ms':value['Planning Time'],
        'hit_blocks':plan.get('Shared Hit Blocks',0),'read_blocks':plan.get('Shared Read Blocks',0),
        'heap_fetches':sum(item.get('Heap Fetches',0) for item in nodes(plan)),
        'indexes':sorted({item['Index Name'] for item in nodes(plan) if 'Index Name' in item}),
        'plan':value}


def stats(conn):
    conn.execute('SELECT pg_stat_force_next_flush()');conn.commit()
    with psycopg.connect(conn.info.dsn,autocommit=True) as other:
        other.execute('SELECT pg_stat_clear_snapshot()')
        row = other.execute('SELECT n_tup_upd,n_tup_hot_upd FROM pg_stat_user_tables WHERE relname=%s',(TABLE,)).fetchone()
    return {'updates':row[0],'hot_updates':row[1]}


def mixed_writes(conn, variant):
    before = stats(conn)
    lsn = conn.execute('SELECT pg_current_wal_insert_lsn()').fetchone()[0]
    conn.commit();started = time.perf_counter()
    for number in range(16):
        conn.execute(f'UPDATE {TABLE} SET heartbeat=heartbeat+1 WHERE cursor_name=%s',
            ('shadow-observation:v1:primary:session:large-0000',))
        conn.execute(f'UPDATE {TABLE} SET state=%s WHERE cursor_name=%s',
            (Jsonb({'payload':'small','iteration':number}),'mutable-small'))
        if number%4 == 0:
            conn.execute(f'UPDATE {TABLE} SET state=%s WHERE cursor_name=%s',
                (Jsonb({'payload':payload(variant+str(number),256*1024)}),'ordinary-large:0000'))
            conn.execute(f'UPDATE {TABLE} SET state=%s WHERE cursor_name=%s',
                (Jsonb({'payload':payload(variant+'named'+str(number),512*1024)}),
                 'shadow-observation:v1:primary:session:large-0000'))
        conn.commit()
    wall = (time.perf_counter()-started)*1000
    wal = conn.execute('SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),%s::pg_lsn)',(lsn,)).fetchone()[0]
    after = stats(conn)
    return {'wall_ms':round(wall,3),'wal_bytes':int(wal),
            'updates':after['updates']-before['updates'],
            'hot_updates':after['hot_updates']-before['hot_updates']}


def evidence_path(tmp_path, filename):
    folder = Path('/evidence') if Path('/evidence').is_dir() else tmp_path
    return folder/filename


def retain(path, report):
    path.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')


def test_natural_prepared_access_paths_and_bounded_mixed_write_cost(conn, tmp_path):
    conn.prepare_threshold = None
    collation = table(conn)
    size = load_large(conn)
    report = {'DEV':'checkpoint-lineage-access-path','server_version':conn.execute('SHOW server_version').fetchone()[0],
        'collation':collation,'database_collation':conn.execute(
            'SELECT datcollate FROM pg_database WHERE datname=current_database()').fetchone()[0],
        'initial_total_bytes':size,'maximum_fixture_bytes':MAX_BYTES,
        'enable_seqscan':conn.execute('SHOW enable_seqscan').fetchone()[0],
        'row_counts':{'large_unexcluded':192,'large_excluded':64,'inline_unexcluded':192,'inline_excluded':64},
        'variants':{}}
    path = evidence_path(tmp_path,'checkpoint-lineage-design-plans.json')
    retain(path,report)
    assert report['enable_seqscan'] == 'on'
    for variant in ('original','A','B','ordered'):
        built = index(conn,variant)
        vacuum(conn)
        name = 'lineage_plan_'+variant.lower()
        conn.execute(f'PREPARE {name}(text[],text,text,text) AS '+QUERIES[variant])
        conn.commit()
        observations = []
        report['variants'][variant] = {**built,'observations':observations}
        retain(path,report)
        for visibility in ('clean','dirty'):
            if visibility == 'dirty':
                conn.execute(f'UPDATE {TABLE} SET heartbeat=heartbeat+1');conn.commit()
            for mode in ('force_custom_plan','force_generic_plan'):
                conn.execute("SELECT set_config('plan_cache_mode',%s,false)",(mode,))
                attempts = [explained(conn,name) for _ in range(3)]
                observations.append({'visibility':visibility,'mode':mode,
                    'median_ms':statistics.median(item['execution_ms'] for item in attempts),
                    'samples':attempts})
                retain(path,report)
                assert all(item['plan']['Plan']['Actual Rows'] == 0 for item in attempts)
                for foreign, value in [('unknown-paper-match',{'wealth_core':False}),('catchup',None)]:
                    insert(conn,foreign,value);conn.commit()
                    assert conn.execute(render(conn,QUERIES[variant])).fetchone() is not None
                    conn.execute(f'DELETE FROM {TABLE} WHERE cursor_name=%s',(foreign,));conn.commit()
        report['variants'][variant]['mixed_writes'] = mixed_writes(conn,variant)
        retain(path,report)
        conn.execute(f'DEALLOCATE {name}');conn.commit()
        assert conn.execute('SELECT pg_total_relation_size(%s::regclass)',(TABLE,)).fetchone()[0] < MAX_BYTES
    print(json.dumps(report,sort_keys=True),flush=True)
    baseline = max(item['median_ms'] for item in report['variants']['original']['observations'])
    for observation in report['variants']['ordered']['observations']:
        assert all(INDEX_B in item['indexes'] for item in observation['samples']), 'generic/custom natural plan did not use fallback index'
        assert observation['median_ms'] < baseline*.25, 'fallback index did not remove healthy negative JSON traversal'


def visibility_metadata(conn):
    relations = conn.execute('SELECT c.relname,c.relpages,c.reltuples,c.relallvisible,c.reloptions,'
        'pg_relation_size(c.oid) FROM pg_class c WHERE c.oid=to_regclass(%s) OR c.oid=to_regclass(%s) '
        'ORDER BY c.relname',(TABLE,INDEX_B)).fetchall()
    vm = conn.execute('SELECT all_visible,all_frozen FROM pg_visibility_map_summary(%s::regclass)',(TABLE,)).fetchone()
    settings = {name:conn.execute('SELECT current_setting(%s)',(name,)).fetchone()[0]
        for name in ('autovacuum','enable_seqscan','enable_indexscan','enable_indexonlyscan',
                     'random_page_cost','seq_page_cost','cpu_tuple_cost','cpu_index_tuple_cost',
                     'effective_cache_size','statement_timeout','plan_cache_mode')}
    return {'relations':relations,'actual_vm':{'all_visible':vm[0],'all_frozen':vm[1]},
            'settings':settings,'total_bytes':conn.execute('SELECT pg_total_relation_size(%s::regclass)',(TABLE,)).fetchone()[0]}


def load_planner_regression(conn):
    # Same cardinality/heap shape as the independently retained larger failure,
    # with each incompressible large payload reduced to512KiB to bound storage.
    for number in range(384):
        name = ('ordinary-large:' if number < 256 else
                'shadow-observation:v1:primary:session:large-')+f'{number:04}'
        insert(conn,name,{'payload':payload(name,512*1024)})
        if number%16 == 15:
            conn.commit()
            assert conn.execute('SELECT pg_total_relation_size(%s::regclass)',(TABLE,)).fetchone()[0] < MAX_BYTES
    for number in range(183):
        name = ('ordinary-inline:' if number < 128 else
                'shadow-observation:v1:primary:session:inline-')+f'{number:04}'
        insert(conn,name,{'payload':name*16})
    for name in parameters()[0]:insert(conn,name,{'wealth_core':False})
    insert(conn,'mutable-small',{})
    conn.commit()
    assert conn.execute('SELECT pg_total_relation_size(%s::regclass)',(TABLE,)).fetchone()[0] < MAX_BYTES


def test_ordered_witness_survives_stale_and_analyzed_zero_visibility(conn, tmp_path, monkeypatch):
    from sentinel import checkpoint_lineage_access as production
    conn.prepare_threshold = None
    table(conn)
    conn.execute('CREATE EXTENSION pg_visibility WITH SCHEMA pg_catalog')
    conn.commit()
    load_planner_regression(conn)
    index(conn,'ordered')
    vacuum(conn)
    path = evidence_path(tmp_path,'checkpoint-lineage-zero-vm-plans.json')
    report = {'server_version':conn.execute('SHOW server_version').fetchone()[0],
        'database':conn.execute('SELECT datcollate,datctype,datlocprovider FROM pg_database '
                                'WHERE datname=current_database()').fetchone(),
        'maximum_bytes':MAX_BYTES,'queries':{'B':QUERY_B,'ordered':QUERY_ORDERED},'observations':[]}
    for variant in ('B','ordered'):
        conn.execute(f'PREPARE visibility_{variant.lower()}(text[],text,text,text) AS '+QUERIES[variant])
    conn.commit()
    def capture(phase):
        for mode in ('force_custom_plan','force_generic_plan'):
            conn.execute("SELECT set_config('plan_cache_mode',%s,false)",(mode,))
            for variant in ('B','ordered'):
                observation = {'phase':phase,'mode':mode,'variant':variant,
                    'before':visibility_metadata(conn),'samples':[]}
                report['observations'].append(observation);retain(path,report)
                for _ in range(3):
                    observation['samples'].append(explained(conn,'visibility_'+variant.lower()))
                    retain(path,report)
                observation['after'] = visibility_metadata(conn);retain(path,report)
    capture('vacuumed')
    conn.execute(f'UPDATE {TABLE} SET heartbeat=heartbeat+1');conn.commit()
    capture('dirty_stale_statistics')
    conn.execute(f'ANALYZE {TABLE}');conn.commit()
    capture('dirty_analyzed_statistics')
    # Preserve every plan before testing physical preconditions or access paths.
    print(json.dumps({'ordered_zero_vm_evidence':str(path),'report':report},sort_keys=True),flush=True)
    for observation in report['observations']:
        metadata = observation['before']
        assert metadata['total_bytes'] < MAX_BYTES
        assert all(metadata['settings'][setting] == 'on' for setting in (
            'autovacuum','enable_seqscan','enable_indexscan','enable_indexonlyscan'))
        assert all(item['plan']['Plan']['Actual Rows'] == 0 for item in observation['samples'])
        if observation['phase'].startswith('dirty'):
            assert metadata['actual_vm']['all_visible'] == 0
            heap = next(row for row in metadata['relations'] if row[0] == TABLE)
            if observation['phase'] == 'dirty_stale_statistics':
                assert heap[3] > 0
            else:
                assert heap[3] == 0
        if observation['variant'] == 'ordered':
            assert all(INDEX_B in item['indexes'] for item in observation['samples']), json.dumps(observation)
    # Execute the removed-order SQL in every captured physical state above. Its
    # actual natural plan is evidence, not an assumption about all future PG
    # optimizers. Independently kill removing the reviewed production request
    # even if another supported optimizer happens to retain the same index.
    removed = production.QUERY.replace(' ORDER BY cursor_name LIMIT 1',' LIMIT 1',1)
    assert removed != production.QUERY
    assert conn.execute(render(conn,QUERY_B)).fetchone() is None
    report['removed_order_executed'] = True
    with monkeypatch.context() as mutation:
        mutation.setattr(production,'QUERY',removed)
        with pytest.raises(AssertionError):
            test_production_query_and_predicate_match_executed_design()
    report['removed_order_wire_falsifier'] = True
    retain(path,report)
