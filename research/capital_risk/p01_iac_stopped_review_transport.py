"""New hosted-use authentication of BOTH immutable ciphers; no state parser."""
from dataclasses import dataclass
import hashlib,json,os,re,subprocess,tarfile,zipfile
from pathlib import Path
import system_campaign_factual_admit as crypto
from full_system_benchmark import need
from seal import sha256_file,safe_name
from probe import FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from ephemeral_runner_capacity import validate_prepared_receipt
from p01_iac_stopped_review_target import HERE,check_target,sha,digest,plain,encoded,read,TARGET_SHA
CRYPTO_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
RO={'/variant','/frozen','/driver','/old','/celg-input','/celg-input-descriptor.json','/evidence'}
SCHEMA='research.p01-stopped-evidence-authentication/1'


def fences(value,name,cmd):
    h,c=value['HostConfig'],value['Config'];binds=[m for m in value['Mounts'] if m['Type']=='bind']
    mounts={m['Destination']:m for m in binds};user=c['User']
    need(value['Name']=='/'+name and re.fullmatch('[0-9a-f]{64}',value['Id']) is not None and value['Image']==EXECUTION_IMAGE,
         'STOPPED_REVIEW_EXACT_CONTAINER_IMAGE_ID_NAME')
    need(len(binds)==len(mounts)==8 and set(mounts)==RO|{'/out'} and mounts['/out']['RW'] is True
        and all(mounts[n]['RW'] is False for n in RO) and type(user) is str
        and re.fullmatch('[0-9]+:[0-9]+',user) is not None and all(int(n)>0 for n in user.split(':')),
        'STOPPED_REVIEW_EIGHT_UNIQUE_BINDS_AND_POSITIVE_UID_GID')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
        and h['PidsLimit']==64 and h['ReadonlyRootfs'] is True and h['CapDrop']==['ALL']
        and any(s.startswith('no-new-privileges') for s in h['SecurityOpt'])
        and c['WorkingDir']=='/variant' and c['Cmd']==cmd
        and c['Labels']['research.study']=='full-system-search-20261029', 'STOPPED_REVIEW_ALL_RESOURCE_SECURITY_COMMAND_FENCES')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{'GH_TOKEN','GITHUB_TOKEN','CAPITAL_RISK_RESEARCH_KEY_20261027'}
    need(not any(k in forbidden and v for k,_,v in (s.partition('=') for s in c['Env'])), 'STOPPED_REVIEW_NO_WORKER_CREDENTIALS')
    return value


def original_stop(value,role,spec):
    old=spec['original'];key={'qualify':'qualification_worker','worker':'worker','review':'reviewer'}[role]
    stop=old['stops'][key];mode={'qualify':'qualify','worker':'economic','review':'review'}[role]
    name=f'capital-system-p01-iac-namespace-{role}-{old["run_id"]}-1'
    fences(value,name,['-B','-u','/driver/p01_iac_namespace_run.py','--mode',mode,'--spec','/out/spec.json'])
    need(value['Id']==old['actual_inspection_ids'][role] and value['State']['Running'] is False
        and value['State']['OOMKilled'] is False and type(value['State']['ExitCode']) is int
        and value['State']['ExitCode']==stop['exit_code']
        and value['Config']['Labels']['research.role']==('review' if role=='review' else 'worker'),
        'STOPPED_REVIEW_ACTUAL_OLD_STOP_ID_AND_ROLE')


def raw_inventory(root,inventory):
    root=Path(root);paths=list(root.rglob('*'))
    need(not root.is_symlink() and not any(p.is_symlink() for p in paths)
        and {p.relative_to(root).as_posix() for p in paths if p.is_file()}==set(inventory), 'STOPPED_REVIEW_EXACT_IMMUTABLE_TREE')
    for name,entry in inventory.items():
        safe_name(name);p=root/name
        need(p.resolve().is_relative_to(root.resolve()) and dict(bytes=p.stat().st_size,sha256=sha256_file(p))==entry,
            'STOPPED_REVIEW_EVERY_RAW_MEMBER_HASH_AT_USE')


