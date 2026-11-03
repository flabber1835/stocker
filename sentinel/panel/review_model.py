"""Typed, nonfinancial operator review facts. No I/O or execution authority."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OperatorReview(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    scope: str = Field(pattern=r'^[a-f0-9]{64}$')
    head: int = Field(ge=0, strict=True)
    reviewed_head: int = Field(ge=0, strict=True)
    status: Literal['CLEAN', 'FAILED', 'REVIEW', 'UNAVAILABLE']
    observed_at: datetime
    reviewed_at: datetime | None = None
    active: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    events: list[dict] = Field(default_factory=list, max_length=20)
    token: str | None = Field(default=None, max_length=8192)
    detail: str = ''

    @model_validator(mode='after')
    def coherent(self):
        if self.reviewed_head > self.head:
            raise ValueError('operator review is ahead of its history')
        if self.observed_at.utcoffset() is None or (
                self.reviewed_at is not None and self.reviewed_at.utcoffset() is None):
            raise ValueError('operator review clock lacks a timezone')
        if self.status == 'CLEAN' and (self.active or self.warnings or self.head != self.reviewed_head
                                     or self.head == 0 or self.reviewed_at is None):
            raise ValueError('clean operator review has unresolved or unreviewed state')
        if self.status == 'FAILED' and not self.active:
            raise ValueError('failed operator review has no active failure')
        if self.token is not None and (self.status != 'REVIEW' or self.active or self.warnings):
            raise ValueError('an active condition cannot carry a green-baseline acknowledgement')
        return self
