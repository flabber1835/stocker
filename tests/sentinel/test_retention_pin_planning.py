"""Private canonical SQL proves scoped compilation and exact restoration."""
from contextlib import contextmanager
import json
from pathlib import Path
import time
import uuid

import pytest

from sentinel.feed import acquisition_part_schema, normalized_layout, retention, retention_schema
from sentinel.feed.schema import DDL as FEED_DDL
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


@pytest.fixture
def pin_sql(pg):
    import psycopg
    from psycopg import sql
    conn=psycopg.connect(pg.sync_dsn)
    schema='pin_planning_'+uuid.uuid4().hex
    conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    conn.execute(sql.SQL('SET search_path TO {},public').format(sql.Identifier(schema)))
    definitions={
        'sentinel_snapshot_jobs':'job_id uuid,state text,reason text,deadline timestamptz',
        'sentinel_acquisition_successors':'parent_job_id uuid,child_job_id uuid',
        'sentinel_acquisition_bindings':'job_id uuid,component text,part_id text',
        'sentinel_acquisition_price_links':'part_id text,payload_part_id text',
        'sentinel_acquisition_parts':'part_id text PRIMARY KEY,manifest jsonb,created_at timestamptz DEFAULT clock_timestamp()',
        'sentinel_operational_snapshots':'job_id uuid,publication_version bigint',
        'sentinel_corpus_publications':'version bigint',
        'sentinel_acquisition_prices':'part_id text,session date,ticker text,payload text,PRIMARY KEY(part_id,session,ticker)',
        'prior_class':'value integer',
    }
    for name,columns in definitions.items():
        conn.execute(f'CREATE TABLE {name}({columns})')
    for prefix,statements in (
        ('CREATE OR REPLACE FUNCTION sentinel_retention_locks()',retention_schema.DDL),
        ('CREATE OR REPLACE FUNCTION sentinel_acquisition_part_pinned(',acquisition_part_schema.DDL),
        ('CREATE OR REPLACE FUNCTION sentinel_acquisition_delete_guard()',acquisition_part_schema.DDL),
        ('CREATE TRIGGER acquisition_delete_guard BEFORE DELETE ON sentinel_acquisition_parts',acquisition_part_schema.DDL),
        ('CREATE OR REPLACE FUNCTION sentinel_acquisition_price_delete_guard()',FEED_DDL),
        ('CREATE TRIGGER acquisition_delete_guard AFTER DELETE ON sentinel_acquisition_prices',acquisition_part_schema.DDL),
    ):
        (statement,) = (query for query in statements if query.startswith(prefix))
        conn.execute(statement)
    conn.commit()
    try:
        yield conn,Path(pg.datadir,'server.log')
    finally:
        conn.rollback()
        conn.execute('SELECT pg_advisory_unlock_all()')
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


@pytest.mark.parametrize('previous',['on','off'])
def test_pin_scope_restores_actual_caller_setting(pin_sql,previous):
    conn,_=pin_sql
    conn.execute('SELECT set_config(\'jit\',%s,false)',(previous,))
    conn.commit()
    with retention._pin_planning(conn):
        assert conn.execute("SHOW jit").fetchone()==('off',)
    assert conn.execute("SHOW jit").fetchone()==(previous,)


def test_cancelled_pin_scope_restores_setting_and_preserves_prior_class(pin_sql):
    import psycopg
    conn,_=pin_sql
    conn.execute("SET jit=on")
    conn.execute('INSERT INTO prior_class VALUES(1)')
    port=retention._Budget(conn,time.monotonic()+.08,ceiling_ms=80)
    with pytest.raises(psycopg.errors.QueryCanceled):
        with retention._pin_planning(port):
            port.execute('INSERT INTO prior_class VALUES(2)')
            port.execute('SELECT pg_sleep(1)')
    assert conn.execute('SHOW jit').fetchone()==('on',)
    assert conn.execute('SELECT value FROM prior_class').fetchall()==[(1,)]