def extract(z,asset,key,header,tag,destination,expected,old,stage):
    destination=Path(destination);destination.mkdir(mode=0o700);seen=set()
    with z.open(asset['name']) as source:
        stream=crypto.AuthenticatedStream(source,asset,key,header,tag)
        with tarfile.open(fileobj=stream,mode='r|gz') as tar:
            first=tar.next();need(first is not None and first.name=='manifest.json' and first.isfile()
                and first.size==expected['original_manifest_bytes']<2*1024**2,'STOPPED_REVIEW_MANIFEST_AFTER_BOTH_GCM')
            raw=tar.extractfile(first).read();need(sha(raw)==expected['original_manifest_sha256']==asset['manifest_sha256'], 'STOPPED_REVIEW_RAW_MANIFEST_DOMAIN')
            m=plain(raw);inventory=m['members']
            need(set(m)=={'schema','stage','arm','run_id','head','request_sha256','protocol_sha256','compression','members'}
                and m['schema']=='research.full-system-output/1' and m['stage']==stage and m['arm']=='P01'
                and m['run_id']==str(old['run_id']) and m['head']==old['head'] and m['request_sha256']==old['request_sha256']
                and m['protocol_sha256']==old['financial_protocol_sha256'] and m['compression']=='TAR_GZIP_V1'
                and len(inventory)==expected['member_count']<5000
                and sum(e['bytes'] for e in inventory.values())==expected['raw_member_bytes']<=2*1024**3
                and digest(inventory)==expected['inventory_sha256'],'STOPPED_REVIEW_FULL_MANIFEST_AND_INVENTORY')
            while item:=tar.next():
                safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'STOPPED_REVIEW_UNIQUE_REGULAR_MEMBER')
                seen.add(item.name);entry=inventory[item.name]
                need(set(entry)=={'bytes','sha256'} and type(entry['bytes']) is int and entry['bytes']>=0
                    and item.size==entry['bytes'] and re.fullmatch('[0-9a-f]{64}',entry['sha256']) is not None,'STOPPED_REVIEW_TYPED_MEMBER_DESCRIPTOR')
                target=destination/item.name;need(target.resolve().is_relative_to(destination.resolve()),'STOPPED_REVIEW_MEMBER_CONTAINMENT')
                target.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(item) as src,target.open('xb') as out:
                    h=hashlib.sha256();count=0
                    while block:=src.read(1024**2):h.update(block);count+=len(block);out.write(block)
                    out.flush();os.fsync(out.fileno())
                need(dict(bytes=count,sha256=h.hexdigest())==entry,'STOPPED_REVIEW_RAW_EXTRACTION_HASH')
            need(seen==set(inventory),'STOPPED_REVIEW_COMPLETE_ENTIRE_INVENTORY')
        while stream.read(1024**2):pass
    return m


