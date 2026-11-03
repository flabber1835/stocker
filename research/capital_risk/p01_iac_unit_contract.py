"""Explicit twelfth input for one continuing common-share unit history."""
import gzip
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,PrivateAttr
from p01_iac_unit_parent import (check_spec,need,sha,digest,OUTER,INNER,STATE,
    INPUT as ORIGINAL_INPUT,ROOT_ADMISSION,SOURCE_RECEIPT,MAP_IDENTITY)

HERE=Path(__file__).parent
SPEC='p01_iac_unit_predecessor.json';FACTS='p01_iac_unit_facts.json';INPUT='p01_iac_unit_input.json'
SCHEMA='research.p01-iac-continuing-unit-input/1'
SOURCE='984687283821901795';CHILD='517224929580411308';OLD_MATCH='369995575874917058'
EVENT='2020-07-01';FIRST=(EVENT,'2020-07-02');END='2021-06-29';MAXIMUM=251
FACTS_SHA='708b94739323faa166cd742fe8bfe40f66b14d14d5153c1c14cf93d4db0d8815'


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'


def unique(pairs):
    out={}
    for key,value in pairs:
        need(key not in out,'NO_DUPLICATE_INPUT_OR_FACT_JSON_KEYS');out[key]=value
    return out


def specification():return check_spec(json.loads((HERE/SPEC).read_bytes(),object_pairs_hook=unique))


def facts():
    raw=(HERE/FACTS).read_bytes();need(sha(raw)==FACTS_SHA,'EXACT_REGISTERED_PRIMARY_UNIT_FACTS')
    value=json.loads(raw,object_pairs_hook=unique)
    need(value['schema']=='research.p01-iac-continuing-unit-facts/1'
         and value['source_security_id']==SOURCE and value['unit_ratio_decimal']=='2.1584'
         and value['unit_ratio_fraction']=='1349/625' and value['event_session']==EVENT
         and value['initial_scope']=='ONLY_SOURCE_PRE_EVENT_UNHELD_NO_ANY_PENDING_EXIT_RESERVATION_OR_CLAIM'
         and value['held_package_or_fraction_settlement_supported'] is False
         and value['financial_input_admitted'] is False,'EXACT_PRIMARY_UNIT_AND_UNHELD_INITIAL_SCOPE')
    return value


class UnitInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    schema_id:Literal['research.p01-iac-continuing-unit-input/1']=Field(alias='schema')
    financial_parent:dict
    predecessor_checkpoint_sha256:Literal[INNER]
    predecessor_state_sha256:Literal[STATE]
    predecessor_input_sha256:Literal[ORIGINAL_INPUT]
    source_successor_receipt_sha256:Literal[SOURCE_RECEIPT]
    source_map_identity_sha256:Literal[MAP_IDENTITY]
    earliest_affected_session:Literal[EVENT]
    source_security_id:Literal[SOURCE]
    unit_ratio_decimal:Literal['2.1584']
    unit_ratio_fraction:Literal['1349/625']
    facts_sha256:Literal[FACTS_SHA]
    facts:dict
    treatment:Literal['PRIMARY_CONTINUING_UNIT_FORWARD_DOMAIN_NOT_CHILD_TOTAL_RETURN']
    pending_scope:Literal['REFUSE_OLD_UNIT_SOURCE_ROLES_AT_EVENT_ALLOW_NEW_UNIT_TRADES_AFTER_EVENT']
    publication_delta_fields:tuple[Literal['signal_close'],Literal['split_ratio']]
    source_or_eligibility_parameters_changed:Literal[False]
    _sha256:str|None=PrivateAttr(default=None)

    @property
    def sha256(self):return self._sha256


def document():
    spec=specification();value=facts()
    return dict(schema=SCHEMA,financial_parent=dict(root_admission_descriptor_sha256=ROOT_ADMISSION,
        outer_sha256=OUTER,inner_sha256=INNER,state_sha256=STATE,input_sha256=ORIGINAL_INPUT,
        source_cursor='2020-06-30',completed=628,original_repairs_sha256=digest(spec['repairs']),
        original_base_sha256=digest(spec['base'])),predecessor_checkpoint_sha256=INNER,
        predecessor_state_sha256=STATE,predecessor_input_sha256=ORIGINAL_INPUT,
        source_successor_receipt_sha256=SOURCE_RECEIPT,source_map_identity_sha256=MAP_IDENTITY,
        earliest_affected_session=EVENT,source_security_id=SOURCE,unit_ratio_decimal='2.1584',
        unit_ratio_fraction='1349/625',facts_sha256=FACTS_SHA,facts=value,
        treatment='PRIMARY_CONTINUING_UNIT_FORWARD_DOMAIN_NOT_CHILD_TOTAL_RETURN',
        pending_scope='REFUSE_OLD_UNIT_SOURCE_ROLES_AT_EVENT_ALLOW_NEW_UNIT_TRADES_AFTER_EVENT',
        publication_delta_fields=['signal_close','split_ratio'],source_or_eligibility_parameters_changed=False)


def parse(path,*,resume_session,predecessor_checkpoint_sha256):
    raw=Path(path).read_bytes();value=json.loads(raw,object_pairs_hook=unique)
    need(len(raw)<=128*1024 and raw==encoded(document()) and value==document() and resume_session=='2020-06-30'
         and predecessor_checkpoint_sha256==INNER,'EXACT_ORIGINAL628_TWELFTH_RAW_DOCUMENT_AND_DESCRIPTOR')
    # JSON arrays are tuples only at this explicit schema boundary.
    value={**value,'publication_delta_fields':tuple(value['publication_delta_fields'])}
    result=UnitInput.model_validate(value);result._sha256=sha(raw);return result


def reused_qualification(old,source_map):
    """Same admitted component bytes; no old synthetic financial execution."""
    spec=specification();entry=spec['reused_action_component'];raw=(Path(old)/entry['member']).read_bytes()
    need(len(raw)==entry['bytes'] and sha(raw)==entry['sha256'],'EXACT_RETAINED_ADMITTED_COMPONENT_GZIP')
    value=json.loads(gzip.decompress(raw))
    flags=('target_independence_qualified','held_target_holding_qualified','ordinary_representation_qualified')
    need(all(value[k] is True for k in flags) and value['held_source_with_target_pending_qualified'] is False
         and value['financial_authority'] is False and value['qualification_state_adopted'] is False
         and value['source_map_identity_sha256']==digest(source_map)
         and all(source_map['successor_all_sources'].get(n)==h for n,h in value['source_files'].items()),
         'REUSE_ONLY_EXACT_SAME516_COMPONENT_SCOPE')
    return dict(**{k:True for k in flags},held_source_with_target_pending_qualified=False,
        component_sha256=entry['sha256'],source_map_identity_sha256=digest(source_map),
        old_synthetic_components_reexecuted=False)
