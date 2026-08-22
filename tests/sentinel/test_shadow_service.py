from __future__ import annotations

import ast
from decimal import Decimal
from datetime import datetime, timezone
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from sentinel import shadow_service


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def _env(**updates):
    value = {
        "SENTINEL_DATABASE_URL": "postgresql://private",
        "SENTINEL_SHADOW_OBSERVATION_ENABLED": "1",
        "SENTINEL_SHADOW_OBSERVATION_ID": "year-end",
        "SENTINEL_SHADOW_STARTING_CASH": "100000.00",
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": "a" * 64,
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": "c" * 64,
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": "d" * 64,
        "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": "b" * 64,
        "SENTINEL_REVIEWED_DEPLOYMENT_MODE": "dual",
    }
    value.update(updates)
    return value


@pytest.mark.parametrize("name", [
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SENTINEL_PAPER_ACCOUNT_ID",
])
def test_shadow_service_refuses_any_broker_authority_environment(name):
    with pytest.raises(shadow_service.ShadowServiceRefused,
                       match="broker authority"):
        shadow_service.ShadowServiceConfig.from_env(
            _env(**{name: "must-not-enter-shadow"}))


def test_shadow_service_config_is_explicit_and_normalized():
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    assert cfg.observation_id == "year-end"
    assert cfg.starting_cash == Decimal("100000.00")
    assert cfg.poll_seconds == 300
    with pytest.raises(shadow_service.ShadowServiceRefused,
                       match="not explicitly enabled"):
        shadow_service.ShadowServiceConfig.from_env(
            _env(SENTINEL_SHADOW_OBSERVATION_ENABLED="0"))
    with pytest.raises(shadow_service.ShadowServiceRefused,
                       match="timing policy differs"):
        shadow_service.ShadowServiceConfig.from_env(_env(
            SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY="close-plus-one-second"))


@pytest.mark.parametrize("name", [
    "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
    "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
    "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
    "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256",
])
def test_shadow_service_requires_every_reviewed_digest(name):
    with pytest.raises(shadow_service.ShadowServiceRefused, match=name):
        shadow_service.ShadowServiceConfig.from_env(_env(**{name: ""}))


@pytest.mark.parametrize("mode", ["", "paper", "unexpected"])
def test_shadow_service_requires_reviewed_shadow_capable_mode(mode):
    with pytest.raises(shadow_service.ShadowServiceRefused,
                       match="REVIEWED_DEPLOYMENT_MODE"):
        shadow_service.ShadowServiceConfig.from_env(
            _env(SENTINEL_REVIEWED_DEPLOYMENT_MODE=mode))


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql):
        return None


class _Conn:
    def cursor(self):
        return _Cursor()


def test_lineage_preflight_accepts_only_truly_empty_not_started(monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service.schema, "require_runtime_schema",
                        lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.shadow_runtime, "classify_shadow_lineage",
        lambda *_args, **_kwargs: {"status": "NOT_STARTED"})
    result = shadow_service._preflight(_Conn(), cfg)
    assert result == {
        "schema": shadow_service.PREFLIGHT_SCHEMA,
        "mode": "BROKER_FREE_SHADOW",
        "status": "NOT_STARTED",
        "broker_mutations_authorized": False,
    }

    monkeypatch.setattr(
        shadow_service.shadow_runtime, "classify_shadow_lineage",
        lambda *_args, **_kwargs: {
            "status": "RECOVERY_REQUIRED",
            "recovery_kind": "TRAILING_CANDIDATE",
        })
    with pytest.raises(shadow_service.ShadowServiceRefused,
                       match="classification is malformed"):
        shadow_service._preflight(_Conn(), cfg)


def test_public_preflight_never_marks_retrospective_fresh_start_healthy(
        monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())

    class Connection:
        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        shadow_service.feed_store, "connect", lambda _url: Connection())
    monkeypatch.setattr(shadow_service, "_preflight", lambda *_args, **_kwargs: {
        "schema": shadow_service.PREFLIGHT_SCHEMA,
        "mode": "BROKER_FREE_SHADOW",
        "status": "NOT_STARTED",
        "broker_mutations_authorized": False,
    })
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-20")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session", lambda _session: "2026-08-21")
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)))

    with pytest.raises(shadow_service.ShadowServiceWaiting,
                       match="next freshly completed close"):
        shadow_service.preflight(
            cfg, now=datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc))


