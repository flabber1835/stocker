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
    "automation_close_preflight event=dispatch retry_due_ms=%d",
    "automation_close_preflight event=return elapsed_ms=%d",
    "automation_execution_stage stage=terminal_transition_and_commit "
    "path=%s returned=%s elapsed_ms=%d",
    "automation_idle_authority_stage outcome=%s stage=%s "
    "elapsed_ms=%d budget_ms=%d backend_pid=%d",
    "automation_idle_authority_parent outcome=%s stage=%s elapsed_ms=%d",
    "automation_callback_startup stage=%s event=begin",
    "automation_callback_startup stage=%s event=end elapsed_ms=%d",
    "paper_broker_read_timing operation=%s part=%s count=%d elapsed_ms=%d",
    "paper_guard_phase operation=%s part=%s phase=%s count=%d elapsed_ms=%d",
    "paper_projection_phase stage=%s phase=%s elapsed_ms=%d",
})
_BROKER_READS = ContextVar("opening_broker_reads", default=None)
_GUARD_PHASES = ContextVar("opening_guard_phases", default=None)
_ACTIVE_BROKER_READ = ContextVar("opening_active_broker_read", default=None)
_GUARD_PHASE_NAMES = frozenset({
    "connection_setup", "read_only_setup", "grant_structural",
    "publication_rollout", "signed_authority", "result_evidence",
})
_GUARD_READ_PARTS = frozenset({"before_read", "after_read"})
_GUARD_READ_OPERATIONS = frozenset({
    "identify_account", "account_snapshot", "account_close_valuation",
    "account_fill_interval_evidence", "resolve_instrument", "asset_rules",
    "market_clock", "opening_prices", "account_cash_activities",
    "observe", "observe_with_terminal_recovery", "find_by_client_key",
    "recent_fills", "owned_order_fills",
})
_MAX_PHASE_COUNT = 100_000
_MAX_PHASE_NS = 86_400_000_000_000


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
def close_preflight(dispatched_at, due_at):
    started = perf_counter_ns()
    retry_due_ms = (-1 if due_at is None else
                    min(86_400_000, max(0, round((dispatched_at - due_at).total_seconds() * 1000))))
    info('automation_close_preflight event=dispatch retry_due_ms=%d', retry_due_ms)
    try:
        yield
    finally:
        elapsed = min(86_400_000, max(0, (perf_counter_ns() - started) // 1_000_000))
        info('automation_close_preflight event=return elapsed_ms=%d', elapsed)


@contextmanager
def callback_startup(phase: str, stage: str):
    if phase not in {'EXECUTE', 'PREFLIGHT_RECOVER'}:
        yield
        return
    if phase == 'PREFLIGHT_RECOVER':
        stage = 'close_preflight_' + stage
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
    guard_counts = {}
    token = _BROKER_READS.set(counts)
    guard_token = _GUARD_PHASES.set(guard_counts)
    try:
        yield
    finally:
        _GUARD_PHASES.reset(guard_token)
        _BROKER_READS.reset(token)
        for (operation, part), (count, elapsed) in counts.items():
            info("paper_broker_read_timing operation=%s part=%s count=%d elapsed_ms=%d",
                 operation, part, count, min(86_400_000, elapsed // 1_000_000))
        for (operation, part, phase), (count, elapsed) in guard_counts.items():
            info("paper_guard_phase operation=%s part=%s phase=%s count=%d elapsed_ms=%d",
                 operation, part, phase, count, elapsed // 1_000_000)


@contextmanager
def broker_read(operation: str, part: str):
    counts = _BROKER_READS.get()
    if counts is None:
        yield
        return
    start = perf_counter_ns()
    active_token = (_ACTIVE_BROKER_READ.set((operation, part))
                    if operation in _GUARD_READ_OPERATIONS
                    and part in _GUARD_READ_PARTS else None)
    try:
        yield
    finally:
        if active_token is not None:
            _ACTIVE_BROKER_READ.reset(active_token)
        key = (operation, part)
        count, elapsed = counts.get(key, (0, 0))
        counts[key] = count + 1, elapsed + max(0, perf_counter_ns() - start)


@contextmanager
def guard_phase(phase: str, *, enabled: bool = True):
    """Aggregate only fixed timing names within an owned broker-read trace."""
    counts = _GUARD_PHASES.get()
    active = _ACTIVE_BROKER_READ.get()
    if (not enabled or counts is None or active is None
            or phase not in _GUARD_PHASE_NAMES):
        yield
        return
    try:
        start = perf_counter_ns()
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            key = (*active, phase)
            key_count, elapsed = counts.get(key, (0, 0))
            counts[key] = (
                min(_MAX_PHASE_COUNT, key_count + 1),
                min(_MAX_PHASE_NS,
                    elapsed + max(0, perf_counter_ns() - start)),
            )
        except Exception:
            # Timing must not replace an authorization refusal or broker result.
            pass


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
