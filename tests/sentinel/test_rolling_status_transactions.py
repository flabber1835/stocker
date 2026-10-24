"""Real PG proof ownership; canonical-book correctness is composed separately."""
from contextlib import contextmanager
import inspect
from types import SimpleNamespace

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from sentinel import committed_read, structural_verification
from sentinel.execution.journal import WRITER_LOCK_KEY
from sentinel.feed import publication, readiness_scope
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401


@pytest.fixture
def material(conn):
    conn.execute('CREATE TABLE status_transaction_fixture(value text NOT NULL)')
    conn.execute("INSERT INTO status_transaction_fixture VALUES('committed')")
    conn.commit()
    return conn


def _mode(conn):
    return (conn.execute('SHOW transaction_isolation').fetchone()[0],
            conn.execute('SHOW transaction_read_only').fetchone()[0])


def _caller_work(conn):
    conn.execute("UPDATE status_transaction_fixture SET value='caller-uncommitted'")
    conn.execute("SET LOCAL application_name='caller-owned-status-transaction'")
    return conn.execute('SELECT txid_current()').fetchone()[0]


def _unchanged_caller(conn, transaction):
    assert conn.info.transaction_status == TransactionStatus.INTRANS
    assert conn.execute('SELECT txid_current()').fetchone()[0] == transaction
    assert conn.execute('SELECT value FROM status_transaction_fixture').fetchone()[0] == 'caller-uncommitted'
    assert conn.execute('SHOW application_name').fetchone()[0] == 'caller-owned-status-transaction'


def test_idle_status_proof_owns_repeatable_read_readonly_and_returns_idle(material):
    conn = material
    with committed_read.proof_connection(conn) as proof:
        assert proof is conn
        assert _mode(proof) == ('repeatable read','on')
        assert proof.execute('SELECT value FROM status_transaction_fixture').fetchone()[0] == 'committed'
    assert conn.info.transaction_status == TransactionStatus.IDLE
    assert not conn.closed


def test_borrowed_status_reads_committed_target_without_ending_caller_work(material):
    conn = material
    transaction = _caller_work(conn)
    with committed_read.proof_connection(conn) as proof:
        assert proof.info.backend_pid != conn.info.backend_pid
        assert proof.info.dbname == conn.info.dbname
        assert _mode(proof) == ('repeatable read','on')
        assert proof.execute('SELECT value FROM status_transaction_fixture').fetchone()[0] == 'committed'
    assert proof.closed
    _unchanged_caller(conn,transaction)
    conn.rollback()
    assert conn.execute('SELECT value FROM status_transaction_fixture').fetchone()[0] == 'committed'


@pytest.mark.parametrize('refusal',['python','sql'])
def test_refused_borrowed_proof_closes_only_itself(material,refusal):
    conn = material
    transaction = _caller_work(conn)
    expected = RuntimeError if refusal == 'python' else psycopg.errors.ReadOnlySqlTransaction
    with pytest.raises(expected):
        with committed_read.proof_connection(conn) as proof:
            assert _mode(proof) == ('repeatable read','on')
            if refusal == 'python':
                raise RuntimeError('isolated proof refusal')
            proof.execute("INSERT INTO status_transaction_fixture VALUES('forbidden')")
    assert proof.closed
    _unchanged_caller(conn,transaction)


@contextmanager
def _actual_pin(conn):
    """Genuine session pin; tiny subject is only this ownership fixture."""
    conn.execute('SELECT pg_advisory_lock_shared(%s)',(publication.CORPUS_LOCK_KEY,))
    subject = SimpleNamespace(evidence={'rolling_snapshot':{}},
        to_dict=lambda:{'schema':'isolated-status-transaction-pin/1'})
    try:
        with readiness_scope.pinned(conn,subject):
            yield
    finally:
        conn.execute('SELECT pg_advisory_unlock_shared(%s)',(publication.CORPUS_LOCK_KEY,))


