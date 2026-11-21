from types import SimpleNamespace

import psycopg
import pytest

from sentinel import backup_runtime_authority, rolling_daily_checkpoint
from sentinel.feed import retention
from sentinel.feed.publication import CORPUS_LOCK_KEY
from sentinel.feed.retention_schema import ACQUISITION_PIN_TABLES
from sentinel.execution import journal
from tests.sentinel.test_opening_checkpoint_read_work import checkpoints  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, enqueue, pg  # noqa: F401


@pytest.fixture(autouse=True)
def admitted_staging(monkeypatch):
    def verified(conn, *, operation, allow_continuity):
        assert operation == 'private acquisition retirement' and allow_continuity
    monkeypatch.setattr(backup_runtime_authority, 'require', verified)
    monkeypatch.setattr(retention, 'opening_execution_due', lambda _: False)


def stage(conn, rows=1):
    part = 'e' * 64
    conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest) VALUES(%s,'{}')", (part,))
    conn.execute("INSERT INTO sentinel_acquisition_prices "
                 "SELECT %s,'2026-09-01','ROW'||lpad(i::text,5,'0'),'{}'::jsonb "
                 "FROM generate_series(1,%s) i", (part, rows))
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


@pytest.mark.parametrize('batch_rows,deleted', [(257, 257), (5000, 1024)])
def test_private_pass_amortizes_authentication_across_bounded_deletes(
        conn, monkeypatch, batch_rows, deleted):
    stage(conn, rows=1100)
    authenticate = retention._authenticate_checkpoints
    step = retention._acquisition_step
    proofs, batches = [], []

    def counted_authentication(port):
        proofs.append(port.execute('SELECT pg_current_xact_id()::text').fetchone()[0])
        authenticate(port)

    def counted_step(port, progress, *, batch_rows):
        result = step(port, progress, batch_rows=batch_rows)
        batches.append(result[1]['deleted_acquisition_rows'])
        return result

    monkeypatch.setattr(retention, '_authenticate_checkpoints', counted_authentication)
    monkeypatch.setattr(retention, '_acquisition_step', counted_step)
    first = retention.maintain(conn, batch_rows=batch_rows)
    assert first['status'] == 'COMPLETE', first
    assert first['deleted_acquisition_rows'] == deleted
    assert batches == [128] * (deleted // 128) + ([deleted % 128] if deleted % 128 else [])
    assert len(proofs) == 1
    assert retention._read_progress(conn).next_class == 6
    conn.rollback()

    second = retention.maintain(conn, batch_rows=1)
    assert second['deleted_acquisition_rows'] == 1
    assert len(set(proofs)) == 2
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (1100 - deleted - 1,)


@pytest.fixture
def idle_checkpoint_proof(conn, checkpoints):
    stage(conn, rows=8)
    return retention.IdleCheckpointProof()


@pytest.fixture
def checkpoint_authentications(monkeypatch):
    authenticate = retention._authenticate_checkpoints
    transactions = []

    def counted(port):
        transactions.append(port.execute('SELECT pg_current_xact_id()::text').fetchone()[0])
        return authenticate(port)

    monkeypatch.setattr(retention, '_authenticate_checkpoints', counted)
    return transactions


def corrupt_idle_archive(conn, checkpoint):
    cursor = rolling_daily_checkpoint.input_name(checkpoint.observation_id, checkpoint.session)
    updated = conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,"
                           "'{content}',to_jsonb(%s::text)) WHERE cursor_name=%s",
                           ('invalid compressed archive', cursor))
    assert updated.rowcount == 1
    conn.commit()


def test_idle_checkpoint_proof_reuses_exact_rows_across_committed_passes(
        conn, idle_checkpoint_proof, checkpoint_authentications, monkeypatch):
    admissions = []

    def admit(connection, *, operation, allow_continuity):
        assert operation == 'private acquisition retirement' and allow_continuity
        admissions.append(connection.execute('SELECT pg_current_xact_id()::text').fetchone()[0])

    monkeypatch.setattr(backup_runtime_authority, 'require', admit)
    first = retention.maintain(conn, batch_rows=1, checkpoint_proof=idle_checkpoint_proof)
    assert first['deleted_acquisition_rows'] == 1, first
    assert idle_checkpoint_proof.witness is not None
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('unrelated-retention-fixture','2026-09-14','{}')")
    conn.commit()

    second = retention.maintain(conn, batch_rows=1, checkpoint_proof=idle_checkpoint_proof)
    assert second['deleted_acquisition_rows'] == 1, second
    assert len(set(admissions)) == 2
    assert checkpoint_authentications == admissions[:1]
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (6,)


@pytest.mark.parametrize('changed', ['archive', 'signing-key'])
def test_idle_checkpoint_proof_refuses_changed_authenticated_input(
        conn, checkpoints, idle_checkpoint_proof, checkpoint_authentications, monkeypatch, changed):
    first = retention.maintain(conn, batch_rows=1, checkpoint_proof=idle_checkpoint_proof)
    assert first['deleted_acquisition_rows'] == 1, first
    assert idle_checkpoint_proof.witness is not None
    if changed == 'archive':
        corrupt_idle_archive(conn, checkpoints[1])
    else:
        monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'replacement-retention-key-' * 3)

    result = retention.maintain(conn, batch_rows=1, checkpoint_proof=idle_checkpoint_proof)
    assert len(set(checkpoint_authentications)) == 2
    assert result['status'] == 'RETRY', result
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (7,)


def test_idle_checkpoint_proof_refuses_archive_replaced_after_authentication(
        conn, checkpoints, idle_checkpoint_proof, monkeypatch):
    authenticate = retention._authenticate_checkpoints

    def racing_authentication(port):
        authenticate(port)
        with psycopg.connect(conn.info.dsn) as other:
            corrupt_idle_archive(other, checkpoints[1])

    monkeypatch.setattr(retention, '_authenticate_checkpoints', racing_authentication)
    result = retention.maintain(conn, batch_rows=1, checkpoint_proof=idle_checkpoint_proof)
    assert result['status'] == 'RETRY', result
    assert idle_checkpoint_proof.witness is None
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (8,)


def test_private_pass_rolls_back_late_step_and_retains_committed_progress(conn, monkeypatch):
    stage(conn, rows=400)
    step = retention._acquisition_step
    clock = 1000.0
    deadlines = []

    def make_second_step_late(port, progress, *, batch_rows):
        nonlocal clock
        result = step(port, progress, batch_rows=batch_rows)
        deadlines.append(port.deadline)
        if len(deadlines) == 1:
            clock += .1
        else:
            clock = deadlines[0] + .01
        return result

    monkeypatch.setattr(retention, 'time', SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(retention, '_acquisition_step', make_second_step_late)
    result = retention.maintain(conn)
    assert deadlines == [1000.5, 1000.5]
    assert result['status'] == 'RETRY'
    assert result['class_errors'] == {'5': 'RetentionBudgetExpired'}
    assert result['deleted_acquisition_rows'] == 128
    assert result['progress_made']
    assert conn.execute('SELECT count(*) FROM sentinel_acquisition_prices').fetchone() == (272,)
    cursor = retention._read_progress(conn)
    assert (cursor.acquisition_after, cursor.acquisition_batches_left, cursor.next_class) == (
        'e' * 64, 0, 6)


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
