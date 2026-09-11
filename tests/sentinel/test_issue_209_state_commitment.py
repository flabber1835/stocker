from __future__ import annotations

import datetime as dt
import json

import pytest

from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from sentinel import binding, schema
from sentinel.core import catchup
from sentinel.execution import journal
from sentinel.execution.plan import ExecutionPlan
from sentinel.feed import publication, store as feed_store
from tests.sentinel.test_paper_activation import (
    PRIOR,
    _plan,
    _state,
)


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
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    drop_public_tables(connection)
    feed_store.require_feed_schema(connection)
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def _install_committed_predecessor(conn):
    bound = binding.bind(
        conn,
        deployment_id="sentinel-issue-209-state",
        broker="sim",
        broker_account_id="SIM-PAPER",
    )
    pinned = publication.publish(
        conn,
        window_start=PRIOR.isoformat(),
        window_end=PRIOR.isoformat(),
        evidence={"frontier": PRIOR.isoformat(), "test": True},
    )
    state = _state(session=PRIOR, data_version=pinned.version)
    catchup._mark_processed(conn, PRIOR, state.to_dict())  # noqa: SLF001
    conn.commit()

    template = _plan(state, pinned, bound)
    prior = ExecutionPlan(**{
        **template.__dict__,
        "plan_id": "pending",
        "decision_session": PRIOR,
        "effective_session": dt.date(2026, 8, 10),
    })
    prior = ExecutionPlan(**{
        **prior.__dict__,
        "plan_id": f"sentinel-{prior.fingerprint()}",
    })
    journal.adopt_current_plan(conn, prior)
    return state, prior


def test_intact_predecessor_state_resumes(conn):
    state, prior = _install_committed_predecessor(conn)

    assert catchup.resume_state(conn) == state.to_dict()
    assert journal.latest_plan(conn).plan_id == prior.plan_id


def test_valid_json_mutation_cannot_seed_next_strategy_transition(conn):
    state, prior = _install_committed_predecessor(conn)
    corrupted = state.to_dict()
    corrupted["last_decision"]["reason"] = "CORRUPTED-BUT-VALID"

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_processed_sessions SET state=%s::jsonb "
            "WHERE cursor_name=%s",
            (json.dumps(corrupted), "catchup"),
        )
    conn.commit()

    with pytest.raises(
        catchup.StateCommitmentMismatch,
        match="state fingerprint does not match",
    ):
        catchup.resume_state(conn)

    assert journal.latest_plan(conn).plan_id == prior.plan_id


@pytest.mark.parametrize("mutation", ["intact", "state", "missing", "hash", "anchor", "session"])
def test_interrupted_canonical_catchup_requires_its_exact_checkpoint(conn, mutation):
    _, prior = _install_committed_predecessor(conn)
    first, last = dt.date(2026, 8, 10), dt.date(2026, 8, 11)
    advanced = []

    def advance(connection, day, state):
        if day == last.isoformat():
            raise RuntimeError("scheduled interruption before second transition")
        advanced.append(day)
        return _state(session=first, data_version=prior.data_version).to_dict()

    with pytest.raises(RuntimeError, match="scheduled interruption"):
        catchup.catch_up(conn, through=last, missed=[first, last],
                         advance_state=advance, decide=lambda *_: None)
    assert catchup.last_processed_session(conn) == first
    assert journal.latest_plan(conn).plan_id == prior.plan_id
    checkpoint_name = "catchup:resume_commitment:v1"
    if mutation == "state":
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,"
                     "'{shadow_peak_nav}','9999'::jsonb) WHERE cursor_name='catchup'")
    elif mutation == "missing":
        conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s", (checkpoint_name,))
    elif mutation in {"hash", "anchor"}:
        field = "state_sha256" if mutation == "hash" else "anchor_plan_id"
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,%s,"
                     "'\"corrupted\"'::jsonb) WHERE cursor_name=%s", ([field], checkpoint_name))
    elif mutation == "session":
        conn.execute("UPDATE sentinel_processed_sessions SET session=%s WHERE cursor_name=%s",
                     (PRIOR, checkpoint_name))
    conn.commit()
    if mutation != "intact":
        with pytest.raises(catchup.StateCommitmentMismatch):
            catchup.resume_state(conn)
        assert journal.latest_plan(conn).plan_id == prior.plan_id
        return

    expected = _state(session=first, data_version=prior.data_version).to_dict()
    assert catchup.resume_state(conn) == expected
    def finish(connection, day, state):
        advanced.append(day)
        return _state(session=last, data_version=prior.data_version).to_dict()
    def decide(day, state):
        from sentinel.core.session import SessionState
        return _plan(SessionState.from_dict(state), publication.require_current(conn), binding.require(conn))
    result = catchup.catch_up(conn, through=last, missed=[first, last],
                             advance_state=finish, decide=decide)
    assert advanced == [first.isoformat(), last.isoformat()]
    assert result.sessions_replayed == 1
    assert catchup.resume_state(conn) == result.state
    assert result.plan.decision_session == last
    assert conn.execute("SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s",
                        (checkpoint_name,)).fetchone() is None
