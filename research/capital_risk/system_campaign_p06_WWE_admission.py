"""Absent-until-real admission prerequisite; transport facts are not a root."""
import json,re
from pathlib import Path
from copy import deepcopy
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p06_WWE173_preconditions as preconditions
HERE=Path(__file__).parent
FILE='P06-WWE12-actual-admission-fact.json'
EXPECTED_SHA='96afb2e7a49532f6aa9b4eb2f3b8f51d3513fdd1f9f0dfee19bf1b91b515daad'
ROOT_SHA='edfe96119e6f8bf833e54189452698bca2bfca65676e2d0a861bb6a9ea69bf0f'
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def fact():
    need(isinstance(EXPECTED_SHA,str) and re.fullmatch('[a-f0-9]{64}',EXPECTED_SHA) is not None
        and isinstance(ROOT_SHA,str) and re.fullmatch('[a-f0-9]{64}',ROOT_SHA) is not None
        and (HERE/FILE).is_file(),'P06_WWE_ABSENT_REAL1426_ADMISSION_FACT_CANNOT_ENABLE_FINANCE')
    raw=(HERE/FILE).read_bytes();need(sha(raw)==EXPECTED_SHA,'P06_WWE_EXACT_REAL1426_ADMISSION_FACT_BYTES')
    value=json.loads(raw);spec=value['root_spec'];admission=spec['root_admission']
    need(value['schema']=='research.P06-WWE12-actual-admission-fact/1' and value['root_admission_sha256']==ROOT_SHA
        and spec['root_admission_sha256']==ROOT_SHA and spec['arm']=='P06' and spec['outer_sha256']==preconditions.OUTER
        and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(1426,'2023-08-31',11)
        and admission['parent_root_admission_sha256']=='28c768af0d50047f04ddd6924c1500bf768cc138f41808cd1c0a0b5321eb64b8'
        and admission['branch_uncertainty_proof']['hosted_canonical_transition_oracle_sha256']=='190de5015b174b76f42786943f87ac5e3100555b660e0e116d7d305a18b71bf8'
        and value['financial_checkpoint_projected'] is value['original_failed_receipt_relabelled'] is False,
        'P06_WWE_REAL1426_FULL11_173_AND_SEPARATE344_ADMISSION_LINEAGE')
    return value
def require(spec):
    value=fact();need(encoded(spec)==encoded(value['root_spec']),'P06_WWE_ONLY_EXACT_FINALLY_ADMITTED1426_ROOT_SPEC')
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);return value
def parent(current,spec):
    value=require(spec);known=preconditions.fact()
    need(current['sha256']==spec['outer_sha256']==known['current_outer_sha256']
        and current['repairs']==spec['repairs']==known['repairs'] and current['base']==spec['base']
        and current['run']['input_sha256']==spec['input_sha256']==known['input_sha256']
        and current['run']['state_sha256']==spec['state_sha256']==known['state_sha256'],
        'P06_WWE_REAL_ADMITTED1426_PARENT_FULL11_NO_ARCHIVE_OR_STATE_SUBSTITUTION')
    return value
def source_names():return (Path(__file__).name,FILE,*preconditions.source_names())
