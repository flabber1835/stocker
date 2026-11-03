"""P01-only authenticated evidence export and nonfinancial public receipts."""
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile

from full_system_benchmark import need
from seal import decrypt,sha256_file
from system_campaign_pxd_financial_body import function
import system_campaign_evidence_export as original

STAGE='campaign-disposable-discovery'
MARKER=b'P01 export qualification: synthetic marker only.\n'
PUBLIC_FIELDS=frozenset(('schema','authority','financial_authority','account_performance_computed',
    'production_contacted','arm','stage','run_id','head','request_sha256','protocol_sha256',
    'strict_parent_outer_sha256','strict_parent_run_id','status','actual_discovery_started',
    'known_fact_index_sha256','checkpoint_cadence','qualification_worker','worker',
    'discovery_launch_attempted','encrypted_output','export_error','pre_export_status',
    'export_qualification_sha256','encrypted_output_exported'))
STOP_FIELDS=frozenset(('stopped','exit_code','oom_killed','wait_error'))
ASSET_FIELDS=frozenset(('name','bytes','sha256','manifest_sha256','compression'))


def adapter():
    return function('system_campaign_evidence_export.py','seal',{
        'campaign-factual-suffix':STAGE,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'P01_DISCOVERY_EXACT_EXPORT_SCOPE'},vars(original))


def sealed(root,target,key,request):
    protocol=json.loads(request.read_bytes())['protocol_sha256']
    return adapter()(root,target,key,request,'P01',stage=STAGE,protocol_sha256=protocol)


def qualify_export(path,request):
    """Actual encryption/authentication on a fixed marker; no market data."""
    path=Path(path);path.mkdir(mode=0o700)
    source=path/'source';source.mkdir(mode=0o700);(source/'marker.txt').write_bytes(MARKER)
    key=os.urandom(32)
    try:
        target=path/'probe.tar.crseal';asset=sealed(source,target,key,request)
        plain=path/'probe.tar.gz';decrypt(target,plain,key,asset['sha256'])
        with tarfile.open(plain,mode='r:gz') as tar:
            need(tar.getnames()==['manifest.json','marker.txt'],'P01_EXPORT_PROBE_EXACT_MEMBERS')
            raw=tar.extractfile('manifest.json').read();manifest=json.loads(raw)
            need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256']
                 and manifest['schema']=='research.full-system-output/1' and manifest['arm']=='P01'
                 and manifest['stage']==STAGE and manifest['run_id']==os.environ['GITHUB_RUN_ID']
                 and manifest['head']==os.environ['GITHUB_SHA']
                 and manifest['request_sha256']==sha256_file(request)
                 and manifest['protocol_sha256']==json.loads(request.read_bytes())['protocol_sha256'],
                 'P01_EXPORT_PROBE_EXACT_AUTHENTICATED_MANIFEST')
            need(tar.extractfile('marker.txt').read()==MARKER
                 and manifest['members']=={'marker.txt':dict(bytes=len(MARKER),sha256=hashlib.sha256(MARKER).hexdigest())},
                 'P01_EXPORT_PROBE_ACTUAL_MARKER_ROUNDTRIP')
    finally:key=None
    return dict(status='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED',
        request_sha256=sha256_file(request),source_adapter_sha256=sha256_file(Path(__file__)),
        cipher_sha256=asset['sha256'],manifest_sha256=asset['manifest_sha256'],
        synthetic_marker_only=True,market_or_financial_state_processed=False,production_contacted=False)


def write_public_receipt(path,receipt):
    need(set(receipt)<=PUBLIC_FIELDS and receipt['arm']=='P01' and receipt['stage']==STAGE
         and receipt['financial_authority'] is False and receipt['account_performance_computed'] is False
         and receipt['production_contacted'] is False,'P01_PUBLIC_RECEIPT_ONLY_DECLARED_NONFINANCIAL_FIELDS')
    nested={'qualification_worker','worker','encrypted_output','export_error'}
    need(all(type(v) in (str,int,bool,type(None)) for k,v in receipt.items() if k not in nested),
         'P01_PUBLIC_SCALAR_METADATA_NO_NESTED_FINANCIAL_PAYLOAD')
    for name in ('qualification_worker','worker'):
        if name in receipt:
            need(set(receipt[name])==STOP_FIELDS,'P01_PUBLIC_STOP_ONLY_DECLARED_METADATA')
            need(type(receipt[name]['stopped']) is bool and type(receipt[name]['oom_killed']) is bool
                 and type(receipt[name]['exit_code']) is int
                 and type(receipt[name]['wait_error']) in (str,type(None)), 'P01_PUBLIC_STOP_SCALAR_TYPES')
    if 'encrypted_output' in receipt:
        need(set(receipt['encrypted_output'])==ASSET_FIELDS,'P01_PUBLIC_ASSET_ONLY_DECLARED_METADATA')
    if 'export_error' in receipt:
        need(set(receipt['export_error'])=={'type','code'},'P01_PUBLIC_EXPORT_ERROR_ONLY_CODE')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.partial')
    with temporary.open('w',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(receipt,sort_keys=True,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def finish_export(receipt,root,path,key,request,*,known):
    """Retain truthful public stop metadata even if encryption refuses."""
    receipt['encrypted_output_exported']=False
    write_public_receipt(path,receipt)
    if known:
        receipt['pre_export_status']=receipt['status']
        try:
            receipt['encrypted_output']=sealed(root,path.parent/'p01-discovery.tar.crseal',key,request)
            receipt['encrypted_output_exported']=True
        except Exception as error:
            code=str(error)
            receipt['export_error']=dict(type=type(error).__name__,
                code=code if re.fullmatch(r'REFUSED_[A-Z0-9_]+',code) else 'EXPORT_OPERATION_FAILED')
            receipt['status']='KNOWN_STOP_EXPORT_REFUSED_NO_PLAINTEXT_FALLBACK'
    write_public_receipt(path,receipt)
    return receipt
