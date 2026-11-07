"""Exact root-admitted OWN628 transport; no financial state restoration."""
from __future__ import annotations

import ast
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Literal
import zipfile

from pydantic import BaseModel,ConfigDict
from p01_epoch_parent import sha,digest,file_binding,SOURCE_RECEIPT,SOURCE_MAP,MAP_IDENTITY,OLD_BINDING,TENTH,PROTOCOL

HERE=Path(__file__).parent
ROOT_ADMISSION='06157fd8d37a92bd5e623081374e00b2b8253b6750fa761234b19a467c798ef6'
PRIOR='p01_native_resume_request.json'
PRIOR_SHA='00bc6fff9ce370204f529a4760eafb15e48f4de140884456e9be5d5c7fac7a7d'
RUN=41421334633;HEAD='a8c3a83d4777c051dc210b49ee900c1ca2c4a5bc';ARTIFACT=13130582666
OUTER='da8f0ef0e04f70f1f388ee68ee1bb70d923dcb35b41f53e4d39b3e1e4b81f0ee'
INNER='ad10aa369b7ea020f0a586571b51807b166e73788030c22345d5db7ac8c28186'
STATE='1edf8901c7783f6683e102f9c92c8a2d5578661046e8481df3e06d4ea67c9ebc'
INPUT='53c3b13673552dbf98263ab0272ac11c8951de619bf19e9ddf2020e59b01584a'
ELEVENTH='430c69b8771ccbfb7b915618cb4536851c5505761cca102cc7b74576cb8b088c'
ELEVENTH_ORIGINAL_PREDECESSOR='a3576136388aed10e7a833eb87b5314ad6c7381597448d5c1359a9d0840d4a7b'
STAGE='campaign-p01-native-continuation-financial';QSTAGE='campaign-p01-native-continuation-qualification'
ZIP=dict(bytes=139998261,sha256='c6be0a7b463bbac39497f53e6ab2e4d6dcdd418b9f597b88e956080f4890d252')
GZIP=dict(bytes=1219179,sha256='aae13932ce4aa996ed4d81b6aa96a60ee85c699c257a55b9012660de800c6baf')
RECEIPT='9ae6e051c630c857d5054ca88ebf6d2757ca7fb79c13caf8f605090ce372e089'
MARKER='04d8f7a232917df423040758abc58213d8fdbd301c10fd26957fcc235e51e92b'
STOP_IDS=dict(qualify='eb13c0007e6fc8b5321404e49f5090321b43ae5644b93c919f72c919191ca189',
 worker='e9ee97772ed2bffb3dd294ee58a8f0834dd8e3ab33c420dc5f466dfc2f8d2df1',
 review='a5d00eb51fa2a0493284d4bb831f38f918bacf0cf3eeb6a63b5caf68fe2afcd1')
EXTRACTOR_SOURCE='6e4218a374b145d3fd250fe46d9275119a3664994593191d618623fd478870f7'
PUBLIC_KEYS=frozenset(('schema','root_admission_descriptor_sha256','arm','run_id','head','artifact_id',
    'outer_sha256','inner_sha256','state_sha256','input_sha256','selected_session','measured_closes',
    'financial_predecessor_admitted','qualification_state_adopted','current_tails_zero',
    'selected_checkpoint','selected_file','request','request_sha256','protocol_sha256','stage',
    'next_session','total_inputs','base','repairs','journals','source_epoch','retained_checkpoint_files',
    'actual_stops','reused_action_component','frozen_observation_members'))


def need(value,code):
    if not value:raise ValueError('REFUSED_P01_IAC628_'+code)


