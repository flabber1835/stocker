"""Hosted authentication of the exact approved old Q subset; no state restore."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

import system_campaign_factual_admit as crypto
from full_system_benchmark import need
from seal import safe_name,sha256_file
from ephemeral_runner_capacity import validate_prepared_receipt
from p01_iac_reference_evidence import ORIGIN,ADMISSION,APPROVED,PROVENANCE,PROVENANCE_SCHEMA

HERE=Path(__file__).parent
SPEC_SHA='33c61bd316935694b2f2215a73ccdf84d81fcd5d7b6c1c12949e9b846842977b'
CRYPTO_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
TOP={'schema','origin','approved_members','root_reuse_admission_sha256','partial_review_sha256',
     'metadata_review_sha256','final_review_sha256','financial_authority','financial_predecessor_admitted'}
ORIGIN_KEYS={'run_id','head','artifact_id','zip','request_file','request_sha256','driver_source_count','protocol_sha256',
    'stage','receipt','marker','capacity','qualification_cipher','authenticated_manifest','actual_worker_stop','public_members'}
CONTROL={'request.json','spec.json','source-map.json','source-bindings.json','qualification/worker-inspect.json'}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def pretty(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def plain(raw):
    def pairs(items):
        result={}
        for k,v in items:need(k not in result,'REFERENCE_ADMIT_NO_DUPLICATE_METADATA_KEY');result[k]=v
        return result
    def invalid(value):raise ValueError('REFUSED_REFERENCE_ADMIT_NONFINITE_METADATA:'+value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def check_spec(spec):
    need(type(spec) is dict and set(spec)==TOP and set(spec['origin'])==ORIGIN_KEYS
         and sha(pretty(spec))==SPEC_SHA and spec['schema']=='research.p01-approved-reference-evidence-spec/1'
         and spec['root_reuse_admission_sha256']==ADMISSION and spec['approved_members']==APPROVED
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and all(type(spec['origin'][k]) is type(v) and spec['origin'][k]==v for k,v in ORIGIN.items()),
         'REFERENCE_ADMIT_ENTIRE_EXACT_NONFINANCIAL_PUBLIC_SPEC')
    stop=spec['origin']['actual_worker_stop']['metadata']
    need(set(stop)=={'stopped','exit_code','oom_killed','wait_error'} and stop['stopped'] is True
         and type(stop['exit_code']) is int and stop['exit_code']==1 and stop['oom_killed'] is False,
         'REFERENCE_ADMIT_ORIGINAL_QUALIFIER_FAILURE_NOT_RELABELLED')
    return spec


def extract_selected(z,asset,key,dest,spec):
    """Full GCM first, then hash ALL members; never decode selected payloads."""
    need(sha256_file(Path(crypto.__file__))==CRYPTO_SHA,'REFERENCE_ADMIT_EXACT_EXISTING_GCM_PROTOCOL')
    need(z.getinfo(asset['name']).file_size==asset['bytes'],'REFERENCE_ADMIT_CIPHER_LENGTH')
    header,tag=crypto.authenticate(z,asset,key)
    dest=Path(dest);dest.mkdir(mode=0o700);captured={};seen=set();count=0;total=0
    origin=spec['origin']
    with z.open(asset['name']) as source:
        stream=crypto.AuthenticatedStream(source,asset,key,header,tag)
        with tarfile.open(fileobj=stream,mode='r|gz') as tar:
            first=tar.next();need(first is not None and first.name=='manifest.json' and first.isfile()
                and first.size<2*1024**2,'REFERENCE_ADMIT_FIRST_BOUNDED_MANIFEST_AFTER_GCM')
            raw=tar.extractfile(first).read();need(sha(raw)==asset['manifest_sha256'],'REFERENCE_ADMIT_MANIFEST_PREIMAGE')
            manifest=plain(raw);inventory=manifest['members'];expected=origin['authenticated_manifest']
            need(manifest['schema']=='research.full-system-output/1' and manifest['arm']=='P01'
                 and manifest['stage']==origin['stage'] and str(manifest['run_id'])==str(origin['run_id'])
                 and manifest['head']==origin['head'] and manifest['request_sha256']==origin['request_sha256']
                 and manifest['protocol_sha256']==origin['protocol_sha256'] and manifest['compression']=='TAR_GZIP_V1'
                 and dict(bytes=len(raw),sha256=sha(raw),members_count=len(inventory),
                    raw_members_bytes=sum(v['bytes'] for v in inventory.values()),inventory_sha256=digest(inventory))==expected
                 and 0<len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<1024**3,
                 'REFERENCE_ADMIT_COMPLETE_ORIGINAL_SCOPE_AND_INVENTORY_DIGEST')
            while item:=tar.next():
                safe_name(item.name)
                need(item.isfile() and item.name in inventory and item.name not in seen,'REFERENCE_ADMIT_UNIQUE_REGULAR_DECLARED_MEMBER')
                seen.add(item.name);entry=inventory[item.name]
                need(type(entry) is dict and set(entry)=={'bytes','sha256'} and type(entry['bytes']) is int
                     and entry['bytes']>=0 and item.size==entry['bytes'] and re.fullmatch('[0-9a-f]{64}',entry['sha256']) is not None,
                     'REFERENCE_ADMIT_EXACT_MEMBER_DESCRIPTOR')
                selected=item.name in spec['approved_members'];control=item.name in CONTROL
                if selected:need(entry==spec['approved_members'][item.name],'REFERENCE_ADMIT_APPROVED_RAW_MEMBER_IDENTITY')
                if control:need(item.size<2*1024**2,'REFERENCE_ADMIT_BOUNDED_STATIC_CONTROL_METADATA')
                target=dest/item.name
                if selected:
                    need(target.resolve().is_relative_to(dest.resolve()),'REFERENCE_ADMIT_SELECTED_PATH_BOUNDARY')
                    target.parent.mkdir(parents=True,exist_ok=True);output=target.open('xb')
                else:output=None
                pieces=[];h=hashlib.sha256();size=0
                try:
                    with tar.extractfile(item) as member:
                        for block in iter(lambda:member.read(1024**2),b''):
                            h.update(block);size+=len(block)
                            if output is not None:output.write(block)
                            if control:pieces.append(block)
                    if output is not None:output.flush();os.fsync(output.fileno())
                finally:
                    if output is not None:output.close()
                need(dict(bytes=size,sha256=h.hexdigest())==entry,'REFERENCE_ADMIT_EVERY_OPAQUE_AND_SELECTED_MEMBER_LENGTH_SHA')
                if control:captured[item.name]=b''.join(pieces)
                count+=1;total+=size
            need(seen==set(inventory) and set(spec['approved_members'])<=seen and CONTROL<=seen,
                 'REFERENCE_ADMIT_NO_OMITTED_OR_EXTRA_OLD_BYTES')
        while stream.read(1024**2):pass
    return dict(manifest=manifest,manifest_raw=raw,controls=captured,members=count,raw_bytes=total)


def actual_stop(value,metadata,origin,source):
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
    site.value='/capital-system-p01-iac-unit-fixture-'
    command,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    command.comparators=[ast.parse(repr(['-B','-u','/driver/p01_iac_unit_fixture_run.py','--mode','qualify','--spec','/out/spec.json']),mode='eval').body]
    mounts,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=='set(mounts)']
    mounts.comparators=[ast.parse(repr({'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json'}),mode='eval').body]
    namespace=dict(need=need,re=re,SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<exact-old497-failed-qualifier-fences>','exec'),namespace)
    namespace['stopped'](value,metadata,'qualify',str(origin['run_id']),origin['request_file'])
    need(value['Id']==origin['actual_worker_stop']['inspection']['id'] and metadata['exit_code']==1
         and re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',value['Config']['User']),
         'REFERENCE_ADMIT_ACTUAL_OLD_FAILED_NONROOT_WORKER')


def admit_reference(root,key,spec):
    """Authenticate a new use of old evidence; return ONLY2 raw files+provenance."""
    check_spec(spec);root=crypto.hosted_destination(root)
    need(sha256_file(Path(crypto.__file__))==CRYPTO_SHA,'REFERENCE_ADMIT_UNCHANGED_EXISTING_CRYPTO')
    origin=spec['origin'];raw_request=(HERE/origin['request_file']).read_bytes()
    need(sha(raw_request)==origin['request_sha256'],'REFERENCE_ADMIT_RAW_OLD497_REQUEST')
    request=plain(raw_request)
    need(len(request['sources'])==497 and all(sha256_file(HERE/n)==h for n,h in request['sources'].items()),
         'REFERENCE_ADMIT_ALL497_OLD_DRIVER_BYTES_BEFORE_FETCH')
    need(shutil.disk_usage(root.parent).free>=12*1024**3 and type(key) is bytes and len(key)==32,
         'REFERENCE_ADMIT_EXISTING_HOST_RESERVE_AND_SEPARATE_KEY')
    root.mkdir(mode=0o700);archive=root/'original-qualification.zip'
    with archive.open('xb') as stream:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{origin['artifact_id']}/zip"],
            stdout=stream,check=True,timeout=180)
    need(dict(bytes=archive.stat().st_size,sha256=sha256_file(archive))==origin['zip'],'REFERENCE_ADMIT_EXACT_ORIGINAL_ZIP')
    public_raw={}
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist())==len(set(z.namelist())) and set(z.namelist())==set(origin['public_members'])|{origin['qualification_cipher']['name']},
             'REFERENCE_ADMIT_EXACT_UNIQUE_ORIGINAL_PUBLIC_AND_CIPHER_NAMES')
        for name,entry in origin['public_members'].items():
            need(z.getinfo(name).file_size==entry['bytes'] and entry['bytes']<2*1024**2,'REFERENCE_ADMIT_BOUNDED_PUBLIC_METADATA')
            raw=z.read(name);need(dict(bytes=len(raw),sha256=sha(raw))==entry,'REFERENCE_ADMIT_EXACT_ORIGINAL_PUBLIC_BYTES');public_raw[name]=raw
        receipt=plain(public_raw[origin['receipt']['name']]);marker=plain(public_raw[origin['marker']['name']])
        need(receipt['schema']=='research.p01-own628-iac-unit-fixture-receipt/1' and receipt['arm']=='P01'
             and receipt['stage']=='campaign-p01-iac-unit-fixture-financial'
             and str(receipt['run_id'])==str(origin['run_id']) and receipt['head']==origin['head']
             and receipt['request_sha256']==origin['request_sha256'] and receipt['protocol_sha256']==origin['protocol_sha256']
             and receipt['qualification_encrypted_output']==origin['qualification_cipher']
             and receipt['qualification_worker']==origin['actual_worker_stop']['metadata']
             and receipt['status']=='QUALIFICATION_ONLY_KNOWN_STOP_REFUSAL_PRESERVED'
             and receipt['qualification_exported'] is True and receipt['encrypted_output_exported'] is False
             and receipt['production_contacted'] is False and not any(k in receipt for k in ('worker','reviewer','encrypted_output')),
             'REFERENCE_ADMIT_OLD_QUALIFIER_FAILURE_WITH_NO_FINANCIAL_WORKER')
        need(sha(public_raw[origin['marker']['name']])==receipt['export_qualification_sha256']
             and marker['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
             and marker['request_sha256']==origin['request_sha256']
             and marker['source_adapter_sha256']==request['sources']['p01_iac_unit_fixture_export.py'],
             'REFERENCE_ADMIT_ORIGINAL_ACTUAL_CRYPTO_MARKER')
        validate_prepared_receipt(plain(public_raw[origin['capacity']['name']]),head=origin['head'],run_id=str(origin['run_id']),
            source_sha256=request['capacity_source_sha256'])
        checked=extract_selected(z,origin['qualification_cipher'],key,root/'approved',spec)
    controls=checked['controls'];inspection=origin['actual_worker_stop']['inspection']
    need(dict(bytes=len(controls[inspection['member']]),sha256=sha(controls[inspection['member']]))
         =={k:inspection[k] for k in ('bytes','sha256')},'REFERENCE_ADMIT_EXACT_ORIGINAL_STOP_PREIMAGE')
    stop_source=(HERE/'system_campaign_p02_close_diagnostics.py').read_bytes()
    need(sha(stop_source)==request['sources']['system_campaign_p02_close_diagnostics.py'],'REFERENCE_ADMIT_EXACT_OLD_STOP_PARSER')
    actual_stop(plain(controls[inspection['member']]),origin['actual_worker_stop']['metadata'],origin,stop_source)
    need(controls['request.json']==raw_request and controls['spec.json']==(HERE/request['source_financial_file']).read_bytes()
         and controls['source-map.json']==(HERE/'p01_celg_bridge_source_map.json').read_bytes()
         and sha(controls['source-bindings.json'])=='cbff432d861381735e7bba6ecd79491b059405cde8840cc2d128dbbad85d0b14',
         'REFERENCE_ADMIT_WHOLE_STATIC_REQUEST_SPEC_DISTINCT515_BINDING_516_MAP')
    provenance=dict(schema=PROVENANCE_SCHEMA,specification=spec,all_old_driver_sources_authenticated=True,
        full_qualification_inventory_authenticated=True,original_qualification_worker_exit_code=1,financial_worker_started=False,
        financial_authority=False,qualification_state_adopted=False,original_raw_request_utf8=raw_request.decode('utf8'),
        original_manifest_utf8=checked['manifest_raw'].decode('utf8'),original_public_metadata_utf8={n:v.decode('utf8') for n,v in public_raw.items()},
        authenticated_raw_members=checked['members'],authenticated_raw_bytes=checked['raw_bytes'],approved_payloads_parsed_by_host=False)
    target=root/'approved'/PROVENANCE
    with target.open('xb') as stream:stream.write(pretty(provenance));stream.flush();os.fsync(stream.fileno())
    return root/'approved'
