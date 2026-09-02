from __future__ import annotations

import json

import pytest

from sentinel import authority, schema
from sentinel.automation import outbox, store
from sentinel.automation.model import AutomationRefused
from sentinel.feed import publication
from sentinel.feed import store as feed_store
from sentinel.execution import authority_gate
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
    feed_store.require_feed_schema(connection)
    yield connection
    connection.close()


def test_crash_after_cycle_transition_reconstructs_missing_alert(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sentinel_automation_cycles (
                cycle_id,state,decision_session,effective_session,
                deployment_id,broker,broker_account_id,takeover_epoch,
                control_generation,certificate_sha256,rollout_mode,
                rollout_version,config_sha256,decision_close_at,prepare_at,
                execution_open_at,execute_at,execution_close_at,
                last_fence_token,completed_at)
            VALUES (
                'crash-transition','BLOCKED',CURRENT_DATE-1,CURRENT_DATE,
                'deployment','alpaca','account',1,1,%s,'PINNED_1_00',1,%s,
                clock_timestamp()-INTERVAL '4 hours',
                clock_timestamp()-INTERVAL '3 hours',
                clock_timestamp()-INTERVAL '2 hours',
                clock_timestamp()-INTERVAL '1 hour',
                clock_timestamp()+INTERVAL '1 hour',1,clock_timestamp())
        """, ("a" * 64, "b" * 64))
        cur.execute("""
            INSERT INTO sentinel_automation_cycle_events
                (cycle_id,from_state,to_state,control_generation,fence_token,detail)
            VALUES ('crash-transition','DISCOVERED','BLOCKED',1,1,%s::jsonb)
        """, (json.dumps({"failure_code": "CRASH_WINDOW"}),))
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_alert_outbox")
        assert cur.fetchone()[0] == 0

    recovered = outbox.claim_next(
        conn, holder_id="restart-dispatcher", claim_seconds=30)
    assert recovered is not None
    assert recovered.event_type == "AUTOMATION_BLOCKED"
    assert recovered.payload["cycle_id"] == "crash-transition"
    assert recovered.payload["reconstructed_from_durable_event"] is True

    outbox.mark_delivered(
        conn, alert_id=recovered.alert_id, holder_id="restart-dispatcher")
    assert outbox.claim_next(
        conn, holder_id="restart-dispatcher", claim_seconds=30) is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_alert_outbox"
            " WHERE payload->>'cycle_id'='crash-transition'")
        assert cur.fetchone()[0] == 1


def test_each_same_state_transition_has_one_event_identity(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sentinel_automation_cycles (
                cycle_id,state,decision_session,effective_session,
                deployment_id,broker,broker_account_id,takeover_epoch,
                control_generation,certificate_sha256,rollout_mode,
                rollout_version,config_sha256,decision_close_at,prepare_at,
                execution_open_at,execute_at,execution_close_at,
                last_fence_token,completed_at)
            VALUES (
                'repeat-state','BLOCKED',CURRENT_DATE-1,CURRENT_DATE,
                'deployment','alpaca','account',1,1,%s,'PINNED_1_00',1,%s,
                clock_timestamp()-INTERVAL '4 hours',
                clock_timestamp()-INTERVAL '3 hours',
                clock_timestamp()-INTERVAL '2 hours',
                clock_timestamp()-INTERVAL '1 hour',
                clock_timestamp()+INTERVAL '1 hour',1,clock_timestamp())
        """, ("a" * 64, "b" * 64))
        for code in ("FIRST_BLOCK", "SECOND_BLOCK"):
            cur.execute("""
                INSERT INTO sentinel_automation_cycle_events
                    (cycle_id,from_state,to_state,control_generation,
                     fence_token,detail)
                VALUES ('repeat-state','RETRY_WAIT','BLOCKED',1,1,%s::jsonb)
            """, (json.dumps({"failure_code": code}),))
    conn.commit()

    delivered = []
    while True:
        alert = outbox.claim_next(
            conn, holder_id="event-dispatcher", claim_seconds=30)
        if alert is None:
            break
        delivered.append(alert)
        outbox.mark_delivered(
            conn, alert_id=alert.alert_id, holder_id="event-dispatcher")

    assert len(delivered) == 2
    assert len({alert.payload["cycle_event_seq"] for alert in delivered}) == 2
    assert {alert.idempotency_key for alert in delivered} == {
        f"cycle-event:{alert.payload['cycle_event_seq']}"
        for alert in delivered
    }


