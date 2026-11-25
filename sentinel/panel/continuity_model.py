"""Typed, display-only verdict for unattended PAPER trading continuity."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


ReasonCode = Literal[
    'CURRENT_TRADING_STOP', 'STATUS_UNKNOWN', 'MISSED_TRADING_WINDOW',
    'IDLE_BROKER_SNAPSHOT_EXPIRED', 'AUTOMATIC_RECOVERY',
    'CURRENT_CHECK_DEGRADED', 'REVIEW_REQUIRED', 'CURRENT_PATH_READY',
]


class NextAction(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['PREPARE_NEXT_PLAN']
    at: datetime
    evidence_key: Literal['paper_reconciliation']


class TradingContinuity(BaseModel):
    """One presentation verdict; never consumed by an execution gate."""
    model_config = ConfigDict(extra='forbid', frozen=True)

    status: Literal['ok', 'warn', 'fail', 'pending']
    color: Literal['green', 'amber', 'red', 'neutral']
    reason_codes: tuple[ReasonCode, ...]
    blocking_keys: tuple[str, ...]
    warning_keys: tuple[str, ...]
    evidence_keys: tuple[str, ...]
    evidence_times: dict[str, datetime]
    valid_until: datetime | None
    next_action: NextAction | None

    @model_validator(mode='after')
    def coherent(self):
        if self.color != {'ok': 'green', 'warn': 'amber',
                          'fail': 'red', 'pending': 'neutral'}[self.status]:
            raise ValueError('continuity status and color disagree')
        if any(clock.utcoffset() is None for clock in
               (*self.evidence_times.values(), self.valid_until,
                self.next_action.at if self.next_action is not None else None)
               if clock is not None):
            raise ValueError('continuity evidence has an unzoned clock')
        if self.next_action is not None and 'MISSED_TRADING_WINDOW' not in self.reason_codes:
            raise ValueError('next-plan claim lacks its missed-window witness')
        return self
