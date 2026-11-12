"""The strict proof owner fences writes without inheriting a source retry."""
import inspect
import json
from datetime import timedelta
from textwrap import dedent
from types import SimpleNamespace

import pytest

from sentinel import automation_recovery, automation_runtime, backup_integrity_reuse, backup_retry
from sentinel.automation import service as protocol
from sentinel.automation.model import BackupProofBusy, ClosingDataPending, SoftwareDefect, TickAction
from sentinel.backup_guard import BackupProofBusyReason
from tests.sentinel.test_automation_service import (
    AFTER_WEDNESDAY_CLOSE, config, conn, enable, pg, refresh_result, service_for,
)
from tests.sentinel.test_automation_service_fault_paths import child
from tests.sentinel.test_closing_data_notifications import closing_cycle


@pytest.mark.asyncio
@pytest.mark.parametrize("omit_busy_budget", [False, True])
async def test_busy_retry_owns_its_budget_and_rechecks_the_gate_on_wake(
        conn, monkeypatch, omit_busy_budget):
    cfg = config().model_copy(update={"retry_max_seconds": 900})
    enable(conn, cfg)
    now = AFTER_WEDNESDAY_CLOSE
    attempts = []
    completions = set()

    def refresh(context):
        attempts.append(context.cycle.cycle_id)
        if len(attempts) <= 8:
            raise ClosingDataPending("source wait")
        if len(attempts) <= 10:
            raise BackupProofBusy("strict backup refusal PROOF_OWNER_BUSY",
                                  reason=BackupProofBusyReason.FRONTIER_CHANGED)
        return refresh_result(context)

    service = service_for(cfg, refresh=refresh)
    service.backup_proof_completed = completions.__contains__

    if omit_busy_budget:
        source = dedent(inspect.getsource(protocol.AutomationService._failure_diagnostic))
        guard = "budget_attempt = busy_attempt or pin_attempt or phase_attempt"
        assert source.count(guard) == 1
        namespace = {}
        exec(source.replace(guard, "budget_attempt = pin_attempt or phase_attempt"),
             vars(protocol), namespace)
        monkeypatch.setattr(protocol.AutomationService, "_failure_diagnostic",
                            namespace["_failure_diagnostic"])

    assert (await service.tick(conn, now=now)).action is TickAction.RECOVERED
    for _ in range(8):
        result = await service.tick(conn, now=now)
        now = result.cycle.next_wake_at

    first = await service.tick(conn, now=now)
    if omit_busy_budget:
        assert first.cycle.diagnostic["callback_failure"] == "TRANSIENT_RETRY_EXHAUSTED"
        return
    assert first.action is TickAction.RETRY_SCHEDULED
    assert first.cycle.diagnostic["phase_attempt_count"] == 9
    assert first.cycle.diagnostic["backup_busy_attempt_count"] == 1
    assert first.cycle.diagnostic["backup_busy_reason"] == "FRONTIER_CHANGED"
    assert first.cycle.next_wake_at == now + timedelta(seconds=5)
    assert (await service.tick(conn, now=now + timedelta(seconds=1))).action is TickAction.WAITING

    completions.add(now)
    now += timedelta(seconds=2)
    second = await service.tick(conn, now=now)
    assert second.action is TickAction.RETRY_SCHEDULED
    assert second.cycle.diagnostic["backup_busy_attempt_count"] == 2
    assert second.cycle.next_wake_at == now + timedelta(seconds=10)
    assert second.cycle.plan_id is None
    assert (await service.tick(conn, now=now + timedelta(seconds=1))).action is TickAction.WAITING
    completions.add(now)
    result = await service.tick(conn, now=now + timedelta(seconds=2))
    assert result.action is TickAction.REFRESHED
    assert len(attempts) == 11 and len(set(attempts)) == 1
    assert result.cycle.execution_open_at == first.cycle.execution_open_at


def test_exact_backup_busy_survives_child_protocol_and_rejects_unreviewed_reason(monkeypatch):
    async def callback(_context):
        raise BackupProofBusy("busy", reason=BackupProofBusyReason.FRONTIER_CHANGED)

    payload = child(monkeypatch, callback).payloads[0]
    with pytest.raises(BackupProofBusy) as error:
        protocol._decode_child_callback(payload)
    assert error.value.reason is BackupProofBusyReason.FRONTIER_CHANGED
    assert error.value.failure_domain == "BACKUP"
    envelope = json.loads(payload)
    envelope["backup_busy_reason"] = "not-reviewed"
    with pytest.raises(SoftwareDefect, match="invalid backup busy reason"):
        protocol._decode_child_callback(json.dumps(envelope).encode())


def test_optional_wake_probe_uses_private_read_only_postgres(conn, monkeypatch):
    monkeypatch.setattr(backup_integrity_reuse, "selected", lambda: True)

    def completed(proof_conn, failed_at):
        assert proof_conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        return failed_at == AFTER_WEDNESDAY_CLOSE

    monkeypatch.setattr(backup_retry, "_completed_since", completed)
    assert backup_retry.completed_since(conn.info.dsn, AFTER_WEDNESDAY_CLOSE)
    assert not backup_retry.completed_since(
        conn.info.dsn, AFTER_WEDNESDAY_CLOSE + timedelta(seconds=1))


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["pending", "ready", "unverified", "expired"])
async def test_negative_close_probe_preserves_positive_backup_gate(conn, monkeypatch, condition):
    cfg, cycle, _permit = closing_cycle()
    now = cycle.prepare_at + timedelta(seconds=1)
    if condition == "expired":
        now = cycle.execution_open_at
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: now)
    monkeypatch.setattr(backup_integrity_reuse, "selected", lambda: True)
    monkeypatch.setattr(automation_runtime.feed_store, "require_feed_schema", lambda _conn: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(automation_runtime.journal, "require_observation_integrity", lambda _conn: None)
    worker = object.__new__(automation_recovery.ProductionAutomation)
    worker.automation_config = cfg
    worker.sentinel_config = SimpleNamespace(database_url=conn.info.dsn)
    worker._operational_source_only = worker._dual_run_enabled = True
    calls = []

    def authorized(read_conn, _context, *, operation_scope, record_verdict):
        assert read_conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        assert operation_scope == "REFRESH" and record_verdict is False
        calls.append("authorized-read")
        if condition == "unverified":
            raise ValueError("missing signed evidence")
        return cycle, None

    worker._assert_cycle_authority = authorized
    worker._refresh_inputs = lambda _conn: SimpleNamespace(window_end=str(cycle.decision_session))
    worker._closing_refresh_wait = lambda *_args, **_kwargs: (
        None if condition == "ready" else ClosingDataPending("exact pending close"))
    worker._require_backup_for_new_mutation = lambda _op: calls.append("backup")

    async def positive(_self, _context):
        calls.append("canonical")
        return "ready"

    monkeypatch.setattr(automation_runtime.ProductionAutomation, "refresh", positive)
    context = SimpleNamespace(cycle=cycle, require_active=lambda: None)
    if condition == "pending":
        with pytest.raises(ClosingDataPending):
            await worker.refresh(context)
        assert calls == ["authorized-read"]
    else:
        assert await worker.refresh(context) == "ready"
        expected_probe = [] if condition == "expired" else ["authorized-read"]
        assert calls == [*expected_probe, "backup", "canonical"]
