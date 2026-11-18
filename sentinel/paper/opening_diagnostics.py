"""Bounded, monotonic timings for one in-process PAPER execution callback."""

from __future__ import annotations

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
