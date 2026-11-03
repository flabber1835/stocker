"""Real row changes must invalidate display-only intent reuse."""
from copy import deepcopy
from datetime import date
import inspect
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


@pytest.mark.parametrize('advance',[60,61,-1])
def test_ttl_and_clock_regression_require_full_validation(conn,monkeypatch,advance):
    raw=value();insert(conn,raw);clock=[100.0];memo=display.IntentMemo(clock=lambda:clock[0])
    memo.read(conn,plan_id=raw['plan_id'])
    def refused(*_args,**_kwargs):
        raise RuntimeError('full validation required')
    monkeypatch.setattr(authority,'load_authority',refused)
    clock[0]+=advance
    with pytest.raises(RuntimeError,match='full validation'):
        memo.read(conn,plan_id=raw['plan_id'])


def test_row_version_change_during_validation_refuses(conn,monkeypatch):
    raw=value();insert(conn,raw);original=authority.load_authority
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        conn.execute('UPDATE sentinel_processed_sessions SET state=state');return result
    monkeypatch.setattr(authority,'load_authority',changed)
    with pytest.raises(authority.DualPlanAuthorityRefused,match='during canonical'):
        display.IntentMemo().read(conn,plan_id=raw['plan_id'])


@pytest.mark.parametrize('field',[1,2,3,5,6,7,8])
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
