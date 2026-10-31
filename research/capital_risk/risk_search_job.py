"""Bounded hosted optimization, separate sealed development and full evidence."""
import argparse,base64,hashlib,json,os,shutil
from pathlib import Path
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from weighted_job import inspect_weighted
from screen_job import encrypt
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,IMAGE,SECRET
from runtime_identity import EXECUTION_IMAGE
from probe import check_context,admitted_output,memory_bytes
from selective_job import admit_prior,need
from selective_completion_job import admit_controls
from risk_profiles import profiles,oracle

HERE=Path(__file__).resolve().parent
NEW_SOURCES=('risk_profiles.py','risk_policy.py','risk_adapter.py','risk_worker.py','risk_gate.py','risk_metrics.py','risk_review_math.py','risk_review.py','risk_search_job.py')
P2_RECEIPT='00d1c4e856652106f8457b546e6a3f979c73503443fb1e9c58a54ab6efc31668'
P2_CIPHER=dict(name='selective-completion.tar.crseal',bytes=705761316,sha256='a448ac0a037f9bb90a1e01fd447629c4f20b36a1eb95c4e10fc18edadf66259e')
P2_MANIFEST='9bcd5eebcdf42147eec6e8212db41924313e0de61b83cacc3a5175f502d9cb9f'

def expected_request():
    return dict(schema='research.bounded-risk-search-request/1',id='bounded-risk-search-001',original_protocol_sha256=PROTOCOL,
        financial_protocol_sha256=sha256_file(HERE/'selective-protocol.json'),original_basis_sha256=sha256_file(HERE/'selective-completion-basis.json'),
        protocol_sha256=sha256_file(HERE/'risk-search-protocol.json'),profiles=[p.model_dump(mode='json') for p in profiles()],
        requirements_sha256=sha256_file(HERE/'risk-search-requirements.lock'),
        recovered_oracles=json.loads((HERE/'risk-search-recovery.json').read_bytes()) if (HERE/'risk-search-recovery.json').exists() else None,
        sources={n:sha256_file(HERE/n) for n in NEW_SOURCES},worker_seconds=900,review_seconds=900,
        owner_scope='BOUNDED12_ARCHITECTURE_PARAMETER_SEARCH_LOCKED_CHRONOLOGICAL_VALIDATION_NO_ROUTINE_APPROVAL_STOPS')

def validate_request(r):
    need(r==expected_request(),'REFUSED_BOUNDED_SEARCH_REQUEST');basis=json.loads((HERE/'selective-completion-basis.json').read_bytes())
    for name,h in basis['original_drivers'].items():need(sha256_file(HERE/name)==h,'REFUSED_CHANGED_ORIGINAL_SEARCH_FINANCIAL_BASIS_'+name)
    need(len(r['profiles'])==12 and len({p['id'] for p in r['profiles']})==12,'REFUSED_SEARCH_BUDGET')
    p=json.loads((HERE/'risk-search-protocol.json').read_bytes())
    need(p['budget']==12 and p['shortlist']==2 and p['development_end']=='2017-12-31' and p['validation_used_for_selection'] is False
        and p['objective']==dict(growth_scale='.01',drawdown_scale='.05',strict_joint_tolerance='1e-10') and not p['production_contacted'],'REFUSED_SEARCH_SELECTION_PROTOCOL')
    recovery=r.get('recovered_oracles')
    if recovery:need(recovery['run_id']==40735253211 and recovery['head']=='a96b667fa27e62181ec0df3abf84a2eb7a4e2388' and set(recovery['profiles'])=={'ORACLE_H0','ORACLE_P2'},'REFUSED_RECOVERY_SCOPE')
    return basis

