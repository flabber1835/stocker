"""Real-PostgreSQL falsifiers for behavioral-schema migration authority.

The fixtures in ``fixtures/`` are frozen historical SQL, deliberately installed
without calling today's :func:`sentinel.schema.ensure_schema`.  Constructing an
"upgrade" by installing the current schema and dropping the tables under test
would bless partial data loss as a legitimate legacy state.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import (  # noqa: E402
    _EphemeralPostgres,
    drop_public_tables,
)

from sentinel import schema  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402


FIXTURES = Path(__file__).with_name("fixtures")
PRE_ROLLOUT = FIXTURES / "behavioral_schema_pre_rollout_69cdfe8.sql"
PRE_ROLLOUT_FB97372 = FIXTURES / "behavioral_schema_pre_rollout_fb97372.sql"
REVIEWED_HEAD_DELTA = FIXTURES / "behavioral_schema_6113bffd_delta.sql"
PRE_ROLLOUT_HEAD = "69cdfe8085a73bc68cc66da0d8dd3f9cd0bafd88"
PRE_ROLLOUT_FB97372_HEAD = "fb97372a166299b23ce7e9fa6951a6304e1c5333"
REVIEWED_HEAD = "6113bffd896824ee24891b0c1aeada60c2b73ef5"
MIGRATION_NAME = "rollout-authority-v1"
CERTIFICATE_SHA256 = "c" * 64


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def database(pg):
    conn = feed_store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()
        cleanup = feed_store.connect(pg.sync_dsn)
        try:
            drop_public_tables(cleanup)
        finally:
            cleanup.close()


def _install_sql(conn, *paths: Path) -> None:
    with conn.cursor() as cur:
        for path in paths:
            script = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            # The frozen files separate top-level statements by a blank line.
            # Execute one at a time so both supported drivers use the same
            # protocol; no fixture depends on multi-command execute support.
            for statement in script.strip().split(";\n\n"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
    conn.commit()


def _install_pre_rollout(conn) -> None:
    # The schema comes directly from PRE_ROLLOUT_HEAD; in particular, it has
    # neither rollout tables nor rollout columns on execution plans.
    _install_sql(conn, PRE_ROLLOUT)


def _install_pre_rollout_fb97372(conn) -> None:
    # Exact origin/main immediately before PR #84: commands predate their
    # durable per-command identity columns, while all other pre-rollout tables
    # have their final pre-rollout shape.
    _install_sql(conn, PRE_ROLLOUT_FB97372)


def _install_reviewed_head(conn) -> None:
    # These two frozen files compose the exact behavioral DDL at REVIEWED_HEAD.
    _install_sql(conn, PRE_ROLLOUT, REVIEWED_HEAD_DELTA)


def _ledger_rows(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,name,bootstrap_kind,source_git_oid,applied_at"
            " FROM sentinel_behavioral_schema_migrations ORDER BY version")
        return cur.fetchall()


def _rollout_rows(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,mode,version,certificate_sha256"
            " FROM sentinel_rollout_state ORDER BY id")
        return cur.fetchall()


def _plan_rollout_columns(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name,is_nullable,column_default"
            " FROM information_schema.columns"
            " WHERE table_schema='public'"
            "   AND table_name='sentinel_execution_plans'"
            "   AND column_name IN"
            "       ('rollout_mode','rollout_version',"
            "        'rollout_certificate_sha256')"
            " ORDER BY column_name")
        return cur.fetchall()


def _regclass(conn, table: str):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        return cur.fetchone()[0]


def _assert_operator_refusal(conn, *, reason: str | None = None) -> str:
    with pytest.raises(schema.SchemaMigrationRefused) as raised:
        schema.ensure_schema(conn)
    message = str(raised.value)
    assert "operator" in message.lower(), message
    if reason is not None:
        assert reason.lower() in message.lower(), message
    conn.rollback()
    return message


def _advance_current_schema_to_controller(conn, *, reason: str) -> None:
    """Create coherent v2 evidence before simulating durable-state loss."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_system_certificates"
            " (certificate_sha256,manifest_bytes,manifest,"
            "  allowed_rollout_modes)"
            " VALUES (%s,%s,'{}'::jsonb,"
            "         '[\"CONTROLLER\"]'::jsonb)",
            (CERTIFICATE_SHA256, b"{}"))
        cur.execute(
            "INSERT INTO sentinel_system_certificate_events"
            " (certificate_sha256,action,detail)"
            " VALUES (%s,'INSTALLED','schema migration test fixture')",
            (CERTIFICATE_SHA256,))
        cur.execute(
            "UPDATE sentinel_rollout_state"
            " SET mode='CONTROLLER',version=2,certificate_sha256=%s"
            " WHERE id=1", (CERTIFICATE_SHA256,))
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (2,'PINNED_1_00','CONTROLLER',%s,%s)",
            (CERTIFICATE_SHA256, reason))


