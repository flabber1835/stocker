"""Admission races and the narrowly scoped private-process predecessor bridge."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sentinel import shadow_drain as drain, shadow_drain_compat as compat
from sentinel import shadow_service_status as status

NOW=datetime.now(timezone.utc)
IMAGE='sha256:'+'2'*64
INCARNATION='3'*32
DSN='postgresql://qualification/drain'


@pytest.fixture(autouse=True)
def binding(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','qualification-only-drain-key-'+'x'*32)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT',compat.PREDECESSOR)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST',IMAGE)
    monkeypatch.setenv('SENTINEL_DATABASE_URL',DSN)
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_MODE','OWNER_AUTHORIZED_FUNCTION_FIRST_V1')


def seed(state, *, incarnation=INCARNATION, now=None):
    status._write(state/status.NAME,status.Status(binding_sha256=status.binding(DSN),
        incarnation=incarnation,state='RUNNING',reason='IDLE',observed_at=now or datetime.now(timezone.utc)))


def request(state, *, now=NOW):
    return drain.request(state,DSN,operation_id='private-drain',request_sha256='a'*64,now=now)


def test_request_excludes_new_admission_and_preserves_first_ack_clock(tmp_path):
    seed(tmp_path,now=NOW)
    original=request(tmp_path)
    calls=[]
    assert drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:calls.append('armed'),now=NOW+timedelta(seconds=1)) is None
    first=(tmp_path/drain.ACK_NAME).read_bytes()
    assert drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:calls.append('armed'),now=NOW+timedelta(seconds=2)) is None
    assert (tmp_path/drain.ACK_NAME).read_bytes()==first and not calls
    proof=drain.acknowledged(tmp_path,DSN,original,now=NOW+timedelta(seconds=2))
    assert proof['quiescent_at']==(NOW+timedelta(seconds=1)).isoformat()


def test_admitted_worker_must_clear_naturally_before_acknowledgement(tmp_path):
    seed(tmp_path,now=NOW);request(tmp_path)
    pending=tmp_path/status.PENDING_NAME;pending.write_text('unresolved admitted work')
    with pytest.raises(ValueError,match='unresolved'):
        drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:pytest.fail('new worker admitted'),now=NOW)
    assert not (tmp_path/drain.ACK_NAME).exists() and pending.read_text()=='unresolved admitted work'
    pending.unlink()
    assert drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:pytest.fail('new worker admitted'),now=NOW) is None


def test_expiry_releases_admission_but_cannot_be_reused_as_acknowledgement(tmp_path):
    seed(tmp_path,now=NOW);original=request(tmp_path)
    drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:'not reached',now=NOW)
    later=NOW+timedelta(seconds=601)
    assert drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:'new admission',now=later)=='new admission'
    with pytest.raises(ValueError):
        drain.acknowledged(tmp_path,DSN,original,now=later)


def test_new_incarnation_cannot_reuse_old_request_or_ack(tmp_path):
    seed(tmp_path,now=NOW);original=request(tmp_path)
    drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:'not reached',now=NOW)
    seed(tmp_path,incarnation='4'*32,now=NOW+timedelta(seconds=1))
    assert drain.arm_or_drain(tmp_path,DSN,'4'*32,lambda:'new incarnation',now=NOW+timedelta(seconds=1))=='new incarnation'
    with pytest.raises(ValueError,match='identity'):
        drain.acknowledged(tmp_path,DSN,original,now=NOW+timedelta(seconds=1))


def test_malformed_authenticated_request_does_not_fall_through_to_arm(tmp_path):
    seed(tmp_path,now=NOW);request(tmp_path)
    path=tmp_path/drain.REQUEST_NAME
    path.write_bytes(path.read_bytes().replace(b'private-drain',b'forged-drain'))
    with pytest.raises(ValueError,match='authentication'):
        drain.arm_or_drain(tmp_path,DSN,INCARNATION,lambda:pytest.fail('new worker admitted'),now=NOW)


def _request_worker(state, channel, remove_guard):
    if remove_guard:
        @contextmanager
        def unguarded(_state):yield
        drain.admission=unguarded
    channel.send('ready')
    assert channel.recv()=='attempt'
    request(state,now=datetime.now(timezone.utc))
    channel.send('written')


def assert_admission_exclusion(state, *, remove_guard=False):
    import fcntl
    seed(state)
    fd=os.open(state/drain.LOCK_NAME,os.O_CREAT|os.O_RDWR,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX)
    context=multiprocessing.get_context('spawn')
    parent,child=context.Pipe()
    process=context.Process(target=_request_worker,args=(state,child,remove_guard))
    try:
        process.start();child.close()
        assert parent.poll(10) and parent.recv()=='ready'
        parent.send('attempt')
        assert not parent.poll(.20),'request crossed the worker admission lock'
        fcntl.flock(fd,fcntl.LOCK_UN)
        assert parent.poll(2) and parent.recv()=='written'
        process.join(2);assert process.exitcode==0
    finally:
        os.close(fd);parent.close()
        if process.is_alive():process.kill();process.join(2)


def test_request_writer_and_arm_use_one_real_cross_process_lock(tmp_path):
    assert_admission_exclusion(tmp_path)


def test_removing_admission_lock_has_a_falsifier(tmp_path):
    with pytest.raises(AssertionError,match='crossed'):
        assert_admission_exclusion(tmp_path,remove_guard=True)


@pytest.mark.parametrize('args,expected',[
    ([b'python',b'-m',b'sentinel.shadow_supervisor'],True),
    ([b'python3',b'-m',b'sentinel.shadow_supervisor'],True),
    ([b'/usr/local/bin/python3.12',b'-m',b'sentinel.shadow_supervisor'],True),
    ([b'/sbin/docker-init',b'--',b'python',b'-m',b'sentinel.shadow_supervisor'],False),
    ([b'python',b'-m',b'sentinel.shadow_supervisor',b'--health'],False),
    ([b'python',b'-m',b'sentinel.shadow_supervisor',b'--service-health'],False),
    ([b'python',b'-c',b'sentinel.shadow_supervisor'],False),
    ([b'python',b'sentinel.shadow_supervisor'],False),
    ([b'sh',b'-m',b'sentinel.shadow_supervisor'],False),
    ([b'python',b'-u',b'-m',b'sentinel.shadow_supervisor'],False),
])
def test_supervisor_command_requires_exact_direct_module_invocation(args,expected):
    assert compat._supervisor_command(b'\0'.join(args)+b'\0') is expected


def process_commands(monkeypatch,tmp_path,commands):
    proc=tmp_path/'proc';proc.mkdir()
    for pid,args in commands.items():
        directory=proc/str(pid);directory.mkdir()
        (directory/'cmdline').write_bytes(b'\0'.join(args)+b'\0')
    original_path=compat.Path
    monkeypatch.setattr(compat,'Path',lambda value:proc if value=='/proc' else original_path(value))
    observed=[]
    def process(pid):
        observed.append(pid)
        return dict(pid=pid,state='S',parent=1,start_ticks=pid*100)
    monkeypatch.setattr(compat,'_process',process)
    return observed


def assert_init_wrapper_is_not_a_supervisor(tmp_path,monkeypatch):
    observed=process_commands(monkeypatch,tmp_path,{
        1:[b'/sbin/docker-init',b'--',b'python',b'-m',b'sentinel.shadow_supervisor'],
        7:[b'python',b'-m',b'sentinel.shadow_supervisor'],
        8:[b'python',b'-m',b'sentinel.shadow_supervisor',b'--health'],
        9:[b'python',b'-m',b'sentinel.shadow_supervisor',b'--service-health'],
    })
    assert compat._supervisors()['pid']==7
    assert observed==[7]


def test_process_discovery_excludes_docker_init_and_health_checks(tmp_path,monkeypatch):
    assert_init_wrapper_is_not_a_supervisor(tmp_path,monkeypatch)


def test_token_only_matching_has_a_docker_init_falsifier(tmp_path,monkeypatch):
    def old_token_match(raw):
        args=raw.split(b'\0')
        return (b'sentinel.shadow_supervisor' in args
            and b'--health' not in args and b'--service-health' not in args)
    monkeypatch.setattr(compat,'_supervisor_command',old_token_match)
    with pytest.raises(ValueError,match='sole exact predecessor supervisor unavailable'):
        assert_init_wrapper_is_not_a_supervisor(tmp_path,monkeypatch)


@pytest.mark.parametrize('owners',[(),(7,8)])
def test_zero_or_multiple_direct_supervisors_refuse_before_pidfd_or_signals(tmp_path,monkeypatch,owners):
    seed(tmp_path)
    commands={1:[b'/sbin/docker-init',b'--',b'python',b'-m',b'sentinel.shadow_supervisor'],
        9:[b'python',b'-m',b'sentinel.shadow_supervisor',b'--health']}
    commands.update({pid:[b'python',b'-m',b'sentinel.shadow_supervisor'] for pid in owners})
    process_commands(monkeypatch,tmp_path,commands)
    monkeypatch.setattr(compat.os,'pidfd_open',lambda *args:pytest.fail('opened a pidfd'))
    monkeypatch.setattr(compat.signal,'pidfd_send_signal',lambda *args:pytest.fail('sent a signal'))
    with pytest.raises(ValueError,match='sole exact predecessor supervisor unavailable'):
        bridge(tmp_path)
    assert not (tmp_path/compat.NAME).exists()


@contextmanager
def private_parent(monkeypatch):
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],start_new_session=True)
    monkeypatch.setattr(compat,'_supervisors',lambda:compat._process(child.pid))
    try:
        yield child
    finally:
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        child.wait(timeout=3)


def bridge(state):
    return compat.bridge(state,operation_id='private-drain',request_sha256='a'*64,
                         container_id='private-container',image=IMAGE)


def test_private_kernel_barrier_delivers_fatal_signal_only_while_stopped(tmp_path,monkeypatch):
    seed(tmp_path)
    with private_parent(monkeypatch) as process:
        original=signal.pidfd_send_signal;signals=[]
        def observe(pidfd,signum):
            signals.append((signum,compat._process(process.pid)['state']))
            return original(pidfd,signum)
        monkeypatch.setattr(compat.signal,'pidfd_send_signal',observe)
        proof=bridge(tmp_path)
        assert process.wait(timeout=3)==-signal.SIGKILL
        fatal=[state for signum,state in signals if signum==signal.SIGKILL]
        assert fatal and all(state in {'T','t'} for state in fatal)
        assert all(signum!=signal.SIGCONT for signum,_ in signals)
        assert proof==compat._load(tmp_path)


def assert_busy_bridge_is_not_killed(state,monkeypatch):
    seed(state)
    pending=state/status.PENDING_NAME;pending.write_text('admitted worker')
    with private_parent(monkeypatch) as process:
        with pytest.raises(ValueError,match='idle'):
            bridge(state)
        end=time.monotonic()+2
        while compat._process(process.pid)['state'] in {'T','t'} and time.monotonic()<end:
            time.sleep(.01)
        assert process.poll() is None and compat._process(process.pid)['state'] not in {'T','t'}
        assert not (state/compat.NAME).exists() and pending.read_text()=='admitted worker'


def test_busy_private_process_is_resumed_without_fatal_signal(tmp_path,monkeypatch):
    assert_busy_bridge_is_not_killed(tmp_path,monkeypatch)


def test_removing_quiescence_proof_has_a_private_process_falsifier(tmp_path,monkeypatch):
    monkeypatch.setattr(compat,'_idle',lambda *args,**kwargs:None)
    with pytest.raises(pytest.fail.Exception):
        assert_busy_bridge_is_not_killed(tmp_path,monkeypatch)


def test_ambiguous_barrier_publication_never_resumes_admission(tmp_path,monkeypatch):
    seed(tmp_path)
    with private_parent(monkeypatch) as process:
        original=compat._write
        def uncertain(state,value):
            original(state,value)
            raise OSError('private fsync acknowledgement lost')
        monkeypatch.setattr(compat,'_write',uncertain)
        with pytest.raises(OSError,match='acknowledgement'):
            bridge(tmp_path)
        assert compat._process(process.pid)['state'] in {'T','t'}
        assert (tmp_path/compat.NAME).is_file()
        monkeypatch.setattr(compat,'_write',original)
        bridge(tmp_path)
        assert process.wait(timeout=3)==-signal.SIGKILL
