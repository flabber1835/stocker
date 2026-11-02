"""Attended LIVE binding is GET-only, inert, exact and transactionally recorded."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
import inspect
from types import SimpleNamespace

import httpx
import pytest

from sentinel.binding import AccountBinding
from sentinel.authority import live_provisioning as provisioning
from sentinel.authority.live import AuthorityRefused, require_live_adapter_admission
from sentinel.authority.model import RolloutMode, RolloutState
from sentinel.execution.native_readonly import ReadOnlyAlpacaClient
from tests.sentinel.live_authority_fixtures import live_fixture, signed_live


class Connection:
    def __init__(self):
        self.bound = None
        self.pending_bound = None
        self.events = []
        self.pending_events = []
        self.financial_history = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        connection = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params=None):
                self.result = (None, None) if "holder_id,expires_at" in sql else (connection.financial_history,)

            def fetchone(self):
                return self.result

        return Cursor()

    def commit(self):
        self.bound = self.pending_bound
        self.events.extend(self.pending_events)
        self.pending_events.clear()
        self.commits += 1

    def rollback(self):
        self.pending_bound = None
        self.pending_events.clear()
        self.rollbacks += 1


def setup(monkeypatch, *, book=None, on_request=None):
    fixture = live_fixture()
    conn = Connection()
    control = SimpleNamespace(enabled=False, kill_switch_engaged=True, binding=None, generation=1)
    monkeypatch.setattr(provisioning.binding, "load", lambda connection: connection.bound)
    monkeypatch.setattr(provisioning.binding, "require", lambda connection: connection.bound)

    def bind(connection, *, deployment_id, broker, broker_account_id, notes, commit):
        assert commit is False
        assert connection.bound is None
        connection.pending_bound = AccountBinding(deployment_id, broker, broker_account_id, 1, notes=notes)
        return connection.pending_bound

    monkeypatch.setattr(provisioning.binding, "bind", bind)
    monkeypatch.setattr(provisioning.journal, "writer_lock", lambda connection: nullcontext())
    monkeypatch.setattr(provisioning.automation_store, "load_control", lambda connection, **kwargs: control)
    monkeypatch.setattr(provisioning, "PostgresOwnershipStore", lambda connection, **kwargs: connection)
    monkeypatch.setattr(provisioning, "record", lambda connection, state, **detail: connection.pending_events.append((state, detail)))
    claims = {name: fixture.claims[name] for name in (
        "certificate_id", "issued_at", "not_before", "subject", "runtime_bindings")}
    claims.update(expires_at=(fixture.now + timedelta(minutes=15)).isoformat(),
                  permitted_operations=["BIND_EMPTY_LIVE"])
    roots = {fixture.key_id: replace(fixture.roots[fixture.key_id], scope="LIVE_ADMIN")}
    admission = provisioning.LiveProvisioningAdmission(
        signed_live(claims, fixture.private_key, fixture.key_id, schema=provisioning.LIVE_ADMIN_SCHEMA),
        fixture.context, roots)
    trace = []
    account = {"id": fixture.subject.account_id, "status": "ACTIVE", "trading_blocked": False,
               "account_blocked": False, "trade_suspended_by_user": False,
               "cash": "100", "equity": "100", "buying_power": "100", "multiplier": "1",
               "long_market_value": "0", "short_market_value": "0"}

    def transport(request):
        trace.append((request.method, request.url.path))
        if on_request is not None:
            on_request(request, trace, account, roots, fixture)
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=account)
        return httpx.Response(200, json=(book or {}).get(request.url.path, []))

    http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = ReadOnlyAlpacaClient(fixture.subject, api_key="offline-test-key", secret_key="offline-test-secret", http_client=http)
    fixture.conn, fixture.control, fixture.admission, fixture.client = conn, control, admission, client
    fixture.http, fixture.trace, fixture.claims, fixture.admin_roots = http, trace, claims, roots
    return fixture


async def bind(fixture, **changes):
    args = dict(client=fixture.client, admission=fixture.admission,
                confirm_live_account=fixture.subject.account_id,
                confirm_deployment=fixture.subject.deployment_id,
                confirm_empty_live_account=True, actor="offline-owner", reason="explicit new live deployment",
                clock=lambda: fixture.now, sleep=lambda _: _no_wait())
    args.update(changes)
    return await provisioning.bind_empty_live_account(fixture.conn, **args)


async def _no_wait():
    pass


@pytest.mark.asyncio
async def test_two_stable_get_only_observations_commit_binding_and_ownership_together(monkeypatch):
    fixture = setup(monkeypatch)
    try:
        bound = await bind(fixture)
        assert bound.broker == "alpaca-live" and bound.broker_account_id == fixture.subject.account_id
        assert fixture.conn.commits == 1 and fixture.conn.rollbacks == 0
        assert len(fixture.conn.events) == 1
        assert len(fixture.trace) == 10 and {method for method, _ in fixture.trace} == {"GET"}
        assert fixture.control.enabled is False and fixture.control.kill_switch_engaged is True
        before = len(fixture.trace)
        with pytest.raises(AuthorityRefused, match="existing account binding"):
            await bind(fixture)
        assert len(fixture.trace) == before
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"confirm_empty_live_account": False}, {"confirm_live_account": "wrong"}, {"confirm_deployment": "wrong"}])
async def test_exact_attended_confirmations_precede_all_broker_reads(monkeypatch, change):
    fixture = setup(monkeypatch)
    try:
        with pytest.raises(AuthorityRefused):
            await bind(fixture, **change)
        assert fixture.trace == [] and fixture.conn.bound is None
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("book", [{"/v2/positions": [{"qty": "1"}]}, {"/v2/orders": [{"id": "open-order"}]}])
async def test_nonempty_broker_book_is_never_adopted_or_liquidated(monkeypatch, book):
    fixture = setup(monkeypatch, book=book)
    try:
        with pytest.raises(AuthorityRefused, match="nonempty"):
            await bind(fixture)
        assert fixture.conn.bound is None and fixture.conn.events == []
        assert {method for method, _ in fixture.trace} == {"GET"}
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
async def test_inert_control_and_financial_history_refuse_before_contact(monkeypatch):
    fixture = setup(monkeypatch)
    try:
        fixture.control.enabled = True
        with pytest.raises(AuthorityRefused, match="disabled"):
            await bind(fixture)
        fixture.control.enabled = False
        fixture.conn.financial_history = True
        with pytest.raises(AuthorityRefused, match="financial"):
            await bind(fixture)
        assert fixture.trace == []
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
async def test_changed_account_and_revoked_authority_rollback_without_binding(monkeypatch):
    def change(request, trace, account, roots, fixture):
        if len(trace) == 6:
            account.update(cash="200", equity="200", buying_power="200")

    fixture = setup(monkeypatch, on_request=change)
    try:
        with pytest.raises(AuthorityRefused, match="between empty-book"):
            await bind(fixture)
        assert fixture.conn.bound is None and fixture.conn.commits == 0
        fixture.admin_roots[fixture.key_id] = replace(fixture.admin_roots[fixture.key_id], status="REVOKED")
        before = len(fixture.trace)
        with pytest.raises(AuthorityRefused, match="enrolled"):
            await bind(fixture)
        assert len(fixture.trace) == before
    finally:
        await fixture.http.aclose()


def test_administrative_and_execution_authority_are_disjoint(monkeypatch):
    fixture = setup(monkeypatch)
    with pytest.raises(AuthorityRefused, match="LIVE adapter admission"):
        require_live_adapter_admission(fixture.admission, base_url="https://api.alpaca.markets", now=fixture.now)
    execution = live_fixture(fixture.now).admission
    with pytest.raises(AuthorityRefused, match="separate LIVE provisioning"):
        provisioning.require_live_provisioning_admission(execution, now=fixture.now)


def test_binding_guard_has_behavioral_falsifier(monkeypatch):
    fixture = setup(monkeypatch)
    fixture.conn.bound = AccountBinding("previous", "alpaca", fixture.subject.account_id, 1)
    with pytest.raises(AuthorityRefused, match="existing account binding"):
        provisioning._inert(fixture.conn)
    source = inspect.getsource(provisioning._inert)
    needle = "if binding.load(conn) is not None:"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "live-binding-falsifier", "exec"),
         provisioning._inert.__globals__, namespace)
    assert namespace["_inert"](fixture.conn) == 1


def test_activation_keeps_kill_and_release_is_separate_exact_confirmation(monkeypatch):
    fixture = setup(monkeypatch)
    fixture.conn.bound = AccountBinding(fixture.subject.deployment_id, "alpaca-live", fixture.subject.account_id, 1)
    verified = SimpleNamespace(sha256="a" * 64)
    operations, actions = [], []
    monkeypatch.setattr(provisioning, "require_current_live_authority",
                        lambda conn, **kwargs: operations.append(kwargs["required_operation"]) or verified)
    monkeypatch.setattr(provisioning.repository, "load_rollout_state", lambda conn: RolloutState(RolloutMode.PINNED_1_00, 1))
    monkeypatch.setattr(provisioning.automation_store, "activate", lambda conn, **kwargs: actions.append(("activate", kwargs)) or "KILLED")
    monkeypatch.setattr(provisioning.automation_store, "release_kill", lambda conn, **kwargs: actions.append(("release", kwargs)) or "RELEASED")
    context = dict(base_url="https://api.alpaca.markets", runtime_identity={}, strategy_identity={},
                   automation_config_sha256="b" * 64, confirm_live_account=fixture.subject.account_id,
                   confirm_deployment=fixture.subject.deployment_id, confirm_real_money=True,
                   actor="owner", reason="reviewed offline activation")
    assert provisioning.activate_live_automation(fixture.conn, **context) == "KILLED"
    assert [action for action, _ in actions] == ["activate"]
    assert operations == ["AUTOMATION", "SUBMIT", "CANCEL"]
    assert actions[0][1]["binding"].broker == "alpaca-live"
    assert provisioning.release_live_kill(fixture.conn, **context) == "RELEASED"
    with pytest.raises(AuthorityRefused, match="real-money"):
        provisioning.release_live_kill(fixture.conn, **{**context, "confirm_real_money": False})
    assert len(actions) == 2