@pytest.mark.parametrize("feed_only", [False, True], ids=["empty", "feed-only"])
def test_brand_new_behavioral_database_seeds_once(database, feed_only):
    if feed_only:
        feed_store.ensure_schema(database)
        with database.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM pg_tables"
                " WHERE schemaname='public' AND tablename LIKE 'sentinel_%'")
            assert cur.fetchone()[0] > 0

    schema.ensure_schema(database)

    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]
    ledger = _ledger_rows(database)
    assert [(row[0], row[1], row[2], row[3]) for row in ledger] == [
        (1, MIGRATION_NAME, "NEW", None)]
    assert _plan_rollout_columns(database) == [
        ("rollout_certificate_sha256", "YES", None),
        ("rollout_mode", "NO", None),
        ("rollout_version", "NO", None),
    ]


def test_verified_backup_marker_may_precede_behavioral_schema(database):
    """The supported safety-first order: legacy DB, backup marker, schema."""
    with database.cursor() as cur:
        cur.execute(
            "CREATE TABLE sentinel_backup_recovery_markers ("
            " marker TEXT PRIMARY KEY,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        cur.execute(
            "INSERT INTO sentinel_backup_recovery_markers(marker)"
            " VALUES ('post-base-wal-marker')")
    database.commit()

    schema.ensure_schema(database)

    with database.cursor() as cur:
        cur.execute("SELECT marker FROM sentinel_backup_recovery_markers")
        assert cur.fetchall() == [("post-base-wal-marker",)]
    assert _ledger_rows(database)[0][2] == "NEW"


def test_only_the_exact_backup_relation_is_recognized(database):
    with database.cursor() as cur:
        cur.execute(
            "CREATE TABLE sentinel_backup_recovery_markers ("
            " marker TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL"
            " DEFAULT NOW(), unexpected TEXT)")
    database.commit()
    _assert_operator_refusal(database, reason="backup recovery-marker")


def test_backup_relation_with_an_extra_index_is_not_exact(database):
    with database.cursor() as cur:
        cur.execute(
            "CREATE TABLE sentinel_backup_recovery_markers ("
            " marker TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL"
            " DEFAULT NOW())")
        cur.execute(
            "CREATE INDEX unexpected_backup_marker_index"
            " ON sentinel_backup_recovery_markers(created_at)")
    database.commit()
    _assert_operator_refusal(database, reason="backup recovery-marker")


def test_unrelated_unknown_relation_still_refuses_markerless_bootstrap(database):
    with database.cursor() as cur:
        cur.execute("CREATE TABLE sentinel_unrelated_unknown (id INTEGER)")
    database.commit()
    _assert_operator_refusal(database, reason="unknown behavioral relations")


def test_public_builtin_shadows_cannot_change_migration_semantics(database):
    with database.cursor() as cur:
        cur.execute(
            "CREATE FUNCTION public.now() RETURNS timestamptz"
            " LANGUAGE SQL IMMUTABLE"
            " AS 'SELECT ''2000-01-01T00:00:00Z''::timestamptz'")
        cur.execute(
            "CREATE FUNCTION public.always_true(text,text) RETURNS boolean"
            " LANGUAGE SQL IMMUTABLE AS 'SELECT true'")
        cur.execute(
            "CREATE OPERATOR public.= (LEFTARG=text, RIGHTARG=text,"
            " FUNCTION=public.always_true)")
    database.commit()

    schema.ensure_schema(database)

    with database.cursor() as cur:
        cur.execute(
            "SELECT updated_at > '2026-01-01T00:00:00Z'::timestamptz"
            " FROM sentinel_rollout_state WHERE id=1")
        assert cur.fetchone() == (True,)
        with pytest.raises(Exception, match="constraint"):
            cur.execute(
                "UPDATE sentinel_rollout_state SET mode='NOT_A_MODE'"
                " WHERE id=1")
    database.rollback()
    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]


