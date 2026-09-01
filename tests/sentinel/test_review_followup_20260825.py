"""Falsifiers for the 2026-08-25 post-merge review remediations."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sentinel import alert_service, automation_supervisor, shadow_supervisor
from sentinel.feed import sharadar, source_authority
from sentinel.feed.source_authority import fetch as source_fetch


def _sep(*, lastupdated="2026-08-05"):
    return {
        "ticker": "AAA", "date": "2026-08-04", "open": 10.0,
        "close": 10.0, "closeunadj": 10.0, "volume": 1000.0,
        "lastupdated": lastupdated,
    }


def _ticker(permaticker, ticker, category):
    return {
        "table": "SEP", "permaticker": str(permaticker), "ticker": ticker,
        "category": category, "firstpricedate": "2026-08-04",
        "lastpricedate": "2026-08-04",
    }


def test_cdc_request_shape_drift_refuses_before_fetch():
    called = False

    def fetch(table, params=None, **kwargs):
        nonlocal called
        called = True
        return iter([_sep()])

    envelope = source_authority.SepUpdateEnvelope.interval(
        "2026-08-01", "2026-08-05", context="test CDC")
    guarded = source_authority.CanonicalSourceFetch(
        fetch, sep_update_envelope=envelope)

    with pytest.raises(source_authority.SourceAuthorityRefused,
                       match="request envelope refused"):
        list(guarded(sharadar.SEP, {
            "lastupdated.gte": "2026-08-02",
            "lastupdated.lte": "2026-08-05",
        }))
    assert called is False


def test_cdc_replay_is_available_only_after_two_exact_update_observations():
    calls = []

    def fetch(table, params=None, **kwargs):
        calls.append(dict(params or {}))
        return iter([_sep()])

    envelope = source_authority.SepUpdateEnvelope.interval(
        "2026-08-01", "2026-08-05", context="test CDC")
    routed = source_fetch._CdcThenReplayFetch(fetch, envelope)
    date_request = {"date.gte": "2026-08-03", "date.lte": "2026-08-04"}

    with pytest.raises(source_authority.SourceAuthorityRefused,
                       match="request envelope refused"):
        list(routed(sharadar.SEP, date_request))
    assert calls == []

    update_request = {
        "lastupdated.gte": "2026-08-01",
        "lastupdated.lte": "2026-08-05",
    }
    assert list(routed(sharadar.SEP, update_request))
    assert list(routed(sharadar.SEP, update_request))
    assert list(routed(sharadar.SEP, date_request))
    assert calls == [update_request, update_request, date_request]


def test_successful_seed_coverage_returns_positive_category_evidence(monkeypatch):
    common = "Domestic Common Stock"
    warrant = "Domestic Warrant"
    projection = source_authority.SeedListingProjection([
        _ticker("1", "AAA", common),
        _ticker("2", "AAAW", warrant),
    ], source_digest="a" * 64)
    monkeypatch.setattr(
        source_authority.coverage.calendar, "sessions_in_range",
        lambda start, end: ["2026-08-04"])

    resolver = lambda ticker, session: {"AAA": "1", "AAAW": "2"}.get(ticker)
    coverage = source_authority.SeedCoverageAccumulator(
        projection, resolver, exceptions={})
    try:
        coverage.add(_sep())
        coverage.add(dict(_sep(), ticker="AAAW"))
        evidence = coverage.require_complete(
            date_from="2026-08-04", date_to="2026-08-04")
    finally:
        coverage.close()

    assert evidence["schema"] == "sentinel.seed-source-coverage/1"
    assert evidence["expected_eligible_total"] == 1
    assert evidence["received_eligible_total"] == 1
    assert evidence["missing_eligible_total"] == 0
    assert evidence["expected_ineligible_by_category"] == {warrant: 1}
    assert evidence["received_ineligible_by_category"] == {warrant: 1}
    assert evidence["missing_ineligible_by_category"] == {}


def test_shadow_health_requires_frontier_health_and_respects_latch(
        monkeypatch, tmp_path):
    heartbeat = tmp_path / "heartbeat"
    latch = tmp_path / "latch"
    heartbeat.touch()
    monkeypatch.setattr(shadow_supervisor, "HEARTBEAT_FILE", heartbeat)
    monkeypatch.setattr(shadow_supervisor, "LATCH_FILE", latch)
    monkeypatch.setattr(shadow_supervisor, "service_health", lambda config: {"ok": True})
    assert shadow_supervisor._health(30.0, config=object()) == 0

    monkeypatch.setattr(
        shadow_supervisor, "service_health",
        lambda config: (_ for _ in ()).throw(RuntimeError("frontier stale")))
    assert shadow_supervisor._health(30.0, config=object()) == 1

    monkeypatch.setattr(shadow_supervisor, "service_health", lambda config: {"ok": True})
    latch.write_text('{"reason":"terminal refusal"}', encoding="utf-8")
    assert shadow_supervisor._health(30.0, config=object()) == 1


def test_shadow_retry_threshold_latches_instead_of_exit_restart_loop(
        monkeypatch, tmp_path):
    heartbeat = tmp_path / "heartbeat"
    latch = tmp_path / "latch"
    monkeypatch.setattr(shadow_supervisor, "HEARTBEAT_FILE", heartbeat)
    monkeypatch.setattr(shadow_supervisor, "LATCH_FILE", latch)
    monkeypatch.setenv("SENTINEL_SHADOW_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "30")
    monkeypatch.setattr(
        shadow_supervisor.ShadowServiceConfig, "from_env",
        classmethod(lambda cls: type("C", (), {"poll_seconds": 0})()))

    class Child:
        def poll(self):
            return shadow_supervisor.EXIT_RETRY

    monkeypatch.setattr(shadow_supervisor.subprocess, "Popen", lambda *a, **k: Child())
    monkeypatch.setattr(shadow_supervisor, "_latched_wait", lambda stopping: 91)
    assert shadow_supervisor.run() == 91
    assert latch.exists()
    assert "bounded semantic retry threshold" in latch.read_text(encoding="utf-8")


def test_callback_deadline_remains_bounded_during_database_loss():
    watch = automation_supervisor.CallbackWatch(
        state="EXECUTE_CALLBACK", observed_at=100.0)
    assert not automation_supervisor._callback_deadline_expired_during_database_loss(
        watch, now_monotonic=109.0, database_unreadable_since=105.0,
        deadline_seconds=10.0)
    assert automation_supervisor._callback_deadline_expired_during_database_loss(
        watch, now_monotonic=111.0, database_unreadable_since=105.0,
        deadline_seconds=10.0)

    unseen = automation_supervisor.CallbackWatch()
    assert automation_supervisor._callback_deadline_expired_during_database_loss(
        unseen, now_monotonic=116.0, database_unreadable_since=105.0,
        deadline_seconds=10.0)


def test_webhook_transport_failure_has_distinct_type(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(alert_service.httpx, "Client", Client)
    adapter = alert_service.WebhookAlertAdapter("https://alerts.example.test")
    with pytest.raises(alert_service.AlertTransportFailure,
                       match="transport failed"):
        adapter._post({"x": 1}, "idempotency-key")


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    ((401, False), (403, False), (404, False), (410, False),
     (408, True), (425, True), (429, True), (503, True)))
def test_webhook_http_failure_classification(
        monkeypatch, status_code, retryable):
    class Response:
        pass

    Response.status_code = status_code

    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, *args, **kwargs): return Response()

    monkeypatch.setattr(alert_service.httpx, "Client", Client)
    adapter = alert_service.WebhookAlertAdapter(
        "https://alerts.example.test")
    with pytest.raises(alert_service.AlertTransportFailure) as caught:
        adapter._post({"x": 1}, "idempotency-key")
    assert caught.value.retryable is retryable
