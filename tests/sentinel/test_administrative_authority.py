"""Adversarial tests for pre-binding signed administrative broker access."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.support.postgres import _EphemeralPostgres

from sentinel import administrative_authority as administrative
from sentinel import authority, binding, schema
from sentinel.feed import store as feed_store
from sentinel.broker import CloseResult, SentinelBroker
from sentinel.execution.commands import Command, LEGACY_MIGRATION_PLAN_PREFIX
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerInstrument, CommandOutcome, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState
from sentinel.guarded_administration import (
    AdministrativeAccessGrant,
    AdministrativeBrokerGuard,
    AdministrativeBrokerOperation,
    GuardedAdministrativeBroker,
    GuardedAdministrativeExecutionBroker,
    build_fresh_administrative_guard,
)

REPO = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))
from sentinel.ownership import AccountObservation, OpenOrder


@pytest.fixture(autouse=True)
def _authorized_runtime_surface(monkeypatch, tmp_path):
    from sentinel import __main__ as cli

    marker = tmp_path / "authorized-runtime-v1"
    marker.write_bytes(cli.AUTHORIZED_RUNTIME_MARKER_BYTES)
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_MARKER", marker)
    monkeypatch.setenv(
        cli.AUTHORIZED_RUNTIME_ENV, cli.AUTHORIZED_RUNTIME_VALUE)


class CountingBroker(SentinelBroker):
    def __init__(self, account_id="paper-123", observation=None):
        self.account_id = account_id
        self.observation = observation or AccountObservation(
            positions={}, open_orders=())
        self.reads = []
        self.mutations = []

    async def account(self):
        self.reads.append("account")
        return SimpleNamespace(raw={"account_number": self.account_id})

    async def observe(self):
        self.reads.append("observe")
        return self.observation

    async def cancel_orders(self, order_ids):
        self.mutations.append(("cancel", tuple(order_ids)))
        return len(order_ids)

    async def close_position(self, ticker):
        self.mutations.append(("close", ticker))
        return CloseResult(ticker, "unsafe", "accepted", None)

    async def find_liquidation(self, client_key):
        self.reads.append(("find", client_key))
        return None

    async def submit_liquidation(self, command):
        self.mutations.append(("submit", command.client_key))
        return CommandOutcome(
            state=CommandState.ACKNOWLEDGED, broker_order_id="order-1")


def grant(operation=administrative.ADMIN_MIGRATE):
    return AdministrativeAccessGrant(
        operation=operation, deployment_id="nas-01",
        broker_account_id="paper-123", takeover_epoch=1)


def migration_observation():
    return AccountObservation(
        positions={"AAA": Decimal("3")},
        position_security_ids={"AAA": "asset-aaa"},
        open_orders=(
            OpenOrder("order-a", "OLD", "buy"),
            OpenOrder("order-b", "OLD", "sell"),
        ))


def migration_command(*, quantity=Decimal("3")) -> Command:
    deployment = DeploymentIdentity(
        deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123", takeover_epoch=1)
    identity = CommandIdentity(
        deployment=deployment,
        plan_id=f"{LEGACY_MIGRATION_PLAN_PREFIX}2026-08-13",
        security_id="legacy:alpaca:asset-aaa")
    return Command(
        identity=identity,
        instrument=BrokerInstrument(
            security_id=identity.security_id, symbol="AAA",
            broker_id="asset-aaa"),
        side=Side.SELL, quantity=quantity,
        state=CommandState.SEND_PENDING)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def admin_claims(*, operation=administrative.ADMIN_MIGRATE,
                 expires_at="2026-08-20T00:00:00Z"):
    from test_signed_authority import claims

    value = claims(expires_at=expires_at)
    value["unattended_automation"] = False
    value["allowed_rollout_modes"] = ["PINNED_1_00"]
    value["permitted_operations"] = [operation]
    value["rollout"].update({
        "from_mode": "PINNED_1_00", "from_version": 1,
        "from_certificate_sha256": None,
        "to_mode": "PINNED_1_00", "to_version": 2,
    })
    return value


def admin_context(value):
    return administrative.AdministrativeAuthorityContext(
        **value["subject"], bindings=value["bindings"])


def signed(value):
    unsigned = authority.unsigned_envelope_bytes(
        key_id=ADMIN_KEY_ID, claims=value)
    return authority.signed_envelope_bytes(
        key_id=ADMIN_KEY_ID, claims=value,
        signature=ADMIN_PRIVATE_KEY.sign(unsigned))


def roots():
    return ADMIN_ROOTS


NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
ADMIN_PRIVATE_KEY = Ed25519PrivateKey.generate()
ADMIN_PUBLIC_KEY = ADMIN_PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
ADMIN_KEY_ID = authority.key_id_for_public_key(ADMIN_PUBLIC_KEY)
ADMIN_ROOTS = {
    ADMIN_KEY_ID: authority.TrustRoot(
        ADMIN_KEY_ID, ADMIN_PUBLIC_KEY, "ACTIVE",
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2030, 1, 1, tzinfo=timezone.utc)),
}


def test_base_signed_claims_keep_admin_and_execution_authority_disjoint():
    from test_signed_authority import claims

    value = claims()
    value["unattended_automation"] = False
    value["allowed_rollout_modes"] = ["PINNED_1_00"]
    value["permitted_operations"] = ["ADMIN_INSPECT", "ADMIN_MIGRATE"]
    value["rollout"].update({
        "from_mode": "PINNED_1_00", "from_version": 1,
        "from_certificate_sha256": None,
        "to_mode": "PINNED_1_00", "to_version": 2,
    })
    assert authority.validate_certificate_claims(value)[
        "permitted_operations"] == ["ADMIN_INSPECT", "ADMIN_MIGRATE"]

    mixed = replace_mapping(
        value, permitted_operations=["ADMIN_INSPECT", "PREPARE_READ"])
    with pytest.raises(authority.AuthorityRefused, match="cannot be combined"):
        authority.validate_certificate_claims(mixed)
    both_destructive = replace_mapping(
        value, permitted_operations=["ADMIN_ADOPT", "ADMIN_MIGRATE"])
    with pytest.raises(authority.AuthorityRefused, match="both first migration"):
        authority.validate_certificate_claims(both_destructive)


def test_admin_config_identity_names_all_concrete_broker_adapters(tmp_path):
    roots_path = tmp_path / "roots.json"
    roots_path.write_text("{}", encoding="utf-8")
    identity = administrative.administrative_execution_config_identity(
        paper_base_url=authority.PAPER_BASE_URL,
        trust_roots_path=roots_path)
    assert identity["adapters"] == {
        "inspection": "sentinel.execution.alpaca.AlpacaExecutionBroker",
        "empty_account": "sentinel.empty_account.GuardedEmptyAccountBroker",
        "migration": "sentinel.broker.AlpacaSentinelBroker",
    }


def test_admin_envelope_refuses_no_go_evidence_before_signing():
    value = admin_claims(operation=administrative.ADMIN_INSPECT)
    value["bindings"] = {
        **value["bindings"],
        "wealth_core": {**value["bindings"]["wealth_core"],
                        "verdict": "NO-GO"},
    }
    with pytest.raises(authority.AuthorityRefused, match="not GO"):
        signed(value)


def test_execution_certificate_installer_refuses_admin_only_envelope():
    value = admin_claims(operation=administrative.ADMIN_INSPECT)
    payload = signed(value)
    digest = __import__("hashlib").sha256(payload).hexdigest()

    # The refusal precedes every execution-authority/context/database access.
    with pytest.raises(authority.AuthorityRefused, match="separate administrative"):
        authority.install_signed_certificate(
            object(), certificate_bytes=payload, confirm_sha256=digest,
            context=object(), now=NOW, trust_roots=roots())


def test_committed_disabled_root_refuses_admin_certificate_before_database():
    from test_signed_authority import signed as sign_with_disabled_root

    payload = sign_with_disabled_root(
        admin_claims(operation=administrative.ADMIN_INSPECT))
    digest = __import__("hashlib").sha256(payload).hexdigest()
    with pytest.raises(authority.AuthorityRefused, match="disabled"):
        administrative.install_administrative_certificate(
            object(), certificate_bytes=payload, confirm_sha256=digest,
            context=object(), reason="must remain disabled", now=NOW)


def replace_mapping(value, **changes):
    copied = dict(value)
    copied.update(changes)
    return copied


def test_fresh_check_surrounds_each_read_and_each_exact_mutation():
    checks = []
    broker = CountingBroker(observation=migration_observation())
    guarded = GuardedAdministrativeBroker(
        inner=broker, grant=grant(),
        guard=AdministrativeBrokerGuard(
            check=lambda _grant, operation, result: checks.append(
                (operation.value, result is not None))))

    async def run():
        await guarded.account()
        await guarded.observe()
        await guarded.cancel_orders(("order-a", "order-b"))
        broker.observation = AccountObservation(
            positions={"AAA": Decimal("3")},
            position_security_ids={"AAA": "asset-aaa"})
        await guarded.observe()
        await guarded.find_liquidation(migration_command().client_key)
        await guarded.submit_liquidation(migration_command())
        with pytest.raises(authority.AuthorityRefused, match="already attempted"):
            await guarded.submit_liquidation(migration_command())

    asyncio.run(run())
    assert checks == [
        ("account", False), ("account", True),
        ("observe", False), ("observe", True),
        ("cancel_order", False), ("cancel_order", False),
        ("observe", False), ("observe", True),
        ("find_liquidation", False), ("find_liquidation", False),
        ("submit_liquidation", False),
    ]
    assert broker.mutations == [
        ("cancel", ("order-a",)), ("cancel", ("order-b",)),
        ("submit", migration_command().client_key),
    ]


def test_each_guard_check_uses_a_distinct_closed_database_view(monkeypatch):
    connections = []
    verified = []

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    def connect():
        value = Connection()
        connections.append(value)
        return value

    monkeypatch.setattr(
        administrative, "require_administrative_authority",
        lambda conn, **_kwargs: verified.append(conn))
    guard = build_fresh_administrative_guard(
        connection_factory=connect,
        paper_base_url=authority.PAPER_BASE_URL,
        runtime_identity=lambda: {}, strategy_identity=lambda: {},
        automation_config_sha256="a" * 64)
    guard.check(grant(), AdministrativeBrokerOperation.ACCOUNT, None)
    guard.check(grant(), AdministrativeBrokerOperation.OBSERVE, None)

    assert verified == connections
    assert len({id(conn) for conn in connections}) == 2
    assert all(conn.closed for conn in connections)


def test_expiry_or_revocation_race_immediately_before_mutation_is_zero_call():
    broker = CountingBroker(observation=migration_observation())
    checks = 0

    def race(_grant, operation, _result):
        nonlocal checks
        checks += 1
        if operation.value == "cancel_order":
            raise authority.AuthorityRefused("certificate revoked")

    guarded = GuardedAdministrativeBroker(
        inner=broker, grant=grant(),
        guard=AdministrativeBrokerGuard(check=race))

    async def run():
        await guarded.account()
        await guarded.observe()
        with pytest.raises(authority.AuthorityRefused, match="revoked"):
            await guarded.cancel_orders(("order-a",))

    asyncio.run(run())
    assert checks == 5
    assert broker.mutations == []


def test_unobserved_cancel_and_nonexact_liquidation_are_zero_call():
    broker = CountingBroker(observation=migration_observation())
    guarded = GuardedAdministrativeBroker(
        inner=broker, grant=grant(),
        guard=AdministrativeBrokerGuard(
            check=lambda _grant, _operation, _result: None))

    async def run():
        await guarded.account()
        await guarded.observe()
        with pytest.raises(authority.AuthorityRefused, match="latest complete"):
            await guarded.cancel_orders(("order-a", "order-not-observed"))
        with pytest.raises(authority.AuthorityRefused, match="Sentinel client key"):
            await guarded.find_liquidation("foreign-client-key")
        broker.observation = AccountObservation(
            positions={"AAA": Decimal("3")},
            position_security_ids={"AAA": "asset-aaa"})
        await guarded.observe()
        with pytest.raises(authority.AuthorityRefused, match="quantity"):
            await guarded.submit_liquidation(
                migration_command(quantity=Decimal("2")))

    asyncio.run(run())
    assert broker.mutations == []
    assert ("find", "foreign-client-key") not in broker.reads


def test_account_mismatch_prevents_book_read_and_every_mutation():
    broker = CountingBroker(account_id="paper-wrong")
    guarded = GuardedAdministrativeBroker(
        inner=broker, grant=grant(),
        guard=AdministrativeBrokerGuard(
            check=lambda _grant, _operation, _result: None))

    async def run():
        with pytest.raises(authority.AuthorityRefused, match="different"):
            await guarded.account()
        with pytest.raises(authority.AuthorityRefused, match="identified"):
            await guarded.observe()
        with pytest.raises(authority.AuthorityRefused, match="identified"):
            await guarded.cancel_orders(("order-a",))

    asyncio.run(run())
    assert broker.reads == ["account"]
    assert broker.mutations == []


def test_inspection_grant_and_broker_native_close_are_structurally_read_only():
    broker = CountingBroker()
    inspect = GuardedAdministrativeBroker(
        inner=broker, grant=grant(administrative.ADMIN_INSPECT),
        guard=AdministrativeBrokerGuard(
            check=lambda _grant, _operation, _result: None))

    async def run():
        await inspect.account()
        await inspect.observe()
        with pytest.raises(authority.AuthorityRefused, match="read-only"):
            await inspect.cancel_orders(("order-a",))
        with pytest.raises(authority.AuthorityRefused, match="read-only"):
            await inspect.submit_liquidation(SimpleNamespace(client_key="x"))
        migrate = GuardedAdministrativeBroker(
            inner=broker, grant=grant(),
            guard=AdministrativeBrokerGuard(
                check=lambda _grant, _operation, _result: None))
        await migrate.account()
        with pytest.raises(authority.AuthorityRefused, match="broker-native close"):
            await migrate.close_position("AAA")

    asyncio.run(run())
    assert broker.mutations == []


def test_known_admin_wrapper_preserves_concrete_adapter_certification():
    from sentinel.paper import inspection as paper_inspection
    from sentinel.execution.simulator import SimulatedBroker

    wrapped = GuardedAdministrativeExecutionBroker(
        inner=SimulatedBroker(),
        grant=grant(administrative.ADMIN_INSPECT),
        guard=AdministrativeBrokerGuard(
            check=lambda _grant, _operation, _result: None))
    paper_inspection._require_certified_paper_broker(wrapped)  # noqa: SLF001
    assert not hasattr(wrapped, "certified_inner")

    with pytest.raises(TypeError, match="certified concrete"):
        GuardedAdministrativeExecutionBroker(
            inner=object(), grant=grant(administrative.ADMIN_INSPECT),
            guard=AdministrativeBrokerGuard(
                check=lambda _grant, _operation, _result: None))


def test_cli_authority_must_pass_before_broker_construction(monkeypatch):
    from sentinel import __main__ as cli

    constructed = False

    def build(_config):
        nonlocal constructed
        constructed = True
        return CountingBroker()

    monkeypatch.setattr(cli, "build_broker", build)
    monkeypatch.setattr(
        cli, "_require_administrative_access",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            authority.AuthorityRefused("no active signed admin certificate")))
    with pytest.raises(authority.AuthorityRefused, match="no active"):
        cli._authorized_administrative_access(  # noqa: SLF001
            object(), config=SimpleNamespace(base_url=authority.PAPER_BASE_URL),
            operation=administrative.ADMIN_INSPECT,
            deployment_id="nas-01", broker_account_id="paper-123",
            takeover_epoch=1)
    assert constructed is False


def test_every_admin_broker_command_authorizes_before_construction(monkeypatch):
    from sentinel import __main__ as cli
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig

    class Connection:
        def close(self):
            pass

    config = SentinelConfig(
        alpaca_key="PKTEST", alpaca_secret="secret",
        base_url=DEFAULT_BASE_URL, state_dir=Path("/tmp/sentinel-test"),
        max_cycles=1, poll_seconds=0,
        database_url="postgresql://test/db")
    constructed = []
    monkeypatch.setattr(feed_store, "connect", lambda _url: Connection())
    monkeypatch.setattr(schema, "ensure_schema", lambda _conn: None)
    monkeypatch.setattr(binding, "load", lambda _conn: None)
    monkeypatch.setattr(
        binding, "require", lambda _conn: binding.AccountBinding(
            "nas-01", "alpaca", "paper-123", 1))
    monkeypatch.setattr(cli, "_administrative_epoch", lambda *_a, **_k: 1)
    monkeypatch.setattr(
        cli, "_authorized_administrative_access",
        lambda *_a, **_k: (_ for _ in ()).throw(
            authority.AuthorityRefused("signed admin authority unavailable")))
    monkeypatch.setattr(
        cli, "build_broker",
        lambda *_a, **_k: constructed.append("legacy"))
    monkeypatch.setattr(
        cli, "build_execution_broker",
        lambda *_a, **_k: constructed.append("execution"))

    calls = (
        cli._inspect_paper_account(  # noqa: SLF001
            config, SimpleNamespace(
                deployment_id="nas-01", expect_account="paper-123")),
        cli._migration_plan(  # noqa: SLF001
            config, SimpleNamespace(
                deployment_id="nas-01", expect_account="paper-123",
                sessions=252)),
        cli._migrate_account(  # noqa: SLF001
            config, SimpleNamespace(
                deployment_id="nas-01", expect_account="paper-123",
                notes=None)),
        cli._adopt_restored(  # noqa: SLF001
            config, SimpleNamespace(
                confirm_old_credentials_revoked=True,
                confirm_paper_account="paper-123", notes=None)),
    )
    assert [asyncio.run(call) for call in calls] == [
        cli.EXIT_NOT_ESTABLISHED,
        cli.EXIT_NOT_ESTABLISHED,
        cli.EXIT_NOT_ESTABLISHED,
        cli.EXIT_NOT_ESTABLISHED,
    ]
    assert constructed == []


def test_final_binding_recheck_hook_runs_after_stable_observation():
    # The hook is intentionally on the handover API rather than hidden in the
    # CLI, so a future caller cannot omit the last pre-binding verification.
    import inspect
    from sentinel import handover

    source = inspect.getsource(handover._migrate_account_locked)  # noqa: SLF001
    assert source.index("authority_check()") < source.index(
        "OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED")


def test_adopt_rechecks_authority_before_epoch_mutation(conn):
    binding.bind(
        conn, deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123")

    def authority_lost():
        raise authority.AuthorityRefused("administrative certificate expired")

    with pytest.raises(authority.AuthorityRefused, match="expired"):
        binding.adopt_restored(
            conn, observed=BrokerAccountIdentity("alpaca", "paper-123"),
            expected_account="paper-123", authority_check=authority_lost)
    assert binding.require(conn).takeover_epoch == 1


def test_migration_rechecks_authority_before_ownership_binding(conn):
    from sentinel import handover

    broker = CountingBroker()

    def authority_lost():
        raise authority.AuthorityRefused("administrative certificate revoked")

    with pytest.raises(authority.AuthorityRefused, match="revoked"):
        asyncio.run(handover.migrate_account(
            broker=broker, conn=conn, deployment_id="nas-01",
            expected_account="paper-123", max_cycles=3, poll_seconds=0,
            sleep=lambda _seconds: asyncio.sleep(0),
            authority_check=authority_lost))
    assert binding.load(conn) is None
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_ownership_events")
        assert cur.fetchone()[0] == 0


def test_cli_parser_keeps_admin_lifecycle_explicit_and_exact(monkeypatch):
    from sentinel import __main__ as cli
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig

    config = SentinelConfig(
        alpaca_key="PKTEST", alpaca_secret="secret",
        base_url=DEFAULT_BASE_URL, state_dir=Path("/tmp/sentinel-test"),
        max_cycles=1, poll_seconds=0,
        database_url="postgresql://test/db")
    seen = {}
    monkeypatch.setattr(
        cli.SentinelConfig, "from_env", classmethod(lambda cls: config))
    for command, function in (
            ("install-administrative-certificate",
             "_install_administrative_certificate"),
            ("activate-administrative-certificate",
             "_activate_administrative_certificate"),
            ("revoke-administrative-certificate",
             "_revoke_administrative_certificate")):
        monkeypatch.setattr(
            cli, function,
            lambda _config, args, name=command: (
                seen.__setitem__(name, vars(args)), cli.EXIT_OK)[1])
    assert cli.main([
        "install-administrative-certificate", "--certificate", "admin.json",
        "--confirm-certificate-sha256", "a" * 64,
        "--deployment-id", "nas-01", "--expect-account", "paper-123",
        "--takeover-epoch", "1", "--reason", "ticket",
        "--confirm-install-administrative-certificate"]) == cli.EXIT_OK
    assert cli.main([
        "activate-administrative-certificate", "--certificate-sha256", "a" * 64,
        "--deployment-id", "nas-01", "--expect-account", "paper-123",
        "--takeover-epoch", "1", "--reason", "ticket",
        "--confirm-activate-administrative-certificate"]) == cli.EXIT_OK
    assert cli.main([
        "revoke-administrative-certificate", "--certificate-sha256", "a" * 64,
        "--reason", "complete",
        "--confirm-revoke-administrative-certificate"]) == cli.EXIT_OK
    assert seen["install-administrative-certificate"]["takeover_epoch"] == 1
    assert seen["activate-administrative-certificate"][
        "confirm_supersedes_certificate_sha256"] is None


def test_runbook_uses_only_digest_pinned_surface_for_admin_broker_access():
    text = (REPO / "docs" / "sentinel-paper-activation.md").read_text(
                encoding="utf-8")
    commands = (
        "inspect-paper-account", "migration-plan", "migrate-account",
        "adopt-restored-account", "prepare-paper-plan", "execute-paper-plan",
    )
    for command in commands:
        assert f"bash scripts/sentinel-authorized-cli.sh {command}" in text
        assert f"$COMPOSE run --rm sentinel {command}" not in text


def test_admin_certificate_lifecycle_restart_expiry_and_revocation(conn):
    value = admin_claims()
    payload = signed(value)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    staged = administrative.install_administrative_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=admin_context(value), reason="approved migration",
        now=NOW, trust_roots=roots())
    assert staged.status == "STAGED"
    with pytest.raises(authority.AuthorityRefused, match="already installed"):
        administrative.install_administrative_certificate(
            conn, certificate_bytes=payload, confirm_sha256=digest,
            context=admin_context(value), reason="duplicate",
            now=NOW, trust_roots=roots())
    with pytest.raises(authority.AuthorityRefused, match="no signed.*active"):
        administrative.load_active_administrative_certificate(
            conn, now=NOW, trust_roots=roots())
    active = administrative.activate_administrative_certificate(
        conn, certificate_sha256=digest, context=admin_context(value),
        reason="approved migration", now=NOW, trust_roots=roots())
    assert active.status == "ACTIVE"
    # A fresh load is the restart boundary: exact bytes are re-verified.
    assert administrative.load_active_administrative_certificate(
        conn, now=NOW, trust_roots=roots()).certificate_sha256 == digest
    with pytest.raises(authority.AuthorityRefused, match="expired"):
        administrative.load_active_administrative_certificate(
            conn, now=datetime(2026, 8, 21, tzinfo=timezone.utc),
            trust_roots=roots())
    administrative.revoke_administrative_certificate(
        conn, certificate_sha256=digest, reason="migration complete")
    with pytest.raises(authority.AuthorityRefused, match="no signed.*active"):
        administrative.load_active_administrative_certificate(
            conn, now=NOW, trust_roots=roots())


def test_admin_install_refuses_account_or_binding_mismatch(conn):
    value = admin_claims()
    payload = signed(value)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    wrong = replace(
        admin_context(value), broker_account_id="paper-wrong")
    with pytest.raises(authority.AuthorityRefused, match="subject"):
        administrative.install_administrative_certificate(
            conn, certificate_bytes=payload, confirm_sha256=digest,
            context=wrong, reason="wrong account", now=NOW,
            trust_roots=roots())
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_signed_administrative_certificates")
        assert cur.fetchone()[0] == 0

    binding.bind(
        conn, deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123")
    with pytest.raises(authority.AuthorityRefused, match="before.*bound"):
        administrative.install_administrative_certificate(
            conn, certificate_bytes=payload, confirm_sha256=digest,
            context=admin_context(value), reason="already bound", now=NOW,
            trust_roots=roots())


def test_durable_key_revocation_invalidates_admin_certificate(conn):
    value = admin_claims(operation=administrative.ADMIN_INSPECT)
    payload = signed(value)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    administrative.install_administrative_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=admin_context(value), reason="inspection", now=NOW,
        trust_roots=roots())
    administrative.activate_administrative_certificate(
        conn, certificate_sha256=digest, context=admin_context(value),
        reason="inspection", now=NOW, trust_roots=roots())
    authority.revoke_signed_key(
        conn, key_id=ADMIN_KEY_ID, reason="key compromised")
    with pytest.raises(authority.AuthorityRefused, match="key is durably revoked"):
        administrative.load_active_administrative_certificate(
            conn, now=NOW, trust_roots=roots())


def test_globally_revoked_key_cannot_install_admin_certificate(conn):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_execution_key_revocations (key_id,reason)"
            " VALUES (%s,%s)",
            (ADMIN_KEY_ID, "offline compromise notice"))
    conn.commit()
    value = admin_claims(operation=administrative.ADMIN_INSPECT)
    payload = signed(value)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    with pytest.raises(authority.AuthorityRefused, match="signing key.*revoked"):
        administrative.install_administrative_certificate(
            conn, certificate_bytes=payload, confirm_sha256=digest,
            context=admin_context(value), reason="must refuse", now=NOW,
            trust_roots=roots())
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_signed_administrative_certificates")
        assert cur.fetchone()[0] == 0
