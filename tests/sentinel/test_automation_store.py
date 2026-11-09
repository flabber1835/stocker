from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import threading

import pytest

from sentinel import schema
from sentinel.automation import schedule, store
from sentinel.automation.health import read_health
from sentinel.automation.model import (
    AutomationConfig,
    AutomationRefused,
    ControlBinding,
    CycleSpec,
    CycleState,
    InvalidCycleTransition,
    MissingAutomationState,
    StaleLeaderRefused,
)
from sentinel.feed import store as feed_store
from sentinel.execution.journal import WRITER_LOCK_KEY, WriterLockUnavailable
from tests.support.postgres import _EphemeralPostgres


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
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def identity(config: AutomationConfig | None = None) -> ControlBinding:
    cfg = config or AutomationConfig()
    return ControlBinding(
        deployment_id="sentinel-a",
        broker="alpaca-paper",
        broker_account_id="paper-account-1",
        takeover_epoch=1,
        certificate_sha256="c" * 64,
        rollout_mode="PINNED_1_00",
        rollout_version=1,
        config_sha256=cfg.fingerprint,
    )


def enable(conn, config: AutomationConfig | None = None):
    binding = identity(config)
    activated = store.activate(
        conn, binding=binding, actor="operator", reason="test activation")
    assert activated.enabled and activated.kill_switch_engaged
    released = store.release_kill(
        conn, expected_binding=binding, actor="operator",
        reason="test unattended authority")
    assert released.enabled and not released.kill_switch_engaged
    return released


def cycle_spec(control, config: AutomationConfig, session="2026-08-12"):
    timing = schedule.for_decision_session(session, config)
    binding = control.binding
    assert binding is not None
    return CycleSpec(
        decision_session=timing.decision_session,
        effective_session=timing.effective_session,
        deployment_id=binding.deployment_id,
        broker=binding.broker,
        broker_account_id=binding.broker_account_id,
        takeover_epoch=binding.takeover_epoch,
        control_generation=control.generation,
        certificate_sha256=binding.certificate_sha256,
        rollout_mode=binding.rollout_mode,
        rollout_version=binding.rollout_version,
        config_sha256=binding.config_sha256,
        decision_close_at=timing.decision_close_at,
        prepare_at=timing.prepare_at,
        execution_open_at=timing.execution_open_at,
        execute_at=timing.execute_at,
        execution_close_at=timing.execution_close_at,
    )


def historical_spec(control, config, session):
    return cycle_spec(control, config, session).model_copy(
        update={"historical_state_only": True})


def test_fresh_schema_is_disabled_killed_and_unleased(conn) -> None:
    control = store.load_control(conn)

    assert control.enabled is False
    assert control.kill_switch_engaged is True
    assert control.generation == 1
    assert control.binding is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT holder_id,fence_token,expires_at"
            " FROM sentinel_automation_lease WHERE id=1")
        assert cur.fetchone() == (None, 0, None)
    health = read_health(conn)
    assert health.healthy and health.policy_state == "DISABLED"
    assert health.operational_ready is False


def test_health_never_reports_revoked_cached_authority_as_ready(conn) -> None:
    control = enable(conn, AutomationConfig())
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    digest = control.certificate_sha256
    assert digest is not None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_signed_execution_certificates"
            " (certificate_sha256,certificate_id,key_id,envelope_bytes,"
            "  envelope,claims,issuer_generation,not_before,expires_at)"
            " VALUES (%s,'cert-health','key-health',%s,'{}'::jsonb,"
            "  '{}'::jsonb,1,NOW()-INTERVAL '1 day',NOW()+INTERVAL '1 day')",
            (digest, b"test-certificate-bytes"))
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_lifecycle"
            " (certificate_sha256,status,activated_at)"
            " VALUES (%s,'ACTIVE',NOW())", (digest,))
        cur.execute(
            "INSERT INTO sentinel_execution_authority_state"
            " (id,generation,highest_issuer_generation,"
            "  active_certificate_sha256) VALUES (1,1,1,%s)", (digest,))
    conn.commit()
    store.record_authority_verdict(
        conn, verdict="PASS", detail="fresh signature check",
        holder_id=permit.holder_id, fence_token=permit.fence_token,
        control_generation=permit.control_generation)
    store.register_instance(
        conn, instance_id=permit.holder_id, state="WAITING", next_wake_at=None)

    ready = read_health(conn)
    assert ready.authority_lifecycle_current is True
    assert ready.service_heartbeat_fresh is True
    assert ready.operational_ready is True

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_revocations"
            " (certificate_sha256,reason) VALUES (%s,'test revocation')",
            (digest,))
        cur.execute(
            "UPDATE sentinel_execution_certificate_lifecycle"
            " SET status='REVOKED',revoked_at=NOW(),"
            " revocation_reason='test revocation'"
            " WHERE certificate_sha256=%s", (digest,))
    conn.commit()

    refused = read_health(conn)
    assert refused.authority_verdict == "PASS"  # retained audit fact only
    assert refused.authority_lifecycle_current is False
    assert refused.policy_state == "AUTHORITY_INVALID"
    assert refused.operational_ready is False


