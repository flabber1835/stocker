"""Dollar commands never masquerade as requested share quantities."""
from dataclasses import replace
from decimal import Decimal, localcontext

import psycopg
import pytest

from sentinel import schema
from sentinel.execution import journal, recovery
from sentinel.execution.contract import BrokerOrder, OrderTerms, Side
from sentinel.execution.order_amount import OrderAmount
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_journal_and_reconcile import cmd, DEPLOY
from tests.sentinel.test_order_terms_schema import (
    pg, database, install_v1, _compiled, _ledger_rows,
)


@pytest.mark.parametrize("kind", ["NEW", "LEGACY", "PR84_HEAD_BRIDGE"])
def test_v3_catalog_is_exact_and_preserves_v2(database, kind):
    install_v1(database, kind)
    with database.cursor() as cur:
        cur.execute("SET LOCAL search_path TO public,pg_temp")
        schema._migrate_order_terms(cur, schema._read_catalog(cur))
        before = schema._read_catalog(cur)
        assert schema._semantic_catalog_sha256(*before, schema._CURRENT_TABLES) == schema._ORDER_TERMS_TARGET_CATALOG_SHA256[kind]
        schema._migrate_order_amount(cur, before)
        after = schema._read_catalog(cur)
        observed = schema._semantic_catalog_sha256(*after, schema._CURRENT_TABLES)
        print("ORDER_AMOUNT_CATALOG", kind, observed, flush=True)
        assert observed == schema._ORDER_AMOUNT_TARGET_CATALOG_SHA256[kind]
        assert schema._semantic_catalog_sha256(*before, schema._STAGE4_TABLES) == schema._semantic_catalog_sha256(*after, schema._STAGE4_TABLES)
        assert schema._validate_ledgered(cur, after) == 3


@pytest.mark.parametrize("values", [dict(), dict(quantity=Decimal(1), notional=Decimal(1)),
    dict(notional=Decimal(0)), dict(quantity=Decimal("NaN")), dict(notional=Decimal("Infinity")),
    dict(notional=1.1)])
def test_exactly_one_positive_decimal_amount(values):
    with pytest.raises(ValueError):
        OrderAmount(**values)


def test_precision_is_exact_under_small_decimal_context():
    with localcontext() as context:
        context.prec = 3
        assert OrderAmount(notional=Decimal("123456.78")).wire() == {"notional": "123456.78"}
        assert OrderAmount(quantity=Decimal("123.000000001")).wire() == {"qty": "123.000000001"}
        for amount in (OrderAmount(notional=Decimal("1.001")), OrderAmount(quantity=Decimal("1.0000000001"))):
            with pytest.raises(ValueError, match="precision"):
                amount.wire()


@pytest.mark.parametrize("flag", ["true", "false", 0, 1, None])
def test_notional_capability_requires_explicit_boolean(flag):
    from sentinel.execution.contract import BrokerCapabilities
    with pytest.raises(TypeError, match="notional_market_buys"):
        BrokerCapabilities(notional_market_buys=flag)


def test_notional_command_roundtrip_and_immutable_denomination(database):
    schema.ensure_schema(database)
    original = replace(cmd(), quantity=None, notional=Decimal("100.01"))
    journal.save_command(database, original)
    loaded, = journal.load_commands(database, DEPLOY)
    assert loaded.notional == original.notional and loaded.quantity is None
    assert loaded.client_key == original.client_key
    for changed in (replace(original, notional=Decimal("100.02")),
                    replace(original, quantity=Decimal(1), notional=None)):
        with pytest.raises(journal.CommandEconomicsChanged):
            journal.save_command(database, changed)
        database.rollback()
    with pytest.raises(ValueError, match="no remaining share"):
        _ = loaded.remaining


@pytest.mark.parametrize("side,terms", [(Side.SELL, OrderTerms()),
    (Side.BUY, OrderTerms(order_type="limit", limit_price=Decimal(10)))])
def test_notional_cannot_be_sell_or_limit(side, terms):
    with pytest.raises(ValueError, match="MARKET/DAY BUY"):
        replace(cmd(), quantity=None, notional=Decimal(10), side=side, order_terms=terms)


def test_positive_recovery_must_match_dollars():
    command = replace(cmd(), quantity=None, notional=Decimal(100))
    order = BrokerOrder("native", command.client_key, command.instrument, Side.BUY,
        S.FILLED, None, Decimal("0.73890218"), Decimal("135.34"), notional=Decimal(100))
    recovery._assert_order_matches_command(command, order, where="test")
    from sentinel.execution.guarded import BrokerAuthorityRefused
    with pytest.raises(BrokerAuthorityRefused, match="notional"):
        recovery._assert_order_matches_command(command, replace(order, notional=Decimal(101)), where="test")


@pytest.mark.parametrize("quantity,notional,side", [(None, None, "BUY"), (1, 1, "BUY"),
    (None, "NaN", "BUY"), (None, "Infinity", "BUY"), (None, "1.001", "BUY"),
    (None, 1, "SELL"), (-1, None, "BUY")])
