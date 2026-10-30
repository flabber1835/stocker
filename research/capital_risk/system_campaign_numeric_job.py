"""Isolated joint calculations on one authenticated complete canonical Core path."""
import argparse,base64,json,os,re,shutil
from pathlib import Path
from full_system_benchmark import need
from full_system_trials_job import command as core_command,seal
from system_campaign_factual_admit import admit
from system_campaign_variants import build as candidate_source
from system_campaign_source import build as baseline_source
from system_campaign_factual_job import SOURCES as CORE_SOURCES
from system_campaign_equivalence_job import SOURCES as EQUIVALENCE_SOURCES
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from alpaca_fit_job import stopped_run,StopUnknown

HERE=Path(__file__).resolve().parent
SOURCES=tuple(dict.fromkeys((*CORE_SOURCES,*EQUIVALENCE_SOURCES,'system_campaign_basis_admit.py','system_campaign_numeric_job.py','system_campaign_numeric.py',
    'system_campaign_numeric_review.py','system_campaign_basis.py','system_campaign_joint_space.py',
    'system_campaign_correlation.py','system_campaign_terminal_facts.py','full_system_controller_policy.py',
    'full_system_controller_vector.py','full_system_controller_worker.py','full_system_controller_review.py',
    'owned_grid.py','owned_value.py','selective_journal.py','system_campaign_march_facts.py',
    'system_campaign_confirm.py','system_campaign_selection.py','alpaca_fit_collect.py','alpaca_fit_compare.py',
    'alpaca_fit_identity_repair.py','alpaca_fit_inputs.py','alpaca_fit_merger_roles.py','alpaca_fit_prior.py',
    'alpaca_fit_relay.py','alpaca_fit_resume.py','core_lineage_review.py','forecast_collect.py','local_stage.py',
    'owned_grid_worker.py','policy.py','trace_screen.py','system_campaign_winter_facts.py','system_campaign_spring_facts.py',
    'system_campaign_followup_facts.py','system_campaign_tgi_facts.py','system_campaign_late_facts.py','system_campaign_yearend_facts.py')))


def expected_request(specifications,equivalence_proofs=None):
    from system_campaign_joint_space import joint_profiles
    from system_campaign_facts import digest
    return {'schema':'research.system-campaign-joint-numerical-request/1','campaign':'system-optimization-002',
        'protocol_sha256':sha256_file(HERE/'system-campaign-search-protocol.json'),
        'core_artifacts':specifications,'semantic_equivalence_proofs':equivalence_proofs or {},
        'joint_registry_sha256':digest(joint_profiles()),
        'catalog_sha256':sha256_file(HERE/'system-campaign-factual-catalog.json'),
        'additional_catalog_sha256':sha256_file(HERE/'system-campaign-additional-terminal-facts.json'),
        'winter_catalog_sha256':sha256_file(HERE/'system-campaign-corrected-winter-facts.json'),
        'spring_catalog_sha256':sha256_file(HERE/'system-campaign-spring-terminal-facts.json'),
        'followup_catalog_sha256':sha256_file(HERE/'system-campaign-followup-terminal-facts.json'),
        'tgi_catalog_sha256':sha256_file(HERE/'system-campaign-tgi-cash-facts.json'),
        'midyear_catalog_sha256':sha256_file(HERE/'system-campaign-midyear-terminal-facts.json'),
        'late_catalog_sha256':sha256_file(HERE/'system-campaign-late-terminal-facts.json'),
        'yearend_catalog_sha256':sha256_file(HERE/'system-campaign-yearend-terminal-facts.json'),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'worker_wait_seconds':7200,
        'review_wait_seconds':3600,'artifact_retention_days':7,'new_core_financial_sessions':0,
        'source_archive_limit_bytes':1024**3,
        'global_selection_performed':False,'production_contacted':False}


