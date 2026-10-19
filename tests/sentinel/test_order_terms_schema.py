"""Exact v1 predecessor upgrade; authority loss is never a migration input."""
import json
import inspect
import os
from pathlib import Path
import textwrap

import psycopg
import pytest

from sentinel import schema
from tests.support.postgres import _EphemeralPostgres, drop_public_tables

FIXTURES = Path(__file__).with_name("fixtures")
PRE_ROLLOUT = FIXTURES / "behavioral_schema_pre_rollout_69cdfe8.sql"
REVIEWED_HEAD_DELTA = FIXTURES / "behavioral_schema_6113bffd_delta.sql"


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres(); server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def database(pg):
    with psycopg.connect(pg.sync_dsn) as conn:
        drop_public_tables(conn)
        yield conn


def _install_sql(conn, *paths):
    for path in paths:
        for statement in path.read_text().replace("\r\n", "\n").strip().split(";\n\n"):
            conn.execute(statement)
    conn.commit()


def _ledger_rows(conn):
    return conn.execute("SELECT version,name,bootstrap_kind,source_git_oid,applied_at "
        "FROM sentinel_behavioral_schema_migrations ORDER BY version").fetchall()


def install_v1(conn, kind="NEW"):
    if kind == "LEGACY":
        _install_sql(conn, PRE_ROLLOUT)
    elif kind == "PR84_HEAD_BRIDGE":
        _install_sql(conn, PRE_ROLLOUT, REVIEWED_HEAD_DELTA)
    text = (FIXTURES / "behavioral_schema_v1_ce308302.sql").read_text()
    source = "'6113bffd896824ee24891b0c1aeada60c2b73ef5'" if kind == "PR84_HEAD_BRIDGE" else "NULL"
    old = "'NEW',NULL)"
    assert text.count(old) == 1
    text = text.replace(old, repr(kind) + "," + source + ")")
    for statement in text.strip().split(";\n\n"):
        conn.execute(statement)
    conn.commit()


@pytest.mark.parametrize("kind", ["NEW", "LEGACY", "PR84_HEAD_BRIDGE"])
def test_v2_catalog_matches_reviewed_migration(database, kind):
    install_v1(database, kind)
    with database.cursor() as cur:
        cur.execute("SET LOCAL search_path TO public,pg_temp")
        cur.execute("SELECT pg_advisory_xact_lock(%s,%s)", schema._SCHEMA_LOCK)
        catalog = schema._read_catalog(cur)
        assert schema._validate_ledgered(cur, catalog, allow_previous=True) == 1
        schema._migrate_order_terms(cur, catalog)
        prior = catalog
        catalog = schema._read_catalog(cur)
        observed = schema._semantic_catalog_sha256(*catalog, schema._CURRENT_TABLES)
        directory = os.environ.get("SENTINEL_TEST_SCHEMA_CATALOG_EVIDENCE")
        if directory:
            with (Path(directory) / (kind + "-catalog.json")).open("x") as stream:
                json.dump(dict(bootstrap_kind=kind, before_catalog=prior, after_catalog=catalog,
                    after_core_sha256=observed, before_core_sha256=schema._semantic_catalog_sha256(*prior, schema._CURRENT_TABLES),
                    before_stage4_sha256=schema._semantic_catalog_sha256(*prior, schema._STAGE4_TABLES),
                    after_stage4_sha256=schema._semantic_catalog_sha256(*catalog, schema._STAGE4_TABLES)), stream, indent=2, default=str)
        print("CATALOG_DERIVATION", kind, observed, flush=True)
        assert observed == schema._ORDER_TERMS_TARGET_CATALOG_SHA256[kind], (kind, observed)
        assert schema._validate_ledgered(cur, catalog) == 2


def test_v1_runtime_refuses_but_explicit_upgrade_preserves_rows_and_ledger(database):
    install_v1(database)
    database.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,revision,"
        "deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state,detail) "
        "VALUES ('old-key','old-plan','old-security',3,'old-deploy','sim','old-account',1,"
        "'OLD','BUY',7,'UNKNOWN','preserve exact history')")
    database.execute("INSERT INTO sentinel_command_events(client_key,from_state,to_state,detail) "
        "VALUES ('old-key','SEND_PENDING','UNKNOWN','preserve event')")
    database.commit()
    before = database.execute("SELECT * FROM sentinel_commands").fetchall()
    events = database.execute("SELECT * FROM sentinel_command_events").fetchall()
    ledger = _ledger_rows(database)
    with pytest.raises(schema.SchemaMigrationRefused, match="v2.*required"):
        schema.require_runtime_schema(database)
    schema.ensure_schema(database)
    row = database.execute("SELECT * FROM sentinel_commands").fetchone()
    assert row[:-1] == before[0]
    assert row[-1] == schema._LEGACY_ORDER_TERMS
    assert database.execute("SELECT * FROM sentinel_command_events").fetchall() == events
    assert _ledger_rows(database)[0] == ledger[0]
    assert [row[0] for row in _ledger_rows(database)] == [1, 2]
    schema.require_runtime_schema(database)
    snapshot = _ledger_rows(database)
    schema.ensure_schema(database)
    assert _ledger_rows(database) == snapshot


