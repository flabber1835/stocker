from __future__ import annotations

import asyncio
import errno
import json
import multiprocessing
import os
import signal
import socket
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest

from sentinel.automation import service as service_module
from sentinel.automation.model import (
    AutomationConfig,
    CallbackDeadlineExceeded,
    CancellationAuthority,
    DataIntegrityFailure,
    HumanInterventionRequired,
    PermanentOperationalRefusal,
    SoftwareDefect,
    SupervisorIntegrityFailure,
    StaleLeaderRefused,
    TransientInfrastructureFailure,
)
from sentinel.automation.service import AutomationService
from sentinel import automation_runtime
from sentinel import automation_supervisor
from sentinel.execution.certification import (
    AdapterNotCertified,
    require_certified_adapter,
)
from sentinel.empty_account import EmptyAccountRefused, _strict_account
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerExactOrderLookup,
    BrokerInstrument, BrokerObservation, BrokerOrder, Completeness, Side,
    resolved_capability_graph,
)
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, ExecutionBrokerGuard, GuardedExecutionBroker,
    ManualExecutionGrant,
)
from sentinel.execution.reconcile import _exact_lookup_account_or_refuse
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState
from sentinel.feed import sharadar
from sentinel.paper import PaperActivationRefused
from sentinel.paper.inspection import _require_certified_paper_broker


def _callback_envelope(**changes) -> bytes:
    payload = {
        "kind": "error",
        "name": "RuntimeError",
        "module": "builtins",
        "qualname": "RuntimeError",
        "actual_module": "builtins",
        "actual_qualname": "RuntimeError",
        "detail": "callback failed",
        "reviewed": False,
    }
    payload.update(changes)
    return json.dumps(payload).encode("utf-8")


def test_callback_ipc_decoder_covers_every_authority_class() -> None:
    assert service_module._decode_child_callback(  # noqa: SLF001
        b'{"kind":"result","value":{"ok":true}}') == {"ok": True}
    with pytest.raises(SoftwareDefect, match="malformed IPC evidence"):
        service_module._decode_child_callback(b"not-json")  # noqa: SLF001
    with pytest.raises(SystemExit, match="stopped"):
        service_module._decode_child_callback(_callback_envelope(  # noqa: SLF001
            name="SystemExit", qualname="SystemExit", detail="stopped"))
    with pytest.raises(KeyboardInterrupt, match="interrupted"):
        service_module._decode_child_callback(_callback_envelope(  # noqa: SLF001
            name="KeyboardInterrupt", qualname="KeyboardInterrupt",
            detail="interrupted"))
    with pytest.raises(TransientInfrastructureFailure, match="retry"):
        service_module._decode_child_callback(_callback_envelope(  # noqa: SLF001
            name="TransientInfrastructureFailure",
            module=TransientInfrastructureFailure.__module__,
            qualname=TransientInfrastructureFailure.__qualname__,
            detail="retry", reviewed=True))
    with pytest.raises(SoftwareDefect, match="builtins.RuntimeError"):
        service_module._decode_child_callback(_callback_envelope())  # noqa: SLF001


@pytest.mark.asyncio
async def test_background_callback_results_are_always_consumed() -> None:
    cancelled = asyncio.create_task(asyncio.sleep(10))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    service_module._consume_background_result(cancelled)  # noqa: SLF001

    async def fails():
        raise RuntimeError("late failure")

    failed = asyncio.create_task(fails())
    await asyncio.sleep(0)
    service_module._consume_background_result(failed)  # noqa: SLF001


def config(*, deadline: int = 1) -> AutomationConfig:
    return AutomationConfig(
        publication_delay_seconds=0,
        execution_delay_seconds=60,
        lease_seconds=10,
        heartbeat_seconds=1,
        callback_deadline_seconds=deadline,
        retry_base_seconds=1,
        retry_max_seconds=2,
    )


def service(*, deadline: int = 1) -> AutomationService:
    return AutomationService(
        config=config(deadline=deadline), holder_id="review-test",
        refresh=lambda _context: {}, prepare=lambda _context: {},
        recover=lambda _context: {}, execute=lambda _context: {})


class Context:
    def __init__(self) -> None:
        self.cancellation = CancellationAuthority()

    def require_active(self) -> None:
        self.cancellation.require_active()


class Connection:
    def __init__(self, *, close_error: BaseException | None = None) -> None:
        self.close_error = close_error

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error


