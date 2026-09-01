"""Small public API for paper-trading lifecycle orchestration."""

from __future__ import annotations

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
    prepare_paper_plan,
)
from .execution import (
    execute_automated_paper_plan,
    execute_paper_plan,
)
from .recovery import recover_automated_paper_cycle

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
