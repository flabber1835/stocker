"""Independent read-only attempts with real PostgreSQL row and pin witnesses."""
from contextlib import contextmanager
import multiprocessing
import inspect
from types import SimpleNamespace

import pytest

from sentinel import operational_ddl_epoch, shadow_status_material as material
from sentinel.feed import publication, readiness_scope, store
from tests.sentinel.test_dashboard_review import conn, pg  # noqa: F401

PUB = publication.Publication(1, None, 'private', '2031-04-21', '2031-04-21',
                              {'rolling_snapshot': {'candidate_id': 'private'}})
KEY = {'observation_id': 'private', 'runtime': {'source': 'exact'}}


@pytest.fixture
def checkpoint(conn):
    operational_ddl_epoch.install(conn)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('rolling-unit-checkpoint','2031-04-21','{\"value\":1}')")
    conn.commit()
    return material.StatusMaterialMemo()


@contextmanager
def pinned(dsn, *, read_only=True, pub=PUB):
    with store.connect(dsn) as reader:
        reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ '+
                       ('READ ONLY' if read_only else 'READ WRITE'))
        reader.execute('SELECT pg_advisory_lock_shared(%s)', (publication.CORPUS_LOCK_KEY,))
        with readiness_scope.pinned(reader, pub):
            yield reader


def check(dsn, memo, calls, *, key=KEY):
    with pinned(dsn) as reader:
        def load():
            calls.append(True)
            return reader.execute("SELECT state FROM sentinel_processed_sessions "
                                  "WHERE cursor_name='rolling-unit-checkpoint'").fetchone()[0]
        return memo.measure(reader, key, load)


def test_separate_transactions_reuse_only_detached_canonical_material(conn, checkpoint):
    calls = []
    first = check(conn.info.dsn, checkpoint, calls)
    first['value'] = 999
    assert check(conn.info.dsn, checkpoint, calls) == {'value': 1}
    assert len(calls) == 1


def changed_row_case(conn, checkpoint, monkeypatch, *, removed=False):
    calls = []
    if removed:
        original = material._witness
        retained = []
        def frozen(*args):
            if not retained:
                retained.append(original(*args))
            return retained[0]
        monkeypatch.setattr(material, '_witness', frozen)
    check(conn.info.dsn, checkpoint, calls)
    conn.execute("UPDATE sentinel_processed_sessions SET state='{\"value\":2}' "
                 "WHERE cursor_name='rolling-unit-checkpoint'")
    conn.commit()
    assert check(conn.info.dsn, checkpoint, calls) == {'value': 2}, 'changed checkpoint was reused'
    assert len(calls) == 2


def test_changed_checkpoint_requires_a_new_canonical_load(conn, checkpoint, monkeypatch):
    changed_row_case(conn, checkpoint, monkeypatch)


def test_removed_row_version_guard_has_an_executed_falsifier(conn, checkpoint, monkeypatch):
    with pytest.raises(AssertionError, match='changed checkpoint was reused'):
        changed_row_case(conn, checkpoint, monkeypatch, removed=True)


@pytest.mark.parametrize('clock_index', [0, 1])
def test_original_scrub_clock_is_never_renewed_by_hits(conn, checkpoint, monkeypatch, clock_index):
    clock = [100., 200.]
    monkeypatch.setattr(material, '_clock', lambda: tuple(clock))
    calls = []
    check(conn.info.dsn, checkpoint, calls)
    clock[clock_index] += material.SCRUB_SECONDS-1
    assert check(conn.info.dsn, checkpoint, calls) == {'value': 1} and len(calls) == 1
    clock[clock_index] += 1
    assert check(conn.info.dsn, checkpoint, calls) == {'value': 1} and len(calls) == 2
    clock[clock_index] -= 2000
    check(conn.info.dsn, checkpoint, calls)
    assert len(calls) == 3


