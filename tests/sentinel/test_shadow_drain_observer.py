"""Read-only authenticated admission and bounded event-driven drain waiting."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from pathlib import Path
import signal
import struct
import threading
import time
from types import SimpleNamespace

import pytest

from sentinel import shadow_drain as drain, shadow_drain_observer as observer
from sentinel import shadow_service_status as status
from tests.sentinel.test_shadow_drain import binding, seed, DSN, INCARNATION


def seeded(state):
    instant=drain._now();seed(state,now=instant)
    value=drain.request(state,DSN,operation_id='private-observer',request_sha256='a'*64,now=instant)
    return value


def test_read_only_admission_never_opens_or_creates_a_writable_lock(tmp_path,monkeypatch):
    request=seeded(tmp_path);opened=[];original=os.open
    def checked(path,flags,*args,**kwargs):
        if str(path).endswith(drain.LOCK_NAME):opened.append(flags)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',checked)
    before={path.name:path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    result,semantic=drain.observe_read_only(tmp_path,DSN,request,deadline=time.monotonic()+1)
    assert result is None and semantic[2:4]==('RUNNING','IDLE')
    assert opened and all(flags&os.O_ACCMODE==os.O_RDONLY and not flags&os.O_CREAT for flags in opened)
    assert {path.name:path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}==before


def test_read_only_open_guard_has_an_executed_falsifier(tmp_path,monkeypatch):
    @contextmanager
    def writable(state,**kwargs):
        with drain.admission(state):yield
    monkeypatch.setattr(drain,'read_only_admission',writable)
    with pytest.raises(AssertionError):
        test_read_only_admission_never_opens_or_creates_a_writable_lock(tmp_path,monkeypatch)


@pytest.mark.parametrize('fault',['missing','symlink','hardlink','replaced'])
def test_missing_aliased_or_replaced_read_lock_refuses(tmp_path,fault):
    seeded(tmp_path);path=tmp_path/drain.LOCK_NAME
    if fault=='missing':path.unlink()
    elif fault=='symlink':path.rename(tmp_path/'other');path.symlink_to(tmp_path/'other')
    elif fault=='hardlink':os.link(path,tmp_path/'other')
    with pytest.raises((OSError,ValueError)):
        with drain.read_only_admission(tmp_path,deadline=time.monotonic()+1):
            if fault=='replaced':path.rename(tmp_path/'other');path.touch()
    if fault=='missing':assert not path.exists()


def _blocked_reader(state,request,pipe):
    try:drain.observe_read_only(state,DSN,request,deadline=time.monotonic()+.12)
    except TimeoutError:pipe.send('bounded')
    else:pipe.send('crossed-writer')
    finally:pipe.close()


def test_held_writer_lock_cannot_extend_observer_acquisition_deadline(tmp_path):
    request=seeded(tmp_path);context=multiprocessing.get_context('fork');parent,child=context.Pipe()
    with drain.admission(tmp_path):
        process=context.Process(target=_blocked_reader,args=(tmp_path,request,child));process.start()
        assert parent.poll(2) and parent.recv()=='bounded'
    process.join(2)
    assert process.exitcode==0


def test_read_only_acquisition_does_not_replace_an_existing_owner_timer(tmp_path):
    seeded(tmp_path);prior=signal.signal(signal.SIGALRM,lambda *_:None)
    signal.setitimer(signal.ITIMER_REAL,5)
    try:
        with pytest.raises(ValueError,match='existing timer'):
            with drain.read_only_admission(tmp_path,deadline=time.monotonic()+1):pass
        assert signal.getitimer(signal.ITIMER_REAL)[0]>0
    finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,prior)


def test_read_only_acceptance_is_the_existing_canonical_ack_without_writes(tmp_path):
    request=seeded(tmp_path);assert drain.acknowledge_idle(tmp_path,DSN,INCARNATION)
    expected=drain.poll(tmp_path,DSN,request)
    before={path.name:path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    actual,semantic=drain.observe_read_only(tmp_path,DSN,request,deadline=time.monotonic()+1)
    assert actual==expected and semantic[1]==INCARNATION
    assert {path.name:path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}==before


class Clock:
    def __init__(self):self.value=0.;self.offset=0.;self.base=datetime(2031,4,21,tzinfo=timezone.utc)
    def monotonic(self):return self.value
    def now(self):return self.base+timedelta(seconds=self.value+self.offset)


def fake_wait(monkeypatch,events,*,ack_initial=False,on_wait=None,on_poll=None):
    clock=Clock();calls=[];sem=('binding','incarnation','RUNNING','ACTIVE_WORKER','attempt')
    acknowledgement={'canonical':'ack'}
    queue=list(events)
    class Watch:
        def __init__(self,state):pass
        def __enter__(self):calls.append('watch');return self
        def __exit__(self,*args):calls.append('closed')
        def check_identity(self):pass
        def wait(self,remaining):
            calls.append('wait');clock.value+=.01
            if on_wait:on_wait(clock)
            if not queue:clock.value=180;return set()
            return queue.pop(0)
    def full(*args,**kwargs):
        calls.append('poll')
        if on_poll:on_poll(clock)
        return (acknowledgement if ack_initial or len([x for x in calls if x=='poll'])>1 else None),sem
    monkeypatch.setattr(drain,'observe_read_only',full)
    monkeypatch.setattr(status,'_load',lambda path:SimpleNamespace(
        binding_sha256=sem[0],incarnation=sem[1],state=sem[2],reason=sem[3],attempt_id=sem[4]))
    def run():
        return observer.wait(Path('/private-unused'),'never-connect',{},started_at=clock.base,
            accept_until=clock.base+timedelta(seconds=180),timeout=180,
            watch_factory=Watch,monotonic=clock.monotonic,now=clock.now)
    return run,calls,clock


def test_watch_is_registered_before_initial_canonical_read_and_existing_ack_accepts(monkeypatch):
    run,calls,_=fake_wait(monkeypatch,[],ack_initial=True)
    assert run()=={'canonical':'ack'} and calls==['watch','poll','closed']


def test_ack_between_initial_read_and_wait_is_not_lost(monkeypatch):
    run,calls,_=fake_wait(monkeypatch,[{drain.ACK_NAME}])
    assert run()=={'canonical':'ack'} and calls.count('poll')==2


def test_hundreds_of_heartbeat_events_do_not_repeat_full_canonical_polls(monkeypatch):
    run,calls,_=fake_wait(monkeypatch,[{status.NAME} for _ in range(200)]+[{drain.ACK_NAME}])
    assert run()=={'canonical':'ack'} and calls.count('poll')==2


def test_status_semantic_change_wakes_the_full_reader_without_new_ack_bytes(monkeypatch):
    run,calls,_=fake_wait(monkeypatch,[{status.NAME}])
    monkeypatch.setattr(status,'_load',lambda path:SimpleNamespace(binding_sha256='binding',
        incarnation='incarnation',state='RUNNING',reason='IDLE',attempt_id=None))
    assert run()=={'canonical':'ack'} and calls.count('poll')==2


def test_unrelated_event_storm_does_not_repeat_canonical_reads(monkeypatch):
    run,calls,_=fake_wait(monkeypatch,[set() for _ in range(200)]+[{drain.ACK_NAME}])
    assert run()=={'canonical':'ack'} and calls.count('poll')==2


def test_overflow_wakes_one_full_canonical_read(monkeypatch):
    run,calls,_=fake_wait(monkeypatch,[{observer._OVERFLOW}])
    assert run()=={'canonical':'ack'} and calls.count('poll')==2


def test_unchanged_writer_lock_close_is_not_a_semantic_wakeup(tmp_path,monkeypatch):
    watch=observer.Inotify(tmp_path);info=tmp_path.stat()
    watch.identity=(info.st_dev,info.st_ino);watch.fd=123;watch.wd=1
    name=drain.LOCK_NAME.encode()+b'\0'
    reads=[struct.pack('iIII',1,0x8,0,len(name))+name]
    monkeypatch.setattr(observer.select,'select',lambda *args:([123],[],[]))
    def read(*args):
        if reads:return reads.pop(0)
        raise BlockingIOError()
    monkeypatch.setattr(observer.os,'read',read)
    assert watch.wait(.1)==set()


def test_lock_close_filter_has_an_executed_falsifier(tmp_path,monkeypatch):
    monkeypatch.setattr(observer,'_relevant',lambda name,mask:name in observer._SEMANTIC|{status.NAME})
    with pytest.raises(AssertionError):
        test_unchanged_writer_lock_close_is_not_a_semantic_wakeup(tmp_path,monkeypatch)


@pytest.mark.parametrize('fault',['timeout','late-ack','clock-regression'])
def test_original_deadline_and_clock_regression_never_accept_ack(monkeypatch,fault):
    def poll(clock):
        if fault=='late-ack':clock.value=180
    def wake(clock):
        if fault=='clock-regression':clock.offset=-1
    run,_calls,_=fake_wait(monkeypatch,[{drain.ACK_NAME}] if fault!='timeout' else [],
        ack_initial=fault=='late-ack',on_poll=poll,on_wait=wake)
    with pytest.raises((TimeoutError,ValueError)):run()


def test_real_inotify_observes_natural_ack_with_heartbeat_only_full_polls_bounded(tmp_path,monkeypatch):
    request=seeded(tmp_path);instant=drain._now()
    def active():
        now=drain._now()
        status._write(tmp_path/status.NAME,status.Status(binding_sha256=status.binding(DSN),
            incarnation=INCARNATION,state='RUNNING',reason='ACTIVE_WORKER',observed_at=now,
            attempt_id='d'*32,worker_deadline=now+timedelta(seconds=30)))
    active();calls=[];original=drain.observe_read_only;failures=[]
    def counted(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(drain,'observe_read_only',counted)
    def writer():
        try:
            for _ in range(10):time.sleep(.012);active()
            assert drain.acknowledge_idle(tmp_path,DSN,INCARNATION)
            seed(tmp_path)
        except BaseException as exc:failures.append(exc)
    thread=threading.Thread(target=writer);thread.start()
    try:
        result=observer.wait(tmp_path,DSN,request,started_at=instant,
            accept_until=instant+timedelta(seconds=3),timeout=3)
    finally:thread.join(2)
    assert not failures and not thread.is_alive()
    assert result['request']==request and len(calls)<=3


def test_directory_replacement_after_canonical_ack_cannot_cross_acceptance(tmp_path,monkeypatch):
    state=tmp_path/'state';state.mkdir();request=seeded(state)
    assert drain.acknowledge_idle(state,DSN,INCARNATION)
    original=drain.observe_read_only
    def replaced(*args,**kwargs):
        result=original(*args,**kwargs)
        state.rename(tmp_path/'original-state');state.mkdir()
        return result
    monkeypatch.setattr(drain,'observe_read_only',replaced)
    instant=drain._now()
    with pytest.raises(ValueError,match='directory changed'):
        observer.wait(state,DSN,request,started_at=instant,
            accept_until=instant+timedelta(seconds=2),timeout=2)
