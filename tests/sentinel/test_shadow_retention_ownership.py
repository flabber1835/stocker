"""Disposal never inherits the financial advance's account ownership."""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentinel import rolling_runtime as runtime
from sentinel import shadow_health_projection, shadow_service
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


def test_verified_health_stays_owned_and_disposal_runs_only_after_release(service):
    assert invoke(service) is service.result
    assert service.events == ["rollback", "acquire", "advance", "health", "release", "cleanup"]


def test_failed_advance_cannot_publish_health_or_enter_disposal(service, monkeypatch):
    def failed(*a, **kw):
        raise RuntimeError("financial advance refused")
    monkeypatch.setattr(runtime, "advance", failed)
    with pytest.raises(RuntimeError, match="financial advance refused"):
        invoke(service)
    assert service.events == ["rollback", "acquire", "release"]


def test_failed_health_hint_still_releases_ownership_before_best_effort_cleanup(service, monkeypatch, capsys):
    def failed(*a, **kw):
        assert service.held[0]
        raise OSError("projection unavailable")
    monkeypatch.setattr(shadow_health_projection, "publish", failed)
    assert invoke(service) is service.result
    assert service.events == ["rollback", "acquire", "advance", "release", "cleanup"]
    assert "shadow health projection unavailable: OSError" in capsys.readouterr().err


def test_unexpected_disposal_failure_preserves_verified_result_and_rolls_back(service, monkeypatch, capsys):
    def failed(_):
        assert not service.held[0]
        raise OSError("disposable cleanup unavailable")
    monkeypatch.setattr(retention, "maintain", failed)
    assert invoke(service) is service.result
    assert service.events[-3:] == ["health", "release", "rollback"]
    assert "rolling input maintenance unavailable: OSError" in capsys.readouterr().err


def test_non_shadow_role_preserves_verification_and_does_not_publish_health(service, monkeypatch):
    monkeypatch.delenv("SENTINEL_FEED_SERVICE_MODE")
    assert invoke(service) is service.result
    assert service.events == ["rollback", "acquire", "advance", "release", "cleanup"]


def test_unchanged_branch_uses_same_best_effort_disposal_after_read_only_verification(service, monkeypatch):
    from sentinel.feed import readiness
    monkeypatch.setattr(runtime, "classify", lambda *a, **kw: {
        "status": "VERIFIED_UNCHANGED", "result": service.result,
        "_readiness_snapshot": object(), "inventory_sha256": "same-inventory"})
    monkeypatch.setattr(readiness, "save_snapshot", lambda *a: service.events.append("readiness"))
    monkeypatch.setattr(runtime, "_refresh_unchanged_health", lambda *a: service.events.append("health"))
    assert invoke(service) is service.result
    assert service.events == ["readiness", "health", "cleanup"]


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
