"""Exact root-admitted OWN627 transport; raw metadata only, never state restore."""
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
ROOT_ADMISSION='16eaa4b08f1111e9894b1e18759c8b02e82e5c801b4f819767a7ef652c1915c9'
PRIOR='p01_factual_batch_request.json'
PRIOR_SHA='2ce21c812d8b9168d519361dda55481ff993a57fe0634e3a292ee4b3cd9fd305'
RUN=41403517644;HEAD='c2eaec48cc9a0ead3b3066df9bd477d158615749';ARTIFACT=13123608374
OUTER='0ea1fbdbc50c17c53af5380c18e734f97512df859d22a4f3e6600c56cba5ae19'
INNER='3ae6bb2e7db30d239d86e61c3313f544c5d8951e76c36b650824c10f9d787d7a'
STATE='e314cbea00c412ca58bcfcdd7334dc7a12c412e7a75504d84e4714b9755fbe0e'
INPUT='53c3b13673552dbf98263ab0272ac11c8951de619bf19e9ddf2020e59b01584a'
ELEVENTH='430c69b8771ccbfb7b915618cb4536851c5505761cca102cc7b74576cb8b088c'
ELEVENTH_ORIGINAL_PREDECESSOR='a3576136388aed10e7a833eb87b5314ad6c7381597448d5c1359a9d0840d4a7b'
STAGE='campaign-p01-grouped-factual-financial';QSTAGE='campaign-p01-grouped-factual-qualification'
ZIP=dict(bytes=178557670,sha256='211c04c54ed2248dc1891f17ae0861673e51d87518a0c3f520b6aafb0c6f9553')
GZIP=dict(bytes=1208602,sha256='c778a71ec4f88fd7fdc91e25961754329c13e9a05dccb426be79c013e898d49b')
RECEIPT='f521141a079d4f58b269f4651fbff59d426d0fa3318fd1268a941ab515da280e'
MARKER='b4fd5f1a475767e9a2ffae15ed227420321a3097fdebfcdc91599aac55e9cb02'
STOP_IDS=dict(qualify='c951145b8c63a6a9000ad63e09d82d5a6dd106c9bc85f71660c38d248583ab84',
 worker='a6a703709ed93f826cfb0a72d205826ef3b716a2022fbeb25ff1f1d17b407f80',
 review='d5ed52e6e44b360a6c5be9aa69355286e8c75427d4ac28485e9995e278531508')
EXTRACTOR_SOURCE='6e4218a374b145d3fd250fe46d9275119a3664994593191d618623fd478870f7'


def need(value,code):
    if not value:raise ValueError('REFUSED_P01_NATIVE627_'+code)


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
    selected_session:Literal['2020-06-29']
    measured_closes:Literal[627]
    financial_predecessor_admitted:Literal[True]
    qualification_state_adopted:Literal[False]
    current_tails_zero:Literal[True]


def check_spec(spec):
    IdentityPins.model_validate({n:spec[n] for n in IdentityPins.model_fields})
    need(spec['schema']=='research.p01-own627-native-resume-predecessor/1'
         and spec['financial_predecessor_admitted'] is True and spec['qualification_state_adopted'] is False
         and spec['current_tails_zero'] is True,'EXACT_ROOT627_BOOLEAN_AUTHORITY')
    need(spec['selected_file']==GZIP and spec['selected_checkpoint']=='book/checkpoint.json.gz'
         and spec['request_sha256']==PRIOR_SHA and len(spec['repairs'])==11
         and spec['repairs'][9]['sha256']==TENTH and spec['repairs'][10]==dict(filename=ELEVENTH+'.json',
             sha256=ELEVENTH,resume_session='2020-02-04',predecessor_checkpoint_sha256=ELEVENTH_ORIGINAL_PREDECESSOR),
         'EXACT_ELEVEN_ORIGINAL_INPUT_DESCRIPTORS_NO_RELABEL')
    epoch=spec['source_epoch']
    need(spec['protocol_sha256']==PROTOCOL and spec['stage']==STAGE and spec['next_session']=='2020-06-30'
         and (epoch['original_physical'],epoch['successor_physical'],epoch['original_canonical'],epoch['successor_canonical'])
             ==(515,516,223,224) and epoch['original_source_bindings']['sha256']==OLD_BINDING
         and epoch['successor_source_map']['sha256']==SOURCE_MAP
         and epoch['successor_source_map_identity_sha256']==MAP_IDENTITY
         and len(spec['retained_checkpoint_files'])==34
         and spec['retained_checkpoint_files']['book/checkpoint.json.gz']==GZIP,
         'EXACT_EXISTING_SOURCE_EPOCH_AND_COMPLETE_GZIP_INVENTORY')
    return spec


