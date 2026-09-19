"""Real rolling runtime approval, interrupted commit recovery and service routing."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel import rolling_runtime as runtime, rolling_authority as authority
from sentinel import rolling_initialization as initial, rolling_daily_checkpoint as daily_cp
from sentinel import rolling_checkpoint as origin, shadow_runtime, shadow_service, shadow_recovery, shadow_observation as shadow
from sentinel.feed import rolling_go_inputs as inputs, operational_snapshot as op, store, calendar
from sentinel.feed.rolling_contract import PriceWindow, canonical_json, digest
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS, NOW
from tests.sentinel.test_rolling_daily import refresh


def advance(conn, session="2026-09-14"):
    return runtime.advance(conn, through=session, observation_id=OBS, starting_cash=100_000)


def status(conn):
    return runtime.status(conn, observation_id=OBS, starting_cash=100_000)


def classify(conn, **kwargs):
    return runtime.classify(conn, observation_id=OBS, starting_cash=100_000, **kwargs)


def test_first_runtime_approval_is_signed_bound_and_idempotent(conn, published):
    assert classify(conn)["status"] == "NOT_STARTED"
    result = advance(conn)
    assert result.verification == shadow.VERIFIED and result.shadow_verdict == shadow.SHADOW_GO
    assert result.to_dict()["verification_scope"] == authority.SCOPE
    value = authority.latest(conn, OBS)[0]
    authority.require_binding(value, origin.read(conn))
    assert value.previous_authority_sha256 is None
    conn.rollback()
    again = advance(conn)
    assert again.state.state_hash == result.state.state_hash and not again.appended
    assert len(authority.latest(conn, OBS)) == 1
    assert initial.resume(conn, observation_id=OBS, starting_cash=100_000).verification == shadow.CANDIDATE
    for table in ("sentinel_execution_plans", "sentinel_commands", "sentinel_fills"):
        assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_committed_candidate_requires_runtime_attestation(conn, published):
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    assert classify(conn)["status"] == "RECOVERY_REQUIRED"
    with pytest.raises(authority.Refused, match="ATTESTATION_REQUIRED"):
        status(conn)
    assert advance(conn).verification == shadow.VERIFIED


def test_authority_failure_preserves_candidate_and_recovery_never_replays(conn, published, monkeypatch):
    original = authority.append
    monkeypatch.setattr(authority, "append", lambda *_: (_ for _ in ()).throw(OSError("authority interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        advance(conn)
    checkpoint = origin.read(conn)
    assert checkpoint is not None and authority.latest(conn, OBS) == []
    conn.rollback()
    monkeypatch.setattr(authority, "append", original)
    monkeypatch.setattr(initial, "initialize", lambda *_a, **_k: pytest.fail("candidate replayed"))
    monkeypatch.setattr(shadow, "advance_state", lambda *_a, **_k: pytest.fail("kernel replayed"))
    result = advance(conn)
    assert result.state.state_hash == checkpoint.state_sha256
    assert result.verification == shadow.VERIFIED and not result.appended


def test_postcommit_cutoff_crossing_cannot_issue_authority(conn, published, monkeypatch):
    original = initial.initialize
    def crossing(*args, **kwargs):
        result = original(*args, **kwargs)
        opened, _ = calendar.session_window(calendar.next_session(result.session))
        monkeypatch.setattr(initial, "_now", lambda conn: opened)
        return result
    monkeypatch.setattr(initial, "initialize", crossing)
    with pytest.raises(origin.RollingColdStartRefused, match="MISSED_OPEN"):
        advance(conn)
    assert origin.read(conn) is not None and authority.latest(conn, OBS) == []
    conn.rollback()
    with pytest.raises(origin.RollingColdStartRefused, match="MISSED_OPEN"):
        classify(conn)


def test_lost_authority_commit_acknowledgement_recovers_exact_row(conn, published, monkeypatch):
    original = authority.append
    state = {"written": False, "raised": False}
    def append(*args):
        original(*args)
        state["written"] = True
    monkeypatch.setattr(authority, "append", append)
    class LostAck:
        def __getattr__(self, name):
            return getattr(conn, name)
        def commit(self):
            conn.commit()
            if state["written"] and not state["raised"]:
                state["raised"] = True
                raise OSError("lost authority acknowledgement")
    with pytest.raises(OSError, match="lost authority"):
        advance(LostAck())
    before = authority.latest(conn, OBS)[0]
    conn.rollback()
    monkeypatch.setattr(authority, "append", lambda *_: pytest.fail("duplicate authority"))
    result = advance(conn)
    assert result.runtime_authority_sha256 == digest(before.model_dump(by_alias=True))


@pytest.mark.parametrize("defect", ["signature", "checkpoint", "runtime", "timing", "chain"])
def test_authority_tamper_refuses_runtime_status(conn, published, defect):
    advance(conn)
    value = authority.latest(conn, OBS)[0].model_dump(by_alias=True)
    if defect in {"checkpoint", "runtime"}:
        value[defect + "_sha256"] = "a" * 64
    elif defect == "timing":
        value["timing"]["candidate_committed_at"] = value["timing"]["execution_open_at"]
    elif defect == "chain":
        value["previous_authority_sha256"] = "b" * 64
    raw = {"authority": value, "hmac_sha256": "0" * 64 if defect == "signature" else authority.signature(value)}
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
                 (canonical_json(raw), authority.name(OBS, value["session"])))
    conn.commit()
    with pytest.raises(shadow.ShadowObservationRefused):
        status(conn)


def test_status_is_readonly_without_warmup_or_transition(conn, published, monkeypatch):
    advance(conn)
    original = runtime._closure
    def closure(conn, context):
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        return original(conn, context)
    monkeypatch.setattr(runtime, "_closure", closure)
    monkeypatch.setattr(initial, "warm_session_state", lambda *_a, **_k: pytest.fail("rewarmed"))
    monkeypatch.setattr(shadow, "advance_state", lambda *_a, **_k: pytest.fail("replayed"))
    assert status(conn).verification == shadow.VERIFIED


def test_daily_runtime_continuation_and_bounded_restart(conn, published, operational_source, monkeypatch):
    first = advance(conn)
    refresh(conn, operational_source, monkeypatch)
    with pytest.raises(authority.Refused, match="PUBLICATION_CHANGED"):
        status(conn)
    second = advance(conn, "2026-09-15")
    assert second.state.wealth_core["episodes"]
    assert second.state.state_hash != first.state.state_hash
    assert status(conn).state.state_hash == second.state.state_hash
    conn.execute("SET LOCAL session_replication_role=replica")
    for table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
        conn.execute("DELETE FROM " + table + " WHERE candidate_id=%s", (published["candidate_id"],))
    conn.commit()
    assert status(conn).verification == shadow.VERIFIED
    refresh(conn, operational_source, monkeypatch)
    third = advance(conn, "2026-09-16")
    assert third.verification == shadow.VERIFIED
    assert len(authority.latest(conn, OBS)) == 2
    assert status(conn).state.state_hash == third.state.state_hash


def test_daily_cannot_skip_missing_predecessor_authority(conn, published, operational_source, monkeypatch):
    advance(conn)
    refresh(conn, operational_source, monkeypatch)
    advance(conn, "2026-09-15")
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s", (authority.name(OBS, "2026-09-14"),))
    conn.commit()
    with pytest.raises(authority.Refused, match="PREDECESSOR_AUTHORITY_REQUIRED"):
        status(conn)


def test_unattested_candidate_cannot_be_skipped_by_new_publication(conn, published, operational_source, monkeypatch):
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    refresh(conn, operational_source, monkeypatch)
    with pytest.raises(authority.Refused, match="CANDIDATE_MUST_BE_ATTESTED_FIRST"):
        advance(conn, "2026-09-15")
    assert daily_cp.read(conn) is None


def test_runtime_requires_exact_target_and_adjacent_session(conn, published, operational_source, monkeypatch):
    with pytest.raises(authority.Refused, match="TARGET_CHANGED"):
        advance(conn, "2026-09-15")
    advance(conn)
    refresh(conn, operational_source, monkeypatch, days=2)
    with pytest.raises(authority.Refused, match="SESSION_GAP"):
        advance(conn, "2026-09-16")


def test_backup_refusal_after_candidate_commit_cannot_issue_authority(conn, published, monkeypatch):
    original = runtime.backup_runtime_authority.require
    def require(conn, *, operation):
        if operation == "rolling runtime attestation":
            raise RuntimeError("backup refused")
        return original(conn, operation=operation)
    monkeypatch.setattr(runtime.backup_runtime_authority, "require", require)
    with pytest.raises(RuntimeError, match="backup refused"):
        advance(conn)
    assert origin.read(conn) is not None and authority.latest(conn, OBS) == []


def test_publication_and_writer_locks_span_candidate_and_authority_commits(conn, published, monkeypatch):
    import psycopg
    from sentinel.execution import journal
    from sentinel.feed import publication
    original = authority.append
    observed = []
    def append(conn, value):
        with psycopg.connect(conn.info.dsn) as contender:
            for key in (publication.CORPUS_LOCK_KEY, journal.WRITER_LOCK_KEY):
                acquired = contender.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
                if acquired:
                    contender.execute("SELECT pg_advisory_unlock(%s)", (key,))
                observed.append(acquired)
        original(conn, value)
    monkeypatch.setattr(authority, "append", append)
    advance(conn)
    assert observed == [False, False]


def test_changed_reviewed_runtime_withdraws_verification(conn, published, monkeypatch):
    advance(conn)
    original = shadow_runtime._validated_runtime_identity
    monkeypatch.setattr(shadow_runtime, "_validated_runtime_identity",
        lambda **kwargs: {**original(**kwargs), "changed_identity": "different"})
    with pytest.raises(origin.RollingColdStartRefused, match="CONFIG_CHANGED"):
        status(conn)


def test_rolling_book_cannot_dispatch_back_to_legacy_publication(conn, published, monkeypatch):
    advance(conn)
    monkeypatch.setattr(inputs, "current", lambda conn: None)
    with pytest.raises(shadow_runtime.ShadowRuntimeRefused, match="ROLLING_PUBLICATION_REQUIRED"):
        shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=100_000)


def test_actual_shadow_service_initializes_and_acquires_next_snapshot(conn, published, operational_source, monkeypatch):
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, "connect", lambda _: Borrowed())
    monkeypatch.setattr(shadow_service.ingest, "daily", lambda *_a, **_k: pytest.fail("legacy ingest"))
    config = shadow_service.ShadowServiceConfig("fixture", OBS, Decimal("100000"),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    first = shadow_recovery.advance_once(config, now=NOW)
    assert first["verification_scope"] == authority.SCOPE and first["verification"] == "VERIFIED"
    # Advance only synthetic provider/clock state: the service must publish.
    data = operational_source
    for table in ("SEP", "SFP"):
        rows = [deepcopy(row) for row in data[table] if row["date"] == "2026-09-14"]
        for row in rows:
            row["date"] = "2026-09-15"
        data[table].extend(rows)
    for row in data["TICKERS"]:
        row["lastpricedate"] = "2026-09-15"
    start = str(PriceWindow.through("2026-09-15").start)
    data["SFP"][:] = [row for row in data["SFP"] if row["date"] >= start]
    later = NOW + timedelta(days=1)
    monkeypatch.setattr(calendar, "latest_closed_session", lambda now=None: "2026-09-15")
    monkeypatch.setattr(op, "_now", lambda: later)
    monkeypatch.setattr(initial, "_now", lambda conn: later)
    assert shadow_recovery.service_health(config, now=later)["service_health"] == "HEALTHY_WAITING"
    second = shadow_recovery.advance_once(config, now=later)
    assert second["session"] == "2026-09-15" and second["verification"] == "VERIFIED"
    calls = list(data["calls"])
    assert shadow_recovery.advance_once(config, now=later)["appended"] is False
    assert data["calls"] == calls


def test_production_worker_gap_waits_without_legacy_catchup(conn, published, monkeypatch):
    advance(conn)
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, "connect", lambda _: Borrowed())
    attempts = []
    monkeypatch.setattr(shadow_recovery, "_roll_and_advance",
        lambda *_a, **_k: attempts.append("legacy recovery"))
    monkeypatch.setattr(calendar, "latest_closed_session", lambda now=None: "2026-09-16")
    monkeypatch.setattr(initial, "_now", lambda conn: NOW + timedelta(days=2))
    config = shadow_service.ShadowServiceConfig("fixture", OBS, Decimal("100000"),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    with pytest.raises(shadow_service.ShadowServiceWaiting, match="MISSING_DATED_PUBLICATION:2026-09-15"):
        shadow_recovery.advance_once(config, now=NOW + timedelta(days=2))
    assert attempts == []
    assert daily_cp.read(conn) is None
    assert shadow_recovery.service_health(config, now=NOW + timedelta(days=2))["service_health"] == "RECONSTRUCTION_PENDING"
