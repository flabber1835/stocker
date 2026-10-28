"""Only the committed two selections: authenticate, exact suffix, compact export."""
import argparse,base64,hashlib,json,os,re,shutil,subprocess,tarfile
from pathlib import Path
from baseline_prefix import run_worker
from weighted_job import inspect_weighted
from screen_job import encrypt
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,IMAGE,SECRET
from runtime_identity import EXECUTION_IMAGE
from probe import check_context,admitted_output,memory_bytes
from selective_job import admit_prior,need
from risk_search_job import command
from risk_profiles import profiles,selected
from risk_capsule import pack_book,encode

HERE=Path(__file__).resolve().parent
VALIDATION_SOURCES=('risk_validation_job.py','risk_validation_worker.py','risk_capsule.py')

def expected_request(selection,selection_commit):
    return dict(schema='research.bounded-risk-validation-request/1',id='bounded-risk-selected-validation-001',
        selection_sha256=sha256_file(HERE/'risk-search-selection.json'),selection=selection,selection_commit=selection_commit,
        protocol_sha256=sha256_file(HERE/'risk-search-protocol.json'),
        requirements_sha256=sha256_file(HERE/'risk-search-requirements.lock'),
        sources={n:sha256_file(HERE/n) for n in VALIDATION_SOURCES},
        main_path_replayed=False,worker_seconds=900,production_contacted=False)

def validate_request(request):
    selection=json.loads((HERE/'risk-search-selection.json').read_bytes())
    need(re.fullmatch('[0-9a-f]{40}',request['selection_commit']) is not None,'REFUSED_SELECTION_COMMIT')
    need(request==expected_request(selection,request['selection_commit']),'REFUSED_SELECTED_VALIDATION_REQUEST')
    locked=subprocess.run(['git','show',request['selection_commit']+':research/capital_risk/risk-search-selection.json'],capture_output=True,check=True).stdout
    need(hashlib.sha256(locked).hexdigest()==request['selection_sha256'],'REFUSED_COMMITTED_SELECTION_BYTES')
    identifiers={p.id for p in profiles()}
    need(selection['schema']=='research.bounded-risk-locked-selection/1' and len(selection['selected'])==2
        and len(set(selection['selected']))==2 and set(selection['ranking'])==identifiers
        and len(selection['ranking'])==12 and selection['ranking'][:2]==selection['selected']
        and not selection['validation_decrypted_before_selection'],'REFUSED_LOCKED_SELECTION')
    need(set(selection['profiles'])==set(selection['selected']),'REFUSED_SELECTED_ARTIFACT_SCOPE')
    return selection

