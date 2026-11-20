import psycopg
import pytest

from sentinel import backup_runtime_authority
from sentinel.feed import retention
from sentinel.feed.publication import CORPUS_LOCK_KEY
from sentinel.feed.retention_schema import ACQUISITION_PIN_TABLES
from sentinel.execution import journal
from tests.sentinel.test_rolling_snapshot_publisher import conn, enqueue, pg  # noqa: F401


@pytest.fixture(autouse=True)
def admitted_staging(monkeypatch):
    def verified(conn, *, operation, allow_continuity):
        assert operation == 'private acquisition retirement' and allow_continuity
    monkeypatch.setattr(backup_runtime_authority, 'require', verified)
    monkeypatch.setattr(retention, 'opening_execution_due', lambda _: False)


def stage(conn):
    part = 'e' * 64
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES(%s,'{}')", (part,))
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-09-01','AAA','{}')", (part,))
    conn.commit()


def test_private_disposal_completes_while_another_backend_owns_account_and_corpus(conn):
    stage(conn)
    with psycopg.connect(conn.info.dsn) as other:
        other.execute('SELECT pg_advisory_xact_lock(%s), pg_advisory_xact_lock(%s)',
                      (journal.WRITER_LOCK_KEY, CORPUS_LOCK_KEY))
        result = retention.maintain(conn)
        assert result['status'] == 'COMPLETE', result
        assert (result['deleted_acquisition_rows'], result['deleted_acquisition_parts']) == (1, 1)
        assert other.execute('SELECT count(*) FROM sentinel_acquisition_parts').fetchone() == (0,)


@pytest.mark.parametrize('table', ACQUISITION_PIN_TABLES + ('sentinel_acquisition_parts',))
def test_open_pin_graph_writer_prevents_deletion_until_its_transaction_finishes(conn, table):
    stage(conn)
    with psycopg.connect(conn.info.dsn) as other:
        other.execute(f'LOCK TABLE {table} IN ROW EXCLUSIVE MODE')
        result = retention.maintain(conn)
        assert result['status'] == 'RETRY' and result['reason'] == 'LockNotAvailable', result
        assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (1,)
        conn.commit()
    assert retention.maintain(conn)['deleted_acquisition_parts'] == 1


def test_database_refuses_an_incomplete_set_of_private_ownership_locks(conn):
    stage(conn)
    with pytest.raises(psycopg.errors.RaiseException, match='retirement requires'):
        with conn.transaction():
            conn.execute('LOCK TABLE sentinel_acquisition_parts IN SHARE ROW EXCLUSIVE MODE')
            conn.execute('LOCK TABLE ' + ', '.join(ACQUISITION_PIN_TABLES[:-1]) + ' IN SHARE MODE')
            conn.execute('DELETE FROM sentinel_acquisition_prices')
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (1,)


@pytest.mark.parametrize('rows', [1, 2])
def test_binding_after_retirement_cannot_pin_missing_or_partial_prices(conn, rows):
    job = enqueue(conn)
    part = 'f' * 64
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) "
                 "VALUES(%s,jsonb_build_object('rows',%s::int))", (part, rows))
    for ticker in ('A', 'B')[:rows]:
        conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-09-01',%s,'{}')", (part, ticker))
    conn.commit()
    assert retention.maintain(conn, batch_rows=1)['deleted_acquisition_rows'] == 1
    with psycopg.connect(conn.info.dsn) as writer, pytest.raises(psycopg.errors.RaiseException, match='new binding requires'):
        writer.execute("INSERT INTO sentinel_acquisition_bindings VALUES(%s,'SEP.month',%s)", (job, part))
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_bindings').fetchone() == (0,)


def test_pin_wins_before_cleanup_and_survives_subsequent_pass(conn):
    job = enqueue(conn)
    part = 'f' * 64
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES(%s,'{\"rows\":1}')", (part,))
    conn.execute("INSERT INTO sentinel_acquisition_prices VALUES(%s,'2026-09-01','A','{}')", (part,))
    conn.commit()
    with psycopg.connect(conn.info.dsn) as writer:
        writer.execute("INSERT INTO sentinel_acquisition_bindings VALUES(%s,'SEP.month',%s)", (job, part))
        result = retention.maintain(conn)
        assert result.get('reason') == 'LockNotAvailable', result
    assert retention.maintain(conn).get('reason') == 'NO_WORK'
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (1,)
