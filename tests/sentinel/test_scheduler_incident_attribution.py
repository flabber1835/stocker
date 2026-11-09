"""Exact scheduler evidence survives immutable leadership notification episodes."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import inspect
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import alert_service, supervisor_io
from sentinel.automation import outbox
from sentinel.automation.health import AutomationHealth, SchedulerDiagnostic
from sentinel.feed import store
from tests.sentinel.test_automation_outbox import conn, pg  # noqa: F401


CANARY = "private-scheduler-canary-password"
SAMPLED = datetime(2026, 11, 8, 1, 46, 39, tzinfo=timezone.utc)
HOLDER = "automation-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def diagnostic(**changes):
    values = dict(
        policy_state="SCHEDULER_STALLED", predicate="INSTANCE_HEARTBEAT_STALE",
        sampled_at=SAMPLED, control_generation=7, fence=13, holder=HOLDER,
        holder_present=True, holder_matches=True, leader_active=True,
        service_heartbeat_fresh=False,
        lease_heartbeat_at=SAMPLED - timedelta(seconds=10),
        lease_expires_at=SAMPLED + timedelta(seconds=2),
        instance_state="WAITING",
        instance_heartbeat_at=SAMPLED - timedelta(seconds=13),
        heartbeat_age_seconds=13.0, heartbeat_window_seconds=12.0,
        callback_started_at=None, callback_deadline_at=None,
        callback_current=False, scheduler_overdue=False, read_elapsed_seconds=.25,
    )
    values.update(changes)
    return SchedulerDiagnostic(**values)


def red(fact=None):
    fact = fact or diagnostic()
    return AutomationHealth(
        healthy=True, installed=True, operational_ready=False,
        enabled=True, kill_switch_engaged=False,
        policy_state=fact.policy_state, control_generation=fact.control_generation,
        leader_holder=fact.holder, fencing_token=fact.fence,
        leader_active=fact.leader_active,
        leader_heartbeat_at=fact.lease_heartbeat_at,
        leader_expires_at=fact.lease_expires_at,
        database_now=fact.sampled_at,
        scheduler_diagnostic=fact, reason=CANARY,
    )


@contextmanager
def pipe_stderr(monkeypatch):
    reader, writer = os.pipe()
    os.set_blocking(reader, False)
    try:
        with monkeypatch.context() as patches:
            patches.setattr(sys, "stderr", SimpleNamespace(fileno=lambda: writer))
            yield reader, writer
    finally:
        os.close(reader)
        os.close(writer)


def records(reader):
    try:
        raw = os.read(reader, 65536)
    except BlockingIOError:
        return []
    return [json.loads(line) for line in raw.splitlines()]


def prohibit_fallback(monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("diagnostics must not fork a fallback logger")
    monkeypatch.setattr(supervisor_io, "run", forbidden)
    return calls


def test_first_negative_preserves_original_closed_facts_and_emits_once(monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    first = red()
    calls = prohibit_fallback(monkeypatch)
    with pipe_stderr(monkeypatch) as (reader, writer):
        assert state.observe(first)
        later = red(diagnostic(sampled_at=SAMPLED + timedelta(seconds=1),
                               heartbeat_age_seconds=14.0))
        assert not state.observe(later)
        observed = records(reader)
        assert len(observed) == 1
        record = observed[0]
        assert record["schema"] == "sentinel.scheduler-incident/1"
        assert record["diagnostic"] == first.scheduler_diagnostic.model_dump(
            mode="json", by_alias=True)
        assert record["pid"] == os.getpid()
        assert CANARY not in json.dumps(record)
        assert len(json.dumps(record).encode()) + 1 <= os.fpathconf(writer, "PC_PIPE_BUF")
    assert calls == []
    assert len(vars(state)) == 1 and len(state._last_negative) == 4


@pytest.mark.parametrize("change", [
    {"predicate": "INSTANCE_HEARTBEAT_MISSING", "instance_heartbeat_at": None,
     "heartbeat_age_seconds": None},
    {"holder": "automation-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    {"fence": 14}, {"control_generation": 8},
])
def test_predicate_or_exact_leader_change_emits_without_prior_recovery(monkeypatch, change):
    state = alert_service._SchedulerIncidentDiagnostics()
    with pipe_stderr(monkeypatch) as (reader, _):
        assert state.observe(red())
        changed = red(diagnostic(**change))
        assert state.observe(changed)
        assert not state.observe(changed)
        assert len(records(reader)) == 2


def test_unknown_observation_retains_key_and_proven_fresh_pulse_rearms(monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    with pipe_stderr(monkeypatch) as (reader, _):
        assert state.observe(red())
        unknown = red().model_copy(update={
            "healthy": False, "policy_state": "NOT_INSTALLED",
            "scheduler_diagnostic": None,
        })
        assert not state.observe(unknown)
        assert not state.observe(red())
        fresh = red().model_copy(update={
            "policy_state": "LEADER_ACTIVE", "scheduler_diagnostic": None,
            "leader_active": True, "service_heartbeat_fresh": True,
        })
        assert not state.observe(fresh)
        assert state.observe(red())
        assert len(records(reader)) == 2


@pytest.mark.parametrize("bad", [
    {"raw_sql": CANARY}, {"predicate": CANARY},
    {"heartbeat_age_seconds": float("nan")},
    {"instance_state": "WAITING " + CANARY},
])
def test_invalid_or_extra_metadata_cannot_leak_into_record(monkeypatch, bad):
    value = diagnostic().model_dump(mode="python", by_alias=True)
    value.update(bad)
    malformed = SimpleNamespace(model_dump=lambda **kwargs: value)
    observed = red().model_copy(update={"scheduler_diagnostic": malformed})
    with pipe_stderr(monkeypatch) as (reader, _):
        assert not alert_service._SchedulerIncidentDiagnostics().observe(observed)
        assert records(reader) == []


def assert_invalid_metadata_cannot_rearm(monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    malformed = SimpleNamespace(model_dump=lambda **kwargs: {"raw_sql": CANARY})
    invalid = red().model_copy(update={
        "scheduler_diagnostic": malformed, "leader_active": True,
        "service_heartbeat_fresh": True,
    })
    with pipe_stderr(monkeypatch) as (reader, _):
        assert state.observe(red())
        assert not state.observe(invalid)
        assert not state.observe(red()), "invalid metadata cannot prove recovery"
        assert len(records(reader)) == 1


def test_invalid_metadata_cannot_rearm_with_executed_falsifier(monkeypatch):
    assert_invalid_metadata_cannot_rearm(monkeypatch)
    source = textwrap.dedent(inspect.getsource(alert_service._SchedulerIncidentDiagnostics.observe))
    guard = 'getattr(health, "scheduler_diagnostic", None) is None'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, "True"), "invalid-metadata-recovery-falsifier", "exec"),
         alert_service.__dict__, namespace)
    monkeypatch.setattr(alert_service._SchedulerIncidentDiagnostics, "observe", namespace["observe"])
    with pytest.raises(AssertionError, match="invalid metadata cannot prove recovery"):
        assert_invalid_metadata_cannot_rearm(monkeypatch)


def test_full_pipe_consumes_one_attempt_without_fallback(monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    calls = prohibit_fallback(monkeypatch)
    with pipe_stderr(monkeypatch) as (reader, writer):
        os.set_blocking(writer, False)
        while True:
            try:
                os.write(writer, b"x" * 4096)
            except BlockingIOError:
                break
        assert not state.observe(red())
        while True:
            try:
                os.read(reader, 65536)
            except BlockingIOError:
                break
        assert not state.observe(red())
        assert records(reader) == []
        assert state.observe(red(diagnostic(fence=14)))
        assert len(records(reader)) == 1
    assert calls == []


def test_nonpipe_stderr_never_falls_back(monkeypatch, tmp_path):
    calls = prohibit_fallback(monkeypatch)
    with (tmp_path / "stderr").open("w") as sink:
        monkeypatch.setattr(sys, "stderr", sink)
        assert not alert_service._SchedulerIncidentDiagnostics().observe(red())
    assert calls == []
    assert (tmp_path / "stderr").read_bytes() == b""


class Connection:
    def execute(self, *args):
        return self
    def rollback(self):
        pass


def new_alert(monkeypatch, health):
    monkeypatch.setattr(alert_service, "_health_cursor", lambda _: (None, 0, None))
    monkeypatch.setattr(outbox, "enqueue", lambda conn, **kwargs: SimpleNamespace(**kwargs))
    return alert_service._enqueue_health_incident(Connection(), health=health, max_attempts=8)


def test_genuinely_new_occurrence_attaches_same_closed_fact(monkeypatch):
    observed = red()
    alert = new_alert(monkeypatch, observed)
    assert alert.idempotency_key == "automation-health-occurrence:1"
    assert alert.payload["scheduler_diagnostic"] == observed.scheduler_diagnostic.model_dump(
        mode="json", by_alias=True)
    assert CANARY not in repr(alert.payload)


def test_removed_payload_attachment_has_executed_falsifier(monkeypatch):
    test_genuinely_new_occurrence_attaches_same_closed_fact(monkeypatch)
    monkeypatch.setattr(alert_service, "_scheduler_diagnostic", lambda _: None)
    with pytest.raises(KeyError, match="scheduler_diagnostic"):
        test_genuinely_new_occurrence_attaches_same_closed_fact(monkeypatch)


def assert_before_coalescing(monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    with pipe_stderr(monkeypatch) as (reader, _):
        def existing_episode(*args, **kwargs):
            assert len(records(reader)) == 1, "coalescing erased negative pulse evidence"
            return "original immutable alert"
        monkeypatch.setattr(alert_service, "_enqueue_health_incident", existing_episode)
        assert alert_service._observe_health(
            Connection(), health=red(), max_attempts=8,
            scheduler_diagnostics=state) == "original immutable alert"


def test_negative_fact_precedes_coalescing_with_executed_falsifier(monkeypatch):
    assert_before_coalescing(monkeypatch)
    monkeypatch.setattr(alert_service._SchedulerIncidentDiagnostics, "observe", lambda *_: False)
    with pytest.raises(AssertionError, match="coalescing erased"):
        assert_before_coalescing(monkeypatch)


def test_same_leadership_episode_logs_changed_predicate_without_payload_rewrite(
        conn, pg, monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    with pipe_stderr(monkeypatch) as (reader, _):
        first = alert_service._observe_health(
            conn, health=red(), max_attempts=8, scheduler_diagnostics=state)
        original_payload = dict(first.payload)
        changed = red(diagnostic(predicate="INSTANCE_HEARTBEAT_MISSING",
                                 instance_heartbeat_at=None, heartbeat_age_seconds=None))
        with store.connect(pg.sync_dsn) as restarted:
            repeated = alert_service._observe_health(
                restarted, health=changed, max_attempts=8, scheduler_diagnostics=state)
            assert repeated.alert_id == first.alert_id
            assert repeated.payload == original_payload
            again = alert_service._observe_health(
                restarted, health=changed, max_attempts=8, scheduler_diagnostics=state)
            assert again == repeated
        observed = records(reader)
        assert [item["diagnostic"]["predicate"] for item in observed] == [
            "INSTANCE_HEARTBEAT_STALE", "INSTANCE_HEARTBEAT_MISSING"]
        assert observed[0]["diagnostic"] == original_payload["scheduler_diagnostic"]
    assert outbox.load_alert(conn, first.alert_id).payload == original_payload
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone() == (1,)
    conn.rollback()


def test_legacy_episode_keeps_original_key_and_payload_when_new_diagnostic_arrives(
        conn, monkeypatch):
    state = alert_service._SchedulerIncidentDiagnostics()
    legacy = red().model_copy(update={"scheduler_diagnostic": None})
    first = alert_service._observe_health(
        conn, health=legacy, max_attempts=8, scheduler_diagnostics=state)
    with pipe_stderr(monkeypatch) as (reader, _):
        repeated = alert_service._observe_health(
            conn, health=red(), max_attempts=8, scheduler_diagnostics=state)
        assert len(records(reader)) == 1
    assert repeated == first
    assert "scheduler_diagnostic" not in repeated.payload
    assert conn.execute("SELECT occurrence FROM sentinel_alert_health_cursor").fetchone() == (1,)
    conn.rollback()
