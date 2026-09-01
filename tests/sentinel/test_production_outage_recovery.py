from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import (
    automation_recovery,
    backup_guard,
    dual_reconciliation,
    shadow_recovery,
    shadow_segments,
    shadow_worker,
)
from sentinel.feed import outage_recovery, sharadar, store as feed_store
from sentinel.panel import app as panel_app, model as panel_model


class _OneRowCursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self.row


class _OneRowConn:
    def __init__(self, row):
        self.row = row
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return _OneRowCursor(self.row)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _archiver_row(*, hours_old=1, unresolved=False, mode="on"):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    last_ok = now - timedelta(hours=hours_old) if hours_old is not None else None
    last_fail = (
        now - timedelta(minutes=1) if unresolved
        else (last_ok - timedelta(minutes=1) if last_ok is not None else None))
    return mode, last_ok, last_fail, 7 if unresolved else 0, now


def test_backup_guard_allows_transient_disconnect_but_fences_prolonged_loss():
    healthy = backup_guard.status(_OneRowConn(_archiver_row()))
    assert healthy.state == "HEALTHY"
    assert healthy.writes_permitted is True
    assert healthy.bulk_writes_permitted is True

    degraded = backup_guard.status(
        _OneRowConn(_archiver_row(hours_old=4, unresolved=True)))
    assert degraded.state == "DEGRADED"
    assert degraded.writes_permitted is True
    assert degraded.bulk_writes_permitted is False
    assert degraded.unresolved_failure is True
    with pytest.raises(backup_guard.BackupWriteFenced, match="DEGRADED"):
        backup_guard.require_bulk_writes_permitted(
            _OneRowConn(_archiver_row(hours_old=4, unresolved=True)),
            operation="retained reseed")

    fenced = backup_guard.status(_OneRowConn(_archiver_row(
        hours_old=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 1,
        unresolved=True)))
    assert fenced.state == "FENCED"
    assert fenced.writes_permitted is False
    with pytest.raises(backup_guard.BackupWriteFenced, match="external WAL"):
        backup_guard.require_writes_permitted(
            _OneRowConn(_archiver_row(
                hours_old=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 1,
                unresolved=True)),
            operation="new order")


def test_backup_guard_refuses_missing_archive_authority():
    result = backup_guard.status(_OneRowConn(_archiver_row(
        hours_old=None, unresolved=True)))
    assert result.state == "FENCED"
    result = backup_guard.status(_OneRowConn(_archiver_row(mode="off")))
    assert result.state == "FENCED"


def test_feed_outage_recovery_escalates_only_named_local_state(monkeypatch):
    class LocalRecoverable(RuntimeError):
        pass

    monkeypatch.setattr(
        outage_recovery, "_RECOVERABLE_LOCAL_STATE", (LocalRecoverable,))
    seeded = {"done": False, "args": None}
    daily_calls = {"count": 0}
    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session",
        lambda _conn: "2026-08-21" if not seeded["done"] else "2026-08-25")
    monkeypatch.setattr(
        outage_recovery, "retained_market_start", lambda _conn: "2025-08-20")
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_bulk_writes_permitted",
        lambda *_args, **_kwargs: None)

    def daily(_conn, *, today):
        assert today == "2026-08-25"
        daily_calls["count"] += 1
        if daily_calls["count"] == 1:
            raise LocalRecoverable("stale")
        return SimpleNamespace(kind="daily")

    monkeypatch.setattr(outage_recovery.ingest, "daily", daily)

    def seed(_conn, *, date_from, date_to):
        seeded["done"] = True
        seeded["args"] = (date_from, date_to)

    monkeypatch.setattr(outage_recovery.ingest, "seed", seed)
    monkeypatch.setattr(
        outage_recovery.publication, "assert_operationally_coherent",
        lambda _c, **_kwargs: None)
    monkeypatch.setattr(outage_recovery.publication, "chain_gaps", lambda _c: [])

    conn = SimpleNamespace(rollback=lambda: None)
    result = outage_recovery.catch_up(conn, target_session="2026-08-25")

    assert result.mode == "RETAINED_FULL_RESEED"
    assert result.recovered_from == "LocalRecoverable"
    assert seeded["args"] == ("2025-08-20", "2026-08-25")
    assert daily_calls["count"] == 2


