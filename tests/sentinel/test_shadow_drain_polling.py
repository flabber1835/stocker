"""Retained older ACKs remain pending; only the exact new quiescence is proof."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import multiprocessing
import os

import pytest

from sentinel import shadow_drain as drain,shadow_service_status as status

NOW=datetime.now(timezone.utc)
DSN='postgresql://qualification/drain-polling'
INCARNATION='8'*32

@pytest.fixture(autouse=True)
def private_binding(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-drain-polling-'+'x'*32)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT','1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST','sha256:'+'2'*64)

def seed(state,instant,*,incarnation=INCARNATION,reason='IDLE'):
    status._write(state/status.NAME,status.Status(binding_sha256=status.binding(DSN),
        incarnation=incarnation,state='RUNNING',reason=reason,observed_at=instant))

def two_requests(state,*,new_incarnation=INCARNATION,change_binding=None):
    before=NOW-timedelta(seconds=601)
    seed(state,before)
    first=drain.request(state,DSN,operation_id='prior-drain',request_sha256='a'*64,now=before)
    drain.arm_or_drain(state,DSN,INCARNATION,lambda:pytest.fail('worker armed'),now=before+timedelta(seconds=1))
    old=(state/drain.ACK_NAME).read_bytes()
    if change_binding:change_binding()
    seed(state,NOW,incarnation=new_incarnation)
    current=drain.request(state,DSN,operation_id='current-drain',request_sha256='b'*64,now=NOW)
    return first,current,old

def test_old_authenticated_ack_is_pending_until_worker_writes_exact_new_ack(tmp_path):
    _first,current,old=two_requests(tmp_path)
    request_bytes=(tmp_path/drain.REQUEST_NAME).read_bytes()
    assert drain.poll(tmp_path,DSN,current,now=NOW) is None
    assert (tmp_path/drain.ACK_NAME).read_bytes()==old
    assert (tmp_path/drain.REQUEST_NAME).read_bytes()==request_bytes
    with pytest.raises(ValueError,match='identity'):
        drain.acknowledged(tmp_path,DSN,current,now=NOW)
    drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:pytest.fail('worker armed'),now=NOW+timedelta(seconds=1))
    proof=drain.poll(tmp_path,DSN,current,now=NOW+timedelta(seconds=2))
    assert proof['request']==current and proof['quiescent_at']==(NOW+timedelta(seconds=1)).isoformat()
    assert current['requested_at']==NOW.isoformat() and (tmp_path/drain.REQUEST_NAME).read_bytes()==request_bytes

def test_previous_runtime_binding_and_incarnation_are_never_current_proof(tmp_path,monkeypatch):
    _first,current,old=two_requests(tmp_path,new_incarnation='9'*32,
        change_binding=lambda:monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST','sha256:'+'3'*64))
    assert drain.poll(tmp_path,DSN,current,now=NOW) is None
    assert (tmp_path/drain.ACK_NAME).read_bytes()==old
    with pytest.raises(ValueError,match='identity'):
        drain.acknowledged(tmp_path,DSN,current,now=NOW)

def test_forged_older_ack_refuses_instead_of_pending(tmp_path):
    _first,current,old=two_requests(tmp_path)
    (tmp_path/drain.ACK_NAME).write_bytes(old.replace(b'prior-drain',b'forged-drain'))
    with pytest.raises(ValueError,match='authentication'):
        drain.poll(tmp_path,DSN,current,now=NOW)

@pytest.mark.parametrize('field,value',[
    ('schema','other'),('kind','DRAIN'),('request_digest','0'*64),
    ('quiescent_at',(NOW+timedelta(seconds=1)).isoformat()),
    ('quiescent_at',(NOW-timedelta(seconds=602)).isoformat()),
    ('quiescent_at',(NOW-timedelta(seconds=1)).isoformat()),
],ids=('schema','kind','request-digest','future-quiescence',
       'before-prior-request','after-prior-deadline'))
def test_authenticated_malformed_or_out_of_interval_prior_ack_refuses(tmp_path,field,value):
    _first,current,_old=two_requests(tmp_path)
    prior=drain._load(tmp_path/drain.ACK_NAME)
    prior[field]=value
    drain._write(tmp_path/drain.ACK_NAME,prior)
    with pytest.raises(ValueError):drain.poll(tmp_path,DSN,current,now=NOW)

@pytest.mark.parametrize('marker',[status.PENDING_NAME,status.CRITICAL_NAME])
def test_prior_ack_cannot_hide_current_unresolved_worker(tmp_path,marker):
    _first,current,_old=two_requests(tmp_path)
    (tmp_path/marker).write_text('unresolved')
    with pytest.raises(ValueError,match='quiescence'):
        drain.poll(tmp_path,DSN,current,now=NOW)

def test_old_ack_does_not_relax_current_request_remaining_lifetime(tmp_path):
    _first,current,_old=two_requests(tmp_path)
    later=NOW+timedelta(seconds=421);seed(tmp_path,later)
    with pytest.raises(ValueError,match='quiescence'):
        drain.poll(tmp_path,DSN,current,now=later)

def assert_future_ack_refused(state):
    _first,current,_old=two_requests(state)
    value=drain._load(state/drain.ACK_NAME)
    value['quiescent_at']=(NOW+timedelta(seconds=1)).isoformat()
    drain._write(state/drain.ACK_NAME,value)
    with pytest.raises(ValueError):drain.poll(state,DSN,current,now=NOW)

def test_removing_prior_ack_guard_has_an_executed_falsifier(tmp_path,monkeypatch):
    monkeypatch.setattr(drain,'_prior_acknowledgement',lambda *args,**kwargs:True)
    with pytest.raises(pytest.fail.Exception):assert_future_ack_refused(tmp_path)

def _poll_worker(state,channel,remove_guard):
    if remove_guard:
        @contextmanager
        def unguarded(_state):yield
        drain.admission=unguarded
    channel.send('ready');assert channel.recv()=='attempt'
    value=drain._load(state/drain.REQUEST_NAME)
    assert drain.poll(state,DSN,value) is not None
    channel.send('read')

def assert_poll_admission_exclusion(state,*,remove_guard=False):
    import fcntl
    instant=datetime.now(timezone.utc);seed(state,instant)
    drain.request(state,DSN,operation_id='current-drain',request_sha256='b'*64,now=instant)
    drain.arm_or_drain(state,DSN,INCARNATION,lambda:pytest.fail('worker armed'),now=instant)
    fd=os.open(state/drain.LOCK_NAME,os.O_CREAT|os.O_RDWR,0o600);fcntl.flock(fd,fcntl.LOCK_EX)
    parent,child=multiprocessing.get_context('spawn').Pipe()
    process=multiprocessing.get_context('spawn').Process(target=_poll_worker,args=(state,child,remove_guard))
    try:
        process.start();child.close();assert parent.poll(10) and parent.recv()=='ready'
        parent.send('attempt')
        assert not parent.poll(.2),'poll crossed worker admission boundary'
        fcntl.flock(fd,fcntl.LOCK_UN)
        assert parent.poll(3) and parent.recv()=='read'
        process.join(3);assert process.exitcode==0
    finally:
        os.close(fd);parent.close()
        if process.is_alive():process.kill();process.join(3)

def test_poll_uses_real_cross_process_admission_lock(tmp_path):
    assert_poll_admission_exclusion(tmp_path)

def test_removing_poll_lock_has_an_executed_falsifier(tmp_path):
    with pytest.raises(AssertionError,match='crossed'):
        assert_poll_admission_exclusion(tmp_path,remove_guard=True)
