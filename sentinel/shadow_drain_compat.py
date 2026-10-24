"""One reviewed predecessor bridge, supplied verbatim to the old interpreter.

This is not a generic kill/recovery API. Busy work is resumed untouched. Only
an already stopped, proven idle exact-b2 supervisor can receive fatal SIGKILL;
admission never resumes after its authenticated kernel barrier is published.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import tempfile
import time

from sentinel import receipt_authentication, shadow_service_status as status

PREDECESSOR = 'b2e308bb664718da373175f1a7d988d07b159ae2'
SCHEMA = 'sentinel.shadow-drain-compat/1'
NAME = 'shadow-compat-drain-barrier.json'


def _signature(value):
    return receipt_authentication.sign({'purpose':SCHEMA,'barrier':value})


def _load(state):
    wrapped = json.loads(status._raw(state/NAME))
    if (not isinstance(wrapped,dict) or set(wrapped) != {'barrier','signature'}
            or not isinstance(wrapped['barrier'],dict)
            or not isinstance(wrapped['signature'],str)
            or not hmac.compare_digest(wrapped['signature'],_signature(wrapped['barrier']))):
        raise ValueError('compatibility barrier authentication refused')
    return wrapped['barrier']


def validate(value, *, operation_id, request_sha256, container_id, image, now):
    if (set(value) != {'schema','operation_id','request_sha256','container_id','commit','image',
            'binding_sha256','incarnation','pid','start_ticks','boot_id','pid_namespace','frozen_at','expires_at'}
            or value['schema'] != SCHEMA or value['commit'] != PREDECESSOR
            or value['operation_id'] != operation_id or value['request_sha256'] != request_sha256
            or value['container_id'] != container_id or value['image'] != image):
        raise ValueError('compatibility barrier identity refused')
    start, expiry = (datetime.fromisoformat(value[key]) for key in ('frozen_at','expires_at'))
    if (start.utcoffset() != timedelta(0) or expiry.utcoffset() != timedelta(0)
            or not timedelta(0) < expiry-start <= timedelta(seconds=600)
            or not start <= now < expiry):
        raise ValueError('compatibility barrier expired')
    return value


def _process(pid):
    raw = Path(f'/proc/{pid}/stat').read_text()
    fields = raw[raw.rindex(')')+2:].split()
    return {'pid':pid,'state':fields[0],'parent':int(fields[1]),'start_ticks':int(fields[19])}


def _supervisors():
    found = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            args = (path/'cmdline').read_bytes().split(b'\0')
            if b'sentinel.shadow_supervisor' in args and b'--health' not in args and b'--service-health' not in args:
                found.append(_process(int(path.name)))
        except FileNotFoundError:
            continue
    if len(found) != 1:
        raise ValueError('sole exact predecessor supervisor unavailable')
    return found[0]


def _idle(state, process, current, *, now, original_frozen_at=None):
    actual = _process(process['pid'])
    if (actual['state'] not in {'T','t'} or actual['start_ticks'] != process['start_ticks']
            or len(list(Path(f"/proc/{process['pid']}/task").iterdir())) != 1
            or (state/status.PENDING_NAME).exists() or (state/status.CRITICAL_NAME).exists()):
        raise ValueError('kernel barrier did not capture an idle supervisor')
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            item = _process(int(path.name))
            if item['parent'] == process['pid'] and item['state'] not in {'Z','X','x'}:
                raise ValueError('admitted dependency or worker still exists')
            args = (path/'cmdline').read_bytes().split(b'\0')
            if b'sentinel.shadow_worker' in args:
                raise ValueError('shadow worker still exists')
        except FileNotFoundError:
            continue
    observed = status._load(state/status.NAME)
    reference = original_frozen_at or now
    if (observed != current or observed.state != 'RUNNING' or observed.reason != 'IDLE'
            or observed.binding_sha256 != status.binding(os.environ.get('SENTINEL_DATABASE_URL',''))
            or not timedelta(0) <= reference-observed.observed_at <= timedelta(seconds=status.MAX_AGE_SECONDS)):
        raise ValueError('fresh authenticated idle incarnation unavailable')


def _write(state, value):
    fd, name = tempfile.mkstemp(prefix='.compat-drain-',dir=state)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600)
            stream.write(json.dumps({'barrier':value,'signature':_signature(value)},
                sort_keys=True,separators=(',',':')).encode())
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name,state/NAME)
        directory = os.open(state,os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def bridge(state, *, operation_id, request_sha256, container_id, image):
    if (os.environ.get('SENTINEL_GIT_COMMIT') != PREDECESSOR
            or os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST') != image
            or os.environ.get('SENTINEL_LOCAL_PAPER_MODE') != 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'):
        raise ValueError('compatibility bridge only accepts the exact reviewed predecessor')
    current = status._load(state/status.NAME)
    process = _supervisors()
    pidfd = os.pidfd_open(process['pid'])
    if _process(process['pid'])['start_ticks'] != process['start_ticks']:
        os.close(pidfd)
        raise ValueError('compatibility process identity changed before hold')
    published = False
    publication_started = False
    stopped = False
    original_frozen_at = None
    try:
        if (state/NAME).exists():
            prior = validate(_load(state),operation_id=operation_id,request_sha256=request_sha256,
                container_id=container_id,image=image,now=datetime.now(timezone.utc))
            if (prior['pid'] != process['pid'] or prior['start_ticks'] != process['start_ticks']
                    or prior['incarnation'] != current.incarnation):
                raise ValueError('compatibility barrier process changed')
            published = True
            original_frozen_at = datetime.fromisoformat(prior['frozen_at'])
        signal.pidfd_send_signal(pidfd,signal.SIGSTOP)
        stopped = True
        deadline = time.monotonic()+2
        while _process(process['pid'])['state'] not in {'T','t'}:
            if time.monotonic() >= deadline:
                raise ValueError('predecessor did not enter kernel stop')
            time.sleep(.01)
        now = datetime.now(timezone.utc)
        _idle(state,process,current,now=now,original_frozen_at=original_frozen_at)
        if not published:
            value = dict(schema=SCHEMA,operation_id=operation_id,request_sha256=request_sha256,
                container_id=container_id,commit=PREDECESSOR,image=image,binding_sha256=current.binding_sha256,
                incarnation=current.incarnation,pid=process['pid'],start_ticks=process['start_ticks'],
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                pid_namespace=os.stat('/proc/self/ns/pid').st_ino,
                frozen_at=now.isoformat(),expires_at=(now+timedelta(seconds=600)).isoformat())
            validate(value,operation_id=operation_id,request_sha256=request_sha256,
                container_id=container_id,image=image,now=now)
            publication_started = True
            _write(state,value)
            published = True
        # The sole stopped process has no live child or active DB observer.
        # Linux delivers SIGKILL fatally to a stopped task, with no SIGCONT.
        signal.pidfd_send_signal(pidfd,signal.SIGKILL)
        return _load(state)
    finally:
        try:
            if stopped and not published and not publication_started:
                signal.pidfd_send_signal(pidfd,signal.SIGCONT)
        finally:
            os.close(pidfd)


if __name__ == '__main__':
    import sys
    state = Path(os.environ.get('SENTINEL_STATE_DIR','/var/lib/sentinel'))
    try:
        value=bridge(state,operation_id=sys.argv[1],request_sha256=sys.argv[2],
            container_id=sys.argv[3],image=sys.argv[4])
    except ValueError:
        # Only a definite pre-publication busy refusal can restore the normal
        # restart policy. Ambiguous publication never produces this response.
        if os.path.lexists(state/NAME):
            raise
        deadline=time.monotonic()+2
        while True:
            current=_supervisors()
            if current['state'] not in {'T','t'}:
                value={'status':'BUSY_BEFORE_BARRIER'}
                break
            if time.monotonic()>=deadline:
                raise
            time.sleep(.01)
    print(json.dumps(value,sort_keys=True))
