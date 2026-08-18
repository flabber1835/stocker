"""Issue #165 — routine feed runtime must never run migration DDL."""
from __future__ import annotations

import inspect
import os
from pathlib import Path
import re

import pytest

from sentinel import __main__ as cli
from sentinel import automation_runtime, schema as behavioral_schema
from sentinel.feed import runtime_schema
from sentinel.feed import store as feed_store


DDL_WORD = re.compile(r"\b(CREATE|DROP|ALTER|TRUNCATE)\b", re.IGNORECASE)
WRITE_WORD = re.compile(
    r"\b(CREATE|DROP|ALTER|TRUNCATE|INSERT|UPDATE|DELETE)\b",
    re.IGNORECASE,
)


class RecordingCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        text = str(sql)
        self.conn.executed.append((text, params))
        if "pg_try_advisory_xact_lock_shared" in text:
            self._row = (self.conn.shared_lock_available,)
        elif "pg_try_advisory_xact_lock(" in text:
            self._row = (self.conn.exclusive_lock_available,)
        else:
            self._row = None

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class RecordingConnection:
    def __init__(self, *, shared=True, exclusive=True):
        self.shared_lock_available = shared
        self.exclusive_lock_available = exclusive
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _sql(conn):
    return [statement for statement, _params in conn.executed]


def test_store_api_separates_runtime_validation_from_explicit_migration():
    runtime_source = inspect.getsource(feed_store.ensure_schema)
    required_source = inspect.getsource(feed_store.require_feed_schema)
    migration_source = inspect.getsource(feed_store.migrate_schema)
    implementation = inspect.getsource(runtime_schema.migrate_feed_schema)

    assert "require_feed_schema(conn)" in runtime_source
    assert "conn.commit()" not in runtime_source
    assert "runtime_schema" in required_source
    assert "migrate_feed_schema" in migration_source
    assert "for statement in DDL" in implementation
    assert "conn.commit()" in implementation
    assert feed_store.ensure_schema is not feed_store.migrate_schema


def test_runtime_validator_function_is_select_only():
    source = inspect.getsource(runtime_schema.require_feed_schema)
    assert "for statement in DDL" not in source
    assert "migrate_feed_schema" not in source
    assert "conn.commit()" not in source
    assert "pg_try_advisory_xact_lock_shared" in source


def test_runtime_validation_refuses_missing_schema_without_any_write_or_ddl():
    conn = RecordingConnection()

    with pytest.raises(runtime_schema.FeedSchemaRefused, match="relation"):
        runtime_schema.require_feed_schema(conn)

    statements = _sql(conn)
    assert statements
    assert all(WRITE_WORD.search(statement) is None for statement in statements)
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_runtime_validation_refuses_while_explicit_migration_lock_is_held():
    conn = RecordingConnection(shared=False)

    with pytest.raises(runtime_schema.FeedSchemaRefused, match="migration lock"):
        runtime_schema.require_feed_schema(conn)

    statements = _sql(conn)
    assert len(statements) == 1
    assert "pg_try_advisory_xact_lock_shared" in statements[0]
    assert DDL_WORD.search(statements[0]) is None
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_production_binding_uses_the_existing_controlled_schema_refusal():
    conn = RecordingConnection()

    with pytest.raises(behavioral_schema.SchemaMigrationRefused, match="feed-schema"):
        feed_store.ensure_schema(conn)

    assert all(WRITE_WORD.search(statement) is None for statement in _sql(conn))
    assert conn.commits == 0