@pytest.mark.parametrize("fence", ["enabled", "live-leader"])
def test_v1_upgrade_requires_fenced_automation(database, fence):
    install_v1(database)
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
    assert [row[0] for row in _ledger_rows(database)] == [1]
    assert not database.execute("SELECT 1 FROM information_schema.columns WHERE "
        "table_name='sentinel_commands' AND column_name='order_terms'").fetchall()


def test_late_v2_failure_rolls_back_column_and_new_ledger(database, monkeypatch):
    install_v1(database)
    before = _ledger_rows(database)
    monkeypatch.setattr(schema, "_ORDER_TERMS_DDL", (*schema._ORDER_TERMS_DDL, "SELECT 1/0"))
    with pytest.raises(Exception, match="division by zero"):
        schema.ensure_schema(database)
    assert _ledger_rows(database) == before
    assert not database.execute("SELECT 1 FROM information_schema.columns WHERE "
        "table_name='sentinel_commands' AND column_name='order_terms'").fetchall()


@pytest.mark.parametrize("damage", ["row2", "column", "default", "constraint", "checksum"])
def test_v2_partial_authority_refuses_without_repair(database, damage):
    schema.ensure_schema(database)
    queries = {
        "row2": "DELETE FROM sentinel_behavioral_schema_migrations WHERE version=2",
        "column": "ALTER TABLE sentinel_commands DROP COLUMN order_terms",
        "default": "ALTER TABLE sentinel_commands ALTER COLUMN order_terms DROP DEFAULT",
        "constraint": "ALTER TABLE sentinel_commands DROP CONSTRAINT sentinel_command_order_terms_ck",
        "checksum": "UPDATE sentinel_behavioral_schema_migrations SET migration_sha256=repeat('f',64) WHERE version=2",
    }
    database.execute(queries[damage]); database.commit()
    with pytest.raises(schema.SchemaMigrationRefused):
        schema.ensure_schema(database)
    with pytest.raises(schema.SchemaMigrationRefused):
        schema.require_runtime_schema(database)


def test_column_rejects_ambiguous_owned_terms_without_python_validation(database):
    schema.ensure_schema(database)
    legacy = schema._LEGACY_ORDER_TERMS
    invalid = [None, {}, {**legacy, "limit_price": "10"},
        {**legacy, "order_type": "limit"},
        {**legacy, "order_type": "limit", "limit_price": "NaN"},
        {**legacy, "order_type": "limit", "limit_price": "-1"},
        {**legacy, "extended_hours": "false"}, {**legacy, "extra": False}]
    for terms in invalid:
        with pytest.raises(psycopg.errors.CheckViolation, match="order_terms"):
            database.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,"
                "deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state,order_terms) "
                "VALUES ('bad','p','s','d','sim','a',1,'S','BUY',1,'PLANNED',%s::jsonb)", (json.dumps(terms),))
        database.rollback()


def _compiled(function, before, after):
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(before) == 1
    namespace = {}
    exec(compile(source.replace(before, after), "<private-order-terms-falsifier>", "exec"),
         function.__globals__, namespace)
    return namespace[function.__name__]


def test_runtime_version_falsifier_detects_removed_v2_requirement(database, monkeypatch):
    monkeypatch.setattr(schema, "_validate_ledgered", _compiled(schema._validate_ledgered,
        "elif not allow_previous:", "elif False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_v1_runtime_refuses_but_explicit_upgrade_preserves_rows_and_ledger(database)


@pytest.mark.parametrize("fence", ["enabled", "live-leader"])
def test_migration_fence_falsifier_detects_removed_authority_check(database, monkeypatch, fence):
    monkeypatch.setattr(schema, "_migrate_order_terms", _compiled(schema._migrate_order_terms,
        "if ((enabled and not killed)\n"
        "            or (holder is not None and live and lease_generation == generation)):",
        "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_v1_upgrade_requires_fenced_automation(database, fence)
