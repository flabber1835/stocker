"""Arm-scoped actual encryption probes and durable nonfinancial receipts."""
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import system_campaign_evidence_export as original
import system_campaign_p01_discovery_export as proven
from system_campaign_parallel_discovery import ARMS,body,literals,compile_body

STAGE=proven.STAGE
MARKER=proven.MARKER


def seal_adapter(arm):
    need(arm in ARMS,'PARALLEL_EXPORT_ONLY_SELECTED_ARMS')
    fn=literals(body('system_campaign_evidence_export.py','seal'),{
        'campaign-factual-suffix':STAGE,'P02':arm,
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'PARALLEL_DISCOVERY_EXACT_ARM_EXPORT_SCOPE'})
    return compile_body(fn,vars(original))


def sealed(root,target,key,request,arm):
    return seal_adapter(arm)(root,target,key,request,arm,stage=STAGE,
        protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])


def qualify_export(path,request,arm):
    need(arm in ARMS,'PARALLEL_PROBE_ONLY_SELECTED_ARM')
    fn=literals(body('system_campaign_p01_discovery_export.py','qualify_export'),{'P01':arm})
    proof=compile_body(fn,dict(vars(proven),sealed=lambda *a:sealed(*a,arm)))(path,request)
    proof.update(status='PARALLEL_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED',arm=arm,
        retained_export_body_sha256=proof['source_adapter_sha256'],
        source_adapter_sha256=sha256_file(Path(__file__)))
    return proof


def write_public_receipt(path,receipt):
    arm=receipt.get('arm');need(arm in ARMS,'PARALLEL_PUBLIC_ONLY_SELECTED_ARM')
    fn=literals(body('system_campaign_p01_discovery_export.py','write_public_receipt'),{'P01':arm})
    return compile_body(fn,vars(proven))(path,receipt)


def finish_export(receipt,root,path,key,request,*,known):
    arm=receipt['arm'];need(arm in ARMS,'PARALLEL_FINISH_ONLY_SELECTED_ARM')
    fn=literals(body('system_campaign_p01_discovery_export.py','finish_export'),{
        'p01-discovery.tar.crseal':'discovery.tar.crseal'})
    return compile_body(fn,dict(vars(proven),sealed=lambda *a:sealed(*a,arm),
        write_public_receipt=write_public_receipt))(receipt,root,path,key,request,known=known)
