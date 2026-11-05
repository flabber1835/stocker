"""Explicit own-root source-only queries; original capture driver stays unchanged."""
from copy import deepcopy
from datetime import date
import hashlib,json
from pathlib import Path
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,StrictBool,model_validator

HERE=Path(__file__).parent
CATALOG='system-campaign-explicit-source-witness-queries.json'
CATALOG_SHA='b9a2f9e47c4899ae36efd6ef813a2c02337ea84ef70dede39d3e4f6d228a3dcb'
Digest=Annotated[str,Field(pattern=r'^[0-9a-f]{64}$')]
Session=Annotated[str,Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
Security=Annotated[str,Field(pattern=r'^[1-9][0-9]*$')]

def need(value,label):
    if not value:raise ValueError('EXPLICIT_SOURCE_QUERY_'+label)

def sha(raw):return hashlib.sha256(raw).hexdigest()

class ExactModel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)

class Native(ExactModel):
    ticker:str=Field(min_length=1)
    security_id:Security
    session:Session
    native_session:Session
    native_term_sha256:Digest
    parent_positions:list[dict]

class Additional(ExactModel):
    ticker:str=Field(min_length=1)
    security_id:Security
    session:Session
    source_observation_sha256:Digest
    parent_positions:list[dict]

class Scope(ExactModel):
    parent_outer_sha256:Digest
    parent_cursor:Session
    terms:Annotated[list[Native],Field(min_length=1,max_length=16)]
    additional_rows:Annotated[list[Additional],Field(max_length=16)]

    @model_validator(mode='after')
    def exact_bounded_future_identities(self):
        days=[self.parent_cursor,*[t.session for t in self.terms],*[t.native_session for t in self.terms],*[t.session for t in self.additional_rows]]
        need(all(date.fromisoformat(day).isoformat()==day for day in days),'CANONICAL_QUERY_DATES')
        need(len({t.security_id for t in self.terms})==len(self.terms)
             and len({(t.session,t.security_id) for t in self.additional_rows})==len(self.additional_rows),
             'UNIQUE_NATIVE_AND_ADDITIONAL_IDENTITIES')
        need(all(self.parent_cursor<t.session<t.native_session and t.parent_positions==[] for t in self.terms)
             and all(self.parent_cursor<t.session and t.parent_positions==[] for t in self.additional_rows),
             'DECLARED_UNCONSUMED_UNHELD_SOURCE_SCOPE')
        need(all(any(a.security_id==t.security_id and a.ticker==t.ticker for t in self.terms) for a in self.additional_rows),
             'ADDITIONAL_ROWS_BELONG_TO_DECLARED_NATIVE')
        return self

class Query(ExactModel):
    arm:Annotated[str,Field(pattern=r'^P(0[0-9]|1[01])$')]
    root_admission_sha256:Digest
    scope:Scope

class Registry(ExactModel):
    schema_id:Literal['research.explicit-own-source-witness-queries/1']=Field(alias='schema')
    financial_authority:StrictBool
    input_adopted:StrictBool
    queries:Annotated[list[Query],Field(min_length=1,max_length=12)]

    @model_validator(mode='after')
    def explicit_source_only(self):
        need(self.financial_authority is self.input_adopted is False,'NO_FINANCIAL_OR_INPUT_AUTHORITY')
        need(len({(q.arm,q.root_admission_sha256) for q in self.queries})==len(self.queries),'UNIQUE_ARM_ROOT_QUERIES')
        return self

def registry():
    raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'EXACT_DECLARED_QUERY_CATALOG_BYTES')
    return Registry.model_validate_json(raw)

def selected_scopes(original,arms,*,enabled,root_lookup):
    need(type(enabled) is bool,'EXPLICIT_READONLY_MODE_FLAG')
    result=deepcopy(original)
    if not enabled:return result
    for query in registry().queries:
        if query.arm not in arms:continue
        root=root_lookup(query.arm)
        if root['root_admission_sha256']!=query.root_admission_sha256:continue
        scope=query.scope.model_dump()
        need(root['arm']==query.arm and root['financial_authority'] is False
             and (root['outer_sha256'],root['selected_session'])==(scope['parent_outer_sha256'],scope['parent_cursor']),
             'EXACT_CURRENT_OWN_ROOT_AXIS_AND_AUTHORITY')
        result[query.arm]=scope
    return result

def source_names():return (Path(__file__).name,CATALOG)