def test_real_pre_rollout_upgrade_seeds_but_leaves_old_plan_unstamped(database):
    _install_pre_rollout(database)
    with database.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_execution_plans"
            " (plan_id,decision_session,effective_session,target_exposure,"
            "  strategy_fingerprint,target_basket)"
            " VALUES ('legacy-plan','2026-08-10','2026-08-11',1,"
            "         'legacy-fingerprint','{\"legacy\":true}'::jsonb)")
        cur.execute(
            "INSERT INTO sentinel_ownership_events (state,detail)"
            " VALUES ('LEGACY', '{\"fixture\":\"69cdfe8\"}'::jsonb)")
    database.commit()

    schema.ensure_schema(database)

    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]
    ledger = _ledger_rows(database)
    assert [(row[0], row[1], row[2], row[3]) for row in ledger] == [
        (1, MIGRATION_NAME, "LEGACY", None)]
    with database.cursor() as cur:
        cur.execute(
            "SELECT rollout_mode,rollout_version,"
            "       rollout_certificate_sha256,strategy_fingerprint,"
            "       target_basket"
            " FROM sentinel_execution_plans WHERE plan_id='legacy-plan'")
        assert cur.fetchone() == (
            None, None, None, "legacy-fingerprint", {"legacy": True})
        cur.execute(
            "SELECT state,detail FROM sentinel_ownership_events ORDER BY seq")
        assert cur.fetchall() == [("LEGACY", {"fixture": "69cdfe8"})]
    assert _plan_rollout_columns(database) == [
        ("rollout_certificate_sha256", "YES", None),
        ("rollout_mode", "YES", None),
        ("rollout_version", "YES", None),
    ]
    with pytest.raises(journal.PlanAuthorityMissing,
                       match="(?i)rollout authority|unstamped"):
        journal.load_plan(database, "legacy-plan")
    # Current-plan discovery must not grant this row authority, but it also
    # must not dead-end normal preparation of the first stamped replacement.
    assert journal.latest_plan(database) is None
    replacement = ExecutionPlan(
        plan_id="stamped-replacement",
        decision_session=date(2026, 8, 11),
        effective_session=date(2026, 8, 12),
        target_exposure=Decimal("1"),
    )
    journal.save_plan(database, replacement, commit=False)
    with pytest.raises(journal.PlanAuthorityMissing,
                       match="(?i)stamped and unstamped|ambiguous"):
        journal.latest_plan(database)
    journal.supersede_all_but(database, replacement.plan_id)
    assert journal.latest_plan(database) == replacement
    with database.cursor() as cur:
        cur.execute(
            "SELECT superseded_by FROM sentinel_execution_plans"
            " WHERE plan_id='legacy-plan'")
        assert cur.fetchone() == (replacement.plan_id,)


def test_exact_fb97372_upgrade_backfills_command_identity_without_rewrite(
        database):
    _install_pre_rollout_fb97372(database)
    with database.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_account_binding"
            " (deployment_id,broker,broker_account_id,takeover_epoch,"
            "  ownership_state,established_at,updated_at,notes)"
            " VALUES ('legacy-deployment','ALPACA_PAPER','legacy-account',9,"
            "         'SENTINEL_OWNED','2026-08-09T09:00:00Z',"
            "         '2026-08-09T09:01:00Z','fb97372 binding')")
        cur.execute(
            "INSERT INTO sentinel_commands"
            " (client_key,plan_id,security_id,revision,symbol,"
            "  broker_instrument_id,side,quantity,state,broker_order_id,"
            "  filled_quantity,filled_average_price,detail,recovered,"
            "  created_at,updated_at)"
            " VALUES ('legacy-client-key','legacy-plan','sec-abc',4,'ABC',"
            "         'instrument-abc','BUY',12.75,'PARTIALLY_FILLED',"
            "         'broker-order-17',3.25,101.125,'preserve command',false,"
            "         '2026-08-09T09:02:00Z','2026-08-09T09:03:00Z')")
        cur.execute(
            "INSERT INTO sentinel_command_events"
            " (client_key,from_state,to_state,filled_quantity,detail,at)"
            " VALUES ('legacy-client-key','ACKNOWLEDGED',"
            "         'PARTIALLY_FILLED',3.25,'preserve event',"
            "         '2026-08-09T09:03:00Z')")
    database.commit()

    legacy_command = (
        "SELECT client_key,plan_id,security_id,revision,symbol,"
        "       broker_instrument_id,side,quantity,state,broker_order_id,"
        "       filled_quantity,filled_average_price,detail,recovered,"
        "       created_at,updated_at"
        " FROM sentinel_commands ORDER BY client_key")
    event_history = (
        "SELECT seq,client_key,from_state,to_state,filled_quantity,detail,at"
        " FROM sentinel_command_events ORDER BY seq")
    binding_state = (
        "SELECT id,deployment_id,broker,broker_account_id,takeover_epoch,"
        "       ownership_state,established_at,updated_at,notes"
        " FROM sentinel_account_binding ORDER BY id")
    with database.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema='public' AND table_name='sentinel_commands'"
            "   AND column_name IN"
            "       ('deployment_id','broker','broker_account_id',"
            "        'takeover_epoch')")
        assert cur.fetchall() == []
        cur.execute(legacy_command)
        command_before = cur.fetchall()
        cur.execute(event_history)
        events_before = cur.fetchall()
        cur.execute(binding_state)
        binding_before = cur.fetchall()

    schema.ensure_schema(database)

    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]
    ledger = _ledger_rows(database)
    assert [(row[0], row[1], row[2], row[3]) for row in ledger] == [
        (1, MIGRATION_NAME, "LEGACY", None)]
    with database.cursor() as cur:
        cur.execute(legacy_command)
        assert cur.fetchall() == command_before
        cur.execute(event_history)
        assert cur.fetchall() == events_before
        cur.execute(binding_state)
        assert cur.fetchall() == binding_before
        cur.execute(
            "SELECT deployment_id,broker,broker_account_id,takeover_epoch"
            " FROM sentinel_commands WHERE client_key='legacy-client-key'")
        assert cur.fetchone() == (
            "legacy-deployment", "ALPACA_PAPER", "legacy-account", 9)

    migration_snapshot_queries = {
        "rollout": (
            "SELECT id,mode,version,certificate_sha256,updated_at"
            " FROM sentinel_rollout_state ORDER BY id"),
        "rollout_events": (
            "SELECT seq,version,from_mode,to_mode,certificate_sha256,reason,at"
            " FROM sentinel_rollout_events ORDER BY seq"),
        "ledger": (
            "SELECT version,name,migration_sha256,bootstrap_kind,"
            "       source_git_oid,applied_at"
            " FROM sentinel_behavioral_schema_migrations ORDER BY version"),
        "binding": binding_state,
        "command": "SELECT * FROM sentinel_commands ORDER BY client_key",
        "events": event_history,
    }
    after_first_migration = {}
    with database.cursor() as cur:
        for name, query in migration_snapshot_queries.items():
            cur.execute(query)
            after_first_migration[name] = cur.fetchall()

    for _ in range(3):
        schema.ensure_schema(database)

    with database.cursor() as cur:
        for name, query in migration_snapshot_queries.items():
            cur.execute(query)
            assert cur.fetchall() == after_first_migration[name]