def admit_selected(download,destination,key,profile,spec,search_run,search_head):
    raw=(download/(profile.id+'.json')).read_bytes();receipt=json.loads(raw)
    need(receipt==spec['receipt'] and receipt['profile_id']==profile.id and receipt['run_id']==str(search_run)
        and receipt['source_commit']==search_head and receipt['status']=='PROFILE_REVIEWED'
        and receipt['known_financial_stopped'] and not receipt['production_contacted'],'REFUSED_SELECTED_RECEIPT')
    cipher=receipt['encrypted_output'];asset=download/cipher['name'];need(asset.stat().st_size==cipher['bytes'],'REFUSED_SELECTED_CIPHER_LENGTH')
    plain=destination.parent/(profile.id+'-authenticated.tar');decrypt(asset,plain,key,cipher['sha256'])
    with tarfile.open(plain,'r|') as t:
        first=t.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'REFUSED_SELECTED_MANIFEST_FIRST');raw_manifest=t.extractfile(first).read()
    manifest=json.loads(raw_manifest);mh=hashlib.sha256(raw_manifest).hexdigest()
    need(manifest['arm']=='H0P2' and manifest['stage']=='holding-comparison' and manifest['protocol_sha256']==PROTOCOL
        and manifest['screen_protocol_sha256']==receipt['request_sha256'],'REFUSED_SELECTED_MANIFEST_SCOPE')
    extract_verified(plain,destination,mh,expected_schema='research.capital-risk-output/1')
    ordinal=3+[p.id for p in profiles()].index(profile.id)
    writer='capital-risk-h0p2-'+str(search_run)+'-'+str(ordinal);reviewer='capital-risk-h0p2-'+str(search_run)+'-'+str(100+ordinal)
    stops={name:inspect_weighted(destination/(name+'-inspect.json'),name) for name in (writer,reviewer)}
    need(all(s['exit_code']==0 and not s['oom'] for s in stops.values()),'REFUSED_SELECTED_NATIVE_STOPS')
    review_path=destination/'review/review.json';need(sha256_file(review_path)==spec['full_review_sha256'],'REFUSED_SELECTED_EXACT_REVIEW')
    review=json.loads(review_path.read_bytes());need(review['status']=='INDEPENDENT_FULL_PROFILE_REVIEW_PASSED'
        and review['profile']==profile.model_dump(mode='json'),'REFUSED_SELECTED_REVIEW_SCOPE')
    binding=json.loads((destination/'result/source-bindings.json').read_bytes());b=binding['binding']
    need(binding['source_sha256']==hashlib.sha256(encode(b)).hexdigest() and b['profile']==profile.model_dump(mode='json'),'REFUSED_SELECTED_SOURCE_BINDING')
    for name,h in {**b['original_sources'],**b['research_sources']}.items():need(sha256_file(HERE/name)==h,'REFUSED_CHANGED_SELECTED_FINANCIAL_SOURCE_'+name)
    retained=json.loads((destination/'result/book/retained-checkpoint-review.json').read_bytes())
    need(retained['checkpoints']==len(retained['files']) and retained['all_tails_zero'],'REFUSED_SELECTED_RESTORE_SCOPE')
    for name,h in retained['files'].items():need(sha256_file(destination/'result/book'/name)==h,'REFUSED_SELECTED_TYPED_FILE')
    return dict(receipt=receipt,manifest_sha256=mh,manifest=manifest,actual_stops=stops,original_review_sha256=sha256_file(review_path),
        financial_source_sha256=binding['source_sha256'])

def make_capsule(case,validation,destination,admission):
    destination.mkdir();(destination/'admission.json').write_bytes(encode(admission)+b'\n')
    shutil.copytree(case/'review',destination/'original-independent-review')
    for name in ('source-bindings.json','summary.json'):
        shutil.copyfile(case/'result'/name,destination/name)
    shutil.copytree(case/'result/identity',destination/'identity')
    main=pack_book(case/'result/book',destination/'book')
    for path in case.glob('*-inspect.json'):shutil.copyfile(path,destination/path.name)
    for path in validation.glob('*-inspect.json'):shutil.copyfile(path,destination/path.name)
    for path in validation.glob('*.log'):shutil.copyfile(path,destination/path.name)
    proof=json.loads((validation/'result/proof.json').read_bytes());shutil.copytree(validation/'result/lineage',destination/'lineage')
    from selective_journal import load
    boundary=load(case/'result/book/restart-boundary.json.gz')
    suffix=pack_book(validation/'result/suffix',destination/'suffix',history_base=boundary['runtime']['account']['state']['applied_events'])
    (destination/'suffix-proof.json').write_bytes(encode(proof)+b'\n')
    return dict(profile_id=proof['profile_id'],status='SELECTED_CAPSULE_EXPORTED',main_checkpoints=len(main['checkpoint_files']),
        suffix_checkpoints=len(suffix['checkpoint_files']),complete_final_runtime_equal=proof['complete_final_runtime_equal'])