def test_schema_check_never_repairs_a_deleted_control_singleton(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_automation_control WHERE id=1")
    conn.commit()

    schema.ensure_schema(conn)

    with pytest.raises(MissingAutomationState, match="control is missing"):
        store.load_control(conn)


def test_concurrent_first_schema_seeds_one_inert_control_and_lease(conn, pg) -> None:
    with conn.cursor() as cur:
        # First installation starts with no durable schema. Removing only
        # automation tables from a ledgered catalog instead models corruption.
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    conn.commit()
    start = threading.Barrier(2)

    def initialize():
        worker = feed_store.connect(pg.sync_dsn)
        try:
            start.wait(timeout=10)
            schema.ensure_schema(worker)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initialize) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)

    assert store.load_control(conn).model_dump(exclude={"updated_at"}) == {
        "enabled": False,
        "generation": 1,
        "kill_switch_engaged": True,
        "deployment_id": None,
        "broker": None,
        "broker_account_id": None,
        "takeover_epoch": None,
        "certificate_sha256": None,
        "rollout_mode": None,
        "rollout_version": None,
        "config_sha256": None,
        "authority_verdict": None,
        "authority_detail": None,
        "authority_checked_at": None,
        "enabled_at": None,
        "disabled_at": None,
    }
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*),MAX(fence_token) FROM sentinel_automation_lease")
        assert cur.fetchone() == (1, 0)


def test_disabled_and_killed_states_refuse_leadership(conn) -> None:
    with pytest.raises(AutomationRefused, match="disabled"):
        store.acquire_lease(conn, holder_id="worker-a", lease_seconds=30)

    binding = identity()
    store.activate(
        conn, binding=binding, actor="operator", reason="enable, keep killed")
    with pytest.raises(AutomationRefused, match="kill switch"):
        store.acquire_lease(conn, holder_id="worker-a", lease_seconds=30)


def test_kill_release_is_one_exact_identity_confirmed_boundary(conn) -> None:
    expected = identity()
    store.activate(
        conn, binding=expected, actor="operator", reason="test activation")
    released = store.release_kill(
        conn, expected_binding=expected, actor="operator", reason="confirmed")

    with pytest.raises(AutomationRefused, match="already released"):
        store.release_kill(
            conn, expected_binding=expected, actor="operator",
            reason="duplicate confirmation")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_automation_events ORDER BY seq")
        assert [row[0] for row in cur.fetchall()] == [
            "ACTIVATED", "KILL_RELEASED"]
    assert store.load_control(conn).generation == released.generation


def test_postgres_time_lease_takeover_fences_the_old_worker(conn, pg) -> None:
    config = AutomationConfig()
    control = enable(conn, config)
    first = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)

    competitor = feed_store.connect(pg.sync_dsn)
    try:
        with pytest.raises(AutomationRefused, match="held by"):
            store.acquire_lease(
                competitor, holder_id="worker-b", lease_seconds=30)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_lease"
                " SET expires_at=clock_timestamp()-INTERVAL '1 second'"
                " WHERE id=1")
        conn.commit()
        second = store.acquire_lease(
            competitor, holder_id="worker-b", lease_seconds=30)
        assert second.fence_token == first.fence_token + 1
        assert second.control_generation == control.generation
        with pytest.raises(StaleLeaderRefused):
            store.heartbeat_lease(
                conn, permit=first, lease_seconds=30)
        renewed = store.heartbeat_lease(
            competitor, permit=second, lease_seconds=30)
        assert renewed.expires_at > second.expires_at
    finally:
        competitor.close()


def test_concurrent_leader_acquisition_has_exactly_one_winner(conn, pg) -> None:
    enable(conn, AutomationConfig())
    start = threading.Barrier(2)

    def acquire(holder):
        worker = feed_store.connect(pg.sync_dsn)
        try:
            start.wait(timeout=10)
            try:
                return store.acquire_lease(
                    worker, holder_id=holder, lease_seconds=30)
            except (AutomationRefused, WriterLockUnavailable):
                return None
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in [
                pool.submit(acquire, "worker-a"),
                pool.submit(acquire, "worker-b"),
            ]
        ]
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].fence_token == 1


def test_lease_takeover_refuses_while_execution_writer_lock_is_held(
        conn, pg) -> None:
    config = AutomationConfig()
    enable(conn, config)
    manual_writer = feed_store.connect(pg.sync_dsn)
    try:
        with manual_writer.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (WRITER_LOCK_KEY,))
        manual_writer.commit()
        with pytest.raises(WriterLockUnavailable):
            store.acquire_lease(
                conn, holder_id="worker-a", lease_seconds=30)
    finally:
        with manual_writer.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK_KEY,))
        manual_writer.commit()
        manual_writer.close()


