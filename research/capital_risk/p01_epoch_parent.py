"""Admit the exact OWN526 source epoch without decoding a financial state."""
from __future__ import annotations

import ast
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from typing import Literal
import zipfile

from pydantic import BaseModel, ConfigDict

HERE = Path(__file__).parent
ROOT_ADMISSION = '2799bc888566c90627728341ca3d6ba455143f00e60a0dd3b5131c6d9b801886'
PRIOR = 'p01_celg_bridge_request.json'
PRIOR_SHA = '2986d3f443daab0840e9d0592799cbbeac45431310c58f584663b06429d07d80'
RUN = 41388852859
HEAD = '40fd373ea1c419f6c0fe46b08ee234bc8c2e2180'
ARTIFACT = 13117112403
OUTER = 'ff0eb01b8afb168e4fb225140857f3a30212af2c136564fc76b25a5ec90e4e2b'
INNER = 'a3576136388aed10e7a833eb87b5314ad6c7381597448d5c1359a9d0840d4a7b'
STATE = '8ca2d00564a4937f4be447c2bf6b7f9fcfbca85bd3e2bb4442ec72d48814c0be'
INPUT = '3f5360ad5c60c65d41066027a2b18a7d697b7acbc6eae4ee083acd7cf93a9faa'
SOURCE_RECEIPT = '150a2d9056b83bc66d0f9634ddfc6036689e3c35e153c4120a213c870ebe36fc'
SOURCE_MAP = '427871409b2bd7be1e3e24b3fb5885e9be3f8d5f1adeaf275f863f89319cbcdb'
MAP_IDENTITY = 'c3a47c8c7d7facc3d7bd798b74fd3f3fbb9dd0115b86369b7dc5b4f3e1aab915'
OLD_BINDING = 'cbff432d861381735e7bba6ecd79491b059405cde8840cc2d128dbbad85d0b14'
TENTH = '0b6a466a45816d48451ece232969029edef3157c45c4aeeaf1ec697bfe50539f'
STAGE = 'campaign-p01-celg-financial-bridge'
QSTAGE = 'campaign-p01-celg-source-input-qualification'
PROTOCOL = 'a5bacaa1bc51bb5ac376b5163186208aeb4d3aedd130fa7ccdb5e54058cb26d3'
ZIP = dict(bytes=102191014, sha256='51c5ab366dc50dc69a7e2ffc77d934f573ed41d80f77891c49a7e24facf62147')
GZIP = dict(bytes=1194868, sha256='c7eb64e2803dff886346fa849ce7486ce3aaab26de0f09210b096742b89fb417')
RECEIPT = '13e11abff0b4775a31ce5c72ff952793ed431626abc89dbed209befe960a4427'
MARKER = 'f88d972724ae57d28b05cd836f88fd5f78acfb30c4d8c280ee0ff83a30621b77'
STOP_IDS = dict(qualify='66a712499faf5d8d6f327d924a4a7d5bed482535707614bfc10a6a21023fdb9f',
    worker='f48027a58294eafb781106ed247d520ffa7fcaacf69e684f124155d5ca702daa',
    review='33c1ae13a33743fa531c8e93344bc3bffd900d4d2fe98946d8d50d7378dfe2de')


def need(value, code):
    if not value: raise ValueError('REFUSED_P01_EPOCH_' + code)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def digest(value): return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
def file_binding(path):
    raw = Path(path).read_bytes()
    return dict(bytes=len(raw), sha256=sha(raw))


