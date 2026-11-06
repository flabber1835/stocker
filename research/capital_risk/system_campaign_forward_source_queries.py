"""Bounded own-parent future source identities with exact current held roles."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Annotated,Literal
from pydantic import Field,StrictBool,StrictInt,model_validator
from system_campaign_pending_native_source_queries_v2 import ExactModel,Digest,Session,Security,Position
from system_campaign_facts import sha
from full_system_benchmark import need

HERE=Path(__file__).parent
CATALOG='system-campaign-p05-own1152-forward-source-queries.json'
CATALOG_SHA='8c42192d198c63d74c81d11afbe60c0c383d6d9595cd8bb3e9c73e2889e60115'

class Native(ExactModel):
    ticker:str=Field(min_length=1)
    security_id:Security
    session:Session
    native_session:Session
    native_term_sha256:Digest
    parent_positions:Annotated[list[Position],Field(max_length=55)]

class Scope(ExactModel):
    parent_outer_sha256:Digest
    parent_cursor:Session
    terms:Annotated[list[Native],Field(min_length=1,max_length=128)]
    additional_rows:Annotated[list[dict],Field(max_length=0)]

    @model_validator(mode='after')
    def exact_future_native_and_current_roles(self):
        days=[self.parent_cursor,*[t.session for t in self.terms],*[t.native_session for t in self.terms],
              *[p.entry_date for t in self.terms for p in t.parent_positions]]
        need(all(date.fromisoformat(day).isoformat()==day for day in days),'FORWARD_SOURCE_CANONICAL_DATES')
        need(len({t.security_id for t in self.terms})==len(self.terms)
             and all(self.parent_cursor<t.session<t.native_session for t in self.terms),
             'FORWARD_SOURCE_UNIQUE_FUTURE_NATIVE_IDENTITIES')
        slots=[p.slot_id for t in self.terms for p in t.parent_positions]
        need(len(slots)==len(set(slots)) and all(p.entry_date<=self.parent_cursor for t in self.terms for p in t.parent_positions)
             and self.additional_rows==[],'FORWARD_SOURCE_EXACT_CURRENT_POSITIONS_NOT_FUTURE_PREDICTIONS')
        return self

class Query(ExactModel):
    arm:Literal['P05']
    root_admission_sha256:Digest
    parent_completed:Annotated[StrictInt,Field(gt=0)]
    parent_input_count:Annotated[StrictInt,Field(gt=0)]
    scope:Scope

class Registry(ExactModel):
    schema_id:Literal['research.explicit-own-forward-source-queries/1']=Field(alias='schema')
    financial_authority:StrictBool
    input_adopted:StrictBool
    queries:Annotated[list[Query],Field(min_length=1,max_length=1)]

    @model_validator(mode='after')
    def source_only(self):
        need(self.financial_authority is self.input_adopted is False,'FORWARD_SOURCE_NO_INPUT_OR_FINANCIAL_AUTHORITY')
        return self

def registry():
    raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'FORWARD_SOURCE_EXACT_DECLARED_CATALOG_BYTES')
    return Registry.model_validate_json(raw)

def selected_scopes(original,arms,*,enabled,root_lookup):
    need(type(enabled) is bool,'FORWARD_SOURCE_EXPLICIT_READONLY_FLAG')
    result=deepcopy(original)
    if not enabled:return result
    for query in registry().queries:
        if query.arm not in arms:continue
        root=root_lookup(query.arm)
        if root['root_admission_sha256']!=query.root_admission_sha256:continue
        scope=query.scope.model_dump()
        need(root['arm']==query.arm and root['financial_authority'] is False
             and (root['outer_sha256'],root['selected_session'],root['measured_closes'],len(root['repairs']))==
                 (scope['parent_outer_sha256'],scope['parent_cursor'],query.parent_completed,query.parent_input_count),
             'FORWARD_SOURCE_EXACT_CURRENT_ROOT_AXIS_FULL_INPUT_COUNT_AND_AUTHORITY')
        result[query.arm]=scope
    return result

def source_names():return (Path(__file__).name,CATALOG)