def validate_contents(root,spec):
    """Authenticate exact source/input/current-prefix identities without decoding state."""
    check_spec(spec);root=Path(root);path=root/spec['selected_checkpoint']
    need(file_binding(path)==GZIP,'OWN627_GZIP')
    cp=json.loads(gzip.decompress(path.read_bytes()));run=cp['run']
    need(cp['sha256']==OUTER==digest({k:v for k,v in cp.items() if k!='sha256'})
         and run['checkpoint_sha256']==INNER==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==STATE==digest(run['state']) and run['input_sha256']==INPUT
         and INPUT==digest(dict(base=cp['base'],repairs=cp['repairs']))
         and cp['source_cursor']==run['state']['last_processed_session']=='2020-06-29' and cp['completed']==627,
         'EXACT_FULL_ADMITTED627_PREIMAGES')
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
    need(actual==spec['retained_checkpoint_files'],'ALL34_CURRENT_AND_HISTORICAL_GZIP_BYTES')
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
    """Reuse unchanged authenticated transport AST with explicit actual627 scope."""
    raw=(HERE/'p01_epoch_parent.py').read_bytes();need(sha(raw)==EXTRACTOR_SOURCE,'FROZEN_GENERIC_EXTRACTOR_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_extract']
    import tarfile
    namespace=dict(need=need,sha=sha,file_binding=file_binding,json=json,tarfile=tarfile,shutil=shutil,
                   RUN=RUN,HEAD=HEAD,PRIOR_SHA=PRIOR_SHA,PROTOCOL=PROTOCOL)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<source-bound627-authenticated-extraction>','exec'),namespace)
    return namespace['_extract'](z,asset,key,root,stage)


def stopped(value,metadata,role,source):
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
    site.value='/capital-system-p01-factual-batch-'
    cmd,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    mode=dict(qualify='qualify',worker='economic',review='review')[role]
    cmd.comparators=[ast.parse(repr(['-B','-u','/driver/p01_factual_batch_run.py','--mode',mode,'--spec','/out/spec.json']),mode='eval').body]
    mount,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=='set(mounts)']
    destinations={'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json'}
    if role!='qualify':destinations.add('/evidence')
    mount.comparators=[ast.parse(repr(destinations),mode='eval').body]
    namespace=dict(need=need,re=re,SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<exact456-actual627-stop-fences>','exec'),namespace)
    namespace['stopped'](value,metadata,role,str(RUN),PRIOR)
    need(value['Id']==STOP_IDS[role] and metadata['exit_code']==0 and metadata['wait_error'] is None
         and re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',value['Config']['User']), 'ACTUAL627_SUCCESSFUL_NONROOT_STOP')


def admit(root,key,spec):
    import system_campaign_factual_admit as crypto
    from ephemeral_runner_capacity import validate_prepared_receipt
    check_spec(spec);root=crypto.hosted_destination(root);root.mkdir(mode=0o700)
    need(shutil.disk_usage(root).free>=4*1024**3+ZIP['bytes'],'CIPHER_AND_FULL_EXTRACTION_RESERVE')
    raw=(HERE/PRIOR).read_bytes();need(sha(raw)==PRIOR_SHA,'FROZEN456_RAW_REQUEST')
    request=json.loads(raw)
    need(len(request['sources'])==456 and all(sha((HERE/n).read_bytes())==h for n,h in request['sources'].items()),
         'ALL456_PUBLISHED_SOURCE_BYTES')
    archive=root/'predecessor.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh','api',f'repos/flabber1835/stocker/actions/artifacts/{ARTIFACT}/zip'],stdout=out,check=True,timeout=180)
    need(file_binding(archive)==ZIP,'EXACT_RETAINED627_ARTIFACT_ZIP')
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist())==len(set(z.namelist())),'UNIQUE_ZIP')
        public=z.read('p01-factual-batch.json');need(sha(public)==RECEIPT,'ACTUAL_PUBLIC_RECEIPT')
        receipt=json.loads(public)
        need(receipt['request_sha256']==PRIOR_SHA and receipt['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
             and receipt['production_contacted'] is False,'ACTUAL_KNOWN_SUCCESSFUL627_SCOPE')
        marker=z.read('p01-factual-batch-export-qualification.json');proof=json.loads(marker)
        need(sha(marker)==receipt['export_qualification_sha256']==MARKER and proof['request_sha256']==PRIOR_SHA
             and proof['source_adapter_sha256']==request['sources']['p01_factual_batch_export.py']
             and proof['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED','ACTUAL627_CRYPTO_MARKER')
        validate_prepared_receipt(json.loads(z.read('ephemeral-runner-capacity.json')),
            head=HEAD,run_id=str(RUN),source_sha256=request['capacity_source_sha256'])
        need(set(z.namelist())=={'ephemeral-runner-capacity.json','full-core-staging.json','p01-factual-batch-phase.json',
             'p01-factual-batch-export-qualification.json','p01-factual-batch.json',
             receipt['encrypted_output']['name'],receipt['qualification_encrypted_output']['name']},'ALL_SEVEN_ZIP_MEMBERS')
        q=_extract(z,receipt['qualification_encrypted_output'],key,root/'qualified',QSTAGE)
        dest=root/'admitted';f=_extract(z,receipt['encrypted_output'],key,dest,STAGE)
        need(len(q)==14 and len(f)==110 and all(f.get(n)==v for n,v in q.items()),'BOTH_FULL627_INVENTORIES')
    for role,name,field in [('qualify','qualification/worker-inspect.json','qualification_worker'),
        ('worker','worker-inspect.json','worker'),('review','stopped-review/worker-inspect.json','reviewer')]:
        stopped(json.loads((dest/name).read_bytes()),receipt[field],role,(HERE/'system_campaign_p02_close_diagnostics.py').read_bytes())
    need((dest/'request.json').read_bytes()==raw and receipt['protocol_sha256']==request['protocol_sha256'],
         'WHOLE_RAW_PRIVATE_REQUEST_AND_EXACT_PROTOCOL')
    validate_contents(dest,spec)
    return dest
