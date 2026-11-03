"""Authenticate retained OWN475 bytes; reuse its stopped canonical review exactly."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

import system_campaign_factual_admit as crypto
from p01_action_clock_parent import old_stop as unused_legacy_stop
from p01_celg_bridge_gate import specification,parent_identity,need,digest,sha,HERE,SPEC
from seal import safe_name,sha256_file

PRIOR='p01_clock_input_request.json'
PRIOR_SHA='a830b2b3fdff69b66810f8c2ced465b83ed47cda7a530f0acd214a46f5303f81'


def extract(z,asset,key,dest,spec,stage):
    need(z.getinfo(asset['name']).file_size==asset['bytes'],'PARENT_EXACT_CIPHER_LENGTH')
    header,tag=crypto.authenticate(z,asset,key)
    dest.mkdir(mode=0o700)
    with z.open(asset['name']) as source:
        plain=crypto.AuthenticatedStream(source,asset,key,header,tag)
        with tarfile.open(fileobj=plain,mode='r|gz') as tar:
            first=tar.next()
            need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'PARENT_FIRST_MANIFEST')
            raw=tar.extractfile(first).read();need(sha(raw)==asset['manifest_sha256'],'PARENT_MANIFEST_HASH')
            manifest=json.loads(raw)
            need(manifest['schema']=='research.full-system-output/1' and manifest['stage']==stage
                 and manifest['arm']=='P01' and int(manifest['run_id'])==spec['run_id']
                 and manifest['head']==spec['head'] and manifest['request_sha256']==PRIOR_SHA
                 and manifest['protocol_sha256']==spec['protocol_sha256'],'PARENT_AUTHENTICATED_ASSET_SCOPE')
            members=manifest['members'];seen=set()
            need(0<len(members)<5000 and sum(v['bytes'] for v in members.values())<1024**3,
                 'PARENT_COMPLETE_BOUNDED_INVENTORY')
            while item:=tar.next():
                safe_name(item.name)
                need(item.isfile() and item.name in members and item.name not in seen
                     and item.size==members[item.name]['bytes'],'PARENT_EXACT_INVENTORY_MEMBER')
                seen.add(item.name);target=dest/item.name
                need(target.resolve().is_relative_to(dest.resolve()),'PARENT_EXTRACTION_BOUNDARY')
                target.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(item) as src,target.open('xb') as out:shutil.copyfileobj(src,out,1024**2)
                os.chmod(target,0o600)
                need(sha256_file(target)==members[item.name]['sha256'],'PARENT_EVERY_LOGICAL_MEMBER_HASH')
            need(seen==set(members),'PARENT_NO_MISSING_MEMBER')
        while plain.read(1024**2):pass
    return members


def stopped(value,metadata,role,spec):
    import ast,re
    from system_campaign_parallel_discovery import compile_body
    import system_campaign_p02_close_diagnostics as original
    request=json.loads((HERE/PRIOR).read_bytes())
    need(sha(Path(original.__file__).read_bytes())==request['sources'][Path(original.__file__).name],
         'PARENT_ORIGINAL_STOP_FENCES_SOURCE')
    fn,=[n for n in ast.parse(Path(original.__file__).read_bytes()).body
         if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
    site.value='/capital-system-p01-clock-input-'
    compare,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    mode={'qualify':'qualify','worker':'economic','review':'review'}[role]
    compare.comparators=[ast.parse(repr(['-B','-u','/driver/p01_clock_input_run.py','--mode',mode,
        '--spec','/out/spec.json']),mode='eval').body]
    compile_body(fn,vars(original))(value,metadata,role,str(spec['run_id']),PRIOR)
    expected=spec['actual_stops'][role]
    need(value['Id']==expected['id'] and value['State']['ExitCode']==expected['exit_code']==0
         and metadata['exit_code']==0 and re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',value['Config']['User']) is not None,
         'PARENT_ACTUAL_EXACT_SUCCESSFUL_NONROOT_STOP')


def admit(root,key):
    spec=specification();root=crypto.hosted_destination(root);root.mkdir(mode=0o700)
    crypto.archive_bound(spec,512*1024**2);archive=root/'predecessor.zip'
    need(sha((HERE/PRIOR).read_bytes())==PRIOR_SHA,'PARENT_EXACT418_REQUEST')
    request=json.loads((HERE/PRIOR).read_bytes())
    need(len(request['sources'])==418 and all(sha((HERE/n).read_bytes())==h for n,h in request['sources'].items()),
         'PARENT_ALL418_PUBLISHED_SOURCE_BYTES')
    with archive.open('xb') as out:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],
                       stdout=out,check=True,timeout=180)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],
         'PARENT_ACTUAL_OWN475_ZIP')
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist())==len(set(z.namelist())),'PARENT_UNIQUE_ZIP_INVENTORY')
        raw=z.read(spec['receipt_name']);need(sha(raw)==spec['receipt_sha256'],'PARENT_EXACT_PUBLIC_RECEIPT')
        r=json.loads(raw)
        need(r['schema']==spec['receipt_schema'] and r['stage']==spec['stage'] and r['arm']=='P01'
             and int(r['run_id'])==spec['run_id'] and r['head']==spec['head']
             and r['request_sha256']==PRIOR_SHA and r['protocol_sha256']==spec['protocol_sha256']
             and r['production_contacted'] is False and r['encrypted_output']==spec['encrypted_output']
             and r['qualification_encrypted_output']==spec['qualification_encrypted_output']
             and r['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT',
             'PARENT_ACTUAL_SUCCESSFUL_TWO_CIPHER_SCOPE')
        probe_raw=z.read('p01-clock-input-export-qualification.json');probe=json.loads(probe_raw)
        need(sha(probe_raw)==r['export_qualification_sha256'] and probe['request_sha256']==PRIOR_SHA
             and probe['source_adapter_sha256']==request['sources']['p01_clock_input_export.py']
             and probe['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
             and probe['synthetic_marker_only'] is True and probe['market_or_financial_state_processed'] is False,
             'PARENT_ACTUAL_MARKER_PREFLIGHT')
        need(set(z.namelist())=={spec['receipt_name'],'full-core-staging.json','p01-clock-input-phase.json',
            'p01-clock-input-export-qualification.json',r['encrypted_output']['name'],
            r['qualification_encrypted_output']['name']},'PARENT_EXACT_TWO_CIPHER_ZIP_MEMBERS')
        q=extract(z,r['qualification_encrypted_output'],key,root/'qualified',spec,
                  'campaign-p01-economic-clock-input-qualification')
        dest=root/'admitted';f=extract(z,r['encrypted_output'],key,dest,spec,spec['stage'])
        need(all(f.get(n)==v for n,v in q.items()),'PARENT_QUALIFICATION_BYTES_RETAINED_EXACTLY')
    for role,name in [('qualify','qualification/worker-inspect.json'),('worker','worker-inspect.json'),
                      ('review','stopped-review/worker-inspect.json')]:
        stopped(json.loads((dest/name).read_bytes()),r['qualification_worker' if role=='qualify' else
                'worker' if role=='worker' else 'reviewer'],role,spec)
    for name,binding in spec['reused_hosted_old_source_proofs'].items():
        path=dest/name
        need(path.stat().st_size==binding['bytes'] and sha256_file(path)==binding['sha256'],
             'PARENT_EXACT_REUSED_STOPPED_SOURCE515_CANONICAL_RESTORE_PROOF')
    need((dest/'request.json').read_bytes()==(HERE/PRIOR).read_bytes()
         and sha256_file(dest/'source-bindings.json')==spec['source_binding_sha256'],
         'PARENT_OLD_SOURCE_AND_REQUEST_BINDINGS')
    selected=dest/spec['selected_checkpoint']
    need(selected.stat().st_size==spec['selected_file']['bytes']
         and sha256_file(selected)==spec['selected_file']['sha256'],'PARENT_EXACT_OWN475_GZIP')
    cp=parent_identity(json.loads(gzip.decompress(selected.read_bytes())),spec)
    for name,c in cp['journals'].items():
        path=dest/f'book/{name}.jsonl'
        need(path.stat().st_size==c['bytes'] and sha256_file(path)==c['prefix_sha256'],
             'PARENT_ALL_COMMITTED_PREFIX_BYTES_NO_CURRENT_TAIL')
    for d in cp['repairs']:
        raw=(dest/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'],'PARENT_ALL_NINE_ORIGINAL_INPUT_BYTES')
    return dest
