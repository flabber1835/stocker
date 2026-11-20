"""Best-effort, bounded timing records for the unattended PAPER worker."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import logging
from time import perf_counter_ns


LOGGER_NAME = "sentinel.opening_stage"
_LOGGER = logging.getLogger(LOGGER_NAME)
_MAX_LINE_BYTES = 512
_TEMPLATES = frozenset({
    "paper_execution_stage stage=%s elapsed_ms=%d",
    "paper_execution_stage status=%s total_ms=%d last_stage=%s exception_type=%s",
    "automation_execution_stage stage=paper_gateway elapsed_ms=%d",
    "automation_execution_stage stage=completion_proof elapsed_ms=%d",
    "automation_preflight_stage stage=%s elapsed_ms=%d",
    "automation_execution_stage stage=terminal_transition_and_commit "
    "path=%s returned=%s elapsed_ms=%d",
    "automation_idle_authority_stage outcome=%s stage=%s "
    "elapsed_ms=%d budget_ms=%d backend_pid=%d",
    "automation_idle_authority_parent outcome=%s stage=%s elapsed_ms=%d",
    "automation_callback_startup stage=%s event=begin",
    "automation_callback_startup stage=%s event=end elapsed_ms=%d",
    "paper_broker_read_timing operation=%s part=%s count=%d elapsed_ms=%d",
})
_BROKER_READS = ContextVar("opening_broker_reads", default=None)


class _WorkerStageSink(logging.Handler):
    """Admit only fixed timing templates to the supervisor's finite writer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno != logging.INFO or record.msg not in _TEMPLATES:
                return
            message = record.getMessage()
            raw = message.encode("utf-8", errors="replace")
            if (len(raw) > _MAX_LINE_BYTES or b"\n" in raw or b"\r" in raw):
                return
            from sentinel import supervisor_io
            supervisor_io.report(message)
        except Exception:
            # Diagnostics cannot replace a financial result or an UNKNOWN
            # transaction outcome, including while unwinding an exception.
            return


def info(template: str, *args: object) -> None:
    """An unavailable logger is diagnostic loss, not callback failure."""
    try:
        _LOGGER.info(template, *args)
    except Exception:
        return


@contextmanager
def preflight(stage: str):
    """Time one callback admission step, including a step that refuses."""
    start = perf_counter_ns()
    try:
        yield
    finally:
        elapsed = min(86_400_000, max(0, (perf_counter_ns() - start) // 1_000_000))
        info("automation_preflight_stage stage=%s elapsed_ms=%d", stage, elapsed)


@contextmanager
def callback_startup(phase: str, stage: str):
    if phase != "EXECUTE":
        yield
        return
    start = perf_counter_ns()
    info("automation_callback_startup stage=%s event=begin", stage)
    try:
        yield
    finally:
        elapsed = min(86_400_000, max(0, (perf_counter_ns() - start) // 1_000_000))
        info("automation_callback_startup stage=%s event=end elapsed_ms=%d", stage, elapsed)


@contextmanager
def broker_reads():
    counts = {}
    token = _BROKER_READS.set(counts)
    try:
        yield
    finally:
        _BROKER_READS.reset(token)
        for (operation, part), (count, elapsed) in counts.items():
            info("paper_broker_read_timing operation=%s part=%s count=%d elapsed_ms=%d",
                 operation, part, count, min(86_400_000, elapsed // 1_000_000))


@contextmanager
def broker_read(operation: str, part: str):
    counts = _BROKER_READS.get()
    if counts is None:
        yield
        return
    start = perf_counter_ns()
    try:
        yield
    finally:
        key = (operation, part)
        count, elapsed = counts.get(key, (0, 0))
        counts[key] = count + 1, elapsed + max(0, perf_counter_ns() - start)


def install_worker_sink() -> None:
    """Configure just the stage logger at the deployed worker entry point."""
    try:
        if not any(isinstance(handler, _WorkerStageSink)
                   for handler in _LOGGER.handlers):
            _LOGGER.addHandler(_WorkerStageSink())
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate = False
    except Exception:
        return
