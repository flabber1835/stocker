"""Offline signed LIVE monitoring, native identity and GET-only falsifiers."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import inspect
import textwrap
from types import SimpleNamespace

import httpx
import pytest

from sentinel import binding, identity, strategy
from sentinel.authority.canonical import canonical_json_bytes
from sentinel.authority.model import AuthorityRefused
from sentinel.config import SentinelConfig
from sentinel.execution import trading_readonly as module
from tests.sentinel.test_live_runtime_authority import runtime_fixture


def monitoring(tmp_path, monkeypatch):
    f = runtime_fixture(tmp_path, monkeypatch)
    for name, value in f.env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(identity, "rehearsal_identity", lambda: f.runtime)
    monkeypatch.setattr(strategy, "production_strategy", lambda: (None, f.strategy))
    f.owner = f.bound
    f.connections, f.calls = [], []
    monkeypatch.setattr(binding, "require", lambda conn: f.owner)
    class Connection:
        def __init__(self): self.closed = False
        def rollback(self): pass
        def close(self): self.closed = True
    def factory(*_args, **_kwargs):
        conn = Connection()
        f.connections.append(conn)
        return conn
    f.account = dict(id=f.subject.account_id, account_number="display-only-number", currency="USD",
        equity="1000", cash="1000", buying_power="1000", multiplier="1", status="ACTIVE",
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False)
    f.after_response = None
    def handler(request):
        assert request.method == "GET"
        assert all(conn.closed for conn in f.connections)
        f.calls.append((request.method, request.url.path, dict(request.url.params)))
        if f.after_response is not None:
            f.after_response()
        return httpx.Response(200, json=deepcopy(f.account) if request.url.path == "/v2/account" else [])
    provider = SimpleNamespace(AsyncClient=lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), **kwargs))
    f.config = replace(SentinelConfig.from_env({}), base_url=f.subject.base_url, database_url="offline-only")
    f.factory, f.provider = factory, provider
    return f


def reader(f):
    return module.TradingReadOnly(config=f.config, connection_factory=f.factory,
                                 http_provider=lambda: f.provider)


def test_read_facade_uses_fresh_closed_connections_around_each_get(tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    r = reader(f)
    initial = len(f.connections)
    assert asyncio.run(r.account_snapshot()).identity.account_id == f.subject.account_id
    assert len(f.connections) == initial + 2
    assert asyncio.run(r.identify_account()).broker == "alpaca-live"
    assert len(f.connections) == initial + 4
    assert all(conn.closed for conn in f.connections)
    assert [path for _, path, _ in f.calls] == ["/v2/account", "/v2/account"]
    for name in ("submit", "cancel", "close_account", "close_position", "observe", "_httpx", "api_key"):
        assert not hasattr(r, name)


def test_missing_live_authority_refuses_before_http(tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    monkeypatch.delenv("SENTINEL_LIVE_CERTIFICATE_PATH")
    with pytest.raises(AuthorityRefused):
        reader(f)
    assert not f.calls
    assert all(conn.closed for conn in f.connections)


@pytest.mark.parametrize("during", [False, True])
def test_read_authority_revocation_is_fresh_even_for_existing_facade(tmp_path, monkeypatch, during):
    f = monitoring(tmp_path, monkeypatch)
    r = reader(f)
    def revoke():
        f.enrollment["roots"][0]["status"] = "REVOKED"
        f.roots_path.write_bytes(canonical_json_bytes(f.enrollment))
    if during:
        f.after_response = revoke
    else:
        revoke()
    with pytest.raises(AuthorityRefused):
        asyncio.run(r.identify_account())
    assert len(f.calls) == int(during)


@pytest.mark.parametrize("change", ["namespace", "epoch", "native"])
def test_same_uuid_cross_environment_or_changed_account_never_publishes(tmp_path, monkeypatch, change):
    f = monitoring(tmp_path, monkeypatch)
    r = reader(f)
    if change == "namespace":
        f.owner = replace(f.owner, broker="alpaca")
    elif change == "epoch":
        f.owner = replace(f.owner, takeover_epoch=2)
    else:
        f.account["id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(AuthorityRefused):
        asyncio.run(r.account_snapshot())
    assert len(f.calls) == int(change == "native")


@pytest.mark.parametrize("path,params", [
    ("/v2/positions", None), ("/v2/account/../orders", None),
    ("https://evil.test/v2/account", None), ("/v2/orders/not-a-uuid", None),
    ("/v2/account", {"url": "https://evil.test"}),
    ("/v2/orders", {"status": "all", "limit": 500, "nested": True}),
    ("/v2/account/activities/FILL", {"order_id": "not-a-uuid", "direction": "asc", "page_size": 100}),
])
def test_monitoring_rejects_unapproved_read_routes_before_http(tmp_path, monkeypatch, path, params):
    f = monitoring(tmp_path, monkeypatch)
    r = reader(f)
    with pytest.raises(module.MonitoringReadRefused):
        asyncio.run(r._get(path, params))
    assert not f.calls


def test_plain_caller_reader_is_not_live_authority(tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    with pytest.raises(module.MonitoringReadRefused, match="authenticated GET-only"):
        module.live_monitoring_reader(f.config, SimpleNamespace(cash="1000"))
    assert not f.calls


def test_native_account_guard_removal_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    source = textwrap.dedent(inspect.getsource(module._ReadTransport._get))
    needle = 'if account.account_id != first.subject.account_id:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), '<monitor-native-mutant>', 'exec'),
         module.__dict__, namespace)
    monkeypatch.setattr(module._ReadTransport, '_get', namespace['_get'])
    with pytest.raises(pytest.fail.Exception):
        test_same_uuid_cross_environment_or_changed_account_never_publishes(
            tmp_path, monkeypatch, 'native')


def test_valid_rotated_subject_cannot_reuse_an_existing_facade(tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    r = reader(f)
    from tests.sentinel.live_authority_fixtures import signed_live
    f.owner = replace(f.owner, takeover_epoch=2)
    subject = f.subject.model_copy(update={'takeover_epoch': 2})
    claims = {**f.claims, 'subject': subject.model_dump(mode='json')}
    f.certificate_path.write_bytes(signed_live(claims, f.private_key, f.key_id))
    with pytest.raises(module.MonitoringReadRefused, match='durable subject changed'):
        asyncio.run(r.identify_account())
    assert not f.calls


def test_current_subject_guard_removal_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(module.TradingReadOnly._TradingReadOnly__current)
    source = textwrap.dedent(source)
    needle = 'elif self.__expected != verified.subject:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'elif False:').replace('self.__', 'self._TradingReadOnly__'),
                 '<monitor-subject-mutant>', 'exec'),
         module.__dict__, namespace)
    monkeypatch.setattr(module.TradingReadOnly, '_TradingReadOnly__current', namespace['__current'])
    with pytest.raises(pytest.fail.Exception):
        test_valid_rotated_subject_cannot_reuse_an_existing_facade(tmp_path, monkeypatch)


def test_live_polling_does_not_require_local_paper_exemption(tmp_path, monkeypatch):
    from threading import Event
    from sentinel import execution_collector as collector, local_paper
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    monkeypatch.delenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY', raising=False)
    monkeypatch.delenv('SENTINEL_FILL_NOTIFICATIONS_SINCE', raising=False)
    monkeypatch.delenv('SENTINEL_SEC_USER_AGENT_EMAIL', raising=False)
    monkeypatch.setattr(local_paper, 'enabled', lambda: False)
    monkeypatch.setattr(collector, 'HEARTBEAT', tmp_path / 'heartbeat')
    monkeypatch.setattr(collector.signal, 'signal', lambda *_args: None)
    stop, calls = Event(), []
    def run(operation, *args, **_kwargs):
        calls.append(args)
        stop.set()
    assert collector.run(stopped=stop, runner=run) == 0
    assert calls == [('ACCOUNT',)]
