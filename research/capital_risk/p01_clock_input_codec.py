"""Explicit own438 economic-clock input; ordinary terminal parsers stay strict."""
from copy import deepcopy
from dataclasses import fields, replace
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator
from full_system_benchmark import need
from system_campaign_discovery_context import material, digest
from p01_action_clock_contract import NativeTerm, SID, OLD, NEW

SCHEMA = 'research.p01-economic-clock-input/1'
FACTS = 'p01_clock_input_facts.json'
SHA = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
PARENT = 'c98df4b3c919f725162b86e1c98d67b0f710805774c4c2a37fa4755f55738034'
INNER = '64f4d7d71cfc70f9a8be6d986f9937a76a5845fde93e46bc81e855372b9c24df'
STATE = 'f86859a6b0f02bc16f303c705d6ee56c8e0cb80122f313a1c94392366131dee3'
INPUT = '2ce8b81eb52c779f9bd47f5e81c5c9c2445f3e8714b2c6a1469aac2d456fab81'
NEXT_STATES = {OLD:'e3fd35266ae5f74f82fe2682b6ae5a702dbab529d9df3a3e8bf792c6ddafa84f',
               NEW:'ab0f9b348e806d9fa55e0be3719eb60d7bb92600633efd1ebafda88a8c14cbed'}
HERE = Path(__file__).parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,frozen=True)
    reference: str
    description: str
    sha256: SHA


class ClockInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,frozen=True)
    schema_id: Literal['research.p01-economic-clock-input/1'] = Field(alias='schema')
    predecessor_checkpoint_sha256: Literal[INNER]
    predecessor_outer_sha256: Literal[PARENT]
    predecessor_state_sha256: Literal[STATE]
    predecessor_input_sha256: Literal[INPUT]
    native: NativeTerm
    native_term_sha256: Literal['224c4333e100384a3d8c76ccd67397234fdaca6c9d90fd3753de8b38cd43e973']
    economic_session: Literal['2019-10-01']
    treatment: Literal['CHANGE_ONLY_SOURCE_TERM_SESSION_PRESERVE_UNRESOLVED_CONSIDERATION']
    require_unheld_unordered_both_days: Literal[True]
    require_no_oct1_leadership: Literal[True]
    require_exact_qualified_state_hashes: Literal[True]
    source_evidence: list[Evidence] = Field(min_length=3,max_length=3)
    _file_sha256: str | None = PrivateAttr(default=None)
    _resume_session: str | None = PrivateAttr(default=None)

    @field_validator('require_unheld_unordered_both_days','require_no_oct1_leadership',
                     'require_exact_qualified_state_hashes',mode='before')
    @classmethod
    def exact_boolean_scope(cls,value):
        need(value is True,'P01_CLOCK_INPUT_EXACT_BOOLEAN_SCOPE');return value

    @property
    def earliest_affected_session(self):
        return OLD

    @property
    def sha256(self):
        return self._file_sha256


def evidence():
    facts = (HERE/FACTS).read_bytes();value = json.loads(facts)
    return [dict(reference='research:p01-economic-clock-facts/1',
                 description='Economic date fixed by primary contract and actual settlement disclosure before qualification.',sha256=sha(facts)),
            dict(reference='research:p01-economic-clock-codec/1',
                 description='Separately typed source preimage, input identity and runtime role guards.',sha256=sha(Path(__file__).read_bytes())),
            dict(reference='research:p01-action-clock-component-observations/41370950659',
                 description='Independent two-day component observations; actual worker exit1/final inventory refusal retained; no checkpoint adoption.',
                 sha256=value['component_review_sha256'])]


def document():
    return dict(schema=SCHEMA,predecessor_checkpoint_sha256=INNER,predecessor_outer_sha256=PARENT,
        predecessor_state_sha256=STATE,predecessor_input_sha256=INPUT,native=NativeTerm().model_dump(),
        native_term_sha256=digest(NativeTerm().model_dump()),economic_session=NEW,
        treatment='CHANGE_ONLY_SOURCE_TERM_SESSION_PRESERVE_UNRESOLVED_CONSIDERATION',
        require_unheld_unordered_both_days=True,require_no_oct1_leadership=True,
        require_exact_qualified_state_hashes=True,source_evidence=evidence())


def unique(pairs):
    out = {}
    for k,v in pairs:
        need(k not in out,'P01_CLOCK_INPUT_NO_DUPLICATE_JSON_KEYS');out[k] = v
    return out


