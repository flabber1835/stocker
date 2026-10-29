"""Authenticate own failed book and continue exact factual suffix on hosted compute."""
import argparse,base64,gzip,hashlib,io,json,os,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from datetime import datetime,timezone
from full_system_trials_job import command,inspect,seal,ARMS
from full_system_source import build,proposals
from full_system_benchmark import need
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from seal import decrypt,safe_name,sha256_file
from stage import SECRET

HERE=Path(__file__).resolve().parent
SOURCES=('full_system_recovery_job.py','full_system_recovery.py','full_system_core.py','full_system_source.py',
    'full_system_trials_job.py','full_system_benchmark.py','build_core_variants.py','core_manifest.py','core_accounting_snapshot.py',
    'core-source-basis.json','core_window_review.py','alpaca_fit_job.py','alpaca_fit_stage.py','probe.py','runtime_identity.py','seal.py','stage.py')

def request():
    return {'schema':'research.full-system-recovery-request/1','study':'full-system-search-20261029',
        'predecessors_sha256':sha256_file(HERE/'full-system-predecessors.json'),
        'protocol_sha256':sha256_file(HERE/'full-system-search-protocol.json'),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'hard_deadline_utc':'2026-10-29T17:57:00Z',
        'same_scientific_parameters':True,'source_conversion':False,'production_contacted':False}

def predecessor(spec,root,key,arm):
    folder=root/'transfer';folder.mkdir();archive=folder/'old.zip'
    with archive.open('xb') as f:subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=f,check=True,timeout=120)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'OLD_ZIP_BYTES')
    with zipfile.ZipFile(archive) as z:
        need(set(z.namelist())=={'full-core-staging.json',f'full-core-{arm}.json',f'full-core-{arm}.tar.crseal'},'OLD_ZIP_MEMBERS')
        raw=z.read(f'full-core-{arm}.json');need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'OLD_RECEIPT_BYTES')
        r=json.loads(raw);s=r['encrypted_output']
        need(int(r['run_id'])==40895864995 and r['head']=='5916e314693835c8ee650407f7df4377a95b143b'
            and r['arm']==arm and r['status']=='PARTIAL_CORE_PREFIX_REVIEWED' and not r['production_contacted'],'OLD_RECEIPT_SCOPE')
        need(z.getinfo(s['name']).file_size==s['bytes'],'OLD_CIPHER_LENGTH')
        cipher=folder/'old.crseal'
        with z.open(s['name']) as src,cipher.open('xb') as out:shutil.copyfileobj(src,out)
    plain=folder/'authenticated.tar.gz';decrypt(cipher,plain,key,s['sha256'])
    dest=root/'admitted';dest.mkdir()
    with tarfile.open(plain,'r:gz') as tar:
        first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'OLD_MANIFEST')
        raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==s['manifest_sha256'],'OLD_MANIFEST_HASH')
        m=json.loads(raw);need(m['schema']=='research.full-system-output/1' and m['stage']=='multiyear-core-path'
            and m['arm']==arm and int(m['run_id'])==40895864995 and m['head']==r['head']
            and m['request_sha256']==r['request_sha256'] and m['protocol_sha256']==r['protocol_sha256'],'OLD_MANIFEST_SCOPE')
        inventory=m['members'];need(len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<1024**3,'OLD_INVENTORY_BOUND');seen=set()
        for item in tar:
            if item.name=='manifest.json':continue
            safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'OLD_MEMBER');seen.add(item.name)
            expected=inventory[item.name];need(item.size==expected['bytes'],'OLD_MEMBER_LENGTH')
            target=dest/item.name;target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(item) as src,target.open('xb') as out:shutil.copyfileobj(src,out)
            need(sha256_file(target)==expected['sha256'],'OLD_MEMBER_HASH')
        need(seen==set(inventory),'ALL_OLD_MEMBERS')
    for name,reviewer in (('economic-worker-inspect.json',False),('independent-review-stop/worker-inspect.json',True)):
        v=json.loads((dest/name).read_bytes());need(sha256_file(dest/name)==spec['inspections'][name],'OLD_INSPECTION_BYTES')
        need(v['Name']==f'/capital-full-core-{arm.lower()}-'+('review' if reviewer else 'worker')+'-40895864995-1'
            and not v['State']['Running'] and not v['State']['OOMKilled'] and v['State']['ExitCode'] in ([0] if reviewer else [1,2])
            and v['Image']=='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d','OLD_ACTUAL_STOP')
    need(sha256_file(dest/'core-review.json')==spec['review_sha256'],'OLD_REVIEW_BYTES')
    proof=json.loads((dest/'core-review.json').read_bytes());need(proof['status']=='PARTIAL_CORE_PREFIX_REVIEWED' and not proof['complete'],'OLD_PARTIAL_REVIEW')
    return dest

