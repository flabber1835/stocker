from __future__ import annotations

import hashlib
import inspect
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from sentinel import authority, binding, schema
from sentinel.cli import authority as authority_cli
from sentinel.cli import automation as automation_cli
from sentinel.cli import feed as feed_cli
from sentinel.paper import validation as paper_validation
from sentinel.automation import store as automation_store
import sentinel.automation_runtime as automation_runtime
from sentinel.execution.guarded import BrokerOperation, PaperPreparationGrant
from sentinel.feed import readiness
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from tests.sentinel import test_signed_authority as signed_fx


ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)


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
def behavioral(pg):
    conn = feed_store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
        cleanup = feed_store.connect(pg.sync_dsn)
        try:
            drop_public_tables(cleanup)
        finally:
            cleanup.close()


def _enable(conn):
    config = automation_runtime.config_from_env({})
    control_binding = SimpleNamespace(
        deployment_id="sentinel-a", broker="alpaca-paper",
        broker_account_id="paper-account-1", takeover_epoch=1,
        certificate_sha256="c" * 64, rollout_mode="PINNED_1_00",
        rollout_version=1, config_sha256=config.fingerprint)
    # Store wants the pydantic model, but keeping construction local makes
    # the regression independent of other test modules.
    from sentinel.automation.model import ControlBinding
    exact = ControlBinding(**control_binding.__dict__)
    automation_store.activate(
        conn, binding=exact, actor="operator", reason="regression")
    automation_store.release_kill(
        conn, expected_binding=exact, actor="operator", reason="regression")
    return automation_store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)


def test_148_readiness_session_scan_is_bounded_and_visibility_preserved():
    source = inspect.getsource(readiness._impl.check_readiness)
    assert "SELECT COUNT(DISTINCT session)" not in source
    assert "session >= %s" in source
    assert "_VISIBLE_BARS" in source
    assert source.count("SELECT DISTINCT session FROM sentinel_bars b") == 1


def test_148_preparation_guard_rechecks_boundary_without_full_readiness(monkeypatch):
    grant = PaperPreparationGrant(
        expected_account="paper-account-1",
        decision_session=date(2026, 8, 14))
    fake_binding = SimpleNamespace(
        broker_account_id="paper-account-1", takeover_epoch=1,
        identity=SimpleNamespace(matches_account=lambda _value: True))
    monkeypatch.setattr("sentinel.handover.assert_no_legacy_path",
                        lambda _conn: fake_binding)
    monkeypatch.setattr(paper_validation, "load_rollout_state", lambda _conn: object())
    monkeypatch.setattr(paper_validation.publication, "require_current",
                        lambda _conn: object())
    monkeypatch.setattr(paper_validation.feed_store, "latest_visible_session",
                        lambda _conn: "2026-08-14")
    monkeypatch.setattr(paper_validation.calendar, "latest_closed_session",
                        lambda _now: "2026-08-14")
    monkeypatch.setattr(
        paper_validation, "_readiness_or_refuse",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("preparation guard rescanned readiness")))
    paper_validation._validate_broker_grant(
        object(), grant, BrokerOperation.ACCOUNT_SNAPSHOT, None,
        now_provider=lambda: datetime(
            2026, 8, 14, 17, tzinfo=timezone.utc),
        strategy_provider=lambda: {})


def test_149_emergency_cli_does_not_enter_schema_preflight(monkeypatch, capsys):
    fake_conn = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(feed_store, "connect", lambda _dsn: fake_conn)
    monkeypatch.setattr(
        schema, "ensure_schema",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("emergency kill entered schema migration")))
    monkeypatch.setattr(
        schema, "require_runtime_schema",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("emergency kill entered schema validation")))
    killed = SimpleNamespace(
        enabled=True, kill_switch_engaged=True, generation=9)
    monkeypatch.setattr(automation_store, "engage_kill",
                        lambda _conn, **_kw: killed)
    config = SimpleNamespace(database_url="postgresql://fixture")
    args = SimpleNamespace(
        command="engage-paper-automation-kill-switch",
        actor="operator", reason="emergency")
    assert automation_cli._remove_automation_authority(
        config, args) == automation_cli.EXIT_OK
    assert '"kill_switch_engaged": true' in capsys.readouterr().out


