from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest

from sentinel import automation_recovery, backup_runtime_authority
from sentinel.automation import service as protocol
from sentinel.automation.model import BackupProofBusy, CycleState, ExecutionEntryBackupBusy
from sentinel.backup_guard import BackupProofBusyReason
from sentinel.paper import execution
from sentinel.paper.model import PaperExecutionEntryBackupBusy
from tests.sentinel.test_automation_service import service_for
from tests.sentinel.test_closing_data_notifications import closing_cycle


@pytest.mark.parametrize("case", ["entry", "inside", "manual"])
def test_only_automated_writer_entry_contention_certifies_no_transport(monkeypatch, case):
    class AutomatedGrant:
        pass

    busy = backup_runtime_authority.BackupIntegrityBusy("exact archive append not proved")

    @contextmanager
    def writer(_conn):
        if case != "inside":
            raise busy
        yield

    monkeypatch.setattr(execution, "AutomationExecutionGrant", AutomatedGrant)
    monkeypatch.setattr(execution.journal, "writer_lock", writer)
    grant = object() if case == "manual" else AutomatedGrant()
    expected = PaperExecutionEntryBackupBusy if case == "entry" else type(busy)
    with pytest.raises(expected) as error:
        with execution._execution_writer(object(), grant):
            assert case == "inside"
            raise busy
    if case == "entry":
        assert error.value.__cause__ is busy
    else:
        assert error.value is busy


@pytest.mark.parametrize("case", ["entry", "generic", "in_flight", "new_fence", "expired"])
def test_only_current_proven_unsent_execution_retries_without_recovery(monkeypatch, case):
    cfg, base, permit = closing_cycle()
    cycle = base.model_copy(update={
        "broker": "alpaca",
        "state": CycleState.EXECUTING,
        "last_fence_token": permit.fence_token + (case == "new_fence"),
    })
    service = service_for(cfg)
    service._unattended_recovery = True
    monkeypatch.setattr(protocol, "in_flight_commands",
        lambda _conn, binding: ("possible broker order",) if case == "in_flight" else ())
    changes = {}

    def transition(_conn, *, permit, cycle_id, to_state, **values):
        assert cycle_id == cycle.cycle_id
        changes.update(values)
        return cycle.model_copy(update={"state": to_state, **values})

    monkeypatch.setattr(protocol.store, "transition_cycle", transition)
    failure = BackupProofBusy if case == "generic" else ExecutionEntryBackupBusy
    now = cycle.execute_at if case != "expired" else cycle.execution_close_at
    result = service._handle_callback_failure(
        object(), now=now, cycle=cycle, permit=permit, phase="EXECUTE",
        exc=failure("busy", reason=BackupProofBusyReason.COVERAGE_CHANGED))
    assert result.cycle.state is (
        CycleState.RETRY_WAIT if case == "entry" else CycleState.RECONCILING)
    assert changes["diagnostic"].get("execution_entry_transport_unstarted") is (
        True if case == "entry" else None)
    assert changes["diagnostic"].get("original_execution_deadline_at") == (
        service._latest_new_execution_at(cycle).isoformat() if case == "entry" else None)
    assert now < changes["next_wake_at"] <= now + timedelta(seconds=30)


def test_consecutive_unsent_entry_failures_keep_their_busy_attempt_count():
    cfg, cycle, _ = closing_cycle()
    service = service_for(cfg)
    failure = ExecutionEntryBackupBusy("busy", reason=BackupProofBusyReason.COVERAGE_CHANGED)
    _, first = service._failure_diagnostic(
        cycle=cycle, phase="EXECUTE", exc=failure, now=cycle.execute_at)
    _, second = service._failure_diagnostic(
        cycle=cycle.model_copy(update={"diagnostic": first}), phase="EXECUTE",
        exc=failure, now=cycle.execute_at + timedelta(seconds=10))
    assert first["backup_busy_attempt_count"] == 1
    assert second["backup_busy_attempt_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["paper_admission", "live_admission", "clock", "gateway"])
async def test_production_execute_preserves_exact_origin_of_backup_contention(monkeypatch, phase):
    runtime = object.__new__(automation_recovery.ProductionAutomation)
    runtime._live_run_enabled = phase == "live_admission"
    context = SimpleNamespace(cycle=SimpleNamespace(broker="alpaca-live" if runtime._live_run_enabled else "alpaca"))
    busy = BackupProofBusy("archive changed", reason=BackupProofBusyReason.COVERAGE_CHANGED)
    stages = []

    def admission(operation):
        stages.append("admission")
        if phase.endswith("admission"):
            raise busy

    async def clock(_context):
        stages.append("clock")
        if phase == "clock":
            raise busy

    async def gateway(_self, _context):
        stages.append("gateway")
        raise busy

    monkeypatch.setattr(runtime, "_require_backup_for_new_mutation", admission)
    monkeypatch.setattr(runtime, "_require_external_execution_clock", clock)
    monkeypatch.setattr(automation_recovery.base.ProductionAutomation, "execute", gateway)
    with pytest.raises(BackupProofBusy) as error:
        await runtime.execute(context)
    if phase == "paper_admission":
        assert stages == ["admission"]
        assert type(error.value) is ExecutionEntryBackupBusy
        assert error.value.reason == busy.reason and error.value.__cause__ is busy
    else:
        assert error.value is busy
