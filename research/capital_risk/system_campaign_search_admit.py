"""Hosted read-only authentication of stopped numerical evidence for selection."""
import gzip,hashlib,json,os,re,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from full_system_benchmark import need
from probe import check_context,FORBIDDEN_CREDENTIALS
from seal import safe_name,sha256_file
from system_campaign_factual_admit import authenticate,AuthenticatedStream,archive_bound
from system_campaign_facts import digest
from system_campaign_space import record

KEEP={'request.json','book/summary.json','book/semantic-basis-admission.json','book/common-factual-basis.json',
    'book/training-2020-12-31.json','book/training-2022-12-30.json','book/joint-registry.json',
    'economic-worker-inspect.json','independent-review-stop/worker-inspect.json',
    'independent-review-stop/review/independent-review.json'}


def actual_stop(v,arm,run,role):
    need(v['Name']==f'/capital-system-joint-{arm.lower()}-{role}-{run}-1'
         and re.fullmatch('[a-f0-9]{64}',v['Id']) and v['Image']=='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
         and not v['State']['Running'] and not v['State']['OOMKilled'] and v['State']['ExitCode']==0,'SEARCH_ADMIT_ACTUAL_STOP')
    h,c=v['HostConfig'],v['Config'];m={r['Destination']:r for r in v['Mounts'] if r['Type']=='bind'}
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
         and h['PidsLimit']==64 and h['ReadonlyRootfs'] and h['CapDrop']==['ALL']
         and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']),'SEARCH_ADMIT_ACTUAL_FENCES')
    has_basis='--equivalence-proof' in c['Cmd'];expected={'/variant','/frozen','/driver','/out','/core'}|({'/evidence'} if role=='review' else set())|({'/basis'} if has_basis else set())
    need(c['Cmd'].count('/driver/system_campaign_numeric_review.py' if role=='review' else '/driver/system_campaign_numeric.py')==1
         and (not has_basis or c['Cmd'][c['Cmd'].index('--equivalence-proof')+1]=='/basis'),
         'SEARCH_ADMIT_EXACT_NUMERICAL_ENTRY')
    need(set(m)==expected and m['/out']['RW'] and all(not v['RW'] for k,v in m.items() if k!='/out')
         and c['WorkingDir']=='/variant' and re.fullmatch('[1-9][0-9]*:[1-9][0-9]*',c['User'])
         and c['Labels']['research.study']=='full-system-search-20261029' and c['Labels']['research.role']==role,
         'SEARCH_ADMIT_ACTUAL_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{'CAPITAL_RISK_RESEARCH_KEY_20261027','GITHUB_TOKEN','GH_TOKEN'}
    need(not any(k in forbidden and val for k,_,val in (r.partition('=') for r in c['Env'])),'SEARCH_ADMIT_NO_CREDENTIALS')


def envelope(root,spec,receipt,inventory):
    summary=json.loads((root/'book/summary.json').read_bytes());review_raw=(root/'independent-review-stop/review/independent-review.json').read_bytes();review=json.loads(review_raw)
    need(summary['status']=='COMPLETE_JOINT_NUMERICAL_INDEPENDENT_REVIEW_REQUIRED'
         and summary['core_checkpoint_sha256']==receipt['core_checkpoint_sha256']==spec['core_checkpoint_sha256']
         and not summary['global_selection_performed'] and not summary['production_contacted'],
         'SEARCH_ADMIT_COMPLETE_CORE_BINDING')
    need(review['status']=='JOINT_NUMERICAL_TRAINING_REVIEW_PASSED_FINALISTS_REQUIRE_DIRECT_CLASSIFIER_AND_ACCOUNT'
         and review['canonical_core_checkpoint_sha256']==spec['core_checkpoint_sha256']
         and review['common_factual_basis_sha256']==summary['common_factual_basis_sha256']
         and review['all_training_metrics_verified'] and review['baseline_all_account_fields_exact']
         and review['joint_profiles']==4096 and not review['production_contacted'],
         'SEARCH_ADMIT_ACTUAL_INDEPENDENT_REVIEW')
    need(digest(json.loads((root/'book/common-factual-basis.json').read_bytes()))==summary['common_factual_basis_sha256'],
         'SEARCH_ADMIT_ACTUAL_FACTUAL_PREIMAGE')
    request=json.loads((root/'request.json').read_bytes());need(sha256_file(root/'request.json')==receipt['request_sha256']
         and request['core_artifacts'][spec['arm']]['outer_sha256']==spec['core_checkpoint_sha256'],
         'SEARCH_ADMIT_EXACT_NUMERIC_REQUEST')
    parameters=spec['parameters'];core=record(parameters)['id'];training={}
    for cutoff in ('2020-12-31','2022-12-30'):
        value=json.loads((root/('book/training-'+cutoff+'.json')).read_bytes())
        need(value['core_profile_sha256']==digest(parameters) and value['cutoff']==cutoff and value['no_evaluation_fields'],
             'SEARCH_ADMIT_ACTUAL_CORE_PROFILE_AND_TRAINING_CUTOFF');training[cutoff]=value
    for n,role in [('economic-worker-inspect.json','worker'),('independent-review-stop/worker-inspect.json','review')]:
        actual_stop(json.loads((root/n).read_bytes()),spec['arm'],spec['run_id'],role)
    return {'core_id':core,'parameters':parameters,'available_after':spec['available_after'],
        'common_factual_basis_sha256':summary['common_factual_basis_sha256'],'numeric_review_sha256':hashlib.sha256(review_raw).hexdigest(),'training':training}


def admit(spec,dest,key):
    check_context(os.environ);temp=Path(os.environ['RUNNER_TEMP']).resolve();dest=Path(dest).resolve()
    need(os.name=='posix' and str(temp)=='/home/runner/work/_temp' and dest.parent==temp
         and dest.name.startswith('campaign-search-admit-') and shutil.disk_usage(temp).free>4*1024**3,
         'SEARCH_ADMIT_PRIVATE_HOSTED_DESTINATION')
    archive_bound(spec,512*1024**2);dest.mkdir(mode=0o700);archive=dest/'source.zip'
    with archive.open('xb') as f:subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=f,check=True,timeout=180)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'SEARCH_ADMIT_EXACT_ZIP')
    with zipfile.ZipFile(archive) as z:
        raw=z.read(spec['receipt_name']);need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'SEARCH_ADMIT_EXACT_RECEIPT');r=json.loads(raw)
        need(r['schema']=='research.system-campaign-joint-numerical-receipt/1' and r['status']=='JOINT_TRAINING_REVIEWED_FINALIST_CONFIRMATION_REQUIRED'
             and r['arm']==spec['arm'] and int(r['run_id'])==spec['run_id'] and r['head']==spec['head']
             and r['request_sha256']==spec['request_sha256'] and r['protocol_sha256']==spec['protocol_sha256']
             and not r['production_contacted'] and not r['global_selection_performed'] and r['new_core_financial_sessions']==0,
             'SEARCH_ADMIT_EXACT_REVIEWED_SCOPE')
        for role in ('worker','reviewer'):
            need(r[role]['stopped'] and r[role]['exit_code']==0 and not r[role]['oom_killed'],'SEARCH_ADMIT_REVIEWED_STOP_RECEIPT')
        asset=r['encrypted_output'];need(asset==spec['encrypted_output']
             and set(z.namelist())=={spec['receipt_name'],'full-core-staging.json',asset['name']},'SEARCH_ADMIT_EXACT_MEMBERS')
        header,tag=authenticate(z,asset,key)
        with z.open(asset['name']) as f:
            plain=AuthenticatedStream(f,asset,key,header,tag)
            with tarfile.open(fileobj=plain,mode='r|gz') as tar:
                first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'SEARCH_ADMIT_FIRST_MANIFEST')
                raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'SEARCH_ADMIT_EXACT_MANIFEST');m=json.loads(raw)
                need(m['schema']=='research.full-system-output/1' and m['stage']=='multiyear-controller'
                     and m['arm']==spec['arm'] and int(m['run_id'])==spec['run_id'] and m['head']==spec['head']
                     and m['request_sha256']==spec['request_sha256'] and m['protocol_sha256']==spec['protocol_sha256'],
                     'SEARCH_ADMIT_MANIFEST_BINDINGS')
                inv=m['members'];need(KEEP<=set(inv) and len(inv)<5000 and sum(v['bytes'] for v in inv.values())<1024**3,'SEARCH_ADMIT_BOUNDED_COMPLETE_INVENTORY')
                root=dest/'verified';root.mkdir();seen=set()
                while item:=tar.next():
                    safe_name(item.name);need(item.isfile() and item.name in inv and item.name not in seen and item.size==inv[item.name]['bytes'],'SEARCH_ADMIT_INVENTORY_MEMBER');seen.add(item.name)
                    sink=None;h=hashlib.sha256();count=0
                    if item.name in KEEP:
                        need(item.size<16*1024**2,'SEARCH_ADMIT_BOUNDED_SELECTED_FILE');p=root/item.name;p.parent.mkdir(parents=True,exist_ok=True);sink=p.open('xb')
                    try:
                        with tar.extractfile(item) as f:
                            while raw:=f.read(1024**2):
                                count+=len(raw);h.update(raw)
                                if sink is not None:sink.write(raw)
                    finally:
                        if sink is not None:sink.close()
                    need(count==inv[item.name]['bytes'] and h.hexdigest()==inv[item.name]['sha256'],'SEARCH_ADMIT_EVERY_MEMBER_HASH')
                need(seen==set(inv),'SEARCH_ADMIT_NO_MISSING_MEMBER')
            while plain.read(1024**2):pass
    result=envelope(root,spec,r,inv)
    (dest/'source-manifest.json').write_bytes(json.dumps(m,indent=2).encode()+b'\n')
    return result
