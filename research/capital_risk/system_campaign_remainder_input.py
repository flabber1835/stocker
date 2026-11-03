"""Own-bound final-event input; ordinary actions still use the canonical parser."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from system_campaign_uncertainty_input import Digest, Evidence, sha
from system_campaign_uncertainty_math import require

SCHEMA = 'research.p02-remainder-terminal-input/1'
FIRST = '2025-05-16'
ORDINARY = 'remainder-terminal-ordinary-overlay.json'
PRIVATE = 'remainder-terminal-private.json'
CATALOG = 'system-campaign-remainder-terminal-facts.json'


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'REMAINDER_DUPLICATE_JSON_KEY')
        value[key] = item
    return value


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha(encoded(value))


class Parent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    file_sha256: Digest
    outer_sha256: Digest
    inner_sha256: Digest
    state_sha256: Digest
    input_sha256: Digest
    source_sha256: Digest
    session: Literal['2025-04-30']


class RemainderInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.p02-remainder-terminal-input/1'] = Field(alias='schema')
    predecessor_checkpoint_sha256: Digest
    parent: Parent
    catalog_sha256: Digest
    private_sha256: Digest
    ordinary_overlay_sha256: Digest
    treatment: Literal['CANONICAL_ACTIONS_AND_UNOWNED_COMPLETE_OUTCOME_RANGE_PROOF']
    source_evidence: list[Evidence] = Field(min_length=4, max_length=32)
    _file_sha256: str | None = PrivateAttr(default=None)
    _resume_session: str | None = PrivateAttr(default=None)
    _ordinary: object = PrivateAttr(default=None)

    @property
    def earliest_affected_session(self):
        return FIRST

    @property
    def sha256(self):
        return self._file_sha256


def parent_binding(cp, file_raw, expected_file_sha256):
    require(sha(file_raw) == expected_file_sha256, 'REMAINDER_OWN_PARENT_GZIP')
    return dict(file_sha256=sha(file_raw), outer_sha256=cp['sha256'],
        inner_sha256=cp['run']['checkpoint_sha256'], state_sha256=cp['run']['state_sha256'],
        input_sha256=cp['run']['input_sha256'], source_sha256=digest(cp['base']['sources']),
        session=cp['source_cursor'])


def parse(path, *, resume_session, predecessor_checkpoint_sha256, parent,
          expected_evidence, catalog_sha256, private_sha256, ordinary_sha256):
    raw = Path(path).read_bytes()
    require(len(raw) <= 131072, 'REMAINDER_INPUT_SIZE')
    obj = RemainderInput.model_validate(json.loads(raw, object_pairs_hook=unique))
    require(type(resume_session) is str
            and date.fromisoformat(resume_session).isoformat() == resume_session
            and resume_session == parent['session'] and resume_session < FIRST,
            'REMAINDER_EXACT_UNCONSUMED_PARENT_CURSOR')
    require(obj.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256 == parent['inner_sha256']
            and obj.parent.model_dump() == parent, 'REMAINDER_EXACT_OWN_PARENT_IDENTITIES')
    refs = [v.model_dump() for v in obj.source_evidence]
    require(refs == expected_evidence and len({v['reference'] for v in refs}) == len(refs),
            'REMAINDER_EXACT_EVIDENCE_AND_IMPLEMENTATION')
    require(obj.catalog_sha256 == catalog_sha256 and obj.private_sha256 == private_sha256
            and obj.ordinary_overlay_sha256 == ordinary_sha256,
            'REMAINDER_EXACT_CATALOG_PRIVATE_AND_CANONICAL_OVERLAY')
    obj._file_sha256, obj._resume_session = sha(raw), resume_session
    return obj


def require_no_position(state, sid):
    """Outstanding receivables count; settled historical ledger entries do not."""
    require(isinstance(state.wealth_core, dict) and isinstance(state.pending, (tuple, list))
            and isinstance(state.ledger, dict), 'REMAINDER_ACTUAL_POSITION_AND_LEDGER_SCHEMA')
    episodes = state.wealth_core.get('episodes')
    require(isinstance(episodes, dict) and all(isinstance(v, dict) and 'security_id' in v
            and v['security_id'] != sid for v in episodes.values()), 'REMAINDER_SENSOR_MUST_NOT_BE_OWNED')
    require(all(isinstance(v, dict) and 'security_id' in v and v['security_id'] != sid
                for v in state.pending), 'REMAINDER_SENSOR_MUST_NOT_BE_ORDERED')
    claims = state.ledger.get('receivables')
    require(isinstance(claims, list) and all(isinstance(v, dict) and 'security_id' in v
            and v['security_id'] != sid for v in claims), 'REMAINDER_SENSOR_MUST_NOT_HAVE_OUTSTANDING_ENTITLEMENT')
    # Forward cash observations/pending entitlements are a second claim surface.
    evidence = getattr(state, 'last_evidence', None)
    require(isinstance(evidence, dict), 'REMAINDER_ACTUAL_LAST_EVIDENCE_SCHEMA')
    cash = evidence.get('cash_distributions')
    require(isinstance(cash, dict) and isinstance(cash.get('pending'), list),
            'REMAINDER_ACTUAL_FORWARD_CASH_SCHEMA')
    require(all(isinstance(v, dict) and 'security_id' in v and v['security_id'] != sid
                for v in cash['pending']), 'REMAINDER_SENSOR_MUST_NOT_HAVE_FORWARD_CASH_CLAIM')


class InputCodec:
    def __init__(self, root, parent, evidence, catalog, natives):
        self.root, self.parent = Path(root), deepcopy(parent)
        self.evidence, self.catalog = deepcopy(evidence), deepcopy(catalog)
        self.natives, self.objects = dict(natives), []

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        raw = Path(path).read_bytes()
        if json.loads(raw, object_pairs_hook=unique).get('schema') != SCHEMA:
            return self.original_load(path, resume_session=resume_session,
                predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj = parse(path, resume_session=resume_session,
            predecessor_checkpoint_sha256=predecessor_checkpoint_sha256, parent=self.parent,
            expected_evidence=self.evidence, catalog_sha256=digest(self.catalog),
            private_sha256=sha((self.root / PRIVATE).read_bytes()),
            ordinary_sha256=sha((self.root / ORDINARY).read_bytes()))
        obj._ordinary = self.original_load(self.root / ORDINARY,
            resume_session=resume_session, predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        self.objects.append(obj)
        return obj

    def apply(self, packet, obj):
        if not isinstance(obj, RemainderInput):
            return self.original_apply(packet, obj)
        require(any(obj is v for v in self.objects) and obj.parent.model_dump() == self.parent
                and [v.model_dump() for v in obj.source_evidence] == self.evidence
                and digest(self.catalog) == obj.catalog_sha256,
                'REMAINDER_ONLY_UNCHANGED_ADMITTED_INPUT')
        require(sha((self.root / ORDINARY).read_bytes()) == obj.ordinary_overlay_sha256
                and sha((self.root / PRIVATE).read_bytes()) == obj.private_sha256,
                'REMAINDER_DERIVED_INPUT_BYTES_STILL_BOUND')
        result = self.original_apply(packet, obj._ordinary)
        for case in self.catalog['cases']:
            if case['treatment'] != 'CVR_RANGE' or case['native_session'] == case['core_session']:
                continue
            sid, native, target = case['security_id'], case['native_session'], case['core_session']
            if result.day not in (native, target):
                continue
            terms = [v for v in result.terminal if v.security_id == sid]
            if result.day == native:
                require(len(terms) == 1 and asdict(terms[0]) == asdict(self.natives[sid])
                        and digest(asdict(terms[0])) == case['native_term_sha256'],
                        'REMAINDER_EXACT_INCOMPLETE_NATIVE_BEFORE_RECALENDAR')
                result = replace(result, terminal=tuple(v for v in result.terminal if v.security_id != sid))
            else:
                require(not terms, 'REMAINDER_NO_RECALENDAR_COLLISION')
                result = replace(result, terminal=(*result.terminal, replace(self.natives[sid], session=target)))
        return result

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest, repair
        self.backtest, self.repair = backtest, repair
        self.original_load, self.original_apply = repair.load_repair, backtest.apply_repair
        self.saved_load = backtest.load_repair
        repair.load_repair = backtest.load_repair = self.load
        backtest.apply_repair = self.apply
        return self

    def __exit__(self, *args):
        self.repair.load_repair, self.backtest.load_repair = self.original_load, self.saved_load
        self.backtest.apply_repair = self.original_apply
