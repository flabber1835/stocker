from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel.execution import journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerInstrument, BrokerObservation, BrokerOrder, BrokerPosition,
    Completeness, Side,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.reconcile import (
    _order_command_conflict, _order_observation_fingerprint,
    _position_identity_conflicts,
)
from sentinel.execution.states import CommandState


def _command(asset_id: str) -> Command:
    deployment = DeploymentIdentity("deploy", "alpaca", "paper-1", 1)
    identity = CommandIdentity(
        deployment=deployment, plan_id="plan-1", security_id="SEC-AAA")
    return Command(
        identity=identity,
        instrument=BrokerInstrument(
            security_id="SEC-AAA", symbol="AAA", broker_id=asset_id),
        side=Side.BUY, quantity=Decimal("2"),
        state=CommandState.ACKNOWLEDGED, broker_order_id="order-1")


def _order(asset_id: str) -> BrokerOrder:
    command = _command("asset-a")
    return BrokerOrder(
        broker_order_id="order-1", client_key=command.client_key,
        instrument=BrokerInstrument(
            security_id="SEC-AAA", symbol="AAA", broker_id=asset_id),
        side=Side.BUY, state=CommandState.ACKNOWLEDGED,
        quantity=Decimal("2"), filled_quantity=Decimal("0"),
        submitted_at=datetime(2026, 8, 29, tzinfo=timezone.utc))


def test_order_reconciliation_refuses_asset_id_change():
    conflict = _order_command_conflict(_order("asset-b"), _command("asset-a"))
    assert "changed durable broker instrument id" in conflict


def test_asset_id_participates_in_order_observation_fingerprint():
    assert _order_observation_fingerprint(_order("asset-a")) != \
        _order_observation_fingerprint(_order("asset-b"))


@pytest.mark.parametrize("field,value", [
    ("external_replacement", True),
    ("replaced_by", "successor"),
    ("replaces", "predecessor"),
    ("submitted_at", datetime(2026, 8, 30, tzinfo=timezone.utc)),
])
def test_replacement_authority_fields_participate_in_order_fingerprint(
        field, value):
    baseline = _order("asset-a")
    assert _order_observation_fingerprint(baseline) != \
        _order_observation_fingerprint(replace(baseline, **{field: value}))


def test_position_reconciliation_refuses_asset_id_change():
    observation = BrokerObservation(
        observed_at=datetime.now(timezone.utc),
        positions=(BrokerPosition(
            instrument=BrokerInstrument(
                security_id="SEC-AAA", symbol="AAA", broker_id="asset-b"),
            quantity=Decimal("2")),),
        completeness=Completeness.COMPLETE)
    conflicts = _position_identity_conflicts(observation, (_command("asset-a"),))
    assert conflicts and "expected one of" in conflicts[0]


class _Cursor:
    def execute(self, _sql, _params):
        pass

    def fetchone(self):
        return (
            "SEC-AAA", "BUY", Decimal("2"), "AAA", "asset-a",
            "deploy", "alpaca", "paper-1", 1)


def test_command_client_key_economics_include_asset_id():
    with pytest.raises(journal.CommandEconomicsChanged, match="broker_instrument_id"):
        journal._assert_economics_unchanged(  # noqa: SLF001
            _Cursor(), _command("asset-b"))


def test_observation_provenance_retains_position_asset_id():
    from sentinel import binding, schema
    from sentinel.execution.contract import BrokerAccountIdentity
    from sentinel.feed import store as feed_store
    from tests.support.postgres import _EphemeralPostgres, drop_public_tables

    server = _EphemeralPostgres()
    try:
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    conn = None
    try:
        conn = feed_store.connect(server.sync_dsn)
        drop_public_tables(conn)
        feed_store.migrate_schema(conn)
        schema.ensure_schema(conn)
        binding.bind(
            conn, deployment_id="asset-identity-test", broker="alpaca",
            broker_account_id="paper-1")
        observed_at = datetime.now(timezone.utc)
        observation = BrokerObservation(
            started_at=observed_at - timedelta(seconds=1),
            observed_at=observed_at,
            account_identity=BrokerAccountIdentity("alpaca", "paper-1"),
            positions=(BrokerPosition(
                instrument=BrokerInstrument(
                    security_id="SEC-AAA", symbol="AAA", broker_id="asset-a"),
                quantity=Decimal("2")),),
            completeness=Completeness.COMPLETE)
        seq = journal.record_observation(conn, observation, "RECONCILING")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT positions FROM sentinel_observation_provenance "
                "WHERE observation_seq=%s", (seq,))
            provenance = cur.fetchone()[0]
        assert datetime.fromisoformat(provenance["started_at"]) == (
            observed_at - timedelta(seconds=1))
        assert provenance["positions"] == [{
            "security_id": "SEC-AAA", "symbol": "AAA",
            "broker_instrument_id": "asset-a", "quantity": "2"}]
    finally:
        if conn is not None:
            conn.close()
        server.stop()
