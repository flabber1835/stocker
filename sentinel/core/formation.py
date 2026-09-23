"""Bounded canonical book formation. Candidate evidence, never GO authority."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.production import warm_session_state
from sentinel.core.session import SessionState
from sentinel.feed import calendar
from sentinel.feed.rolling_contract import Contract, Digest, digest
from sentinel.shadow_runtime import _starting_cash, _warmup_input_identity
from sentinel.strategy import controller_for_identity


class FormationRefused(ValueError):
    pass


class FormationPlan(Contract):
    schema_id: Literal['sentinel.historical-formation/1'] = Field(
        default='sentinel.historical-formation/1', alias='schema')
    end: str
    capital: str = '50000'
    warmup_sessions: Literal[252] = 252
    formation_sessions: Literal[126] = 126
    strategy: dict
    source_sha256: Digest

    @field_validator('capital')
    @classmethod
    def exact_capital(cls, value):
        return format(_starting_cash(value), 'f')

    @model_validator(mode='after')
    def supported(self):
        controller_for_identity(self.strategy)
        if calendar.previous_sessions(self.end, 1) != [self.end]:
            raise ValueError('formation endpoint must be an XNYS session')
        return self

    @property
    def axis(self):
        return calendar.previous_sessions(self.end, self.warmup_sessions + self.formation_sessions)


class Formation:
    """One canonical book; caller owns storage and source admission.

    Input hashes bind the normalized material, not its truth or completeness.
    These checkpoints deliberately cannot be used as a shadow GO receipt.
    """

    def __init__(self, plan: FormationPlan, window, *, data_version: int):
        self.plan = FormationPlan.model_validate(plan.model_dump(by_alias=True))
        self.axis = self.plan.axis
        if list(window.sessions) != self.axis[:252]:
            raise FormationRefused('FORMATION_WARMUP_AXIS_CHANGED')
        if set(window.bars_by_session) != set(window.sessions):
            raise FormationRefused('FORMATION_WARMUP_COVERAGE_CHANGED')
        if any(not window.bars_by_session[s] for s in window.sessions):
            raise FormationRefused('FORMATION_WARMUP_EMPTY_SESSION')
        timeline = getattr(window, 'metadata_timeline', None)
        if timeline is None or list(timeline.sessions) != window.sessions:
            raise FormationRefused('FORMATION_CAUSAL_METADATA_REQUIRED')
        self.controller = controller_for_identity(self.plan.strategy)
        initial = SessionState.fresh(starting_cash=float(Decimal(self.plan.capital)),
            controller=Controller(self.controller), strategy_identity=self.plan.strategy)
        self.state = warm_session_state(initial, window, publication_version=data_version)
        self.warmup_identity = _warmup_input_identity(window, window.sessions, prospective_witness=False)
        self.count = 0
        self.chain = digest(dict(plan=self.plan.model_dump(by_alias=True),
                                 warmup=self.warmup_identity, state=self.state.state_hash))

    @property
    def complete(self):
        return self.count == self.plan.formation_sessions

    def advance(self, published):
        if self.complete:
            raise FormationRefused('FORMATION_ALREADY_COMPLETE')
        if published.session != self.axis[252 + self.count]:
            raise FormationRefused('FORMATION_SESSION_GAP_OR_DUPLICATE')
        # Commit only after the canonical transition and serialization succeed.
        value = asdict(published)
        candidate = advance_session(self.state, published,
            controller_config=self.controller, strategy_identity=self.plan.strategy)
        chain = digest(dict(previous=self.chain, input=digest(value), state=candidate.state_hash))
        self.state, self.chain, self.count = candidate, chain, self.count + 1
        return candidate

    def checkpoint(self):
        value = dict(schema='sentinel.formation-candidate/1', status='NOT_ADMITTED',
            plan=self.plan.model_dump(by_alias=True), count=self.count, chain=self.chain,
            warmup_identity=self.warmup_identity, state=self.state.to_dict(),
            state_sha256=self.state.state_hash)
        return {**value, 'sha256': digest(value)}

    @classmethod
    def resume(cls, value, *, plan: FormationPlan):
        expected = {'schema', 'status', 'plan', 'count', 'chain', 'warmup_identity',
                    'state', 'state_sha256', 'sha256'}
        if not isinstance(value, dict) or set(value) != expected:
            raise FormationRefused('FORMATION_CHECKPOINT_SHAPE_CHANGED')
        if (value['schema'] != 'sentinel.formation-candidate/1' or value['status'] != 'NOT_ADMITTED'
                or value['plan'] != plan.model_dump(by_alias=True)
                or value['sha256'] != digest({k: v for k, v in value.items() if k != 'sha256'})):
            raise FormationRefused('FORMATION_CHECKPOINT_BINDING_CHANGED')
        count = value['count']
        if type(count) is not int or not 0 <= count <= plan.formation_sessions:
            raise FormationRefused('FORMATION_CHECKPOINT_COUNT_CHANGED')
        state = SessionState.from_dict(value['state'])
        cursor = plan.axis[251 + count] if count else None
        if (state.state_hash != value['state_sha256'] or state.last_processed_session != cursor
                or state.strategy_identity != plan.strategy):
            raise FormationRefused('FORMATION_CHECKPOINT_STATE_CHANGED')
        result = cls.__new__(cls)
        result.plan = FormationPlan.model_validate(plan.model_dump(by_alias=True))
        result.axis, result.count, result.state = result.plan.axis, count, state
        result.chain = value['chain']
        result.warmup_identity = deepcopy(value['warmup_identity'])
        result.controller = controller_for_identity(result.plan.strategy)
        return result
