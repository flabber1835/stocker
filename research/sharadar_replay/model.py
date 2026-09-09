"""Independent scenario contract. No production imports."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Corpus(Contract):
    bars: tuple[tuple, ...]
    actions: tuple[tuple, ...]
    identities: tuple[tuple, ...]
    spy: tuple[tuple, ...]
    defensive: tuple[tuple, ...]


class Fault(Contract):
    table: Literal["SEP", "SFP", "TICKERS", "ACTIONS"]
    kind: Literal["missing_column", "omit_ticker", "repeat_cursor", "http_400",
                  "duplicate_row", "stale_export", "invalid_json", "row_width",
                  "missing_cursor", "invalid_zip", "conflicting_row", "set_value",
                  "rate_limit", "service_unavailable"]
    channel: Literal["pages", "export"] = "pages"
    ticker: str | None = None
    after_rows: int = Field(default=0, ge=0)
    field: str | None = None
    value: str | int | float | None = None


class Step(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    at: dt.datetime
    through: dt.date
    tables: dict[str, tuple[dict, ...]]
    expected: Corpus
    ready: bool = True
    error: str | None = None
    required_blockers: tuple[str, ...] = ()
    faults: tuple[Fault, ...] = ()
    publication_failure: bool = False

    @model_validator(mode="after")
    def causal_time(self):
        if self.at.utcoffset() != dt.timedelta(0):
            raise ValueError("scenario clock must be explicit UTC")
        if self.through > self.at.date():
            raise ValueError("market frontier exceeds source clock")
        if set(self.tables) != {"SEP", "SFP", "TICKERS", "ACTIONS"}:
            raise ValueError("all four provider tables must be explicit")
        for table, rows in self.tables.items():
            for row in rows:
                for field in (("date", "lastupdated") if table == "SEP" else ("date",)):
                    if row.get(field) and dt.date.fromisoformat(str(row[field])) > self.at.date():
                        raise ValueError(f"{table}.{field} exposes a future observation")
        return self


class Scenario(Contract):
    schema_version: Literal["sharadar-replay/1"] = "sharadar-replay/1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    variation_seed: int = 0
    page_size: int = Field(default=53, ge=1)
    seed_start: dt.date
    seed: Step
    steps: tuple[Step, ...] = Field(min_length=1)
    recovery_from: str | None = None
    recovery_attempt_budget: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def ordered(self):
        names = [self.seed.name, *(step.name for step in self.steps)]
        if len(names) != len(set(names)):
            raise ValueError("step names must be unique")
        if self.seed_start > self.seed.through:
            raise ValueError("reversed seed interval")
        prior = self.seed.at
        for step in self.steps:
            if step.at <= prior:
                raise ValueError("observation time must strictly advance")
            prior = step.at
        if self.recovery_from and self.recovery_from not in names[1:]:
            raise ValueError("recovery begins at an explicit daily attempt")
        return self