def test_context_publication_and_ddl_changes_invalidate(conn, checkpoint):
    calls = []
    check(conn.info.dsn, checkpoint, calls)
    check(conn.info.dsn, checkpoint, calls, key={**KEY, 'runtime': {'source': 'new'}})
    assert len(calls) == 2
    with pinned(conn.info.dsn, pub=publication.Publication(2, 1, 'new', '2031-04-21', '2031-04-21',
                                                         PUB.evidence)) as reader:
        checkpoint.measure(reader, KEY, lambda: calls.append(True) or {'value': 1})
    assert len(calls) == 3
    conn.execute('ALTER TABLE sentinel_processed_sessions ADD COLUMN cache_test_guard text')
    conn.commit()
    check(conn.info.dsn, checkpoint, calls)
    assert len(calls) == 4


def test_no_cursor_namespace_can_hide_changed_foreign_lineage(conn, checkpoint):
    calls = []
    check(conn.info.dsn, checkpoint, calls)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('broker-observation:v4:private','2031-04-21','{\"wealth_core\":{}}')")
    conn.commit()
    check(conn.info.dsn, checkpoint, calls)
    assert len(calls) == 2


def test_assigned_and_write_transactions_cannot_reuse_or_seed(conn, checkpoint):
    calls = []
    for _ in range(2):
        with pinned(conn.info.dsn, read_only=False) as reader:
            assert checkpoint.measure(reader, KEY, lambda: calls.append(True) or 42) == 42
    assert len(calls) == 2 and bytes(checkpoint.slot[:4]) == b'\0'*4
    with pinned(conn.info.dsn) as reader:
        reader.execute('SELECT pg_current_xact_id()')
        for _ in range(2):
            assert checkpoint.measure(reader, KEY, lambda: calls.append(True) or 42) == 42
    assert len(calls) == 4 and bytes(checkpoint.slot[:4]) == b'\0'*4
    with pinned(conn.info.dsn) as reader:
        reader.execute('SELECT pg_advisory_unlock_shared(%s)', (publication.CORPUS_LOCK_KEY,))
        with pytest.raises(publication.CorpusIncoherent, match='PIN_LOST'):
            checkpoint.measure(reader, KEY, lambda: pytest.fail('lost pin reached canonical work'))
    with store.connect(conn.info.dsn) as reader:
        assert checkpoint.measure(reader, KEY, lambda: 17) == 17
    assert bytes(checkpoint.slot[:4]) == b'\0'*4


@pytest.mark.parametrize('damage', ['header', 'payload', 'owner'])
def test_untrusted_private_bytes_never_reach_pickle_decoder(checkpoint, monkeypatch, damage):
    checkpoint._store('subject', material._clock(), {'trusted': True})
    memory = memoryview(checkpoint.slot).cast('B')
    size = int.from_bytes(memory[:4], 'big')
    if damage == 'header':
        memory[8] ^= 1
    elif damage == 'payload':
        memory[7+size] ^= 1
    else:
        checkpoint.owner = 'different-owner'
    monkeypatch.setattr(material.pickle, 'loads', lambda *_: pytest.fail('untrusted pickle decoded'))
    assert checkpoint._read('subject', material._clock()) is None


def test_removed_authentication_has_an_executed_decoder_falsifier(checkpoint, monkeypatch):
    monkeypatch.setattr(material.hmac, 'compare_digest', lambda *_: True)
    with pytest.raises(pytest.fail.Exception, match='untrusted pickle decoded'):
        test_untrusted_private_bytes_never_reach_pickle_decoder(checkpoint, monkeypatch, 'owner')


def prior_epoch_case(monkeypatch):
    class Port:
        info = SimpleNamespace(backend_pid=7)
        xmax = 4294967296+50
        def execute(self, sql):
            if 'current_setting' in sql:
                assert 'pg_current_xact_id_if_assigned() IS NULL' in sql
                row = ('repeatable read','on','origin',True,True,'system','database','started',self.xmax)
                return SimpleNamespace(fetchone=lambda: row)
            if 'pg_class' in sql:
                return SimpleNamespace(fetchone=lambda: (1,2,3,4))
            return SimpleNamespace(fetchall=lambda: [('rolling-checkpoint','2031-04-21',1,'100','(0,1)')])
    port = Port()
    pin = SimpleNamespace(owner=port, backend_pid=7, publication='original')
    monkeypatch.setattr(readiness_scope, 'capture', lambda _: pin)
    monkeypatch.setattr(readiness_scope, 'require_token', lambda *_: None)
    monkeypatch.setattr(operational_ddl_epoch, 'current', lambda _: ('incarnation',1))
    assert material._witness(port, KEY) is None, 'prior-epoch frozen tuple admitted'
    port.xmax += 51
    assert isinstance(material._witness(port, KEY), str)


