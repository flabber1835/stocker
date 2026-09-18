"""Audit #399: kill real database-owning children at rolling commit boundaries.

Pinned production: aff4461d9af6d4a7367018768fda18d948958b49.
Dependencies: disposable PostgreSQL, synthetic source rows, deterministic clock,
and the repository's explicitly reviewed test runtime identity. No broker I/O.
"""
from dataclasses import replace
import json
import os
import select
import signal
import traceback

import pytest

from sentinel import rolling_runtime as runtime, rolling_authority as authority
from sentinel import rolling_initialization as initial, rolling_daily_checkpoint as daily_cp
from sentinel import rolling_checkpoint as origin, shadow_observation as shadow
from sentinel.core import rolling_continuity as continuity
from sentinel.execution import journal
from sentinel.feed import operational_snapshot as op, publication, store
from sentinel.feed.rolling_contract import digest
from tests.conftest import isolated_source_cache, isolated_image_backup_policy  # noqa: F401
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh

BOUNDARIES = [
    ("cold", "genesis_write"), ("cold", "record_write"),
    ("daily", "record_write"), ("daily", "input_archive"),
] + [(phase, boundary) for phase in ("cold", "daily") for boundary in (
    "checkpoint_write", "candidate_commit_before", "candidate_commit_after",
    "authority_write", "authority_commit_before", "authority_commit_after")]


def advance(c, session):
    return runtime.advance(c, through=session, observation_id=OBS, starting_cash=100_000)


def kill_at_boundary(dsn, inherited_fd, phase, boundary, session):
    """Parent sends SIGKILL only after the exact real SQL boundary is signalled."""
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        # Discard the inherited descriptor at OS level, preserving the parent's
        # libpq session; all child SQL uses a new independent connection.
        os.close(inherited_fd)
        c = None
        try:
            c = store.connect(dsn)
            patch = pytest.MonkeyPatch()
            state = {"stage": None, "checkpoint": None}

            def hit(point):
                if point == boundary:
                    marker = {"boundary": point, "phase": phase, "pid": os.getpid(),
                              "backend_pid": c.info.backend_pid,
                              "checkpoint": state["checkpoint"]}
                    os.write(write_fd, (json.dumps(marker) + "\n").encode())
                    while True:
                        signal.pause()

            def wrap(target, name, point, stage=None):
                original = getattr(target, name)
                def invoke(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if stage:
                        state["stage"] = stage
                        if stage == "candidate":
                            cp = args[1]
                            state["checkpoint"] = {"state_hash": cp.state_sha256,
                                "record_hash": cp.record_sha256, "input_hash": digest(cp.input_value),
                                "checkpoint_hash": digest(cp.model_dump(by_alias=True))}
                    hit(point)
                    return result
                patch.setattr(target, name, invoke)

            wrap(shadow.PostgresShadowObservationStore, "append_genesis", "genesis_write")
            wrap(shadow.PostgresShadowObservationStore, "append", "record_write")
            wrap(daily_cp, "archive_input", "input_archive")
            wrap(origin if phase == "cold" else daily_cp, "write", "checkpoint_write", "candidate")
            wrap(authority, "append", "authority_write", "authority")

            class Connection:
                def __getattr__(self, name):
                    return getattr(c, name)
                def commit(self):
                    stage = state["stage"]
                    if stage:
                        hit(stage + "_commit_before")
                    c.commit()
                    if stage:
                        # SQL COMMIT succeeded; its caller has not received the
                        # normal return from the production commit invocation.
                        hit(stage + "_commit_after")
                        state["stage"] = None

            advance(Connection(), session)
            os.write(write_fd, b'{"error":"runtime returned before selected boundary"}\n')
        except BaseException:
            os.write(write_fd, (json.dumps({"error": traceback.format_exc()}) + "\n").encode())
        os._exit(2)

    os.close(write_fd)
    reaped = False
    try:
        readable, _, _ = select.select([read_fd], [], [], 40)
        assert readable, f"child did not reach {phase}/{boundary}"
        raw = os.read(read_fd, 65536)
        marker = json.loads(raw)
        assert "error" not in marker, marker.get("error")
        assert marker["boundary"] == boundary and marker["pid"] == child
        os.kill(child, signal.SIGKILL)
        _, exit_status = os.waitpid(child, 0)
        reaped = True
        assert os.WIFSIGNALED(exit_status) and os.WTERMSIG(exit_status) == signal.SIGKILL
        return marker
    finally:
        os.close(read_fd)
        if not reaped:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child, 0)


@pytest.mark.parametrize("phase,boundary", BOUNDARIES,
                         ids=[f"{phase}-{boundary}" for phase,boundary in BOUNDARIES])
