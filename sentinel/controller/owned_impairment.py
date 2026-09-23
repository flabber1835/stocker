"""Independent, persisted protection for sustained damage in owned Core."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRATEGY_ID = 'sentinel-compact-champion-owned55-v1'
RULE = dict(schema=1, entry_drawdown=-.10, entry_damage=.88, entry_green=.20,
            entry_sessions=5, recovery_damage=.63, recovery_green=.20,
            recovery_sessions=8, recovery_core_r20_above=0., active_ceiling=.55)


def enabled(identity):
    return identity.get('strategy') == STRATEGY_ID


def load():
    from .champion_config import load as champion
    base = champion()
    payload = dict(strategy=STRATEGY_ID, parent=base.digest, rule=RULE)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return replace(base, strategy_id=STRATEGY_ID, digest=digest)


class OwnedImpairmentState(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    version: Literal[1] = 1
    active: bool = False
    entry_streak: int = Field(default=0, ge=0, lt=5)
    recovery_streak: int = Field(default=0, ge=0, lt=8)
    last_session: str | None = None

    @field_validator('version', mode='before')
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('invalid owned-impairment schema')
        return value

    @model_validator(mode='after')
    def coherent(self):
        if type(self.version) is not int:
            raise ValueError('invalid owned-impairment schema')
        if (self.active and self.entry_streak) or (not self.active and self.recovery_streak):
            raise ValueError('owned-impairment counter contradicts latch')
        if self.last_session is None:
            if self.active or self.entry_streak or self.recovery_streak:
                raise ValueError('owned-impairment history lacks session')
        elif date.fromisoformat(self.last_session).isoformat() != self.last_session:
            raise ValueError('invalid owned-impairment session')
        return self


def fresh():
    return OwnedImpairmentState().model_dump()


def validate(identity, value, *, expected_session=...):
    if enabled(identity):
        if not isinstance(value, dict) or set(value) != set(fresh()):
            raise ValueError('owned-impairment state required for selected identity')
        state = OwnedImpairmentState.model_validate(value)
        if expected_session is not ... and state.last_session != expected_session:
            raise ValueError('owned-impairment cursor differs from canonical session')
        return state
    if value is not None:
        raise ValueError('owned-impairment state under another strategy')
    return None


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def step(*, observation, base_target, state):
    before = validate({'strategy': STRATEGY_ID}, state)
    session = observation.session
    if date.fromisoformat(session).isoformat() != session:
        raise ValueError('invalid owned-impairment decision session')
    if before.last_session is not None and session <= before.last_session:
        raise ValueError('owned-impairment sessions must advance strictly once')
    if not _finite(base_target) or not 0 <= base_target <= 1:
        raise ValueError('invalid parent allocation')
    dd, damage, green, r20 = (observation.shadow_drawdown, observation.damaged_breadth,
                             observation.green_breadth, observation.shadow_r20)
    for value in (damage, green):
        if _finite(value) and not 0 <= value <= 1:
            raise ValueError('invalid owned breadth fraction')
    impaired = (all(_finite(v) for v in (dd, damage, green))
                and dd <= RULE['entry_drawdown'] and damage >= RULE['entry_damage']
                and green <= RULE['entry_green'])
    healthy = (all(_finite(v) for v in (r20, damage, green))
               and r20 > RULE['recovery_core_r20_above']
               and damage <= RULE['recovery_damage'] and green >= RULE['recovery_green'])
    active, entry, recovery = before.active, 0, 0
    reason = 'OWNED_NORMAL'
    if active:
        recovery = before.recovery_streak + 1 if healthy else 0
        if recovery >= RULE['recovery_sessions']:
            active, recovery, reason = False, 0, 'OWNED_RECOVERED'
        else:
            reason = 'OWNED_IMPAIRMENT_HELD'
    else:
        entry = before.entry_streak + 1 if impaired else 0
        if entry >= RULE['entry_sessions']:
            active, entry, reason = True, 0, 'OWNED_IMPAIRMENT_ENTER'
    after = OwnedImpairmentState(active=active, entry_streak=entry,
        recovery_streak=recovery, last_session=session)
    ceiling = RULE['active_ceiling'] if active else 1.
    return after.model_dump(), dict(target=min(base_target, ceiling), reason=reason,
        active=active, impaired=bool(impaired), healthy=bool(healthy),
        parent_target=base_target, ceiling=ceiling,
        entry_streak=entry, recovery_streak=recovery)