def test_pin_cleanup_failure_cannot_replace_original_error(pin_sql):
    conn,_=pin_sql
    original=RuntimeError('original guard refusal')
    class BrokenRollback:
        def execute(self,query,params=None):
            if query.startswith('ROLLBACK TO'):
                raise OSError('cleanup transport unavailable')
            return conn.execute(query,params)
    with pytest.raises(RuntimeError) as caught:
        with retention._pin_planning(BrokenRollback()):
            raise original
    assert caught.value is original
    conn.rollback()
    assert conn.execute('SHOW jit').fetchone()==('on',)


def _records(text):
    result,offset,decoder=[],0,json.JSONDecoder()
    while (start:=text.find('plan:',offset))>=0:
        start+=5
        start+=len(text[start:])-len(text[start:].lstrip())
        try:
            value,end=decoder.raw_decode(text[start:])
        except ValueError:
            offset=start+1
        else:
            result.append(value)
            offset=start+end
    return result


def _canonical_compilations(pin_sql):
    conn,log=pin_sql
    conn.execute("LOAD 'auto_explain'")
    for name,value in [('log_min_duration','0'),('log_analyze','on'),
                       ('log_buffers','on'),('log_nested_statements','on'),('log_format','json')]:
        conn.execute(f"SET auto_explain.{name}='{value}'")
    # This private discriminator deliberately forces the compilation branch;
    # the default-settings populated causal A/B is retained separately.
    conn.execute('SET LOCAL jit=on')
    conn.execute('SET LOCAL jit_above_cost=0')
    before=log.stat().st_size
    assert conn.execute('SELECT sentinel_acquisition_part_pinned(%s)',('a'*64,)).fetchone()==(False,)
    on=_records(log.read_text()[before:])
    before=log.stat().st_size
    with retention._pin_planning(conn):
        assert conn.execute('SELECT sentinel_acquisition_part_pinned(%s)',('a'*64,)).fetchone()==(False,)
    off=_records(log.read_text()[before:])
    canonical=lambda records:[record for record in records
        if 'WITH RECURSIVE live(job_id)' in record.get('Query Text','')]
    assert canonical(on) and canonical(off)
    assert sum(value.get('JIT',{}).get('Functions',0) for value in canonical(on))>0
    assert sum(value.get('JIT',{}).get('Functions',0) for value in canonical(off))==0, \
        'canonical pin query was recompiled inside the suppression scope'
    assert conn.execute('SHOW jit').fetchone()==('on',)


def test_scoped_pin_query_eliminates_actual_canonical_jit_compilation(pin_sql):
    _canonical_compilations(pin_sql)


def test_removing_pin_compilation_boundary_is_detected(pin_sql,monkeypatch):
    @contextmanager
    def omitted(_conn):
        yield
    monkeypatch.setattr(retention,'_pin_planning',omitted)
    with pytest.raises(AssertionError,match='recompiled inside'):
        _canonical_compilations(pin_sql)


def test_real_acquisition_disposal_and_final_guard_run_inside_scope(pin_sql):
    conn,_=pin_sql
    target='a'*64
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES(%s,'{}')",(target,))
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-09-14','AAA','{}')",(target,))
    for key in (1579621904,1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)',(key,))
    conn.execute('SET jit=on')
    observed=[]
    class Actual:
        def execute(self,query,params=None):
            if 'sentinel_acquisition_' in query:
                observed.append(query)
                assert conn.execute('SHOW jit').fetchone()==('off',)
            return conn.execute(query,params)
    progress=retention.RetentionProgress(known_retirement_count=0)
    _,result=retention._run_class(Actual(),5,progress,batch_rows=7)
    assert result['deleted_acquisition_rows']==1 and result['deleted_acquisition_parts']==1
    assert observed and conn.execute('SHOW jit').fetchone()==('on',)


