"""Real finite HTTP transport and event-as-wakeup falsifiers, no Docker calls."""
from contextlib import contextmanager
from copy import deepcopy
import ast
import importlib
import inspect
import json
from pathlib import Path
import socket
import stat
import struct
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import (
    coordinator, host_module, model)

health = importlib.import_module(host_module.__package__ + '.docker_health')
IDENTITY = 'a' * 64
IMAGE = 'sha256:' + 'b' * 64
NAME = 'sentinel-sentinel-shadow-1'


def item(status='starting'):
    return dict(Id=IDENTITY, Name='/' + NAME, Image=IMAGE,
        State=dict(Running=True, OOMKilled=False, Restarting=False,
                   Health=dict(Status=status)))


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeEngine:
    def __init__(self, observations, batches=(), *, clock=None):
        self.clock = clock or Clock()
        self.observations = list(observations)
        self.batches = list(batches)
        self.reads = []
        self.deadlines = []
        self.closed = False

    def inspect(self, identity, deadline):
        self.reads.append(identity)
        self.deadlines.append(deadline)
        value = self.observations.pop(0)
        if callable(value):
            value = value()
        return deepcopy(value)

    @contextmanager
    def wakeups(self, identity, deadline):
        assert identity == IDENTITY
        self.stream_deadline = deadline
        try:
            yield self
        finally:
            self.closed = True

    def wait(self, deadline):
        assert deadline == self.stream_deadline
        if self.batches:
            value = self.batches.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        self.clock.value = deadline
        return False


def run_wait(engine, deadline=180):
    return health.wait(engine, NAME, IMAGE, deadline, clock=engine.clock)


def test_already_healthy_needs_one_fresh_observation_and_no_stream():
    engine = FakeEngine([item('healthy')])
    run_wait(engine)
    assert engine.reads == [NAME] and not hasattr(engine, 'stream_deadline')


@pytest.mark.parametrize('case', ['headers_before_registration', 'silent_live_loss'])
def test_quiet_lost_transition_is_resolved_by_one_final_fresh_read(case):
    # Headers or a live subscription do not guarantee delivery. No wake arrives.
    engine = FakeEngine([item(), item(), item('healthy')])
    run_wait(engine)
    assert engine.clock() == 177
    assert engine.reads == [NAME, IDENTITY, IDENTITY]
    assert engine.deadlines == [180, 180, 180] and engine.closed


def test_removing_final_reconciliation_falsifies_quiet_loss(monkeypatch):
    tree = ast.parse(inspect.getsource(health.wait))
    body = next(node for node in tree.body[0].body if isinstance(node, ast.With)).body
    assert isinstance(body[-1], ast.If)
    body[-1] = ast.Return(value=None)
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), '<removed-final-read>', 'exec'),
         health.__dict__, namespace)
    monkeypatch.setattr(health, 'wait', namespace['wait'])
    with pytest.raises(AssertionError):
        test_quiet_lost_transition_is_resolved_by_one_final_fresh_read('silent_live_loss')


def test_event_is_only_a_wakeup_and_never_a_positive_verdict():
    engine = FakeEngine([item(), item(), item(), item()], [True])
    with pytest.raises(model.DeliveryRefused, match='SHADOW_STARTUP_DEADLINE'):
        run_wait(engine)
    assert len(engine.reads) == 4 and engine.closed


def test_one_transition_batch_gets_one_fresh_read():
    engine = FakeEngine([item(), item(), item('healthy')], [True])
    run_wait(engine)
    assert engine.reads == [NAME, IDENTITY, IDENTITY] and engine.closed


@pytest.mark.parametrize('fault', ['identity', 'name', 'image', 'running', 'oom', 'restarting'])
def test_fresh_observation_fails_closed_on_replacement_or_current_failure(fault):
    changed = item('healthy')
    if fault == 'identity':
        changed['Id'] = 'c' * 64
    elif fault == 'name':
        changed['Name'] = '/renamed'
    elif fault == 'image':
        changed['Image'] = 'sha256:' + 'c' * 64
    else:
        changed['State'][{'running': 'Running', 'oom': 'OOMKilled',
                          'restarting': 'Restarting'}[fault]] = fault != 'running'
    engine = FakeEngine([item(), changed])
    with pytest.raises(model.DeliveryRefused, match='SUCCESSOR_SHADOW_FAILED'):
        run_wait(engine)
    assert engine.closed and engine.reads == [NAME, IDENTITY]


