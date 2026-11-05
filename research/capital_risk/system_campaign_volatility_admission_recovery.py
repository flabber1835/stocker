"""P11-only host admission recovery, with bounded nonfinancial phase evidence."""
import argparse,ast,json,os,shutil,traceback
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from probe import memory_bytes
from system_campaign_parallel_discovery import compile_body
import system_campaign_volatility_reference_job as previous

HERE=Path(__file__).parent
PRIOR=previous.REQUEST
PRIOR_SHA='542b3c344802e425786ff817cd69a56be6dc413dc9f89b1bdd1bf8371481afd4'
REQUEST='system-campaign-volatility-admission-recovery-request-001.json'
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,PRIOR,'system_campaign_volatility_admission_recovery.py',
                           'system_campaign_volatility_admission_probe.py')))
STAGES={'BEFORE_INITIAL_DISK_GATE','BEFORE_STRICT_PARENT_FETCH','STRICT_PARENT_ADMITTED',
        'BEFORE_RETAINED_FAST_FETCH','RETAINED_FAST_ADMITTED','BEFORE_WORKER_RESOURCE_GATE',
        'QUALIFIER_LAUNCH_ATTEMPTED','QUALIFIER_STOPPED','DISCOVERY_LAUNCH_ATTEMPTED','FAILURE'}
PUBLIC_CODES={
    'REFUSED_FULL_SYSTEM_PARALLEL_INITIAL_DISK_RESERVE',
    'REFUSED_FULL_SYSTEM_HOSTED_FACTUAL_DESTINATION_CAPACITY',
    'REFUSED_FULL_SYSTEM_PARALLEL_ONE_WORKER_PER_VM_RESOURCE_GATE',
    'REFUSED_FULL_SYSTEM_PARALLEL_EXACT_ORIGINAL_CANDIDATE_FINANCIAL_SOURCE_NO_CONVERSION'}


def expected_request():
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'V_ADMISSION_EXACT415_REQUEST')
    old=json.loads((HERE/PRIOR).read_bytes())
    need(old==previous.expected_request() and len(old['sources'])==415,'V_ADMISSION_ALL415_OLD_SOURCES_UNCHANGED')
    value=previous.expected_request()
    value.update(schema='research.volatility-p11-admission-recovery-request/1',arms=['P11'],
        concurrent_candidate_limit=1,prior415_request_sha256=PRIOR_SHA,other_P10_job_unchanged=True,
        retained_preworker_failure_run_id=41366297007,retained_preworker_failure_artifact_id=13107306946,
        retained_preworker_receipt_sha256='7dd7006719ec1bdbe4d391ea29cea1b000546f410cb9d648bd9dd010290b527c',
        atomic_allowlisted_nonfinancial_admission_phases=True,
        sources={n:sha256_file(HERE/n) for n in SOURCES})
    return value


def note(path,stage,error=None):
    need(stage in STAGES,'V_ADMISSION_PUBLIC_PHASE_ALLOWLIST')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    old=json.loads(path.read_bytes()) if path.exists() else None
    message=str(error) if error is not None else ''
    value=dict(schema='research.volatility-nonfinancial-admission-phase/1',
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],arm='P11',stage=stage,
        previous_stage=old['stage'] if old else None,free_disk_bytes=shutil.disk_usage(Path(os.environ['RUNNER_TEMP'])).free,
        available_memory_bytes=memory_bytes()['MemAvailable'],
        exception_class=type(error).__name__ if error is not None else None,
        invariant_code=message if message in PUBLIC_CODES else None,
        code_locations=[dict(file=Path(f.filename).name,function=f.name,line=f.lineno)
                        for f in traceback.extract_tb(error.__traceback__)] if error is not None else [],
        exception_value_printed=False,financial_or_market_payload_included=False,
        telemetry_only=True,production_contacted=False)
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();temporary=path.with_suffix('.pending')
    with temporary.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def tree():
    fn=previous.orchestration_tree();block,=[n for n in fn.body if isinstance(n,ast.Try)]
    targets={"old":"BEFORE_STRICT_PARENT_FETCH","binding":"STRICT_PARENT_ADMITTED",
             "receipt['qualification_worker']":"QUALIFIER_LAUNCH_ATTEMPTED",
             'proof':'QUALIFIER_STOPPED'}
    new=[]
    for i,n in enumerate(block.body):
        stage='BEFORE_INITIAL_DISK_GATE' if i==0 else None
        if isinstance(n,ast.Assign) and len(n.targets)==1:stage=targets.get(ast.unparse(n.targets[0]),stage)
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call):
            if ast.unparse(n.value.func)=='admit_fast':stage='BEFORE_RETAINED_FAST_FETCH'
            elif ast.unparse(n.value.func)=='os.environ.pop':stage='RETAINED_FAST_ADMITTED'
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='need':
            if 'MemAvailable' in ast.unparse(n):stage='BEFORE_WORKER_RESOURCE_GATE'
        if stage:new.extend(ast.parse(f"note(args.output.parent/'admission-phase.json',{stage!r})").body)
        new.append(n)
    need(sum(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='note'
             for n in new)==8,'V_ADMISSION_EXACT_EIGHT_OBSERVATION_SITES')
    block.body=new
    handler,=[h for h in block.handlers if isinstance(h.type,ast.Name) and h.type.id=='Exception']
    handler.name='admission_error'
    handler.body[:0]=ast.parse("note(args.output.parent/'admission-phase.json','FAILURE',admission_error)").body
    return ast.fix_missing_locations(fn)


def main(args):
    need(args.arm=='P11','V_ADMISSION_ONLY_UNLOCALIZED_P11_NO_P10_RERUN')
    return compile_body(tree(),dict(vars(previous.parallel),expected_request=expected_request,
        worker_command=previous.worker_command,inspect=previous.inspect,admit_fast=previous.admit_fast,
        check_qualification=previous.v1.check_qualification,note=note))(args)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=['P11'],required=True)
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
