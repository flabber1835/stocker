"""Typed, own-predecessor-bound uncertainty commitment; never a cash repair."""
import hashlib
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from system_campaign_uncertainty_math import require

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    reference: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sha256: Digest


class LeadershipUncertaintyInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.leadership-uncertainty-input/1'] = Field(alias='schema')
    predecessor_checkpoint_sha256: Digest
    session: Literal['2019-10-22']
    security_id: Literal['941065113449292610']
    sensor_only: Literal[True]
    require_unowned_and_unordered: Literal[True]
    consideration_range: Literal['18<=cash_plus_nontransferable_right<=20']
    treatment: Literal['ALL_EXECUTED_COMPARISONS_MUST_BE_INTERVAL_INVARIANT']
    source_evidence: list[Evidence] = Field(min_length=4, max_length=16)
    _file_sha256: str | None = PrivateAttr(default=None)
    _resume_session: str | None = PrivateAttr(default=None)

    @field_validator('sensor_only', 'require_unowned_and_unordered', mode='before')
    @classmethod
    def exact_true(cls, value):
        require(value is True, 'EXACT_BOOLEAN_SCOPE')
        return value

    @property
    def earliest_affected_session(self):
        return self.session

    @property
    def sha256(self):
        return self._file_sha256


def parse(path, *, resume_session, predecessor_checkpoint_sha256, expected_evidence):
    raw = Path(path).read_bytes()
    require(len(raw) <= 65536, 'INPUT_COMMITMENT_SIZE')
    result = LeadershipUncertaintyInput.model_validate_json(raw)
    require(type(resume_session) is str and date.fromisoformat(resume_session).isoformat() == resume_session,
            'INPUT_CANONICAL_RESUME_SESSION')
    require(result.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256,
            'INPUT_EXACT_OWN_PREDECESSOR')
    require(resume_session < result.session, 'INPUT_EVENT_UNCONSUMED')
    actual = [v.model_dump() for v in result.source_evidence]
    require(actual == expected_evidence and len({v['reference'] for v in actual}) == len(actual),
            'INPUT_EXACT_CONTRACT_IMPLEMENTATION_AND_GATE')
    result._file_sha256 = sha(raw)
    result._resume_session = resume_session
    return result


def require_no_financial_position(prior):
    """No cash/right valuation is supplied to an owned or ordered position."""
    sid = '941065113449292610'
    require(isinstance(prior.wealth_core, dict) and isinstance(prior.pending, (list, tuple)),
            'ACTUAL_FINANCIAL_POSITION_SCHEMA')
    require(isinstance(prior.wealth_core.get('episodes'), dict), 'ACTUAL_EPISODES_SCHEMA')
    require(all(isinstance(v, dict) and 'security_id' in v
                and v['security_id'] != sid for v in prior.wealth_core['episodes'].values()),
            'CVR_MUST_NOT_BE_OWNED')
    require(all(isinstance(v, dict) and 'security_id' in v and v['security_id'] != sid
                for v in prior.pending), 'CVR_MUST_NOT_BE_ORDERED')


class InputCodec:
    """A distinct typed input, preserving every ordinary action-parser guard."""
    def __init__(self, expected_evidence):
        self.evidence = deepcopy(expected_evidence)
        self.objects = []

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        raw = Path(path).read_bytes()
        # A distinct marker is dispatched to its own strict schema. Ordinary
        # terminal-repair/1 emptiness/completeness guards are never relaxed.
        schema = json.loads(raw).get('schema')
        if schema != 'research.leadership-uncertainty-input/1':
            return self.original_load(path, resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        result = parse(path, resume_session=resume_session,
                       predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,
                       expected_evidence=self.evidence)
        self.objects.append(result)
        return result

    def apply(self, packet, loaded):
        if not isinstance(loaded, LeadershipUncertaintyInput):
            return self.original_apply(packet, loaded)
        require(any(loaded is obj for obj in self.objects), 'ONLY_ADMITTED_UNCERTAINTY_OBJECT')
        require([v.model_dump() for v in loaded.source_evidence] == self.evidence
                and loaded._resume_session < loaded.session, 'UNCHANGED_ADMITTED_UNCERTAINTY_INPUT')
        # The incomplete terminal, every quote and every actual cash/account
        # input remain byte-for-byte as published. A separate certified sensor
        # gateway is required; this codec alone cannot resolve the refusal.
        return packet

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest, repair
        self.backtest, self.repair = backtest, repair
        self.original_load, self.original_apply = repair.load_repair, backtest.apply_repair
        self.saved_backtest_load = backtest.load_repair
        repair.load_repair = backtest.load_repair = self.load
        backtest.apply_repair = self.apply
        return self

    def __exit__(self, *args):
        self.repair.load_repair = self.original_load
        self.backtest.load_repair = self.saved_backtest_load
        self.backtest.apply_repair = self.original_apply