def test_markerless_legacy_with_missing_safety_index_is_not_recognized(
        database):
    _install_pre_rollout(database)
    with database.cursor() as cur:
        cur.execute("DROP INDEX idx_sentinel_commands_inflight")
    database.commit()

    _assert_operator_refusal(database, reason="fingerprint")

    assert _regclass(
        database, "sentinel_behavioral_schema_migrations") is None
    assert _regclass(database, "sentinel_rollout_state") is None
    assert _regclass(database, "idx_sentinel_commands_inflight") is None


def _seed_reviewed_controller_state(conn) -> None:
    manifest = {"fixture": REVIEWED_HEAD, "authority": "preserve-only"}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_system_certificates"
            " (certificate_sha256,manifest_bytes,manifest,"
            "  allowed_rollout_modes,installed_at)"
            " VALUES (%s,%s,%s::jsonb,%s::jsonb,"
            "         '2026-08-10T10:00:00Z')",
            (CERTIFICATE_SHA256, json.dumps(manifest).encode(),
             json.dumps(manifest), json.dumps(["CONTROLLER"])))
        cur.execute(
            "INSERT INTO sentinel_system_certificate_events"
            " (certificate_sha256,action,detail,at)"
            " VALUES (%s,'INSTALLED','historical fixture',"
            "         '2026-08-10T10:00:01Z')",
            (CERTIFICATE_SHA256,))
        cur.execute(
            "INSERT INTO sentinel_account_binding"
            " (deployment_id,broker,broker_account_id,takeover_epoch,"
            "  ownership_state,established_at,updated_at,notes)"
            " VALUES ('deployment-preserved','ALPACA_PAPER',"
            "         'paper-account-preserved',7,'SENTINEL_OWNED',"
            "         '2026-08-10T10:01:00Z','2026-08-10T10:02:00Z',"
            "         'must survive bridge')")
        cur.execute(
            "INSERT INTO sentinel_ownership_events (state,at,detail)"
            " VALUES ('SENTINEL_OWNED','2026-08-10T10:02:00Z',"
            "         '{\"epoch\":7}'::jsonb)")
        cur.execute(
            "INSERT INTO sentinel_rollout_state"
            " (id,mode,version,certificate_sha256,updated_at)"
            " VALUES (1,'CONTROLLER',2,%s,'2026-08-10T10:03:00Z')",
            (CERTIFICATE_SHA256,))
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason,at)"
            " VALUES (2,'PINNED_1_00','CONTROLLER',%s,"
            "         'historical controller transition',"
            "         '2026-08-10T10:03:00Z')",
            (CERTIFICATE_SHA256,))
        cur.execute(
            "INSERT INTO sentinel_execution_plans"
            " (plan_id,decision_session,effective_session,target_exposure,"
            "  data_version,shadow_snapshot_hash,sentinel_transition_hash,"
            "  strategy_fingerprint,deployment_id,broker,broker_account_id,"
            "  takeover_epoch,publication_fingerprint,account_nav,"
            "  account_cash,cash_residual,unpriced_securities,"
            "  defensive_security,rollout_mode,rollout_version,"
            "  rollout_certificate_sha256,target_basket,created_at)"
            " VALUES ('controller-plan','2026-08-10','2026-08-11',0.55,"
            "         41,'shadow-preserved','transition-preserved',"
            "         'strategy-preserved','deployment-preserved',"
            "         'ALPACA_PAPER','paper-account-preserved',7,"
            "         'publication-preserved',100000,45000,0,'[]'::jsonb,"
            "         'BIL','CONTROLLER',2,%s,"
            "         '{\"ABC\":55}'::jsonb,'2026-08-10T10:04:00Z')",
            (CERTIFICATE_SHA256,))
    conn.commit()