def inspect(name,identity=None):
    need(re.fullmatch(r'capital-system-joint-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1',name) is not None,'JOINT_WORKER_NAME')
    import subprocess
    v=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c=v['HostConfig'],v['Config'];mounts={m['Destination']:m for m in v['Mounts'] if m['Type']=='bind'}
    need(v['Name']=='/'+name and v['Image']==EXECUTION_IMAGE and (identity is None or v['Id']==identity),
         'JOINT_ACTUAL_WORKER_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
         and h['ReadonlyRootfs'] and h['PidsLimit']==64 and h['CapDrop']==['ALL']
         and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),'JOINT_ACTUAL_WORKER_FENCES')
    review='-review-' in name
    has_basis='--equivalence-proof' in c['Cmd']
    if has_basis:need(c['Cmd'][c['Cmd'].index('--equivalence-proof')+1]=='/basis','JOINT_DECLARED_SEPARATE_BASIS')
    expected=({'/variant','/frozen','/driver','/out','/core','/evidence'} if review else
              {'/variant','/frozen','/driver','/out','/core'})|({'/basis'} if has_basis else set())
    need(set(mounts)==expected and mounts['/out']['RW']
         and all(not m['RW'] for k,m in mounts.items() if k!='/out') and c['WorkingDir']=='/variant'
         and c['User']==f'{os.getuid()}:{os.getgid()}' and c['Labels']['research.study']=='full-system-search-20261029'
         and c['Labels']['research.role']==('review' if review else 'worker'),'JOINT_READ_ONLY_EVIDENCE_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'}
    need(not any(k in forbidden and value for k,_,value in (item.partition('=') for item in c['Env'])),
         'JOINT_NO_WORKER_CREDENTIALS')
    return v


