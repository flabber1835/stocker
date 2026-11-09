"""One finite read-only event waiter; events never prove drain quiescence."""
from __future__ import annotations

import ctypes
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import select
import stat
import struct
import time

from sentinel import shadow_drain as drain, shadow_service_status as status

_SEMANTIC = frozenset({drain.REQUEST_NAME,drain.ACK_NAME,drain.LOCK_NAME,
                      status.PENDING_NAME,status.CRITICAL_NAME})
_OVERFLOW = '<inotify-overflow>'
_HEADER = struct.Struct('iIII')


def _relevant(name, mask):
    if name==drain.LOCK_NAME:
        return bool(mask&(0x4|0x40|0x80|0x100|0x200))
    return name in _SEMANTIC|{status.NAME}


class Inotify:
    """Watch directory renames before reading; retain no file evidence."""
    def __init__(self, state):
        self.state=state;self.fd=None

    def __enter__(self):
        info=os.stat(self.state,follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):raise ValueError('observer directory is aliased')
        self.identity=(info.st_dev,info.st_ino)
        libc=ctypes.CDLL(None,use_errno=True)
        libc.inotify_init1.argtypes=[ctypes.c_int];libc.inotify_init1.restype=ctypes.c_int
        libc.inotify_add_watch.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_uint32]
        libc.inotify_add_watch.restype=ctypes.c_int
        self.fd=libc.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC)
        if self.fd<0:raise OSError(ctypes.get_errno(),'observer watch unavailable')
        # CLOSE_WRITE, MOVED_FROM/TO, CREATE/DELETE, ATTRIB, self move/delete/unmount.
        self.wd=libc.inotify_add_watch(self.fd,os.fsencode(self.state),
            0x8|0x40|0x80|0x100|0x200|0x4|0x400|0x800|0x2000)
        if self.wd<0:
            os.close(self.fd);self.fd=None
            raise OSError(ctypes.get_errno(),'observer watch unavailable')
        try:self._fence()
        except BaseException:
            os.close(self.fd);self.fd=None
            raise
        return self

    def _fence(self):
        info=os.stat(self.state,follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev,info.st_ino)!=self.identity:
            raise ValueError('observer directory changed')

    def check_identity(self):
        self._fence()

    def wait(self, remaining):
        self._fence()
        if not select.select([self.fd],[],[],max(0,remaining))[0]:return set()
        names=set()
        for _ in range(8):  # bounded coalescing, not an event-storm extension
            try:raw=os.read(self.fd,65536)
            except BlockingIOError:break
            if not raw:raise ValueError('observer watch ended')
            offset=0
            while offset<len(raw):
                if len(raw)-offset<_HEADER.size:raise ValueError('observer event malformed')
                wd,mask,_cookie,length=_HEADER.unpack_from(raw,offset)
                offset+=_HEADER.size
                if length>len(raw)-offset:raise ValueError('observer event malformed')
                name=os.fsdecode(raw[offset:offset+length].split(b'\0',1)[0]);offset+=length
                if mask&0x4000:names.add(_OVERFLOW)
                if mask&(0x400|0x800|0x2000|0x8000):
                    raise ValueError('observer watch invalidated')
                if wd==self.wd and _relevant(name,mask):names.add(name)
        self._fence()
        return names

    def __exit__(self,*_args):
        if self.fd is not None:os.close(self.fd);self.fd=None


def wait(state, database_url, request_value, *, started_at, accept_until, timeout,
         watch_factory=Inotify, monotonic=time.monotonic, now=None):
    """Return only canonical ACK before the original absolute acceptance deadline."""
    now=now or drain._now
    instant=now()
    if (type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0<timeout<=180
            or started_at.utcoffset()!=timedelta(0) or accept_until.utcoffset()!=timedelta(0)
            or not started_at<=instant<accept_until
            or not timedelta(0)<accept_until-started_at<=timedelta(seconds=180)):
        raise ValueError('observer original deadline invalid')
    deadline=monotonic()+min(timeout,(accept_until-instant).total_seconds())
    previous=instant
    def current_time():
        nonlocal previous
        instant=now()
        if instant<previous:raise ValueError('observer clock regressed')
        previous=instant
        if instant>=accept_until or monotonic()>=deadline:
            raise TimeoutError('shadow drain acknowledgement deadline')
        return instant
    with watch_factory(state) as watcher:
        full=True;semantic=None
        while True:
            current_time()
            if full:
                watcher.check_identity()
                acknowledgement,semantic=drain.observe_read_only(
                    state,database_url,request_value,deadline=deadline)
                current_time()
                if acknowledgement is not None:
                    watcher.check_identity()
                    current_time()
                    return acknowledgement
            events=watcher.wait(max(0,deadline-monotonic()))
            current_time()
            full=bool(events&(_SEMANTIC|{_OVERFLOW}))
            if not full and status.NAME in events:
                # Only this <=8192-byte canonical status decode occurs on a pulse.
                # Its semantic comparison is a wakeup hint, never acceptance.
                current=drain.semantic_status(status._load(state/status.NAME))
                full=current!=semantic


def main(argv=None):
    import argparse
    import sys
    parser=argparse.ArgumentParser()
    parser.add_argument('--started-at',required=True)
    parser.add_argument('--accept-until',required=True)
    parser.add_argument('--timeout',type=float,required=True)
    args=parser.parse_args(argv)
    raw=sys.stdin.buffer.read(status.MAX_BYTES+1)
    if len(raw)>status.MAX_BYTES:raise ValueError('observer request exceeds its bound')
    request_value=json.loads(raw)
    result=wait(Path(os.environ.get('SENTINEL_STATE_DIR','/var/lib/sentinel')),
        os.environ.get('SENTINEL_DATABASE_URL',''),request_value,
        started_at=datetime.fromisoformat(args.started_at),
        accept_until=datetime.fromisoformat(args.accept_until),timeout=args.timeout)
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
