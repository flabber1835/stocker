"""Real row changes must invalidate display-only intent reuse."""
from copy import deepcopy
from datetime import date
import inspect
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from sentinel import dual_plan_authority as authority
from sentinel.panel import intent_memo as display
from tests.sentinel.test_dashboard_review import conn, pg


def value(plan='private-plan'):
    raw=dict(schema=authority.SCHEMA,plan_id=plan,plan_fingerprint='b'*64,
        decision_session='2031-04-21',shadow_record_sha256='c'*64,
        shadow_runtime_authority_sha256='d'*64,shadow_state={'large_private_fixture':'x'*300000},
        publication={},account_snapshot={},marks={},tickers={'one':'ONE'},
        broker_observation=dict(completeness='COMPLETE',account_identity={'broker':'alpaca',
            'account_id':'qualification-account'},observed_at='2031-04-21T20:00:00+00:00',
            positions=[{'instrument':{'security_id':'one'},'quantity':'10'}]))
    raw['authority_sha256']=authority._sha256(raw)
    return raw


def insert(conn, raw):
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)',
                 (authority._cursor(raw['plan_id']),raw['decision_session'],json.dumps(raw)))
    conn.commit()


def test_repeated_display_reuses_only_small_validated_projection(conn,monkeypatch):
    raw=value();insert(conn,raw);calls=[];original=authority.load_authority
    def counted(*args,**kwargs):
        calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(authority,'load_authority',counted)
    memo=display.IntentMemo();first=memo.read(conn,plan_id=raw['plan_id'])
    assert first==memo.read(conn,plan_id=raw['plan_id']) and len(calls)==1
    assert 'shadow_state' not in first and len(json.dumps(first))<2000
    first['tickers']['one']='MUTATED'
    assert memo.read(conn,plan_id=raw['plan_id'])['tickers']['one']=='ONE'


def tamper_case(conn,monkeypatch,*,removed=False):
    raw=value();insert(conn,raw)
    if removed:
        original=display.row_version
        version=original(conn,raw['plan_id'])
        monkeypatch.setattr(display,'row_version',lambda *_args:version)
    memo=display.IntentMemo();memo.read(conn,plan_id=raw['plan_id'])
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{tickers,one}','\"FORGED\"') "
                 'WHERE cursor_name=%s',(authority._cursor(raw['plan_id']),));conn.commit()
    with pytest.raises(authority.DualPlanAuthorityRefused,match='digest'):
        memo.read(conn,plan_id=raw['plan_id'])


def test_changed_row_with_unchanged_claimed_digest_never_hits_memo(conn,monkeypatch):
    tamper_case(conn,monkeypatch)


def test_removed_row_version_guard_is_detected(conn,monkeypatch):
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        tamper_case(conn,monkeypatch,removed=True)


def test_delete_and_reinsert_is_revalidated(conn):
    raw=value();insert(conn,raw);memo=display.IntentMemo();memo.read(conn,plan_id=raw['plan_id'])
    conn.execute('DELETE FROM sentinel_processed_sessions');conn.commit()
    assert memo.read(conn,plan_id=raw['plan_id']) is None
    raw['tickers']['one']='NEW';raw.pop('authority_sha256');raw['authority_sha256']=authority._sha256(raw)
    insert(conn,raw)
    assert memo.read(conn,plan_id=raw['plan_id'])['tickers']['one']=='NEW'


def test_clock_regression_requires_full_validation(conn,monkeypatch):
    raw=value();insert(conn,raw);clock=[100.0];memo=display.IntentMemo(clock=lambda:clock[0])
    memo.read(conn,plan_id=raw['plan_id'])
    def refused(*_args,**_kwargs):
        raise RuntimeError('full validation required')
    monkeypatch.setattr(authority,'load_authority',refused)
    clock[0]-=1
    with pytest.raises(RuntimeError,match='full validation'):
        memo.read(conn,plan_id=raw['plan_id'])


@pytest.mark.parametrize('idle_seconds', [60, 61, 3600, 86400])
def test_idle_unchanged_physical_row_keeps_its_validated_projection(conn, monkeypatch, idle_seconds):
    raw=value();insert(conn,raw);clock=[100.0];calls=[];original=authority.load_authority
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(authority, 'load_authority', counted)
    memo=display.IntentMemo(clock=lambda:clock[0]);first=memo.read(conn,plan_id=raw['plan_id'])
    clock[0]+=idle_seconds
    assert memo.read(conn,plan_id=raw['plan_id'])==first
    assert len(calls)==1, 'idle time cannot force validation of an unchanged immutable row'
    assert first['broker_observation']['observed_at']=='2031-04-21T20:00:00+00:00'


