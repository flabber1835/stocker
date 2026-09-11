"""Explicit, independently specified lifecycle actions and invariants."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False).encode()).hexdigest()


class InvalidTrace(ValueError):
    pass


class InvariantFailure(AssertionError):
    def __init__(self, name, expected, actual):
        self.invariant, self.expected, self.actual = name, expected, actual
        self.index = -1
        super().__init__(f"{name}: expected {expected!r}; got {actual!r}")


def check(name, expected, actual):
    if expected != actual:
        raise InvariantFailure(name, expected, actual)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["daily", "restart", "execute", "fill", "reconcile", "cash",
                  "checkpoint", "restore", "media_loss", "media_repair",
                  "wal_corrupt", "wal_repair", "env_bad", "env_repair",
                  "data_bad", "data_repair", "kill_submit", "timeout_submit", "cancel_race",
                  "corrupt_state", "compete", "kill_catchup", "market_shock"]
    value: int = Field(default=0, ge=-10000, le=10000, strict=True)

    @model_validator(mode="after")
    def meaningful_value(self):
        if self.kind == "fill" and self.value not in {-1, 0, 1}:
            raise ValueError("fill uses -1 (available orders), 0 (required full), or 1 (required partial)")
        if self.kind == "cash" and self.value == 0:
            raise ValueError("cash event must be nonzero")
        if self.kind == "market_shock" and (self.value == 0 or self.value < -9000):
            raise ValueError("shock must be a nonzero return of at least -9000 basis points")
        if self.kind not in {"fill", "cash", "market_shock"} and self.value != 0:
            raise ValueError("this action has no numeric parameter")
        return self


class Trace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["sentinel.integrated-state/1"] = "sentinel.integrated-state/1"
    fixture: Literal["rising-published-market-v1"] = "rising-published-market-v1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    seed: int = Field(default=0, ge=0, le=2**32 - 1, strict=True)
    profile: Literal["paper", "live_cash"] = "paper"
    actions: tuple[Action, ...] = Field(min_length=1, max_length=2000)
    required: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_requirements(self):
        if len(set(self.required)) != len(self.required):
            raise ValueError("duplicate coverage requirement")
        return self

    def envelope(self):
        payload = self.model_dump(mode="json")
        return {"trace": payload, "sha256": digest(payload)}

    @classmethod
    def decode(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {"trace", "sha256"}:
            raise InvalidTrace("invalid trace envelope")
        if digest(raw["trace"]) != raw["sha256"]:
            raise InvalidTrace("trace content digest mismatch")
        return cls.model_validate(raw["trace"])


def reduce_trace(trace, run, invariant, *, budget=32):
    """Bounded ddmin; every accepted reduction replays the same named defect."""
    def reproduces(candidate):
        try:
            run(candidate)
        except InvariantFailure as exc:
            return exc.invariant == invariant
        except InvalidTrace:
            return False
        return False

    if not reproduces(trace):
        raise ValueError("original trace does not reproduce the named invariant")
    current, evaluations, granularity = trace, 0, 2
    while len(current.actions) > 1 and evaluations < budget:
        width = (len(current.actions) + granularity - 1) // granularity
        changed = False
        for start in range(0, len(current.actions), width):
            actions = current.actions[:start] + current.actions[start + width:]
            if not actions:
                continue
            candidate = current.model_copy(update={"actions": actions, "required": ()})
            evaluations += 1
            if reproduces(candidate):
                current, changed = candidate, True
                granularity = max(2, granularity - 1)
                break
            if evaluations >= budget:
                break
        if not changed:
            if granularity >= len(current.actions):
                break
            granularity = min(len(current.actions), granularity * 2)
    if not reproduces(current):
        raise RuntimeError("reduced trace failed final replay")
    return current, {"evaluations": evaluations, "budget": budget,
                     "budget_exhausted": evaluations >= budget,
                     "original_actions": len(trace.actions),
                     "reduced_actions": len(current.actions)}
