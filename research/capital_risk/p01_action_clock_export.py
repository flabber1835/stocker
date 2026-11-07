"""Same proven encryption path, distinct qualification scope and public allowlist."""
import ast
import json
import os
from pathlib import Path
import re

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from system_campaign_pxd_financial_body import function
import system_campaign_evidence_export as original
import system_campaign_p01_discovery_export as probe_source

STAGE = 'campaign-p01-action-clock-qualification'
PUBLIC = frozenset(('schema','arm','stage','authority','financial_authority','production_contacted',
    'run_id','head','request_sha256','protocol_sha256','strict_parent_outer_sha256','status',
    'worker','encrypted_output','encrypted_output_exported','export_error','export_qualification_sha256'))


def sealed(root, target, key, request):
    call = function('system_campaign_evidence_export.py', 'seal', {
        'campaign-factual-suffix':STAGE, 'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'P01_CLOCK_EXACT_EXPORT_SCOPE'}, vars(original))
    return call(root, target, key, request, 'P01', stage=STAGE,
                protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])


def qualify_export(path, request):
    fn, = [n for n in ast.parse(Path(probe_source.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'qualify_export']
    return compile_body(fn, dict(vars(probe_source), STAGE=STAGE, sealed=sealed, __file__=__file__))(path, request)


def write_receipt(path, value):
    need(set(value) <= PUBLIC and value['arm'] == 'P01' and value['stage'] == STAGE
         and value['authority'] == 'QUALIFICATION_ONLY_NOT_FINANCIAL_AUTHORITY'
         and value['financial_authority'] is False and value['production_contacted'] is False,
         'P01_CLOCK_PUBLIC_SCOPE_ALLOWLIST')
    need(all(type(v) in (str,int,bool,type(None)) for k,v in value.items()
             if k not in {'worker','encrypted_output','export_error'}), 'P01_CLOCK_PUBLIC_METADATA_ONLY')
    if 'worker' in value:
        s = value['worker']
        need(set(s) == {'stopped','exit_code','oom_killed','wait_error'} and s['stopped'] is True
             and type(s['exit_code']) is int and type(s['oom_killed']) is bool
             and type(s['wait_error']) in (str,type(None)), 'P01_CLOCK_EXACT_PUBLIC_STOP_FIELDS')
    if 'encrypted_output' in value:
        need(set(value['encrypted_output']) == {'name','bytes','sha256','manifest_sha256','compression'},
             'P01_CLOCK_EXACT_PUBLIC_ASSET_FIELDS')
    if 'export_error' in value:
        need(set(value['export_error']) == {'type','code'}, 'P01_CLOCK_PUBLIC_ERROR_CLASS_ONLY')
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.partial')
    with pending.open('w',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2)+'\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(pending,path)


def finish(receipt, root, path, key, request, *, known):
    receipt['encrypted_output_exported'] = False; write_receipt(path,receipt)
    if known:
        try:
            receipt['encrypted_output'] = sealed(root, path.parent/'p01-action-clock.tar.crseal', key, request)
            receipt['encrypted_output_exported'] = True
        except Exception as error:
            code = str(error)
            receipt['export_error'] = dict(type=type(error).__name__,
                code=code if re.fullmatch('REFUSED_[A-Z0-9_]+',code) else 'EXPORT_OPERATION_FAILED')
            receipt['status'] = 'KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    write_receipt(path,receipt)
