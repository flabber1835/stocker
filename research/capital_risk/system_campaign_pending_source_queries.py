"""Separate held/pending source-only query family; no monetary input authority."""
from copy import deepcopy
from datetime import date
import hashlib,json
from pathlib import Path
from typing import Annotated,Literal
from pydantic import Field,StrictInt,StrictBool,model_validator
from system_campaign_explicit_source_queries import ExactModel,Digest,Session,Security

HERE=Path(__file__).parent
CATALOG='system-campaign-p05-own1132-srra-pending-source-queries.json'
CATALOG_SHA='17d9905aec728f3cca311e9eb11324b716808bae5ee23a65376f7e5e8d654da1'

def need(value,label):
    if not value:raise ValueError('PENDING_SOURCE_QUERY_'+label)

def sha(raw):return hashlib.sha256(raw).hexdigest()

class Position(ExactModel):
    slot_id:Annotated[StrictInt,Field(ge=0)]
    ticker:str=Field(min_length=1)
    quantity:Annotated[StrictInt,Field(gt=0)]
    entry_date:Session

class Pending(ExactModel):
    pending_sessions:Annotated[StrictInt,Field(ge=0,le=0)]
    stale_at_event:Annotated[StrictInt,Field(ge=0,le=0)]
    native_term_sha256:Digest
    unresolved:StrictBool

class Native(ExactModel):
    ticker:str=Field(min_length=1)
    security_id:Security
    session:Session
    native_session:Session
    native_term_sha256:Digest
    parent_positions:Annotated[list[Position],Field(min_length=1,max_length=55)]
    pending_at_parent:Pending

class Additional(ExactModel):
    ticker:str=Field(min_length=1)
    security_id:Security
    session:Session
    source_observation_sha256:Digest
    parent_positions:Annotated[list[Position],Field(min_length=1,max_length=55)]

class Scope(ExactModel):
    parent_outer_sha256:Digest
    parent_cursor:Session
    terms:Annotated[list[Native],Field(min_length=1,max_length=1)]
    additional_rows:Annotated[list[Additional],Field(min_length=1,max_length=1)]

    @model_validator(mode='after')
    def exact_consumed_native_and_actual_held_role(self):
        term,=self.terms;extra,=self.additional_rows;pending=term.pending_at_parent
        dates=[self.parent_cursor,term.session,term.native_session,extra.session,*[p.entry_date for p in term.parent_positions]]
        need(all(date.fromisoformat(day).isoformat()==day for day in dates),'CANONICAL_SCOPE_DATES')
        need(term.session<term.native_session==extra.session==self.parent_cursor
             and pending.native_term_sha256==term.native_term_sha256 and pending.unresolved is False,
             'ONLY_EXACT_NATIVE_AT_PARENT_WITH_ZERO_PENDING_AGE')
        need((extra.ticker,extra.security_id)==(term.ticker,term.security_id)
             and extra.parent_positions==term.parent_positions
             and len({p.slot_id for p in term.parent_positions})==len(term.parent_positions)
             and all(p.ticker==term.ticker and p.entry_date<=self.parent_cursor for p in term.parent_positions),
             'EXACT_NONEMPTY_HELD_POSITION_AND_NATIVE_DAY_ROW_SCOPE')
        return self

class Query(ExactModel):
    arm:Literal['P05']
    root_admission_sha256:Digest
    parent_completed:Annotated[StrictInt,Field(gt=0)]
    parent_input_count:Annotated[StrictInt,Field(gt=0)]
    scope:Scope

class Registry(ExactModel):
    schema_id:Literal['research.explicit-own-pending-source-queries/1']=Field(alias='schema')
    financial_authority:StrictBool
    input_adopted:StrictBool
    queries:Annotated[list[Query],Field(min_length=1,max_length=1)]

    @model_validator(mode='after')
    def source_only(self):
        need(self.financial_authority is self.input_adopted is False,'SOURCE_ROLES_GRANT_NO_INPUT_OR_FINANCIAL_AUTHORITY')
        return self

def registry():
    raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'EXACT_QUALIFIED_CATALOG_BYTES')
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
             and (root['outer_sha256'],root['selected_session'],root['measured_closes'],len(root['repairs']))==
                 (scope['parent_outer_sha256'],scope['parent_cursor'],query.parent_completed,query.parent_input_count),
             'EXACT_CURRENT_ROOT_FULL_INPUT_COUNT_AXIS_AND_AUTHORITY')
        result[query.arm]=scope
    return result

def source_names():return (Path(__file__).name,CATALOG)