class IdentityPins(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    root_admission_descriptor_sha256:Literal[ROOT_ADMISSION]
    arm:Literal['P01']
    run_id:Literal[RUN]
    head:Literal[HEAD]
    artifact_id:Literal[ARTIFACT]
    outer_sha256:Literal[OUTER]
    inner_sha256:Literal[INNER]
    state_sha256:Literal[STATE]
    input_sha256:Literal[INPUT]
    selected_session:Literal['2020-06-30']
    measured_closes:Literal[628]
    financial_predecessor_admitted:Literal[True]
    qualification_state_adopted:Literal[False]
    current_tails_zero:Literal[True]


def check_spec(spec):
    need(type(spec) is dict and set(spec)<=PUBLIC_KEYS,'PUBLIC_SPEC_EXPLICIT_METADATA_ALLOWLIST')
    IdentityPins.model_validate({n:spec[n] for n in IdentityPins.model_fields})
    need(all(type(spec[n]) is int for n in ('run_id','artifact_id','measured_closes')),
         'STRICT_ACTUAL628_IDENTITY_TYPES')
    need(spec['schema']=='research.p01-own628-iac-unit-predecessor/1'
         and spec['financial_predecessor_admitted'] is True and spec['qualification_state_adopted'] is False
         and spec['current_tails_zero'] is True,'EXACT_ROOT628_BOOLEAN_AUTHORITY')
    need(spec['selected_file']==GZIP and spec['selected_checkpoint']=='book/checkpoint.json.gz'
         and spec['request']==PRIOR and type(spec['total_inputs']) is int and spec['total_inputs']==11
         and spec['request_sha256']==PRIOR_SHA and len(spec['repairs'])==11
         and spec['repairs'][9]['sha256']==TENTH and spec['repairs'][10]==dict(filename=ELEVENTH+'.json',
             sha256=ELEVENTH,resume_session='2020-02-04',predecessor_checkpoint_sha256=ELEVENTH_ORIGINAL_PREDECESSOR),
         'EXACT_ELEVEN_ORIGINAL_INPUT_DESCRIPTORS_NO_RELABEL')
    epoch=spec['source_epoch']
    need(set(epoch['original_source_bindings'])==set(epoch['successor_source_map'])=={'bytes','sha256'},
         'PUBLIC_SOURCE_EPOCH_NO_LOCAL_PATHS')
    need(spec['protocol_sha256']==PROTOCOL and spec['stage']==STAGE and spec['next_session']=='2020-07-01'
         and (epoch['original_physical'],epoch['successor_physical'],epoch['original_canonical'],epoch['successor_canonical'])
             ==(515,516,223,224) and epoch['original_source_bindings']['sha256']==OLD_BINDING
         and epoch['successor_source_map']['sha256']==SOURCE_MAP
         and epoch['successor_source_map_identity_sha256']==MAP_IDENTITY
         and len(spec['retained_checkpoint_files'])==38
         and spec['retained_checkpoint_files']['book/checkpoint.json.gz']==GZIP,
         'EXACT_EXISTING_SOURCE_EPOCH_AND_COMPLETE_GZIP_INVENTORY')
    return spec


def validate_contents(root,spec):
    """Authenticate exact source/input/current-prefix identities without decoding state."""
    check_spec(spec);root=Path(root);path=root/spec['selected_checkpoint']
    need(file_binding(path)==GZIP,'OWN628_GZIP')
    cp=json.loads(gzip.decompress(path.read_bytes()));run=cp['run']
    need(cp['sha256']==OUTER==digest({k:v for k,v in cp.items() if k!='sha256'})
         and run['checkpoint_sha256']==INNER==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==STATE==digest(run['state']) and run['input_sha256']==INPUT
         and INPUT==digest(dict(base=cp['base'],repairs=cp['repairs']))
         and cp['source_cursor']==run['state']['last_processed_session']=='2020-06-30' and cp['completed']==628,
         'EXACT_FULL_ADMITTED628_PREIMAGES')
    need(cp['base']==spec['base'] and cp['repairs']==spec['repairs'] and cp['journals']==spec['journals'],
         'EXACT_BASE_ELEVEN_INPUT_ORDER_AND_PREFIXES')
    for name,entry in cp['journals'].items():
        raw=(root/'book'/(name+'.jsonl')).read_bytes()
        need(len(raw)==entry['bytes'] and sha(raw)==entry['prefix_sha256']
             and (sha(raw.splitlines(keepends=True)[-1]) if raw else None)==entry['last_record_sha256'],
             'FOUR_COMPLETE_PREFIXES_ZERO_CURRENT_TAIL')
    for entry in cp['repairs']:
        need(entry['filename']==entry['sha256']+'.json'
             and file_binding(root/'book/repairs'/entry['filename'])['sha256']==entry['sha256'],
             'ALL_ELEVEN_ORIGINAL_DOCUMENT_BYTES')
    actual={p.relative_to(root).as_posix():file_binding(p) for base in ('book','lineage')
            for p in (root/base).rglob('*.json.gz')}
    need(actual==spec['retained_checkpoint_files'],'ALL38_CURRENT_AND_HISTORICAL_GZIP_BYTES')
    need(sha((root/'source-bindings.json').read_bytes())==OLD_BINDING
         and sha((root/'source-map.json').read_bytes())==SOURCE_MAP
         and sha((root/'source-successor.json').read_bytes())==SOURCE_RECEIPT,'EXACT_ARCHIVED_SOURCE_EPOCH_BYTES')
    mapping=json.loads((root/'source-map.json').read_bytes());binding=json.loads((root/'source-bindings.json').read_bytes())
    receipt=json.loads((root/'source-successor.json').read_bytes())
    need(digest(mapping)==MAP_IDENTITY and len(mapping['predecessor_all_sources'])==515
         and len(mapping['successor_all_sources'])==516 and mapping['predecessor_all_sources']==binding['all_sources']
         and len(mapping['successor_financial_sources'])==224 and cp['base']['sources']==mapping['successor_financial_sources']
         and cp['base']['source_successor_sha256']==SOURCE_RECEIPT
         and receipt['schema']=='research.p01-celg-own475-source-successor/1'
         and receipt['successor_sources']==cp['base']['sources'] and receipt['source_map_sha256']==MAP_IDENTITY
         and receipt['successor_identity']==run['state']['strategy_identity'],'OLD515_DISTINCT_CURRENT516_NO_NEW_BOUNDARY')
    return cp


def _extract(z,asset,key,root,stage):
    """Reuse unchanged authenticated transport AST with explicit actual628 scope."""
    raw=(HERE/'p01_epoch_parent.py').read_bytes();need(sha(raw)==EXTRACTOR_SOURCE,'FROZEN_GENERIC_EXTRACTOR_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_extract']
    import tarfile
    namespace=dict(need=need,sha=sha,file_binding=file_binding,json=json,tarfile=tarfile,shutil=shutil,
                   RUN=RUN,HEAD=HEAD,PRIOR_SHA=PRIOR_SHA,PROTOCOL=PROTOCOL)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<source-bound628-authenticated-extraction>','exec'),namespace)
    return namespace['_extract'](z,asset,key,root,stage)


def stopped(value,metadata,role,source):
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
    site.value='/capital-system-p01-native-resume-'
    cmd,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    mode=dict(qualify='qualify',worker='economic',review='review')[role]
    cmd.comparators=[ast.parse(repr(['-B','-u','/driver/p01_native_resume_run.py','--mode',mode,'--spec','/out/spec.json']),mode='eval').body]
    mount,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=='set(mounts)']
    destinations={'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json'}
    if role!='qualify':destinations.add('/evidence')
    mount.comparators=[ast.parse(repr(destinations),mode='eval').body]
    namespace=dict(need=need,re=re,SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<exact468-actual628-stop-fences>','exec'),namespace)
    namespace['stopped'](value,metadata,role,str(RUN),PRIOR)
    need(value['Id']==STOP_IDS[role] and metadata['exit_code']==0 and metadata['wait_error'] is None
         and re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',value['Config']['User']), 'ACTUAL628_SUCCESSFUL_NONROOT_STOP')


def admit(root,key,spec):
    import system_campaign_factual_admit as crypto
    from ephemeral_runner_capacity import validate_prepared_receipt
    check_spec(spec);root=crypto.hosted_destination(root);root.mkdir(mode=0o700)
    need(shutil.disk_usage(root).free>=4*1024**3+ZIP['bytes'],'CIPHER_AND_FULL_EXTRACTION_RESERVE')
    raw=(HERE/PRIOR).read_bytes();need(sha(raw)==PRIOR_SHA,'FROZEN468_RAW_REQUEST')
    request=json.loads(raw)
    need(len(request['sources'])==468 and all(sha((HERE/n).read_bytes())==h for n,h in request['sources'].items()),
         'ALL468_PUBLISHED_SOURCE_BYTES')
    archive=root/'predecessor.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh','api',f'repos/flabber1835/stocker/actions/artifacts/{ARTIFACT}/zip'],stdout=out,check=True,timeout=180)
    need(file_binding(archive)==ZIP,'EXACT_RETAINED628_ARTIFACT_ZIP')
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist())==len(set(z.namelist())),'UNIQUE_ZIP')
        public=z.read('p01-native-resume.json');need(sha(public)==RECEIPT,'ACTUAL_PUBLIC_RECEIPT')
        receipt=json.loads(public)
        need(receipt['request_sha256']==PRIOR_SHA and receipt['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
             and receipt['production_contacted'] is False,'ACTUAL_KNOWN_SUCCESSFUL628_SCOPE')
        marker=z.read('p01-native-resume-export-qualification.json');proof=json.loads(marker)
        need(sha(marker)==receipt['export_qualification_sha256']==MARKER and proof['request_sha256']==PRIOR_SHA
             and proof['source_adapter_sha256']==request['sources']['p01_native_resume_export.py']
             and proof['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED','ACTUAL628_CRYPTO_MARKER')
        validate_prepared_receipt(json.loads(z.read('ephemeral-runner-capacity.json')),
            head=HEAD,run_id=str(RUN),source_sha256=request['capacity_source_sha256'])
        need(set(z.namelist())=={'ephemeral-runner-capacity.json','full-core-staging.json','p01-native-resume-phase.json',
             'p01-native-resume-export-qualification.json','p01-native-resume.json',
             receipt['encrypted_output']['name'],receipt['qualification_encrypted_output']['name']},'ALL_SEVEN_ZIP_MEMBERS')
        q=_extract(z,receipt['qualification_encrypted_output'],key,root/'qualified',QSTAGE)
        dest=root/'admitted';f=_extract(z,receipt['encrypted_output'],key,dest,STAGE)
        need(len(q)==12 and len(f)==113 and all(f.get(n)==v for n,v in q.items()),'BOTH_FULL628_INVENTORIES')
    for role,name,field in [('qualify','qualification/worker-inspect.json','qualification_worker'),
        ('worker','worker-inspect.json','worker'),('review','stopped-review/worker-inspect.json','reviewer')]:
        stopped(json.loads((dest/name).read_bytes()),receipt[field],role,(HERE/'system_campaign_p02_close_diagnostics.py').read_bytes())
    need((dest/'request.json').read_bytes()==raw and receipt['protocol_sha256']==request['protocol_sha256'],
         'WHOLE_RAW_PRIVATE_REQUEST_AND_EXACT_PROTOCOL')
    validate_contents(dest,spec)
    return dest
