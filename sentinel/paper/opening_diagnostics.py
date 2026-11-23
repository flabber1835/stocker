"""Bounded, monotonic timings for one in-process PAPER execution callback."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
from time import perf_counter_ns

from sentinel import opening_stage_log

_MAX_DURATION_MS = 86_400_000
_STAGES = frozenset({
    "entry", "shadow", "sizing", "authority", "account_actions",
    "initial_projection", "broker_reconciliation", "final_projection",
    "executor", "final_evidence", "gateway_exit",
})
_CURRENT: ContextVar[_StageTrace | None] = ContextVar(
    "paper_opening_stage_trace", default=None)
_PROJECTION_STAGES = frozenset({"initial", "final"})
_PROJECTION_PHASES = (
    "state_target", "mutable_inputs", "action_inputs", "unit_projection",
    "policy_resolution", "finalization",
)
_PROJECTION_CURRENT: ContextVar[_ProjectionTrace | None] = ContextVar(
    "paper_opening_projection_trace", default=None)


class _ProjectionTrace:
    """Consecutive, bounded subphases of one target projection."""

    def __init__(self, stage: str):
        self.stage = stage
        self.phase: str | None = None
        self.previous_ns = perf_counter_ns()
        self.next_phase = 0

    def mark(self, phase: str) -> None:
        if (self.next_phase >= len(_PROJECTION_PHASES)
                or phase != _PROJECTION_PHASES[self.next_phase]):
            return
        now = perf_counter_ns()
        self._emit(now)
        self.phase = phase
        self.previous_ns = now
        self.next_phase += 1

    def finish(self) -> None:
        self._emit(perf_counter_ns())
        self.phase = None

    def _emit(self, now: int) -> None:
        if self.phase is None:
            return
        elapsed = max(0, min((now - self.previous_ns) // 1_000_000,
                             _MAX_DURATION_MS))
        opening_stage_log.info(
            "paper_projection_phase stage=%s phase=%s elapsed_ms=%d",
            self.stage, self.phase, elapsed)


@contextmanager
def projection(stage: str):
    """Own one initial or final projection inside a timed PAPER gateway."""
    if _CURRENT.get() is None or stage not in _PROJECTION_STAGES:
        yield
        return
    try:
        trace = _ProjectionTrace(stage)
    except Exception:
        # A diagnostic clock failure must not change the financial result.
        yield
        return
    token = _PROJECTION_CURRENT.set(trace)
    try:
        yield
    finally:
        try:
            trace.finish()
        except Exception:
            # Preserve the result or original refusal while unwinding.
            pass
        finally:
            _PROJECTION_CURRENT.reset(token)


def projection_phase(phase: str) -> None:
    trace = _PROJECTION_CURRENT.get()
    if trace is not None:
        try:
            trace.mark(phase)
        except Exception:
            # A partial timing record cannot become an execution refusal.
            pass


class _StageTrace:
    def __init__(self):
        self.started_ns = perf_counter_ns()
        self.previous_ns = self.started_ns
        self.timings_ms: dict[str, int] = {}
        self.last_stage = "start"

    def mark(self, stage: str) -> None:
        if stage not in _STAGES or stage in self.timings_ms:
            raise ValueError("PAPER execution stage is unknown or repeated")
        now = perf_counter_ns()
        elapsed = max(0, min((now - self.previous_ns) // 1_000_000,
                             _MAX_DURATION_MS))
        self.timings_ms[stage] = int(elapsed)
        self.previous_ns = now
        self.last_stage = stage
        opening_stage_log.info("paper_execution_stage stage=%s elapsed_ms=%d", stage, elapsed)

    def finish(self, *, status: str, exception_type: str = "") -> None:
        last_completed = self.last_stage
        self.mark("gateway_exit")
        total = max(0, min((perf_counter_ns() - self.started_ns) // 1_000_000,
                           _MAX_DURATION_MS))
        opening_stage_log.info(
            "paper_execution_stage status=%s total_ms=%d last_stage=%s exception_type=%s",
            status, total, last_completed, exception_type)


def mark(stage: str) -> None:
    trace = _CURRENT.get()
    if trace is not None:
        trace.mark(stage)


def timed_execution(operation):
    """Report fixed stages even when the gateway refuses before returning."""
    @wraps(operation)
    async def wrapped(*args, **kwargs):
        trace = _StageTrace()
        token = _CURRENT.set(trace)
        try:
            with opening_stage_log.broker_reads():
                result = await operation(*args, **kwargs)
        except BaseException as exc:
            trace.finish(status="exception", exception_type=type(exc).__name__)
            raise
        else:
            trace.finish(status="complete")
            return replace(result, opening_stages_ms=dict(trace.timings_ms))
        finally:
            _CURRENT.reset(token)
    return wrapped