def test_149_host_emergency_path_needs_no_backup_or_authorized_environment(
        tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    argv_file = tmp_path / "docker-argv"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$DOCKER_ARGV_FILE\"\n")
    docker.chmod(0o755)
    env = os.environ.copy()
    for name in (
            "SENTINEL_BACKUP_DIR", "SENTINEL_GIT_COMMIT",
            "SENTINEL_RUNTIME_IMAGE_DIGEST", "SENTINEL_TEST_IMAGE_DIGEST",
            "SENTINEL_AUTHORITY_ARTIFACTS_DIR", "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY", "SENTINEL_AUTHORIZED_RUNTIME"):
        env.pop(name, None)
    env.update({
        "PATH": f"{fakebin}:{env['PATH']}",
        "DOCKER_ARGV_FILE": str(argv_file),
        "SENTINEL_POSTGRES_PASSWORD": "fixture-only",
        "SENTINEL_FORCE_CPU_LIMITS": "1",
    })
    subprocess.run(
        ["bash", str(REPO / "scripts/sentinel-emergency-kill.sh"),
         "--actor", "operator", "--reason", "emergency"],
        cwd=REPO, env=env, check=True)
    argv = argv_file.read_text().splitlines()
    joined = " ".join(argv)
    assert "docker-compose.sentinel-backup.yml" not in joined
    assert "docker-compose.sentinel-automation.yml" not in joined
    assert "--no-deps" in argv
    assert "sentinel" in argv
    assert "engage-paper-automation-kill-switch" in argv


def test_150_require_leader_leaves_backend_idle_not_idle_in_transaction(
        behavioral, pg):
    permit = _enable(behavioral)
    with behavioral.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        pid = int(cur.fetchone()[0])
    behavioral.rollback()

    automation_store.require_leader(behavioral, permit)

    observer = feed_store.connect(pg.sync_dsn)
    try:
        with observer.cursor() as cur:
            cur.execute("SELECT state FROM pg_stat_activity WHERE pid=%s", (pid,))
            assert cur.fetchone()[0] == "idle"
    finally:
        observer.rollback()
        observer.close()


def test_150_runtime_schema_is_read_only_and_does_not_repair(behavioral):
    schema.require_runtime_schema(behavioral)
    with behavioral.cursor() as cur:
        cur.execute(
            "ALTER TABLE sentinel_automation_control "
            "DROP COLUMN authority_detail")
    behavioral.commit()

    with pytest.raises(schema.SchemaMigrationRefused, match="missing migration columns"):
        schema.require_runtime_schema(behavioral)
    with behavioral.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' "
            "AND table_name='sentinel_automation_control' "
            "AND column_name='authority_detail'")
        assert cur.fetchone() is None
    behavioral.rollback()


def test_150_runtime_validation_coexists_with_idle_reader(behavioral, pg):
    blocker = feed_store.connect(pg.sync_dsn)
    runtime = feed_store.connect(pg.sync_dsn)
    try:
        with blocker.cursor() as cur:
            cur.execute("SELECT * FROM sentinel_automation_control WHERE id=1")
            cur.fetchone()
        # Keep blocker intentionally idle in transaction. Runtime validation
        # uses only compatible reads, so it must not introduce queued DDL.
        schema.require_runtime_schema(runtime)
    finally:
        blocker.rollback()
        blocker.close()
        runtime.rollback()
        runtime.close()


def test_150_explicit_schema_ddl_has_bounded_lock_wait(behavioral, pg):
    blocker = feed_store.connect(pg.sync_dsn)
    migrator = feed_store.connect(pg.sync_dsn)
    try:
        with blocker.cursor() as cur:
            cur.execute("SELECT * FROM sentinel_automation_control WHERE id=1")
            cur.fetchone()
        with pytest.raises(Exception, match="lock timeout"):
            schema.ensure_schema(migrator)
    finally:
        blocker.rollback()
        blocker.close()
        migrator.rollback()
        migrator.close()