def test_original_publication_pin_loss_during_proof_refuses_without_rollback(material):
    conn = material
    transaction = _caller_work(conn)
    with _actual_pin(conn):
        with pytest.raises(publication.CorpusIncoherent,match='PIN_LOST'):
            with committed_read.proof_connection(conn) as proof:
                assert proof.info.backend_pid != conn.info.backend_pid
                assert conn.execute('SELECT pg_advisory_unlock_shared(%s)',
                    (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
    _unchanged_caller(conn,transaction)


@pytest.mark.parametrize('idle_owner',[False,True])
@pytest.mark.parametrize('refusal',[False,True])
def test_pin_checks_leave_initially_idle_input_idle_and_preserve_original_owner(material,idle_owner,refusal):
    owner=material
    transaction=None if idle_owner else _caller_work(owner)
    other=None
    try:
        with _actual_pin(owner):
            if idle_owner:
                # A session advisory lock survives the end of this read. The
                # same backend remains the original active scope owner.
                owner.rollback()
                supplied=owner
            else:
                other=psycopg.connect(owner.info.dsn)
                supplied=other
            assert supplied.info.transaction_status==TransactionStatus.IDLE
            def observe():
                with committed_read.proof_connection(supplied) as proof:
                    assert proof.info.backend_pid!=supplied.info.backend_pid
                    assert _mode(proof)==('repeatable read','on')
                    assert proof.execute('SELECT value FROM status_transaction_fixture').fetchone()[0]=='committed'
                    if refusal:
                        raise RuntimeError('private committed proof refused')
            if refusal:
                with pytest.raises(RuntimeError,match='private committed proof refused'):
                    observe()
            else:
                observe()
            assert supplied.info.transaction_status==TransactionStatus.IDLE, \
                'pin checking left initially idle input in a transaction'
            if transaction is not None:
                _unchanged_caller(owner,transaction)
            else:
                assert owner.info.transaction_status==TransactionStatus.IDLE
            # Check through an independent observer so the ownership assertion
            # above is not itself changed by a verification SELECT.
            with psycopg.connect(owner.info.dsn) as observer:
                key=publication.CORPUS_LOCK_KEY
                assert observer.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                    "AND pid=%s AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                    "AND classid=%s AND objid=%s AND objsubid=1 AND mode='ShareLock' AND granted)",
                    (owner.info.backend_pid,key>>32,key&0xffffffff)).fetchone()[0], \
                    'committed proof released the original owner session pin'
    finally:
        if other is not None:
            other.close()
        owner.rollback()


@pytest.mark.parametrize('removed',['capture','recheck'])
def test_removing_pin_check_transaction_context_leaks_idle_input_and_is_detected(material,monkeypatch,removed):
    old,new=(('    with conn.transaction(force_rollback=True):\n        pin = readiness_scope.capture(conn)',
              '    pin = readiness_scope.capture(conn)') if removed=='capture' else
             ('            with conn.transaction(force_rollback=True):\n                readiness_scope.require_token(conn,pin)',
              '            readiness_scope.require_token(conn,pin)'))
    _mutated(monkeypatch,old,new)
    with pytest.raises(AssertionError,match='pin checking left initially idle input'):
        test_pin_checks_leave_initially_idle_input_idle_and_preserve_original_owner(material,False,False)


def test_private_structural_reuse_checks_original_writer_on_fresh_backend(material):
    conn = material
    transaction = _caller_work(conn)
    with _actual_pin(conn):
        conn.execute('SELECT pg_advisory_lock(%s)',(WRITER_LOCK_KEY,))
        try:
            with structural_verification.callback(conn):
                with committed_read.proof_connection(conn) as proof:
                    value = structural_verification.material(proof,slot='rolling-checkpoint',
                        key='isolated-transaction-ownership',
                        load=lambda:proof.execute('SELECT value FROM status_transaction_fixture').fetchone()[0])
                    assert value == 'committed'
                    assert conn.execute('SELECT pg_advisory_unlock(%s)',(WRITER_LOCK_KEY,)).fetchone()[0]
                    with pytest.raises(structural_verification.VerificationScopeRefused,match='WRITER_LOCK_LOST'):
                        structural_verification.material(proof,slot='rolling-checkpoint',
                            key='isolated-transaction-ownership',load=lambda:pytest.fail('lost owner reloaded material'))
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)',(WRITER_LOCK_KEY,))
    _unchanged_caller(conn,transaction)


