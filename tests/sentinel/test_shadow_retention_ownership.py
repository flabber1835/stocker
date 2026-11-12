"""Retention is separate from financial work and respects the idle drain."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import inspect
import os
from types import SimpleNamespace

import pytest

from sentinel import rolling_runtime as runtime
from sentinel import shadow_drain, shadow_health_projection, shadow_service, shadow_supervisor
from sentinel.feed import retention


@pytest.fixture
def service(monkeypatch):
    events = []
    held = [False]
    conn = SimpleNamespace(rollback=lambda: events.append("rollback"))
    result = SimpleNamespace(to_dict=lambda: {"verified": True})
    monkeypatch.setenv("SENTINEL_FEED_SERVICE_MODE", "SHADOW")
    monkeypatch.setattr(runtime, "classify", lambda *a, **kw:
                        {"status": "ATTESTED_STRUCTURAL", "latest_session": "2026-10-29"})
    monkeypatch.setattr(runtime.calendar, "next_session", lambda _: "2026-10-30")
    opened = datetime(2026, 10, 30, 13, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(runtime.calendar, "session_window", lambda _: (opened, opened))
    monkeypatch.setattr(runtime.initial, "_now", lambda _: opened.replace(day=29))

    @contextmanager
    def writer(_):
        assert not held[0], "post-verification cleanup inherited account ownership"
        events.append("acquire")
        held[0] = True
        try:
            yield
        finally:
            held[0] = False
            events.append("release")

    def advance(*a, **kw):
        assert held[0]
        events.append("advance")
        return result

    def publish(*a, **kw):
        assert held[0], "health inventory was published without canonical ownership"
        events.append("health")

    def maintain(_):
        assert not held[0], "cleanup held the financial writer during its own backup proof"
        events.append("cleanup")

    monkeypatch.setattr(runtime.journal, "writer_lock", writer)
    monkeypatch.setattr(runtime, "advance", advance)
    monkeypatch.setattr(shadow_service.ShadowServiceConfig, "from_env", lambda: object())
    monkeypatch.setattr(shadow_health_projection, "publish", publish)
    monkeypatch.setattr(retention, "maintain", maintain)
    return SimpleNamespace(conn=conn, result=result, events=events, held=held)


def invoke(service):
    return runtime.service_advance(service.conn, through="2026-10-29",
        observation_id="paper-source", starting_cash=100000, acquisition_deadline=object())


def test_verified_health_stays_owned_and_advance_does_not_run_disposal(service):
    assert invoke(service) is service.result
    assert service.events == ["rollback", "acquire", "advance", "health", "release"]


def test_failed_advance_cannot_publish_health_or_enter_disposal(service, monkeypatch):
    def failed(*a, **kw):
        raise RuntimeError("financial advance refused")
    monkeypatch.setattr(runtime, "advance", failed)
    with pytest.raises(RuntimeError, match="financial advance refused"):
        invoke(service)
    assert service.events == ["rollback", "acquire", "release"]


def test_failed_health_hint_still_releases_ownership(service, monkeypatch, capsys):
    def failed(*a, **kw):
        assert service.held[0]
        raise OSError("projection unavailable")
    monkeypatch.setattr(shadow_health_projection, "publish", failed)
    assert invoke(service) is service.result
    assert service.events == ["rollback", "acquire", "advance", "release"]
    assert "shadow health projection unavailable: OSError" in capsys.readouterr().err


def test_non_shadow_role_preserves_verification_and_does_not_publish_health(service, monkeypatch):
    monkeypatch.delenv("SENTINEL_FEED_SERVICE_MODE")
    assert invoke(service) is service.result
    assert service.events == ["rollback", "acquire", "advance", "release"]


def test_unchanged_branch_renews_evidence_without_running_disposal(service, monkeypatch):
    from sentinel.feed import readiness
    monkeypatch.setattr(runtime, "classify", lambda *a, **kw: {
        "status": "VERIFIED_UNCHANGED", "result": service.result,
        "_readiness_snapshot": object(), "inventory_sha256": "same-inventory"})
    monkeypatch.setattr(readiness, "save_snapshot", lambda *a: service.events.append("readiness"))
    monkeypatch.setattr(runtime, "_refresh_unchanged_health", lambda *a: service.events.append("health"))
    assert invoke(service) is service.result
    assert service.events == ["readiness", "health"]


def test_idle_retention_holds_drain_admission_and_yields_to_a_drain(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow_supervisor, 'LATCH_FILE', tmp_path/'latch.json')
    calls = []

    def retain(url):
        calls.append(url)
        fd = os.open(tmp_path/shadow_drain.LOCK_NAME, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        return True

    monkeypatch.setattr(retention, 'idle_pass', retain)
    assert shadow_supervisor._idle_retention('private') is True
    monkeypatch.setattr(shadow_drain, '_acknowledge_idle', lambda *_, **__: True)
    assert shadow_supervisor._idle_retention('private') is False
    assert calls == ['private']


def test_idle_retention_cannot_consume_the_next_close_wake(monkeypatch):
    clock = [0.0]
    close = datetime(2026, 11, 11, 21, tzinfo=timezone.utc)
    monkeypatch.setattr(shadow_supervisor.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(shadow_supervisor.time, 'sleep', lambda n: clock.__setitem__(0, clock[0] + n))
    monkeypatch.setattr(shadow_supervisor.shadow_budget, 'now', lambda: close + timedelta(seconds=clock[0]))
    calls = []
    args = dict(deadline=300, close_at=close + timedelta(seconds=8), stopping=lambda: False,
                heartbeat=lambda: None, idle_work=lambda: calls.append(clock[0]) or False)
    shadow_supervisor._poll_after_worker(**args)
    assert clock[0] == 8 and calls == []

    # Removing only the budget guard lets a child run with insufficient time.
    source = inspect.getsource(shadow_supervisor._poll_after_worker)
    guard = 'and remaining() > RETENTION_CHILD_SECONDS + RETENTION_REAP_SECONDS'
    assert guard in source
    altered = {}
    exec(source.replace(guard, ''), vars(shadow_supervisor), altered)
    clock[0] = 0
    altered['_poll_after_worker'](**args)
    assert calls == [0]


def test_restoring_nested_cleanup_is_detected_by_lock_observation(service, monkeypatch):
    original = runtime.advance
    def nested(*a, **kw):
        result = original(*a, **kw)
        retention.maintain(service.conn)
        return result
    monkeypatch.setattr(runtime, "advance", nested)
    with pytest.raises(AssertionError, match="cleanup held the financial writer"):
        invoke(service)


def test_removing_health_ownership_is_detected(service, monkeypatch):
    @contextmanager
    def unlocked(_):
        # This falsifier still lets advance succeed; only the health ownership
        # requirement should detect the sequencing regression.
        service.held[0] = True
        yield
        service.held[0] = False
    original = runtime.advance
    def release_after_advance(*a, **kw):
        result = original(*a, **kw)
        service.held[0] = False
        return result
    monkeypatch.setattr(runtime.journal, "writer_lock", unlocked)
    monkeypatch.setattr(runtime, "advance", release_after_advance)
    # service_advance deliberately treats a health hint as best effort; the
    # failed guarded publication must be recorded rather than called valid.
    assert invoke(service) is service.result
    assert "health" not in service.events