def admit_p2(download,destination,key):
    rp=download/'selective-completion.json';need(sha256_file(rp)==P2_RECEIPT,'REFUSED_OLD_P2_RECEIPT');r=json.loads(rp.read_bytes())
    need(r['status']=='H0_P2_COMPARISON_COMPLETE' and r['run_id']=='40724796359' and r['source_commit']=='32b6be13b88d8a521323bcd10fbbc1d51558fdb0'
        and r['known_stopped'] and not r['production_contacted'] and r['encrypted_output']==P2_CIPHER,'REFUSED_OLD_P2_SCOPE')
    asset=download/P2_CIPHER['name'];need(asset.stat().st_size==P2_CIPHER['bytes'],'REFUSED_OLD_P2_LENGTH')
    plain=destination.parent/'old-p2.tar';decrypt(asset,plain,key,P2_CIPHER['sha256']);m=extract_verified(plain,destination,P2_MANIFEST,expected_schema='research.capital-risk-output/1')
    need(m['arm']=='H0P2' and m['stage']=='holding-comparison' and m['protocol_sha256']==PROTOCOL and m['screen_protocol_sha256']==r['request_sha256'] and len(m['members'])==1873,'REFUSED_OLD_P2_MANIFEST')
    name='capital-risk-h0p2-40724796359-1';stop=inspect_weighted(destination/(name+'-inspect.json'),name);need(stop['exit_code']==0 and not stop['oom'],'REFUSED_OLD_P2_STOP')
    old=json.loads((destination/'driver-identities.json').read_bytes())
    for name,h in old.items():need(sha256_file(HERE/name)==h,'REFUSED_OLD_P2_SOURCE_'+name)
    return dict(run_id=40724796359,receipt_sha256=P2_RECEIPT,ciphertext=P2_CIPHER,manifest_sha256=P2_MANIFEST,actual_stop=stop,driver_count=len(old))

def command(name,frozen,qualified,out,script,arguments):
    args=launch_arguments(name,frozen,out,HERE);cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['--mount',f'type=bind,source={qualified},target=/qualified,readonly','-e','HOLDING_QUAL_HOSTED=1']+args[cut:cut+1]+['-B','-u','/driver/'+script]+arguments

def admit_recovered_oracle(download,destination,key,spec,profile):
    r=json.loads((download/(profile.id+'.json')).read_bytes());need(r==spec['receipt'],'REFUSED_ORACLE_RECOVERY_RECEIPT')
    asset=download/r['encrypted_output']['name'];need(asset.stat().st_size==r['encrypted_output']['bytes'],'REFUSED_ORACLE_RECOVERY_CIPHER_LENGTH')
    plain=destination.parent/(profile.id+'-preserved.tar');decrypt(asset,plain,key,r['encrypted_output']['sha256'])
    import tarfile
    with tarfile.open(plain,'r|') as tar:first=tar.next();raw=tar.extractfile(first).read()
    m=json.loads(raw);mh=hashlib.sha256(raw).hexdigest()
    need(m['arm']=='H0P2' and m['stage']=='holding-comparison' and m['protocol_sha256']==PROTOCOL and m['screen_protocol_sha256']==r['request_sha256'],'REFUSED_ORACLE_RECOVERY_MANIFEST')
    extract_verified(plain,destination,mh,expected_schema='research.capital-risk-output/1')
    writer=spec['actual_stop']['name'];stop=inspect_weighted(destination/(writer+'-inspect.json'),writer)
    need(stop==spec['actual_stop'] and stop['exit_code']==0 and not stop['oom'],'REFUSED_ORACLE_RECOVERY_STOP')
    bindings=json.loads((destination/'result/source-bindings.json').read_bytes())['binding'];need(bindings['profile']==profile.model_dump(mode='json'),'REFUSED_RECOVERED_PROFILE_IDENTITY')
    for name,h in {**bindings['original_sources'],**bindings['research_sources']}.items():need(sha256_file(HERE/name)==h,'REFUSED_CHANGED_RECOVERED_FINANCIAL_SOURCE_'+name)
    (destination/'review-recovery-lineage.json').write_text(json.dumps(dict(original_receipt=r,manifest_sha256=mh,original_financial_stop=stop,financial_account_replayed=False),indent=2)+'\n')
    return writer