def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RECOVERY_RERUN')
    req=json.loads(a.request.read_bytes());need(req==request(),'EXACT_RECOVERY_REQUEST')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    stage=json.loads(a.staging.read_bytes());need(stage['status']=='STAGING_PASSED' and stage['source_files_verified']==514
        and stage['members_verified']==591 and stage['authenticated_before_parsing'] and not stage['replay_started']
        and stage['run_id']==os.environ['GITHUB_RUN_ID'] and stage['source_commit']==os.environ['GITHUB_SHA'],'CURRENT_STAGING')
    transfer=temp/('full-recovery-'+a.arm);transfer.mkdir(mode=0o700)
    spec=json.loads((HERE/'full-system-predecessors.json').read_bytes())['arms'][a.arm]
    old=predecessor(spec,transfer,key,a.arm)
    # GitHub credential is for this one authenticated transfer only, never workers.
    os.environ.pop('GH_TOKEN',None)
    source=temp/('full-recovery-source-'+a.arm);bound=build(frozen/'source-fixed',source,proposals()[ARMS[a.arm]]['parameters'])
    need(bound==json.loads((old/'private-source-bindings.json').read_bytes()),'ALL_515_FINANCIAL_SOURCES_UNCHANGED')
    root=temp/('full-recovery-output-'+a.arm);shutil.copytree(old,root)
    (root/'recovery-spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    (root/'recovery-request.json').write_bytes(a.request.read_bytes())
    # Keep the authenticated old reviewer diagnostics separately; new outputs are distinct.
    (root/'core-review.json').rename(root/'prior-core-review.json')
    (root/'independent-review-stop').rename(root/'prior-independent-review-stop')
    for p in source.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(source,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'RECOVERY_RESOURCES')
    receipt={'schema':'research.full-system-recovery-receipt/1','arm':a.arm,'run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':req['protocol_sha256'],
        'predecessor_run_id':40895864995,'production_contacted':False,'status':'NOT_STARTED','performance_admitted':False}
    known=False
    def cmd(name,mode):
        result=command(name,source,frozen,root,mode);result[result.index('/driver/full_system_core.py')]='/driver/full_system_recovery.py';return result
    try:
        seconds=(datetime(2026,10,29,17,57,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds()
        need(seconds>1200,'REMAINING_BUDGET')
        name='capital-full-core-'+a.arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        worker=stopped_run(cmd(name,'economic'),name,root,deadline=int(seconds)-900,inspector=inspect)
        known=True;receipt['worker']=worker;receipt['status']='STOPPED_SUFFIX_PRESERVED'
        shutil.copyfile(root/'worker-inspect.json',root/'economic-worker-inspect.json');shutil.copyfile(root/'worker.log',root/'economic-worker.log')
        if not worker['oom_killed']:
            diagnostics=temp/('full-recovery-review-'+a.arm);diagnostics.mkdir()
            name='capital-full-core-'+a.arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            reviewed=stopped_run(cmd(name,'review'),name,diagnostics,deadline=600,inspector=inspect)
            receipt['reviewer']=reviewed;shutil.copytree(diagnostics,root/'independent-review-stop')
            if reviewed['exit_code']==0 and not reviewed['oom_killed']:
                v=json.loads((root/'core-review.json').read_bytes());receipt['status']='COMPLETE_CORE_INDEPENDENTLY_REVIEWED' if v['complete'] and worker['exit_code']==0 else 'PARTIAL_CORE_PREFIX_REVIEWED'
    except StopUnknown:receipt['status']='REVIEW_STOP_UNKNOWN_CORE_PRESERVED' if known else 'CORE_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='RECOVERY_REFUSED'
        if known:(root/'recovery-failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(root,a.output.parent/('full-recovery-'+a.arm+'.tar.crseal'),key,a.request,a.arm)
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='COMPLETE_CORE_INDEPENDENTLY_REVIEWED' else 2)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--arm',choices=ARMS,required=True);main(p.parse_args())