def main():
    parser=argparse.ArgumentParser()
    for n in ('request','staging-receipt','price-download','selected-download','output'):parser.add_argument('--'+n,type=Path,required=True)
    a=parser.parse_args();check_context(os.environ);need(os.environ['GITHUB_RUN_ATTEMPT']=='1','REFUSED_VALIDATION_RERUN')
    request=json.loads(a.request.read_bytes());selection=validate_request(request);stage=json.loads(a.staging_receipt.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['protocol_sha256']==PROTOCOL and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
        and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['source_files_verified']==514 and stage['members_verified']==591 and not stage['replay_started']
        and all(stage[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified')),'REFUSED_VALIDATION_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_VALIDATION_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';qualified=temp/'risk-selected-qualified';qualified.mkdir(mode=0o700)
    need(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=16*1024**3,'REFUSED_VALIDATION_CAPACITY')
    price=admit_prior(a.price_download,qualified/'price',key);cases=qualified/'cases';cases.mkdir()
    admissions={}
    for identifier in selection['selected']:
        admissions[identifier]=admit_selected(a.selected_download/identifier,cases/identifier,key,selected(identifier),selection['profiles'][identifier],selection['search_run_id'],selection['search_head'])
    for root in (frozen,qualified):
        for path in root.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
        os.chmod(root,0o555)
    private=temp/'risk-selected-validation';private.mkdir(mode=0o700);capsules=private/'capsules';capsules.mkdir()
    (private/'request.json').write_bytes(a.request.read_bytes());(private/'selection.json').write_bytes((HERE/'risk-search-selection.json').read_bytes())
    (private/'price-admission.json').write_bytes(encode(price)+b'\n');(private/'driver-identities.json').write_bytes(encode({p.name:sha256_file(p) for p in HERE.glob('*.py')})+b'\n')
    outcomes=[];all_passed=True
    for index,identifier in enumerate(selection['selected'],1):
        name='capital-risk-h0p2-'+os.environ['GITHUB_RUN_ID']+'-'+str(index);out=temp/('risk-selected-'+identifier);out.mkdir(mode=0o700)
        known=False;error=None
        try:
            args=['--profile',identifier,'--actual','/qualified/cases/'+identifier+'/result','--root','/frozen/baseline-comparison','--bundle','/frozen/bundle','--qualified','/qualified/price','--output','/out/result']
            run_worker(command(name,frozen,qualified,out,'risk_validation_worker.py',args),name,out,deadline=900)
            stopped=inspect_weighted(out/(name+'-inspect.json'),name);known=True;need(stopped['exit_code']==0 and not stopped['oom'],'REFUSED_SELECTED_SUFFIX_STOP')
            result=make_capsule(cases/identifier,out,capsules/identifier,admissions[identifier]);outcomes.append(result)
        except Exception as exc:
            error=dict(type=type(exc).__name__,message=str(exc));all_passed=False
            try:inspect_weighted(out/(name+'-inspect.json'),name);known=True
            except Exception:pass
            if known:shutil.copytree(out,private/('stopped-failure-'+identifier))
            outcomes.append(dict(profile_id=identifier,status='SELECTED_VALIDATION_REFUSED' if known else 'WRITER_STOP_UNKNOWN',error=error))
        print(json.dumps(dict(profile_id=identifier,status=outcomes[-1]['status'])))
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True);cipher=output.parent/'risk-selected-validation.tar.crseal';contract=sha256_file(a.request)
    encrypt(private,cipher,key,contract,arm='H0P2',stage='holding-comparison');key=None
    receipt=dict(schema='research.bounded-risk-selected-validation-receipt/1',status='SELECTED_VALIDATION_COMPLETE' if all_passed else 'SELECTED_VALIDATION_REFUSED',
        run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],request_sha256=contract,selection_sha256=request['selection_sha256'],
        original_protocol_sha256=PROTOCOL,outcomes=outcomes,production_contacted=False,main_paths_replayed=False,
        encrypted_output=dict(name=cipher.name,bytes=cipher.stat().st_size,sha256=sha256_file(cipher)))
    output.write_bytes(encode(receipt)+b'\n');print(json.dumps(receipt));raise SystemExit(0 if all_passed else 2)

if __name__=='__main__':main()
