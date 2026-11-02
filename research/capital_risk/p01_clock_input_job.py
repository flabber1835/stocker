"""Qualify the registered clock input, then freshly resume own438 through pre-CELG."""
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
from system_campaign_pxd_financial_body import function
from system_campaign_parallel_discovery import compile_body
from p01_action_clock_parent import SPEC,specification,reference,admit
from p01_clock_input_codec import document,FACTS
from p01_clock_input_export import STAGE,qualify_export,write_receipt,preserve_qualification,finish
import p01_action_clock_job as previous
import system_campaign_p02_continue_job as inspector_source

HERE=Path(__file__).parent
PRIOR='p01_action_clock_request.json'
PRIOR_SHA='dbb4cb6584f74121ca7dffdca56b394c2582c40b2c9f9eaad3187f18286fe223'
REQUEST='p01_clock_input_request.json'
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,PRIOR,FACTS,'p01_clock_input_codec.py',
    'p01_clock_input_run.py','p01_clock_input_review.py','p01_clock_input_export.py',
    'p01_clock_input_job.py','p01_clock_input_probe.py','system_campaign_pxd_pause.py')))


def expected_request():
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA and json.loads((HERE/PRIOR).read_bytes())==previous.expected_request(),
         'P01_CLOCK_INPUT_ALL410_OLD_COMPONENT_SOURCES_UNCHANGED')
    spec=specification()
    return dict(schema='research.p01-economic-clock-financial-request/1',arm='P01',campaign='system-optimization-002',
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        source_financial_file=SPEC,source_financial_sha256=sha256_file(HERE/SPEC),parent_reference=reference(spec),
        original_inputs=8,new_typed_clock_inputs=1,input_document=document(),
        input_document_sha256=__import__('hashlib').sha256((json.dumps(document(),sort_keys=True,indent=2)+'\n').encode()).hexdigest(),
        source515_unchanged=True,financial_state_conversion=False,qualification_state_adoption=False,
        financial_start='2019-09-30',processing_endpoint='2019-11-19',maximum_financial_transitions=37,
        expected_completed=475,full_measurement_start='2018-01-02',full_measurement_end='2026-07-31',
        new_codec_zero_session_startup_and_two_component_transition_gate=True,
        qualification_wait_seconds=1800,financial_wait_seconds=2400,review_wait_seconds=900,
        retain_stopped_qualification_before_financial_launch=True,actual_marker_roundtrip_before_parent=True,
        initial_min_disk_bytes=12*1024**3,preworker_min_disk_bytes=10*1024**3,
        preworker_min_memory_bytes=10*1024**3,artifact_retention_days=7,
        sources={n:sha256_file(HERE/n) for n in SOURCES},production_contacted=False)


def entrypoint(mode):
    need(mode in ('qualify','economic','review'),'P01_CLOCK_INPUT_EXACT_MODE')
    return ['-B','-u','/driver/p01_clock_input_run.py','--mode',mode,'--spec','/out/spec.json']