def test_live_owner_renews_during_writer_contention_without_takeover(conn, pg):
    """A real financial writer cannot starve the idle owner's heartbeat."""
    import time

    enable(conn, AutomationConfig())
    first = store.acquire_lease(conn, holder_id="worker-a", lease_seconds=3)
    writer = feed_store.connect(pg.sync_dsn)
    try:
        writer.execute("SELECT pg_advisory_lock(%s)", (WRITER_LOCK_KEY,))
        writer.commit()
        for _ in range(8):
            renewed = store.acquire_lease(
                conn, holder_id="worker-a", lease_seconds=3)
            assert renewed.fence_token == first.fence_token
            assert renewed.acquired_at == first.acquired_at
            assert conn.execute(
                "SELECT expires_at>clock_timestamp() "
                "FROM sentinel_automation_lease WHERE id=1").fetchone() == (True,)
            conn.rollback()
            time.sleep(.5)
        with pytest.raises(WriterLockUnavailable):
            store.acquire_lease(conn, holder_id="competitor", lease_seconds=3)
        conn.rollback()
        conn.execute("UPDATE sentinel_automation_lease SET "
                     "expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=1")
        conn.commit()
        with pytest.raises(WriterLockUnavailable):
            store.acquire_lease(conn, holder_id="worker-a", lease_seconds=3)
    finally:
        writer.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK_KEY,))
        writer.commit()
        writer.close()
    fresh = store.acquire_lease(conn, holder_id="worker-a", lease_seconds=3)
    assert fresh.fence_token == first.fence_token + 1


def test_restoring_writer_coupled_renewal_is_detected(conn, pg, monkeypatch):
    import inspect
    import textwrap
    body = textwrap.dedent(inspect.getsource(store.acquire_lease))
    broken = body.replace('if owned is not None:', 'if False:')
    assert broken != body
    namespace = {}
    exec(compile(broken, 'writer-coupled-renewal-falsifier', 'exec'), store.__dict__, namespace)
    monkeypatch.setattr(store, 'acquire_lease', namespace['acquire_lease'])
    with pytest.raises(WriterLockUnavailable):
        test_live_owner_renews_during_writer_contention_without_takeover(conn, pg)


@pytest.mark.parametrize('race', ['kill', 'generation', 'expiry', 'takeover'])
def test_live_renewal_race_cannot_bypass_exclusive_acquisition(conn, pg, monkeypatch, race):
    enable(conn, AutomationConfig())
    original = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    writer = feed_store.connect(pg.sync_dsn)
    writer.execute('SELECT pg_advisory_lock(%s)', (WRITER_LOCK_KEY,))
    writer.commit()
    real_heartbeat = store.heartbeat_lease
    def racing_heartbeat(connection, **kwargs):
        if race == 'kill':
            store.engage_kill(writer, actor='test', reason='renewal race')
        elif race == 'generation':
            store.engage_kill(writer, actor='test', reason='generation handoff')
            store.release_kill(writer, expected_binding=identity(AutomationConfig()),
                               actor='test', reason='reviewed new generation')
        elif race == 'expiry':
            writer.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=1")
            writer.commit()
        else:
            writer.execute("UPDATE sentinel_automation_lease SET holder_id='worker-b',fence_token=fence_token+1 WHERE id=1")
            writer.commit()
        return real_heartbeat(connection, **kwargs)
    monkeypatch.setattr(store, 'heartbeat_lease', racing_heartbeat)
    try:
        with pytest.raises(WriterLockUnavailable):
            store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
        with pytest.raises(StaleLeaderRefused):
            store.require_leader(conn, original)
        assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
        conn.rollback()
    finally:
        writer.execute('SELECT pg_advisory_unlock(%s)', (WRITER_LOCK_KEY,))
        writer.commit()
        writer.close()


def test_emergency_kill_succeeds_while_execution_writer_lock_is_held(
        conn, pg) -> None:
    config = AutomationConfig()
    control = enable(conn, config)
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    manual_writer = feed_store.connect(pg.sync_dsn)
    try:
        with manual_writer.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (WRITER_LOCK_KEY,))
        manual_writer.commit()

        killed = store.engage_kill(
            conn, actor="operator", reason="emergency fence")

        assert killed.kill_switch_engaged is True
        assert killed.generation == control.generation + 1
        with pytest.raises(StaleLeaderRefused):
            store.require_leader(conn, permit)
    finally:
        with manual_writer.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK_KEY,))
        manual_writer.commit()
        manual_writer.close()


