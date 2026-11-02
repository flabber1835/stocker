"""P10-scoped actual marker and stopped-only separate encrypted exports."""
import ast
import json
import os
from pathlib import Path
import re

from system_campaign_p10_ahl2_contract import TAINT, need, sha, function
from system_campaign_p10_ahl2_parent import retained_source

STAGE = 'campaign-p10-ahl2-diagnostic-suffix'
QUALIFICATION_STAGE = 'campaign-p10-ahl2-changed-qualification'
RECEIPT_SCHEMA = 'research.p10-own-ahl2-diagnostic-receipt/1'
STOP = {'stopped', 'exit_code', 'oom_killed', 'wait_error'}
ASSET = {'name', 'bytes', 'sha256', 'manifest_sha256', 'compression'}
EXPORT_CODES = frozenset({'EXPORT_OPERATION_FAILED','EXPORT_INVENTORY_REFUSED','EXPORT_CIPHER_IO_FAILED'})
PUBLIC = {'schema','arm','stage','run_id','head','request_sha256','protocol_sha256',
    'authority','financial_authority','account_performance_computed','production_contacted',
    'strict_parent_outer_sha256','diagnostic_parent_file_sha256','status','qualification_worker','worker','reviewer',
    'qualification_encrypted_output','encrypted_output','qualification_exported','encrypted_output_exported',
    'export_qualification_sha256','export_error','qualification_log_copy_failed','worker_log_copy_failed',
    'review_log_copy_failed','review_stop_unknown'}


def asset_valid(value):
    need(type(value) is dict and set(value) == ASSET
         and type(value['name']) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', value['name']) is not None
         and value['name'] not in ('.','..') and type(value['bytes']) is int and value['bytes'] > 0
         and all(type(value[k]) is str and re.fullmatch('[a-f0-9]{64}', value[k]) is not None
                 for k in ('sha256','manifest_sha256'))
         and type(value['compression']) is str and value['compression'] == 'TAR_GZIP_V1',
         'P10_PUBLIC_ASSET_EXACT_BASENAME_POSITIVE_BYTE_INT_SHA_AND_COMPRESSION')
    return value


def export_error_valid(value):
    need(type(value) is dict and set(value) == {'type','code'}
         and type(value['type']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', value['type']) is not None
         and type(value['code']) is str and value['code'] in EXPORT_CODES,
         'P10_PUBLIC_EXPORT_ERROR_CLASS_AND_CLOSED_STATIC_CODE')
    return value


def bind_literals(fn, mapping):
    counts = dict.fromkeys(mapping, 0)
    class Bind(ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value in mapping:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(mapping[node.value]), node)
            return node
    result = Bind().visit(fn)
    need(all(v == 1 for v in counts.values()), 'P10_EXACT_EXPORT_BINDING_LITERAL_SITES')
    return ast.fix_missing_locations(result)


def sealed(root, target, key, request, *, stage=STAGE):
    import system_campaign_evidence_export as original
    need(stage in (STAGE, QUALIFICATION_STAGE), 'P10_ONLY_DECLARED_NONFINANCIAL_ENCRYPTED_SCOPES')
    fn = function(retained_source(original), 'seal')
    fn = bind_literals(fn, {'campaign-factual-suffix':stage, 'P02':'P10',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'P10_EXACT_DIAGNOSTIC_EXPORT_SCOPE'})
    scope = dict(vars(original))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<same-authenticated-seal-p10-scope>', 'exec'), scope)
    return scope['seal'](Path(root), Path(target), key, Path(request), 'P10', stage=stage,
        protocol_sha256=json.loads(Path(request).read_bytes())['protocol_sha256'])


def qualify_export(path, request):
    import system_campaign_p01_discovery_export as original
    fn = function(retained_source(original), 'qualify_export')
    fn = bind_literals(fn, {'P01':'P10',
        'P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED':'P10_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'})
    scope = dict(vars(original), STAGE=STAGE, sealed=sealed, __file__=__file__)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<actual-p10-marker-roundtrip>', 'exec'), scope)
    return scope['qualify_export'](Path(path), Path(request))


def write_receipt(path, value):
    need(set(value) <= PUBLIC and value['schema'] == RECEIPT_SCHEMA and value['arm'] == 'P10'
         and value['authority'] == TAINT
         and value['stage'] == STAGE and value['financial_authority'] is False
         and value['account_performance_computed'] is False and value['production_contacted'] is False,
         'P10_SAFE_PUBLIC_DIAGNOSTIC_RECEIPT_ONLY')
    nested = {'qualification_worker','worker','reviewer','qualification_encrypted_output','encrypted_output','export_error'}
    need(all(type(v) in (str,int,bool,type(None)) for k,v in value.items() if k not in nested),
         'P10_PUBLIC_SCALAR_METADATA_ONLY')
    for name in ('qualification_worker','worker','reviewer'):
        if name in value:
            stop = value[name]
            need(set(stop) == STOP and stop['stopped'] is True and type(stop['exit_code']) is int
                 and type(stop['oom_killed']) is bool and type(stop['wait_error']) in (str,type(None)),
                 'P10_EXACT_ACTUAL_PUBLIC_STOP_METADATA')
    for name in ('qualification_encrypted_output','encrypted_output'):
        if name in value:
            asset_valid(value[name])
    if 'export_error' in value:
        export_error_valid(value['export_error'])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.partial')
    with pending.open('w', encoding='utf8', newline='\n') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def preserve(receipt, root, path, key, request, *, qualification=False, known=False):
    """Known nonzero evidence is exportable; UNKNOWN is never a snapshot."""
    key_name = 'qualification_encrypted_output' if qualification else 'encrypted_output'
    flag = 'qualification_exported' if qualification else 'encrypted_output_exported'
    receipt[flag] = False
    write_receipt(path, receipt)
    if known:
        need(receipt['status'] != 'UNKNOWN_NO_MUTABLE_SNAPSHOT', 'P10_UNKNOWN_WRITER_NO_SNAPSHOT')
        suffix = 'qualification' if qualification else 'discovery'
        try:
            receipt[key_name] = sealed(root, Path(path).parent / ('p10-ahl2-' + suffix + '.tar.crseal'),
                key, request, stage=QUALIFICATION_STAGE if qualification else STAGE)
            receipt[flag] = True
        except Exception as error:
            code = 'EXPORT_INVENTORY_REFUSED' if str(error) == 'RETAINED_EXPORT_EXPLICIT_TWO_GIB_BOUND' else \
                   'EXPORT_CIPHER_IO_FAILED' if isinstance(error, OSError) else 'EXPORT_OPERATION_FAILED'
            receipt['export_error'] = dict(type=type(error).__name__, code=code)
            receipt['status'] = 'KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    write_receipt(path, receipt)
    return receipt