def unpack(z,key,root,spec):
    """All tags first; all inventories next; only then static inspection JSON."""
    check_target(spec);old=spec['original'];public={};names=z.namelist();assets=old['assets']
    need(len(names)==len(set(names)) and set(names)==set(spec['public_members'])|{e['name'] for e in assets.values()}, 'STOPPED_REVIEW_EXACT_ZIP_NAMES')
    for name,e in spec['public_members'].items():
        need(z.getinfo(name).file_size==e['bytes']<2*1024**2,'STOPPED_REVIEW_PUBLIC_SIZE_BEFORE_READ')
        raw=z.read(name);need(dict(bytes=len(raw),sha256=sha(raw))==e,'STOPPED_REVIEW_ORIGINAL_RAW_PUBLIC_BYTES');public[name]=raw
    headers={}
    for role,keyname in (('qualification','qualification_encrypted_output'),('financial','encrypted_output')):
        asset=assets[keyname];need(z.getinfo(asset['name']).file_size==asset['bytes'],'STOPPED_REVIEW_CIPHER_LENGTH_BEFORE_GCM')
        headers[role]=crypto.authenticate(z,asset,key)
    manifests={}
    for role,keyname in (('qualification','qualification_encrypted_output'),('financial','encrypted_output')):
        manifests[role]=extract(z,assets[keyname],key,*headers[role],Path(root)/role,old['manifests'][role],old,'campaign-p01-iac-namespace-'+role)
    # No checkpoint/book JSON is parsed here or below.
    receipt=plain(public['p01-iac-namespace.json']);marker=plain(public['p01-iac-namespace-export-qualification.json'])
    need(receipt['schema']==old['receipt']['schema'] and receipt['stage']==old['receipt']['stage']
        and receipt['status']=='FINANCIAL_SUFFIX_REVIEW_REFUSED_PRESERVED' and receipt['run_id']==str(old['run_id'])
        and receipt['head']==old['head'] and receipt['request_sha256']==old['request_sha256']
        and receipt['qualification_encrypted_output']==assets['qualification_encrypted_output'] and receipt['encrypted_output']==assets['encrypted_output']
        and all(receipt[k]==v for k,v in old['stops'].items()) and receipt['production_contacted'] is False
        and receipt['qualification_exported'] is True and receipt['encrypted_output_exported'] is True,'STOPPED_REVIEW_ORIGINAL_RECEIPT_AND_STOPS')
    request=plain(read(HERE/old['request_file']))
    need(sha(read(HERE/old['request_file']))==old['request_sha256'] and len(request['sources'])==515
        and all(sha256_file(HERE/n)==h for n,h in request['sources'].items()),'STOPPED_REVIEW_ENTIRE_ORIGINAL515_SOURCE_AND_RAW_REQUEST')
    need(marker['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED' and marker['request_sha256']==old['request_sha256']
        and marker['source_adapter_sha256']==request['sources']['p01_iac_namespace_export.py']
        and sha(public['p01-iac-namespace-export-qualification.json'])==receipt['export_qualification_sha256'],'STOPPED_REVIEW_ORIGINAL_MARKER')
    validate_prepared_receipt(plain(public['ephemeral-runner-capacity.json']),head=old['head'],run_id=str(old['run_id']),source_sha256=request['capacity_source_sha256'])
    q,f=Path(root)/'qualification',Path(root)/'financial'
    for name,entry in manifests['qualification']['members'].items():
        need(manifests['financial']['members'].get(name)==entry and sha256_file(q/name)==sha256_file(f/name),'STOPPED_REVIEW_EVERY_Q15_BYTE_RETAINED_IN_F')
    need((f/'request.json').read_bytes()==(q/'request.json').read_bytes()==read(HERE/old['request_file'])
        and (f/'spec.json').read_bytes()==(q/'spec.json').read_bytes()==read(HERE/request['source_financial_file']), 'STOPPED_REVIEW_WHOLE_TARGET_REQUEST_SPEC')
    for role,path in (('qualify',q/'qualification/worker-inspect.json'),('worker',f/'worker-inspect.json'),('review',f/'stopped-review/worker-inspect.json')):
        original_stop(plain(read(path)),role,spec)
    return dict(schema=SCHEMA,target_sha256=TARGET_SHA,manifests=manifests,original_stops=old['stops'],both_tags_and_entire_inventories_authenticated=True,
        target_financial_envelope=dict(run_id=old['run_id'],head=old['head'],request_sha256=old['request_sha256'],source_count=515),
        financial_payloads_parsed=False,financial_authority=False,original_states_adopted=False)


@dataclass(frozen=True)
class Evidence:
    qualification_root:Path
    financial_root:Path
    authentication:dict


def authenticate(spec,root,key):
    check_target(spec);need(sha256_file(Path(crypto.__file__))==CRYPTO_SHA,'STOPPED_REVIEW_FROZEN_CRYPTO_SOURCE')
    root=crypto.hosted_destination(root);need(type(key) is bytes and len(key)==32,'STOPPED_REVIEW_SEPARATE_KEY')
    root.mkdir(mode=0o700);archive=root/'original.zip';old=spec['original']
    with archive.open('xb') as stream:subprocess.run(['gh','api',f'repos/flabber1835/stocker/actions/artifacts/{old["artifact_id"]}/zip'],stdout=stream,check=True,timeout=180)
    need(dict(bytes=archive.stat().st_size,sha256=sha256_file(archive))==old['zip'],'STOPPED_REVIEW_EXACT_IMMUTABLE_ZIP')
    with zipfile.ZipFile(archive) as z:auth=unpack(z,key,root,spec)
    return Evidence(root/'qualification',root/'financial',auth)


def verify_tree(root,spec,authentication):
    check_target(spec);need(authentication['schema']==SCHEMA and authentication['target_sha256']==TARGET_SHA
        and authentication['both_tags_and_entire_inventories_authenticated'] is True and authentication['original_stops']==spec['original']['stops']
        and authentication['financial_authority'] is False and authentication['original_states_adopted'] is False,'STOPPED_REVIEW_AUTHENTICATION_LINK_BEFORE_STATE_PARSER')
    m=authentication['manifests'];old=spec['original']
    for role in ('qualification','financial'):
        raw=(json.dumps(m[role],sort_keys=True)+'\n').encode();e=old['manifests'][role]
        need(sha(raw)==e['original_manifest_sha256'] and digest(m[role]['members'])==e['inventory_sha256'],'STOPPED_REVIEW_MANIFEST_PREIMAGE_AT_USE')
    raw_inventory(root,m['financial']['members'])
    need(all(m['financial']['members'].get(n)==v for n,v in m['qualification']['members'].items()),'STOPPED_REVIEW_Q15_RETAINED_AT_USE')
    return authentication