def test_hard_backup_fence_blocks_ordinary_daily_before_ingest(monkeypatch):
    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session",
        lambda _conn: "2026-08-21")
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            backup_guard.BackupWriteFenced("backup FENCED")))
    monkeypatch.setattr(
        outage_recovery.ingest, "daily",
        lambda *_args, **_kwargs: pytest.fail(
            "ordinary ingest must not start after hard backup fence"))

    with pytest.raises(backup_guard.BackupWriteFenced, match="FENCED"):
        outage_recovery.catch_up(SimpleNamespace(), target_session="2026-08-25")


def test_degraded_backup_blocks_bulk_reseed_before_seed_starts(monkeypatch):
    class LocalRecoverable(RuntimeError):
        pass

    monkeypatch.setattr(
        outage_recovery, "_RECOVERABLE_LOCAL_STATE", (LocalRecoverable,))
    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session",
        lambda _conn: "2026-08-21")
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outage_recovery.ingest, "daily",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(LocalRecoverable("stale")))
    monkeypatch.setattr(
        outage_recovery, "retained_market_start", lambda _conn: "2025-08-20")
    monkeypatch.setattr(
        outage_recovery.ingest, "seed",
        lambda *_args, **_kwargs: pytest.fail(
            "bulk seed must not start while backup is degraded"))
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_bulk_writes_permitted",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            backup_guard.BackupWriteFenced("backup DEGRADED")))

    conn = SimpleNamespace(rollback=lambda: None)
    with pytest.raises(backup_guard.BackupWriteFenced, match="DEGRADED"):
        outage_recovery.catch_up(conn, target_session="2026-08-25")


def test_feed_outage_recovery_never_relabels_vendor_failure_local(monkeypatch):
    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session",
        lambda _conn: "2026-08-21")
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda *_args, **_kwargs: None)
    vendor = sharadar.SharadarRequestError("provider unavailable")
    monkeypatch.setattr(
        outage_recovery.ingest, "daily",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(vendor))
    monkeypatch.setattr(
        outage_recovery.ingest, "seed",
        lambda *_args, **_kwargs: pytest.fail("vendor failure must not full-reseed"))

    with pytest.raises(sharadar.SharadarRequestError):
        outage_recovery.catch_up(SimpleNamespace(), target_session="2026-08-25")


def test_automation_backup_fence_blocks_new_work_but_not_recovery(monkeypatch):
    runtime = object.__new__(automation_recovery.ProductionAutomation)
    conn = _OneRowConn(_archiver_row(
        hours_old=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 1,
        unresolved=True))
    runtime.connect = lambda: conn

    with pytest.raises(backup_guard.BackupWriteFenced):
        runtime._require_backup_for_new_mutation("plan")
    assert conn.closed is True
    assert (automation_recovery.ProductionAutomation.recover
            is automation_recovery.base.ProductionAutomation.recover)


@pytest.mark.parametrize(
    ("latest", "target", "expected"),
    [
        ("2026-08-21", "2026-08-24", "normal"),
        ("2026-08-20", "2026-08-24", "rollover"),
    ],
)
def test_shadow_recovery_distinguishes_one_session_from_causal_gap(
        monkeypatch, latest, target, expected):
    cfg = SimpleNamespace(database_url="db", observation_id="primary")
    monkeypatch.setattr(
        shadow_recovery.base, "preflight",
        lambda *_args, **_kwargs: {
            "status": "ATTESTED_STRUCTURAL", "latest_session": latest})
    monkeypatch.setattr(
        shadow_recovery.calendar, "latest_closed_session", lambda _now: target)
    next_map = {
        "2026-08-20": "2026-08-21",
        "2026-08-21": "2026-08-24",
        "2026-08-24": "2026-08-25",
    }
    monkeypatch.setattr(
        shadow_recovery.calendar, "next_session", lambda session: next_map[str(session)])
    monkeypatch.setattr(
        shadow_recovery.shadow_runtime, "publication_not_before",
        lambda _session: datetime(2026, 8, 25, 3, 45, tzinfo=timezone.utc))
    monkeypatch.setattr(
        shadow_recovery.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 25, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc)))
    monkeypatch.setattr(shadow_recovery, "_require_backup", lambda *_a, **_k: None)
    normal = []
    rollover = []
    monkeypatch.setattr(
        shadow_recovery.base, "advance_once",
        lambda *_a, **_k: normal.append(True) or {"path": "normal"})
    monkeypatch.setattr(
        shadow_recovery, "_roll_and_advance",
        lambda *_a, **_k: rollover.append(True) or {"path": "rollover"})

    result = shadow_recovery.advance_once(
        cfg, now=datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc))

    assert result["path"] == expected
    assert bool(normal) is (expected == "normal")
    assert bool(rollover) is (expected == "rollover")


