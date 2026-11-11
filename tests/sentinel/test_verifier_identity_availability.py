"""A parent identity outage cannot overwrite a real bounded worker outcome."""
from datetime import timedelta
import inspect
from threading import BoundedSemaphore,Event
import textwrap

from psycopg.errors import ConnectionTimeout,QueryCanceled
import pytest

from sentinel.panel import authority_reader as reader,model,observer_failure
from tests.sentinel.test_observer_failure_diagnostics import NOW,PRIVATE,positive,completed


def controlled(*,negative=False,queued=False):
    tick=[0];unavailable=[False];entered=Event();release=Event();calls=[]
    slot=BoundedSemaphore(1)
    if queued:slot.acquire()
    def evidence(*args):
        if unavailable[0]:raise ConnectionTimeout(PRIVATE)
        return 'a'*64
    def run(*args,**kwargs):
        calls.append(1);entered.set();assert release.wait(3)
        if negative:return observer_failure.classify(QueryCanceled(PRIVATE)).model_dump(mode='json',by_alias=True)
        return positive(NOW+timedelta(seconds=tick[0]))
    # An outage in the parent's identity read leaves the worker's independent
    # post-slot identity check available to confirm the originally queued subject.
    value=reader.Reader(runner=run,evidence_reader=evidence,
        queued_evidence_reader=lambda *args: 'a'*64,key_factory=lambda db,paper,key:key,
        clock=lambda:tick[0],wall_clock=lambda:NOW+timedelta(seconds=tick[0]),
        retain_failed_attempt=True,execution_slot=slot)
    return value,tick,unavailable,entered,release,calls,slot


@pytest.mark.parametrize('queued',[False,True])
def test_parent_outage_keeps_running_or_queued_attempt_and_same_successful_result(queued):
    value,tick,unavailable,entered,release,calls,slot=controlled(queued=queued)
    value.read('private',include_paper=False)
    if not queued:assert entered.wait(1)
    before=value.attempt_state()
    assert before['outcome']==('QUEUED' if queued else 'RUNNING')
    tick[0]=20;unavailable[0]=True
    try:
        rows=value.read('private',include_paper=False)[0]
        assert rows[0].status==model.UNKNOWN and 'ConnectionTimeout' in rows[0].detail
        assert PRIVATE not in rows[0].detail
        assert value.attempt_state()==before
        assert value.failure is None and value.pending_failed_attempt() is None
        tick[0]=40
        assert value.read('private',include_paper=False)[0][0].status==model.UNKNOWN
        assert value.attempt_state()==before
    finally:
        if queued:slot.release()
        release.set();completed(value)
    assert len(calls)==1
    unavailable[0]=False
    assert value.read('private',include_paper=False)[0][0].status==model.OK
    after=value.attempt_state()
    assert after['attempt_id']==before['attempt_id'] and after['deadline']==before['deadline']
    assert after['outcome']=='VERIFIED' and after['diagnostic'] is None
    assert value.identity_failure is None and value.pending_failed_attempt() is None


def test_parent_outage_cannot_replace_actual_child_failure():
    value,tick,unavailable,entered,release,calls,_=controlled(negative=True)
    value.read('private',include_paper=False);assert entered.wait(1)
    tick[0]=10;unavailable[0]=True
    try:assert value.read('private',include_paper=False)[0][0].status==model.UNKNOWN
    finally:release.set();completed(value)
    actual=value.attempt_state()
    assert actual['outcome']=='FAILED' and actual['completed_at'] is not None
    assert actual['diagnostic']['code']=='READ_TIMEOUT'
    unavailable[0]=False
    row=value.read('private',include_paper=False)[0][0]
    assert row.status==model.UNKNOWN and 'READ_TIMEOUT' in row.detail
    assert value.attempt_state()['latched_failure']['code']=='READ_TIMEOUT'
    assert len(calls)==1


@pytest.mark.parametrize('consume',[False,True])
def test_preoutage_answer_or_cached_proof_cannot_restore_current_evidence(consume):
    tick=[0];unavailable=[False];calls=[]
    def evidence(*args):
        if unavailable[0]:raise ConnectionTimeout(PRIVATE)
        return 'a'*64
    def run(*a,**kw):calls.append(1);return positive(NOW+timedelta(seconds=tick[0]))
    value=reader.Reader(runner=run,evidence_reader=evidence,key_factory=lambda db,paper,key:key,
        clock=lambda:tick[0],wall_clock=lambda:NOW+timedelta(seconds=tick[0]))
    value.read('private',include_paper=False);completed(value)
    if consume:assert value.read('private',include_paper=False)[0][0].status==model.OK
    old_id=value.attempt_state()['attempt_id']
    tick[0]=10;unavailable[0]=True
    assert value.read('private',include_paper=False)[0][0].status==model.UNKNOWN
    unavailable[0]=False;tick[0]=11
    assert value.read('private',include_paper=False)[0][0].status==model.UNKNOWN
    assert value.identity_failure is not None and len(calls)==1
    tick[0]=31
    value.read('private',include_paper=False);completed(value)
    assert value.read('private',include_paper=False)[0][0].status==model.OK
    assert value.attempt_state()['attempt_id']!=old_id and len(calls)==2


def test_source_wait_cannot_clear_identity_availability_as_full_verification():
    unavailable=[True]
    def evidence(*args):
        if unavailable[0]:raise ConnectionTimeout(PRIVATE)
        return 'a'*64
    data=positive()
    data['rows'][0].update(status=model.WARN,recovery=dict(phase='SOURCE_FRONTIER',automatic=True,
        operator_required=False,deadline=NOW+timedelta(seconds=100)))
    value=reader.Reader(runner=lambda *a,**kw:data,evidence_reader=evidence,
        key_factory=lambda db,paper,key:key,clock=lambda:0,wall_clock=lambda:NOW)
    assert value.read('private',include_paper=False)[0][0].status==model.UNKNOWN
    unavailable[0]=False
    value.read('private',include_paper=False);completed(value)
    assert value.read('private',include_paper=False)[0][0].status==model.UNKNOWN
    assert value.identity_failure is not None


@pytest.mark.parametrize('defect',['outcome','old_answer','hide_availability'])
def test_availability_boundary_has_executed_falsifiers(monkeypatch,defect):
    source=textwrap.dedent(inspect.getsource(reader.Reader.read))
    if defect=='outcome':
        needle='self.identity_failed_at = self.wall_clock()'
        replacement=needle+"\n            self.attempt_outcome = 'FAILED'"
        check=lambda:test_parent_outage_keeps_running_or_queued_attempt_and_same_successful_result(False)
    elif defect=='old_answer':
        needle='completed_at >= self.identity_failed_at';replacement='True'
        check=lambda:test_preoutage_answer_or_cached_proof_cannot_restore_current_evidence(False)
    else:
        needle='if self.identity_failure is not None:';replacement='if False:'
        check=lambda:test_preoutage_answer_or_cached_proof_cannot_restore_current_evidence(True)
    assert source.count(needle)==1
    scope={}
    exec(compile(source.replace(needle,replacement),'identity availability mutant','exec'),vars(reader),scope)
    monkeypatch.setattr(reader.Reader,'read',scope['read'])
    with pytest.raises(AssertionError):check()
