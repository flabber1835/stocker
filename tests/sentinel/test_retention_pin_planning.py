"""Private canonical SQL proves scoped compilation and exact restoration."""
from contextlib import contextmanager
import json
from pathlib import Path
import time
import uuid

import pytest

from sentinel.feed import acquisition_part_schema, normalized_layout, retention, retention_schema
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
        ('CREATE OR REPLACE FUNCTION sentinel_acquisition_price_delete_guard()',acquisition_part_schema.DDL),
        ('CREATE TRIGGER acquisition_delete_guard AFTER DELETE ON sentinel_acquisition_prices',acquisition_part_schema.DDL),
    ):
        conn.execute(next(query for query in statements if query.startswith(prefix)))
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
