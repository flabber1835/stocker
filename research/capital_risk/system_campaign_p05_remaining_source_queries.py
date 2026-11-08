"""Bounded own-parent future source identities with exact current held roles."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Annotated,Literal
from pydantic import Field,StrictBool,StrictInt,model_validator
from system_campaign_pending_native_source_queries_v2 import ExactModel,Digest,Session,Security,Position
from system_campaign_facts import sha
from full_system_benchmark import need

from system_campaign_explicit_source_queries import Scope as OriginalUnheldScope

HERE=Path(__file__).parent
CATALOG='system-campaign-p05-own1175-remaining-source-queries.json'
CATALOG_SHA='71204afa88c22774bf0562fc59d063883cb8636ad5edf81e8ae3c66ebd348af0'

class Native(ExactModel):
    ticker:str=Field(min_length=1)
    security_id:Security
    session:Session
    native_session:Session
    native_term_sha256:Digest
    parent_positions:Annotated[list[Position],Field(max_length=55)]

class Scope(OriginalUnheldScope):
    terms:Annotated[list[Native],Field(min_length=1,max_length=128)]


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