def test_cycle_identity_events_and_stale_fence_are_durable(conn, pg) -> None:
    config = AutomationConfig(
        publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, config)
    first = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    spec = cycle_spec(control, config)
    created = store.create_cycle(conn, permit=first, spec=spec)
    restarted = store.create_cycle(conn, permit=first, spec=spec)
    assert restarted == created

    prepared = store.transition_cycle(
        conn, permit=first, cycle_id=created.cycle_id,
        to_state=CycleState.PREPARING, increment_attempt=True)
    assert prepared.attempt_count == 1

    competitor = feed_store.connect(pg.sync_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_lease"
                " SET expires_at=clock_timestamp()-INTERVAL '1 second'"
                " WHERE id=1")
        conn.commit()
        second = store.acquire_lease(
            competitor, holder_id="worker-b", lease_seconds=30)
        with pytest.raises(StaleLeaderRefused):
            store.transition_cycle(
                conn, permit=first, cycle_id=created.cycle_id,
                to_state=CycleState.PLAN_READY, plan_id="old-worker-plan")
        ready = store.transition_cycle(
            competitor, permit=second, cycle_id=created.cycle_id,
            to_state=CycleState.PLAN_READY, plan_id="current-plan")
        assert ready.plan_id == "current-plan"
        with competitor.cursor() as cur:
            cur.execute(
                "SELECT from_state,to_state,fence_token"
                " FROM sentinel_automation_cycle_events"
                " WHERE cycle_id=%s ORDER BY seq", (created.cycle_id,))
            events = cur.fetchall()
        assert [event[:2] for event in events] == [
            (None, "DISCOVERED"),
            ("DISCOVERED", "PREPARING"),
            ("PREPARING", "PLAN_READY"),
        ]
        assert events[-1][2] == second.fence_token
    finally:
        competitor.close()


def test_kill_generation_immediately_invalidates_old_permit(conn) -> None:
    config = AutomationConfig()
    enable(conn, config)
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)

    killed = store.engage_kill(
        conn, actor="operator", reason="test emergency brake")

    assert killed.kill_switch_engaged
    assert killed.generation == permit.control_generation + 1
    with pytest.raises(StaleLeaderRefused):
        store.require_leader(conn, permit)
    with pytest.raises(AutomationRefused, match="already engaged"):
        store.engage_kill(
            conn, actor="operator", reason="duplicate emergency request")
    assert store.load_control(conn).generation == killed.generation


def test_config_mismatch_atomically_kills_clears_authority_and_fences_leader(
        conn) -> None:
    configured = AutomationConfig()
    enable(conn, configured)
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    store.record_authority_verdict(
        conn, verdict="PASS", detail="current certificate verified",
        holder_id=permit.holder_id, fence_token=permit.fence_token,
        control_generation=permit.control_generation)
    changed = configured.model_copy(update={"retry_base_seconds": 7})

    killed = store.engage_config_mismatch_kill(
        conn, expected_generation=permit.control_generation,
        expected_config_sha256=configured.fingerprint,
        actual_config_sha256=changed.fingerprint)

    assert killed.generation == permit.control_generation + 1
    assert killed.enabled is True
    assert killed.kill_switch_engaged is True
    assert killed.authority_verdict is None
    assert killed.authority_detail is None
    assert killed.authority_checked_at is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT holder_id,control_generation,expires_at"
            " FROM sentinel_automation_lease WHERE id=1")
        assert cur.fetchone() == (None, None, None)
        cur.execute(
            "SELECT action,actor,detail FROM sentinel_automation_events"
            " ORDER BY seq DESC LIMIT 1")
        action, actor, detail = cur.fetchone()
    assert (action, actor) == ("KILL_ENGAGED", "sentinel-automation")
    assert detail == {
        "activated_config_sha256": configured.fingerprint,
        "observed_config_sha256": changed.fingerprint,
        "originating_generation": permit.control_generation,
    }
    with pytest.raises(StaleLeaderRefused):
        store.require_leader(conn, permit)
    with pytest.raises(StaleLeaderRefused):
        store.engage_config_mismatch_kill(
            conn, expected_generation=permit.control_generation,
            expected_config_sha256=configured.fingerprint,
            actual_config_sha256=changed.fingerprint)


