"""Exact own-prefix proof refinement; its market-packet operation is identity."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator
from system_campaign_uncertainty_input import Digest, Evidence, sha
from system_campaign_uncertainty_math import require

SCHEMA = 'research.controller-outcome-refinement-input/1'
MODE = 'ALL_COMPLETE_CANONICAL_RECOVERY_OUTCOMES_MUST_MATCH'
LINEAGE_FIELDS = frozenset(('predecessor_checkpoint_sha256', 'parent_outer_sha256',
    'parent_file_sha256', 'parent_input_sha256', 'first_affected_session'))


class OutcomeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.controller-outcome-refinement-input/1'] = Field(alias='schema')
    predecessor_checkpoint_sha256: Digest
    parent_outer_sha256: Digest
    parent_file_sha256: Digest
    parent_input_sha256: Digest
    first_affected_session: str
    proof_mode: Literal['ALL_COMPLETE_CANONICAL_RECOVERY_OUTCOMES_MUST_MATCH']
    max_leaves: Literal[64]
    max_nodes: Literal[127]
    max_depth: Literal[16]
    no_point_valuation: Literal[True]
    retained_uncertainty_models_unchanged: Literal[True]
    source_evidence: list[Evidence] = Field(min_length=7, max_length=16)
    _file_sha256: str | None = PrivateAttr(default=None)
    _resume_session: str | None = PrivateAttr(default=None)

    @field_validator('first_affected_session')
    @classmethod
    def canonical_date(cls, value):
        require(date.fromisoformat(value).isoformat() == value, 'OUTCOME_CANONICAL_DATE')
        return value

    @field_validator('max_leaves', 'max_nodes', 'max_depth', mode='before')
    @classmethod
    def exact_budget_type(cls, value):
        require(type(value) is int, 'OUTCOME_EXACT_INTEGER_BUDGET')
        return value

    @field_validator('no_point_valuation', 'retained_uncertainty_models_unchanged', mode='before')
    @classmethod
    def exact_scope(cls, value):
        require(value is True, 'OUTCOME_EXACT_BOOLEAN_SCOPE')
        return value

    @property
    def earliest_affected_session(self):
        return self.first_affected_session

    @property
    def sha256(self):
        return self._file_sha256


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'OUTCOME_DUPLICATE_INPUT_KEY')
        result[key] = value
    return result


def parse(path, *, resume_session, predecessor_checkpoint_sha256, expected_evidence, boundary):
    raw = Path(path).read_bytes()
    require(len(raw) <= 65536, 'OUTCOME_INPUT_SIZE')
    obj = OutcomeInput.model_validate(json.loads(raw, object_pairs_hook=unique))
    require(type(resume_session) is str
            and date.fromisoformat(resume_session).isoformat() == resume_session
            and resume_session == boundary['session'] < obj.first_affected_session,
            'OUTCOME_UNCONSUMED_EXACT_PARENT_CURSOR')
    require(obj.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256 == boundary['inner_sha256']
            and obj.parent_outer_sha256 == boundary['outer_sha256']
            and obj.parent_file_sha256 == boundary['file_sha256']
            and obj.parent_input_sha256 == boundary['input_sha256']
            and obj.first_affected_session == boundary['next_session'],
            'OUTCOME_EXACT_ALL_PARENT_AND_NEXT_SESSION_BINDINGS')
    references = [v.model_dump() for v in obj.source_evidence]
    require(references == expected_evidence
            and len({v['reference'] for v in references}) == len(references),
            'OUTCOME_EXACT_IMPLEMENTATION_EVIDENCE')
    obj._file_sha256, obj._resume_session = sha(raw), resume_session
    return obj


class InputCodec:
    def __init__(self, expected_evidence, boundary):
        self.evidence = deepcopy(expected_evidence)
        self.boundary = deepcopy(boundary)
        self.objects = []

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes()).get('schema') != SCHEMA:
            return self.original_load(path, resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj = parse(path, resume_session=resume_session,
            predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,
            expected_evidence=self.evidence, boundary=self.boundary)
        self.objects.append(obj)
        return obj

    def apply(self, packet, obj):
        if not isinstance(obj, OutcomeInput):
            return self.original_apply(packet, obj)
        require(any(obj is value for value in self.objects)
                and [v.model_dump() for v in obj.source_evidence] == self.evidence
                and obj.parent_input_sha256 == self.boundary['input_sha256'],
                'OUTCOME_ONLY_EXACT_ADMITTED_PROOF_INPUT')
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