def test_expired_partial_shadow_waits_then_rolls_instead_of_promoting(monkeypatch):
    cfg = SimpleNamespace(database_url="db", observation_id="primary")
    monkeypatch.setattr(
        shadow_recovery.base, "preflight",
        lambda *_args, **_kwargs: {
            "status": "RECOVERY_REQUIRED",
            "recovery_kind": "TRAILING_CANDIDATE",
            "recovery_session": "2026-08-20",
            "execution_session": "2026-08-21",
            "recovery_cutoff_at": "2026-08-21T13:30:00Z",
        })
    monkeypatch.setattr(
        shadow_recovery, "_fresh_target", lambda _now: "2026-08-24")
    calls = []
    monkeypatch.setattr(
        shadow_recovery, "_roll_and_advance",
        lambda *_a, **kwargs: calls.append(kwargs["target"]) or {"rolled": True})
    monkeypatch.setattr(
        shadow_recovery.base, "advance_once",
        lambda *_a, **_k: pytest.fail("expired candidate must never be promoted"))

    result = shadow_recovery.advance_once(
        cfg, now=datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc))

    assert result == {"rolled": True}
    assert calls == ["2026-08-24"]


def test_shadow_financial_health_is_red_for_multi_session_gap(monkeypatch):
    cfg = SimpleNamespace(database_url="db", observation_id="primary")
    monkeypatch.setattr(
        shadow_recovery.base, "preflight",
        lambda *_args, **_kwargs: {
            "status": "ATTESTED_STRUCTURAL", "latest_session": "2026-08-20"})
    monkeypatch.setattr(
        shadow_recovery.calendar, "latest_closed_session", lambda _now: "2026-08-24")
    monkeypatch.setattr(
        shadow_recovery.calendar, "next_session",
        lambda session: {
            "2026-08-20": "2026-08-21",
            "2026-08-24": "2026-08-25",
        }[str(session)])

    with pytest.raises(shadow_recovery.ShadowServiceWaiting, match="readiness is red"):
        shadow_recovery.service_health(
            cfg, now=datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc))


def test_shadow_financial_health_is_red_after_partial_cutoff(monkeypatch):
    cfg = SimpleNamespace(database_url="db", observation_id="primary")
    monkeypatch.setattr(
        shadow_recovery.base, "preflight",
        lambda *_args, **_kwargs: {
            "status": "RECOVERY_REQUIRED",
            "recovery_cutoff_at": "2026-08-21T13:30:00Z",
        })
    with pytest.raises(shadow_recovery.ShadowServiceWaiting, match="readiness is red"):
        shadow_recovery.service_health(
            cfg, now=datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc))


def test_shadow_worker_only_classifies_true_provider_availability():
    transport = sharadar.SharadarRequestError(
        "Sharadar request failed after 6 attempt(s) (TransportError) for SEP")
    retry = shadow_recovery.ShadowServiceRetry("not ready")
    retry.__cause__ = transport
    assert shadow_worker._availability_failure(retry) is True
    assert shadow_worker._availability_failure(
        sharadar.SharadarRetryDeferred(3600, 429)) is True
    assert shadow_worker._availability_failure(
        backup_guard.BackupWriteFenced("backup offline")) is True

    assert shadow_worker._availability_failure(
        sharadar.SharadarProtocolError("SEP: schema changed")) is False
    assert shadow_worker._availability_failure(
        sharadar.SharadarRequestError(
            "Sharadar request failed (HTTP 401) for SEP")) is False
    assert shadow_worker._availability_failure(RuntimeError("logic bug")) is False