PRESERVED_QUERIES = {
    "rollout": (
        "SELECT id,mode,version,certificate_sha256,updated_at"
        " FROM sentinel_rollout_state ORDER BY id"),
    "rollout_events": (
        "SELECT version,from_mode,to_mode,certificate_sha256,reason,at"
        " FROM sentinel_rollout_events ORDER BY seq"),
    "certificates": (
        "SELECT certificate_sha256,manifest_bytes,manifest,"
        "       allowed_rollout_modes,installed_at,revoked_at,"
        "       revocation_reason"
        " FROM sentinel_system_certificates ORDER BY certificate_sha256"),
    "certificate_events": (
        "SELECT certificate_sha256,action,detail,at"
        " FROM sentinel_system_certificate_events ORDER BY seq"),
    "account": (
        "SELECT id,deployment_id,broker,broker_account_id,takeover_epoch,"
        "       ownership_state,established_at,updated_at,notes"
        " FROM sentinel_account_binding ORDER BY id"),
    "ownership_events": (
        "SELECT state,at,detail FROM sentinel_ownership_events ORDER BY seq"),
    "plans": (
        "SELECT plan_id,decision_session,effective_session,target_exposure,"
        "       data_version,shadow_snapshot_hash,sentinel_transition_hash,"
        "       strategy_fingerprint,deployment_id,broker,broker_account_id,"
        "       takeover_epoch,publication_fingerprint,account_nav,"
        "       account_cash,cash_residual,unpriced_securities,"
        "       defensive_security,rollout_mode,rollout_version,"
        "       rollout_certificate_sha256,target_basket,superseded_by,"
        "       created_at FROM sentinel_execution_plans ORDER BY plan_id"),
}


def _preserved_snapshot(conn):
    snapshot = {}
    with conn.cursor() as cur:
        for name, query in PRESERVED_QUERIES.items():
            cur.execute(query)
            snapshot[name] = cur.fetchall()
    return snapshot


def test_exact_6113_bridge_preserves_all_durable_operational_intent(database):
    _install_reviewed_head(database)
    _seed_reviewed_controller_state(database)
    before = _preserved_snapshot(database)

    schema.ensure_schema(database)

    assert _preserved_snapshot(database) == before
    ledger = _ledger_rows(database)
    assert [(row[0], row[1], row[2], row[3]) for row in ledger] == [
        (1, MIGRATION_NAME, "PR84_HEAD_BRIDGE", REVIEWED_HEAD)]
    assert _plan_rollout_columns(database) == [
        ("rollout_certificate_sha256", "YES", None),
        ("rollout_mode", "NO", None),
        ("rollout_version", "NO", None),
    ]


@pytest.mark.parametrize("damage", [
    "mode-default",
    "rollout-constraint",
    "active-certificate-index",
])
def test_markerless_6113_bridge_requires_exact_semantic_catalog(
        database, damage):
    _install_reviewed_head(database)
    _seed_reviewed_controller_state(database)
    before = _preserved_snapshot(database)
    with database.cursor() as cur:
        if damage == "mode-default":
            cur.execute(
                "ALTER TABLE sentinel_execution_plans"
                " ALTER COLUMN rollout_mode"
                " SET DEFAULT 'PINNED_1_00_CORRUPT'")
        elif damage == "rollout-constraint":
            cur.execute(
                "ALTER TABLE sentinel_rollout_state DROP CONSTRAINT"
                " sentinel_rollout_state_mode_check")
            cur.execute(
                "ALTER TABLE sentinel_rollout_state ADD CONSTRAINT"
                " sentinel_rollout_state_mode_check CHECK"
                " (mode IN ('PINNED_1_00','CONTROLLER','CORRUPT'))")
        elif damage == "active-certificate-index":
            cur.execute("DROP INDEX idx_sentinel_one_active_certificate")
            cur.execute(
                "CREATE UNIQUE INDEX idx_sentinel_one_active_certificate"
                " ON sentinel_system_certificates ((2))"
                " WHERE revoked_at IS NULL")
        else:                                                   # pragma: no cover
            raise AssertionError(damage)
    database.commit()

    _assert_operator_refusal(database)

    assert _regclass(
        database, "sentinel_behavioral_schema_migrations") is None
    assert _preserved_snapshot(database) == before


@pytest.mark.parametrize("damage", ["singleton", "table"])
def test_damaged_exact_6113_schema_is_not_misclassified_as_bridge_or_legacy(
        database, damage):
    """The one-time markerless bridge is closed to partial PR-head loss."""
    _install_reviewed_head(database)
    _seed_reviewed_controller_state(database)
    with database.cursor() as cur:
        if damage == "singleton":
            cur.execute("DELETE FROM sentinel_rollout_state WHERE id=1")
        else:
            cur.execute("DROP TABLE sentinel_rollout_state")
    database.commit()
    with database.cursor() as cur:
        cur.execute(
            "SELECT version,reason FROM sentinel_rollout_events ORDER BY seq")
        events_before = cur.fetchall()
        cur.execute(
            "SELECT certificate_sha256 FROM sentinel_system_certificates")
        certificates_before = cur.fetchall()
        cur.execute(
            "SELECT plan_id,rollout_mode,rollout_version,"
            "       rollout_certificate_sha256"
            " FROM sentinel_execution_plans")
        plans_before = cur.fetchall()

    _assert_operator_refusal(database)

    assert _regclass(
        database, "sentinel_behavioral_schema_migrations") is None
    if damage == "singleton":
        assert _regclass(database, "sentinel_rollout_state") is not None
        assert _rollout_rows(database) == []
    else:
        assert _regclass(database, "sentinel_rollout_state") is None
    with database.cursor() as cur:
        cur.execute(
            "SELECT version,reason FROM sentinel_rollout_events ORDER BY seq")
        assert cur.fetchall() == events_before
        cur.execute(
            "SELECT certificate_sha256 FROM sentinel_system_certificates")
        assert cur.fetchall() == certificates_before
        cur.execute(
            "SELECT plan_id,rollout_mode,rollout_version,"
            "       rollout_certificate_sha256"
            " FROM sentinel_execution_plans")
        assert cur.fetchall() == plans_before