def test_authority_verdict_is_fenced_and_cleared_on_generation_change(
        conn, pg) -> None:
    enable(conn, AutomationConfig())
    first = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    store.record_authority_verdict(
        conn, verdict="PASS", detail="current certificate verified",
        holder_id=first.holder_id, fence_token=first.fence_token,
        control_generation=first.control_generation)
    assert store.load_control(conn).authority_verdict == "PASS"

    competitor = feed_store.connect(pg.sync_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_lease SET"
                " expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=1")
        conn.commit()
        second = store.acquire_lease(
            competitor, holder_id="worker-b", lease_seconds=30)
        with pytest.raises(StaleLeaderRefused):
            store.record_authority_verdict(
                conn, verdict="FAIL", detail="stale worker result",
                holder_id=first.holder_id, fence_token=first.fence_token,
                control_generation=first.control_generation)
        assert store.load_control(competitor).authority_verdict == "PASS"
        killed = store.engage_kill(
            competitor, actor="operator", reason="invalidate authority")
        assert killed.authority_verdict is None
        assert killed.authority_checked_at is None
        with pytest.raises(StaleLeaderRefused):
            store.record_authority_verdict(
                conn, verdict="PASS", detail="late pass",
                holder_id=second.holder_id, fence_token=second.fence_token,
                control_generation=second.control_generation)
    finally:
        competitor.close()


def test_historical_cycles_can_only_become_state_only_audit(conn) -> None:
    config = AutomationConfig(
        publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, config)
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    records = store.ensure_historical_cycles(
        conn, permit=permit, specs=(
            historical_spec(control, config, "2026-08-10"),
            historical_spec(control, config, "2026-08-11"),
        ))

    assert [record.decision_session for record in records] == [
        date(2026, 8, 10), date(2026, 8, 11)]
    with pytest.raises(Exception, match="historical state-only"):
        store.transition_cycle(
            conn, permit=permit, cycle_id=records[0].cycle_id,
            to_state=CycleState.PREPARING)
    missed = store.mark_historical_missed(
        conn, permit=permit, before_session=date(2026, 8, 12))
    assert all(record.state is CycleState.MISSED_STATE_ONLY for record in missed)
    assert store.latest_cycle(conn) is None
    assert store.latest_cycle(conn, include_historical=True).decision_session == date(
        2026, 8, 11)


def test_terminal_daily_cycle_satisfies_later_canonical_catchup_audit(conn) -> None:
    config = AutomationConfig(
        publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, config)
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    ordinary = store.create_cycle(
        conn, permit=permit,
        spec=cycle_spec(control, config, "2026-08-10"))
    terminal = store.transition_cycle(
        conn, permit=permit, cycle_id=ordinary.cycle_id,
        to_state=CycleState.SUPERSEDED,
        failure_code="MISSED_EXECUTION_WINDOW")

    records = store.ensure_historical_cycles(
        conn, permit=permit, specs=(
            historical_spec(control, config, "2026-08-10"),))

    assert records == (terminal,)
    assert records[0].historical_state_only is False
    assert store.mark_historical_missed(
        conn, permit=permit,
        before_session=date(2026, 8, 12)) == ()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_automation_cycles"
            " WHERE decision_session='2026-08-10'")
        assert cur.fetchone()[0] == 1


def test_nonterminal_daily_cycle_cannot_be_recast_as_historical(conn) -> None:
    config = AutomationConfig(
        publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, config)
    permit = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    store.create_cycle(
        conn, permit=permit,
        spec=cycle_spec(control, config, "2026-08-10"))

    with pytest.raises(Exception, match="not safely terminal"):
        store.ensure_historical_cycles(
            conn, permit=permit, specs=(
                historical_spec(control, config, "2026-08-10"),))


def test_cross_generation_adoption_preserves_cycle_identity_and_audits_fence(
        conn) -> None:
    config = AutomationConfig(
        publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, config)
    first = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    created = store.create_cycle(
        conn, permit=first, spec=cycle_spec(control, config))
    preparing = store.transition_cycle(
        conn, permit=first, cycle_id=created.cycle_id,
        to_state=CycleState.PREPARING)
    store.engage_kill(conn, actor="operator", reason="generation boundary")
    expected = store.load_control(conn).binding
    assert expected is not None
    current = store.release_kill(
        conn, expected_binding=expected, actor="operator",
        reason="generation adoption")
    second = store.acquire_lease(
        conn, holder_id="worker-b", lease_seconds=30)

    adopted = store.adopt_cycle(
        conn, permit=second, cycle_id=preparing.cycle_id,
        to_state=CycleState.SUPERSEDED,
        failure_code="CONTROL_GENERATION_SUPERSEDED")
    assert adopted.cycle_id == preparing.cycle_id
    assert adopted.control_generation == preparing.control_generation
    assert adopted.state is CycleState.SUPERSEDED
    assert adopted.last_fence_token == second.fence_token
    assert second.control_generation == current.generation
    with conn.cursor() as cur:
        cur.execute(
            "SELECT control_generation,fence_token,detail"
            " FROM sentinel_automation_cycle_events WHERE cycle_id=%s"
            " ORDER BY seq DESC LIMIT 1", (created.cycle_id,))
        generation, fence, detail = cur.fetchone()
    assert generation == second.control_generation
    assert fence == second.fence_token
    assert detail["adoption"] is True
    assert detail["originating_control_generation"] == first.control_generation


