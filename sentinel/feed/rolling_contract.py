"""Typed storage identities for a complete operational price generation.

These values describe evidence. They confer no source, checkpoint or trading
authority. See docs/rolling-snapshot-storage.md.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.feed import calendar

PRICE_SESSIONS = 300
VERIFICATION_POLICY = "sentinel.operational-verification/1"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(min_length=1, max_length=256)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PriceWindow(Contract):
    count: ClassVar[int] = PRICE_SESSIONS
    sessions: tuple[date, ...]

    @model_validator(mode="after")
    def exact_axis(self):
        if len(self.sessions) != self.count:
            raise ValueError(f"price window requires exactly {self.count} sessions")
        actual = tuple(day.isoformat() for day in self.sessions)
        expected = tuple(calendar.previous_sessions(actual[-1], self.count))
        if actual != expected:
            raise ValueError("price window is not the exact consecutive XNYS axis")
        return self

    @classmethod
    def through(cls, target: str) -> "PriceWindow":
        return cls(sessions=tuple(calendar.previous_sessions(target, cls.count)))

    @property
    def start(self) -> date:
        return self.sessions[0]

    @property
    def end(self) -> date:
        return self.sessions[-1]


class FormationWindow(PriceWindow):
    """First acquisition only; ordinary rolling history remains 300 closes."""
    count: ClassVar[int] = 379
    purpose: Literal['OWNED55_FRESH_FORMATION_V1'] = 'OWNED55_FRESH_FORMATION_V1'


def snapshot_window(value):
    cls = FormationWindow if value.get('purpose') == 'OWNED55_FRESH_FORMATION_V1' else PriceWindow
    return cls.model_validate(value)


class RestartRequirement(Contract):
    """Aggregate tail requirement; the predecessor consumes the same budget."""

    feature_sessions: int = Field(default=252, ge=1)
    restart_sessions: int = Field(default=260, ge=1)
    spy_sessions: int = Field(default=254, ge=1)
    predecessor_sessions: int = Field(default=1, ge=1)

    @property
    def total_sessions(self) -> int:
        return max(self.feature_sessions, self.restart_sessions,
                   self.spy_sessions) + self.predecessor_sessions

    @model_validator(mode="after")
    def fits_window(self):
        if self.total_sessions > PRICE_SESSIONS:
            raise ValueError("aggregate restart requirements exceed the 300-session window")
        return self


class CanonicalBar(Contract):
    security_id: Label
    session: date
    ticker: Label
    close_signal: Positive | None
    close_unadjusted: Positive
    open_unadjusted: Positive | None
    volume: Nonnegative | None
    split_ratio: Positive
    dividend_per_share: Nonnegative

    @field_validator("security_id", "ticker")
    @classmethod
    def canonical_label(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("canonical security labels cannot be blank or padded")
        return value


class CanonicalBenchmark(Contract):
    session: date
    spy_total_return: Positive
    bil_open_signal: Positive | None
    bil_close_signal: Positive
    bil_close_adjusted: Positive | None
    bil_close_unadjusted: Positive


class SnapshotManifest(Contract):
    schema_version: Literal["sentinel.rolling-price-snapshot/1"] = (
        "sentinel.rolling-price-snapshot/1")
    provider: Literal["SHARADAR"] = "SHARADAR"
    normalization_version: Label
    calendar_version: Label
    window: FormationWindow | PriceWindow
    reference_sha256: Digest
    source_evidence_sha256: Digest
    coverage_sha256: Digest
    bars_sha256: Digest
    benchmarks_sha256: Digest
    bar_count: int = Field(gt=0)
    requirements: RestartRequirement

    @property
    def snapshot_id(self) -> str:
        return digest(self.model_dump(mode="json"))


class OperationalVerificationScope(Contract):
    policy: Literal["sentinel.operational-verification/1"] = VERIFICATION_POLICY
    scope: Literal["CURRENT_WINDOW_AND_LIVE_DEPENDENCIES"] = (
        "CURRENT_WINDOW_AND_LIVE_DEPENDENCIES")
    snapshot_id: Digest
    reference_sha256: Digest
    strategy_sha256: Digest
    checkpoint_sha256: Digest
    live_dependencies_sha256: Digest
    window: PriceWindow
    cursor: date

    @model_validator(mode="after")
    def cursor_available(self):
        # The earliest row is the predecessor, not a resumable decision cursor.
        if self.cursor not in self.window.sessions[1:]:
            raise ValueError("durable cursor/predecessor is outside the available window")
        return self