def test_deleted_current_singleton_refuses_across_ensure_and_restart(database, pg):
    schema.ensure_schema(database)
    _advance_current_schema_to_controller(
        database, reason="controller posture lost with singleton")
    with database.cursor() as cur:
        cur.execute("DELETE FROM sentinel_rollout_state WHERE id=1")
    database.commit()

    _assert_operator_refusal(database, reason="rollout")
    assert _rollout_rows(database) == []
    with database.cursor() as cur:
        cur.execute("SELECT version,reason FROM sentinel_rollout_events")
        assert cur.fetchall() == [
            (2, "controller posture lost with singleton")]

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        _assert_operator_refusal(restarted, reason="rollout")
        assert _rollout_rows(restarted) == []
    finally:
        restarted.close()


def test_deleted_current_rollout_table_with_history_is_never_repaired(
        database, pg):
    schema.ensure_schema(database)
    _advance_current_schema_to_controller(
        database, reason="preserved history")
    with database.cursor() as cur:
        cur.execute("DROP TABLE sentinel_rollout_state")
    database.commit()

    _assert_operator_refusal(database, reason="rollout")
    assert _regclass(database, "sentinel_rollout_state") is None
    with database.cursor() as cur:
        cur.execute("SELECT version,reason FROM sentinel_rollout_events")
        assert cur.fetchall() == [(2, "preserved history")]

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        _assert_operator_refusal(restarted, reason="rollout")
        assert _regclass(restarted, "sentinel_rollout_state") is None
    finally:
        restarted.close()


def test_ledgered_schema_with_missing_safety_index_refuses_without_repair(
        database):
    schema.ensure_schema(database)
    with database.cursor() as cur:
        cur.execute("DROP INDEX idx_sentinel_commands_inflight")
    database.commit()

    _assert_operator_refusal(database, reason="catalog fingerprint")

    assert _regclass(database, "idx_sentinel_commands_inflight") is None
    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]


def test_ledgered_schema_with_invalid_safety_index_refuses(database):
    schema.ensure_schema(database)
    # PostgreSQL can leave this exact named/defined index INVALID after a
    # failed CREATE INDEX CONCURRENTLY. Catalog authority must inspect the
    # enforcement flags, not merely pg_indexes text.
    with database.cursor() as cur:
        cur.execute(
            "UPDATE pg_index SET indisvalid=false"
            " WHERE indexrelid='idx_sentinel_commands_inflight'::regclass")
    database.commit()

    _assert_operator_refusal(database, reason="catalog fingerprint")

    with database.cursor() as cur:
        cur.execute(
            "SELECT indisvalid FROM pg_index"
            " WHERE indexrelid='idx_sentinel_commands_inflight'::regclass")
        assert cur.fetchone() == (False,)


def test_safety_index_predicate_literal_case_is_semantic(database):
    schema.ensure_schema(database)
    with database.cursor() as cur:
        cur.execute("DROP INDEX idx_sentinel_commands_inflight")
        cur.execute(
            "CREATE UNIQUE INDEX idx_sentinel_commands_inflight"
            " ON sentinel_commands (security_id)"
            " WHERE state IN ('send_pending','acknowledged','unknown',"
            "                 'partially_filled','cancel_pending')")
    database.commit()

    _assert_operator_refusal(database, reason="catalog fingerprint")

    with database.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes"
            " WHERE indexname='idx_sentinel_commands_inflight'")
        assert "'send_pending'" in cur.fetchone()[0]