def test_real_process_death_preserves_atomic_economic_closure(
        conn, published, operational_source, monkeypatch, record_property, phase, boundary):
    prior = None
    expected_state = None
    session = "2026-09-14"
    if phase == "daily":
        prior = advance(conn, session)
        refresh(conn, operational_source, monkeypatch)
        session = "2026-09-15"
        with op.pinned(conn) as (pub, binding):
            material, anchors, proof = continuity.prepare(conn, prior=prior.state,
                previous_binding=origin.read(conn).snapshot, publication=pub, binding=binding)
            value = replace(initial._published(material, pub),
                            signal_basis_anchors=anchors, history_proof=proof)
            expected_state = shadow.advance_state(
                shadow.SessionState.from_dict(prior.state.to_dict()), value,
                controller_config=initial._context(OBS, 100_000)["controller"],
                strategy_identity=prior.state.strategy_identity)
            assert expected_state.wealth_core["episodes"]
            assert expected_state.wealth_core["cash"] < 100_000
    conn.rollback()
    dsn = conn.info.dsn
    marker = kill_at_boundary(dsn, conn.fileno(), phase, boundary, session)
    record_property("kill_boundary", json.dumps(marker, sort_keys=True))
    committed_candidate = boundary in {"candidate_commit_after", "authority_write",
                                       "authority_commit_before", "authority_commit_after"}
    committed_authority = boundary == "authority_commit_after"
    c = store.connect(dsn)
    try:
        for key in (publication.CORPUS_LOCK_KEY, journal.WRITER_LOCK_KEY):
            assert c.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
            c.execute("SELECT pg_advisory_unlock(%s)", (key,))
        c.rollback()
        book = shadow.PostgresShadowObservationStore(c, observation_id=OBS)
        before_records = book.records()
        assert len(before_records) == (int(phase == "daily") + int(committed_candidate))
        if phase == "cold":
            assert (book.genesis() is not None) == committed_candidate
            cp = origin.read(c)
        else:
            assert book.genesis() is not None
            cp = daily_cp.read(c)
            archived = c.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                                 (daily_cp.input_name(OBS, session),)).fetchone()
            assert (archived is not None) == committed_candidate
        assert (cp is not None) == committed_candidate
        before_auth = authority.latest(c, OBS)
        assert len(before_auth) == (int(phase == "daily") + int(committed_authority))
        if committed_candidate:
            assert cp.state_sha256 == marker["checkpoint"]["state_hash"]
            assert cp.record_sha256 == marker["checkpoint"]["record_hash"]
            assert digest(cp.input_value) == marker["checkpoint"]["input_hash"]
            assert digest(cp.model_dump(by_alias=True)) == marker["checkpoint"]["checkpoint_hash"]
            if expected_state:
                assert cp.state_sha256 == expected_state.state_hash
        c.rollback()
        classification = runtime.classify(c, observation_id=OBS, starting_cash=100_000,
                                         structural_only=(phase == "daily" and not committed_candidate))
        assert classification["status"] == (
            "VERIFIED" if committed_authority else "RECOVERY_REQUIRED" if committed_candidate
            else "ATTESTED_STRUCTURAL" if phase == "daily" else "NOT_STARTED")
        with monkeypatch.context() as guard:
            if committed_candidate:
                def no_replay(*a, **kw):
                    pytest.fail("durable economic transition was replayed")
                guard.setattr(shadow, "advance_state", no_replay)
                guard.setattr(initial, "warm_session_state", no_replay)
            if committed_authority:
                guard.setattr(authority, "append", lambda *a, **kw: pytest.fail("authority duplicated"))
            recovered = advance(c, session)
        assert recovered.verification == shadow.VERIFIED
        assert recovered.appended == (not committed_candidate)
        if cp is not None:
            assert recovered.state.state_hash == cp.state_sha256
        if expected_state:
            assert recovered.state.to_dict() == expected_state.to_dict()
        final_records = book.records()
        assert len(final_records) == (2 if phase == "daily" else 1)
        assert len(authority.latest(c, OBS)) == (2 if phase == "daily" else 1)
        if committed_authority:
            assert recovered.runtime_authority_sha256 == digest(before_auth[0].model_dump(by_alias=True))
        for table in ("sentinel_execution_plans", "sentinel_commands", "sentinel_fills"):
            assert c.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
        c.rollback()
        c.close()
        c = store.connect(dsn)
        again = runtime.status(c, observation_id=OBS, starting_cash=100_000)
        assert again.state.state_hash == recovered.state.state_hash
        record_property("recovered_state_hash", recovered.state.state_hash)
        record_property("pre_recovery_status", classification["status"])
    finally:
        c.close()
