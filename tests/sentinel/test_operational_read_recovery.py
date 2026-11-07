"""A pre-commit transient read may recover inside the same collector budget."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from psycopg.errors import QueryCanceled

from sentinel.panel import model, observer_failure, projection_service as producer, review

NOW=datetime(2031,4,21,20,tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_collection_stage():
    token = producer._COLLECTION_STAGE.set('NOT_STARTED')
    try:
        yield
    finally:
        producer._COLLECTION_STAGE.reset(token)


def setup(monkeypatch, *, fail_until=1, stage='OWNER', exception=QueryCanceled, elapsed=1):
    clock=[0.0];calls=[];failures=[]
    monkeypatch.setattr(producer,'time',SimpleNamespace(monotonic=lambda:clock[0],
        sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    def publish(*a,**k):
        calls.append(clock[0]);clock[0]+=elapsed
        producer._COLLECTION_STAGE.set(stage)
        if len(calls)<=fail_until:raise exception('private diagnostic text')
        return dict(valid_until=(NOW+timedelta(seconds=30)).isoformat())
    def negative(*a,**k):
        failures.append((a,k));return dict(valid_until=(NOW+timedelta(seconds=30)).isoformat())
    monkeypatch.setattr(producer,'publish_once',publish)
    monkeypatch.setattr(producer,'publish_failure',negative)
    return calls,failures,clock


def test_transient_owner_read_recollects_once_without_publishing_false_failure(monkeypatch):
    calls,failures,clock=setup(monkeypatch)
    result=producer.collect_result('fixture','owner','state','instance')
    assert result['outcome']=='PUBLISHED' and len(calls)==2
    assert failures==[] and clock[0]<producer.DEADLINE_SECONDS
    assert producer._COLLECTION_STAGE.get()=='NOT_STARTED'


def test_removed_recovery_path_is_detected(monkeypatch):
    monkeypatch.setattr(producer,'_READ_STAGES',frozenset())
    with pytest.raises(AssertionError):
        test_transient_owner_read_recollects_once_without_publishing_false_failure(monkeypatch)


@pytest.mark.parametrize(('stage','exception','elapsed','count'),[
    ('OWNER',QueryCanceled,1,2),('OWNER',QueryCanceled,18,1),
    ('COMMIT',QueryCanceled,1,1),('ENCODE',ValueError,1,1),
])
def test_persistent_late_commit_or_identity_fault_retains_true_negative(monkeypatch,stage,exception,elapsed,count):
    calls,failures,_=setup(monkeypatch,fail_until=3,stage=stage,exception=exception,elapsed=elapsed)
    assert producer.collect_result('fixture','owner','state','instance')['outcome']=='PUBLISHED'
    assert len(calls)==count and len(failures)==1
    diagnostic=failures[0][0][-1];context=failures[0][1]['context']
    assert diagnostic['code']==('READ_TIMEOUT' if exception is QueryCanceled else 'VALIDATION_REFUSED')
    assert context['stage']==stage and context['attempts']==count
    assert producer._COLLECTION_STAGE.get()=='NOT_STARTED'


def test_backoff_cannot_reset_the_original_budget(monkeypatch):
    calls,failures,clock=setup(monkeypatch,fail_until=3)
    monkeypatch.setattr(producer.time,'sleep',lambda _:clock.__setitem__(0,21))
    producer.collect_result('fixture','owner','state','instance')
    assert len(calls)==1 and len(failures)==1


def test_safe_operational_failure_stage_is_retained_without_exception_text():
    secret='postgresql://private:never-export@private-host/book'
    diagnostic=observer_failure.classify(QueryCanceled(secret)).model_dump(mode='json',by_alias=True)
    row=model.Row('operational_projection','Operational observation','UNAVAILABLE',model.UNKNOWN,as_of=NOW)
    panel=model.Panel(now=NOW,rows=[row],trial_details=dict(operational_failure=diagnostic,
        operational_failure_context=dict(schema='sentinel.operational-failure-context/1',
            stage='OWNER',attempts=2,elapsed_ms=6250)))
    value=review.condition_evidence(panel,{'operational_projection'})
    evidence=value['operational_projection']
    assert evidence['code']=='OPERATIONAL_COLLECTION_READ_TIMEOUT'
    assert evidence['collector_stage']=='OWNER' and evidence['attempts']==2
    assert evidence['exception_type']=='QueryCanceled'
    assert evidence['diagnostic_sha256']==diagnostic['fingerprint']
    assert secret not in json.dumps(value) and 'never-export' not in json.dumps(value)