def test_kill_event_reconstructs_after_notifier_crash(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sentinel_automation_events
                (generation,action,actor,reason,detail)
            VALUES (2,'KILL_ENGAGED','operator','emergency stop','{}'::jsonb)
        """)
    conn.commit()

    alert = outbox.claim_next(
        conn, holder_id="kill-dispatcher", claim_seconds=30)
    assert alert is not None
    assert alert.event_type == "AUTOMATION_KILL_ENGAGED"
    assert alert.payload["generation"] == 2
    assert alert.payload["reason"] == "emergency stop"


def test_control_singleton_sql_tamper_refuses_before_lease_authority(conn) -> None:
    binding = {
        "deployment_id": "deployment",
        "broker": "alpaca",
        "broker_account_id": "account",
        "takeover_epoch": 1,
        "certificate_sha256": "a" * 64,
        "rollout_mode": "PINNED_1_00",
        "rollout_version": 1,
        "config_sha256": "b" * 64,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sentinel_automation_control
               SET enabled=TRUE,generation=2,kill_switch_engaged=TRUE,
                   deployment_id=%s,broker=%s,broker_account_id=%s,
                   takeover_epoch=%s,certificate_sha256=%s,rollout_mode=%s,
                   rollout_version=%s,config_sha256=%s,
                   enabled_at=clock_timestamp(),updated_at=clock_timestamp()
             WHERE id=1
        """, tuple(binding[key] for key in (
            "deployment_id", "broker", "broker_account_id", "takeover_epoch",
            "certificate_sha256", "rollout_mode", "rollout_version",
            "config_sha256")))
        cur.execute("""
            INSERT INTO sentinel_automation_events
                (generation,action,actor,reason,detail)
            VALUES (2,'ACTIVATED','test','valid activation',%s::jsonb)
        """, (json.dumps(binding),))
    conn.commit()

    assert store.load_control(conn).generation == 2

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_automation_control"
            " SET kill_switch_engaged=FALSE,updated_at=clock_timestamp()"
            " WHERE id=1")
    conn.commit()

    with pytest.raises(AutomationRefused, match="immutable history"):
        store.load_control(conn)
    with pytest.raises(AutomationRefused):
        store.acquire_lease(
            conn, holder_id="must-not-own-lease", lease_seconds=30)


def test_rollout_singleton_cannot_replay_historical_authority(conn) -> None:
    assert authority.load_rollout_state(conn).version == 1
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sentinel_rollout_state
               SET mode='CONTROLLER',version=2,certificate_sha256=%s,
                   updated_at=NOW() WHERE id=1
        """, ("c" * 64,))
        cur.execute("""
            INSERT INTO sentinel_rollout_events
                (version,from_mode,to_mode,certificate_sha256,reason)
            VALUES (2,'PINNED_1_00','CONTROLLER',%s,'valid transition')
        """, ("c" * 64,))
    conn.commit()

    assert authority.load_rollout_state(conn).version == 2

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sentinel_rollout_state
               SET mode='PINNED_1_00',version=1,certificate_sha256=NULL,
                   updated_at=NOW() WHERE id=1
        """)
    conn.commit()

    with pytest.raises(authority.AuthorityRefused, match="immutable rollout history"):
        authority.load_rollout_state(conn)


def test_publication_evidence_and_receipt_are_durably_enforced(conn) -> None:
    with pytest.raises(publication.CorpusIncoherent, match="JSON object"):
        publication.publish(conn, evidence=[])

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_corpus_publications (evidence)"
            " VALUES ('[]'::jsonb)")
    with pytest.raises(publication.CorpusIncoherent, match="JSON object"):
        publication.current(conn)
    conn.rollback()

    published = publication.publish(conn, evidence={"falsifier": "receipt"})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (previous_version,evidence) VALUES (%s,'{}'::jsonb)",
            (published.version,))
    with pytest.raises(publication.CorpusIncoherent,
                       match="lacks its validation receipt"):
        publication.current(conn)
    conn.rollback()

    receipt = published.evidence[publication.RECEIPT_EVIDENCE_KEY]
    assert receipt["schema"] == publication.RECEIPT_SCHEMA
    assert len(str(receipt["receipt_sha256"])) == 64


def test_execution_authority_rejects_sql_publication_without_receipt(conn) -> None:
    root = publication.publish(conn, evidence={"certified": "root"})
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,previous_version,run_id,published_at,window_start,"
            " window_end,evidence FROM sentinel_corpus_publications"
            " WHERE version=%s", (root.version,))
        root_row = cur.fetchone()
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (previous_version,evidence) VALUES (%s,'{}'::jsonb)"
            " RETURNING version", (root.version,))
        forged_version = int(cur.fetchone()[0])
    conn.commit()

    with pytest.raises(authority.AuthorityRefused,
                       match="validation chain is invalid"):
        authority_gate.require_publication_chain(
            conn,
            expected_root_sha256=authority_gate.publication_row_sha256(root_row),
            current_version=forged_version)
