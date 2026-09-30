"""Generic schema for reviewed provider data; never ticker-specific behavior."""
from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from sentinel.feed.rolling_contract import Contract, Digest, Label, digest

MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 4096


class CorrectionRefused(RuntimeError):
    pass


class Evidence(Contract):
    reference: str = Field(min_length=1, max_length=2048)
    sha256: Digest
    reviewer: Label


class CoverageRecord(Contract):
    kind: Literal['SESSION_ABSENCE', 'TERMINAL_ABSENCE']
    session: str
    permaticker: str = Field(pattern=r'^[0-9]{1,20}$')
    ticker: str = Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,19}$')
    category: Label
    first_session: str | None = None
    first_observed: str | None = None
    last_session: str | None = None
    evidence: Evidence

    @field_validator('session', 'first_session', 'first_observed', 'last_session')
    @classmethod
    def exact_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError('correction date must be canonical ISO')
        return value

    @model_validator(mode='after')
    def boundary(self):
        if self.kind == 'SESSION_ABSENCE':
            if (not self.first_session or not self.first_observed or self.last_session
                    or self.session < self.first_session or self.first_observed < self.first_session):
                raise ValueError('session absence requires exact listing and observed boundaries')
        elif self.last_session != self.session or self.first_session or self.first_observed:
            raise ValueError('terminal absence requires exact terminal boundary')
        return self


class Dataset(Contract):
    schema_version: Literal['sentinel.source-corrections/1'] = Field(alias='schema')
    provider: Literal['SHARADAR']
    coverage: tuple[CoverageRecord, ...] = Field(max_length=MAX_RECORDS)
    disputed_cash_events: tuple[dict, ...] = Field(max_length=MAX_RECORDS)
    cash_authorities: tuple[dict, ...] = Field(max_length=MAX_RECORDS)

    @model_validator(mode='after')
    def unique(self):
        keys = [(row.session, row.permaticker) for row in self.coverage]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate correction identity/session')
        return self


def validate(value):
    try:
        result = Dataset.model_validate(value).model_dump(mode='json', by_alias=True)
        if len(json.dumps(result).encode('utf-8')) > MAX_BYTES:
            raise ValueError('correction dataset exceeds byte bound')
        from sentinel.feed.corporate_action_authority import _validated_registry
        _validated_registry(result['disputed_cash_events'], result['cash_authorities'])
        return result
    except (TypeError, ValueError, RuntimeError) as exc:
        if isinstance(exc, CorrectionRefused):
            raise
        raise CorrectionRefused('invalid correction dataset: ' + str(exc)) from exc


def require_extension(previous, candidate):
    """New facts only. Changing existing economics is a separate repair action."""
    for field in ('coverage', 'disputed_cash_events', 'cash_authorities'):
        old = {digest(row) for row in previous[field]}
        new = {digest(row) for row in candidate[field]}
        if not old.issubset(new):
            raise CorrectionRefused('correction update cannot remove or replace reviewed facts: ' + field)
