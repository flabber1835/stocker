"""Finite native Engine observations; events wake reads and never prove health."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import math
import os
from pathlib import Path
import re
import selectors
import socket
import stat
import struct
import time
from urllib.parse import urlencode

from .model import DeliveryRefused, require

SOCKET = Path('/var/run/docker.sock')
API = '1.56'
IO_SECONDS = 3.0
MAX_HEADERS = 16384
MAX_BODY = 2 * 1024 * 1024
MAX_EVENT = 65536
MAX_BATCH = 256
ACTIONS = frozenset({'health_status: starting', 'health_status: healthy',
    'health_status: unhealthy', 'die', 'oom', 'destroy', 'restart', 'stop',
    'start', 'kill', 'pause', 'unpause', 'rename', 'update'})


class _Deadline(TimeoutError):
    pass


class _WouldBlock(Exception):
    pass


def _remaining(deadline, clock):
    remaining = deadline - clock()
    if remaining <= 0:
        raise _Deadline()
    return remaining


def _json(raw):
    def finite(raw_number):
        value = float(raw_number)
        require(math.isfinite(value), 'ENGINE_JSON_NONFINITE')
        return value

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'ENGINE_JSON_DUPLICATE_KEY')
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
            parse_constant=lambda _: require(False, 'ENGINE_JSON_NONFINITE'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DeliveryRefused('ENGINE_JSON_MALFORMED') from exc


def _socket_identity(path):
    require(os.name == 'posix' and hasattr(socket, 'AF_UNIX')
        and hasattr(socket, 'SO_PEERCRED'), 'ENGINE_TRANSPORT_UNSUPPORTED')
    require(path.resolve() == Path('/run/docker.sock'), 'ENGINE_ENDPOINT_UNSUPPORTED')
    value = path.stat()
    require(stat.S_ISSOCK(value.st_mode) and value.st_uid == 0,
        'ENGINE_SOCKET_UNSAFE')
    return value.st_dev, value.st_ino


def _require_peer(sock):
    peer = struct.unpack('3i', sock.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    require(peer[1] == 0, 'ENGINE_PEER_UNSAFE')


class _Response:
    """HTTP/1.1 reader with an absolute deadline at every socket operation."""

    def __init__(self, engine, path, deadline, *, stream=False):
        self.engine, self.stream = engine, stream
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.selector = None
        self.buffer = bytearray()
        self.chunk_left = 0
        self.chunk_end = False
        self.trailers = False
        self.complete = False
        self.left = None
        try:
            self.selector = selectors.DefaultSelector()
            require(_socket_identity(engine.path) == engine.identity,
                'ENGINE_SOCKET_CHANGED')
            self.sock.setblocking(False)
            self.selector.register(self.sock, selectors.EVENT_WRITE)
            code = self.sock.connect_ex(str(engine.path))
            require(code in {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN},
                'ENGINE_CONNECT_FAILED')
            self._ready(deadline)
            require(self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0,
                'ENGINE_CONNECT_FAILED')
            _require_peer(self.sock)
            require(_socket_identity(engine.path) == engine.identity,
                'ENGINE_SOCKET_CHANGED')
            request = ('GET ' + path + ' HTTP/1.1\r\nHost: localhost\r\n'
                'Accept: ' + ('application/x-ndjson' if stream else 'application/json')
                + '\r\nConnection: close\r\n\r\n').encode('ascii')
            while request:
                _remaining(deadline, engine.clock)
                try:
                    written = self.sock.send(request)
                except BlockingIOError:
                    self._ready(deadline)
                    continue
                require(written > 0, 'ENGINE_SEND_FAILED')
                request = request[written:]
            self.selector.modify(self.sock, selectors.EVENT_READ)
            self._headers(deadline)
            _remaining(deadline, engine.clock)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            if self.selector is not None:
                self.selector.close()
        finally:
            self.sock.close()

    def _ready(self, deadline):
        remaining = _remaining(deadline, self.engine.clock)
        if not self.selector.select(remaining):
            raise _Deadline()
        _remaining(deadline, self.engine.clock)

    def _recv(self, deadline, wait):
        while True:
            _remaining(deadline, self.engine.clock)
            try:
                raw = self.sock.recv(65536)
            except BlockingIOError:
                if not wait:
                    raise _WouldBlock()
                self._ready(deadline)
                continue
            require(bool(raw), 'ENGINE_STREAM_EOF')
            self.buffer.extend(raw)
            return

    def _take(self, count, deadline, wait=True):
        while len(self.buffer) < count:
            self._recv(deadline, wait)
        raw = bytes(self.buffer[:count])
        del self.buffer[:count]
        return raw

    def _line(self, limit, deadline, wait=True):
        while True:
            end = self.buffer.find(b'\r\n')
            if end >= 0:
                require(end <= limit, 'ENGINE_HEADER_EXCEEDS_BOUND')
                return self._take(end + 2, deadline, wait)[:-2]
            require(len(self.buffer) <= limit, 'ENGINE_HEADER_EXCEEDS_BOUND')
            self._recv(deadline, wait)

    def _headers(self, deadline):
        first = self._line(8192, deadline)
        require(re.fullmatch(rb'HTTP/1\.1 200(?: [\x20-\x7e]*)?', first) is not None,
            'ENGINE_HTTP_REFUSED')
        headers = {}
        total = len(first) + 2
        while True:
            line = self._line(8192, deadline)
            total += len(line) + 2
            require(total <= MAX_HEADERS, 'ENGINE_HEADERS_EXCEED_BOUND')
            if not line:
                break
            name, separator, raw = line.partition(b':')
            require(separator and re.fullmatch(rb'[A-Za-z0-9-]+', name) is not None,
                'ENGINE_HEADERS_MALFORMED')
            name = name.lower()
            require(name not in headers, 'ENGINE_HEADERS_DUPLICATE')
            headers[name] = raw.strip().lower()
        content = headers.get(b'content-type', b'').split(b';', 1)[0]
        allowed = {b'application/x-ndjson', b'application/jsonl'} if self.stream else {b'application/json'}
        require(content in allowed, 'ENGINE_CONTENT_TYPE_UNSUPPORTED')
        require(headers.get(b'content-encoding', b'identity') == b'identity',
            'ENGINE_ENCODING_UNSUPPORTED')
        encoding = headers.get(b'transfer-encoding')
        length = headers.get(b'content-length')
        require(not (encoding is not None and length is not None),
            'ENGINE_FRAMING_AMBIGUOUS')
        if encoding is not None:
            require(encoding == b'chunked', 'ENGINE_FRAMING_UNSUPPORTED')
        else:
            require(not self.stream and length is not None and length.isdigit(),
                'ENGINE_FRAMING_UNSUPPORTED')
            self.left = int(length)
            require(self.left <= MAX_BODY, 'ENGINE_BODY_EXCEEDS_BOUND')

    def part(self, deadline, wait=True):
        if self.complete:
            return b''
        if self.left is not None:
            if self.left == 0:
                self.complete = True
                return b''
            while not self.buffer:
                self._recv(deadline, wait)
            count = min(self.left, len(self.buffer), 65536)
            self.left -= count
            return self._take(count, deadline, wait)
        if self.chunk_end:
            require(self._take(2, deadline, wait) == b'\r\n', 'ENGINE_CHUNK_MALFORMED')
            self.chunk_end = False
        if self.trailers:
            require(self._line(MAX_HEADERS, deadline, wait) == b'',
                'ENGINE_TRAILERS_UNSUPPORTED')
            self.complete = True
            return b''
        if self.chunk_left == 0:
            line = self._line(128, deadline, wait)
            require(re.fullmatch(rb'[0-9a-fA-F]{1,8}', line) is not None,
                'ENGINE_CHUNK_MALFORMED')
            self.chunk_left = int(line, 16)
            require(self.chunk_left <= MAX_BODY, 'ENGINE_CHUNK_EXCEEDS_BOUND')
            if self.chunk_left == 0:
                self.trailers = True
                require(self._line(MAX_HEADERS, deadline, wait) == b'',
                    'ENGINE_TRAILERS_UNSUPPORTED')
                self.complete = True
                return b''
        while not self.buffer:
            self._recv(deadline, wait)
        count = min(self.chunk_left, len(self.buffer), 65536)
        raw = self._take(count, deadline, wait)
        self.chunk_left -= count
        self.chunk_end = self.chunk_left == 0
        return raw

    def json(self, deadline):
        body = bytearray()
        while True:
            raw = self.part(deadline)
            if not raw:
                break
            body.extend(raw)
            require(len(body) <= MAX_BODY, 'ENGINE_BODY_EXCEEDS_BOUND')
        _remaining(deadline, self.engine.clock)
        return _json(body)


class _Wakeups:
    def __init__(self, response, identity):
        self.response, self.identity = response, identity
        self.pending = bytearray()

    def _record(self, deadline, wait):
        while True:
            end = self.pending.find(b'\n')
            if end >= 0:
                require(end <= MAX_EVENT, 'ENGINE_EVENT_EXCEEDS_BOUND')
                raw = bytes(self.pending[:end])
                del self.pending[:end + 1]
                value = _json(raw)
                require(isinstance(value, dict) and isinstance(value.get('Actor'), dict)
                    and isinstance(value.get('Action'), str)
                    and len(value['Action']) <= 100, 'ENGINE_EVENT_MALFORMED')
                return (value.get('Type') == 'container'
                    and value['Actor'].get('ID') in (
                        (self.identity,) if isinstance(self.identity,str) else self.identity)
                    and value['Action'] in ACTIONS)
            require(len(self.pending) <= MAX_EVENT, 'ENGINE_EVENT_EXCEEDS_BOUND')
            raw = self.response.part(deadline, wait)
            require(bool(raw), 'ENGINE_STREAM_EOF')
            self.pending.extend(raw)

    def wait(self, deadline):
        try:
            while not self._record(deadline, True):
                pass
        except _Deadline:
            return False
        for _ in range(MAX_BATCH - 1):
            try:
                self._record(deadline, False)
            except (_WouldBlock, _Deadline):
                break
        return True


class Engine:
    def __init__(self, path=SOCKET, *, clock=time.monotonic):
        self.path, self.clock = Path(path), clock
        self.identity = _socket_identity(self.path)

    def _deadline(self, deadline):
        _remaining(deadline, self.clock)
        return min(deadline, self.clock() + IO_SECONDS)

    def json(self, path, deadline):
        end = self._deadline(deadline)
        response = _Response(self, path, end)
        try:
            return response.json(end)
        finally:
            response.close()

    def version(self, deadline):
        value = self.json('/version', deadline)
        def version(raw):
            require(isinstance(raw, str) and re.fullmatch(r'\d+\.\d+', raw) is not None,
                'ENGINE_API_UNSUPPORTED')
            return tuple(int(part) for part in raw.split('.'))
        require(isinstance(value, dict) and value.get('Os') == 'linux'
            and version(value.get('MinAPIVersion')) <= version(API)
            <= version(value.get('ApiVersion')), 'ENGINE_API_UNSUPPORTED')

    def inspect(self, identity, deadline):
        require(re.fullmatch(r'[a-zA-Z0-9_.-]+', identity) is not None,
            'APPLICATION_IDENTITY_INVALID')
        value = self.json('/v' + API + '/containers/' + identity + '/json', deadline)
        require(isinstance(value, dict), 'APPLICATION_CONTAINER_OBSERVATION_MALFORMED')
        return value

    @contextmanager
    def wakeups(self, identity, deadline):
        identities = (identity,) if isinstance(identity,str) else identity
        require(isinstance(identities,tuple) and 1<=len(identities)<=6
            and len(set(identities))==len(identities)
            and all(isinstance(item,str) and re.fullmatch(r'[0-9a-f]{64}',item) is not None
                    for item in identities),
            'APPLICATION_IDENTITY_INVALID')
        actions = ['health_status', *sorted(ACTIONS - {
            'health_status: starting', 'health_status: healthy', 'health_status: unhealthy'})]
        query = urlencode({'since': '1', 'filters': json.dumps({
            'type': ['container'], 'container': list(identities), 'event': actions},
            separators=(',', ':'))})
        response = _Response(self, '/v' + API + '/events?' + query,
            self._deadline(deadline), stream=True)
        try:
            yield _Wakeups(response, identity)
        finally:
            response.close()


def require_context(values):
    require(isinstance(values, list) and len(values) == 1
        and isinstance(values[0], dict), 'ENGINE_CONTEXT_UNSUPPORTED')
    value = values[0]
    require(value.get('Name') == 'default' and not value.get('TLSMaterial')
        and value.get('Endpoints') == {'docker': {
            'Host': 'unix:///var/run/docker.sock', 'SkipTLSVerify': False}},
        'ENGINE_CONTEXT_UNSUPPORTED')


def wait(engine, name, image, deadline, *, clock=time.monotonic):
    expected = None

    def observe():
        nonlocal expected
        value = engine.inspect(expected or name, deadline)
        _remaining(deadline, clock)
        identity = value.get('Id')
        require(isinstance(identity, str) and re.fullmatch(r'[0-9a-f]{64}', identity)
            and value.get('Name') == '/' + name and value.get('Image') == image
            and (expected is None or identity == expected), 'SUCCESSOR_SHADOW_FAILED')
        expected = identity
        state = value.get('State')
        require(isinstance(state, dict) and state.get('Running') is True
            and state.get('OOMKilled') is False and state.get('Restarting') is False,
            'SUCCESSOR_SHADOW_FAILED')
        health = state.get('Health')
        return isinstance(health, dict) and health.get('Status') == 'healthy'

    if observe():
        return
    final_at = deadline - IO_SECONDS
    require(clock() < final_at, 'SHADOW_STARTUP_DEADLINE')
    with engine.wakeups(expected, final_at) as wakeups:
        # Headers are not a subscription ACK. Only this fresh state is evidence.
        if observe():
            return
        while clock() < final_at and wakeups.wait(final_at):
            if observe():
                return
        if observe():
            return
    raise DeliveryRefused('SHADOW_STARTUP_DEADLINE')


def wait_many(engine, names, image, deadline, *, clock=time.monotonic, expected=None):
    """One subscription for all roles; every wake uses fresh canonical state."""
    require(isinstance(names,tuple) and 1<=len(names)<=6 and len(set(names))==len(names),
            'APPLICATION_NAMES_INVALID')
    expected = dict(expected or {})
    require(not expected or set(expected)==set(names),'APPLICATION_STARTUP_BINDING_INVALID')
    for value in expected.values():
        require(isinstance(value,dict) and isinstance(value.get('Id'),str)
            and re.fullmatch(r'[0-9a-f]{64}',value['Id']) is not None
            and type(value.get('RestartCount')) is int and value['RestartCount']>=0
            and isinstance(value.get('State'),dict)
            and isinstance(value['State'].get('StartedAt'),str) and value['State']['StartedAt'],
            'APPLICATION_STARTUP_BINDING_INVALID')

    def observe():
        result = {}
        for name in names:
            value = engine.inspect(expected.get(name,{}).get('Id',name),deadline)
            _remaining(deadline,clock)
            state = value.get('State')
            require(isinstance(value.get('Id'),str)
                and re.fullmatch(r'[0-9a-f]{64}',value['Id']) is not None
                and value.get('Name')=='/'+name and value.get('Image')==image
                and isinstance(state,dict) and state.get('Running') is True
                and state.get('OOMKilled') is False and state.get('Restarting') is False
                and isinstance(state.get('StartedAt'),str) and state['StartedAt']
                and type(value.get('RestartCount')) is int, 'APPLICATION_STARTUP_FAILED')
            if name in expected:
                prior=expected[name]
                require(value['Id']==prior['Id'] and value['RestartCount']==prior['RestartCount']
                    and state['StartedAt']==prior['State']['StartedAt'],
                    'APPLICATION_STARTUP_PROCESS_CHANGED')
            else:
                expected[name]=value
            health=state.get('Health')
            status=health.get('Status') if isinstance(health,dict) else None
            # A failed probe can recover without changing this startup process.
            require(isinstance(status,str) and status in {'starting','unhealthy','healthy'},
                    'APPLICATION_STARTUP_FAILED')
            result[name]=value
        return result

    def healthy(values):
        return all(value['State']['Health']['Status']=='healthy' for value in values.values())

    values=observe()
    if healthy(values):return values
    final_at=deadline-IO_SECONDS
    require(clock()<final_at,'APPLICATION_READINESS_DEADLINE')
    with engine.wakeups(tuple(expected[name]['Id'] for name in names),final_at) as wakeups:
        values=observe()
        if healthy(values):return values
        while clock()<final_at and wakeups.wait(final_at):
            values=observe()
            if healthy(values):return values
        values=observe()
        if healthy(values):return values
    raise DeliveryRefused('APPLICATION_READINESS_DEADLINE')