def test_adoption_never_moves_pretransport_cycle_to_executable_state(conn) -> None:
    config = AutomationConfig(
        publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, config)
    first = store.acquire_lease(
        conn, holder_id="worker-a", lease_seconds=30)
    created = store.create_cycle(
        conn, permit=first, spec=cycle_spec(control, config))
    store.engage_kill(conn, actor="operator", reason="generation boundary")
    expected = store.load_control(conn).binding
    assert expected is not None
    store.release_kill(
        conn, expected_binding=expected, actor="operator",
        reason="generation adoption")
    second = store.acquire_lease(
        conn, holder_id="worker-b", lease_seconds=30)

    with pytest.raises(InvalidCycleTransition, match="adoption cannot move"):
        store.adopt_cycle(
            conn, permit=second, cycle_id=created.cycle_id,
            to_state=CycleState.EXECUTING)


class _PulseReadConnection:
    """Interleave a real committed foreground pulse with earlier health work."""
    def __init__(self, connection, after_history):
        self.connection, self.after_history = connection, after_history
        self.statements = []

    def cursor(self):
        owner = self
        cursor = self.connection.cursor()
        class Cursor:
            def __enter__(self):
                cursor.__enter__()
                return self
            def __exit__(self, *args):
                return cursor.__exit__(*args)
            def execute(self, query, params=None):
                owner.statements.append(query)
                cursor.execute(query, params)
                if 'FROM sentinel_alert_outbox a' in query and owner.after_history:
                    hook, owner.after_history = owner.after_history, None
                    hook()
                return self
            def __getattr__(self, name):
                return getattr(cursor, name)
        return Cursor()

    def __getattr__(self, name):
        return getattr(self.connection, name)


def _pulse_authority(conn):
    from tests.sentinel.test_callback_liveness import authority
    return authority(conn, AutomationConfig(lease_seconds=12, heartbeat_seconds=3))


def _assert_late_holder_read(conn, pg, permit, reader=read_health):
    store.heartbeat_lease(conn, permit=permit, lease_seconds=12, instance_state='WAITING')
    conn.execute("UPDATE sentinel_automation_service_instances SET "
                 "heartbeat_at=clock_timestamp()-INTERVAL '13 seconds' WHERE instance_id=%s",
                 (permit.holder_id,))
    conn.commit()
    def advance():
        with feed_store.connect(pg.sync_dsn) as writer:
            store.heartbeat_lease(writer, permit=permit, lease_seconds=12,
                                  instance_state='WAITING')
    observed = _PulseReadConnection(conn, advance)
    result = reader(observed)
    assert result.policy_state == 'LEADER_ACTIVE'
    assert result.service_heartbeat_fresh and result.operational_ready
    temporal = [q for q in observed.statements if 'WITH sampled AS MATERIALIZED' in q]
    assert len(temporal) == 1
    assert 'i.instance_id=l.holder_id' in temporal[0]
    assert result.scheduler_diagnostic is None


def test_health_observes_one_late_coherent_holder_pulse(conn, pg):
    _, permit = _pulse_authority(conn)
    _assert_late_holder_read(conn, pg, permit)


def test_early_temporal_read_falsifier_is_detected(conn, pg):
    import inspect
    from sentinel.automation import health
    _, permit = _pulse_authority(conn)
    _assert_late_holder_read(conn, pg, permit)
    source = inspect.getsource(health.read_health)
    history = source.index('            "SELECT COUNT(*) FROM sentinel_commands')
    history = source.rfind('        cur.execute(', 0, history)
    temporal = source.index('        # Slow integrity/history work precedes')
    end = source.index('    conn.rollback()', temporal)
    # Move the unchanged temporal query before the history work; the real
    # independently committed pulse then falls outside that saved snapshot.
    broken = source[:history]+source[temporal:end]+source[history:temporal]+source[end:]
    scope = dict(health.__dict__)
    exec(compile(broken, 'early scheduler observation falsifier', 'exec'), scope)
    with pytest.raises(AssertionError):
        _assert_late_holder_read(conn, pg, permit, scope['read_health'])