def test_late_price_part_seeks_existing_primary_key_for_each_capped_batch(pin_sql):
    conn, _ = pin_sql
    target, last, empty = ('a' * 64, 'y' * 64, 'z' * 64)
    # Match the installed 58-key distribution and roughly 1.9% selectivity.
    # Acquisition parts arrive in hash-key rather than lexical order; a part's
    # own tuples can all sit late in the heap even with weak key correlation.
    conn.execute("""
        INSERT INTO sentinel_acquisition_prices
        SELECT 'f' || left(repeat(md5(((n-1) / 2560)::text),2),63), DATE '2026-01-01' + mod(n,100),
               lpad(n::text,8,'0'), repeat('price payload',12)
        FROM generate_series(1,143360) n
    """)
    conn.execute("""
        INSERT INTO sentinel_acquisition_prices
        SELECT %s, DATE '2026-01-01' + mod(n,100), lpad(n::text,8,'0'), repeat('price payload',12)
        FROM generate_series(1,2816) n
    """, (target,))
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-09-14','AAA','{}')", (last,))
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) "
        "SELECT DISTINCT part_id,'{}'::jsonb FROM sentinel_acquisition_prices")
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES(%s,'{}')", (empty,))
    # The resulting 150,000-row sample covers the entire private fixture.
    conn.execute('ALTER TABLE sentinel_acquisition_prices ALTER COLUMN part_id SET STATISTICS 500')
    conn.execute('ANALYZE sentinel_acquisition_prices')
    for key in (1579621904, 1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    conn.commit()

    plans = {}
    class Measured:
        def execute(self, query, params=None):
            if query.startswith('SELECT ctid FROM sentinel_acquisition_prices'):
                def plan(statement, part):
                    return '\n'.join(line for line, in conn.execute(
                        'EXPLAIN (COSTS OFF) ' + statement, (part, params[1])).fetchall())
                for part in (target, last, empty):
                    plans[part] = plan(query, part)
                plans['unordered'] = plan(query.replace('ORDER BY session,ticker ', ''), target)
            return conn.execute(query, params)

    progress = retention.RetentionProgress(known_retirement_count=0)
    progress, result = retention._run_class(Measured(), 5, progress, batch_rows=5000)
    assert progress.acquisition_after == target and result['deleted_acquisition_rows'] == 128
    assert result['deleted_acquisition_parts'] == 0
    assert 'Seq Scan on sentinel_acquisition_prices' in plans['unordered']
    for part in (target, last, empty):
        assert 'Index Scan using sentinel_acquisition_prices_pkey' in plans[part]
        assert 'Index Cond: (part_id =' in plans[part] and 'Sort' not in plans[part]


def test_locked_price_prefix_yields_to_unlocked_rows_and_other_parts_until_revisit(pin_sql):
    import psycopg
    from psycopg import sql
    conn, _ = pin_sql
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) "
        "VALUES ('first','{}'),('next-empty','{}'),('next-one','{}')")
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES "
        "('first','2026-09-14','A','{}'),('first','2026-09-14','B','{}'),"
        "('first','2026-09-14','C','{}'),('next-one','2026-09-14','A','{}')")
    for key in (1579621904, 1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    initial = retention.RetentionProgress(known_retirement_count=0)
    schema = conn.execute('SELECT current_schema()').fetchone()[0]
    conn.commit()
    def step(progress):
        conn.execute("SET LOCAL statement_timeout='1s'")
        result = retention._run_class(conn, 5, progress, batch_rows=128)
        conn.commit()
        return result
    with psycopg.connect(conn.info.dsn) as peer:
        peer.execute(sql.SQL('SET LOCAL search_path TO {},public').format(sql.Identifier(schema)))
        peer.execute("SELECT ticker FROM sentinel_acquisition_prices WHERE part_id='first' "
            "AND ticker='A' FOR UPDATE").fetchone()
        _, result = step(initial)
        assert (result['deleted_acquisition_rows'], result['deleted_acquisition_parts']) == (2, 0)
        # Only the locked last row remains. A fresh traversal can still drain
        # both kinds of later parts under the actual pin and deletion guards.
        progress, result = step(initial)
        assert progress.acquisition_after == 'next-empty'
        assert (result['deleted_acquisition_rows'], result['deleted_acquisition_parts']) == (0, 1)
        progress, result = step(progress)
        assert progress.acquisition_after == 'next-one'
        assert (result['deleted_acquisition_rows'], result['deleted_acquisition_parts']) == (1, 1)
        progress, result = step(progress)
        assert progress.acquisition_after is None and not result['progress_made']
    _, result = step(progress)
    assert (result['deleted_acquisition_rows'], result['deleted_acquisition_parts']) == (1, 1)
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_parts').fetchone() == (0,)


def test_bulk_delete_checks_each_distinct_part_once(pin_sql):
    conn, log = pin_sql
    conn.execute('SET LOCAL jit=off')
    for key in (1579621904, 1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    conn.execute("""
        INSERT INTO sentinel_acquisition_prices
        SELECT part, DATE '2026-09-14' + day, 'AAA', '{}'
        FROM unnest(ARRAY['first','second']) AS parts(part)
        CROSS JOIN generate_series(0, 49) AS days(day)
    """)
    conn.execute("LOAD 'auto_explain'")
    conn.execute("SET auto_explain.log_min_duration='0'")
    conn.execute("SET auto_explain.log_nested_statements='on'")
    conn.execute("SET auto_explain.log_format='json'")
    before = log.stat().st_size
    assert conn.execute('DELETE FROM sentinel_acquisition_prices').rowcount == 100
    plans = _records(log.read_text()[before:])
    checks = [plan for plan in plans if 'WITH RECURSIVE live(job_id)' in plan.get('Query Text', '')]
    assert len(checks) == 2


def test_bulk_delete_refuses_a_statement_containing_a_pinned_part(pin_sql):
    import psycopg

    conn, _ = pin_sql
    job_id = uuid.uuid4()
    conn.execute("INSERT INTO sentinel_snapshot_jobs(job_id,state) VALUES(%s,'ACQUIRING')", (job_id,))
    conn.execute(
        "INSERT INTO sentinel_acquisition_bindings VALUES(%s,'SEP.first','pinned')",
        (job_id,),
    )
    conn.execute("""
        INSERT INTO sentinel_acquisition_prices VALUES
        ('pinned','2026-09-14','AAA','{}'), ('retired','2026-09-14','AAA','{}')
    """)
    for key in (1579621904, 1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    with pytest.raises(psycopg.errors.RaiseException, match='active acquisition part'):
        with conn.transaction():
            conn.execute('DELETE FROM sentinel_acquisition_prices')
    assert conn.execute(
        'SELECT part_id FROM sentinel_acquisition_prices ORDER BY part_id'
    ).fetchall() == [('pinned',), ('retired',)]


def test_acquisition_hint_is_scoped_and_restored(pin_sql,monkeypatch):
    conn,_=pin_sql
    conn.execute('SET jit=on')
    conn.commit()
    hints=['FALSE']*7
    hints[5]="NOT sentinel_acquisition_part_pinned('"+'a'*64+"')"
    monkeypatch.setattr(retention,'_HINTS',tuple(hints))
    monkeypatch.setattr(retention,'_read_progress',lambda _:None)
    monkeypatch.setattr(retention,'_payload_possible',lambda *_:False)
    monkeypatch.setattr(normalized_layout,'available',lambda _:False)
    observed=[]
    class Actual:
        def execute(self,query,params=None):
            if query=='SELECT '+hints[5]:
                observed.append(True)
                assert conn.execute('SHOW jit').fetchone()==('off',)
            return conn.execute(query,params)
        def rollback(self):
            conn.rollback()
    assert retention._possible_work(Actual()) and observed
    assert conn.execute('SHOW jit').fetchone()==('on',)

def test_pinned_prefix_has_bounded_discovery_and_resumes_after_restart(pin_sql):
    conn, _ = pin_sql
    count = 733
    last = f'{count:04}'
    job = uuid.uuid4()
    conn.execute("INSERT INTO sentinel_snapshot_jobs(job_id,state) VALUES(%s,'ACQUIRING')", (job,))
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) "
                 "SELECT lpad(n::text,4,'0'),'{}' FROM generate_series(1,%s) n", (count,))
    conn.execute("INSERT INTO sentinel_acquisition_bindings SELECT %s,'SEP',part_id "
                 "FROM sentinel_acquisition_parts WHERE part_id<>%s", (job,last))
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-09-14','AAA','{}')", (last,))
    for key in (1579621904,1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    conn.commit()
    progress = retention.RetentionProgress(known_retirement_count=0)
    calls = 0
    class Measured:
        def execute(self, query, params=None):
            nonlocal calls
            if 'WHERE part_id=%s AND NOT sentinel_acquisition_part_pinned' in query:
                calls += 1
            return conn.execute(query, params)
    for step in range(count // retention.ACQUISITION_PAGE + 2):
        calls = 0
        progress, result = retention._run_class(Measured(), 5, progress, batch_rows=1)
        assert 0 < calls <= retention.ACQUISITION_PAGE
        if step == 0:
            # Merely visiting a live part must not block its real writer.
            import psycopg
            with psycopg.connect(conn.info.dsn) as writer:
                schema = conn.execute('SELECT current_schema()').fetchone()[0]
                writer.execute("SELECT set_config('search_path',%s,true)", (schema,))
                assert writer.execute("SELECT part_id FROM sentinel_acquisition_parts "
                                      "WHERE part_id='0001' FOR UPDATE NOWAIT").fetchone() == ('0001',)
        conn.commit()
        progress = retention.RetentionProgress.model_validate_json(progress.model_dump_json(by_alias=True))
        if result['deleted_acquisition_parts']:
            break
    assert result['deleted_acquisition_parts'] == result['deleted_acquisition_rows'] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_parts').fetchone() == (count-1,)
    with retention._pin_planning(conn):
        assert conn.execute('SELECT '+retention._HINTS[5]).fetchone() == (False,)
    progress, result = retention._run_class(conn, 5, progress, batch_rows=1)
    assert progress.acquisition_after is None and not result['progress_made']
    # A part that loses its pin behind the old cursor is reachable on the next sweep.
    conn.execute("DELETE FROM sentinel_acquisition_bindings WHERE part_id='0001'")
    _, result = retention._run_class(conn, 5, progress, batch_rows=1)
    assert result['deleted_acquisition_parts'] == 1

@pytest.mark.parametrize('interruption', ['planner_restore', 'final_class_check'])
def test_post_delete_interruption_yields_the_key_but_rolls_back_data(pin_sql, monkeypatch, interruption):
    conn, _ = pin_sql
    conn.execute('SET jit=on')
    conn.execute('CREATE TABLE sentinel_snapshot_retirements(candidate_id uuid)')
    conn.execute('CREATE TABLE sentinel_snapshot_maintenance(id boolean PRIMARY KEY, '
                 'updated_at timestamptz DEFAULT clock_timestamp(), diagnostic jsonb)')
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES('first','{}'),('second','{}')")
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES('first','2026-09-14','A','{}'),"
                 "('first','2026-09-14','B','{}')")
    for key in (1579621904,1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    retained = retention.RetentionProgress(known_retirement_count=0, next_class=5,
        acquisition_after='first', acquisition_batches_left=4)
    retention._write_result(conn, {}, retained)
    conn.commit()

    run = retention._run_class
    monkeypatch.setattr(retention, '_run_class', lambda port, cls, progress, **kw:
        run(port, cls, progress, **kw) if cls == 5 else (progress, retention._stats()))
    execute = retention._Budget.execute
    deleted = []

    def interrupt_once(port, sql, params=None):
        if sql.startswith("SELECT set_config('jit'") and len(deleted) == 1:
            assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (1,)
            if interruption == 'planner_restore':
                conn.execute("SET LOCAL statement_timeout='20ms'")
                conn.execute('SELECT pg_sleep(1)')  # Real cancellation during planner restoration.
            result = execute(port, sql, params)
            port.deadline = time.monotonic() - 1  # Actual post-return class budget check.
            return result
        result = execute(port, sql, params)
        if sql.startswith('DELETE FROM sentinel_acquisition_prices'):
            deleted.append(result.rowcount)
        return result

    monkeypatch.setattr(retention._Budget, 'execute', interrupt_once)
    failed = retention._pass(conn, batch_rows=1)
    conn.commit()
    assert deleted == [1] and failed['status'] == 'RETRY'
    assert not failed['more_work'] and not failed['progress_made']
    assert failed['deleted_acquisition_rows'] == failed['deleted_acquisition_parts'] == 0
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (2,)
    saved = retention._read_progress(conn)
    assert saved.acquisition_after == 'first' and saved.acquisition_batches_left == 0
    assert conn.execute('SHOW jit').fetchone() == ('on',)

    monkeypatch.setattr(retention._Budget, 'execute', execute)
    next_pass = retention._pass(conn, batch_rows=1)
    conn.commit()
    assert next_pass['deleted_acquisition_parts'] == 1 and next_pass['deleted_acquisition_rows'] == 0
    assert conn.execute('SELECT part_id FROM sentinel_acquisition_parts').fetchall() == [('first',)]


def test_cancelled_part_yields_to_the_next_key_and_is_revisited(pin_sql):
    import psycopg

    conn, _ = pin_sql
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) "
                 "VALUES('first','{}'),('second','{}')")
    for key in (1579621904,1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    conn.commit()
    class SlowPin:
        def execute(self, query, params=None):
            if 'WHERE part_id=%s AND NOT sentinel_acquisition_part_pinned' in query and params == ('first',):
                return conn.execute('SELECT pg_sleep(1)')
            return conn.execute(query, params)
    conn.execute("SET LOCAL statement_timeout='60ms'")
    progress = retention.RetentionProgress(known_retirement_count=0)
    with pytest.raises(retention._CandidateRetry) as failure:
        retention._run_class(SlowPin(), 5, progress, batch_rows=1)
    assert isinstance(failure.value.cause, psycopg.errors.QueryCanceled)
    assert failure.value.progress.acquisition_after == 'first'
    assert conn.execute("SELECT count(*) FROM sentinel_acquisition_parts").fetchone() == (2,)
    conn.commit()
    progress, result = retention._run_class(conn, 5, failure.value.progress, batch_rows=1)
    assert result['deleted_acquisition_parts'] == 1 and progress.acquisition_after == 'second'
    progress, _ = retention._run_class(conn, 5, progress, batch_rows=1)
    assert progress.acquisition_after is None
    _, result = retention._run_class(conn, 5, progress, batch_rows=1)
    assert result['deleted_acquisition_parts'] == 1

def test_part_burst_drains_consecutively_then_yields_under_the_original_pin_guard(pin_sql):
    conn, _ = pin_sql
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES('first','{}'),('next','{}')")
    conn.execute("INSERT INTO sentinel_acquisition_prices "
                 "SELECT 'first',DATE '2026-01-01',n::text,'{}' FROM generate_series(1,%s) n",
                 (retention.ACQUISITION_BATCH_ROWS*retention.ACQUISITION_BURST+1,))
    for key in (1579621904,1579663541):
        conn.execute('SELECT pg_advisory_lock(%s)', (key,))
    conn.commit()
    progress = retention.RetentionProgress(known_retirement_count=0)
    for _ in range(retention.ACQUISITION_BURST):
        progress, result = retention._run_class(conn, 5, progress, batch_rows=retention.ACQUISITION_BATCH_ROWS)
        assert result['deleted_acquisition_rows'] == retention.ACQUISITION_BATCH_ROWS
        assert not result['deleted_acquisition_parts'] and progress.acquisition_after == 'first'
        conn.commit()
        progress = retention.RetentionProgress.model_validate_json(progress.model_dump_json(by_alias=True))
    progress, result = retention._run_class(conn, 5, progress, batch_rows=1)
    assert result['deleted_acquisition_parts'] == 1 and progress.acquisition_after == 'next'
    job = uuid.uuid4()
    conn.execute("INSERT INTO sentinel_snapshot_jobs(job_id,state) VALUES(%s,'ACQUIRING')", (job,))
    conn.execute("INSERT INTO sentinel_acquisition_bindings VALUES(%s,'SEP','first')", (job,))
    # Previously committed continuation data cannot authorize a newly pinned part.
    saved = progress.model_copy(update={'acquisition_after':'first','acquisition_batches_left':3})
    _, result = retention._run_class(conn, 5, saved, batch_rows=1)
    assert not result['deleted_acquisition_rows']
    assert conn.execute("SELECT count(*) FROM sentinel_acquisition_prices WHERE part_id='first'").fetchone() == (1,)

@pytest.mark.parametrize('kind, pinned', [
    ('active',True), ('ancestor',True), ('pending_successor',True), ('expired_successor',False),
    ('current_publication',True), ('old_publication',False), ('other_component',False),
    ('other_provider',False), ('unreferenced',False),
])
def test_acquisition_admission_hint_matches_canonical_pin_for_parent_and_linked_payload(pin_sql,kind,pinned):
    conn, _ = pin_sql
    parent, child = uuid.uuid4(), uuid.uuid4()
    provider = 'OTHER' if kind == 'other_provider' else 'ALPACA_OPENFIGI'
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES "
                 "('binding',jsonb_build_object('generation',jsonb_build_object('provider',%s::text))),"
                 "('payload','{}')", (provider,))
    conn.execute("INSERT INTO sentinel_acquisition_price_links VALUES('binding','payload')")
    state = 'ACQUIRING' if kind == 'active' else 'REFUSED'
    reason = 'SOURCE_GENERATION_CHANGED' if kind in ('pending_successor','expired_successor') else ''
    conn.execute('INSERT INTO sentinel_snapshot_jobs(job_id,state,reason,deadline) '
                 "VALUES(%s,%s,%s,clock_timestamp()+%s::interval)",
                 (parent,state,reason,'1 hour' if kind=='pending_successor' else '-1 hour'))
    if kind == 'ancestor':
        conn.execute("INSERT INTO sentinel_snapshot_jobs(job_id,state) VALUES(%s,'ACQUIRING')",(child,))
        conn.execute("INSERT INTO sentinel_acquisition_successors VALUES(%s,%s)",(parent,child))
    if kind != 'unreferenced':
        component = 'unrelated' if kind == 'other_component' else 'SEP.first'
        conn.execute("INSERT INTO sentinel_acquisition_bindings VALUES(%s,%s,'binding')", (parent,component))
    if kind in ('current_publication','old_publication','other_component','other_provider'):
        conn.execute("INSERT INTO sentinel_corpus_publications VALUES(2)")
        conn.execute("INSERT INTO sentinel_operational_snapshots VALUES(%s,%s)",
                     (parent,1 if kind=='old_publication' else 2))
    with retention._pin_planning(conn):
        actual = conn.execute("SELECT sentinel_acquisition_part_pinned(part_id) "
                              "FROM sentinel_acquisition_parts ORDER BY part_id").fetchall()
        assert actual == [(pinned,),(pinned,)]
        assert conn.execute('SELECT '+retention._HINTS[5]).fetchone() == (not pinned,)
