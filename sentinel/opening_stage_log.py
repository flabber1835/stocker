"""Best-effort, bounded timing records for the unattended PAPER worker."""

from __future__ import annotations

import logging


LOGGER_NAME = "sentinel.opening_stage"
_LOGGER = logging.getLogger(LOGGER_NAME)
_MAX_LINE_BYTES = 512
_TEMPLATES = frozenset({
    "paper_execution_stage stage=%s elapsed_ms=%d",
    "paper_execution_stage status=%s total_ms=%d last_stage=%s exception_type=%s",
    "automation_execution_stage stage=paper_gateway elapsed_ms=%d",
    "automation_execution_stage stage=completion_proof elapsed_ms=%d",
    "automation_execution_stage stage=terminal_transition_and_commit "
    "path=%s returned=%s elapsed_ms=%d",
})


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