@pytest.mark.parametrize('damage,predicate,policy', [
    ('stale', 'INSTANCE_HEARTBEAT_STALE', 'SCHEDULER_STALLED'),
    ('future', 'INSTANCE_HEARTBEAT_FUTURE', 'SCHEDULER_STALLED'),
    ('missing', 'INSTANCE_MISSING', 'SCHEDULER_STALLED'),
    ('expired', 'LEASE_EXPIRED', 'WAITING_FOR_LEADER'),
])
def test_coherent_health_preserves_negative_pulses_and_safe_facts(conn, damage, predicate, policy):
    from datetime import timedelta
    from pydantic import ValidationError
    _, permit = _pulse_authority(conn)
    store.register_instance(conn, instance_id=permit.holder_id, state='WAITING')
    store.register_instance(conn, instance_id='fresh-standby', state='WAITING')
    if damage in {'stale', 'future'}:
        sign = '-' if damage == 'stale' else '+'
        conn.execute('UPDATE sentinel_automation_service_instances SET '
                     f"heartbeat_at=clock_timestamp(){sign}INTERVAL '13 seconds' "
                     'WHERE instance_id=%s', (permit.holder_id,))
    elif damage == 'missing':
        conn.execute('DELETE FROM sentinel_automation_service_instances WHERE instance_id=%s',
                     (permit.holder_id,))
    else:
        conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-INTERVAL '1 second'")
    conn.commit()
    result = read_health(conn)
    assert result.policy_state == policy and not result.operational_ready
    fact = result.scheduler_diagnostic
    assert fact.predicate == predicate and fact.holder == permit.holder_id
    assert fact.control_generation == permit.control_generation and fact.fence == permit.fence_token
    assert fact.sampled_at == result.database_now and fact.sampled_at.utcoffset() == timedelta(0)
    assert fact.lease_expires_at == result.leader_expires_at
    assert fact.instance_heartbeat_at == result.last_instance_heartbeat_at
    assert fact.heartbeat_window_seconds >= 1 and fact.read_elapsed_seconds >= 0
    assert 'fresh-standby' not in repr(fact.model_dump())
    assert len(fact.model_dump_json()) < 2048
    raw = fact.model_dump()
    for bad in (dict(raw, read_elapsed_seconds=float('nan')),
                dict(raw, heartbeat_age_seconds=float('inf')),
                dict(raw, holder='private value with spaces'),
                dict(raw, sampled_at=fact.sampled_at.replace(tzinfo=None)),
                dict(raw, extra='unbounded')):
        with pytest.raises(ValidationError):
            type(fact).model_validate(bad)


def test_late_control_change_is_not_bound_to_old_validated_lineage(conn, pg):
    _, permit = _pulse_authority(conn)
    def revoke():
        with feed_store.connect(pg.sync_dsn) as writer:
            store.engage_kill(writer, actor='operator', reason='private race')
    with pytest.raises(AutomationRefused, match='control changed'):
        read_health(_PulseReadConnection(conn, revoke))


def _pulse_pair(conn, holder):
    row = conn.execute('SELECT l.heartbeat_at,l.expires_at,i.heartbeat_at,i.state '
        'FROM sentinel_automation_lease l JOIN sentinel_automation_service_instances i '
        'ON i.instance_id=l.holder_id WHERE l.holder_id=%s', (holder,)).fetchone()
    conn.rollback()
    return row


def test_main_acquisition_and_renewal_publish_one_exact_timestamp(conn):
    from datetime import timedelta
    enable(conn)
    permit = store.acquire_lease(conn, holder_id='foreground', lease_seconds=30,
                                instance_state='WAITING')
    for operation in ('initial', 'renew', 'owned_acquire'):
        if operation == 'renew':
            permit = store.heartbeat_lease(conn, permit=permit, lease_seconds=30,
                                           instance_state='EXECUTED')
        elif operation == 'owned_acquire':
            permit = store.acquire_lease(conn, holder_id='foreground', lease_seconds=30,
                                        instance_state='WAITING')
        lease, expiry, instance, state = _pulse_pair(conn, permit.holder_id)
        assert lease == instance and expiry-lease == timedelta(seconds=30)
        assert expiry == permit.expires_at
        assert state == ('EXECUTED' if operation == 'renew' else 'WAITING')


def test_main_pulse_is_invisible_until_commit_and_rolls_back_as_one_pair(conn, pg, monkeypatch):
    enable(conn)
    permit = store.acquire_lease(conn, holder_id='foreground', lease_seconds=30,
                                instance_state='WAITING')
    before = _pulse_pair(conn, permit.holder_id)
    real = store._write_instance
    saw = []
    def fail(cur, **kwargs):
        real(cur, **kwargs)
        with feed_store.connect(pg.sync_dsn) as observer:
            saw.append(_pulse_pair(observer, permit.holder_id))
        raise RuntimeError('private failure before publication commit')
    monkeypatch.setattr(store, '_write_instance', fail)
    with pytest.raises(RuntimeError, match='before publication commit'):
        store.heartbeat_lease(conn, permit=permit, lease_seconds=30, instance_state='EXECUTED')
    assert saw == [before] and _pulse_pair(conn, permit.holder_id) == before


