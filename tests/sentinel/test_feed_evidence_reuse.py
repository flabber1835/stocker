"""Display integrity reuse has an exact subject, a fixed age and no verdict."""
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel.feed import publication, rolling_store
from sentinel.panel import feed_display as display, read_projection

NOW=datetime(2031,4,21,20,tzinfo=timezone.utc)
META=('db-oid','postmaster',0,'relation','filenode','toast','toast-file','xmin','ctid',True,True,1024)


@pytest.fixture(autouse=True)
def private_proofs():
    display._BYTE_PROOFS.clear()
    yield
    display._BYTE_PROOFS.clear()


class Connection:
    def __init__(self):
        self.row=META
        self.reads=0
    def execute(self, statement, params=()):
        assert 'octet_length(e.canonical_payload)' in statement
        self.reads+=1
        return SimpleNamespace(fetchone=lambda:self.row)


def setup(monkeypatch):
    clocks=[0.0,0.0]
    calls=[]
    monkeypatch.setattr(display,'time',SimpleNamespace(monotonic=lambda:clocks[0]))
    monkeypatch.setattr(display,'_now',lambda:NOW+timedelta(seconds=clocks[1]))
    monkeypatch.setattr(rolling_store,'verify_evidence',lambda conn,key:calls.append(key))
    monkeypatch.setattr(display,'_authenticate_byte_context',lambda *args:None)
    return Connection(),clocks,calls


def frame(conn,key='context'):
    return display._ByteFrame(key,conn,('system','db'),None,('epoch',1))


def test_hits_skip_actual_hashes_without_renewing_original_proof(monkeypatch):
    conn,clocks,calls=setup(monkeypatch)
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    proof=next(iter(display._BYTE_PROOFS.values()))
    clocks[:]=[599,599]
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    assert calls==['a'*64] and conn.reads==2
    assert next(iter(display._BYTE_PROOFS.values())) is proof
    assert proof.valid_until==NOW+timedelta(seconds=600) and proof.deadline==600


@pytest.mark.parametrize('clock',[(-1,0),(0,-1),(600,0),(0,600),(600,600)])
def test_expiry_and_clock_reversal_require_actual_verification(monkeypatch,clock):
    conn,clocks,calls=setup(monkeypatch)
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    clocks[:]=clock
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    assert calls==['a'*64,'a'*64]


def test_subject_query_cannot_carry_a_proof_past_its_expiry(monkeypatch):
    conn,clocks,calls=setup(monkeypatch)
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    original=conn.execute
    clocks[:]=[599,599]
    def slow(*args):
        clocks[:]=[601,601]
        return original(*args)
    conn.execute=slow
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    assert calls==['a'*64,'a'*64]


@pytest.mark.parametrize('field',range(len(META)))
def test_each_physical_tuple_and_storage_coordinate_invalidates(monkeypatch,field):
    conn,_,calls=setup(monkeypatch)
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    changed=list(META)
    changed[field]=False if field in (9,10) else 'changed'
    conn.row=tuple(changed)
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    assert calls==['a'*64,'a'*64]


@pytest.mark.parametrize('change',['context','identity','owner'])
def test_context_identity_and_owner_cannot_share_proof(monkeypatch,change):
    conn,_,calls=setup(monkeypatch)
    display._verify_evidence(conn,'a'*64,context=frame(conn))
    if change=='owner':
        monkeypatch.setattr(display,'os',SimpleNamespace(getpid=lambda:-1))
    display._verify_evidence(conn,'b'*64 if change=='identity' else 'a'*64,
        context=frame(conn,'changed' if change=='context' else 'context'))
    assert len(calls)==2


def test_no_witness_legacy_or_missing_rows_never_reuse(monkeypatch):
    conn,_,calls=setup(monkeypatch)
    for _ in range(2):display._verify_evidence(conn,'a'*64,context=None)
    assert conn.reads==0 and len(calls)==2 and not display._BYTE_PROOFS
    for row in (None,(*META[:-3],False,False,None)):
        conn.row=row
        for _ in range(2):display._verify_evidence(conn,'a'*64,context=frame(conn))
    assert len(calls)==6 and not display._BYTE_PROOFS


def test_failed_hash_is_never_cached(monkeypatch):
    conn,_,calls=setup(monkeypatch)
    def refuse(_,identity):
        calls.append(identity)
        raise rolling_store.SnapshotStorageRefused('corrupt bytes')
    monkeypatch.setattr(rolling_store,'verify_evidence',refuse)
    for _ in range(2):
        with pytest.raises(rolling_store.SnapshotStorageRefused):
            display._verify_evidence(conn,'a'*64,context=frame(conn))
    assert len(calls)==2 and not display._BYTE_PROOFS