def test_prior_epoch_frozen_tuple_cannot_seed_reusable_material(monkeypatch):
    prior_epoch_case(monkeypatch)


def test_removed_epoch_guard_has_an_executed_falsifier(monkeypatch):
    source = inspect.getsource(material._witness)
    mutated = source.replace('or any(int(row[3]) >= low_xmax for row in rows)', 'or False')
    assert mutated != source
    namespace = dict(vars(material))
    exec(compile(mutated, '<private-epoch-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(material, '_witness', namespace['_witness'])
    with pytest.raises(AssertionError, match='prior-epoch frozen tuple admitted'):
        prior_epoch_case(monkeypatch)


def test_incomplete_and_oversized_results_are_not_admitted(conn, checkpoint, monkeypatch):
    with pinned(conn.info.dsn) as reader:
        for _ in range(2):
            with pytest.raises(ValueError, match='canonical failure'):
                checkpoint.measure(reader, KEY, lambda: (_ for _ in ()).throw(ValueError('canonical failure')))
    assert bytes(checkpoint.slot[:4]) == b'\0'*4
    monkeypatch.setattr(material, 'MAX_BYTES', 8192)
    with pinned(conn.info.dsn) as reader:
        assert len(checkpoint.measure(reader, KEY, lambda: b'x'*10000)) == 10000
    assert bytes(checkpoint.slot[:4]) == b'\0'*4


def _child_read(dsn, memo, queue):
    calls = []
    result = check(dsn, memo, calls)
    queue.put((result, len(calls)))


def test_material_survives_owned_spawned_attempts(conn, checkpoint):
    context = multiprocessing.get_context('spawn')
    queue = context.Queue()
    try:
        for expected in (1, 0):
            child = context.Process(target=_child_read, args=(conn.info.dsn, checkpoint, queue))
            child.start()
            try:
                assert queue.get(timeout=20) == ({'value': 1}, expected)
                child.join(5)
                assert child.exitcode == 0
            finally:
                if child.is_alive(): child.kill(); child.join(5)
                child.close()
    finally:
        queue.close(); queue.join_thread()


def test_rolling_hook_keeps_current_owner_gate_and_standalone_canonical(conn, checkpoint, monkeypatch):
    from sentinel import rolling_runtime, runtime_admission
    context = dict(KEY, controller=SimpleNamespace(to_dict=lambda: {'rule': 'unchanged'}))
    calls, gates = [], []
    bound = SimpleNamespace(runtime_identity={'original': True})
    monkeypatch.setattr(rolling_runtime, '_status_closure',
                        lambda *_: calls.append(True) or (bound, None, {'canonical': True}, None, None))
    monkeypatch.setattr(runtime_admission, '_require_backed_owner_scope',
                        lambda *args: gates.append(True))
    token = material.current_memo.set(checkpoint)
    try:
        for _ in range(2):
            with pinned(conn.info.dsn) as reader:
                assert rolling_runtime._closure(reader, context, status_only=True)[2] == {'canonical': True}
        assert len(calls) == 1 and len(gates) == 2
        def refuse(*_): raise ValueError('fresh authority refused')
        monkeypatch.setattr(runtime_admission, '_require_backed_owner_scope', refuse)
        with pinned(conn.info.dsn) as reader, pytest.raises(ValueError, match='fresh authority'):
            rolling_runtime._closure(reader, context, status_only=True)
        assert len(calls) == 1
    finally:
        material.current_memo.reset(token)
    monkeypatch.setattr(runtime_admission, '_require_backed_owner_scope', lambda *_: None)
    with pinned(conn.info.dsn) as reader:
        rolling_runtime._closure(reader, context, status_only=True)
    assert len(calls) == 2