def test_split_timestamp_falsifier_is_detected(conn):
    import inspect
    enable(conn)
    permit = store.acquire_lease(conn, holder_id='foreground', lease_seconds=30,
                                instance_state='WAITING')
    source = inspect.getsource(store.heartbeat_lease)
    assert 'pulse=row[2]' in source
    scope = dict(store.__dict__)
    exec(compile(source.replace('pulse=row[2]', 'pulse=None'), 'split pulse falsifier', 'exec'), scope)
    scope['heartbeat_lease'](conn, permit=permit, lease_seconds=30, instance_state='WAITING')
    lease, _, instance, _ = _pulse_pair(conn, permit.holder_id)
    with pytest.raises(AssertionError):
        assert lease == instance


@pytest.mark.parametrize('callback', [False, True])
def test_row_lock_wait_cannot_resurrect_expired_pulse(conn, pg, callback):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    enable(conn)
    permit = store.acquire_lease(conn, holder_id='foreground', lease_seconds=30 if callback else 1,
                                instance_state='WAITING')
    if callback:
        store.register_instance(conn, instance_id=permit.holder_id, state='PREPARE_CALLBACK',
                                callback_deadline_seconds=1)
    before = _pulse_pair(conn, permit.holder_id)
    blocker = feed_store.connect(pg.sync_dsn)
    table = 'sentinel_automation_service_instances' if callback else 'sentinel_automation_lease'
    blocker.execute('SELECT * FROM '+table+' FOR UPDATE').fetchall()
    entered = Event()
    def renew():
        with feed_store.connect(pg.sync_dsn) as writer:
            entered.set()
            with pytest.raises(StaleLeaderRefused):
                store.heartbeat_lease(writer, permit=permit, lease_seconds=30, callback=callback,
                    **({} if callback else {'instance_state':'WAITING'}))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(renew)
            assert entered.wait(3)
            time.sleep(1.15)
            blocker.rollback()
            task.result(timeout=5)
    finally:
        blocker.close()
    assert _pulse_pair(conn, permit.holder_id) == before


def test_fresh_main_acquisition_rolls_back_lease_and_new_instance_together(conn, pg, monkeypatch):
    enable(conn)
    old = store.acquire_lease(conn, holder_id='old-foreground', lease_seconds=30,
                              instance_state='WAITING')
    conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-INTERVAL '1 second'")
    conn.commit()
    before = _pulse_pair(conn, old.holder_id)
    real = store._write_instance
    def fail(cur, **kwargs):
        real(cur, **kwargs)
        with feed_store.connect(pg.sync_dsn) as observer:
            assert _pulse_pair(observer, old.holder_id) == before
            assert observer.execute('SELECT count(*) FROM sentinel_automation_service_instances '
                "WHERE instance_id='new-foreground'").fetchone()[0] == 0
        raise RuntimeError('private fresh-acquisition publication failure')
    monkeypatch.setattr(store, '_write_instance', fail)
    with pytest.raises(RuntimeError, match='fresh-acquisition'):
        store.acquire_lease(conn, holder_id='new-foreground', lease_seconds=30,
                            instance_state='WAITING')
    assert _pulse_pair(conn, old.holder_id) == before
    assert conn.execute('SELECT count(*) FROM sentinel_automation_service_instances '
        "WHERE instance_id='new-foreground'").fetchone()[0] == 0
    conn.rollback()


def test_callback_pulse_uses_same_timestamp_without_renewing_invocation(conn):
    _, permit = _pulse_authority(conn)
    store.register_instance(conn, instance_id=permit.holder_id, state='PREPARE_CALLBACK',
                            callback_deadline_seconds=120)
    query = ('SELECT callback_started_at,callback_deadline_at '
        'FROM sentinel_automation_service_instances WHERE instance_id=%s')
    original = conn.execute(query, (permit.holder_id,)).fetchone()
    conn.rollback()
    store.heartbeat_lease(conn, permit=permit, lease_seconds=12, callback=True)
    lease, _, instance, state = _pulse_pair(conn, permit.holder_id)
    assert lease == instance and state == 'PREPARE_CALLBACK'
    assert conn.execute(query, (permit.holder_id,)).fetchone() == original
    conn.rollback()


@pytest.mark.parametrize('operation', ['acquire', 'renew', 'callback_renew'])
def test_foreground_progress_cannot_start_or_reset_callback_bounds(conn, operation):
    _, permit = _pulse_authority(conn)
    store.register_instance(conn, instance_id=permit.holder_id, state='PREPARE_CALLBACK',
                            callback_deadline_seconds=120)
    before = _pulse_pair(conn, permit.holder_id)
    with pytest.raises(ValueError, match='callback'):
        if operation == 'acquire':
            store.acquire_lease(conn, holder_id=permit.holder_id, lease_seconds=12,
                                instance_state='PREPARE_CALLBACK')
        else:
            store.heartbeat_lease(conn, permit=permit, lease_seconds=12,
                callback=operation=='callback_renew',
                instance_state='WAITING' if operation=='callback_renew' else 'PREPARE_CALLBACK')
    assert _pulse_pair(conn, permit.holder_id) == before
