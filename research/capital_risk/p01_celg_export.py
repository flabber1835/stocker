"""Actual approved AES-GCM path with a distinct synthetic-component scope."""
import ast
import json
import os
from pathlib import Path
import re

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from system_campaign_pxd_financial_body import function
import system_campaign_evidence_export as seal_source
import system_campaign_p01_discovery_export as marker_source
import p01_action_clock_export as receipt_source

HERE=Path(__file__).parent
PRIOR='p01_clock_input_request.json'
PRIOR_SHA='a830b2b3fdff69b66810f8c2ced465b83ed47cda7a530f0acd214a46f5303f81'
STAGE='campaign-p01-celg-synthetic-component'
AUTHORITY='QUALIFICATION_ONLY_NOT_FINANCIAL_AUTHORITY'
PUBLIC=frozenset(('schema','arm','stage','authority','financial_authority','production_contacted',
    'run_id','head','request_sha256','protocol_sha256','source_parent_outer_sha256','status',
    'worker','encrypted_output','encrypted_output_exported','export_error','export_qualification_sha256',
    'capacity_receipt_sha256','pre_export_status'))

def pinned(module,name):
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'CELG_EXPORT_EXACT_FROZEN_P01_418_REQUEST')
    raw=Path(module.__file__).read_bytes()
    need(sha256_file(Path(module.__file__))==json.loads((HERE/PRIOR).read_bytes())['sources'][Path(module.__file__).name],
         'CELG_EXPORT_EXACT_RETAINED_IMPLEMENTATION')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    return fn

def sealed(root,target,key,request):
    call=function('system_campaign_evidence_export.py','seal',{
        'campaign-factual-suffix':STAGE,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'CELG_COMPONENT_EXACT_NEW_SYNTHETIC_EXPORT_SCOPE'},vars(seal_source))
    return call(root,target,key,request,'P01',stage=STAGE,
                protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])

def qualify_export(path,request):
    proof=compile_body(pinned(marker_source,'qualify_export'),dict(vars(marker_source),
        STAGE=STAGE,sealed=sealed,__file__=__file__))(path,request)
    proof.update(status='CELG_COMPONENT_ACTUAL_NEW_SCOPE_MARKER_ROUNDTRIP_PASSED',stage=STAGE,
        financial_or_canonical_state_processed=False,source_adapter_sha256=sha256_file(Path(__file__)))
    return proof

def write_receipt(path,value):
    return compile_body(pinned(receipt_source,'write_receipt'),dict(vars(receipt_source),
        PUBLIC=PUBLIC,STAGE=STAGE))(path,value)

def finish(receipt,root,path,key,request,*,known):
    receipt['encrypted_output_exported']=False;write_receipt(path,receipt)
    if known:
        need(receipt.get('worker',{}).get('stopped') is True,'CELG_EXPORT_ONLY_ACTUAL_KNOWN_STOP')
        receipt['pre_export_status']=receipt['status'];write_receipt(path,receipt)
        try:
            receipt['encrypted_output']=sealed(root,path.parent/'p01-celg-component.tar.crseal',key,request)
            receipt['encrypted_output_exported']=True
        except Exception as error:
            message=str(error)
            receipt['export_error']=dict(type=type(error).__name__,
                code=message if re.fullmatch(r'REFUSED_[A-Z0-9_]+',message) else 'EXPORT_OPERATION_FAILED')
            receipt['status']='KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    write_receipt(path,receipt)
    return receipt
