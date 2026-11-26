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
    "automation_idle_authority_phase phase=%s count=%d elapsed_ms=%d",
    "automation_idle_authority_rows kind=%s count=%d rows=%d",
    "automation_callback_startup stage=%s event=begin",
    "automation_callback_startup stage=%s event=end elapsed_ms=%d",
    "paper_broker_read_timing operation=%s part=%s count=%d elapsed_ms=%d",
    "paper_guard_phase operation=%s part=%s phase=%s count=%d elapsed_ms=%d",
    "paper_guard_rows operation=%s part=%s kind=%s count=%d rows=%d",
    "paper_projection_phase stage=%s phase=%s elapsed_ms=%d",
})
_BROKER_READS = ContextVar("opening_broker_reads", default=None)
_GUARD_PHASES = ContextVar("opening_guard_phases", default=None)
_GUARD_ROWS = ContextVar("opening_guard_rows", default=None)
_IDLE_AUTHORITY_PHASES = ContextVar("idle_authority_phases", default=None)
_IDLE_AUTHORITY_ROWS = ContextVar("idle_authority_rows", default=None)
_ACTIVE_BROKER_READ = ContextVar("opening_active_broker_read", default=None)
_GUARD_PHASE_NAMES = frozenset({
    "connection_setup", "read_only_setup", "grant_structural",
    "publication_rollout", "signed_authority", "result_evidence",
    "current_publication", "strategy_identity", "runtime_identity",
    "certificate_preliminary", "publication_rows", "publication_receipts",
    "publication_policy_sources", "certificate_bindings",
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
    guard_rows = {}
    token = _BROKER_READS.set(counts)
    guard_token = _GUARD_PHASES.set(guard_counts)
    rows_token = _GUARD_ROWS.set(guard_rows)
    try:
        yield
    finally:
        _GUARD_ROWS.reset(rows_token)
        _GUARD_PHASES.reset(guard_token)
        _BROKER_READS.reset(token)
        for (operation, part), (count, elapsed) in counts.items():
            info("paper_broker_read_timing operation=%s part=%s count=%d elapsed_ms=%d",
                 operation, part, count, min(86_400_000, elapsed // 1_000_000))
        for (operation, part, phase), (count, elapsed) in guard_counts.items():
            info("paper_guard_phase operation=%s part=%s phase=%s count=%d elapsed_ms=%d",
                 operation, part, phase, count, elapsed // 1_000_000)
        for (operation, part, kind), (count, rows) in guard_rows.items():
            info("paper_guard_rows operation=%s part=%s kind=%s count=%d rows=%d",
                 operation, part, kind, count, rows)


@contextmanager
def idle_authority_phases(diagnostics=None):
    """Attribute one isolated observer request without carrying a proof forward."""
    counts = {}
    rows = {}
    token = _IDLE_AUTHORITY_PHASES.set(counts)
    rows_token = _IDLE_AUTHORITY_ROWS.set(rows)
    try:
        yield
    finally:
        _IDLE_AUTHORITY_ROWS.reset(rows_token)
        _IDLE_AUTHORITY_PHASES.reset(token)
        if diagnostics is None:
            emit_idle_authority_phases(dict(phases=counts, rows=rows))
        else:
            diagnostics.update(phases=counts, rows=rows)


def emit_idle_authority_phases(diagnostics):
    """Emit the child's bounded measurements through the worker's installed sink."""
    if not isinstance(diagnostics, dict):
        return
    for section, expected, maximum, divisor, template in (
            ('phases', _GUARD_PHASE_NAMES, _MAX_PHASE_NS, 1_000_000,
             'automation_idle_authority_phase phase=%s count=%d elapsed_ms=%d'),
            ('rows', {'publication_rows'}, _MAX_PHASE_COUNT, 1,
             'automation_idle_authority_rows kind=%s count=%d rows=%d')):
        values = diagnostics.get(section)
        if not isinstance(values, dict):
            continue
        for name in sorted(expected):
            pair = values.get(name)
            if (isinstance(pair, (list, tuple)) and len(pair) == 2
                    and all(type(value) is int for value in pair)
                    and 0 < pair[0] <= _MAX_PHASE_COUNT and 0 <= pair[1] <= maximum):
                info(template, name, pair[0], pair[1] // divisor)


def authority_rows(kind: str, rows: int) -> None:
    """Count an already fetched proof result, without inspecting its values."""
    if kind != "publication_rows" or type(rows) is not int or rows < 0:
        return
    try:
        guard_counts = _GUARD_ROWS.get()
        active = _ACTIVE_BROKER_READ.get()
        if guard_counts is not None and active is not None:
            key = (*active, kind)
            count, total = guard_counts.get(key, (0, 0))
            guard_counts[key] = (min(_MAX_PHASE_COUNT, count + 1),
                                 min(_MAX_PHASE_COUNT, total + rows))
        idle_counts = _IDLE_AUTHORITY_ROWS.get()
        if idle_counts is not None:
            count, total = idle_counts.get(kind, (0, 0))
            idle_counts[kind] = (min(_MAX_PHASE_COUNT, count + 1),
                                min(_MAX_PHASE_COUNT, total + rows))
    except Exception:
        # A diagnostic cannot replace an authority refusal.
        pass


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
    """Aggregate fixed timing names in a broker read or idle observer proof."""
    counts = _GUARD_PHASES.get()
    active = _ACTIVE_BROKER_READ.get()
    idle_counts = _IDLE_AUTHORITY_PHASES.get()
    if (not enabled or phase not in _GUARD_PHASE_NAMES
            or (idle_counts is None and (counts is None or active is None))):
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
            duration = max(0, perf_counter_ns() - start)
            if counts is not None and active is not None:
                key = (*active, phase)
                key_count, elapsed = counts.get(key, (0, 0))
                counts[key] = (
                    min(_MAX_PHASE_COUNT, key_count + 1),
                    min(_MAX_PHASE_NS, elapsed + duration),
                )
            if idle_counts is not None:
                key_count, elapsed = idle_counts.get(phase, (0, 0))
                idle_counts[phase] = (
                    min(_MAX_PHASE_COUNT, key_count + 1),
                    min(_MAX_PHASE_NS, elapsed + duration),
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