def test_lineage_preflight_requires_verified_shadow_go(monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service.schema, "require_runtime_schema",
                        lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.shadow_runtime, "classify_shadow_lineage",
        lambda *_args, **_kwargs: {
            "status": "VERIFIED",
            "result": SimpleNamespace(to_dict=lambda: {
                "shadow_verdict": "SHADOW_GO", "verification": "VERIFIED",
                "session": "2026-08-20",
            }),
        })
    result = shadow_service._preflight(_Conn(), cfg)
    assert result["status"] == "VERIFIED"
    assert result["broker_mutations_authorized"] is False


def test_structural_preflight_names_attested_session_without_claiming_go(
        monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service.schema, "require_runtime_schema",
                        lambda _conn: None)
    calls = []

    def classify(*_args, **kwargs):
        calls.append(kwargs)
        return {"status": "ATTESTED_STRUCTURAL",
                "latest_session": "2026-08-20"}

    monkeypatch.setattr(
        shadow_service.shadow_runtime, "classify_shadow_lineage", classify)

    result = shadow_service._preflight(  # noqa: SLF001
        _Conn(), cfg, allow_stale_frontier=True)

    assert result["status"] == "ATTESTED_STRUCTURAL"
    assert result["latest_session"] == "2026-08-20"
    assert "lineage" not in result
    assert calls[0]["structural_only"] is True


@pytest.mark.parametrize("kind", ["GENESIS_ONLY", "TRAILING_CANDIDATE"])
def test_lineage_preflight_surfaces_only_explicit_preopen_recovery(
        monkeypatch, kind):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service.schema, "require_runtime_schema",
                        lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.shadow_runtime, "classify_shadow_lineage",
        lambda *_args, **_kwargs: {
            "status": "RECOVERY_REQUIRED",
            "recovery_kind": kind,
            "recovery_session": "2026-08-20",
            "execution_session": "2026-08-21",
            "recovery_cutoff_at": "2026-08-21T13:30:00Z",
        })

    result = shadow_service._preflight(_Conn(), cfg)

    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["recovery_kind"] == kind
    assert result["recovery_session"] == "2026-08-20"
    assert result["broker_mutations_authorized"] is False


def test_new_lineage_waits_during_market_hours_for_a_fresh_close(monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service, "preflight", lambda _cfg, **_kwargs: {
        "status": "NOT_STARTED"})
    monkeypatch.setattr(
        shadow_service.feed_store, "connect",
        lambda _url: pytest.fail("WAITING path must not touch PostgreSQL"))
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-20")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session",
        lambda _session: "2026-08-21")
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)))

    with pytest.raises(shadow_service.ShadowServiceWaiting,
                       match="next freshly completed close"):
        shadow_service.advance_once(
            cfg, now=datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc))


def test_new_lineage_may_use_a_close_whose_following_open_is_future(monkeypatch):
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-21")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session",
        lambda _session: "2026-08-24")
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 24, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)))
    target = shadow_service._causal_target(
        preflight_status="NOT_STARTED",
        now=datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc))
    assert target == "2026-08-21"


def test_existing_verified_lineage_does_not_use_new_lineage_wait_rule(monkeypatch):
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-20")
    target = shadow_service._causal_target(
        preflight_status="VERIFIED",
        now=datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc))
    assert target == "2026-08-20"


def test_service_health_keeps_exact_daily_gap_healthy_before_source_final(
        monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service, "preflight", lambda *_args, **_kwargs: {
        "status": "ATTESTED_STRUCTURAL", "latest_session": "2026-08-20",
        "broker_mutations_authorized": False})
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-21")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session",
        lambda session: ("2026-08-21" if str(session) == "2026-08-20"
                         else "2026-08-24"))
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 24, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)))

    result = shadow_service.service_health(
        cfg, now=datetime(2026, 8, 21, 20, 1, tzinfo=timezone.utc))

    assert result["service_health"] == "HEALTHY_WAITING"
    assert result["target_session"] == "2026-08-21"


