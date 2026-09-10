"""Small public API for paper-trading lifecycle orchestration."""

from __future__ import annotations

from sentinel import backup_runtime_authority as _backup_runtime_authority

from .model import (
    ExecutionResult,
    PaperAccountInspection,
    PaperActivationRefused,
    PaperRetryableRefused,
    PreOpenShareUnitAuthorityUnavailable,
    PreparationResult,
)
from .inspection import (
    DEFENSIVE_SYMBOL,
    build_security_resolver,
    inspect_paper_account,
)
from .preparation import (
    current_paper_plan,
    prepare_paper_plan as _prepare_paper_plan,
)
from .execution import (
    execute_automated_paper_plan as _execute_automated_paper_plan,
    execute_paper_plan as _execute_paper_plan,
)
from .recovery import recover_automated_paper_cycle


def _require_mutation_backup(conn, *, operation: str) -> None:
    """Require a complete current restore horizon before new paper mutation."""
    try:
        _backup_runtime_authority.require(conn, operation=operation)
    except _backup_runtime_authority.BackupRuntimeUnavailable as exc:
        raise PaperRetryableRefused(str(exc)) from exc
    except _backup_runtime_authority.BackupRuntimeRefused as exc:
        raise PaperActivationRefused(str(exc)) from exc


async def prepare_paper_plan(*args, **kwargs):
    conn = kwargs.get("conn")
    if conn is not None:
        _require_mutation_backup(conn, operation="paper plan preparation")
    return await _prepare_paper_plan(*args, **kwargs)


async def execute_paper_plan(*args, **kwargs):
    conn = kwargs.get("conn")
    if conn is not None:
        _require_mutation_backup(conn, operation="paper order execution")
    return await _execute_paper_plan(*args, **kwargs)


async def execute_automated_paper_plan(*args, **kwargs):
    conn = kwargs.get("conn")
    if conn is not None:
        _require_mutation_backup(conn, operation="automated paper order execution")
    return await _execute_automated_paper_plan(*args, **kwargs)


__all__ = [
    "DEFENSIVE_SYMBOL",
    "ExecutionResult",
    "PaperAccountInspection",
    "PaperActivationRefused",
    "PaperRetryableRefused",
    "PreOpenShareUnitAuthorityUnavailable",
    "PreparationResult",
    "build_security_resolver",
    "current_paper_plan",
    "execute_automated_paper_plan",
    "execute_paper_plan",
    "inspect_paper_account",
    "prepare_paper_plan",
    "recover_automated_paper_cycle",
]