@pytest.mark.parametrize("damage", [
    "column-type",
    "column-default",
    "constraint-definition",
    "index-definition",
    "unexpected-trigger",
    "unexpected-column",
])
def test_stage4_runtime_requires_complete_semantic_catalog(database, damage):
    schema.ensure_schema(database)
    with database.cursor() as cur:
        if damage == "column-type":
            cur.execute(
                "ALTER TABLE sentinel_automation_service_instances"
                " ALTER COLUMN authority_detail TYPE VARCHAR(64)")
        elif damage == "column-default":
            cur.execute(
                "ALTER TABLE sentinel_automation_control"
                " ALTER COLUMN enabled SET DEFAULT TRUE")
        elif damage == "constraint-definition":
            cur.execute(
                "ALTER TABLE sentinel_alert_dispatcher_health DROP CONSTRAINT"
                " sentinel_alert_dispatcher_health_state_check")
            cur.execute(
                "ALTER TABLE sentinel_alert_dispatcher_health ADD CONSTRAINT"
                " sentinel_alert_dispatcher_health_state_check CHECK"
                " (state IN ('STARTING','HEALTHY','DEGRADED','FAILED','CORRUPT'))")
        elif damage == "index-definition":
            cur.execute(
                "DROP INDEX idx_sentinel_alert_dispatcher_health_heartbeat")
            cur.execute(
                "CREATE INDEX idx_sentinel_alert_dispatcher_health_heartbeat"
                " ON sentinel_alert_dispatcher_health (heartbeat_at,state)")
        elif damage == "unexpected-trigger":
            cur.execute(
                "CREATE TRIGGER sentinel_alert_outbox_corrupt_trigger"
                " BEFORE UPDATE ON sentinel_alert_outbox FOR EACH ROW"
                " EXECUTE FUNCTION sentinel_refuse_trial_evidence_mutation()")
        elif damage == "unexpected-column":
            cur.execute(
                "ALTER TABLE sentinel_automation_lease"
                " ADD COLUMN corrupt_extension TEXT")
        else:                                                   # pragma: no cover
            raise AssertionError(damage)
    database.commit()

    with pytest.raises(schema.SchemaMigrationRefused, match="Stage-4"):
        schema.require_runtime_schema(database)
    database.rollback()
    _assert_operator_refusal(database, reason="Stage-4")


def test_unlogged_rollout_authority_is_not_a_durable_current_schema(database):
    schema.ensure_schema(database)
    with database.cursor() as cur:
        cur.execute("ALTER TABLE sentinel_rollout_state SET UNLOGGED")
    database.commit()

    _assert_operator_refusal(database, reason="rollout_state")

    with database.cursor() as cur:
        cur.execute(
            "SELECT relpersistence FROM pg_class"
            " WHERE oid='sentinel_rollout_state'::regclass")
        assert cur.fetchone() == ("u",)
    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]


def _ledger_shape(conn):
    if _regclass(conn, "sentinel_behavioral_schema_migrations") is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,name,migration_sha256,bootstrap_kind,source_git_oid"
            " FROM sentinel_behavioral_schema_migrations ORDER BY version")
        return cur.fetchall()


@pytest.mark.parametrize("damage", [
    "missing",
    "empty",
    "corrupt-name",
    "corrupt-hash",
    "corrupt-bootstrap",
    "corrupt-source",
    "gapped",
    "future",
])
def test_missing_or_corrupt_migration_authority_refuses_without_repair(
        database, damage):
    schema.ensure_schema(database)
    _advance_current_schema_to_controller(
        database, reason=f"preserve controller across {damage} ledger")
    with database.cursor() as cur:
        if damage == "missing":
            cur.execute("DROP TABLE sentinel_behavioral_schema_migrations")
        elif damage == "empty":
            cur.execute("DELETE FROM sentinel_behavioral_schema_migrations")
        elif damage == "corrupt-name":
            cur.execute(
                "UPDATE sentinel_behavioral_schema_migrations"
                " SET name='corrupt-authority' WHERE version=1")
        elif damage == "corrupt-hash":
            cur.execute(
                "UPDATE sentinel_behavioral_schema_migrations"
                " SET migration_sha256=%s WHERE version=1", ("f" * 64,))
        elif damage == "corrupt-bootstrap":
            cur.execute(
                "ALTER TABLE sentinel_behavioral_schema_migrations"
                " ALTER COLUMN bootstrap_kind DROP NOT NULL")
            cur.execute(
                "UPDATE sentinel_behavioral_schema_migrations"
                " SET bootstrap_kind=NULL WHERE version=1")
        elif damage == "corrupt-source":
            cur.execute(
                "UPDATE sentinel_behavioral_schema_migrations"
                " SET bootstrap_kind='PR84_HEAD_BRIDGE',source_git_oid=%s"
                " WHERE version=1", ("e" * 40,))
        elif damage in {"gapped", "future"}:
            if damage == "gapped":
                # A ledger that starts at version 2 has no contiguous v1 base.
                cur.execute(
                    "UPDATE sentinel_behavioral_schema_migrations"
                    " SET version=2,name='rollout-authority-v2'"
                    " WHERE version=1")
            else:
                # Contiguous, but this binary knows no behavioral version 2.
                cur.execute(
                    "INSERT INTO sentinel_behavioral_schema_migrations"
                    " (version,name,migration_sha256,bootstrap_kind,source_git_oid)"
                    " SELECT 2,'unsupported-authority-v2',migration_sha256,"
                    "        bootstrap_kind,source_git_oid"
                    " FROM sentinel_behavioral_schema_migrations"
                    " WHERE version=1")
        else:                                                   # pragma: no cover
            raise AssertionError(damage)
    database.commit()
    before = _ledger_shape(database)

    _assert_operator_refusal(database, reason="migration")

    assert _ledger_shape(database) == before
    assert _rollout_rows(database) == [
        (1, "CONTROLLER", 2, CERTIFICATE_SHA256)]
    with database.cursor() as cur:
        cur.execute("SELECT version,reason FROM sentinel_rollout_events")
        assert cur.fetchall() == [
            (2, f"preserve controller across {damage} ledger")]
    # The missing-ledger case is distinguishable from the exact 6113 bridge by
    # this post-ledger witness; startup must not recreate the ledger.
    assert [(name, default) for name, _nullable, default
            in _plan_rollout_columns(database)] == [
        ("rollout_certificate_sha256", None),
        ("rollout_mode", None),
        ("rollout_version", None),
    ]