class IdentityPins(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    root_admission_descriptor_sha256: Literal[ROOT_ADMISSION]
    arm: Literal['P01']
    run_id: Literal[RUN]
    head: Literal[HEAD]
    artifact_id: Literal[ARTIFACT]
    outer_sha256: Literal[OUTER]
    inner_sha256: Literal[INNER]
    state_sha256: Literal[STATE]
    input_sha256: Literal[INPUT]
    selected_session: Literal['2020-02-04']
    measured_closes: Literal[526]
    financial_predecessor_admitted: Literal[True]
    qualification_state_adopted: Literal[False]
    current_tails_zero: Literal[True]


def check_spec(spec):
    IdentityPins.model_validate({name: spec[name] for name in IdentityPins.model_fields})
    need(spec['financial_predecessor_admitted'] is True and spec['qualification_state_adopted'] is False
         and spec['current_tails_zero'] is True, 'EXACT_BOOLEAN_AUTHORITY')
    need(spec['selected_file'] == GZIP and spec['selected_checkpoint'] == 'book/checkpoint.json.gz'
         and spec['request_sha256'] == PRIOR_SHA and len(spec['repairs']) == 10
         and spec['repairs'][-1]['sha256'] == TENTH, 'EXACT_ADMITTED_METADATA')
    epoch = spec['source_epoch']
    need(spec['protocol_sha256'] == PROTOCOL and spec['stage'] == STAGE
         and spec['next_session'] == '2020-02-05'
         and (epoch['original_physical'], epoch['successor_physical'],
              epoch['original_canonical'], epoch['successor_canonical']) == (515,516,223,224)
         and epoch['original_source_bindings']['sha256'] == OLD_BINDING
         and epoch['successor_source_map']['sha256'] == SOURCE_MAP
         and epoch['successor_source_map_identity_sha256'] == MAP_IDENTITY,
         'EXACT_CURRENT_EPOCH_AND_NEXT_SESSION')
    return spec


def validate_contents(root, spec):
    """Hash/JSON checks only; deliberately no Ledger, SessionState or runtime import."""
    check_spec(spec); root = Path(root)
    need(file_binding(root / spec['selected_checkpoint']) == GZIP, 'OWN526_GZIP')
    cp = json.loads(gzip.decompress((root / spec['selected_checkpoint']).read_bytes()))
    run = cp['run']
    need(cp['sha256'] == OUTER == digest({k:v for k,v in cp.items() if k != 'sha256'})
         and run['checkpoint_sha256'] == INNER == digest({k:v for k,v in run.items() if k != 'checkpoint_sha256'})
         and run['state_sha256'] == STATE == digest(run['state']) and run['input_sha256'] == INPUT
         and run['input_sha256'] == digest(dict(base=cp['base'], repairs=cp['repairs']))
         and cp['source_cursor'] == run['state']['last_processed_session'] == '2020-02-04'
         and cp['completed'] == 526, 'ENTIRE_ADMITTED_CHECKPOINT_PREIMAGES')
    need(cp['base'] == spec['base'] and cp['repairs'] == spec['repairs']
         and cp['journals'] == spec['journals'], 'EXACT_BASE_INPUT_ORDER_AND_PREFIX_COMMITMENTS')
    for name, entry in cp['journals'].items():
        raw = (root / 'book' / (name + '.jsonl')).read_bytes()
        need(len(raw) == entry['bytes'] and sha(raw) == entry['prefix_sha256']
             and (sha(raw.splitlines(keepends=True)[-1]) if raw else None) == entry['last_record_sha256'],
             'EXACT_COMMITTED_PREFIX_ZERO_CURRENT_TAIL')
    for entry in cp['repairs']:
        need(entry['filename'] == entry['sha256'] + '.json'
             and sha((root / 'book/repairs' / entry['filename']).read_bytes()) == entry['sha256'],
             'ALL_TEN_ARCHIVED_DOCUMENT_BYTES')
    need(sha((root / 'source-bindings.json').read_bytes()) == OLD_BINDING
         and sha((root / 'source-map.json').read_bytes()) == SOURCE_MAP
         and sha((root / 'source-successor.json').read_bytes()) == SOURCE_RECEIPT, 'SOURCE_EPOCH_ARCHIVED_BYTES')
    mapping = json.loads((root / 'source-map.json').read_bytes())
    binding = json.loads((root / 'source-bindings.json').read_bytes())
    receipt = json.loads((root / 'source-successor.json').read_bytes())
    need(digest(mapping) == MAP_IDENTITY and len(mapping['predecessor_all_sources']) == 515
         and len(mapping['successor_all_sources']) == 516
         and mapping['predecessor_all_sources'] == binding['all_sources']
         and len(mapping['successor_financial_sources']) == 224
         and cp['base']['sources'] == mapping['successor_financial_sources']
         and cp['base']['source_successor_sha256'] == SOURCE_RECEIPT
         and receipt['schema'] == 'research.p01-celg-own475-source-successor/1'
         and receipt['successor_sources'] == cp['base']['sources']
         and receipt['source_map_sha256'] == MAP_IDENTITY
         and receipt['successor_identity'] == run['state']['strategy_identity'], 'DISTINCT_OLD515_AND_CURRENT516_EPOCHS')
    return cp


def _extract(z, asset, key, root, stage):
    import system_campaign_factual_admit as crypto
    from seal import safe_name
    need(z.getinfo(asset['name']).file_size == asset['bytes'], 'CIPHER_LENGTH')
    header, tag = crypto.authenticate(z, asset, key)
    root.mkdir(mode=0o700)
    with z.open(asset['name']) as source:
        plain = crypto.AuthenticatedStream(source, asset, key, header, tag)
        with tarfile.open(fileobj=plain, mode='r|gz') as tar:
            first = tar.next()
            need(first.name == 'manifest.json' and first.isfile() and first.size < 2*1024**2, 'FIRST_MANIFEST')
            raw = tar.extractfile(first).read(); need(sha(raw) == asset['manifest_sha256'], 'MANIFEST_HASH')
            manifest = json.loads(raw)
            need(manifest['schema'] == 'research.full-system-output/1' and manifest['stage'] == stage
                 and manifest['arm'] == 'P01' and int(manifest['run_id']) == RUN and manifest['head'] == HEAD
                 and manifest['request_sha256'] == PRIOR_SHA and manifest['protocol_sha256'] == PROTOCOL,
                 'AUTHENTICATED_SCOPE')
            members = manifest['members']; seen = set()
            need(0 < len(members) < 5000 and sum(v['bytes'] for v in members.values()) < 1024**3, 'BOUNDED_INVENTORY')
            while item := tar.next():
                safe_name(item.name)
                need(item.isfile() and item.name in members and item.name not in seen
                     and item.size == members[item.name]['bytes'], 'COMPLETE_UNIQUE_INVENTORY')
                seen.add(item.name); target = root / item.name
                need(target.resolve().is_relative_to(root.resolve()), 'EXTRACTION_BOUNDARY')
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as src, target.open('xb') as out: shutil.copyfileobj(src, out, 1024**2)
                need(file_binding(target) == members[item.name], 'EVERY_MEMBER_HASH')
            need(seen == set(members), 'NO_MISSING_MEMBER')
        while plain.read(1024**2): pass
    return members


def stopped(value, metadata, role, source):
    fn, = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'stopped']
    site, = [n for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value == '/capital-system-factual-p02-']
    site.value = '/capital-system-p01-celg-bridge-'
    cmd, = [n for n in ast.walk(fn) if isinstance(n, ast.Compare) and ast.unparse(n.left) == "c['Cmd']"]
    mode = dict(qualify='qualify', worker='economic', review='review')[role]
    cmd.comparators = [ast.parse(repr(['-B','-u','/driver/p01_celg_bridge_run.py','--mode',mode,'--spec','/out/spec.json']), mode='eval').body]
    mount, = [n for n in ast.walk(fn) if isinstance(n, ast.Compare) and ast.unparse(n.left) == 'set(mounts)']
    destinations = {'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json'}
    if role != 'qualify': destinations.add('/evidence')
    mount.comparators = [ast.parse(repr(destinations), mode='eval').body]
    namespace = dict(need=need, re=re, SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<exact439-stop-fences>', 'exec'), namespace)
    namespace['stopped'](value, metadata, role, str(RUN), PRIOR)
    need(value['Id'] == STOP_IDS[role] and metadata['exit_code'] == 0
         and metadata['wait_error'] is None and re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', value['Config']['User']),
         'EXACT_ACTUAL_SUCCESSFUL_NONROOT_STOP')


def admit(root, key, spec):
    """Hosted acquisition only; caller retains separate key and immutable source."""
    import system_campaign_factual_admit as crypto
    from ephemeral_runner_capacity import validate_prepared_receipt
    check_spec(spec); root = crypto.hosted_destination(root); root.mkdir(mode=0o700)
    need(shutil.disk_usage(root).free >= 4*1024**3 + ZIP['bytes'], 'LOCAL_CIPHER_AND_EXTRACTION_RESERVE')
    raw = (HERE / PRIOR).read_bytes(); need(sha(raw) == PRIOR_SHA, 'FROZEN439_REQUEST')
    request = json.loads(raw)
    need(len(request['sources']) == 439 and all(sha((HERE/n).read_bytes()) == h for n,h in request['sources'].items()), 'ALL439_SOURCE_BYTES')
    archive = root / 'predecessor.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh','api',f'repos/flabber1835/stocker/actions/artifacts/{ARTIFACT}/zip'], stdout=out, check=True, timeout=180)
    need(file_binding(archive) == ZIP, 'EXACT_RETAINED_ARTIFACT_ZIP')
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist()) == len(set(z.namelist())), 'UNIQUE_ZIP')
        public = z.read('p01-celg-bridge.json'); need(sha(public) == RECEIPT, 'EXACT_PUBLIC_RECEIPT')
        receipt = json.loads(public)
        need(receipt['request_sha256'] == PRIOR_SHA and receipt['status'] == 'FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
             and receipt['production_contacted'] is False, 'KNOWN_SUCCESSFUL_SCOPE')
        marker = z.read('p01-celg-bridge-export-qualification.json'); proof = json.loads(marker)
        need(sha(marker) == receipt['export_qualification_sha256'] == MARKER
             and proof['request_sha256'] == PRIOR_SHA and proof['source_adapter_sha256'] == request['sources']['p01_celg_bridge_export.py']
             and proof['status'] == 'P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED', 'ACTUAL_CRYPTO_MARKER')
        validate_prepared_receipt(json.loads(z.read('ephemeral-runner-capacity.json')), head=HEAD, run_id=str(RUN), source_sha256=request['capacity_source_sha256'])
        need(set(z.namelist()) == {'ephemeral-runner-capacity.json','full-core-staging.json','p01-celg-bridge-phase.json',
             'p01-celg-bridge-export-qualification.json','p01-celg-bridge.json',receipt['encrypted_output']['name'],receipt['qualification_encrypted_output']['name']}, 'EXACT_SEVEN_ZIP_MEMBERS')
        q = _extract(z, receipt['qualification_encrypted_output'], key, root/'qualified', QSTAGE)
        dest = root/'admitted'; f = _extract(z, receipt['encrypted_output'], key, dest, STAGE)
        need(len(q) == 13 and len(f) == 97 and all(f.get(n) == v for n,v in q.items()), 'BOTH_COMPLETE_RETAINED_INVENTORIES')
    for role,name,field in [('qualify','qualification/worker-inspect.json','qualification_worker'),('worker','worker-inspect.json','worker'),('review','stopped-review/worker-inspect.json','reviewer')]:
        stopped(json.loads((dest/name).read_bytes()), receipt[field], role, (HERE/'system_campaign_p02_close_diagnostics.py').read_bytes())
    need((dest/'request.json').read_bytes() == raw and receipt['protocol_sha256'] == request['protocol_sha256'], 'WHOLE_PRIVATE_REQUEST_AND_PROTOCOL')
    validate_contents(dest, spec)
    return dest
