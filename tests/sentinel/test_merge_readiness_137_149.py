from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sentinel import schema
from sentinel.cli import authority as authority_cli
from sentinel.cli import feed as feed_cli
from sentinel.automation import store as automation_store
from sentinel.automation.model import AutomationConfig, ControlBinding
import sentinel.automation_runtime as automation_runtime
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "repo"


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


def test_137_candidate_survives_more_than_five_minutes_of_build_time(
        monkeypatch):
    """Model a ten-minute warmup without sleeping in CI.

    The command-start lifecycle reference must remain authoritative after the
    simulated build delay; a second wall-clock read would recreate #137.
    """
    reference = datetime(2026, 8, 16, 20, 42, tzinfo=timezone.utc)
    wall = [reference]
    clock_reads = []

    class Clock:
        @classmethod
        def now(cls, _tz=None):
            clock_reads.append(wall[0])
            return wall[0]

    class Conn:
        def close(self):
            return None

    monkeypatch.setattr(authority_cli, "datetime", Clock)
    monkeypatch.setattr(feed_store, "connect", lambda _dsn: Conn())
    monkeypatch.setattr(schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(
        feed_cli, "_closed_preview_frontier",
        lambda _conn: (SimpleNamespace(ready=True), "2026-08-14"))
    monkeypatch.setattr(
        authority_cli, "_current_system_identities",
        lambda: ({"runtime": 1}, {"strategy": 1}))
    monkeypatch.setattr(
        automation_runtime, "config_from_env",
        lambda: SimpleNamespace(fingerprint="a" * 64))

    import sentinel.observation_authority as observation

    def delayed_warmup(_conn, starting_cash):
        del starting_cash
        wall[0] = reference + timedelta(minutes=10)
        return {"ok": True}

    monkeypatch.setattr(
        observation, "current_warmup_evidence", delayed_warmup)

    def candidate(_conn, **kwargs):
        assert wall[0] == reference + timedelta(minutes=10)
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
    assert clock_reads == [reference]


def test_149_emergency_wrapper_reaches_postgres_and_fences_live_lease(
        pg, tmp_path):
    """Exercise host wrapper -> CLI -> real PostgreSQL with unrelated env absent."""
    conn = feed_store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    cfg = AutomationConfig()
    control_binding = ControlBinding(
        deployment_id="sentinel-a",
        broker="alpaca-paper",
        broker_account_id="paper-account-1",
        takeover_epoch=1,
        certificate_sha256="c" * 64,
        rollout_mode="PINNED_1_00",
        rollout_version=1,
        config_sha256=cfg.fingerprint,
    )
    automation_store.activate(
        conn, binding=control_binding, actor="operator", reason="regression")
    released = automation_store.release_kill(
        conn, expected_binding=control_binding,
        actor="operator", reason="regression")
    automation_store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    conn.commit()

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "exec \"$SENTINEL_TEST_PYTHON\" -m sentinel "
        "engage-paper-automation-kill-switch "
        "--actor operator --reason emergency\n")
    docker.chmod(0o755)

    env = os.environ.copy()
    for name in (
            "SENTINEL_BACKUP_DIR", "SENTINEL_GIT_COMMIT",
            "SENTINEL_RUNTIME_IMAGE_DIGEST", "SENTINEL_TEST_IMAGE_DIGEST",
            "SENTINEL_AUTHORITY_ARTIFACTS_DIR", "SENTINEL_POSTGRES_PASSWORD",
            "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
            "SENTINEL_AUTHORIZED_RUNTIME"):
        env.pop(name, None)
    env.update({
        "PATH": f"{fakebin}:{env['PATH']}",
        "SENTINEL_TEST_PYTHON": sys.executable,
        "SENTINEL_HOST_PYTHON": sys.executable,
        "SENTINEL_DATABASE_URL": pg.sync_dsn,
        "SENTINEL_FORCE_CPU_LIMITS": "1",
    })

    try:
        result = subprocess.run(
            ["bash", str(REPO / "scripts/sentinel-emergency-kill.sh"),
             "--actor", "operator", "--reason", "emergency"],
            cwd=REPO, env=env, check=True, text=True,
            capture_output=True)
        assert '"kill_switch_engaged": true' in result.stdout

        conn.rollback()
        fenced = automation_store.load_control(conn)
        assert fenced.kill_switch_engaged is True
        assert fenced.generation == released.generation + 1
        with conn.cursor() as cur:
            cur.execute(
                "SELECT holder_id,control_generation,expires_at "
                "FROM sentinel_automation_lease WHERE id=1")
            assert cur.fetchone() == (None, None, None)
            cur.execute(
                "SELECT action FROM sentinel_automation_events "
                "ORDER BY seq DESC LIMIT 1")
            assert cur.fetchone()[0] == "KILL_ENGAGED"
    finally:
        conn.rollback()
        conn.close()
        cleanup = feed_store.connect(pg.sync_dsn)
        try:
            drop_public_tables(cleanup)
        finally:
            cleanup.close()