def _pid_is_executing(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            state = handle.read().split()[2]
    except (FileNotFoundError, IndexError, ProcessLookupError):
        return False
    return state != "Z"


def _worker_with_delayed_callback(marker: str, ready: str, pid_file: str) -> None:
    service_module.store.heartbeat_lease = lambda *_args, **_kwargs: None
    service_module.store.register_instance = lambda *_args, **_kwargs: None

    async def delayed_writer(_context):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with open(pid_file, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        with open(ready, "w", encoding="utf-8") as handle:
            handle.write("ready")
        time.sleep(1.2)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("unsafe")

    async def invoke():
        await service(deadline=5)._invoke(  # noqa: SLF001
            delayed_writer, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=Connection)

    asyncio.run(invoke())


@pytest.fixture
def harmless_heartbeat(monkeypatch):
    monkeypatch.setattr(
        service_module.store, "heartbeat_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service_module.store, "register_instance",
        lambda *_args, **_kwargs: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_boundary", ["sleep", "postgres", "vendor"])
async def test_blocking_sync_work_inside_async_callback_is_process_killed(
        harmless_heartbeat, blocked_boundary) -> None:
    async def blocked(_context):
        assert blocked_boundary in {"sleep", "postgres", "vendor"}
        time.sleep(5)

    started = time.monotonic()
    with pytest.raises(CallbackDeadlineExceeded, match="bounded runtime"):
        await service()._invoke(  # noqa: SLF001
            blocked, Context(), permit=object(), phase="REFRESH",
            heartbeat_conn_factory=Connection)
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_cancelled_child_cannot_attempt_late_durable_write(
        harmless_heartbeat, tmp_path) -> None:
    marker = tmp_path / "late-write"

    async def late_writer(_context):
        time.sleep(2)
        marker.write_text("unsafe", encoding="utf-8")

    with pytest.raises(CallbackDeadlineExceeded):
        await service()._invoke(  # noqa: SLF001
            late_writer, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=Connection)
    await asyncio.sleep(1.2)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_sigterm_ignoring_child_has_no_post_deadline_grace(
        harmless_heartbeat, tmp_path) -> None:
    marker = tmp_path / "sigterm-grace-write"

    async def sigterm_ignoring_writer(_context):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(1.15)
        marker.write_text("unsafe", encoding="utf-8")

    with pytest.raises(CallbackDeadlineExceeded):
        await service()._invoke(  # noqa: SLF001
            sigterm_ignoring_writer, Context(), permit=object(),
            phase="PREPARE", heartbeat_conn_factory=Connection)
    await asyncio.sleep(0.4)
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_callback_descendant_is_reaped_before_outcome_progression(
        harmless_heartbeat, tmp_path, complete) -> None:
    marker = tmp_path / f"descendant-write-{complete}"

    async def callback(_context):
        child = os.fork()
        if child == 0:  # pragma: no cover - separate fault process
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(1.4)
            marker.write_text("unsafe", encoding="utf-8")
            os._exit(0)
        if complete:
            return {"completed": True}
        time.sleep(5)

    if complete:
        result = await service(deadline=1)._invoke(  # noqa: SLF001
            callback, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=Connection)
        assert result == {"completed": True}
    else:
        with pytest.raises(CallbackDeadlineExceeded):
            await service(deadline=1)._invoke(  # noqa: SLF001
                callback, Context(), permit=object(), phase="PREPARE",
                heartbeat_conn_factory=Connection)
    await asyncio.sleep(1.6)
    assert not marker.exists()


def test_callback_dies_when_automation_worker_is_sigkilled(tmp_path) -> None:
    marker = tmp_path / "orphan-write"
    ready = tmp_path / "callback-ready"
    pid_file = tmp_path / "callback-pid"
    process_context = multiprocessing.get_context("fork")
    worker = process_context.Process(
        target=_worker_with_delayed_callback,
        args=(str(marker), str(ready), str(pid_file)))
    worker.start()
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    callback_pid = int(pid_file.read_text(encoding="utf-8"))

    os.kill(worker.pid, signal.SIGKILL)
    worker.join(timeout=2)
    assert not worker.is_alive()
    deadline = time.monotonic() + 2
    while _pid_is_executing(callback_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _pid_is_executing(callback_pid)
    time.sleep(1.3)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group test")
def test_actual_supervisor_spawn_reaps_complete_group_before_replacement(
        tmp_path) -> None:
    ready = tmp_path / "group-ready"
    pids = tmp_path / "group-pids"
    marker = tmp_path / "delayed-write"
    program = r'''
import os, signal, sys, time
ready, pids, marker = sys.argv[1:]
callback = os.fork()
if callback == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    extra = os.fork()
    if extra == 0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(10)
        os._exit(0)
    with open(pids, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {extra}")
    with open(ready, "w", encoding="utf-8") as handle:
        handle.write("ready")
    time.sleep(1.2)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write("unsafe")
    os._exit(0)
time.sleep(10)
'''
    first = automation_supervisor._spawn(  # noqa: SLF001
        "group-integration-1",
        command=(sys.executable, "-c", program, str(ready), str(pids),
                 str(marker)))
    second = None
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        callback_pid, extra_pid = (
            int(value) for value in pids.read_text(encoding="utf-8").split())
        old_group = os.getpgid(first.pid)
        assert old_group == first.pid

        os.kill(first.pid, signal.SIGKILL)
        first.wait(timeout=2)
        automation_supervisor._terminate(first, grace_seconds=0)  # noqa: SLF001
        deadline = time.monotonic() + 2
        while (any(_pid_is_executing(pid)
                   for pid in (callback_pid, extra_pid))
               and time.monotonic() < deadline):
            time.sleep(0.02)
        assert not _pid_is_executing(callback_pid)
        assert not _pid_is_executing(extra_pid)
        time.sleep(1.3)
        assert not marker.exists()

        second = automation_supervisor._spawn(  # noqa: SLF001
            "group-integration-2",
            command=(sys.executable, "-c", "import time; time.sleep(10)"))
        assert os.getpgid(second.pid) == second.pid
        assert os.getpgid(second.pid) != old_group
    finally:
        if first.poll() is None:
            automation_supervisor._terminate(first, grace_seconds=0)  # noqa: SLF001
        if second is not None:
            automation_supervisor._terminate(second, grace_seconds=0)  # noqa: SLF001


def test_supervisor_anchors_first_callback_poll_to_registered_start() -> None:
    watch = automation_supervisor.CallbackWatch()
    assert automation_supervisor._callback_deadline_expired(  # noqa: SLF001
        watch, state="PREPARE_CALLBACK", now_monotonic=100.0,
        deadline_seconds=30.0, state_age_seconds=31.0)


@pytest.mark.asyncio
async def test_failure_after_callback_start_cleans_process(
        harmless_heartbeat, monkeypatch, tmp_path) -> None:
    marker = tmp_path / "thread-start-leak"
    killed_pids = []
    original_kill = service_module._kill_callback_process
    original_thread_start = service_module.threading.Thread.start

    def capture_kill(process, **kwargs):
        if process is not None and process.pid is not None:
            killed_pids.append(process.pid)
        return original_kill(process, **kwargs)

    def fail_heartbeat_start(thread):
        if thread.name.startswith("sentinel-heartbeat-"):
            raise RuntimeError("injected heartbeat start failure")
        return original_thread_start(thread)

    async def late_writer(_context):
        time.sleep(0.4)
        marker.write_text("unsafe", encoding="utf-8")

    monkeypatch.setattr(service_module, "_kill_callback_process", capture_kill)
    monkeypatch.setattr(
        service_module.threading.Thread, "start", fail_heartbeat_start)
    with pytest.raises(RuntimeError, match="heartbeat start failure"):
        await service(deadline=4)._invoke(  # noqa: SLF001
            late_writer, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=Connection)
    assert killed_pids
    assert all(not _pid_is_executing(pid) for pid in killed_pids)
    await asyncio.sleep(0.5)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_failure_during_task_creation_cleans_process(
        harmless_heartbeat, monkeypatch, tmp_path) -> None:
    marker = tmp_path / "task-start-leak"
    killed_pids = []
    original_kill = service_module._kill_callback_process

    def capture_kill(process, **kwargs):
        if process is not None and process.pid is not None:
            killed_pids.append(process.pid)
        return original_kill(process, **kwargs)

    def fail_create_task(coro):
        coro.close()
        raise RuntimeError("injected task creation failure")

    async def late_writer(_context):
        time.sleep(0.4)
        marker.write_text("unsafe", encoding="utf-8")

    monkeypatch.setattr(service_module, "_kill_callback_process", capture_kill)
    monkeypatch.setattr(service_module.asyncio, "create_task", fail_create_task)
    with pytest.raises(RuntimeError, match="task creation failure"):
        await service(deadline=4)._invoke(  # noqa: SLF001
            late_writer, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=Connection)
    assert killed_pids
    assert all(not _pid_is_executing(pid) for pid in killed_pids)
    await asyncio.sleep(0.5)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_child_exception_short_name_cannot_spoof_reviewed_type(
        harmless_heartbeat) -> None:
    class TransientInfrastructureFailure(Exception):
        pass

    async def spoofed(_context):
        raise TransientInfrastructureFailure("not Sentinel's exception")

    with pytest.raises(SoftwareDefect, match="unreviewed callback exception"):
        await service()._invoke(  # noqa: SLF001
            spoofed, Context(), permit=object(), phase="REFRESH",
            heartbeat_conn_factory=Connection)


@pytest.mark.asyncio
async def test_heartbeat_connection_construction_failure_is_signaled() -> None:
    async def blocked(_context):
        time.sleep(10)

    def unavailable():
        raise ConnectionError("database unavailable")

    with pytest.raises(StaleLeaderRefused, match="heartbeat failed"):
        await service(deadline=4)._invoke(  # noqa: SLF001
            blocked, Context(), permit=object(), phase="RECOVER",
            heartbeat_conn_factory=unavailable)


@pytest.mark.asyncio
async def test_heartbeat_close_failure_is_signaled(
        harmless_heartbeat) -> None:
    async def blocked(_context):
        time.sleep(10)

    with pytest.raises(StaleLeaderRefused, match="close failed"):
        await service(deadline=4)._invoke(  # noqa: SLF001
            blocked, Context(), permit=object(), phase="RECOVER",
            heartbeat_conn_factory=lambda: Connection(
                close_error=ConnectionError("close failed")))


@pytest.mark.asyncio
async def test_factory_returning_after_callback_stop_cannot_renew(
        monkeypatch) -> None:
    renewals = []
    monkeypatch.setattr(
        service_module.store, "heartbeat_lease",
        lambda *_args, **_kwargs: renewals.append("renewed"))
    monkeypatch.setattr(
        service_module.store, "register_instance",
        lambda *_args, **_kwargs: None)

    def delayed_connection():
        time.sleep(0.4)
        return Connection()

    async def completes(_context):
        time.sleep(1.1)
        return {"completed": True}

    result = await service(deadline=4)._invoke(  # noqa: SLF001
        completes, Context(), permit=object(), phase="PREPARE",
        heartbeat_conn_factory=delayed_connection)
    assert result == {"completed": True}
    assert renewals == []


@pytest.mark.asyncio
async def test_unjoined_heartbeat_worker_is_terminal_supervisor_failure(
        harmless_heartbeat) -> None:
    def blocked_factory():
        time.sleep(4)
        return Connection()

    async def completes(_context):
        time.sleep(1.1)
        return {"completed": True}

    with pytest.raises(SoftwareDefect, match="did not stop"):
        await service(deadline=5)._invoke(  # noqa: SLF001
            completes, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=blocked_factory)


def test_alpaca_label_cannot_spoof_composition_certification() -> None:
    class SpoofedAlpaca(SimulatedBroker):
        certification_name = "alpaca"

    spoofed = SpoofedAlpaca()
    with pytest.raises(AdapterNotCertified, match="composition-issued"):
        require_certified_adapter(spoofed, expected="alpaca")
    with pytest.raises(PaperActivationRefused, match="composition-issued"):
        _require_certified_paper_broker(spoofed)


def test_guarded_wrapper_subclass_cannot_mint_certification() -> None:
    class Bypass(GuardedExecutionBroker):
        async def submit(self, **_kwargs):
            raise AssertionError("bypassed guard")

    async def before(_grant, _operation):
        return None

    async def after(_grant, _operation, _result):
        return None

    with pytest.raises(AdapterNotCertified, match="wrapper implementation"):
        Bypass(
            inner=SimulatedBroker(),
            grant=ManualExecutionGrant(
                confirm_paper_account="SIM-ACCOUNT",
                confirm_plan_id="plan", confirm_effective_session=date(2026, 8, 31),
                confirm_submit_paper_orders=True),
            guard=ExecutionBrokerGuard(
                before_read=before, after_read=after,
                before_mutation=before))


def _snapshot(account_id: str) -> BrokerAccountSnapshot:
    return BrokerAccountSnapshot(
        identity=BrokerAccountIdentity("alpaca", account_id),
        equity=Decimal("100"), cash=Decimal("100"),
        buying_power=Decimal("100"), multiplier=Decimal("1"),
        status="ACTIVE")


def _observation(account_id: str) -> BrokerObservation:
    now = datetime.now(timezone.utc)
    return BrokerObservation(
        observed_at=now, started_at=now, orders=(), positions=(),
        completeness=Completeness.COMPLETE,
        account_identity=BrokerAccountIdentity("alpaca", account_id))


def test_empty_account_snapshot_a_then_observation_b_is_refused() -> None:
    with pytest.raises(EmptyAccountRefused, match="differs"):
        _strict_account(
            _snapshot("A"), expected_account="A", observation=_observation("B"))


@pytest.mark.parametrize("positive", [False, True])
def test_exact_lookup_from_account_b_cannot_mutate_account_a(positive) -> None:
    observation = _observation("A")
    now = observation.observed_at
    order = None
    if positive:
        order = BrokerOrder(
            broker_order_id="b-order", client_key="durable-key",
            instrument=BrokerInstrument("SEC", "SEC", "asset"),
            side=Side.BUY, state=CommandState.ACKNOWLEDGED,
            quantity=Decimal("1"))
    lookup = BrokerExactOrderLookup(
        client_key="durable-key", request_started_at=now,
        request_completed_at=now,
        identity_before=BrokerAccountIdentity("alpaca", "B"),
        identity_after=BrokerAccountIdentity("alpaca", "B"), order=order)
    with pytest.raises(BrokerAuthorityRefused, match="differs"):
        _exact_lookup_account_or_refuse(lookup, observation)


def test_capability_graph_separates_certified_and_inherited_methods() -> None:
    graph = resolved_capability_graph(SimulatedBroker())
    assert "recovery_aware" in graph["certified_capabilities"]
    assert graph["method_availability"]["recovery_aware"] is False
    assert graph["recovery_aware"] is False
    assert graph["adapter_certification"]["conformance_suite"]


@pytest.mark.parametrize("exc,expected", [
    (sharadar.SharadarRetryDeferred(10, 429),
     TransientInfrastructureFailure),
    (sharadar.SharadarRetryDeferred(10, 503),
     TransientInfrastructureFailure),
    (sharadar.SharadarRequestError("Sharadar request failed (HTTP 401)"),
     PermanentOperationalRefusal),
    (sharadar.SharadarProtocolError("malformed payload"),
     DataIntegrityFailure),
    (ConnectionError("database unavailable"),
     TransientInfrastructureFailure),
    (OSError(errno.ECONNRESET, "connection reset"),
     TransientInfrastructureFailure),
    (FileNotFoundError(errno.ENOENT, "required artifact missing"),
     PermanentOperationalRefusal),
    (PermissionError(errno.EACCES, "permission denied"),
     PermanentOperationalRefusal),
    (IsADirectoryError(errno.EISDIR, "invalid artifact path"),
     PermanentOperationalRefusal),
    (OSError(errno.ENOSPC, "disk full"),
     HumanInterventionRequired),
    (httpx.ReadTimeout("read timed out"),
     TransientInfrastructureFailure),
    (httpx.ConnectTimeout("connect timed out"),
     TransientInfrastructureFailure),
    (httpx.WriteTimeout("write timed out"),
     TransientInfrastructureFailure),
])
def test_dependency_failures_receive_reviewed_taxonomy(exc, expected) -> None:
    assert isinstance(
        automation_runtime.classify_dependency_failure(exc), expected)


def test_unknown_dependency_exception_remains_software_defect_candidate() -> None:
    assert automation_runtime.classify_dependency_failure(
        AttributeError("bad internal shape")) is None


@pytest.mark.parametrize(("code", "expected"), [
    (socket.EAI_AGAIN, TransientInfrastructureFailure),
    (socket.EAI_FAIL, PermanentOperationalRefusal),
    (socket.EAI_NONAME, PermanentOperationalRefusal),
    (socket.EAI_MEMORY, HumanInterventionRequired),
    (socket.EAI_BADFLAGS, SoftwareDefect),
    (socket.EAI_FAMILY, SoftwareDefect),
    (socket.EAI_SERVICE, SoftwareDefect),
    (socket.EAI_SOCKTYPE, SoftwareDefect),
])
def test_dns_failures_receive_resolver_specific_taxonomy(code, expected) -> None:
    classified = automation_runtime.classify_dependency_failure(
        socket.gaierror(code, "resolver failure"))
    assert isinstance(classified, expected)


def test_eai_system_uses_underlying_system_errno() -> None:
    resolver = socket.gaierror(socket.EAI_SYSTEM, "system resolver failure")
    resolver.__cause__ = OSError(errno.ECONNRESET, "connection reset")
    classified = automation_runtime.classify_dependency_failure(resolver)
    assert isinstance(classified, TransientInfrastructureFailure)


@pytest.mark.asyncio
async def test_refresh_connection_outage_is_transient_end_to_end() -> None:
    runtime = object.__new__(automation_runtime.ProductionAutomation)

    def unavailable():
        raise ConnectionError("postgres temporarily unavailable")

    runtime.connect = unavailable
    with pytest.raises(TransientInfrastructureFailure, match="transport"):
        await runtime.refresh(object())
