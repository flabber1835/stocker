"""Strict contingent sensor commitment; no cash valuation or financial runtime."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

SCHEMA = 'research.bounded-contingent-sensor-input/1'
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Session = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
Amount = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]*)(\.[0-9]+)?$')]


def need(value, label):
    if not value:
        raise ValueError('BOUNDED_SENSOR_' + label)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


class ExactModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Event(ExactModel):
    ticker: str = Field(min_length=1)
    security_id: Annotated[str, Field(pattern=r'^[1-9][0-9]*$')]
    native_session: Session
    effective_session: Session
    prior_session: Session
    native_term_sha256: Digest
    currency: Literal['USD']
    upfront_cash_per_share: Amount
    right_lower_per_share: Amount
    right_upper_per_share: Amount
    right_kind: Literal['NONTRANSFERABLE_CONTINGENT_VALUE_RIGHT']
    ownership_scope: Literal['UNOWNED_UNORDERED_SENSOR_ONLY']
    treatment: Literal['EVERY_REACHABLE_CANONICAL_DECISION_MUST_MATCH']
    price_or_probability_selected: Literal[False]
    cash_settlement_authorized: Literal[False]
    historical_causality: Literal['UNVERIFIED']

    @field_validator('price_or_probability_selected', 'cash_settlement_authorized', mode='before')
    @classmethod
    def exact_false(cls, value):
        need(value is False, 'EXACT_FALSE_AUTHORITY')
        return value

    @model_validator(mode='after')
    def bounds_and_clock(self):
        for name in ('native_session', 'effective_session', 'prior_session'):
            value = getattr(self, name)
            need(date.fromisoformat(value).isoformat() == value, 'CANONICAL_EVENT_SESSION')
        need(self.prior_session < self.effective_session and self.native_session <= self.effective_session,
             'EXACT_EVENT_ORDER')
        cash, lower, upper = (Decimal(getattr(self, k)) for k in
                            ('upfront_cash_per_share', 'right_lower_per_share', 'right_upper_per_share'))
        need(cash.is_finite() and lower.is_finite() and upper.is_finite()
             and cash > 0 and 0 <= lower < upper, 'POSITIVE_CASH_AND_NONDEGENERATE_RIGHT')
        return self


class Evidence(ExactModel):
    reference: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sha256: Digest


class BoundedSensorInput(ExactModel):
    schema_id: Literal['research.bounded-contingent-sensor-input/1'] = Field(alias='schema')
    predecessor_checkpoint_sha256: Digest
    event: Event
    source_evidence: Annotated[list[Evidence], Field(min_length=4, max_length=32)]
    _file_sha256: str | None = PrivateAttr(default=None)
    _resume_session: str | None = PrivateAttr(default=None)

    @property
    def earliest_affected_session(self):
        return self.event.native_session

    @property
    def sha256(self):
        return self._file_sha256


def parse(path, *, resume_session, predecessor_checkpoint_sha256, expected_event, expected_evidence):
    raw = Path(path).read_bytes()
    need(len(raw) <= 65536, 'INPUT_SIZE')
    obj = BoundedSensorInput.model_validate_json(raw)
    need(type(resume_session) is str and date.fromisoformat(resume_session).isoformat() == resume_session
         and resume_session < obj.event.native_session, 'UNCONSUMED_CANONICAL_CURSOR')
    need(obj.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256, 'EXACT_OWN_PREDECESSOR')
    need(obj.event.model_dump() == expected_event, 'EXACT_QUALIFIED_EVENT')
    rows = [e.model_dump() for e in obj.source_evidence]
    need(rows == expected_evidence and len({e['reference'] for e in rows}) == len(rows), 'EXACT_SOURCE_EVIDENCE')
    obj._file_sha256, obj._resume_session = sha(raw), resume_session
    return obj


def require_no_position(prior, sid):
    need(isinstance(prior.wealth_core, dict) and isinstance(prior.pending, (list, tuple)), 'ACTUAL_POSITION_SCHEMA')
    episodes = prior.wealth_core.get('episodes')
    need(isinstance(episodes, dict) and all(isinstance(v, dict) and 'security_id' in v
         and v['security_id'] != sid for v in episodes.values()), 'MUST_NOT_BE_OWNED')
    need(all(isinstance(v, dict) and 'security_id' in v and v['security_id'] != sid
             for v in prior.pending), 'MUST_NOT_BE_ORDERED')


class InputCodec:
    def __init__(self, expected_event, expected_evidence, native):
        Event.model_validate(expected_event)
        need(digest(asdict(native)) == expected_event['native_term_sha256']
             and native.security_id == expected_event['security_id']
             and native.session == expected_event['native_session']
             and native.cash_per_share is None and not native.completeness(0)[0], 'EXACT_INCOMPLETE_NATIVE')
        self.event, self.evidence = deepcopy(expected_event), deepcopy(expected_evidence)
        self.native, self.objects = native, []

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes()).get('schema') != SCHEMA:
            return self.original_load(path, resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj = parse(path, resume_session=resume_session, predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,
                    expected_event=self.event, expected_evidence=self.evidence)
        self.objects.append(obj)
        return obj

    def apply(self, packet, obj):
        if not isinstance(obj, BoundedSensorInput):
            return self.original_apply(packet, obj)
        need(any(obj is value for value in self.objects) and obj.event.model_dump() == self.event
             and [e.model_dump() for e in obj.source_evidence] == self.evidence, 'ONLY_EXACT_ADMITTED_OBJECT')
        native, day, sid = (self.event[k] for k in ('native_session', 'effective_session', 'security_id'))
        if packet.day not in (native, day):
            return packet
        terms = [t for t in packet.terminal if t.security_id == sid]
        if packet.day == native:
            need(len(terms) == 1 and asdict(terms[0]) == asdict(self.native), 'EXACT_NATIVE_PACKET')
            if native == day:
                return packet
            return replace(packet, terminal=tuple(t for t in packet.terminal if t.security_id != sid))
        need(not terms, 'NO_RECALENDAR_COLLISION')
        return replace(packet, terminal=(*packet.terminal, replace(self.native, session=day)))

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest, repair
        self.backtest, self.repair = backtest, repair
        self.original_load, self.original_apply = repair.load_repair, backtest.apply_repair
        self.saved_backtest_load = backtest.load_repair
        need(self.saved_backtest_load == self.original_load, 'FULL_INSTALLED_LOADER_CHAIN')
        repair.load_repair = backtest.load_repair = self.load
        backtest.apply_repair = self.apply
        return self

    def __exit__(self, *args):
        self.repair.load_repair, self.backtest.load_repair = self.original_load, self.saved_backtest_load
        self.backtest.apply_repair = self.original_apply