def test_explicit_migration_is_the_only_feed_path_that_executes_ddl(monkeypatch):
    conn = RecordingConnection()
    monkeypatch.setattr(runtime_schema, "_validate_catalog", lambda _catalog: None)
    monkeypatch.setattr(runtime_schema, "_validate_views", lambda _cur: None)

    feed_store.migrate_schema(conn)

    statements = _sql(conn)
    assert any(DDL_WORD.search(statement) for statement in statements)
    assert any("DROP INDEX IF EXISTS uq_sentinel_anomaly_split_event_run"
               in statement for statement in statements)
    assert any("DROP INDEX IF EXISTS idx_sentinel_action_obs_window"
               in statement for statement in statements)
    assert any("DROP VIEW IF EXISTS sentinel_active_actions"
               in statement for statement in statements)
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_destructive_migration_objects_are_semantically_catalog_validated():
    assert "uq_sentinel_anomaly_split_event_run" in runtime_schema._INDEX_WITNESSES
    assert "idx_sentinel_action_obs_window" in runtime_schema._INDEX_WITNESSES
    assert "sentinel_active_actions" in runtime_schema._VIEW_WITNESSES
    assert "sentinel_active_ingest_rejections" in runtime_schema._VIEW_WITNESSES


def test_required_constraint_semantics_are_not_name_only():
    assert runtime_schema._PRIMARY_KEYS["sentinel_bars"] == (
        "primary key (security_id, session)")
    assert "sentinel_action_generation_events" in runtime_schema._CONSTRAINT_WITNESSES
    assert "sentinel_anomaly_observation_events" in runtime_schema._CONSTRAINT_WITNESSES


def test_all_production_automation_callbacks_use_runtime_validation_not_migration():
    for method in (
        automation_runtime.ProductionAutomation.refresh,
        automation_runtime.ProductionAutomation.prepare,
        automation_runtime.ProductionAutomation.recover,
        automation_runtime.ProductionAutomation.execute,
    ):
        source = inspect.getsource(method)
        assert "feed_store.require_feed_schema(conn)" in source
        assert "migrate_schema" not in source


def test_normal_cli_operations_never_name_the_feed_migration():
    runtime_functions = (
        cli.cmd_target_book,
        cli.cmd_check_data,
        cli.cmd_feed_repair,
        cli.cmd_rejection_audit,
        cli.cmd_feed,
        cli._prepare_paper_plan,
        cli._current_paper_plan,
        cli._execute_paper_plan,
    )
    for function in runtime_functions:
        assert "migrate_schema" not in inspect.getsource(function)


def _migration_phase(script: str, next_method: str) -> str:
    root = Path(os.environ.get("SENTINEL_REPO_ROOT")
                or Path(__file__).resolve().parents[2])
    path = root / "scripts" / script
    source = path.read_text(encoding="utf-8")
    assert source.count("store.migrate_schema(c)") == 1
    start = source.index("    def quiesce_backup_and_migrate(self) -> None:")
    end = source.index(f"\n    def {next_method}", start)
    return source[start:end]


def test_core_autonomous_deploy_migrates_feed_only_after_quiesce_and_restore():
    phase = _migration_phase("sentinel_autonomous_deploy.py", "refresh_data(self)")

    assert "self._direct_stop_automation()" in phase
    assert "scripts/sentinel-restore-drill.sh" in phase
    assert "schema.ensure_schema(c); store.migrate_schema(c);" in phase
    assert phase.index("self._direct_stop_automation()") < phase.index(
        "store.migrate_schema(c)")
    assert phase.index("scripts/sentinel-restore-drill.sh") < phase.index(
        "store.migrate_schema(c)")


def test_bootstrap_autonomous_deploy_cannot_skip_feed_migration():
    phase = _migration_phase(
        "sentinel_autonomous_deploy_bootstrap.py",
        "persist_success(self, health: Mapping)")

    assert "self._direct_stop_automation()" in phase
    assert "self._create_backup(restore_drill=True)" in phase
    assert "schema.ensure_schema(c); store.migrate_schema(c);" in phase
    assert phase.index("self._direct_stop_automation()") < phase.index(
        "store.migrate_schema(c)")
    assert phase.index("self._create_backup(restore_drill=True)") < phase.index(
        "store.migrate_schema(c)")
