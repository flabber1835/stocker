"""Finite authenticated admission hold for an exact shadow incarnation.

The request writer and worker arming share one file lock. An acknowledgement
is possible only after an admitted worker has naturally cleared its marker.
Expiry releases admission and invalidates the acknowledgement simultaneously.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile

from sentinel import receipt_authentication, shadow_service_status as status

REQUEST_NAME = 'shadow-drain-request.json'
ACK_NAME = 'shadow-drain-acknowledgement.json'
LOCK_NAME = 'shadow-drain-admission.lock'
SCHEMA = 'sentinel.shadow-drain/1'
MAX_SECONDS = 600


def _now():
    return datetime.now(timezone.utc)


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sign(value):
    return receipt_authentication.sign({'purpose':SCHEMA,'payload':value})


def _load(path):
    value = json.loads(status._raw(path))
    if (not isinstance(value,dict) or set(value) != {'payload','signature'}
            or not isinstance(value['payload'],dict) or not isinstance(value['signature'],str)
            or not hmac.compare_digest(value['signature'],_sign(value['payload']))):
        raise ValueError('shadow drain authentication refused')
    return value['payload']


def _write(path, value):
    if path.is_symlink():
        raise ValueError('shadow drain path is aliased')
    raw = _canonical({'payload':value,'signature':_sign(value)})
    if len(raw) > status.MAX_BYTES:
        raise ValueError('shadow drain exceeds its bound')
    fd, temporary = tempfile.mkstemp(prefix='.shadow-drain-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory = os.open(path.parent,os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def admission(state):
    import fcntl
    fd = os.open(state/LOCK_NAME,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        import stat
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('shadow admission lock is aliased')
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def validate_request(value, *, binding, incarnation, now):
    if (not isinstance(value,dict) or set(value) != {
            'schema','kind','operation_id','request_sha256','binding_sha256','incarnation','requested_at','expires_at'}
            or value['schema'] != SCHEMA or value['kind'] != 'DRAIN'
            or not isinstance(value['operation_id'],str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,79}',value['operation_id'])
            or not isinstance(value['request_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['request_sha256'])
            or not isinstance(value['binding_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['binding_sha256'])
            or not isinstance(value['incarnation'],str) or not re.fullmatch('[0-9a-f]{32}',value['incarnation'])
            or value['binding_sha256'] != binding or value['incarnation'] != incarnation):
        raise ValueError('shadow drain identity refused')
    start, expiry = (datetime.fromisoformat(value[field]) for field in ('requested_at','expires_at'))
    if (start.utcoffset() != timedelta(0) or expiry.utcoffset() != timedelta(0)
            or not timedelta(0) < expiry-start <= timedelta(seconds=MAX_SECONDS)
            or now < start):
        raise ValueError('shadow drain clock refused')
    return now < expiry


def request(state, database_url, *, operation_id, request_sha256, now=None):
    now = now or _now()
    with admission(state):
        current = status._load(state/status.NAME)
        if (current.binding_sha256 != status.binding(database_url) or current.state != 'RUNNING'
                or not timedelta(0) <= now-current.observed_at <= timedelta(seconds=status.MAX_AGE_SECONDS)):
            raise ValueError('current shadow incarnation unavailable')
        path = state/REQUEST_NAME
        if path.exists():
            prior = _load(path)
            live = validate_request(prior,binding=prior.get('binding_sha256'),incarnation=prior.get('incarnation'),now=now)
            live = live and prior['binding_sha256'] == current.binding_sha256 and prior['incarnation'] == current.incarnation
            if live:
                if prior['operation_id'] != operation_id or prior['request_sha256'] != request_sha256:
                    raise ValueError('another operation owns shadow drain')
                return prior
        value = dict(schema=SCHEMA,kind='DRAIN',operation_id=operation_id,request_sha256=request_sha256,
            binding_sha256=current.binding_sha256,incarnation=current.incarnation,
            requested_at=now.isoformat(),expires_at=(now+timedelta(seconds=MAX_SECONDS)).isoformat())
        validate_request(value,binding=current.binding_sha256,incarnation=current.incarnation,now=now)
        _write(path,value)
        return value


def arm_or_drain(state, database_url, incarnation, arm, *, now=None):
    """One atomic admission boundary; None means held, never an armed worker."""
    now = now or _now()
    with admission(state):
        path = state/REQUEST_NAME
        if path.exists():
            request_value = _load(path)
            live = validate_request(request_value,binding=request_value.get('binding_sha256'),
                                    incarnation=request_value.get('incarnation'),now=now)
            live = live and request_value['binding_sha256'] == status.binding(database_url) and request_value['incarnation'] == incarnation
            if live:
                if (state/status.PENDING_NAME).exists() or (state/status.CRITICAL_NAME).exists():
                    raise ValueError('shadow drain cannot acknowledge unresolved work')
                acknowledgement = dict(schema=SCHEMA,kind='DRAINED',request=request_value,
                    request_digest=_digest(request_value),quiescent_at=now.isoformat())
                target = state/ACK_NAME
                if target.exists():
                    prior = _load(target)
                    if prior.get('request_digest') == acknowledgement['request_digest']:
                        return None  # Preserve the original quiescent clock.
                _write(target,acknowledgement)
                return None
        return arm()


def acknowledged(state, database_url, request_value, *, now=None, remaining_seconds=180):
    now = now or _now()
    with admission(state):
        current = status._load(state/status.NAME)
        if (not validate_request(request_value,binding=status.binding(database_url),incarnation=current.incarnation,now=now)
                or datetime.fromisoformat(request_value['expires_at'])-now < timedelta(seconds=remaining_seconds)
                or current.state != 'RUNNING' or current.reason != 'IDLE'
                or current.binding_sha256 != request_value['binding_sha256']
                or not timedelta(0) <= now-current.observed_at <= timedelta(seconds=status.MAX_AGE_SECONDS)
                or _load(state/REQUEST_NAME) != request_value
                or (state/status.PENDING_NAME).exists() or (state/status.CRITICAL_NAME).exists()):
            raise ValueError('shadow drain quiescence unavailable')
        value = _load(state/ACK_NAME)
        if (set(value) != {'schema','kind','request','request_digest','quiescent_at'}
                or value['schema'] != SCHEMA or value['kind'] != 'DRAINED'
                or value['request'] != request_value or value['request_digest'] != _digest(request_value)):
            raise ValueError('shadow drain acknowledgement identity refused')
        quiescent = datetime.fromisoformat(value['quiescent_at'])
        if not datetime.fromisoformat(request_value['requested_at']) <= quiescent <= now:
            raise ValueError('shadow drain acknowledgement clock refused')
        return value


def poll(state, database_url, request_value, *, now=None):
    instant = now or _now()
    current = status._load(state/status.NAME)
    if (not validate_request(request_value,binding=status.binding(database_url),
            incarnation=current.incarnation,now=instant)
            or _load(state/REQUEST_NAME) != request_value):
        raise ValueError('shadow drain request no longer current')
    if current.state=='RUNNING' and current.reason=='ACTIVE_WORKER':
        return None
    if not (state/ACK_NAME).exists():
        return None
    return acknowledged(state,database_url,request_value,now=instant)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('request','acknowledged'))
    parser.add_argument('--operation-id',required=True)
    parser.add_argument('--request-sha256',required=True)
    args = parser.parse_args(argv)
    state = Path(os.environ.get('SENTINEL_STATE_DIR','/var/lib/sentinel'))
    database_url = os.environ.get('SENTINEL_DATABASE_URL','')
    if args.action == 'request':
        value = request(state,database_url,operation_id=args.operation_id,request_sha256=args.request_sha256)
    else:
        value = _load(state/REQUEST_NAME)
        if value['operation_id'] != args.operation_id or value['request_sha256'] != args.request_sha256:
            raise ValueError('shadow drain operation changed')
        value = poll(state,database_url,value)
    print(json.dumps(value,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