def test_memory_is_bounded_and_eviction_requires_fresh_work(monkeypatch):
    conn,_,calls=setup(monkeypatch)
    for i in range(17):display._verify_evidence(conn,f'{i:064x}',context=frame(conn))
    assert len(display._BYTE_PROOFS)==16
    display._verify_evidence(conn,f'{0:064x}',context=frame(conn))
    assert len(calls)==18 and len(display._BYTE_PROOFS)==16


@pytest.mark.parametrize('change',['endpoint','physical','installation','ddl','guard','marker','environment','source','limit','age'])
def test_source_environment_database_and_policy_context_is_reobserved(monkeypatch,tmp_path,change):
    present=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:(True,)),
        info=SimpleNamespace(host='host',port=5432,dbname='db',user='reader'))
    facts=['system','db','witness','file','xmin','ctid','epoch',1,
        ['marker','file','xmin','ctid','installed'],[['event','xmin','ctid','O','handler','xmin','ctid']]]
    monkeypatch.setattr(display,'_byte_metadata',lambda conn:tuple(facts))
    source=tmp_path/'verifier.py';source.write_text('reviewed verifier')
    monkeypatch.setattr(rolling_store,'__file__',str(source))
    before=display._byte_context(present).key
    if change=='endpoint':present.info.port=5433
    elif change=='physical':facts[0]='different-system'
    elif change=='installation':facts[8][4]='different'
    elif change=='ddl':facts[7]=2
    elif change=='guard':facts[9][0][6]='changed-handler-tuple'
    elif change=='marker':facts[8][2]='changed-marker-tuple'
    elif change=='environment':monkeypatch.setenv('PRIVATE_SOURCE_CONTEXT','changed')
    elif change=='source':source.write_text('changed verifier')
    elif change=='limit':monkeypatch.setattr(rolling_store,'MAX_EVIDENCE_BYTES',1)
    elif change=='age':
        from sentinel.panel import authority_reader
        monkeypatch.setattr(authority_reader,'FRESH_SECONDS',1)
    assert display._byte_context(present).key!=before


def test_absent_ddl_witness_grants_no_context():
    conn=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:(False,)))
    assert display._byte_context(conn) is None


def test_malformed_independent_context_refuses_instead_of_granting_reuse(monkeypatch):
    conn=Connection()
    def malformed(actual):raise ValueError('malformed independent witness')
    monkeypatch.setattr(read_projection,'_subject_facts',malformed)
    monkeypatch.setattr(rolling_store,'verify_evidence',lambda *args:None)
    with pytest.raises(ValueError,match='independent witness'):
        display._verify_evidence(conn,'a'*64,context=frame(conn))


def test_catalog_authentication_once_per_miss_frame_and_never_on_a_hit(monkeypatch):
    conn,_,calls=setup(monkeypatch);authenticated=[]
    monkeypatch.setattr(display,'_authenticate_byte_context',lambda *args:authenticated.append(True))
    owned=frame(conn)
    for key in ('a'*64,'b'*64):display._verify_evidence(conn,key,context=owned)
    assert len(authenticated)==1 and len(calls)==2
    fresh=frame(conn)
    for key in ('a'*64,'b'*64):display._verify_evidence(conn,key,context=fresh)
    assert len(authenticated)==1 and len(calls)==2 and fresh.authenticated is False


@pytest.mark.parametrize('changed',['physical','installation','epoch'])
def test_authenticated_facts_must_match_the_observed_witness(monkeypatch,changed):
    conn=Connection();owned=frame(conn)
    facts=[('system','db'),None,('epoch',1),{}]
    if changed=='physical':facts[0]=('different-system','db')
    elif changed=='installation':facts[1]={'installation_id':'different'}
    else:facts[2]=('epoch',2)
    monkeypatch.setattr(read_projection,'_subject_facts',lambda actual:tuple(facts))
    with pytest.raises(ValueError,match='CONTEXT_CHANGED'):
        display._authenticate_byte_context(conn,owned)


@pytest.mark.parametrize('change',['owner','ended'])
def test_frame_cannot_cross_connection_owner_or_outlive_its_transaction(monkeypatch,change):
    conn,_,calls=setup(monkeypatch);owned=frame(conn)
    if change=='ended':owned.active=False
    actual=Connection() if change=='owner' else conn
    with pytest.raises(ValueError,match='CONTEXT_OWNER_CHANGED'):
        display._verify_evidence(actual,'a'*64,context=owned)
    assert not calls and actual.reads==0