def _mutated(monkeypatch,old,new):
    source = inspect.getsource(committed_read.proof_connection)
    assert source.count(old) == 1
    namespace = {}
    exec(compile(source.replace(old,new),'isolated-status-ownership-mutant','exec'),vars(committed_read),namespace)
    monkeypatch.setattr(committed_read,'proof_connection',namespace['proof_connection'])


def test_missing_original_pin_recheck_is_killed_by_real_midproof_loss(material,monkeypatch):
    _mutated(monkeypatch,'readiness_scope.require_token(conn,pin)','pass')
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_original_publication_pin_loss_during_proof_refuses_without_rollback(material)


def test_missing_readonly_mode_is_killed_by_real_owned_proof(material,monkeypatch):
    _mutated(monkeypatch,"proof.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')",'pass')
    with pytest.raises(AssertionError):
        test_idle_status_proof_owns_repeatable_read_readonly_and_returns_idle(material)


def _reader(monkeypatch, kind, caller, *, refuse=False):
    """Replace only the canonical material leaf; ownership and schemas stay real.

    Complete canonical closure is exercised by the composed current workflow
    and the historical retained-attestation test. This tiny real SQL subject
    isolates each public reader's connection/transaction contract.
    """
    from sentinel import rolling_daily, rolling_initialization
    from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending
    from sentinel.panel import shadow_source_wait

    def material(proof):
        assert _mode(proof) == ('repeatable read', 'on')
        assert proof.info.dbname == caller.info.dbname
        value = proof.execute('SELECT value FROM status_transaction_fixture').fetchone()[0]
        if refuse:
            raise RuntimeError('canonical material refusal')
        return value

    if kind == 'historical':
        def historical(proof, **_):
            return material(proof)
        monkeypatch.setattr(shadow_source_wait, '_read_committed', historical)
        refusal = RuntimeError('typed historical display request')
        refusal.__cause__ = RollingSourceFrontierPending('source frontier')
        return lambda: shadow_source_wait.read(caller, refusal,
            observation_id='ownership', starting_cash='50000', now=None)

    monkeypatch.setattr(rolling_initialization, '_context', lambda *_: {})
    if kind == 'initialization':
        monkeypatch.setattr(rolling_initialization.checkpoints, 'read', material)
        monkeypatch.setattr(rolling_initialization.checkpoints, 'restore',
                            lambda _proof, checkpoint, **_: checkpoint)
        return lambda: rolling_initialization.resume(caller,
            observation_id='ownership', starting_cash='50000')
    def daily(proof, _context):
        return None, None, material(proof)
    monkeypatch.setattr(rolling_daily.checkpoints, 'load', daily)
    return lambda: rolling_daily.resume(caller,
        observation_id='ownership', starting_cash='50000')


@pytest.mark.parametrize('kind', ['initialization', 'daily', 'historical'])
@pytest.mark.parametrize('borrowed', [False, True])
def test_public_committed_readers_preserve_transaction_ownership(material, monkeypatch, kind, borrowed):
    caller = material
    reader = _reader(monkeypatch, kind, caller)
    transaction = _caller_work(caller) if borrowed else None
    assert reader() == 'committed'
    if borrowed:
        _unchanged_caller(caller, transaction)
    else:
        assert caller.info.transaction_status == TransactionStatus.IDLE
        assert not caller.closed


@pytest.mark.parametrize('kind', ['initialization', 'daily', 'historical'])
def test_public_committed_reader_refusal_does_not_end_caller_work(material, monkeypatch, kind):
    caller = material
    reader = _reader(monkeypatch, kind, caller, refuse=True)
    transaction = _caller_work(caller)
    with pytest.raises(RuntimeError, match='canonical material refusal'):
        reader()
    _unchanged_caller(caller, transaction)
