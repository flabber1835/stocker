"""Falsifiers for attended, read-only ADMIN_BIND_EMPTY enrollment."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel import (
    administrative_authority as administrative,
    authority,
    binding,
    empty_account,
    schema,
)
from sentinel.empty_account_authority import build_candidate
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, Side
from sentinel.execution.simulator import FaultKind, SimulatedBroker
from sentinel.feed import store as feed_store
from sentinel.guarded_administration import (
    AdministrativeAccessGrant,
    AdministrativeBrokerGuard,
)
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


D = Decimal
NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
KEY_ID = authority.key_id_for_public_key(PUBLIC)
ROOTS = {KEY_ID: authority.TrustRoot(
    KEY_ID, PUBLIC, "ACTIVE",
    datetime(2020, 1, 1, tzinfo=timezone.utc),
    datetime(2030, 1, 1, tzinfo=timezone.utc))}


def sha(char: str) -> str:
    return char * 64


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
    drop_public_tables(connection)
    feed_store.require_feed_schema(connection)
    schema.ensure_schema(connection)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_universe"
            " (permaticker,ticker,category,sector,related_tickers,"
            " first_price_date,last_price_date,is_delisted,snapshot_date)"
            " VALUES ('1001','AAA','Domestic Common Stock','Technology',"
            " NULL,'2020-01-01',NULL,FALSE,'2026-08-15')")
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (version,previous_version,window_start,window_end,evidence)"
            " VALUES (81,NULL,'2026-08-15','2026-08-15','{}'::jsonb)")
    connection.commit()
    yield connection
    connection.close()


def bindings_claim() -> dict:
    return {
        "git_commit": "a" * 40,
        "sentinel_source_sha256": sha("b"),
        "wealth_core_source_sha256": sha("c"),
        "runtime_image_digest": "sha256:" + sha("d"),
        "test_image_digest": "sha256:" + sha("e"),
        "requirements_lock_sha256": sha("f"),
        "runtime_identity_sha256": sha("1"),
        "strategy_identity_sha256": sha("2"),
        "execution_config_sha256": sha("3"),
        "automation_config_sha256": sha("4"),
        "current_corpus": {
            "data_version": 1,
            "publication_chain_root_sha256": sha("5"),
        },
        "current_metadata_snapshot": {
            "snapshot_date": "2026-08-15", "row_count": 1,
            "sha256": sha("6"),
        },
        "publication_policy": {
            "schema": "sentinel.publication-chain-policy/1",
            "implementation_sha256": sha("7"),
            "chain_root_sha256": sha("5"),
        },
        "controller": {"rule_sha256": sha("8"),
                       "config_sha256": sha("9")},
    }


def claims(**changes) -> dict:
    value = {
        "certificate_id": "empty-paper-binding-0001",
        "issuer_generation": 1,
        "issued_at": "2026-08-16T12:00:00Z",
        "not_before": "2026-08-16T12:00:00Z",
        "expires_at": "2026-08-16T12:30:00Z",
        "authorization_mode": "ADMIN_BIND_EMPTY",
        "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
        "historical_certification": "NOT_GRANTED",
        "scope": "ALPACA_PAPER",
        "unattended_automation": False,
        "permitted_operations": ["ADMIN_BIND_EMPTY"],
        "subject": {
            "deployment_id": "nas-01", "broker": "alpaca",
            "broker_account_id": "paper-123", "takeover_epoch": 1,
            "environment": "ALPACA_PAPER",
            "paper_base_url": authority.PAPER_BASE_URL,
        },
        "durable_rollout": {
            "mode": "PINNED_1_00", "version": 1,
            "certificate_sha256": None,
        },
        "bindings": bindings_claim(),
        "retained_evidence": {
            "schema": "sentinel.paper-empty-account-evidence/1",
            "sha256": sha("0"),
        },
        "supersedes_certificate_sha256": None,
    }
    value.update(changes)
    return value


def signed(value: dict, *, key=PRIVATE, key_id=KEY_ID) -> bytes:
    unsigned = authority.unsigned_envelope_bytes(key_id=key_id, claims=value)
    return authority.signed_envelope_bytes(
        key_id=key_id, claims=value, signature=key.sign(unsigned))


def context(value: dict) -> administrative.AdministrativeAuthorityContext:
    return administrative.AdministrativeAuthorityContext(
        **value["subject"], bindings=value["bindings"])


def activate(conn) -> tuple[dict, str]:
    value = claims()
    payload = signed(value)
    digest = hashlib.sha256(payload).hexdigest()
    administrative.install_administrative_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(value), reason="empty enrollment test",
        now=NOW, trust_roots=ROOTS)
    administrative.activate_administrative_certificate(
        conn, certificate_sha256=digest, context=context(value),
        reason="empty enrollment test", now=NOW, trust_roots=ROOTS)
    return value, digest


def facade(monkeypatch, broker: SimulatedBroker):
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    from sentinel.execution.certification import certify_adapter

    inner = AlpacaExecutionBroker(
        api_key="test", secret_key="test",
        base_url="https://paper-api.alpaca.markets")

    async def account_snapshot():
        return await broker.account_snapshot()

    async def observe():
        return await broker.observe()

    monkeypatch.setattr(inner, "account_snapshot", account_snapshot)
    monkeypatch.setattr(inner, "observe", observe)
    certify_adapter(inner, name="alpaca", mode="ALPACA_PAPER")
    return empty_account.GuardedEmptyAccountBroker(
        inner=inner,
        grant=AdministrativeAccessGrant(
            operation="ADMIN_BIND_EMPTY", deployment_id="nas-01",
            broker_account_id="paper-123", takeover_epoch=1),
        guard=AdministrativeBrokerGuard(check=lambda *_args: None))


def flat_broker() -> SimulatedBroker:
    return SimulatedBroker(
        account=BrokerAccountIdentity("alpaca", "paper-123"),
        equity=D("100000"), cash=D("100000"))


def test_facade_accepts_only_the_certified_alpaca_adapter(monkeypatch):
    monkeypatch.setattr(
        "sentinel.execution.certification.require_certified",
        lambda _name: None)
    with pytest.raises(TypeError, match="certified Alpaca"):
        empty_account.GuardedEmptyAccountBroker(
            inner=object(),
            grant=AdministrativeAccessGrant(
                operation="ADMIN_BIND_EMPTY", deployment_id="nas-01",
                broker_account_id="paper-123", takeover_epoch=1),
            guard=AdministrativeBrokerGuard(check=lambda *_args: None))


async def no_sleep(_seconds):
    return None


def test_empty_authority_requires_no_historical_go_claim():
    value = authority.validate_empty_account_certificate_claims(claims())
    assert value["historical_certification"] == "NOT_GRANTED"
    assert "wealth_core" not in value["bindings"]
    assert value["permitted_operations"] == ["ADMIN_BIND_EMPTY"]
    assert value["unattended_automation"] is False


def test_offline_issuer_signs_only_canonical_reviewed_candidate(tmp_path):
    from tools.sentinel_empty_account_authority import issue

    evidence = {
        "schema": "sentinel.paper-empty-account-evidence/1",
        "authorization_mode": "ADMIN_BIND_EMPTY",
        "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
        "historical_certification": "NOT_GRANTED",
        "scope": "ALPACA_PAPER",
        "subject": claims()["subject"],
        "durable_rollout": claims()["durable_rollout"],
        "bindings": claims()["bindings"],
        "review": {
            "reviewer": "reviewer", "ticket": "ticket",
            "reviewed_at": "2026-08-16T12:00:00Z",
            "authority_effect": "ADMIN_BIND_EMPTY",
        },
    }
    value = claims(retained_evidence={
        "schema": "sentinel.paper-empty-account-evidence/1",
        "sha256": authority.canonical_sha256(evidence),
    })
    candidate = {
        "schema": "sentinel.paper-empty-account-candidate/1",
        "claims": value, "retained_evidence": evidence,
    }
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_bytes(authority.canonical_json_bytes(candidate))
    private_path = tmp_path / "private.pem"
    private_path.write_bytes(PRIVATE.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    private_path.chmod(0o600)
    output = tmp_path / "certificate.json"
    digest = issue(
        candidate=candidate_path, private_key_file=private_path,
        key_id=KEY_ID, output=output)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    verified = authority.verify_signed_certificate(
        output.read_bytes(), now=NOW, trust_roots=ROOTS)
    assert verified.authorization_mode == "ADMIN_BIND_EMPTY"
    assert verified.claims["historical_certification"] == "NOT_GRANTED"


@pytest.mark.parametrize(
    ("mutate", "message"), [
        (lambda v: v["subject"].update(takeover_epoch=2), "epoch-1"),
        (lambda v: v["subject"].update(
            paper_base_url="https://api.alpaca.markets"), "paper epoch-1"),
        (lambda v: v.update(expires_at="2026-08-16T13:00:01Z"),
         "one hour"),
    ])
def test_wrong_subject_endpoint_epoch_or_lifetime_refuses(mutate, message):
    value = claims()
    mutate(value)
    with pytest.raises(authority.AuthorityRefused, match=message):
        authority.validate_empty_account_certificate_claims(value)


def test_wrong_signature_key_and_expiry_refuse():
    payload = bytearray(signed(claims()))
    payload[-3] = ord("A") if payload[-3] != ord("A") else ord("B")
    with pytest.raises(authority.AuthorityRefused):
        authority.verify_signed_certificate(
            bytes(payload), now=NOW, trust_roots=ROOTS)
    other = Ed25519PrivateKey.generate()
    other_public = other.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    other_id = authority.key_id_for_public_key(other_public)
    with pytest.raises(authority.AuthorityRefused, match="not trusted"):
        authority.verify_signed_certificate(
            signed(claims(), key=other, key_id=other_id),
            now=NOW, trust_roots=ROOTS)
    with pytest.raises(authority.AuthorityRefused, match="expired"):
        authority.verify_signed_certificate(
            signed(claims()),
            now=datetime(2026, 8, 16, 12, 30, tzinfo=timezone.utc),
            trust_roots=ROOTS)


def test_context_refuses_wrong_account_deployment_and_bindings(conn):
    value = claims()
    for changed in (
            {**value["subject"], "broker_account_id": "paper-other"},
            {**value["subject"], "deployment_id": "nas-other"}):
        bad = administrative.AdministrativeAuthorityContext(
            **changed, bindings=value["bindings"])
        with pytest.raises(authority.AuthorityRefused, match="subject"):
            administrative.install_administrative_certificate(
                conn, certificate_bytes=signed(value),
                confirm_sha256=hashlib.sha256(signed(value)).hexdigest(),
                context=bad, reason="bad", now=NOW, trust_roots=ROOTS)
    bad_bindings = {**value["bindings"], "runtime_identity_sha256": sha("a")}
    with pytest.raises(authority.AuthorityRefused, match="bindings"):
        administrative.install_administrative_certificate(
            conn, certificate_bytes=signed(value),
            confirm_sha256=hashlib.sha256(signed(value)).hexdigest(),
            context=administrative.AdministrativeAuthorityContext(
                **value["subject"], bindings=bad_bindings),
            reason="bad runtime", now=NOW, trust_roots=ROOTS)


@pytest.mark.parametrize(
    ("field", "value", "message"), [
        ("status", "SUSPENDED", "account_status"),
        ("trading_blocked", True, "trading_blocked"),
        ("account_blocked", True, "account_blocked"),
        ("trade_suspended_by_user", True, "trade_suspended_by_user"),
        ("multiplier", D("2"), "cash_only_multiplier"),
        ("buying_power", D("99900"), "unsettled_buying_power"),
        ("buying_power", D("100100"), "margin_buying_power"),
    ])
def test_blocked_suspended_margin_or_unsettled_refuses(
        conn, monkeypatch, field, value, message):
    broker = flat_broker()
    setattr(broker, field, value)
    with pytest.raises(empty_account.EmptyAccountRefused, match=message):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, broker),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: sha("a"), sleep=no_sleep))
    assert binding.load(conn) is None


def test_nonempty_position_refuses_before_mutation(conn, monkeypatch):
    broker = flat_broker()
    broker.seed_position(
        BrokerInstrument("SEC-AAA", "AAA", "asset-aaa"), "1")
    view = facade(monkeypatch, broker)
    with pytest.raises(empty_account.EmptyAccountRefused, match="position"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=view, deployment_id="nas-01",
            expected_account="paper-123",
            consume_authority=lambda: pytest.fail("must not consume"),
            sleep=no_sleep))
    assert not hasattr(view, "submit")
    assert not hasattr(view, "cancel")
    assert not hasattr(view, "close_position")
    assert binding.load(conn) is None


def test_any_open_order_refuses(conn, monkeypatch):
    broker = flat_broker()
    broker.seed_foreign_order(
        BrokerInstrument("SEC-AAA", "AAA", "asset-aaa"),
        side=Side.BUY, qty="1")
    with pytest.raises(empty_account.EmptyAccountRefused, match="open order"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, broker),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: pytest.fail("must not consume"),
            sleep=no_sleep))
    assert binding.load(conn) is None


def test_incomplete_pagination_refuses(conn, monkeypatch):
    broker = flat_broker().schedule_observe(FaultKind.TRUNCATED_ORDERS)
    with pytest.raises(Exception, match="COMPLETE"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, broker),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: pytest.fail("must not consume"),
            sleep=no_sleep))
    assert binding.load(conn) is None


@pytest.mark.parametrize("change", ["account", "position", "order"])
def test_account_order_or_position_change_between_reads_refuses(
        conn, monkeypatch, change):
    broker = flat_broker()

    async def changing_sleep(_seconds):
        if change == "account":
            broker.cash = D("99999")
        elif change == "position":
            broker.seed_position(
                BrokerInstrument("SEC-AAA", "AAA", "asset-aaa"), "1")
        else:
            broker.seed_foreign_order(
                BrokerInstrument("SEC-AAA", "AAA", "asset-aaa"),
                side=Side.BUY, qty="1")

    with pytest.raises(Exception):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, broker),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: pytest.fail("must not consume"),
            sleep=changing_sleep))
    assert binding.load(conn) is None


def test_wrong_broker_account_and_existing_binding_refuse(conn, monkeypatch):
    wrong = flat_broker()
    wrong.account = BrokerAccountIdentity("alpaca", "paper-other")
    with pytest.raises(authority.AuthorityRefused, match="signed Alpaca"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, wrong),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: pytest.fail("must not consume"),
            sleep=no_sleep))
    binding.bind(
        conn, deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123")
    broker = flat_broker()
    with pytest.raises(empty_account.EmptyAccountRefused, match="before broker"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, broker),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: pytest.fail("must not consume"),
            sleep=no_sleep))
    assert broker.calls == []


def test_failure_after_reads_is_atomic(conn, monkeypatch):
    def fail_consumption():
        raise authority.AuthorityRefused("revoked concurrently")

    with pytest.raises(authority.AuthorityRefused, match="revoked concurrently"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, flat_broker()),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=fail_consumption, sleep=no_sleep))
    assert binding.load(conn) is None
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_ownership_events")
        assert cur.fetchone()[0] == 0


def test_binding_write_failure_rolls_back_consumption_and_event(
        conn, monkeypatch):
    _value, digest = activate(conn)

    def consume():
        administrative.consume_empty_binding_authority(
            conn, certificate_sha256=digest, now=NOW,
            trust_roots=ROOTS, commit=False)
        return digest

    monkeypatch.setattr(
        binding, "bind",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("binding write failed")))
    with pytest.raises(RuntimeError, match="binding write failed"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, flat_broker()),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=consume, sleep=no_sleep))
    assert binding.load(conn) is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT active_certificate_sha256 FROM "
            "sentinel_administrative_authority_state WHERE id=1")
        assert cur.fetchone()[0] == digest
        cur.execute(
            "SELECT status,revocation_reason FROM "
            "sentinel_signed_administrative_certificates "
            "WHERE certificate_sha256=%s", (digest,))
        assert cur.fetchone() == ("ACTIVE", None)
        cur.execute("SELECT COUNT(*) FROM sentinel_ownership_events")
        assert cur.fetchone()[0] == 0


def test_success_binds_once_consumes_authority_and_replay_refuses(
        conn, monkeypatch):
    _value, digest = activate(conn)
    broker = flat_broker()

    def consume():
        administrative.consume_empty_binding_authority(
            conn, certificate_sha256=digest, now=NOW,
            trust_roots=ROOTS, commit=False)
        return digest

    view = facade(monkeypatch, broker)
    result = asyncio.run(empty_account.bind_empty_account(
        conn=conn, broker=view, deployment_id="nas-01",
        expected_account="paper-123", consume_authority=consume,
        sleep=no_sleep))
    assert result.binding.to_dict() == {
        "deployment_id": "nas-01", "broker": "alpaca",
        "broker_account_id": "paper-123", "takeover_epoch": 1,
        "ownership_state": "SENTINEL_OWNED", "notes": "",
    }
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_account_binding")
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT status,revocation_reason FROM "
            "sentinel_signed_administrative_certificates "
            "WHERE certificate_sha256=%s", (digest,))
        assert cur.fetchone() == (
            "REVOKED", "consumed by successful ADMIN_BIND_EMPTY")
    assert not hasattr(view, "submit")
    assert not hasattr(view, "cancel")
    assert broker.calls == [
        "account_snapshot", "list_orders", "get_positions", "list_orders",
        "account_snapshot", "list_orders", "get_positions", "list_orders",
    ]
    status = administrative.administrative_authority_status(conn)
    assert status["active_certificate_sha256"] is None
    assert status["certificates"][0]["status"] == "REVOKED"
    assert status["certificates"][0]["revocation_reason"] \
        == "consumed by successful ADMIN_BIND_EMPTY"
    with pytest.raises(empty_account.EmptyAccountRefused, match="before broker"):
        asyncio.run(empty_account.bind_empty_account(
            conn=conn, broker=facade(monkeypatch, flat_broker()),
            deployment_id="nas-01", expected_account="paper-123",
            consume_authority=lambda: digest, sleep=no_sleep))


def runtime_identity() -> dict:
    return {
        "deployment_artifacts": {
            "schema": "sentinel.runtime-artifacts/1",
            "git_commit": "a" * 40,
            "runtime_image_digest": "sha256:" + sha("d"),
            "test_image_digest": "sha256:" + sha("e"),
        },
        "identity_hash": sha("1"),
        "environment": {
            "compatible": True, "pins_match": True, "sources_known": True,
            "pin_drift": {}, "sentinel_source": {"hash": sha("b")},
            "wealth_core_source": {"hash": sha("c")},
            "image_lock_sha256": sha("f"),
        },
    }


def test_paper_observation_candidate_refuses_before_binding_and_succeeds_after(
        conn):
    from sentinel.observation_authority import build_candidate as observation

    kwargs = dict(
        certificate_id="paper-observation-after-empty-0001",
        issuer_generation=2, deployment_id="nas-01",
        expected_account="paper-123", runtime_identity=runtime_identity(),
        strategy_identity={"strategy": "current"},
        automation_config_sha256=sha("4"),
        warmup={"schema": "sentinel.paper-observation-warmup/1"},
        maximum_exposure="0.5", reviewer="reviewer", ticket="ticket",
        not_before=NOW, now=NOW)
    with pytest.raises(binding.AccountNotBound):
        observation(conn, **kwargs)
    binding.bind(
        conn, deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123")
    candidate = observation(conn, **kwargs)
    assert candidate["claims"]["authorization_mode"] \
        == "PAPER_OBSERVATION_ONLY"


def test_prebinding_candidate_binds_current_runtime_and_refuses_drift(conn):
    candidate = build_candidate(
        conn, certificate_id="empty-paper-candidate-0001",
        issuer_generation=1, deployment_id="nas-01",
        expected_account="paper-123", runtime_identity=runtime_identity(),
        strategy_identity={"strategy": "current"},
        automation_config_sha256=sha("4"), reviewer="reviewer",
        ticket="ticket", not_before=NOW, now=NOW)
    assert candidate["claims"]["historical_certification"] == "NOT_GRANTED"
    drifted = runtime_identity()
    drifted["deployment_artifacts"]["runtime_image_digest"] = (
        "sha256:" + sha("a"))
    context_now = administrative.build_current_context(
        conn, certificate=authority.verify_signed_certificate(
            signed(candidate["claims"]), now=NOW, trust_roots=ROOTS),
        deployment_id="nas-01", broker_account_id="paper-123",
        takeover_epoch=1, paper_base_url=authority.PAPER_BASE_URL,
        runtime_identity=drifted, strategy_identity={"strategy": "current"},
        automation_config_sha256=sha("4"), trust_roots_path=(
            authority.DEFAULT_TRUST_ROOTS_PATH))
    with pytest.raises(authority.AuthorityRefused, match="bindings"):
        administrative.install_administrative_certificate(
            conn, certificate_bytes=signed(candidate["claims"]),
            confirm_sha256=hashlib.sha256(
                signed(candidate["claims"])).hexdigest(),
            context=context_now, reason="runtime drift", now=NOW,
            trust_roots=ROOTS)


@pytest.mark.parametrize("operation", [
    "ADMIN_INSPECT", "ADMIN_MIGRATE", "ADMIN_ADOPT", "PREPARE_READ",
    "EXECUTE_READ", "AUTOMATION",
])
def test_empty_authority_cannot_authorize_any_other_operation(conn, operation):
    activate(conn)
    with pytest.raises(authority.AuthorityRefused):
        administrative.require_administrative_authority(
            conn, operation=operation, deployment_id="nas-01",
            broker_account_id="paper-123", takeover_epoch=1,
            paper_base_url=authority.PAPER_BASE_URL,
            runtime_identity={}, strategy_identity={},
            automation_config_sha256=sha("4"), now=NOW,
            trust_roots=ROOTS)