def test_four_concurrent_first_initializers_serialize_to_one_seed(database, pg):
    start = threading.Barrier(4)

    def initialize() -> None:
        worker = feed_store.connect(pg.sync_dsn)
        try:
            start.wait(timeout=15)
            schema.ensure_schema(worker)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(initialize) for _ in range(4)]
        for future in futures:
            future.result(timeout=45)

    assert _rollout_rows(database) == [(1, "PINNED_1_00", 1, None)]
    ledger = _ledger_rows(database)
    assert [(row[0], row[1]) for row in ledger] == [
        (1, MIGRATION_NAME)]
    with database.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_rollout_events")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("bootstrap", ["empty", "legacy"])
@pytest.mark.parametrize("fault", ["seed", "post-seed"])
def test_migration_or_seed_failure_rolls_back_every_effect(
        database, monkeypatch, bootstrap, fault):
    if bootstrap == "legacy":
        _install_pre_rollout(database)
        with database.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_execution_plans"
                " (plan_id,decision_session,effective_session,target_exposure)"
                " VALUES ('rollback-plan','2026-08-10','2026-08-11',1)")
        database.commit()

    if fault == "seed":
        monkeypatch.setattr(
            schema, "_INITIAL_ROLLOUT_STATE",
            "INSERT INTO sentinel_rollout_state (id,mode,version)"
            " VALUES (1,'NOT_A_MODE',1)")
        failure_pattern = "constraint|sentinel_rollout_state"
    else:
        # _MIGRATION_FINALIZE_DDL runs after the singleton insert. This proves
        # a later DDL failure rolls that seed back as part of the same xact.
        monkeypatch.setattr(
            schema, "_MIGRATION_FINALIZE_DDL",
            (*schema._MIGRATION_FINALIZE_DDL, "SELECT 1 / 0"))
        failure_pattern = "division by zero"
    with pytest.raises(Exception, match=failure_pattern):  # driver-neutral
        schema.ensure_schema(database)
    # ensure_schema itself must have rolled the transaction back and released
    # its xact lock; a caller must not need a cleanup rollback before reuse.
    with database.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)

    assert _regclass(
        database, "sentinel_behavioral_schema_migrations") is None
    assert _regclass(database, "sentinel_rollout_state") is None
    if bootstrap == "empty":
        with database.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname='public' AND tablename LIKE 'sentinel_%'")
            assert cur.fetchall() == []
    else:
        assert _regclass(database, "sentinel_execution_plans") is not None
        assert _plan_rollout_columns(database) == []
        with database.cursor() as cur:
            cur.execute(
                "SELECT plan_id,target_exposure FROM sentinel_execution_plans")
            assert cur.fetchall() == [("rollback-plan", Decimal("1"))]


def test_6113_bridge_failure_rolls_back_witness_and_preserves_state(
        database, monkeypatch):
    _install_reviewed_head(database)
    _seed_reviewed_controller_state(database)
    before = _preserved_snapshot(database)
    columns_before = _plan_rollout_columns(database)
    monkeypatch.setattr(
        schema, "_MIGRATION_FINALIZE_DDL",
        (*schema._MIGRATION_FINALIZE_DDL, "SELECT 1 / 0"))

    with pytest.raises(Exception, match="division by zero"):
        schema.ensure_schema(database)

    with database.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
        cur.execute(
            "SELECT COUNT(*) FROM pg_constraint"
            " WHERE conname='sentinel_execution_plan_rollout_authority_ck'")
        assert cur.fetchone() == (0,)
    assert _regclass(
        database, "sentinel_behavioral_schema_migrations") is None
    assert _plan_rollout_columns(database) == columns_before
    assert _preserved_snapshot(database) == before


def test_repeated_ensure_schema_is_a_data_and_authority_noop(database):
    schema.ensure_schema(database)
    with database.cursor() as cur:
        cur.execute(
            "SELECT mode,version,certificate_sha256,updated_at"
            " FROM sentinel_rollout_state WHERE id=1")
        rollout_before = cur.fetchone()
    ledger_before = _ledger_rows(database)
    columns_before = _plan_rollout_columns(database)

    for _ in range(5):
        schema.ensure_schema(database)

    with database.cursor() as cur:
        cur.execute(
            "SELECT mode,version,certificate_sha256,updated_at"
            " FROM sentinel_rollout_state WHERE id=1")
        assert cur.fetchone() == rollout_before
    assert _ledger_rows(database) == ledger_before
    assert _plan_rollout_columns(database) == columns_before