def test_publication_is_authenticated_once_then_bound(monkeypatch):
    calls=[];pub=object()
    monkeypatch.setattr(display.snapshots,'_current',lambda conn:calls.append('authenticated') or pub)
    monkeypatch.setattr(display,'_binding',lambda conn,value:calls.append('bound'))
    monkeypatch.setattr(publication,'current',lambda conn:pytest.fail('duplicate legacy dispatch'))
    monkeypatch.setattr(display.readers,'is_rolling',lambda value:value is pub)
    assert display._current(object()) is pub and calls==['authenticated','bound']


def _mutate_subject(monkeypatch,needle,replacement):
    source=inspect.getsource(display._byte_subject)
    assert source.count(needle)==1
    values={}
    exec(compile(source.replace(needle,replacement),'removed-byte-proof-subject','exec'),vars(display),values)
    monkeypatch.setattr(display,'_byte_subject',values['_byte_subject'])


def test_removed_tuple_subject_has_an_executed_falsifier(monkeypatch):
    _mutate_subject(monkeypatch,'list(row)','[]')
    with pytest.raises(AssertionError):
        test_each_physical_tuple_and_storage_coordinate_invalidates(monkeypatch,7)


def test_removed_context_subject_has_an_executed_falsifier(monkeypatch):
    _mutate_subject(monkeypatch,'os.getpid(), context.key, identity','os.getpid(), "ignored", identity')
    with pytest.raises(AssertionError):test_context_identity_and_owner_cannot_share_proof(monkeypatch,'context')


def test_removed_expiry_has_an_executed_falsifier(monkeypatch):
    monkeypatch.setattr(display._ByteProof,'current',lambda *args:True)
    with pytest.raises(AssertionError):
        test_expiry_and_clock_reversal_require_actual_verification(monkeypatch,(600,600))


def test_removed_owner_subject_has_an_executed_falsifier(monkeypatch):
    _mutate_subject(monkeypatch,'os.getpid(), context.key, identity','"ignored-owner", context.key, identity')
    with pytest.raises(AssertionError):test_context_identity_and_owner_cannot_share_proof(monkeypatch,'owner')


def _mutate_verification(monkeypatch,needle,replacement):
    source=inspect.getsource(display._verify_evidence)
    assert source.count(needle)==1
    values={}
    exec(compile(source.replace(needle,replacement),'removed-byte-proof-guard','exec'),vars(display),values)
    monkeypatch.setattr(display,'_verify_evidence',values['_verify_evidence'])


def test_removed_witness_requirement_has_an_executed_falsifier(monkeypatch):
    _mutate_verification(monkeypatch,'if context is None:','if False:')
    with pytest.raises((AssertionError,AttributeError)):
        test_no_witness_legacy_or_missing_rows_never_reuse(monkeypatch)


def test_pre_query_clock_cannot_substitute_for_current_expiry_check(monkeypatch):
    _mutate_verification(monkeypatch,'if proof is not None and proof.current(_now(), time.monotonic()):',
        'if proof is not None and proof.current(instant, started):')
    with pytest.raises(AssertionError):test_subject_query_cannot_carry_a_proof_past_its_expiry(monkeypatch)


def test_removed_memory_limit_has_an_executed_falsifier(monkeypatch):
    monkeypatch.setattr(display,'_MAX_PROOFS',1024)
    with pytest.raises(AssertionError):test_memory_is_bounded_and_eviction_requires_fresh_work(monkeypatch)


def test_removed_frame_owner_guard_has_an_executed_falsifier(monkeypatch):
    _mutate_verification(monkeypatch,'if not context.active or context.owner is not conn:','if False:')
    with pytest.raises(pytest.fail.Exception):
        test_frame_cannot_cross_connection_owner_or_outlive_its_transaction(monkeypatch,'owner')


def test_removed_full_authentication_has_an_executed_falsifier(monkeypatch):
    _mutate_verification(monkeypatch,'_authenticate_byte_context(conn, context)','None')
    with pytest.raises(pytest.fail.Exception):
        test_malformed_independent_context_refuses_instead_of_granting_reuse(monkeypatch)


def test_removed_authenticated_witness_binding_has_an_executed_falsifier(monkeypatch):
    monkeypatch.setattr(display,'_authenticate_byte_context',lambda *args:None)
    with pytest.raises(pytest.fail.Exception):
        test_authenticated_facts_must_match_the_observed_witness(monkeypatch,'epoch')