def test_database_rejects_ambiguous_amount_without_python(database, quantity, notional, side):
    schema.ensure_schema(database)
    with pytest.raises(psycopg.errors.CheckViolation, match="amount"):
        database.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,"
            "deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,notional,state) "
            "VALUES ('bad','p','s','d','sim','a',1,'S',%s,%s,%s,'PLANNED')", (side, quantity, notional))
    database.rollback()


def test_v3_runtime_falsifier(database, monkeypatch):
    install_v1(database)
    with database.cursor() as cur:
        schema._migrate_order_terms(cur, schema._read_catalog(cur))
    database.commit()
    with pytest.raises(schema.SchemaMigrationRefused, match="v3.*required"):
        schema.require_runtime_schema(database)
    monkeypatch.setattr(schema, "_validate_ledgered", _compiled(schema._validate_ledgered,
        "elif not allow_previous:", "elif False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        with pytest.raises(schema.SchemaMigrationRefused):
            schema.require_runtime_schema(database)


def install_v2(conn):
    install_v1(conn)
    with conn.cursor() as cur:
        schema._migrate_order_terms(cur, schema._read_catalog(cur))
    conn.commit()


@pytest.mark.parametrize("fence", ["enabled", "live-leader"])
def test_v3_migration_requires_fenced_automation(database, fence):
    install_v2(database)
    if fence == "enabled":
        database.execute("UPDATE sentinel_automation_control SET enabled=true,kill_switch_engaged=false,"
            "deployment_id='private-test',broker='sim',broker_account_id='private',takeover_epoch=1,"
            "certificate_sha256=repeat('a',64),rollout_mode='PINNED_1_00',rollout_version=1,config_sha256=repeat('b',64)")
    else:
        database.execute("UPDATE sentinel_automation_lease SET holder_id='private-test',"
            "fence_token=1,control_generation=1,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
            "expires_at=clock_timestamp()+interval '1 minute'")
    database.commit()
    with pytest.raises(schema.SchemaMigrationRefused, match="fenced.*no live"):
        schema.ensure_schema(database)
    assert [row[0] for row in _ledger_rows(database)] == [1, 2]
    assert not database.execute("SELECT 1 FROM information_schema.columns WHERE "
        "table_name='sentinel_commands' AND column_name='notional'").fetchall()


@pytest.mark.parametrize("fence", ["enabled", "live-leader"])
def test_v3_fence_falsifier(database, monkeypatch, fence):
    monkeypatch.setattr(schema, "_migrate_order_amount", _compiled(schema._migrate_order_amount,
        "if ((enabled and not killed)\n"
        "            or (holder is not None and live and lease_generation == generation)):",
        "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_v3_migration_requires_fenced_automation(database, fence)


def test_late_v3_failure_preserves_v2_catalog_and_ledger(database, monkeypatch):
    install_v2(database)
    before = _ledger_rows(database)
    monkeypatch.setattr(schema, "_ORDER_AMOUNT_DDL", (*schema._ORDER_AMOUNT_DDL, "SELECT 1/0"))
    with pytest.raises(Exception, match="division by zero"):
        schema.ensure_schema(database)
    assert _ledger_rows(database) == before
    with database.cursor() as cur:
        assert schema._validate_ledgered(cur, schema._read_catalog(cur), allow_previous=True) == 2


def test_notional_observation_adoption_and_tamper_evidence(database):
    import json
    from sentinel import binding, dual_reconciliation
    from tests.sentinel.test_order_terms_journal import NOW, observation
    schema.ensure_schema(database)
    binding.bind(database, deployment_id=DEPLOY.deployment_id, broker=DEPLOY.broker,
                 broker_account_id=DEPLOY.broker_account_id)
    database.execute("UPDATE sentinel_account_binding SET established_at=%s", (NOW,))
    database.commit()
    original = replace(cmd(), quantity=None, notional=Decimal("100.01"))
    native = BrokerOrder("native", original.client_key, original.instrument, Side.BUY,
        S.PARTIALLY_FILLED, None, Decimal("0.001"), Decimal("100"),
        submitted_at=NOW, notional=original.notional)
    seq = journal.record_observation(database, observation(native))
    payload = journal.load_observation_payload(database, seq)
    assert payload["kind"] == journal.AMOUNT_OBSERVATION_PAYLOAD_KIND
    assert payload["orders"][0]["quantity"] is None and payload["orders"][0]["notional"] == "100.01"
    journal.adopt_recovered_order(database, native, deployment=DEPLOY)
    restored, = journal.load_commands(database, DEPLOY)
    assert restored.notional == original.notional and restored.quantity is None
    assert restored.filled_quantity == Decimal("0.001")
    # A stale restore adopts the native amount under its original identity.
    with pytest.raises(journal.RecoveredOrderConflict):
        journal.adopt_recovered_order(database, replace(native, notional=Decimal(101)), deployment=DEPLOY)
    raw = database.execute("SELECT orders FROM sentinel_observations WHERE seq=%s", (seq,)).fetchone()[0]
    raw[0]["notional"] = "101"
    database.execute("UPDATE sentinel_observations SET orders=%s::jsonb WHERE seq=%s", (json.dumps(raw), seq))
    database.commit()
    with pytest.raises(journal.ObservationEvidenceUncertifiable):
        journal.load_observation_payload(database, seq)