def parse(path, *, resume_session, predecessor_checkpoint_sha256):
    raw = Path(path).read_bytes()
    need(len(raw)<=65536,'P01_CLOCK_INPUT_BOUNDED_DOCUMENT')
    value = json.loads(raw,object_pairs_hook=unique)
    need(value == document(),'P01_CLOCK_INPUT_EXACT_DOCUMENT_AND_EVIDENCE')
    obj = ClockInput.model_validate(value)
    need(type(resume_session) is str and date.fromisoformat(resume_session).isoformat()==resume_session
         and resume_session=='2019-09-27' and predecessor_checkpoint_sha256==INNER,
         'P01_CLOCK_INPUT_EXACT_OWN438_UNCONSUMED_BOUNDARY')
    obj._file_sha256=sha(raw);obj._resume_session=resume_session
    return obj


def require_roles(prior, day):
    need(isinstance(prior.wealth_core,dict) and isinstance(prior.wealth_core.get('episodes'),dict)
         and isinstance(prior.pending,(list,tuple)) and isinstance(prior.median5,dict),
         'P01_CLOCK_INPUT_ACTUAL_ROLE_SCHEMA')
    need(all(isinstance(ep,dict) and 'security_id' in ep and ep['security_id']!=SID
             for ep in prior.wealth_core['episodes'].values()),'P01_CLOCK_INPUT_MUST_BE_UNHELD')
    need(all(isinstance(order,dict) and 'security_id' in order and order['security_id']!=SID
             for order in prior.pending),'P01_CLOCK_INPUT_MUST_BE_UNORDERED')
    if day==NEW:
        need(isinstance(prior.median5.get('selected'),list) and SID not in prior.median5['selected'],
             'P01_CLOCK_INPUT_OCT1_MUST_NOT_BE_SELECTED_LEADERSHIP')


class InputCodec:
    def __init__(self,native):
        need(material(native)==NativeTerm().model_dump(),'P01_CLOCK_INPUT_EXACT_NATIVE_OBJECT')
        self.native=native;self.objects=[];self.applied={OLD:0,NEW:0}

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes()).get('schema')!=SCHEMA:
            return self.original_load(path,resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj=parse(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        self.objects.append(obj);return obj

    def apply(self,packet,loaded):
        if not isinstance(loaded,ClockInput):return self.original_apply(packet,loaded)
        need(any(loaded is x for x in self.objects) and loaded.model_dump(by_alias=True)==document(),
             'P01_CLOCK_INPUT_ONLY_UNCHANGED_REGISTERED_OBJECT')
        if packet.day not in (OLD,NEW):return packet
        matches=[t for t in packet.terminal if t.security_id==SID]
        if packet.day==OLD:
            need(len(matches)==1 and material(matches[0])==loaded.native.model_dump(),
                 'P01_CLOCK_INPUT_EXACT_SEP30_PREIMAGE')
            terms=tuple(t for t in packet.terminal if t is not matches[0])
        else:
            need(not matches,'P01_CLOCK_INPUT_NO_OCT1_COLLISION')
            terms=(*packet.terminal,replace(self.native,session=NEW))
        changed=replace(packet,terminal=terms)
        need(all(getattr(packet,f.name) is getattr(changed,f.name) for f in fields(packet)
                 if f.name!='terminal'),'P01_CLOCK_INPUT_ONLY_TERMINAL_PACKET_FIELD')
        self.applied[packet.day]+=1
        return changed

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,repair
        self.backtest,self.repair=backtest,repair
        self.original_load,self.original_apply=repair.load_repair,backtest.apply_repair
        self.saved_load=backtest.load_repair
        repair.load_repair=backtest.load_repair=self.load;backtest.apply_repair=self.apply
        return self

    def __exit__(self,*args):
        self.repair.load_repair=self.original_load;self.backtest.load_repair=self.saved_load
        self.backtest.apply_repair=self.original_apply


class RoleGuard:
    def __init__(self):
        self.observed=[]

    def advance(self,run,published):
        day=published.session
        if day in NEXT_STATES:
            require_roles(run.state,day)
        following=self.original(run,published)
        if day in NEXT_STATES:
            require_roles(following.state,day)
            need(following.state.state_hash==NEXT_STATES[day],
                 'P01_CLOCK_INPUT_FULL_CANONICAL_STATE_MATCHES_QUALIFICATION')
            self.observed.append(dict(session=day,prior_state_sha256=run.state.state_hash,
                state_sha256=following.state.state_hash,unheld=True,unordered=True,
                no_leadership_required=day==NEW))
        return following

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import runtime
        self.runtime=runtime;self.original=runtime.advance;runtime.advance=self.advance;return self

    def __exit__(self,*args):
        self.runtime.advance=self.original
