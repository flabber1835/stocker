"""Exact ABMD calendar and full nominal contingent range, sensor-only."""
from dataclasses import asdict,replace
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,PrivateAttr,field_validator
from system_campaign_uncertainty_input import Digest,Evidence,sha
from system_campaign_uncertainty_math import require

SID='1050970006012443443'
NATIVE='2022-12-21'
DAY='2022-12-22'
SCHEMA='research.abiomed-leadership-uncertainty-input/1'


class AbiomedInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    schema_id:Literal['research.abiomed-leadership-uncertainty-input/1']=Field(alias='schema')
    predecessor_checkpoint_sha256:Digest
    native_session:Literal['2022-12-21']
    session:Literal['2022-12-22']
    security_id:Literal['1050970006012443443']
    native_term_sha256:Digest
    sensor_only:Literal[True]
    require_unowned_and_unordered:Literal[True]
    consideration_range:Literal['380<=cash_plus_nontransferable_right<=415']
    treatment:Literal['RECALENDAR_INCOMPLETE_TERM_AND_CERTIFY_ALL_COMPARISONS']
    source_evidence:list[Evidence]=Field(min_length=6,max_length=20)
    _file_sha256:str|None=PrivateAttr(default=None)
    _resume_session:str|None=PrivateAttr(default=None)

    @field_validator('sensor_only','require_unowned_and_unordered',mode='before')
    @classmethod
    def exact_true(cls,value):
        require(value is True,'ABIOMED_EXACT_BOOLEAN_SCOPE');return value

    @property
    def earliest_affected_session(self):return NATIVE
    @property
    def sha256(self):return self._file_sha256


def unique(pairs):
    value={}
    for key,item in pairs:
        require(key not in value,'ABIOMED_DUPLICATE_INPUT_KEY');value[key]=item
    return value


def parse(path,*,resume_session,predecessor_checkpoint_sha256,expected_evidence,native_sha256):
    raw=Path(path).read_bytes();require(len(raw)<=65536,'ABIOMED_INPUT_SIZE')
    obj=AbiomedInput.model_validate(json.loads(raw,object_pairs_hook=unique))
    require(type(resume_session) is str and date.fromisoformat(resume_session).isoformat()==resume_session
            and resume_session<NATIVE,'ABIOMED_UNCONSUMED_CANONICAL_CURSOR')
    require(obj.predecessor_checkpoint_sha256==predecessor_checkpoint_sha256,'ABIOMED_EXACT_OWN_PREDECESSOR')
    refs=[v.model_dump() for v in obj.source_evidence]
    require(refs==expected_evidence and len({v['reference'] for v in refs})==len(refs)
            and obj.native_term_sha256==native_sha256,'ABIOMED_EXACT_NATIVE_AND_EVIDENCE')
    obj._file_sha256=sha(raw);obj._resume_session=resume_session
    return obj


def require_no_position(prior):
    require(isinstance(prior.wealth_core,dict) and isinstance(prior.pending,(list,tuple)),
            'ABIOMED_ACTUAL_POSITION_SCHEMA')
    episodes=prior.wealth_core.get('episodes')
    require(isinstance(episodes,dict) and all(isinstance(v,dict) and 'security_id' in v
            and v['security_id']!=SID for v in episodes.values()),'ABIOMED_MUST_NOT_BE_OWNED')
    require(all(isinstance(v,dict) and 'security_id' in v and v['security_id']!=SID
            for v in prior.pending),'ABIOMED_MUST_NOT_BE_ORDERED')


class InputCodec:
    def __init__(self,expected_evidence,native):
        self.evidence=deepcopy(expected_evidence);self.native=native;self.objects=[]
        self.native_sha256=sha(json.dumps(asdict(native),sort_keys=True,separators=(',',':'),allow_nan=False).encode())

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes()).get('schema')!=SCHEMA:
            return self.original_load(path,resume_session=resume_session,
                                      predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj=parse(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,
                  expected_evidence=self.evidence,native_sha256=self.native_sha256)
        self.objects.append(obj);return obj

    def apply(self,packet,obj):
        if not isinstance(obj,AbiomedInput):return self.original_apply(packet,obj)
        require(any(obj is v for v in self.objects) and [v.model_dump() for v in obj.source_evidence]==self.evidence
                and obj.native_term_sha256==self.native_sha256,'ABIOMED_ONLY_EXACT_ADMITTED_INPUT')
        if packet.day not in (NATIVE,DAY):return packet
        terms=[v for v in packet.terminal if v.security_id==SID]
        if packet.day==NATIVE:
            require(len(terms)==1 and asdict(terms[0])==asdict(self.native),'ABIOMED_EXACT_ORIGINAL_NATIVE_BYTES')
            return replace(packet,terminal=tuple(v for v in packet.terminal if v.security_id!=SID))
        require(not terms,'ABIOMED_NO_EFFECTIVE_DAY_COLLISION')
        return replace(packet,terminal=(*packet.terminal,replace(self.native,session=DAY)))

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,repair
        self.backtest,self.repair=backtest,repair
        self.original_load,self.original_apply=repair.load_repair,backtest.apply_repair
        self.saved_backtest_load=backtest.load_repair
        repair.load_repair=backtest.load_repair=self.load;backtest.apply_repair=self.apply
        return self

    def __exit__(self,*args):
        self.repair.load_repair=self.original_load;self.backtest.load_repair=self.saved_backtest_load
        self.backtest.apply_repair=self.original_apply
