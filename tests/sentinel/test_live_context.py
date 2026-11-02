"""Canonical LIVE loaders retain original journal/native ownership boundaries."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import hashlib
import inspect
from types import SimpleNamespace

import pytest

from sentinel.authority.canonical import _b64url_encode, canonical_json_bytes
from sentinel.authority.live_runtime import ENROLLMENT_SCHEMA, TRUST_ROOTS_PATH_ENV
from sentinel.authority.model import AuthorityRefused
from sentinel.binding import AccountBinding
from sentinel.execution import live_context as context
from sentinel.execution.contract import BrokerAccountIdentity, BrokerObservation, BrokerOrder, BrokerPosition, Completeness
from sentinel.execution.live_order_policy import LiveOrderDeferred, LiveOrderRefused
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState
from tests.sentinel.live_order_fixtures import DAY, NOW, REFERENCE_SESSION, command, funding, order_fixture
from tests.sentinel.test_live_order_policy import assess


class Cursor:
    def __init__(self, owner):
        self.owner = owner
        self.rows = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, parameters):
        self.owner.queries.append((sql, parameters))
        if "pg_locks" in sql:
            self.rows = ((self.owner.writer,),)
        elif "WHERE broker_order_id=" in sql:
            self.rows = tuple((item.client_key,) for item in self.owner.commands
                              if item.broker_order_id == parameters[0])[:2]
        elif "ORDER BY client_key LIMIT" in sql:
            self.rows = tuple((item.client_key,) for item in self.owner.commands)[:parameters[0]]
        else:
            raise AssertionError("unexpected SQL: " + sql)

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, commands):
        self.commands = commands
        self.writer = True
        self.queries = []

    def cursor(self):
        return Cursor(self)


class Broker:
    def __init__(self, fixture):
        self.account = fixture.account
        self.after = fixture.account
        self.observation = BrokerObservation(NOW, started_at=NOW,
            positions=fixture.positions, account_identity=fixture.account.identity)
        self.calls = []

    async def account_snapshot(self):
        self.calls.append("account")
        return self.account if len(self.calls) == 1 else self.after

    async def observe(self):
        self.calls.append("observe")
        return self.observation


def setup(monkeypatch):
    fixture = order_fixture()
    fixture.bound = AccountBinding(fixture.subject.deployment_id, "alpaca-live", fixture.subject.account_id, 1)
    fixture.plan = ExecutionPlan("plan", REFERENCE_SESSION, DAY, Decimal(1),
        deployment_id=fixture.bound.deployment_id, broker=fixture.bound.broker,
        broker_account_id=fixture.bound.broker_account_id, takeover_epoch=1)
    fixture.conn = Connection(fixture.commitments)
    fixture.broker = Broker(fixture)
    fixture.references = SimpleNamespace(prices={"SEC": Decimal(10)}, decision_session=REFERENCE_SESSION,
                                         unit_factors={"SEC": "3/2"})
    fixture.projection = object()
    fixture.source_checks = []
    monkeypatch.setattr(context.binding_module, "require", lambda _conn: fixture.bound)
    monkeypatch.setattr(context.journal, "load_plan", lambda _conn, _plan_id: fixture.plan)
    monkeypatch.setattr(context.journal, "load_commands", lambda _conn, _identity, client_keys: tuple(
        item for item in fixture.conn.commands if item.client_key in client_keys))
    monkeypatch.setattr(context.target_reprojection, "load_projection", lambda *_args, **_kwargs: fixture.projection)
    monkeypatch.setattr(context.target_reprojection, "assert_projection",
                        lambda *_args, **_kwargs: fixture.source_checks.append("projection"))
    def source(*_args, **_kwargs):
        fixture.source_checks.append("source")
        return fixture.references, SimpleNamespace(for_security=lambda _sid: fixture.request.order_terms)
    monkeypatch.setattr(context.protected_limits, "submission_protection", source)
    monkeypatch.setattr(context, "load_live_funding_admission", lambda: None)
    return fixture


async def load(fixture, **changes):
    arguments = dict(broker=fixture.broker, plan=fixture.plan, binding=fixture.bound,
        client_key=fixture.request.client_key, actions=None, now=lambda: NOW)
    arguments.update(changes)
    return await context.load_live_order_context(fixture.conn, **arguments)


@pytest.mark.asyncio
async def test_original_context_brackets_reads_and_revalidates_authenticated_references(monkeypatch):
    fixture = setup(monkeypatch)
    loaded = await load(fixture)
    assert loaded.request == fixture.request and loaded.commitments == fixture.commitments
    assert loaded.reference_close == 10 and loaded.reference_unit_factor == "3/2"
    assert loaded.account_observed_at == NOW and loaded.funding is None
    assert fixture.broker.calls == ["account", "observe", "account"]
    assert fixture.source_checks == ["projection", "source"]
    assert all(sql.startswith("SELECT") for sql, _params in fixture.conn.queries)


@pytest.mark.asyncio
async def test_no_writer_lock_refuses_before_broker_reads(monkeypatch):
    fixture = setup(monkeypatch)
    fixture.conn.writer = False
    with pytest.raises(LiveOrderRefused, match="WRITER_LOCK"):
        await load(fixture)
    assert fixture.broker.calls == []


@pytest.mark.asyncio
async def test_account_change_between_reads_defers_without_journal_mutation(monkeypatch):
    fixture = setup(monkeypatch)
    fixture.broker.after = replace(fixture.account, cash=Decimal(1001))
    with pytest.raises(LiveOrderDeferred, match="CHANGED_DURING"):
        await load(fixture)


@pytest.mark.asyncio
async def test_additional_native_funding_change_invalidates_an_otherwise_stable_account(monkeypatch):
    from tests.sentinel.live_native_funding_fixtures import native_fixture
    fixture = setup(monkeypatch)
    native, _source = native_fixture()
    facts = native.account.native_funding
    fixture.broker.account = replace(fixture.account, native_funding=facts)
    changed = replace(facts, amounts=tuple((name, Decimal(50) if name == "non_marginable_buying_power" else value)
                                          for name, value in facts.amounts))
    fixture.broker.after = replace(fixture.account, native_funding=changed)
    with pytest.raises(LiveOrderDeferred, match="FUNDING_CHANGED_DURING"):
        await load(fixture)


@pytest.mark.asyncio
async def test_native_funding_bracket_guard_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(context.load_live_order_context)
    needle = "if _native_funding_shape(before.native_funding) != _native_funding_shape(after.native_funding):"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "native-bracket-falsifier", "exec"),
         context.__dict__, namespace)
    monkeypatch.setattr(context, "load_live_order_context", namespace["load_live_order_context"])
    with pytest.raises(pytest.fail.Exception):
        await test_additional_native_funding_change_invalidates_an_otherwise_stable_account(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["partial", "wrong_account", "clock", "unexpected_position"])
async def test_incomplete_wrong_or_changed_observation_never_creates_submit_context(monkeypatch, kind):
    fixture = setup(monkeypatch)
    observation = fixture.broker.observation
    if kind == "partial":
        observation = replace(observation, completeness=Completeness.PARTIAL)
    elif kind == "wrong_account":
        observation = replace(observation, account_identity=BrokerAccountIdentity("alpaca", fixture.subject.account_id))
    elif kind == "clock":
        observation = replace(observation, started_at=NOW-timedelta(seconds=1))
    else:
        observation = replace(observation, positions=(BrokerPosition(fixture.request.instrument, Decimal(1)),))
    fixture.broker.observation = observation
    with pytest.raises(LiveOrderRefused):
        await load(fixture)


@pytest.mark.asyncio
async def test_positive_current_order_requires_recovery_instead_of_duplicate_post(monkeypatch):
    fixture = setup(monkeypatch)
    request = fixture.request
    order = BrokerOrder("native-order", request.client_key, request.instrument, request.side,
        CommandState.ACKNOWLEDGED, request.quantity, submitted_at=NOW,
        order_terms=request.order_terms)
    fixture.broker.observation = replace(fixture.broker.observation, orders=(order,))
    with pytest.raises(LiveOrderDeferred, match="RECOVER_FIRST"):
        await load(fixture)


@pytest.mark.asyncio
async def test_unknown_or_conflicting_native_order_refuses(monkeypatch):
    fixture = setup(monkeypatch)
    request = fixture.request
    order = BrokerOrder("native-order", "foreign", request.instrument, request.side,
        CommandState.ACKNOWLEDGED, request.quantity, submitted_at=NOW,
        order_terms=request.order_terms)
    fixture.broker.observation = replace(fixture.broker.observation, orders=(order,))
    with pytest.raises(LiveOrderRefused, match="FOREIGN_OR_CHANGED"):
        await load(fixture)


@pytest.mark.asyncio
async def test_source_failure_cannot_be_replaced_with_stored_or_caller_price(monkeypatch):
    fixture = setup(monkeypatch)
    def unavailable(*_args, **_kwargs):
        raise ValueError("synthetic source changed")
    monkeypatch.setattr(context.protected_limits, "submission_protection", unavailable)
    with pytest.raises(ValueError, match="source changed"):
        await load(fixture)


@pytest.mark.asyncio
async def test_journal_bound_refuses_before_fetching_full_rows(monkeypatch):
    fixture = setup(monkeypatch)
    monkeypatch.setattr(context, "MAX_CONTEXT_COMMANDS", 0)
    with pytest.raises(LiveOrderRefused, match="JOURNAL_BOUND"):
        await load(fixture)
    assert fixture.broker.calls == []


def test_cancel_loader_names_only_exact_owned_nonterminal_command(monkeypatch):
    fixture = setup(monkeypatch)
    owned = replace(fixture.request, broker_order_id="owned-native-id", state=CommandState.ACKNOWLEDGED)
    fixture.conn.commands = (owned,)
    assert context.load_owned_cancel_command(fixture.conn, binding=fixture.bound, broker_order_id="owned-native-id") == owned
    with pytest.raises(LiveOrderRefused, match="EXACT_OWNED"):
        context.load_owned_cancel_command(fixture.conn, binding=fixture.bound, broker_order_id="foreign")
    fixture.conn.commands = (replace(owned, state=CommandState.FILLED, filled_quantity=owned.quantity,
                                      filled_average_price=Decimal(10)),)
    with pytest.raises(LiveOrderRefused, match="CANCEL_COMMAND_CHANGED"):
        context.load_owned_cancel_command(fixture.conn, binding=fixture.bound, broker_order_id="owned-native-id")


def write_enrollment(path, generated, *, revoked=()):
    root = generated.root
    payload = {"schema": ENROLLMENT_SCHEMA, "roots": [{"key_id": generated.key_id,
        "public_key": _b64url_encode(root.public_key), "not_before": root.not_before.isoformat(),
        "not_after": root.not_after.isoformat(), "status": root.status, "scope": root.scope}],
        "revoked_certificate_sha256": list(revoked)}
    path.write_bytes(canonical_json_bytes(payload))


def test_funding_file_has_no_implicit_path_enrollment_or_credential_access(tmp_path):
    assert context.load_live_funding_admission(env={}) is None
    assert context.load_live_funding_admission(env={context.FUNDING_CERTIFICATE_PATH_ENV: ""}) is None
    with pytest.raises(AuthorityRefused, match="absolute"):
        context.load_live_funding_admission(env={context.FUNDING_CERTIFICATE_PATH_ENV: "relative.json"})
    public = tmp_path / "funding.json"
    public.write_bytes(b"public-data")
    with pytest.raises(AuthorityRefused, match=TRUST_ROOTS_PATH_ENV):
        context.load_live_funding_admission(env={context.FUNDING_CERTIFICATE_PATH_ENV: str(public)})


def test_public_file_generation_and_revocations_are_fresh_not_cached(tmp_path):
    fixture = order_fixture()
    generated = funding(fixture)
    certificate = tmp_path / "funding.json"
    enrollment = tmp_path / "enrollment.json"
    certificate.write_bytes(generated.admission.certificate)
    write_enrollment(enrollment, generated)
    loaded = context.load_live_funding_admission(env={context.FUNDING_CERTIFICATE_PATH_ENV: str(certificate),
                                                   TRUST_ROOTS_PATH_ENV: str(enrollment)})
    assert assess(fixture, receipt=loaded).allowed
    write_enrollment(enrollment, generated,
        revoked=(hashlib.sha256(generated.admission.certificate).hexdigest(),))
    with pytest.raises(LiveOrderRefused, match="SIGNATURE_OR_CLAIMS"):
        assess(fixture, receipt=loaded)


@pytest.mark.asyncio
async def test_held_book_guard_removal_is_detected_behaviorally(monkeypatch):
    source = inspect.getsource(context._check_observation)
    needle = "if actual != expected:"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "live-context-book-falsifier", "exec"),
         context.__dict__, namespace)
    monkeypatch.setattr(context, "_check_observation", namespace["_check_observation"])
    with pytest.raises(pytest.fail.Exception):
        await test_incomplete_wrong_or_changed_observation_never_creates_submit_context(monkeypatch, "unexpected_position")