def main():
    parser=argparse.ArgumentParser()
    for n in ('request','staging-receipt','price-download','control-download','p2-download','output'):parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--oracle-recovery-download',type=Path)
    a=parser.parse_args();check_context(os.environ);need(os.environ['GITHUB_RUN_ATTEMPT']=='1','REFUSED_SEARCH_FRESH_RERUN')
    request=json.loads(a.request.read_bytes());basis=validate_request(request);stage=json.loads(a.staging_receipt.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['protocol_sha256']==PROTOCOL and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
        and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['source_files_verified']==514 and stage['members_verified']==591 and stage['authenticated_before_parsing']
        and stage['runtime_index_config_layer_chain_verified'] and stage['offline_image_source_verified'] and not stage['replay_started'],'REFUSED_SEARCH_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_SEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';qualified=temp/'bounded-risk-qualified';qualified.mkdir(mode=0o700)
    need(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=28*1024**3,'REFUSED_SEARCH_INITIAL_CAPACITY')
    admissions=dict(price=admit_prior(a.price_download,qualified/'price',key),controls=admit_controls(a.control_download,qualified/'controls',key,basis),old_p2=admit_p2(a.p2_download,qualified/'oldp2',key))
    for root in (frozen,qualified/'price',qualified/'controls',qualified/'oldp2'):
        for path in root.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
        os.chmod(root,0o555)
    cases=qualified/'cases';cases.mkdir();reviews=qualified/'reviews';reviews.mkdir()
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    assets=output.parent/'profiles';assets.mkdir();devroot=temp/'risk-development';devroot.mkdir(mode=0o700)
    drivers={p.name:sha256_file(p) for p in HERE.glob('*.py')};contract=sha256_file(a.request)
    (devroot/'driver-identities.json').write_text(json.dumps(drivers,indent=2)+'\n');(devroot/'admissions.json').write_text(json.dumps(admissions,indent=2)+'\n');(devroot/'request.json').write_bytes(a.request.read_bytes())
    results=[];qualification=True
    recovered=(request.get('recovered_oracles') or {}).get('profiles',{})
    need(not recovered or a.oracle_recovery_download is not None,'REFUSED_MISSING_ORACLE_RECOVERY_INPUTS')
    def publish_progress():
        sealed=output.parent/('risk-development-progress-'+str(len(results)).zfill(2)+'.tar.crseal')
        encrypt(devroot,sealed,key,contract,arm='H0P2',stage='holding-comparison')
        complete=qualification and len(results)==14 and all(r['status']=='PROFILE_REVIEWED' for r in results)
        receipt=dict(schema='research.bounded-risk-development-receipt/1',status='SEARCH_DEVELOPMENT_COMPLETE' if complete else 'SEARCH_PARTIAL_PRESERVED',run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],
            request_sha256=contract,original_protocol_sha256=PROTOCOL,qualification_passed=qualification,profiles=list(results),validation_metrics_disclosed=False,production_contacted=False,
            encrypted_output=dict(name=sealed.name,bytes=sealed.stat().st_size,sha256=sha256_file(sealed)))
        output.write_text(json.dumps(receipt,indent=2)+'\n');return complete
    for index,profile in enumerate((oracle('ORACLE_H0'),oracle('ORACLE_P2'),*profiles()),1):
        if index>2 and not qualification:break
        name='capital-risk-h0p2-'+os.environ['GITHUB_RUN_ID']+'-'+str(index);case=cases/profile.id
        if profile.id in recovered:
            name=admit_recovered_oracle(a.oracle_recovery_download/profile.id,case,key,recovered[profile.id],profile)
            (case/'current-review-request.json').write_bytes(a.request.read_bytes());(case/'current-review-driver-identities.json').write_text(json.dumps(drivers,indent=2)+'\n')
        else:
            case.mkdir(mode=0o700);(case/'driver-identities.json').write_text(json.dumps(drivers,indent=2)+'\n');(case/'request.json').write_bytes(a.request.read_bytes())
        known=False;status='PROFILE_REFUSED';error=None;record=dict(profile_id=profile.id,family=profile.family,review_passed=False)
        try:
            need(memory_bytes()['MemAvailable']>=3*1024**3 and shutil.disk_usage(temp).free>=4*1024**3,'REFUSED_NEXT_PROFILE_CAPACITY')
            args=['--profile',profile.id,'--root','/frozen/baseline-comparison','--bundle','/frozen/bundle','--qualified','/qualified/price','--output','/out/result']
            if profile.id not in recovered:run_worker(command(name,frozen,qualified,case,'risk_worker.py',args),name,case,deadline=900)
            stopped=inspect_weighted(case/(name+'-inspect.json'),name);known=True;need(stopped['exit_code']==0 and not stopped['oom'],'REFUSED_PROFILE_FINANCIAL_OUTCOME')
            rname='capital-risk-h0p2-'+os.environ['GITHUB_RUN_ID']+'-'+str(100+index);reviewroot=reviews/profile.id;reviewroot.mkdir(mode=0o700)
            args=['--profile',profile.id,'--writer-name',name,'--actual','/qualified/cases/'+profile.id+'/result','--source','/frozen/baseline-comparison','--bundle','/frozen/bundle','--qualified','/qualified','--output','/out/review']
            run_worker(command(rname,frozen,qualified,reviewroot,'risk_review.py',args),rname,reviewroot,deadline=900)
            rstopped=inspect_weighted(reviewroot/(rname+'-inspect.json'),rname);need(rstopped['exit_code']==0 and not rstopped['oom'],'REFUSED_PROFILE_REVIEW_OUTCOME')
            full=json.loads((reviewroot/'review/review.json').read_bytes());need(full['status']=='INDEPENDENT_FULL_PROFILE_REVIEW_PASSED','REFUSED_PROFILE_REVIEW_STATUS')
            if index<=2:need(full['compatibility']['status']=='EVERY_ECONOMIC_FIELD_EXACT','REFUSED_COMPATIBILITY_GATE')
            shutil.copytree(reviewroot/'review',case/'review');(case/(rname+'-inspect.json')).write_bytes((reviewroot/(rname+'-inspect.json')).read_bytes())
            (case/(rname+'.log')).write_bytes((reviewroot/(rname+'.log')).read_bytes())
            record=json.loads((case/'review/development.json').read_bytes());record.update(writer_stop=stopped,reviewer_stop=rstopped,
                full_review_sha256=sha256_file(case/'review/review.json'),validation_results_included=False)
            status='PROFILE_REVIEWED';record['status']=status
        except Exception as exc:
            error=dict(type=type(exc).__name__,message=str(exc))
            try:stopped=inspect_weighted(case/(name+'-inspect.json'),name);known=True
            except Exception:status='WRITER_STOP_UNKNOWN'
            record.update(status=status,error=error,known_financial_stopped=known)
            if index<=2:qualification=False
        if known:(devroot/(profile.id+'-writer-inspect.json')).write_bytes((case/(name+'-inspect.json')).read_bytes())
        rname='capital-risk-h0p2-'+os.environ['GITHUB_RUN_ID']+'-'+str(100+index);rp=reviews/profile.id/(rname+'-inspect.json')
        if rp.exists():
            try:
                inspect_weighted(rp,rname);(devroot/(profile.id+'-reviewer-inspect.json')).write_bytes(rp.read_bytes())
                (case/(rname+'-inspect.json')).write_bytes(rp.read_bytes())
                logfile=reviews/profile.id/(rname+'.log')
                if logfile.exists():(case/(rname+'.log')).write_bytes(logfile.read_bytes())
                if logfile.exists() and profile.id.startswith('ORACLE_'):(devroot/(profile.id+'-reviewer.log')).write_bytes(logfile.read_bytes())
                partial=reviews/profile.id/'review'
                if partial.exists() and not (case/'review').exists():shutil.copytree(partial,case/'review')
            except Exception:pass  # Unknown reviewer output is deliberately not archived.
        diagnostic=temp/('risk-diagnostic-'+profile.id);diagnostic.mkdir();(diagnostic/'outcome.json').write_text(json.dumps(dict(status=status,error=error,known_financial_stopped=known),indent=2)+'\n')
        outcome_name='review-recovery-outcome.json' if profile.id in recovered else 'outcome.json'
        (case/outcome_name).write_bytes((diagnostic/'outcome.json').read_bytes()) if known else None
        asset=assets/(profile.id+'.tar.crseal');encrypt(case if known else diagnostic,asset,key,contract,arm='H0P2',stage='holding-comparison')
        receipt=dict(schema='research.bounded-risk-profile-receipt/1',profile_id=profile.id,status=status,run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],request_sha256=contract,
            known_financial_stopped=known,production_contacted=False,encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
        receipt['financial_origin']=dict(run_id=40735253211 if profile.id in recovered else int(os.environ['GITHUB_RUN_ID']),reused_complete_oracle=profile.id in recovered)
        (assets/(profile.id+'.json')).write_text(json.dumps(receipt,indent=2)+'\n');record['receipt']=receipt
        (devroot/(profile.id+'.json')).write_text(json.dumps(record,indent=2)+'\n');results.append(dict(profile_id=profile.id,status=status))
        publish_progress()
        print(json.dumps(dict(profile_id=profile.id,status=status)))
    complete=qualification and len(results)==14 and all(r['status']=='PROFILE_REVIEWED' for r in results)
    key=None;print(output.read_text());raise SystemExit(0 if complete else 2)

if __name__=='__main__':main()