def inspect(name,identity=None):
    value=function('system_campaign_p02_continue_job.py','inspect',{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-p01-clock-input-(?:qualify|worker|review)-[0-9]+-1'},vars(inspector_source))(name,identity)
    mode='review' if '-review-' in name else 'qualify' if '-qualify-' in name else 'economic'
    need(value['Config']['Cmd']==entrypoint(mode),'P01_CLOCK_INPUT_EXACT_WORKER_ENTRYPOINT')
    return value


def worker_command(name,mode,source,frozen,out,old,evidence=None):
    import system_campaign_p01_accurate_job as command_source
    values=command_source.worker_command(name,'review' if mode=='review' else 'economic',source,frozen,out,old,evidence)
    values[values.index('-B'):]=entrypoint(mode);return values


def resources(request,temp):
    need(memory_bytes()['MemAvailable']>=request['preworker_min_memory_bytes']
         and shutil.disk_usage(temp).free>=request['preworker_min_disk_bytes'],
         'P01_CLOCK_INPUT_BEFORE_EACH_WORKER_RESOURCE_RESERVE')


def note(path,phase,error=None):
    namespace=dict(vars(previous),AUTHORITY='NONFINANCIAL_HOST_PHASE_METADATA',
        PHASES=previous.PHASES|{'QUALIFIER_LAUNCH_ATTEMPTED','QUALIFIER_STOPPED','FINANCIAL_LAUNCH_ATTEMPTED',
            'FINANCIAL_STOPPED','REVIEW_LAUNCH_ATTEMPTED','REVIEW_STOPPED','REVIEW_STOP_UNKNOWN'},
        PUBLIC_CODES=previous.PUBLIC_CODES|{'REFUSED_FULL_SYSTEM_P01_CLOCK_INPUT_INITIAL_DISK_RESERVE',
            'REFUSED_FULL_SYSTEM_P01_CLOCK_INPUT_BEFORE_EACH_WORKER_RESOURCE_RESERVE',
            'REFUSED_FULL_SYSTEM_P01_CLOCK_INPUT_EXACT_FINANCIAL_SOURCE515'})
    raw=Path(previous.__file__).read_bytes()
    need(sha256_file(Path(previous.__file__))==json.loads((HERE/PRIOR).read_bytes())['sources']['p01_action_clock_job.py'],
         'P01_CLOCK_INPUT_EXACT_ADMITTED410_PHASE_IMPLEMENTATION')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='note']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant)
           and n.value=='research.p01-action-clock-public-phase/1']
    need(len(sites)==1,'P01_CLOCK_INPUT_ONE_PUBLIC_PHASE_SCHEMA_SITE')
    sites[0].value='research.p01-clock-input-public-phase/1'
    return compile_body(fn,namespace)(path,phase,error)


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','P01_CLOCK_INPUT_NO_BLIND_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'P01_CLOCK_INPUT_EXACT_REQUEST')
    stage_valid(json.loads(args.staging.read_bytes()))
    temp=Path(os.environ['RUNNER_TEMP']);args.output.parent.mkdir(parents=True,exist_ok=True)
    note_path=args.output.parent/'p01-clock-input-phase.json'
    r=dict(schema='research.p01-economic-clock-financial-receipt/1',arm='P01',stage=STAGE,
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),
        protocol_sha256=request['protocol_sha256'],strict_parent_outer_sha256=specification()['outer_sha256'],
        status='BEFORE_EXPORT_PROBE',production_contacted=False,qualification_exported=False)
    write_receipt(args.output,r);out=temp/'p01-clock-input-financial-output';out.mkdir(mode=0o700)
    known=False;key=None
    try:
        note(note_path,'BEFORE_EXPORT_PROBE')
        probe=qualify_export(temp/'p01-clock-input-export-probe',args.request)
        probe_path=args.output.parent/'p01-clock-input-export-qualification.json'
        probe_path.write_bytes((json.dumps(probe,sort_keys=True,indent=2)+'\n').encode())
        r['export_qualification_sha256']=sha256_file(probe_path);note(note_path,'EXPORT_PROBE_PASSED')
        key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'P01_CLOCK_INPUT_SEPARATE_KEY')
        note(note_path,'BEFORE_INITIAL_DISK_GATE')
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'P01_CLOCK_INPUT_INITIAL_DISK_RESERVE')
        note(note_path,'BEFORE_PARENT_FETCH');old=admit(temp/'campaign-factual-transfer-p01-clock-input',key)
        note(note_path,'PARENT_ADMITTED');frozen=temp/'capital-risk-stage-001/inputs';source=temp/'p01-clock-input-source'
        binding=json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',source,binding['parameters'])==binding,'P01_CLOCK_INPUT_EXACT_FINANCIAL_SOURCE515')
        note(note_path,'SOURCE_IDENTICAL')
        for directory in (source,old):
            for path in directory.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(directory,0o555)
        os.environ.pop('GH_TOKEN',None)
        for name,path in [('spec.json',HERE/SPEC),('request.json',args.request),('source-bindings.json',old/'source-bindings.json')]:
            shutil.copyfile(path,out/name)
        qual=temp/'p01-clock-input-qualification-output';qual.mkdir(mode=0o700);shutil.copyfile(HERE/SPEC,qual/'spec.json')
        note(note_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(note_path,'QUALIFIER_LAUNCH_ATTEMPTED')
        name='capital-system-p01-clock-input-qualify-'+os.environ['GITHUB_RUN_ID']+'-1'
        r['status']='REGISTERED_INPUT_QUALIFICATION_LAUNCH_ATTEMPTED';write_receipt(args.output,r)
        r['qualification_worker']=stopped_run(worker_command(name,'qualify',source,frozen,qual,old),name,qual,
            deadline=request['qualification_wait_seconds'],inspector=inspect)
        known=True;note(note_path,'QUALIFIER_STOPPED')
        (out/'qualification').mkdir()
        if (qual/'proof').exists():shutil.copytree(qual/'proof',out/'qualification',dirs_exist_ok=True)
        for name in ('worker-inspect.json','worker.log'):shutil.copyfile(qual/name,out/'qualification'/name)
        s=r['qualification_worker'];need(s['exit_code']==0 and not s['oom_killed'],'P01_CLOCK_INPUT_QUALIFIER_REFUSED')
        q=json.loads((out/'qualification/qualification-summary.json').read_bytes())
        need(q['status']=='REGISTERED_CLOCK_INPUT_CANONICALLY_QUALIFIED' and q['typed_inputs']==9
             and q['component_transitions']==2 and q['financial_predecessor_authorized'] is False
             and q['new_input_document_sha256']==request['input_document_sha256'],
             'P01_CLOCK_INPUT_ACTUAL_REGISTERED_CODEC_GATE')
        r['status']='REGISTERED_INPUT_QUALIFIED_ORIGINAL_OWN438_NOT_YET_ADVANCED'
        preserve_qualification(r,out,args.output,key,args.request)
        note(note_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(note_path,'FINANCIAL_LAUNCH_ATTEMPTED')
        name='capital-system-p01-clock-input-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        known=False;r['status']='FRESH_OWN438_FINANCIAL_LAUNCH_ATTEMPTED';write_receipt(args.output,r)
        r['worker']=stopped_run(worker_command(name,'economic',source,frozen,out,old),name,out,
            deadline=request['financial_wait_seconds'],inspector=inspect)
        known=True;note(note_path,'FINANCIAL_STOPPED')
        r['status']='FINANCIAL_STOPPED_PENDING_SUFFIX_REVIEW';write_receipt(args.output,r)
        outcome=json.loads((out/'clock-input-outcome.json').read_bytes())
        need(outcome['new_input_document_sha256']==q['new_input_document_sha256'],
             'P01_CLOCK_INPUT_FINANCIAL_DOCUMENT_IDENTICAL_TO_ACTUAL_QUALIFIER')
        import gzip
        actual=json.loads(gzip.decompress((out/'book/checkpoint.json.gz').read_bytes()))
        need(actual['run']['input_sha256']==q['successor_input_sha256'],
             'P01_CLOCK_INPUT_FINANCIAL_INPUT_IDENTITY_IDENTICAL_TO_ACTUAL_QUALIFIER')
        # A genuine financial refusal is preserved and reviewed at its actual committed cursor.
        review=temp/'p01-clock-input-review-output';review.mkdir(mode=0o700);shutil.copyfile(HERE/SPEC,review/'spec.json')
        note(note_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp)
        name='capital-system-p01-clock-input-review-'+os.environ['GITHUB_RUN_ID']+'-1'
        note(note_path,'REVIEW_LAUNCH_ATTEMPTED')
        try:
            r['reviewer']=stopped_run(worker_command(name,'review',source,frozen,review,old,out),name,review,
                deadline=request['review_wait_seconds'],inspector=inspect)
        except StopUnknown:
            r['status']='FINANCIAL_STOPPED_REVIEW_STOP_UNKNOWN';r['review_stop_unknown']=True
            note(note_path,'REVIEW_STOP_UNKNOWN')
        else:
            note(note_path,'REVIEW_STOPPED')
            shutil.copytree(review,out/'stopped-review');s=r['reviewer']
            if s['exit_code']==0 and not s['oom_killed']:
                r['status']='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT' \
                    if outcome['status']=='COMPLETE_CLOCK_INPUT_FINANCIAL_SEGMENT_PENDING_REVIEW' else \
                    'PARTIAL_FINANCIAL_PREFIX_HOSTED_REVIEWED_REFUSAL_PRESERVED'
            else:r['status']='FINANCIAL_SUFFIX_REVIEW_REFUSED_PRESERVED'
    except StopUnknown as error:
        known=False;r['status']='ACTIVE_WORKER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT';note(note_path,'STOP_UNKNOWN',error)
    except Exception as error:
        r['status']='CLOCK_INPUT_REFUSED_KNOWN_STOP' if known else 'CLOCK_INPUT_REFUSED_BEFORE_STOP_PROOF'
        note(note_path,'FAILURE',error)
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    note(note_path,'BEFORE_EXPORT');finish(r,out,args.output,key,args.request,known=known);key=None
    note(note_path,'FINISHED');print(json.dumps(r),flush=True)
    raise SystemExit(0 if r['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