def test_day_two_structural_lineage_ingests_then_fully_advances(monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service, "preflight", lambda *_args, **_kwargs: {
        "status": "ATTESTED_STRUCTURAL", "latest_session": "2026-08-20"})
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-21")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session",
        lambda session: ("2026-08-21" if str(session) == "2026-08-20"
                         else "2026-08-24"))
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 24, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)))

    class Connection:
        def rollback(self):
            return None

        def close(self):
            return None

    conn = Connection()
    visible = {"session": "2026-08-20"}
    monkeypatch.setattr(
        shadow_service.feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(
        shadow_service.feed_store, "require_feed_schema", lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.feed_store, "latest_visible_session",
        lambda _conn: visible["session"])
    ingests = []

    def daily(_conn, *, today):
        ingests.append(today)
        visible["session"] = today

    monkeypatch.setattr(shadow_service.ingest, "daily", daily)
    monkeypatch.setattr(
        shadow_service.readiness, "check_readiness",
        lambda _conn: SimpleNamespace(ready=True, failures=[]))
    monkeypatch.setattr(
        shadow_service.shadow_runtime, "advance_ready_shadow",
        lambda *_args, **kwargs: SimpleNamespace(to_dict=lambda: {
            "session": kwargs["through"], "shadow_verdict": "SHADOW_GO",
            "verification": "VERIFIED", "appended": True}))

    result = shadow_service.advance_once(
        cfg, now=datetime(2026, 8, 22, 3, 46, tzinfo=timezone.utc))

    assert ingests == ["2026-08-21"]
    assert result["session"] == "2026-08-21"
    assert result["verification"] == "VERIFIED"


def test_verified_same_session_is_a_retained_noop(monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    lineage = {
        "session": "2026-08-20",
        "shadow_verdict": "SHADOW_GO",
        "verification": "VERIFIED",
        "record_sha256": "a" * 64,
    }
    monkeypatch.setattr(shadow_service, "preflight", lambda *_args, **_kwargs: {
        "status": "VERIFIED", "lineage": lineage})
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-20")
    monkeypatch.setattr(
        shadow_service.feed_store, "connect",
        lambda _url: pytest.fail("same-session status must not append/rewrite"))

    result = shadow_service.advance_once(
        cfg, now=datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc))

    assert result == lineage


def test_verified_lineage_gap_refuses_before_post_cutoff_ingest(monkeypatch):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service, "preflight", lambda *_args, **_kwargs: {
        "status": "VERIFIED",
        "lineage": {
            "session": "2026-08-19",
            "shadow_verdict": "SHADOW_GO",
            "verification": "VERIFIED",
        },
    })
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-20")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session",
        lambda session: ("2026-08-20" if str(session) == "2026-08-19"
                         else "2026-08-21"))
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)))
    monkeypatch.setattr(
        shadow_service.feed_store, "connect",
        lambda _url: pytest.fail("missed cutoff must refuse before ingest/DB"))

    with pytest.raises(shadow_service.ShadowServiceRefused,
                       match="missed the following-open cutoff"):
        shadow_service.advance_once(
            cfg, now=datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize("kind", ["GENESIS_ONLY", "TRAILING_CANDIDATE"])
def test_restart_routes_exact_recovery_session_without_ingest(monkeypatch, kind):
    cfg = shadow_service.ShadowServiceConfig.from_env(_env())
    monkeypatch.setattr(shadow_service, "preflight", lambda *_args, **_kwargs: {
        "status": "RECOVERY_REQUIRED",
        "recovery_kind": kind,
        "recovery_session": "2026-08-20",
        "execution_session": "2026-08-21",
        "recovery_cutoff_at": "2026-08-21T13:30:00Z",
    })

    class Connection:
        def rollback(self):
            return None

        def close(self):
            return None

    conn = Connection()
    monkeypatch.setattr(
        shadow_service.feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(
        shadow_service.feed_store, "require_feed_schema", lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(
        shadow_service.ingest, "daily",
        lambda *_args, **_kwargs: pytest.fail(
            "recovery must not move the publication"))
    monkeypatch.setattr(
        shadow_service.readiness, "check_readiness",
        lambda *_args, **_kwargs: pytest.fail(
            "runtime recovery owns readiness under its pin"))
    calls = []

    def recover(actual, *, through, observation_id, starting_cash):
        calls.append((actual, through, observation_id, starting_cash))
        return SimpleNamespace(to_dict=lambda: {
            "session": through,
            "shadow_verdict": "SHADOW_GO",
            "verification": "VERIFIED",
            "appended": False,
        })

    monkeypatch.setattr(
        shadow_service.shadow_runtime, "advance_ready_shadow", recover)

    result = shadow_service.advance_once(cfg)

    assert result["session"] == "2026-08-20"
    assert result["verification"] == "VERIFIED"
    assert calls == [(conn, "2026-08-20", "year-end", Decimal("100000.00"))]


@pytest.mark.parametrize(("session", "expected_utc"), [
    ("2026-08-21", "2026-08-22T03:45:00+00:00"),  # regular EDT
    ("2026-11-27", "2026-11-28T04:45:00+00:00"),  # half-day EST
    ("2026-03-06", "2026-03-07T04:45:00+00:00"),  # before DST
    ("2026-03-09", "2026-03-10T03:45:00+00:00"),  # after DST
])
def test_reviewed_sharadar_not_before_is_fixed_local_2345(
        session, expected_utc):
    assert shadow_service.shadow_runtime.publication_not_before(
        session).isoformat() == expected_utc


def test_visible_close_is_never_trusted_before_local_2345(monkeypatch):
    eastern = ZoneInfo("America/New_York")
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-11-27")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session", lambda _session: "2026-11-30")
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc),
            datetime(2026, 11, 30, 21, 0, tzinfo=timezone.utc)))

    with pytest.raises(shadow_service.ShadowServiceWaiting,
                       match="reviewed Sharadar publication"):
        shadow_service._causal_target(
            preflight_status="NOT_STARTED",
            now=datetime(2026, 11, 27, 23, 44, tzinfo=eastern))
    assert shadow_service._causal_target(
        preflight_status="NOT_STARTED",
        now=datetime(2026, 11, 27, 23, 45, tzinfo=eastern)) == "2026-11-27"