def test_long_idle_never_hides_changed_bytes_retaining_a_claimed_digest(conn):
    raw=value();insert(conn,raw);clock=[100.0];memo=display.IntentMemo(clock=lambda:clock[0])
    memo.read(conn,plan_id=raw['plan_id']);clock[0]+=86400
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{tickers,one}','\"FORGED\"')")
    conn.commit()
    with pytest.raises(authority.DualPlanAuthorityRefused, match='digest'):
        memo.read(conn,plan_id=raw['plan_id'])


@pytest.mark.parametrize('name', ['SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST',
                                 'SENTINEL_STATE_DIR'])
def test_configuration_change_still_requires_canonical_validation(conn, monkeypatch, name):
    raw=value();insert(conn,raw);memo=display.IntentMemo();memo.read(conn,plan_id=raw['plan_id'])
    monkeypatch.setenv(name, 'changed-fixture')
    def refused(*_args, **_kwargs):
        raise RuntimeError('full validation required')
    monkeypatch.setattr(authority, 'load_authority', refused)
    with pytest.raises(RuntimeError, match='full validation'):
        memo.read(conn,plan_id=raw['plan_id'])


def test_row_version_change_during_validation_refuses(conn,monkeypatch):
    raw=value();insert(conn,raw);original=authority.load_authority
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        conn.execute('UPDATE sentinel_processed_sessions SET state=state');return result
    monkeypatch.setattr(authority,'load_authority',changed)
    with pytest.raises(authority.DualPlanAuthorityRefused,match='during canonical'):
        display.IntentMemo().read(conn,plan_id=raw['plan_id'])


@pytest.mark.parametrize('field',[0,1,2,3,4,5,6,7,8])
def test_physical_database_relation_tuple_and_epoch_cannot_cross_memo(conn,monkeypatch,field):
    raw=value();insert(conn,raw);memo=display.IntentMemo();memo.read(conn,plan_id=raw['plan_id'])
    original=display.row_version
    def changed(*args):
        stamp=list(original(*args));stamp[field]='foreign';return tuple(stamp)
    monkeypatch.setattr(display,'row_version',changed)
    def refused(*args,**kwargs):
        raise RuntimeError('full validation required')
    monkeypatch.setattr(authority,'load_authority',refused)
    with pytest.raises(RuntimeError,match='full validation'):
        memo.read(conn,plan_id=raw['plan_id'])


