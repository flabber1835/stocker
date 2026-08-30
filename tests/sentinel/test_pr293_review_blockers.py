from __future__ import annotations

import asyncio
import errno
import multiprocessing
import os
import signal
import socket
import time

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
from sentinel.execution.certification import (
    AdapterNotCertified,
    require_certified_adapter,
)
from sentinel.execution.contract import resolved_capability_graph
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import sharadar
from sentinel.paper import PaperActivationRefused
from sentinel.paper.inspection import _require_certified_paper_broker


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