def test_removed_exact_id_guard_accepts_replacement_falsifier(monkeypatch):
    source = inspect.getsource(health.wait)
    guarded = 'and (expected is None or identity == expected)'
    assert source.count(guarded) == 1
    namespace = {}
    exec(compile(source.replace(guarded, ''), '<removed-id-guard>', 'exec'),
         health.__dict__, namespace)
    monkeypatch.setattr(health, 'wait', namespace['wait'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_fresh_observation_fails_closed_on_replacement_or_current_failure('identity')


def test_eof_is_refusal_without_reconnect_or_positive_final_fallback():
    engine = FakeEngine([item(), item(), item('healthy')],
                        [model.DeliveryRefused('ENGINE_STREAM_EOF')])
    with pytest.raises(model.DeliveryRefused, match='ENGINE_STREAM_EOF'):
        run_wait(engine)
    assert len(engine.reads) == 2 and engine.closed


def test_late_healthy_result_is_not_accepted():
    clock = Clock()
    def late():
        clock.value = 180
        return item('healthy')
    engine = FakeEngine([late], clock=clock)
    with pytest.raises(health._Deadline):
        run_wait(engine)


def test_coordinator_passes_the_original_deadline_and_clock_without_sleep():
    clock = Clock()
    calls = []
    host = SimpleNamespace(wait_application_health=lambda service, **kwargs:
                           calls.append((service, kwargs)))
    delivery = coordinator.Delivery(host, None, monotonic=clock,
        sleep=lambda _: pytest.fail('periodic health sleep'))
    delivery._wait_shadow()
    assert calls == [('sentinel-shadow', dict(deadline=180, clock=clock))]


@pytest.mark.parametrize('fault', ['context', 'endpoint', 'tls', 'extra_endpoint'])
def test_context_admission_has_no_remote_or_ambient_fallback(fault):
    value = dict(Name='default', TLSMaterial={}, Endpoints={'docker': {
        'Host': 'unix:///var/run/docker.sock', 'SkipTLSVerify': False}})
    if fault == 'context':
        value['Name'] = 'desktop-linux'
    elif fault == 'endpoint':
        value['Endpoints']['docker']['Host'] = 'tcp://remote:2375'
    elif fault == 'tls':
        value['TLSMaterial'] = {'docker': ['certificate']}
    else:
        value['Endpoints']['other'] = {}
    with pytest.raises(model.DeliveryRefused, match='ENGINE_CONTEXT_UNSUPPORTED'):
        health.require_context([value])


@pytest.mark.parametrize('uid,accepted', [(0, True), (10001, False)])
def test_peer_credentials_require_root(uid, accepted):
    sock = SimpleNamespace(getsockopt=lambda *args: struct.pack('3i', 123, uid, 0))
    if accepted:
        health._require_peer(sock)
    else:
        with pytest.raises(model.DeliveryRefused, match='ENGINE_PEER_UNSAFE'):
            health._require_peer(sock)


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity', '1e999', '-1e999'])
def test_nonfinite_json_is_rejected_even_in_unused_metadata_fields(number):
    with pytest.raises(model.DeliveryRefused, match='ENGINE_JSON_NONFINITE'):
        health._json('{"unused":' + number + '}')


@pytest.mark.parametrize('fault', ['endpoint', 'owner', 'type'])
def test_production_socket_admission_rejects_unqualified_metadata(fault):
    value = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=0,
                            st_dev=1, st_ino=2)
    resolved = Path('/run/docker.sock')
    if fault == 'endpoint':
        resolved = Path('/tmp/docker-proxy.sock')
    elif fault == 'owner':
        value.st_uid = 10001
    else:
        value.st_mode = stat.S_IFREG | 0o660
    path = SimpleNamespace(resolve=lambda: resolved, stat=lambda: value)
    with pytest.raises(model.DeliveryRefused):
        health._socket_identity(path)


def json_response(value, *, chunked=False):
    body = json.dumps(value).encode()
    if chunked:
        return (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
            b'Transfer-Encoding: chunked\r\n\r\n' + chunk(body) + b'0\r\n\r\n')
    return (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
        + b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)


def chunk(raw):
    return format(len(raw), 'x').encode() + b'\r\n' + raw + b'\r\n'


def event(action='health_status: healthy', *, identity=IDENTITY, kind='container'):
    return json.dumps(dict(Type=kind, Action=action,
                          Actor=dict(ID=identity))).encode() + b'\n'


EVENT_HEADERS = (b'HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n'
                 b'Transfer-Encoding: chunked\r\n\r\n')


class UnixServer:
    """Private synthetic endpoint; production socket/peer guards tested separately."""
    def __init__(self, path, handler):
        self.path, self.handler = path, handler
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(path))
        self.socket.listen()
        self.socket.settimeout(.1)
        self.stop = threading.Event()
        self.connections = []
        self.requests = []
        self.errors = []
        self.workers = []
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections.append(conn)
            worker = threading.Thread(target=self.handle, args=(conn,))
            self.workers.append(worker)
            worker.start()

    def handle(self, conn):
        try:
            request = bytearray()
            while b'\r\n\r\n' not in request:
                raw = conn.recv(4096)
                if not raw:
                    break
                request.extend(raw)
            self.requests.append(bytes(request))
            self.handler(conn, bytes(request), self.stop)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except BaseException as exc:
            self.errors.append(exc)
        finally:
            conn.close()

    def close(self):
        self.stop.set()
        for conn in self.connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.socket.close()
        self.thread.join(2)
        for worker in self.workers:
            worker.join(2)
        assert not self.thread.is_alive() and not self.errors
        assert all(not worker.is_alive() for worker in self.workers)