class NativeSnapshotPort:
    """Synthetic MVCC metadata, not a substitute for the real-PG cases below."""

    def __init__(self, *, raw_xmin=100, snapshot_xmax=4294967346, assigned=False):
        self.info = SimpleNamespace(dsn='credential-free-native-witness-fixture')
        self.raw_xmin = raw_xmin
        self.snapshot_xmax = snapshot_xmax
        self.assigned = assigned

    def execute(self, statement, parameters):
        # Keep the safety predicate in the actual native witness query. In
        # particular, checking assignment must never assign an XID to a reader.
        assert 'WITH snapshot AS MATERIALIZED' in statement
        assert statement.count('pg_current_snapshot()') == 1
        assert 'pg_current_xact_id_if_assigned() IS NULL' in statement
        assert 'pg_current_xact_id()' not in statement
        assert 'mod(snapshot.xmax,4294967296)' in statement
        assert 'state->' not in statement
        reusable = not self.assigned and self.raw_xmin < self.snapshot_xmax % 4294967296
        version = ('2031-04-21', 100, str(self.raw_xmin), '(0,1)', 101, 102,
                   'fixture-system', '2031-04-21T00:00:00+00:00',
                   str(self.snapshot_xmax // 4294967296), reusable)
        return SimpleNamespace(fetchone=lambda: version)


def frozen_prior_epoch_case(monkeypatch, *, obsolete_epoch_only=False):
    port = NativeSnapshotPort(raw_xmin=100, snapshot_xmax=4294967296 + 50)
    current = [value()]
    calls = []
    def canonical(*args, **kwargs):
        calls.append(True)
        return deepcopy(current[0])
    monkeypatch.setattr(authority, 'load_authority', canonical)
    if obsolete_epoch_only:
        original = display.row_version
        monkeypatch.setattr(display, 'row_version', lambda *args: original(*args)[:9])
        monkeypatch.setattr(display, '_reusable', lambda stamp: stamp is not None
                            and len(stamp) == 9 and type(stamp[4]) is int and stamp[4] > 0)
    memo = display.IntentMemo()
    assert memo.read(port, plan_id=current[0]['plan_id'])['tickers']['one'] == 'ONE'
    admitted_before_counter_passed = len(memo.entries)
    # A frozen tuple from the previous epoch had raw xmin100 while this epoch
    # was only at50. Later, a new committed tuple can reuse xmin100 and its slot
    # before the full-XID epoch changes. It must never inherit the old projection.
    port.snapshot_xmax = 4294967296 + 101
    current[0] = value()
    current[0]['tickers']['one'] = 'NEW'
    assert memo.read(port, plan_id=current[0]['plan_id'])['tickers']['one'] == 'NEW', (
        'prior-epoch frozen tuple masked newly committed authority bytes')
    assert len(calls) == 2 and admitted_before_counter_passed == 0
    assert len(memo.entries) == 1


def test_previous_epoch_frozen_raw_xmin_cannot_mask_same_epoch_reuse(monkeypatch):
    frozen_prior_epoch_case(monkeypatch)


def test_obsolete_epoch_only_admission_has_an_executed_aba_falsifier(monkeypatch):
    with pytest.raises(AssertionError, match='prior-epoch frozen tuple masked'):
        frozen_prior_epoch_case(monkeypatch, obsolete_epoch_only=True)


def test_same_epoch_counter_progress_keeps_hit_but_epoch_transition_revalidates(monkeypatch):
    port = NativeSnapshotPort(snapshot_xmax=4294967296 + 101)
    calls = []
    def canonical(*args, **kwargs):
        calls.append(True)
        return value()
    monkeypatch.setattr(authority, 'load_authority', canonical)
    memo = display.IntentMemo()
    first = memo.read(port, plan_id='private-plan')
    port.snapshot_xmax = 4294967296 + 200
    assert memo.read(port, plan_id='private-plan') == first and len(calls) == 1
    port.snapshot_xmax = 2 * 4294967296 + 101
    assert memo.read(port, plan_id='private-plan') == first and len(calls) == 2


@pytest.mark.parametrize('reuse', [False, None, 1, 'true', 't'])
def test_only_actual_boolean_true_allows_hit_or_admission(monkeypatch, reuse):
    port = NativeSnapshotPort(snapshot_xmax=4294967296 + 101)
    original = display.row_version
    def witness(*args):
        stamp = list(original(*args))
        stamp[9] = reuse
        return tuple(stamp)
    monkeypatch.setattr(display, 'row_version', witness)
    calls = []
    monkeypatch.setattr(authority, 'load_authority', lambda *a, **k: calls.append(True) or value())
    memo = display.IntentMemo()
    for _ in range(2):
        assert memo.read(port, plan_id='private-plan')['tickers']['one'] == 'ONE'
    assert len(calls) == 2 and not memo.entries, 'nonreusable witness entered the process memo'


def test_removed_boolean_admission_guard_has_an_executed_falsifier(monkeypatch):
    monkeypatch.setattr(display, '_reusable', lambda stamp: stamp is not None
                        and len(stamp) == 10 and type(stamp[4]) is int and stamp[4] > 0)
    with pytest.raises(AssertionError, match='nonreusable witness entered'):
        test_only_actual_boolean_true_allows_hit_or_admission(monkeypatch, False)


def assigned_writer_case(monkeypatch, *, top_level_only=False):
    port = NativeSnapshotPort(snapshot_xmax=4294967296 + 101, assigned=True)
    if top_level_only:
        original = display.row_version
        def incorrect_parent_only(*args):
            stamp = list(original(*args))
            # The child's tuple xmin100 differs from the assigned parent99.
            # Excluding only an exact parent-XID match wrongly admits the child.
            stamp[9] = port.raw_xmin != 99 and port.raw_xmin < port.snapshot_xmax % 4294967296
            return tuple(stamp)
        monkeypatch.setattr(display, 'row_version', incorrect_parent_only)
    calls = []
    monkeypatch.setattr(authority, 'load_authority', lambda *a, **k: calls.append(True) or value())
    memo = display.IntentMemo()
    memo.read(port, plan_id='private-plan')
    memo.read(port, plan_id='private-plan')
    assert len(calls) == 2 and not memo.entries, 'assigned child transaction entered the process memo'


def test_assigned_writer_is_canonical_and_uncached(monkeypatch):
    assigned_writer_case(monkeypatch)


def test_parent_xid_only_exclusion_has_an_executed_subtransaction_falsifier(monkeypatch):
    with pytest.raises(AssertionError, match='assigned child transaction entered'):
        assigned_writer_case(monkeypatch, top_level_only=True)


@pytest.mark.parametrize('filenode', [None, 0, -1, True, '101'])
def test_nonpositive_or_noninteger_physical_file_cannot_admit_a_projection(monkeypatch, filenode):
    port = NativeSnapshotPort(snapshot_xmax=4294967296 + 101)
    original = display.row_version
    def witness(*args):
        stamp = list(original(*args))
        stamp[4] = filenode
        return tuple(stamp)
    monkeypatch.setattr(display, 'row_version', witness)
    calls = []
    monkeypatch.setattr(authority, 'load_authority', lambda *a, **k: calls.append(True) or value())
    memo = display.IntentMemo()
    memo.read(port, plan_id='private-plan')
    memo.read(port, plan_id='private-plan')
    assert len(calls) == 2 and not memo.entries


@pytest.mark.parametrize('raw_xmin', [100, 101, 200])
def test_equal_or_ahead_raw_xmin_is_canonical_and_uncached(monkeypatch, raw_xmin):
    port = NativeSnapshotPort(raw_xmin=raw_xmin, snapshot_xmax=4294967296 + 100)
    calls = []
    monkeypatch.setattr(authority, 'load_authority', lambda *a, **k: calls.append(True) or value())
    memo = display.IntentMemo()
    memo.read(port, plan_id='private-plan')
    memo.read(port, plan_id='private-plan')
    assert len(calls) == 2 and not memo.entries


def replace_valid_authority(conn, raw, symbol):
    updated = deepcopy(raw)
    updated['tickers']['one'] = symbol
    updated.pop('authority_sha256')
    updated['authority_sha256'] = authority._sha256(updated)
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
                 (json.dumps(updated), authority._cursor(raw['plan_id'])))
    return updated


def counted_canonical(monkeypatch):
    calls = []
    original = authority.load_authority
    def canonical(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(authority, 'load_authority', canonical)
    return calls


def test_real_reader_witness_never_allocates_a_transaction_id(conn):
    raw = value()
    insert(conn, raw)
    assert conn.execute('SELECT pg_current_xact_id_if_assigned()').fetchone() == (None,)
    stamp = display.row_version(conn, raw['plan_id'])
    assert len(stamp) == 10 and stamp[9] is True and type(stamp[4]) is int and stamp[4] > 0
    assert conn.execute('SELECT pg_current_xact_id_if_assigned()').fetchone() == (None,)


@pytest.mark.parametrize('resolution', ['rollback', 'commit'])
def test_own_top_level_write_is_uncached_until_original_transaction_resolves(conn, monkeypatch, resolution):
    raw = value()
    insert(conn, raw)
    calls = counted_canonical(monkeypatch)
    memo = display.IntentMemo()
    assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == 'ONE'
    replace_valid_authority(conn, raw, 'UNCOMMITTED')
    assert conn.execute('SELECT pg_current_xact_id_if_assigned() IS NOT NULL').fetchone() == (True,)
    assert display.row_version(conn, raw['plan_id'])[9] is False
    for _ in range(2):
        assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == 'UNCOMMITTED'
    assert len(calls) == 3 and len(memo.entries) == 1
    getattr(conn, resolution)()
    expected = 'ONE' if resolution == 'rollback' else 'UNCOMMITTED'
    assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == expected
    assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == expected
    assert len(calls) == (3 if resolution == 'rollback' else 4)


@pytest.mark.parametrize('resolution', ['rollback', 'commit'])
def test_own_subtransaction_write_cannot_enter_process_memo(conn, monkeypatch, resolution):
    raw = value()
    insert(conn, raw)
    calls = counted_canonical(monkeypatch)
    memo = display.IntentMemo()
    memo.read(conn, plan_id=raw['plan_id'])
    conn.execute('SAVEPOINT private_writer')
    replace_valid_authority(conn, raw, 'CHILD')
    own_xid = conn.execute('SELECT pg_current_xact_id_if_assigned()::text').fetchone()[0]
    stamp = display.row_version(conn, raw['plan_id'])
    assert stamp[2] != own_xid, 'fixture must exercise a child XID rather than its top-level parent'
    assert stamp[9] is False
    for _ in range(2):
        assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == 'CHILD'
    assert len(calls) == 3 and len(memo.entries) == 1
    if resolution == 'rollback':
        conn.execute('ROLLBACK TO SAVEPOINT private_writer')
        assert display.row_version(conn, raw['plan_id'])[9] is False
        assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == 'ONE'
        assert len(calls) == 4
    conn.execute('RELEASE SAVEPOINT private_writer')
    conn.commit()
    expected = 'ONE' if resolution == 'rollback' else 'CHILD'
    assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == expected
    assert memo.read(conn, plan_id=raw['plan_id'])['tickers']['one'] == expected
    assert len(calls) == 4


def test_canonical_and_notification_loaders_stay_uncached():
    from sentinel import paper_plan_preview
    source=inspect.getsource(authority.load_authority)
    assert '_validate_payload' in source and 'intent_memo' not in source
    assert inspect.signature(paper_plan_preview.read).parameters['authority_loader'].default is None
    assert 'loader = authority_loader or dual_plan_authority.load_authority' in inspect.getsource(paper_plan_preview.read)


def test_dated_intent_private_read_cost(conn,record_property):
    raw=value();insert(conn,raw)
    started=time.perf_counter()
    for _ in range(5):
        authority.load_authority(conn,plan_id=raw['plan_id'])
    full=(time.perf_counter()-started)/5
    memo=display.IntentMemo();memo.read(conn,plan_id=raw['plan_id'])
    started=time.perf_counter()
    for _ in range(5):
        memo.read(conn,plan_id=raw['plan_id'])
    reuse=(time.perf_counter()-started)/5
    record_property('display_benchmark',dict(fixture_payload_bytes=len(json.dumps(raw)),
        full_validation_seconds=full,version_checked_reuse_seconds=reuse,reads_per_path=5))
    assert len(memo.entries)==1


def relation_rewrite_case(conn, monkeypatch, *, removed=False):
    raw=value();insert(conn,raw)
    original=display.row_version
    before=original(conn,raw['plan_id'])
    if removed:
        def without_file(*args):
            version=list(original(*args))
            version[4]=before[4]
            return tuple(version)
        monkeypatch.setattr(display,'row_version',without_file)
    calls=[];load=authority.load_authority
    def counted(*args,**kwargs):
        calls.append(1)
        return load(*args,**kwargs)
    monkeypatch.setattr(authority,'load_authority',counted)
    memo=display.IntentMemo();first=memo.read(conn,plan_id=raw['plan_id'])
    conn.commit();conn.autocommit=True
    try:
        conn.execute('VACUUM FULL sentinel_processed_sessions')
    finally:
        conn.autocommit=False
    after=original(conn,raw['plan_id'])
    assert before[4]!=after[4], 'private rewrite must change the physical file'
    assert before[:4]==after[:4] and before[5:]==after[5:], 'isolate the file guard'
    assert memo.read(conn,plan_id=raw['plan_id'])==first
    assert len(calls)==2, 'rewritten physical storage must be canonically revalidated'


def test_relation_rewrite_with_same_tuple_identifiers_is_revalidated(conn,monkeypatch):
    relation_rewrite_case(conn,monkeypatch)


def test_removed_physical_file_guard_is_detected(conn,monkeypatch):
    with pytest.raises(AssertionError,match='canonically revalidated'):
        relation_rewrite_case(conn,monkeypatch,removed=True)


def test_large_authority_hit_uses_metadata_buffers_without_toast(conn,monkeypatch,record_property):
    raw=value()
    # Deterministic high entropy prevents a tiny compressed representation from
    # hiding the TOAST work that the production-sized record demonstrated.
    raw['shadow_state']['large_private_fixture']=''.join(
        hashlib.sha256(i.to_bytes(4,'big')).hexdigest() for i in range(150000))
    raw.pop('authority_sha256');raw['authority_sha256']=authority._sha256(raw)
    insert(conn,raw)
    calls=[];load=authority.load_authority
    def counted(*args,**kwargs):
        calls.append(1)
        return load(*args,**kwargs)
    monkeypatch.setattr(authority,'load_authority',counted)
    memo=display.IntentMemo();first=memo.read(conn,plan_id=raw['plan_id'])
    assert memo.read(conn,plan_id=raw['plan_id'])==first and len(calls)==1

    class Capture:
        def execute(self,statement,parameters):
            self.statement,self.parameters=statement,parameters
            return conn.execute(statement,parameters)
    capture=Capture();display.row_version(capture,raw['plan_id'])
    def buffers(statement,parameters):
        result=conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+statement,parameters).fetchone()[0][0]
        plan=result['Plan']
        return plan.get('Shared Hit Blocks',0)+plan.get('Shared Read Blocks',0)
    metadata=buffers(capture.statement,capture.parameters)
    payload=buffers("SELECT state->>'authority_sha256' FROM sentinel_processed_sessions WHERE cursor_name=%s",
                    (authority._cursor(raw['plan_id']),))
    record_property('large_intent_buffers',dict(payload_bytes=len(json.dumps(raw)),
        metadata_buffers=metadata,payload_field_buffers=payload))
    assert payload>100, 'fixture must reproduce a genuinely out-of-line large read'
    assert metadata<20 and payload>metadata*20, 'hit witness must not fetch the authority TOAST value'
