"""Read-only retained FAST evidence; bounded missing-reference qualification."""
import argparse,ast,json,os
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import body,literals,compile_body
from system_campaign_volatility_reference_parent import SPEC,admit
import system_campaign_parallel_discovery_job as parallel
import system_campaign_volatility_discovery_job as v1
import system_campaign_volatility_discovery_job_v2 as previous
import system_campaign_p02_continue_job as inspector_source

HERE=Path(__file__).parent;ARMS=('P10','P11')
REQUEST='system-campaign-volatility-discovery-request-003.json'
PRIOR=previous.REQUEST
PRIOR_SHA='40774539921540348cf90cff4b95c81d08ab5ec1f0e6b028efaf1167cc93e4e0'
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,PRIOR,SPEC,
    'system_campaign_volatility_reference_parent.py','system_campaign_volatility_reference_gate.py',
    'system_campaign_volatility_reference_run.py','system_campaign_volatility_reference_job.py',
    'system_campaign_volatility_reference_probe.py')))


def expected_request():
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'V_REFERENCE_EXACT408_PREDECESSOR_REQUEST')
    old=json.loads((HERE/PRIOR).read_bytes())
    need(len(old['sources'])==408 and all(sha256_file(HERE/n)==v for n,v in old['sources'].items()),
         'V_REFERENCE_ALL408_PRIOR_DRIVER_BYTES_UNCHANGED')
    value=previous.expected_request();need(value==old,'V_REFERENCE_ORIGINAL_EXPECTED_REQUEST_UNCHANGED')
    value.update(schema='research.volatility-discovery-reference-qualification-recovery-request/1',
        prior408_request_sha256=PRIOR_SHA,reused_fast_spec=SPEC,reused_fast_spec_sha256=sha256_file(HERE/SPEC),
        only_missing_reference_qualification_executed=True,reused_fast_run_id=41362963470,
        reused_fast_qualifier_exit_code=137,diagnostic_origin_before_reference_equality=False,
        qualify_wait_seconds=3600,discovery_wait_seconds=14400,
        reference_transition_progress_durable=True,sources={n:sha256_file(HERE/n) for n in SOURCES})
    return value


def entrypoint(arm,mode):
    need(arm in ARMS and mode in ('qualify','discovery'),'V_REFERENCE_EXACT_TWO_ENTRYPOINTS')
    return ['-B','-u','/driver/system_campaign_volatility_reference_run.py','--mode',mode,
            '--arm',arm,'--spec','/out/spec.json']


def fast_directory(arm):
    return Path(os.environ['RUNNER_TEMP'])/('campaign-factual-transfer-v-reference-'+arm.lower())/'admitted'


def worker_command(name,arm,mode,source,frozen,out,old):
    value=parallel.worker_command(name,arm,mode,source,frozen,out,old)
    value[value.index('-B'):]=entrypoint(arm,mode)
    if mode=='qualify':
        at=value.index('--entrypoint')
        value[at:at]=['--mount',f'type=bind,source={fast_directory(arm)},target=/previous,readonly']
    return value


def inspect(name,identity=None):
    arm=name.split('-')[4].upper();mode='qualify' if '-qualify-' in name else 'discovery'
    need(arm in ARMS,'V_REFERENCE_ONLY_SELECTED_ARM_INSPECTIONS')
    fn=literals(body('system_campaign_p02_continue_job.py','inspect'),{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-parallel-discovery-p(?:10|11)-(?:qualify|worker)-[0-9]+-1'})
    sets=[n for n in ast.walk(fn) if isinstance(n,ast.Set) and all(isinstance(v,ast.Constant) for v in n.elts)
          and {ast.literal_eval(v) for v in n.elts}=={'/variant','/frozen','/driver','/out','/old'}]
    need(len(sets)==1,'V_REFERENCE_ONE_READONLY_PREVIOUS_MOUNT_SET')
    if mode=='qualify':sets[0].elts.append(ast.Constant('/previous'))
    value=compile_body(fn,vars(inspector_source))(name,identity)
    need(value['Config']['Cmd']==entrypoint(arm,mode),'V_REFERENCE_EXACT_CANONICAL_ENTRYPOINT')
    return value


def admit_fast(arm,temp,key):
    dest=admit(arm,Path(temp)/('campaign-factual-transfer-v-reference-'+arm.lower()),key)
    need(dest==fast_directory(arm),'V_REFERENCE_FIXED_DISJOINT_DESTINATION')
    for path in dest.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(dest,0o555)
    return dest


def orchestration_tree():
    fn=v1.previous.adopted('main')
    inserts=[]
    for n in ast.walk(fn):
        if (isinstance(n,ast.Call) and ast.unparse(n.func)=='os.environ.pop'
           and len(n.args)>0 and isinstance(n.args[0],ast.Constant) and n.args[0].value=='GH_TOKEN'):
            inserts.append(n)
    need(len(inserts)==1,'V_REFERENCE_ONE_FETCH_BEFORE_TOKEN_DISCARD')
    block,=[n for n in fn.body if isinstance(n,ast.Try)]
    at,=[i for i,n in enumerate(block.body) if isinstance(n,ast.Expr) and n.value is inserts[0]]
    block.body[at:at]=ast.parse('admit_fast(arm,temp,key)').body
    for n in ast.walk(fn):
        if isinstance(n,ast.Assign) and len(n.targets)==1 and ast.unparse(n.targets[0])=='proof':
            proof=n;break
    else:raise ValueError('V_REFERENCE_MISSING_ORIGINAL_QUALIFICATION_ADMISSION')
    at,=[i for i,n in enumerate(block.body) if n is proof]
    block.body[at+1:at+1]=ast.parse('check_qualification(proof,args.arm)').body
    return ast.fix_missing_locations(fn)


def main(args):
    need(args.arm in ARMS,'V_REFERENCE_ONLY_TWO_UNSTARTED_DIAGNOSTIC_ARMS')
    return compile_body(orchestration_tree(),dict(vars(parallel),expected_request=expected_request,
        worker_command=worker_command,inspect=inspect,admit_fast=admit_fast,check_qualification=v1.check_qualification))(args)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