@pytest.fixture
def unix_engine(tmp_path, monkeypatch):
    servers = []
    # The private fixture cannot claim to be /run/docker.sock or a root daemon.
    monkeypatch.setattr(health, '_socket_identity', lambda path:
                        (path.stat().st_dev, path.stat().st_ino))
    monkeypatch.setattr(health, '_require_peer', lambda sock: None)
    def create(handler):
        path = tmp_path / ('engine-' + str(len(servers)) + '.sock')
        server = UnixServer(path, handler)
        servers.append(server)
        return health.Engine(path), server
    yield create
    for server in servers:
        server.close()


@pytest.mark.parametrize('chunked', [False, True])
def test_real_unix_http_metadata_decodes_explicit_framing(unix_engine, chunked):
    engine, server = unix_engine(lambda conn, request, stop:
                                conn.sendall(json_response(item(), chunked=chunked)))
    assert engine.inspect(IDENTITY, time.monotonic() + 1) == item()
    assert b'/v1.56/containers/' + IDENTITY.encode() + b'/json' in server.requests[0]


def test_socket_replacement_is_refused_before_another_connection(unix_engine, monkeypatch):
    engine, server = unix_engine(lambda conn, request, stop:
                                conn.sendall(json_response(item())))
    monkeypatch.setattr(health, '_socket_identity', lambda path: (999, 999))
    with pytest.raises(model.DeliveryRefused, match='ENGINE_SOCKET_CHANGED'):
        engine.inspect(IDENTITY, time.monotonic() + 1)
    assert server.requests == []


def test_selector_allocation_failure_closes_the_already_owned_socket(monkeypatch):
    closed = []
    monkeypatch.setattr(health.socket, 'socket', lambda *args:
                        SimpleNamespace(close=lambda: closed.append(True)))
    def exhausted():
        raise OSError('private synthetic descriptor exhaustion')
    monkeypatch.setattr(health.selectors, 'DefaultSelector', exhausted)
    with pytest.raises(OSError):
        health._Response(None, '/', time.monotonic() + 1)
    assert closed == [True]


@pytest.mark.parametrize('fault', ['status', 'duplicate', 'ambiguous', 'oversized',
                                  'encoding', 'missing_framing', 'bad_chunk', 'eof'])
def test_real_unix_http_rejects_unsupported_or_partial_responses(unix_engine, fault):
    response = {
        'status': b'HTTP/1.1 500 Error\r\n\r\n',
        'duplicate': b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Type: application/json\r\n\r\n',
        'ambiguous': b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nContent-Length: 2\r\n\r\n',
        'oversized': b'HTTP/1.1 200 OK\r\nX-Large: ' + b'a' * 9000 + b'\r\n\r\n',
        'encoding': b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\n{}',
        'missing_framing': b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}',
        'bad_chunk': b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n',
        'eof': b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{}',
    }[fault]
    engine, _ = unix_engine(lambda conn, request, stop: conn.sendall(response))
    with pytest.raises(model.DeliveryRefused):
        engine.inspect(IDENTITY, time.monotonic() + 1)


def test_slow_header_trickle_does_not_renew_absolute_deadline(unix_engine):
    def trickle(conn, request, stop):
        for byte in b'HTTP/1.1 200 OK\r\n':
            if stop.wait(.02):
                return
            conn.send(bytes([byte]))
    engine, _ = unix_engine(trickle)
    before = time.monotonic()
    with pytest.raises(health._Deadline):
        engine.inspect(IDENTITY, before + .08)
    assert time.monotonic() - before < .5


def test_event_filter_excludes_exec_chatter_and_exact_identity_is_rechecked(unix_engine):
    def stream(conn, request, stop):
        conn.sendall(EVENT_HEADERS + chunk(event('exec_start') + event(identity='c' * 64)
            + event() + event()))
        stop.wait(1)
    engine, server = unix_engine(stream)
    with engine.wakeups(IDENTITY, time.monotonic() + 1) as wakeups:
        assert wakeups.wait(time.monotonic() + .5)
    request = server.requests[0].split(b' ')[1].decode()
    filters = json.loads(parse_qs(urlsplit(request).query)['filters'][0])
    assert filters['container'] == [IDENTITY] and filters['type'] == ['container']
    assert not any(value.startswith('exec_') for value in filters['event'])


