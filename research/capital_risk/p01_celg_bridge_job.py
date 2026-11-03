"""Qualify OWN475 source/input bridge; freshly continue and review bounded finance."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from seal import sha256_file
from stage import SECRET
from system_campaign_variants import build
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_parallel_discovery import compile_body
from p01_celg_bridge_gate import specification,HERE,SPEC,digest
from p01_celg_bridge_parent import admit,PRIOR,PRIOR_SHA
from p01_celg_bridge_source import write_disjoint
from p01_celg_bridge_export import STAGE,qualify_export,write_receipt,preserve_qualification,finish
from p01_celg_input_transport import authenticate_capsule
from ephemeral_runner_capacity import validate_prepared_receipt
import p01_action_clock_job as phases
import system_campaign_p02_continue_job as inspector_source

REQUEST='p01_celg_bridge_request.json'
DESCRIPTOR='p01_celg_bridge_quote_descriptor.json'
SOURCE_MAP='p01_celg_bridge_source_map.json'
NEW=('p01_celg_source.py','p01_celg_component.py','p01_celg_bridge_payload.py','p01_celg_bridge_source.py',
    SPEC,'p01_celg_bridge_gate.py','p01_celg_bridge_parent.py','p01_celg_bridge_codec.py',
    'p01_celg_bridge_pause.py','p01_celg_bridge_accounting.py','p01_celg_bridge_facts.json',
    'p01_celg_bridge_run.py','p01_celg_bridge_review.py','p01_celg_bridge_export.py',
    'p01_celg_bridge_job.py','p01_celg_bridge_probe.py',DESCRIPTOR,SOURCE_MAP,
    'p01_celg_input_transport.py','ephemeral_runner_capacity.py')
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'],PRIOR,*NEW)))


def expected_request():
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'P01_CELG_BRIDGE_EXACT_PRIOR418_REQUEST')
    prior=json.loads((HERE/PRIOR).read_bytes())
    need(len(prior['sources'])==418 and all(sha256_file(HERE/n)==h for n,h in prior['sources'].items()),
         'P01_CELG_BRIDGE_ALL418_PRIOR_SOURCE_BYTES_UNCHANGED')
    spec=specification();descriptor=json.loads((HERE/DESCRIPTOR).read_bytes())
    source_map=json.loads((HERE/SOURCE_MAP).read_bytes())
    return dict(schema='research.p01-celg-own475-financial-bridge-request/1',arm='P01',
        campaign='system-optimization-002',stage=STAGE,
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        source_financial_file=SPEC,source_financial_sha256=sha256_file(HERE/SPEC),
        original_outer_sha256=spec['outer_sha256'],original_inner_sha256=spec['inner_sha256'],
        original_state_sha256=spec['state_sha256'],original_input_sha256=spec['input_sha256'],
        original_inputs=9,new_typed_clock_and_right_input=1,
        original_physical_sources=515,successor_physical_sources=516,
        original_canonical_sources=223,successor_canonical_sources=224,
        source_map_file_sha256=sha256_file(HERE/SOURCE_MAP),source_map_identity_sha256=digest(source_map),
        source_map_changed_paths=sorted(source_map['changed']),
        old_source_restore_proofs_reused=spec['reused_hosted_old_source_proofs'],
        quote_descriptor=descriptor,quote_descriptor_sha256=sha256_file(HERE/DESCRIPTOR),
        quote_release_asset_id=700454247,
        quote_release_upload_review_sha256='1c7c413236a895f1ec5fad9865ae317acaa3c660718c6abed1b897839ea2d27d',
        actual_quote_transport_sha256='b5b9ff12a66d9ca7bf66c3c934af2e9262924f1e7ca71a026fb78fc86b74bb42',
        capacity_source_sha256='c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379',
        no_plaintext_market_response_in_public_sources=True,source_then_input_zero_session_boundaries=True,
        qualified_full_runtime_sessions=2,qualification_state_adoption=False,
        financial_start='2019-11-20',processing_endpoint='2020-02-04',maximum_financial_transitions=51,
        expected_completed=526,full_measurement_end='2026-07-31',
        qualification_wait_seconds=2400,financial_wait_seconds=3600,review_wait_seconds=1200,
        initial_min_disk_bytes=12*1024**3,preworker_min_disk_bytes=10*1024**3,
        preworker_min_memory_bytes=10*1024**3,artifact_retention_days=7,
        sources={n:sha256_file(HERE/n) for n in SOURCES},production_contacted=False)


def entrypoint(mode):
    need(mode in ('qualify','economic','review'),'P01_CELG_BRIDGE_EXACT_MODE')
    return ['-B','-u','/driver/p01_celg_bridge_run.py','--mode',mode,'--spec','/out/spec.json']


def inspect(name,identity=None):
    raw=Path(inspector_source.__file__).read_bytes()
    need(sha256_file(Path(inspector_source.__file__))==json.loads((HERE/PRIOR).read_bytes())['sources'][
        'system_campaign_p02_continue_job.py'],'P01_CELG_BRIDGE_PINNED_INSPECTOR')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
    pattern,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value==
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1']
    pattern.value=r'capital-system-p01-celg-bridge-(?:qualify|worker|review)-[0-9]+-1'
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign)
                  and any(isinstance(v,ast.Name) and v.id=='expected' for v in n.targets)]
    assignment.value=ast.parse("{'/variant','/frozen','/driver','/out','/old','/celg-input',"
        "'/celg-input-descriptor.json'} | (set() if '-qualify-' in name else {'/evidence'})",mode='eval').body
    value=compile_body(fn,vars(inspector_source))(name,identity)
    mode='qualify' if '-qualify-' in name else 'review' if '-review-' in name else 'economic'
    need(value['Config']['Cmd']==entrypoint(mode),'P01_CELG_BRIDGE_EXACT_WORKER_ENTRYPOINT')
    return value


def worker_command(name,mode,source,frozen,out,old,capsule,evidence=None):
    from system_campaign_p01_accurate_job import worker_command as original
    values=original(name,'review' if mode=='review' else 'economic',source,frozen,out,old,evidence)
    index=values.index('--entrypoint')
    values[index:index]=['--mount',f'type=bind,source={capsule},target=/celg-input,readonly',
        '--mount',f'type=bind,source={HERE/DESCRIPTOR},target=/celg-input-descriptor.json,readonly']
    values[values.index('-B'):]=entrypoint(mode);return values


def resources(request,temp):
    need(memory_bytes()['MemAvailable']>=request['preworker_min_memory_bytes']
         and shutil.disk_usage(temp).free>=request['preworker_min_disk_bytes'],
         'P01_CELG_BRIDGE_BEFORE_EACH_WORKER_RESOURCE_RESERVE')


def note(path,phase,error=None):
    fn,=[n for n in ast.parse(Path(phases.__file__).read_bytes()).body
         if isinstance(n,ast.FunctionDef) and n.name=='note']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant)
           and n.value=='research.p01-action-clock-public-phase/1']
    site.value='research.p01-celg-bridge-public-phase/1'
    namespace=dict(vars(phases),AUTHORITY='NONFINANCIAL_HOST_PHASE_METADATA',
        PHASES=phases.PHASES|{'QUALIFIER_LAUNCH_ATTEMPTED','QUALIFIER_STOPPED','FINANCIAL_LAUNCH_ATTEMPTED',
            'FINANCIAL_STOPPED','REVIEW_LAUNCH_ATTEMPTED','REVIEW_STOPPED','REVIEW_STOP_UNKNOWN'},
        PUBLIC_CODES=phases.PUBLIC_CODES|{'REFUSED_FULL_SYSTEM_P01_CELG_BRIDGE_INITIAL_DISK_RESERVE',
            'REFUSED_FULL_SYSTEM_P01_CELG_BRIDGE_BEFORE_EACH_WORKER_RESOURCE_RESERVE'})
    return compile_body(fn,namespace)(path,phase,error)


def freeze(root):
    for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(root,0o555)


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','P01_CELG_BRIDGE_NO_BLIND_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'P01_CELG_BRIDGE_EXACT_REQUEST')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],source_sha256=request['capacity_source_sha256'])
    stage_valid(json.loads(args.staging.read_bytes()))
    temp=Path(os.environ['RUNNER_TEMP']);args.output.parent.mkdir(parents=True,exist_ok=True)
    note_path=args.output.parent/'p01-celg-bridge-phase.json'
    r=dict(schema='research.p01-celg-own475-financial-bridge-receipt/1',arm='P01',stage=STAGE,
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),
        protocol_sha256=request['protocol_sha256'],strict_parent_outer_sha256=specification()['outer_sha256'],
        status='BEFORE_EXPORT_PROBE',production_contacted=False,qualification_exported=False)
    write_receipt(args.output,r);out=temp/'p01-celg-bridge-financial-output';out.mkdir(mode=0o700)
    known=False;key=None
    try:
        note(note_path,'BEFORE_EXPORT_PROBE')
        probe=qualify_export(temp/'p01-celg-bridge-export-probe',args.request)
        probe_path=args.output.parent/'p01-celg-bridge-export-qualification.json'
        probe_path.write_bytes((json.dumps(probe,sort_keys=True,indent=2)+'\n').encode())
        r['export_qualification_sha256']=sha256_file(probe_path);note(note_path,'EXPORT_PROBE_PASSED')
        key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'P01_CELG_BRIDGE_SEPARATE_KEY')
        note(note_path,'BEFORE_INITIAL_DISK_GATE')
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'P01_CELG_BRIDGE_INITIAL_DISK_RESERVE')
        note(note_path,'BEFORE_PARENT_FETCH');old=admit(temp/'campaign-factual-transfer-p01-celg-bridge',key)
        note(note_path,'PARENT_ADMITTED')
        capsule=temp/'p01-celg-actual-input';authenticate_capsule(request['quote_descriptor'],capsule,key=key)
        frozen=temp/'capital-risk-stage-001/inputs';original=temp/'p01-celg-bridge-old-source'
        binding=json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',original,binding['parameters'])==binding,
             'P01_CELG_BRIDGE_EXACT_ORIGINAL515_SOURCE')
        files={p.relative_to(original).as_posix():p.read_bytes() for p in original.rglob('*') if p.is_file()}
        source=temp/'p01-celg-bridge-successor-source'
        source_map=write_disjoint(files,binding['all_sources'],source,
                                  financial_sources=specification()['base']['sources'])
        need(source_map==json.loads((HERE/SOURCE_MAP).read_bytes()),'P01_CELG_BRIDGE_EXACT_FULL_SOURCE_SUCCESSOR_MAP')
        note(note_path,'SOURCE_IDENTICAL')
        for root in (original,source,old,capsule):freeze(root)
        os.environ.pop('GH_TOKEN',None)
        for name,path in [('spec.json',HERE/SPEC),('request.json',args.request),
            ('source-bindings.json',old/'source-bindings.json'),('source-map.json',HERE/SOURCE_MAP)]:
            shutil.copyfile(path,out/name)
        qual=temp/'p01-celg-bridge-qualification-output';qual.mkdir(mode=0o700)
        for name in ('spec.json','source-map.json'):shutil.copyfile(out/name,qual/name)
        note(note_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(note_path,'QUALIFIER_LAUNCH_ATTEMPTED')
        name='capital-system-p01-celg-bridge-qualify-'+os.environ['GITHUB_RUN_ID']+'-1'
        r['status']='SOURCE_INPUT_QUALIFICATION_LAUNCH_ATTEMPTED';write_receipt(args.output,r)
        r['qualification_worker']=stopped_run(worker_command(name,'qualify',source,frozen,qual,old,capsule),name,qual,
            deadline=request['qualification_wait_seconds'],inspector=inspect)
        known=True;note(note_path,'QUALIFIER_STOPPED')
        (out/'qualification').mkdir()
        if (qual/'proof').exists():shutil.copytree(qual/'proof',out/'qualification',dirs_exist_ok=True)
        for n in ('worker-inspect.json','worker.log'):shutil.copyfile(qual/n,out/'qualification'/n)
        s=r['qualification_worker'];need(s['exit_code']==0 and not s['oom_killed'],'P01_CELG_BRIDGE_QUALIFIER_REFUSED')
        q=json.loads((qual/'proof/qualification-summary.json').read_bytes())
        need(q['status']=='OWN475_CELG_SOURCE_INPUT_AND_TWO_SESSIONS_QUALIFIED'
             and q['financial_predecessor_authorized'] is False and q['component_transitions']==2
             and q['source_map_sha256']==request['source_map_identity_sha256'],
             'P01_CELG_BRIDGE_ACTUAL_FULL_RUNTIME_QUALIFIER_GATE')
        r['status']='SOURCE_INPUT_QUALIFIED_ORIGINAL_OWN475_NOT_YET_ADVANCED'
        preserve_qualification(r,out,args.output,key,args.request)
        freeze(qual)
        note(note_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(note_path,'FINANCIAL_LAUNCH_ATTEMPTED')
        name='capital-system-p01-celg-bridge-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        known=False;r['status']='FRESH_OWN475_FINANCIAL_LAUNCH_ATTEMPTED';write_receipt(args.output,r)
        r['worker']=stopped_run(worker_command(name,'economic',source,frozen,out,old,capsule,qual),name,out,
            deadline=request['financial_wait_seconds'],inspector=inspect)
        known=True;note(note_path,'FINANCIAL_STOPPED')
        r['status']='FINANCIAL_STOPPED_PENDING_SUFFIX_REVIEW';write_receipt(args.output,r)
        outcome=json.loads((out/'celg-bridge-outcome.json').read_bytes())
        need(outcome['input_document_sha256']==q['input_document_sha256'],
             'P01_CELG_BRIDGE_FRESH_FINANCE_SAME_QUALIFIED_INPUT_DOCUMENT')
        review=temp/'p01-celg-bridge-review-output';review.mkdir(mode=0o700);shutil.copyfile(HERE/SPEC,review/'spec.json')
        note(note_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(note_path,'REVIEW_LAUNCH_ATTEMPTED')
        name='capital-system-p01-celg-bridge-review-'+os.environ['GITHUB_RUN_ID']+'-1'
        try:
            r['reviewer']=stopped_run(worker_command(name,'review',source,frozen,review,old,capsule,out),name,review,
                deadline=request['review_wait_seconds'],inspector=inspect)
        except StopUnknown:
            r['status']='FINANCIAL_STOPPED_REVIEW_STOP_UNKNOWN';r['review_stop_unknown']=True
            note(note_path,'REVIEW_STOP_UNKNOWN')
        else:
            note(note_path,'REVIEW_STOPPED');shutil.copytree(review,out/'stopped-review');s=r['reviewer']
            r['status']=('FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT' if
                outcome['status']=='COMPLETE_CELG_BRIDGE_SEGMENT_PENDING_REVIEW' else
                'PARTIAL_FINANCIAL_PREFIX_HOSTED_REVIEWED_REFUSAL_PRESERVED') if s['exit_code']==0 and not s['oom_killed'] \
                else 'FINANCIAL_SUFFIX_REVIEW_REFUSED_PRESERVED'
    except StopUnknown as error:
        known=False;r['status']='ACTIVE_WORKER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT';note(note_path,'STOP_UNKNOWN',error)
    except Exception as error:
        r['status']='CELG_BRIDGE_REFUSED_KNOWN_STOP' if known else 'CELG_BRIDGE_REFUSED_BEFORE_STOP_PROOF'
        note(note_path,'FAILURE',error)
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    note(note_path,'BEFORE_EXPORT');finish(r,out,args.output,key,args.request,known=known);key=None
    note(note_path,'FINISHED');print(json.dumps(r),flush=True)
    raise SystemExit(0 if r['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