def test_150_automation_composition_uses_read_only_runtime_schema_gate():
    source = inspect.getsource(automation_runtime.ProductionAutomation)
    assert "schema.ensure_schema(conn)" not in source
    assert source.count("schema.require_runtime_schema(conn)") >= 4
    cli_source = inspect.getsource(automation_cli._automation_run)
    assert "schema.require_runtime_schema(conn)" in cli_source
    assert "schema.ensure_schema(conn)" not in cli_source


@pytest.fixture()
def signed_conn(pg):
    conn = feed_store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    binding.bind(
        conn, deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
        cleanup = feed_store.connect(pg.sync_dsn)
        try:
            drop_public_tables(cleanup)
        finally:
            cleanup.close()


def test_137_future_certificate_stages_before_not_before_but_activation_waits(
        signed_conn):
    document = signed_fx.claims(
        not_before="2026-08-14T00:00:00Z",
        expires_at="2026-08-20T00:00:00Z")
    payload = signed_fx.signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    installed = authority.install_signed_certificate(
        signed_conn, certificate_bytes=payload, confirm_sha256=digest,
        context=signed_fx.context(document), now=signed_fx.NOW,
        trust_roots=signed_fx.ROOTS)
    assert installed.status == "STAGED"

    with pytest.raises(authority.AuthorityRefused, match="not yet valid"):
        authority.activate_signed_certificate(
            signed_conn, certificate_sha256=digest,
            context=signed_fx.context(document), reason="too early",
            now=signed_fx.NOW, trust_roots=signed_fx.ROOTS,
            confirm_controller_rollout=True)

    active = authority.activate_signed_certificate(
        signed_conn, certificate_sha256=digest,
        context=signed_fx.context(document), reason="window opened",
        now=datetime(2026, 8, 14, tzinfo=timezone.utc),
        trust_roots=signed_fx.ROOTS,
        confirm_controller_rollout=True)
    assert active.status == "ACTIVE"


def test_137_candidate_cli_captures_lifecycle_reference_before_warmup(
        monkeypatch, tmp_path):
    events = []
    reference = datetime(2026, 8, 16, 20, 42, tzinfo=timezone.utc)

    class Clock:
        @classmethod
        def now(cls, _tz=None):
            events.append("clock")
            return reference

    class Conn:
        def close(self):
            events.append("close")

    monkeypatch.setattr(authority_cli, "datetime", Clock)
    monkeypatch.setattr(feed_store, "connect", lambda _dsn: Conn())
    monkeypatch.setattr(schema, "require_runtime_schema",
                        lambda _conn: events.append("schema"))
    monkeypatch.setattr(feed_cli, "_closed_preview_frontier",
                        lambda _conn: (SimpleNamespace(ready=True), "2026-08-14"))
    monkeypatch.setattr(authority_cli, "_current_system_identities",
                        lambda: ({"runtime": 1}, {"strategy": 1}))
    monkeypatch.setattr(
        automation_runtime, "config_from_env",
        lambda: SimpleNamespace(fingerprint="a" * 64))

    import sentinel.observation_authority as observation
    monkeypatch.setattr(
        observation, "current_warmup_evidence",
        lambda _conn, starting_cash: events.append("warmup") or {"ok": True})

    def candidate(_conn, **kwargs):
        events.append("candidate")
        assert kwargs["now"] == reference
        assert kwargs["not_before"] == reference
        return {"schema": "fixture", "claims": {}, "retained_evidence": {}}

    monkeypatch.setattr(observation, "build_candidate", candidate)
    args = SimpleNamespace(
        certificate_id="cert-1", issuer_generation=1,
        deployment_id="nas-01", expect_account="paper-123",
        not_before="2026-08-16T20:42:00Z", expires_at=None,
        maximum_exposure="1", cash=100000.0,
        reviewer="reviewer", ticket="ticket")
    config = SimpleNamespace(database_url="postgresql://fixture")
    assert authority_cli.cmd_create_paper_observation_candidate(
        config, args) == authority_cli.EXIT_OK
    assert events.index("clock") < events.index("warmup")
    assert events.index("warmup") < events.index("candidate")
