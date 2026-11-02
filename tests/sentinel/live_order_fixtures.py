"""Synthetic LIVE funding attestations; no provider or account was contacted."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel.authority.canonical import key_id_for_public_key
from sentinel.authority.live import LiveTrustRoot
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerInstrument, OrderTerms, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.live_settlement import (
    FUNDING_SCHEMA, LiveFundingAdmission, account_snapshot_sha256, positions_sha256,
)
from sentinel.execution.states import CommandState
from tests.sentinel.live_authority_fixtures import live_fixture, signed_live


NOW = datetime(2026, 10, 26, 13, 31, tzinfo=timezone.utc)
DAY = NOW.date()
REFERENCE_SESSION = date(2026, 10, 23)


def command(fixture, *, security="SEC", revision=0, side=Side.BUY, **changes):
    deployment = DeploymentIdentity(fixture.subject.deployment_id, "alpaca-live",
        fixture.subject.account_id, fixture.subject.takeover_epoch)
    values = dict(identity=CommandIdentity(deployment, "plan", security, revision),
        instrument=BrokerInstrument(security, security, "native-" + security),
        side=side, quantity=Decimal(10), state=CommandState.SEND_PENDING,
        created_at=NOW - timedelta(seconds=5),
        order_terms=(OrderTerms("limit", "day", Decimal("10.10"))
                     if side is Side.BUY else OrderTerms()))
    values.update(changes)
    return Command(**values)


def order_fixture():
    fixture = live_fixture(NOW)
    fixture.account = BrokerAccountSnapshot(
        BrokerAccountIdentity("alpaca-live", fixture.subject.account_id),
        equity=Decimal(1000), cash=Decimal(1000), buying_power=Decimal(1000),
        multiplier=Decimal(1), status="ACTIVE")
    fixture.positions = ()
    fixture.request = command(fixture)
    fixture.commitments = (fixture.request,)
    return fixture


def funding(fixture, *, account=None, positions=None, **changes):
    account = fixture.account if account is None else account
    positions = fixture.positions if positions is None else positions
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    root = LiveTrustRoot(public, NOW - timedelta(hours=1), NOW + timedelta(hours=1),
                        status="ENROLLED", scope="LIVE_SETTLEMENT")
    claims = dict(observation_id="generated-offline-observation", subject=fixture.subject.model_dump(mode="json"),
        effective_session=DAY.isoformat(), observed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(seconds=20)).isoformat(),
        account_sha256=account_snapshot_sha256(account), positions_sha256=positions_sha256(positions),
        native_evidence_sha256="a" * 64,
        qualification_receipts={name: fixture.claims["qualification_receipts"][name]
                                for name in ("native_settlement", "native_reservations", "accounting")},
        settled_cash="1000", provider_reserved_cash="0", long_market_value="0", short_market_value="0")
    claims.update(changes)
    receipt = signed_live(claims, private, key_id, schema=FUNDING_SCHEMA)
    return SimpleNamespace(admission=LiveFundingAdmission(receipt, {key_id: root}),
        claims=claims, private_key=private, key_id=key_id, root=root, public_key=public)


def resigned_authority(fixture, **limits):
    claims = {**fixture.claims, "limits": {**fixture.claims["limits"], **limits}}
    return replace(fixture.admission,
        certificate=signed_live(claims, fixture.private_key, fixture.key_id))