def test_post_gap_dual_transport_requires_exact_segment_marker(monkeypatch):
    marker = "b" * 64
    state = SimpleNamespace(last_processed_session="2026-08-25")
    result = SimpleNamespace(
        session="2026-08-25", shadow_verdict="SHADOW_GO",
        verification="VERIFIED", state=state)
    monkeypatch.setattr(
        dual_reconciliation.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: result)
    monkeypatch.setattr(
        dual_reconciliation.shadow_segments, "active_segment",
        lambda *_args, **_kwargs: SimpleNamespace(index=2, marker_sha256=marker))
    monkeypatch.setattr(
        dual_reconciliation, "_load_regenesis_handover",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        dual_reconciliation.journal, "latest_plan", lambda _conn: None)
    monkeypatch.delenv(dual_reconciliation.REGENESIS_APPROVAL_ENV, raising=False)

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="economic segment 2"):
        dual_reconciliation.verified_shadow_intent(
            object(), decision_session="2026-08-25",
            observation_id="primary", starting_cash="100000")

    monkeypatch.setenv(dual_reconciliation.REGENESIS_APPROVAL_ENV, marker)
    assert dual_reconciliation.verified_shadow_intent(
        object(), decision_session="2026-08-25",
        observation_id="primary", starting_cash="100000") is result


def test_panel_discloses_segment_return_and_exact_approval_marker(monkeypatch):
    marker = "c" * 64
    monkeypatch.setenv("SENTINEL_REVIEWED_DEPLOYMENT_MODE", "dual")
    monkeypatch.setenv("SENTINEL_SHADOW_OBSERVATION_ID", "primary")
    monkeypatch.setattr(feed_store, "connect", lambda _dsn: _OneRowConn(None))
    monkeypatch.setattr(
        panel_app.shadow_segments, "active_segment",
        lambda *_args, **_kwargs: SimpleNamespace(
            index=3, first_session="2026-08-25", reason="MULTI_SESSION_CAUSAL_GAP",
            predecessor_session="2026-08-20", marker_sha256=marker))
    original = panel_model.Panel(rows=[
        panel_model.Row(
            "shadow_verification", "Certified shadow strategy",
            "SHADOW VERIFIED THROUGH 2026-08-25"),
        panel_model.Row("shadow_return", "Certified strategy return", "+2.00%"),
    ])

    disclosed = panel_app._shadow_segment_disclosure(original, "postgresql://test")

    segment = disclosed.row("shadow_segment")
    assert segment is not None and segment.status == panel_model.WARN
    assert marker in segment.detail
    returned = disclosed.row("shadow_return")
    assert returned is not None
    assert returned.label == "Certified segment return"
    assert "NOT trial-to-date" in returned.detail


def test_segment_rollover_reason_does_not_hide_a_single_contiguous_session():
    assert (shadow_recovery._rollover_reason("2026-08-21", "2026-08-24")
            == shadow_segments.SEGMENT_REASON_MISSED_FOLLOWING_OPEN)
    assert (shadow_recovery._rollover_reason("2026-08-20", "2026-08-24")
            == shadow_segments.SEGMENT_REASON_MULTI_SESSION_GAP)


def test_segment_zero_without_reviewed_config_delegates_original_genesis_check():
    calls = []

    def original(conn, *, current, first_session, runtime_identity):
        calls.append((conn, current, first_session, runtime_identity))
        return "legacy-pass"

    fake_runtime = SimpleNamespace(
        _require_reviewed_genesis_publication=original,
        PostgresShadowObservationStore=object,
    )
    shadow_segments.install_runtime_store(fake_runtime)
    conn = object()
    publication = object()
    identity = {"validated_data_publication_sha256": "a" * 64}

    result = fake_runtime._require_reviewed_genesis_publication(
        conn, current=publication, first_session="2026-08-25",
        runtime_identity=identity)

    assert result == "legacy-pass"
    assert calls == [(conn, publication, "2026-08-25", identity)]