def test_silent_event_stream_waits_once_to_final_admission_without_reads(unix_engine):
    def stream(conn, request, stop):
        conn.sendall(EVENT_HEADERS)
        stop.wait(.5)
    engine, _ = unix_engine(stream)
    with engine.wakeups(IDENTITY, time.monotonic() + 1) as wakeups:
        assert wakeups.wait(time.monotonic() + .03) is False


@pytest.mark.parametrize('case', ['pre_registration_gap', 'silent_registered_loss',
                                 'open_partial_event', 'open_partial_chunk'])
def test_actual_unix_stream_lost_transition_still_reconciles_once(
        unix_engine, monkeypatch, case):
    monkeypatch.setattr(health, 'IO_SECONDS', .2)
    post_header_read = threading.Event()
    state = dict(healthy=False, observations=0)
    def serve(conn, request, stop):
        if b'/events?' in request:
            prefix = (chunk(b'{"Type":') if case == 'open_partial_event' else
                      b'20\r\n{"Type":' if case == 'open_partial_chunk' else b'')
            conn.sendall(EVENT_HEADERS + prefix)  # Not registration ACK.
            assert post_header_read.wait(1)
            state['healthy'] = True  # No live record, for either permitted loss.
            stop.wait(1)
        else:
            state['observations'] += 1
            snapshot = item('healthy' if state['healthy'] else 'starting')
            if state['observations'] == 2:
                post_header_read.set()
            conn.sendall(json_response(snapshot))
    engine, _ = unix_engine(serve)
    deadline = time.monotonic() + .8
    health.wait(engine, NAME, IMAGE, deadline)
    assert state['observations'] == 3 and time.monotonic() < deadline


@pytest.mark.parametrize('raw', [chunk(b'{"Type":'), b'20\r\n{"Type":'])
def test_partial_event_followed_by_eof_is_failure_not_silent_deadline(unix_engine, raw):
    engine, _ = unix_engine(lambda conn, request, stop:
                           conn.sendall(EVENT_HEADERS + raw))
    with pytest.raises(model.DeliveryRefused, match='ENGINE_STREAM_EOF'):
        with engine.wakeups(IDENTITY, time.monotonic() + 1) as wakeups:
            wakeups.wait(time.monotonic() + .3)


def test_partial_chunked_event_is_reassembled_without_trusting_headers(unix_engine):
    def stream(conn, request, stop):
        raw = event()
        conn.sendall(EVENT_HEADERS + chunk(raw[:10]))
        stop.wait(.01)
        conn.sendall(chunk(raw[10:]))
        stop.wait(.5)
    engine, _ = unix_engine(stream)
    with engine.wakeups(IDENTITY, time.monotonic() + 1) as wakeups:
        assert wakeups.wait(time.monotonic() + .3)


@pytest.mark.parametrize('raw', [b'{bad-json}\n', b'{"Actor":{},"Action":0}\n',
    b'a' * (health.MAX_EVENT + 1) + b'\n',
    b'{"Actor":{},"Actor":{},"Action":"die"}\n'])
def test_invalid_event_body_refuses_and_closes_owned_transport(unix_engine, raw):
    def stream(conn, request, stop):
        conn.sendall(EVENT_HEADERS + chunk(raw))
        stop.wait(.5)
    engine, _ = unix_engine(stream)
    with pytest.raises(model.DeliveryRefused):
        with engine.wakeups(IDENTITY, time.monotonic() + 1) as wakeups:
            wakeups.wait(time.monotonic() + .3)


@pytest.mark.parametrize('version', [dict(Os='windows', MinAPIVersion='1.40', ApiVersion='1.56'),
    dict(Os='linux', MinAPIVersion='1.57', ApiVersion='1.57'),
    dict(Os='linux', MinAPIVersion='1.40', ApiVersion='1.55')])
def test_api_version_is_explicit_and_unsupported_does_not_poll(unix_engine, version):
    engine, server = unix_engine(lambda conn, request, stop:
                                conn.sendall(json_response(version)))
    with pytest.raises(model.DeliveryRefused, match='ENGINE_API_UNSUPPORTED'):
        engine.version(time.monotonic() + 1)
    assert len(server.requests) == 1


def test_host_context_admission_is_bounded_and_never_launches_ack(monkeypatch):
    host = object.__new__(host_module.Host)
    host.request = dict(candidate=dict(image=IMAGE))
    calls = []
    context = [dict(Name='remote', TLSMaterial={}, Endpoints={})]
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps(context).encode())
    host.run = run
    with pytest.raises(model.DeliveryRefused, match='ENGINE_CONTEXT_UNSUPPORTED'):
        host.wait_application_health('sentinel-shadow', deadline=180, clock=Clock())
    assert calls == [(['docker', 'context', 'inspect'], dict(timeout=3))]
