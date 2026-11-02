"""Authenticate one stopped diagnostic prefix; never admit it financially."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

from full_system_benchmark import need
from probe import check_context
from seal import safe_name,sha256_file
from system_campaign_discovery_context import CHECKPOINT,TAINT,digest
import system_campaign_factual_admit as crypto
import system_campaign_p02_close_diagnostics as stops

HERE=Path(__file__).resolve().parent
SPEC='system-campaign-p01-discovery-suffix-predecessor.json'
SPEC_SHA='fe9772d2afe4c62f777ba0e0c765c2473d5dd41cc930b15e9ea8ec1b170c6ec2'
CRYPTO_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'


def specification():
    raw=(HERE/SPEC).read_bytes()
    need(hashlib.sha256(raw).hexdigest()==SPEC_SHA,'P01_DIAGNOSTIC_EXACT_PREDECESSOR_SPEC')
    value=json.loads(raw)
    need(value['authority']==TAINT and value['financial_authority'] is False
         and value['run_id']==41331415571 and value['transitions']==356
         and value['next_session']=='2021-02-01' and value['expected_remaining_sessions']==1381,
         'P01_ONLY_EXACT_ADMITTED_DIAGNOSTIC356_PREFIX')
    return value


def validate_checkpoint(cp,spec):
    need(cp['schema']==CHECKPOINT and cp['authority']==TAINT and cp['financial_authority'] is False
         and cp['account_performance_computed'] is False
         and cp['strict_parent_outer_sha256']==spec['strict_parent_outer_sha256']
         and cp['source_cursor']==spec['selected_session'] and cp['discovery_transitions']==spec['transitions']
         and cp['journals']==spec['journals'] and cp['events']==spec['events']
         and cp['event_chain_sha256']==spec['events']['chain_sha256']
         and cp['transition_chain_sha256']==spec['transition_chain_sha256'],
         'P01_EXACT_DIAGNOSTIC_CHECKPOINT_NOT_FINANCIAL_OR_RELABELED')
    run=cp['runtime_checkpoint'];body={k:v for k,v in run.items() if k!='checkpoint_sha256'}
    need(digest(body)==run['checkpoint_sha256']==spec['runtime_checkpoint_sha256']
         and digest(run['state'])==run['state_sha256']==spec['state_sha256']
         and run['state']['last_processed_session']==spec['selected_session']
         and run['input_sha256']==spec['input_sha256'],'P01_DIAGNOSTIC_INNER_STATE_INPUT_CONTENT_BINDINGS')
    return cp


def verify_stream(raw,commitment,*,last=False):
    need(len(raw)==commitment['bytes'] and hashlib.sha256(raw).hexdigest()==commitment['prefix_sha256']
         and (not raw or raw.endswith(b'\n')),'P01_DIAGNOSTIC_EXACT_COMMITTED_PREFIX_ZERO_TAIL')
    if last:
        lines=raw.splitlines(keepends=True)
        need((hashlib.sha256(lines[-1]).hexdigest() if lines else None)==commitment['last_record_sha256'],
             'P01_DIAGNOSTIC_LAST_JOURNAL_RECORD_BINDING')


def old_stopped(value,metadata,role,spec):
    """Reuse the exact old fence body, changing only P01 entrypoint literals."""
    raw=Path(stops.__file__).read_bytes()
    request=json.loads((HERE/'system-campaign-p01-discovery-request-003.json').read_bytes())
    need(sha256_file(Path(stops.__file__))==request['sources'][Path(stops.__file__).name],
         'P01_DIAGNOSTIC_EXACT_RETAINED_STOP_REVIEW_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    replacements={'/capital-system-factual-p02-':'/capital-system-discovery-p01-',
        'economic':'qualify' if role=='qualify' else 'discovery',
        '/driver/system_campaign_p02_close_run.py':'/driver/system_campaign_p01_discovery_run.py'}
    counts=dict.fromkeys(replacements,0)
    class Sites(ast.NodeTransformer):
        def visit_Constant(self,node):
            if isinstance(node.value,str) and node.value in replacements:
                counts[node.value]+=1;return ast.copy_location(ast.Constant(replacements[node.value]),node)
            return node
    fn=Sites().visit(fn)
    need(all(v==1 for v in counts.values()),'P01_DIAGNOSTIC_EXACT_THREE_STOP_IDENTITY_SITES')
    scope=dict(vars(stops));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<retained-p01-stopped-fences>','exec'),scope)
    scope['stopped'](value,metadata,role,str(spec['run_id']),'system-campaign-p01-discovery-request-003.json')


def validate_contents(root,spec):
    root=Path(root)
    cp_path=root/spec['diagnostic_checkpoint']
    need(cp_path.stat().st_size==spec['checkpoint_bytes']
         and sha256_file(cp_path)==spec['diagnostic_checkpoint_sha256'],'P01_DIAGNOSTIC_EXACT_GZIP_PREDECESSOR')
    cp=validate_checkpoint(json.loads(gzip.decompress(cp_path.read_bytes())),spec)
    for name,entry in cp['journals'].items():verify_stream((root/'diagnostic-book'/(name+'.jsonl')).read_bytes(),entry,last=True)
    verify_stream((root/'discovery-events.jsonl').read_bytes(),cp['events'])
    need(sha256_file(root/'source-bindings.json')==spec['source_binding_sha256']
         and sha256_file(root/'qualification/discovery-canonical-qualification.json')==spec['original_qualification_sha256'],
         'P01_REUSED_ORIGINAL_SOURCE_AND_ACTUAL_CANONICAL_QUALIFICATION_BYTES')
    proof=json.loads((root/'qualification/discovery-canonical-qualification.json').read_bytes())
    need(proof['status']=='QUALIFIED' and proof['synthetic_canonical_transitions']==3
         and proof['strict_parent_bytes_unchanged'] and proof['actual_strict_checkpoint_rejection']
         and proof['original_runtime_hook_restored'] and not proof['actual_discovery_started'],
         'P01_REUSE_ONLY_ACTUAL_UNCHANGED_ORIGINAL_THREE_CASE_GATE')
    for name,entry in spec['inspections'].items():
        path=root/name;need(sha256_file(path)==entry['sha256'],'P01_OLD_ACTUAL_STOP_INSPECTION_BYTES')
        value=json.loads(path.read_bytes())
        need(value['Id']==entry['id'] and value['Name']==entry['name'],'P01_OLD_ACTUAL_CONTAINER_IDENTITY')
        old_stopped(value,entry['metadata'],entry['role'],spec)
    return cp


def admit(spec,root,key):
    check_context(os.environ)
    need(os.name=='posix' and Path(os.environ['RUNNER_TEMP']).resolve()==Path('/home/runner/work/_temp')
         and Path(root).resolve().parent==Path(os.environ['RUNNER_TEMP']).resolve()
         and Path(root).name=='p01-diagnostic-suffix-parent'
         and spec==specification(),'P01_DIAGNOSTIC_HOSTED_EXACT_DESTINATION')
    need(sha256_file(Path(crypto.__file__))==CRYPTO_SHA,'P01_UNCHANGED_AUTHENTICATED_STREAM_CRYPTO')
    root=Path(root);root.mkdir(mode=0o700);archive=root/'previous.zip'
    with archive.open('xb') as stream:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],
            stdout=stream,check=True,timeout=90)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],
         'P01_DIAGNOSTIC_EXACT_DOWNLOAD_LENGTH_SHA')
    with zipfile.ZipFile(archive) as z:
        asset=spec['encrypted_output']
        need(len(z.namelist())==4 and set(z.namelist())=={spec['receipt_name'],'full-core-staging.json',
             'p01-export-qualification.json',asset['name']},'P01_DIAGNOSTIC_EXACT_FOUR_PUBLIC_MEMBERS')
        raw=z.read(spec['receipt_name']);need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],
            'P01_DIAGNOSTIC_EXACT_SOURCE_RECEIPT')
        receipt=json.loads(raw)
        need(int(receipt['run_id'])==spec['run_id'] and receipt['head']==spec['head']
             and receipt['request_sha256']==spec['request_sha256'] and receipt['encrypted_output']==asset
             and receipt['authority']==TAINT and receipt['financial_authority'] is False
             and receipt['arm']=='P01' and receipt['stage']=='campaign-disposable-discovery'
             and receipt['protocol_sha256']==spec['protocol_sha256'] and not receipt['production_contacted'],
             'P01_DIAGNOSTIC_SOURCE_RECEIPT_SCOPE')
        need(hashlib.sha256(z.read('p01-export-qualification.json')).hexdigest()==spec['public_probe_sha256'],
             'P01_RETAINED_ACTUAL_EXPORT_PROBE_BYTES')
        header,tag=crypto.authenticate(z,asset,key)
        dest=root/'admitted';dest.mkdir(mode=0o700)
        with z.open(asset['name']) as source:
            plain=crypto.AuthenticatedStream(source,asset,key,header,tag)
            with tarfile.open(fileobj=plain,mode='r|gz') as tar:
                first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<1024**2,
                    'P01_DIAGNOSTIC_FIRST_AUTHENTICATED_MANIFEST')
                raw=tar.extractfile(first).read()
                need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'P01_DIAGNOSTIC_MANIFEST_SHA')
                manifest=json.loads(raw)
                need(manifest['schema']=='research.full-system-output/1'
                     and manifest['arm']=='P01' and manifest['stage']=='campaign-disposable-discovery'
                     and int(manifest['run_id'])==spec['run_id'] and manifest['head']==spec['head']
                     and manifest['request_sha256']==spec['request_sha256']
                     and manifest['protocol_sha256']==spec['protocol_sha256'],'P01_DIAGNOSTIC_MANIFEST_BINDINGS')
                inventory=manifest['members'];seen=set()
                need(len(inventory)==spec['inventory_members'] and sum(v['bytes'] for v in inventory.values())<32*1024**2,
                     'P01_DIAGNOSTIC_BOUNDED_COMPLETE_INVENTORY')
                while item:=tar.next():
                    safe_name(item.name)
                    need(item.isfile() and item.name in inventory and item.name not in seen
                         and item.size==inventory[item.name]['bytes'],'P01_DIAGNOSTIC_EXACT_REGULAR_MEMBER')
                    target=dest/item.name;need(target.resolve().is_relative_to(dest.resolve()),'P01_DIAGNOSTIC_EXTRACT_BOUNDARY')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with tar.extractfile(item) as src,target.open('xb') as out:shutil.copyfileobj(src,out)
                    need(sha256_file(target)==inventory[item.name]['sha256'],'P01_DIAGNOSTIC_MEMBER_SHA')
                    seen.add(item.name)
                need(seen==set(inventory),'P01_DIAGNOSTIC_ALL_INVENTORY_MEMBERS')
            while plain.read(1024**2):pass
    validate_contents(dest,spec)
    return dest
