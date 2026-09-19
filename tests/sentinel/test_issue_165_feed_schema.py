"""Issue #165 — routine feed runtime must never run migration DDL."""
from __future__ import annotations

import inspect
import importlib
import io
from contextlib import nullcontext, redirect_stdout
import os
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime, schema as behavioral_schema
from sentinel.cli import account as account_cli
from sentinel.cli import feed as feed_cli
from sentinel.cli import paper as paper_cli
from sentinel.feed import runtime_schema
from sentinel.feed import staging
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
    required_source = inspect.getsource(feed_store.require_feed_schema)
    migration_source = inspect.getsource(feed_store.migrate_schema)
    implementation = inspect.getsource(runtime_schema.migrate_feed_schema)

    assert not hasattr(feed_store, "ensure_schema")
    assert "conn.commit()" not in required_source
    assert "runtime_schema" in required_source
    assert "migrate_feed_schema" in migration_source
    assert "for statement in DDL" in implementation
    assert "conn.commit()" in implementation
    assert feed_store.require_feed_schema is not feed_store.migrate_schema


def test_runtime_validator_function_is_select_only():
    source = inspect.getsource(runtime_schema.require_feed_schema)
    assert "for statement in DDL" not in source
    assert "migrate_feed_schema" not in source
    assert "conn.commit()" not in source
    assert "pg_try_advisory_xact_lock_shared" in source


@pytest.mark.parametrize("operation", ["stage", "staged"])
def test_staging_never_installs_columns_during_normal_io(monkeypatch, operation):
    class RuntimeCursor(RecordingCursor):
        rowcount = 0

        def execute(self, sql, params=None):
            assert DDL_WORD.search(str(sql)) is None, "runtime staging executed DDL"
            super().execute(sql, params)

    class RuntimeConnection(RecordingConnection):
        def cursor(self):
            return RuntimeCursor(self)

    monkeypatch.setattr(
        feed_store, "streaming_cursor",
        lambda *_args, **_kwargs: nullcontext(iter(())))
    conn = RuntimeConnection()
    scope = {"run_id": "00000000-0000-0000-0000-000000000165", "chunk": "ddl"}
    if operation == "stage":
        assert staging.stage(conn, (), **scope) == 0
    else:
        assert list(staging.staged(conn, **scope)) == []


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
        feed_store.require_feed_schema(conn)

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
        account_cli.cmd_target_book,
        feed_cli.cmd_check_data,
        feed_cli.cmd_feed_repair,
        feed_cli.cmd_rejection_audit,
        feed_cli.cmd_feed_seed,
        paper_cli._prepare_paper_plan,
        paper_cli._current_paper_plan,
        paper_cli._execute_paper_plan,
    )
    for function in runtime_functions:
        assert "migrate_schema" not in inspect.getsource(function)


def _migration_trace(monkeypatch, *, bootstrap=False):
    """Execute both migration owners and their generated Python, without I/O."""
    root = Path(os.environ.get("SENTINEL_REPO_ROOT")
                or Path(__file__).resolve().parents[2])
    monkeypatch.syspath_prepend(str(root / "scripts"))
    module = importlib.import_module(
        "sentinel_autonomous_deploy_bootstrap" if bootstrap else "sentinel_autonomous_deploy")
    cls = module.BootstrapDeploy if bootstrap else module.AutonomousDeploy
    obj = object.__new__(cls)
    obj.cfg = SimpleNamespace(actor="fixture", health_timeout=30)
    obj.phase = lambda _: None
    obj.base_compose = ["simulated-compose"]
    trace = []
    obj._try_emergency_kill = lambda: trace.append("kill") or True
    obj._direct_stop_automation = lambda: trace.append("stop automation")
    obj._direct_stop_shadow = lambda: trace.append("stop shadow")
    obj._automation_status = lambda: {"enabled": False, "kill_switch_engaged": True}
    conn = SimpleNamespace(rollback=lambda: None, close=lambda: None)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://unused/fixture")
    monkeypatch.setattr(feed_store, "connect", lambda *_a, **_k: conn)
    monkeypatch.setattr(behavioral_schema, "ensure_schema", lambda _: trace.append("behavioral migration"))
    monkeypatch.setattr(feed_store, "migrate_schema", lambda _: trace.append("feed migration"))
    from sentinel import deployment_fence
    monkeypatch.setattr(deployment_fence, "require",
                        lambda _: trace.append("fence") or {"status": "DURABLY_FENCED"})

    def invoke(argv, **_kwargs):
        stdout = ""
        if "-c" in argv:
            # Execute the production-generated migration program, replacing
            # only the external database operations with recording endpoints.
            with redirect_stdout(io.StringIO()) as output:
                exec(compile(argv[-1], "<deployment program>", "exec"), {})
            stdout = output.getvalue()
        elif "scripts/sentinel-base-backup.sh" in argv:
            trace.append("base backup")
            stdout = "verified_base_backup: /fixture/base\n"
        elif "scripts/sentinel-backup-status.sh" in argv:
            trace.append("backup verification")
        elif "scripts/sentinel-restore-drill.sh" in argv:
            assert "--physical-only" in argv
            trace.append("physical replay")
        else:
            assert "up" in argv and "--wait" in argv and "sentinel-postgres" in argv
            trace.append("postgres")
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    obj.runner = SimpleNamespace(run=invoke)
    obj.quiesce_backup_and_migrate()
    return trace


def _require_migration_order(trace):
    assert trace == [
        "kill", "stop automation", "stop shadow", "postgres", "fence",
        "base backup", "backup verification", "physical replay", "fence",
        "behavioral migration", "feed migration", "kill",
    ]


def test_core_autonomous_deploy_migrates_feed_only_after_quiesce_and_replay(monkeypatch):
    _require_migration_order(_migration_trace(monkeypatch))


def test_bootstrap_autonomous_deploy_cannot_skip_feed_migration(monkeypatch):
    _require_migration_order(_migration_trace(monkeypatch, bootstrap=True))
