import json

import pytest

from sentinel import trial_evidence
from sentinel.controller.frozen_rule import load as load_controller
from sentinel.controller.machine import Controller
from sentinel.core.decision import runtime_strategy_identity
from sentinel.core.production import SessionState
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres(); server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = feed_store.connect(pg.sync_dsn)
    drop_public_tables(c)
    feed_store.require_feed_schema(c)
    from sentinel import schema
    schema.ensure_schema(c)
    yield c
    c.close()


def canonical_state(session="2026-08-20"):
    config = load_controller()
    state = SessionState.fresh(
        starting_cash=100000.0, controller=Controller(config),
        strategy_identity=runtime_strategy_identity(config))
    state.last_processed_session = session
    state.data_version = 7
    state.last_decision = {"session": session, "target_core_exposure": 1.0}
    state.last_evidence = {"observation": {"session": session, "shadow_nav": 100000.0}}
    return state.to_dict()


def test_generic_catchup_state_is_not_misrepresented_as_strategy_evidence(conn):
    assert trial_evidence.record_strategy_session(
        conn, session="2026-08-20", state={"sessions": 1}) is False
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_trial_strategy_evidence")
        assert cur.fetchone()[0] == 0


def test_canonical_strategy_evidence_is_idempotent_and_hash_verified(conn):
    state = canonical_state()
    assert trial_evidence.record_strategy_session(
        conn, session="2026-08-20", state=state) is True
    assert trial_evidence.record_strategy_session(
        conn, session="2026-08-20", state=state) is True
    row = trial_evidence.load_strategy_session(conn, "2026-08-20")
    assert row["state_sha256"] == SessionState.from_dict(state).state_hash
    assert row["decision"]["target_core_exposure"] == 1.0
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_trial_strategy_evidence")
        assert cur.fetchone()[0] == 1


def test_same_session_different_strategy_evidence_refuses(conn):
    state = canonical_state()
    trial_evidence.record_strategy_session(
        conn, session="2026-08-20", state=state)
    changed = json.loads(json.dumps(state))
    changed["last_decision"]["target_core_exposure"] = 0.55
    with pytest.raises(trial_evidence.TrialEvidenceConflict, match="different"):
        trial_evidence.record_strategy_session(
            conn, session="2026-08-20", state=changed)
    conn.rollback()


def test_postgres_refuses_update_and_delete_of_trial_evidence(conn):
    state = canonical_state()
    trial_evidence.record_strategy_session(
        conn, session="2026-08-20", state=state)
    conn.commit()
    with pytest.raises(Exception, match="append-only"):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_trial_strategy_evidence SET data_version=8 "
                "WHERE session='2026-08-20'")
    conn.rollback()
    with pytest.raises(Exception, match="append-only"):
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentinel_trial_strategy_evidence "
                "WHERE session='2026-08-20'")
    conn.rollback()
