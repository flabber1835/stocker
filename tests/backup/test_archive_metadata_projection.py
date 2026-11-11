"""Real PostgreSQL metadata parity and evaluated stat-call counts."""
from pathlib import Path

import psycopg
import pytest

from sentinel import backup_runtime_authority as authority
from tests.support.postgres import _EphemeralPostgres


# The original projection from 277160861._archive_metadata, retained as the
# differential oracle. It neither hashes archive content nor proves a chain.
LEGACY_SQL = (
    "SELECT name,(pg_stat_file(%s || '/' || name,true)).size,"
    " (pg_stat_file(%s || '/' || name,true)).modification,"
    " (pg_stat_file(%s || '/' || name,true)).change,"
    " pg_read_file(%s || '/' || name || '.sha256',0,80,true),"
    " (pg_stat_file(%s || '/' || name || '.sha256',true)).modification,"
    " (pg_stat_file(%s || '/' || name || '.sha256',true)).change"
    " FROM unnest(%s::text[]) AS entries(name)")


@pytest.fixture(scope='module')
def private_pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def media(private_pg):
    directory = Path(private_pg.datadir)/'metadata-projection'
    directory.mkdir(exist_ok=True)
    for name in ('first', 'second'):
        (directory/name).write_bytes(b'private archive metadata fixture')
        (directory/(name+'.sha256')).write_text('sha256='+'a'*64+'\n', encoding='ascii')
    with psycopg.connect(private_pg.sync_dsn, autocommit=True) as conn:
        yield conn, directory


def query(root, names):
    class Recording:
        def __init__(self):
            self.statement = None
        def cursor(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def execute(self, statement, args):
            self.statement = statement, args
        def fetchall(self):
            return []
    recording = Recording()
    assert authority._archive_metadata(recording, root=str(root), objects=names) == {}
    return recording.statement


def legacy(conn, root, names):
    return conn.execute(LEGACY_SQL, (str(root),)*6+(list(names),)).fetchall()


@pytest.mark.parametrize('fault', ['healthy', 'empty', 'missing_payload', 'missing_sidecar',
                                  'both_missing', 'truncated', 'long_sidecar'])
def test_actual_file_observations_match_original_projection(media, fault):
    conn, root = media
    names = ('first', 'second') if fault != 'empty' else ()
    if fault in {'missing_payload', 'both_missing'}:
        (root/'first').unlink()
    if fault in {'missing_sidecar', 'both_missing'}:
        (root/'first.sha256').unlink()
    if fault == 'truncated':
        (root/'first').write_bytes(b'x')
    if fault == 'long_sidecar':
        (root/'first.sha256').write_text('x'*100, encoding='ascii')
    before = legacy(conn, root, names)
    current = authority._archive_metadata(conn, root=str(root), objects=names)
    after = legacy(conn, root, names)
    assert before == after
    assert current == {r[0]: tuple(r[1:]) for r in before}


@pytest.mark.parametrize('payload', [b'\xff', b'sha256=\xff'])
def test_invalid_sidecar_encoding_keeps_original_database_refusal(media, payload):
    conn, root = media
    (root/'first.sha256').write_bytes(payload)
    for operation in (lambda: legacy(conn, root, ('first',)),
                      lambda: authority._archive_metadata(conn, root=str(root), objects=('first',))):
        with pytest.raises(psycopg.errors.CharacterNotInRepertoire):
            operation()


def counted_statement(conn, root, names):
    # STABLE wrappers preserve the real native file observations while a
    # sequence counts each evaluation. Their volatility lets the omission
    # falsifier expose projection expansion when materialization is removed.
    conn.execute('CREATE TEMP SEQUENCE stat_evaluations')
    conn.execute('''CREATE TYPE pg_temp.file_stat AS (
        size bigint,access timestamptz,modification timestamptz,
        change timestamptz,creation timestamptz,isdir boolean)''')
    conn.execute('''CREATE FUNCTION pg_temp.counted_stat(path text, missing_ok boolean)
        RETURNS pg_temp.file_stat
        LANGUAGE plpgsql STABLE AS $$
        DECLARE result pg_temp.file_stat;
        BEGIN
          PERFORM nextval('pg_temp.stat_evaluations');
          SELECT * INTO result FROM pg_catalog.pg_stat_file(path,missing_ok);
          RETURN result;
        END $$''')
    conn.execute('''CREATE FUNCTION pg_temp.counted_read(path text,offset_bytes bigint,
        length_bytes bigint,missing_ok boolean) RETURNS text LANGUAGE plpgsql STABLE AS $$
        BEGIN RETURN pg_catalog.pg_read_file(path,offset_bytes,length_bytes,missing_ok); END $$''')
    statement, args = query(root, names)
    return statement.replace('pg_stat_file(', 'pg_temp.counted_stat(').replace(
        'pg_read_file(', 'pg_temp.counted_read('), args


def count(conn, statement, args):
    conn.execute("SELECT setval('pg_temp.stat_evaluations',1,false)")
    result = conn.execute(statement, args).fetchall()
    last, called = conn.execute('SELECT last_value,is_called FROM pg_temp.stat_evaluations').fetchone()
    return result, last if called else 0


@pytest.mark.parametrize('names', [(), ('first',), ('first', 'second')])
def test_materialized_composites_evaluate_two_stats_per_object(media, names):
    conn, root = media
    statement, args = counted_statement(conn, root, names)
    current, calls = count(conn, statement, args)
    original, old_calls = count(conn,
        LEGACY_SQL.replace('pg_stat_file(', 'pg_temp.counted_stat('),
        (str(root),)*6+(list(names),))
    assert current == original
    assert calls == 2*len(names)
    assert old_calls == 5*len(names)


def nodes(plan):
    yield plan
    for child in plan.get('Plans', []):
        yield from nodes(child)


def test_actual_native_query_keeps_materialized_cte_in_plan(media):
    conn, root = media
    statement, args = query(root, ('first', 'second'))
    result = conn.execute('EXPLAIN (FORMAT JSON) '+statement, args).fetchone()[0][0]['Plan']
    assert any(n.get('Node Type') == 'CTE Scan' and n.get('CTE Name') == 'objects'
               for n in nodes(result))


def test_removed_materialization_is_detected_by_executed_call_counter(media):
    conn, root = media
    statement, args = counted_statement(conn, root, ('first', 'second'))
    assert statement.count('AS MATERIALIZED') == 1
    broken, calls = count(conn, statement.replace('AS MATERIALIZED', 'AS NOT MATERIALIZED'), args)
    assert broken == legacy(conn, root, ('first', 'second'))
    assert calls == 10
    with pytest.raises(AssertionError):
        assert calls == 4, 'metadata projection repeated file-stat evaluation'


def test_restored_duplicate_projection_is_detected_by_executed_call_counter(media):
    conn, root = media
    counted_statement(conn, root, ('first', 'second'))
    _, calls = count(conn, LEGACY_SQL.replace('pg_stat_file(', 'pg_temp.counted_stat('),
        (str(root),)*6+(['first', 'second'],))
    with pytest.raises(AssertionError):
        assert calls == 4, 'metadata projection repeated file-stat evaluation'