def test_weekend_resume_uses_friday_only_after_friday_2345(monkeypatch):
    eastern = ZoneInfo("America/New_York")
    monkeypatch.setattr(
        shadow_service.calendar, "latest_closed_session",
        lambda _now: "2026-08-21")
    monkeypatch.setattr(
        shadow_service.calendar, "next_session", lambda _session: "2026-08-24")
    monkeypatch.setattr(
        shadow_service.calendar, "session_window",
        lambda _session: (
            datetime(2026, 8, 24, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)))

    assert shadow_service._causal_target(
        preflight_status="NOT_STARTED",
        now=datetime(2026, 8, 22, 12, 0, tzinfo=eastern)) == "2026-08-21"


def test_shadow_module_and_compose_service_have_no_broker_surface():
    source = inspect.getsource(shadow_service)
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "sentinel.execution" not in imported
    assert "sentinel.automation_runtime" not in imported
    assert "build_broker" not in imported
    assert "build_execution_broker" not in imported

    compose = (ROOT / "docker-compose.sentinel-automation.yml").read_text(
        encoding="utf-8")
    start = compose.index("  sentinel-shadow:")
    block = compose[start:]
    assert 'profiles: ["shadow"]' in block
    assert 'entrypoint: ["python", "-m", "sentinel.shadow_service"]' in block
    assert "ALPACA_API_KEY" not in block
    assert "ALPACA_SECRET_KEY" not in block
    assert "SENTINEL_PAPER_ACCOUNT_ID" not in block
    assert "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256" in block
    assert shadow_service.shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY in block


def test_inactive_shadow_profile_does_not_require_late_review_values():
    compose = (ROOT / "docker-compose.sentinel-automation.yml").read_text(
        encoding="utf-8")
    start = compose.index("  sentinel-shadow:")
    block = compose[start:]
    assert "${SENTINEL_SHADOW_OBSERVATION_ENABLED:-0}" in block
    for name in (
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
            "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
            "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256",
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE"):
        assert "${%s:-}" % name in block
        assert "${%s:?" % name not in block