def command(name,source,frozen,out,core,evidence=None,equivalence_proof=None):
    base=core_command(name,source,frozen,out,'review' if evidence else 'economic')
    start=base.index('--entrypoint')
    extra=['--mount',f'type=bind,source={core},target=/core,readonly']
    if evidence:extra+=['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    if equivalence_proof:extra+=['--mount',f'type=bind,source={equivalence_proof},target=/basis,readonly']
    tail=['--entrypoint','python',EXECUTION_IMAGE,'-B','-u',
        '/driver/system_campaign_numeric_review.py' if evidence else '/driver/system_campaign_numeric.py']
    if evidence:tail+=['--core','/core','--evidence','/evidence/book','--output','/out/review']
    else:tail+=['--evidence','/core','--output','/out/book']
    if equivalence_proof:tail+=['--equivalence-proof','/basis']
    return base[:start]+extra+tail


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','JOINT_NO_FRESH_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(request['core_artifacts'],request.get('semantic_equivalence_proofs'))
        and args.arm in request['core_artifacts'] and re.fullmatch(r'P[0-9]{2}',args.arm) is not None,
        'JOINT_EXACT_PARAMETERIZED_CORE_REQUEST')
    spec=request['core_artifacts'][args.arm]
    proofs=request['semantic_equivalence_proofs']
    need(set(proofs)<={'P00'} and set(proofs)<=set(request['core_artifacts']),
         'JOINT_ONLY_DEFAULT_HAS_SEPARATE_EQUIVALENCE')
    need(spec['selected_checkpoint']=='book/checkpoint.json.gz' and spec['selected_session']=='2026-07-31'
         and not spec.get('review_refusal') and not spec.get('unadvanced_qualification_failure')
         and spec['inspections']['economic-worker-inspect.json']['exit_code']==0
         and spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==0,
         'JOINT_COMPLETE_STOPPED_ARTIFACT_ONLY')
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'JOINT_EXACT_FROZEN_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    core=admit(spec,temp/('campaign-factual-transfer-joint-'+args.arm),key,max_zip_bytes=request['source_archive_limit_bytes'])
    equivalence=None
    if args.arm in proofs:
        proof_spec=proofs[args.arm]
        need(proof_spec['receipt_schema']=='research.system-campaign-basis-equivalence-receipt/1'
             and proof_spec['arm']==args.arm
             and proof_spec['selected_checkpoint']=='book/checkpoint.json.gz'
             and proof_spec['selected_session']=='2019-04-30'
             and proof_spec['inspections']['economic-worker-inspect.json']['exit_code']==0
             and proof_spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==0
             and not proof_spec.get('review_refusal') and not proof_spec.get('unadvanced_qualification_failure'),
             'JOINT_AUTHENTICATED_REVIEWED_BASIS_SPEC')
        equivalence=admit(proof_spec,temp/('campaign-factual-transfer-basis-'+args.arm),key,max_zip_bytes=request['source_archive_limit_bytes'])
        certificate=json.loads((equivalence/'independent-review-stop/basis-equivalence-review.json').read_bytes())
        need(certificate['independent_review_passed'] is True
             and certificate['old_complete_checkpoint_sha256']==spec['outer_sha256'],
             'JOINT_ACTUAL_CERTIFICATE_COMPLETE_PREDECESSOR')
    os.environ.pop('GH_TOKEN',None)
    proof=json.loads((core/'core-review.json').read_bytes())
    need(proof['complete'] and proof['counts']=={'formation':126,'daily':2156}
         and proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified'],
         'JOINT_ACTUAL_COMPLETE_CANONICAL_REVIEW')
    source=temp/'campaign-joint-source';binding=json.loads((core/'source-bindings.json').read_bytes())
    rendered=candidate_source(frozen/'source-fixed',source,binding['parameters']) if args.arm.startswith('P') else baseline_source(frozen/'source-fixed',source)
    need(rendered==binding,'JOINT_OWN_EXACT_FINANCIAL_SOURCE')
    for root in (source,core,*([equivalence] if equivalence else [])):
        for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
        os.chmod(root,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'JOINT_HOSTED_RESOURCES')
    out=temp/'campaign-joint-output';out.mkdir(mode=0o700);(out/'request.json').write_bytes(args.request.read_bytes())
    receipt={'schema':'research.system-campaign-joint-numerical-receipt/1','arm':args.arm,
        'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(args.request),
        'protocol_sha256':request['protocol_sha256'],'core_predecessor_run_id':spec['run_id'],
        'core_checkpoint_sha256':spec['outer_sha256'],'production_contacted':False,'new_core_financial_sessions':0,
        'global_selection_performed':False,'performance_admitted':False,'status':'NOT_STARTED'}
    known=False
    try:
        name=f'capital-system-joint-{args.arm.lower()}-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(command(name,source,frozen,out,core,equivalence_proof=equivalence),name,out,deadline=7200,inspector=inspect)
        known=True;receipt['worker']=w;receipt['status']='JOINT_STOPPED_OUTPUT_PRESERVED'
        shutil.copyfile(out/'worker-inspect.json',out/'economic-worker-inspect.json')
        if w['exit_code']==0 and not w['oom_killed']:
            audit=temp/'campaign-joint-review';audit.mkdir(mode=0o700)
            name=f'capital-system-joint-{args.arm.lower()}-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            r=stopped_run(command(name,source,frozen,audit,core,out,equivalence),name,audit,deadline=3600,inspector=inspect)
            receipt['reviewer']=r;shutil.copytree(audit,out/'independent-review-stop')
            if r['exit_code']==0 and not r['oom_killed']:
                actual=json.loads((audit/'review/independent-review.json').read_bytes())
                need(actual['all_training_metrics_verified'] and actual['baseline_all_account_fields_exact'],
                     'JOINT_ACTUAL_INDEPENDENT_REVIEW')
                receipt['status']='JOINT_TRAINING_REVIEWED_FINALIST_CONFIRMATION_REQUIRED'
    except StopUnknown:receipt['status']='JOINT_REVIEW_STOP_UNKNOWN_KNOWN_OUTPUT_PRESERVED' if known else 'JOINT_WORKER_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='JOINT_REFUSED_KNOWN_OUTPUT' if known else 'JOINT_REFUSED_NO_FINANCIAL_ADMISSION'
        if known:(out/'driver-failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(out,args.output.parent/('campaign-joint-'+args.arm+'.tar.crseal'),key,
        args.request,args.arm,stage='multiyear-controller',protocol_sha256=request['protocol_sha256'])
    key=None;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='JOINT_TRAINING_REVIEWED_FINALIST_CONFIRMATION_REQUIRED' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for n in ('request','staging','output'):parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--arm',required=True);main(parser.parse_args())
