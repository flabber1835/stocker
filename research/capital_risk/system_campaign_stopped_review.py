"""Read-only review of exact stopped evidence, preserving all financial sources."""
import argparse,ast,base64,hashlib,json,os,shutil,sys
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType
HERE=Path(__file__).parent
REQUEST='system-campaign-stopped-review-request.json'
FACT='P06-FIN356-stopped-review-fact.json'
CAPTURED='P06-FIN356-captured-financial-request.json'
ORIGINAL_REQUEST_SHA='a6d57b1ffc888ee344fefb1a20071fa9c8558e0678f2982efcaa990be1abfb69'
OBSERVER_SHA='a091a44855a9caacede61fee9b6d6eb2439fb1ff1e32e234ddf35189d56a879a'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def need(value,reason):
    if not value:raise ValueError('STOPPED_REVIEW_'+reason)
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def save(path,value):
    with Path(path).open('xb') as stream:stream.write(encoded(value))

def validate(request):
    need(request['schema']=='research.stopped-evidence-review-request/1'
        and request['financial_authority'] is request['input_adopted'] is False
        and request['maximum_parallel_financial_workers']==0 and request['maximum_parallel_readonly_workers']==1,
        'ONLY_ZERO_FINANCIAL_AUTHORITY')
    need(all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in (Path(__file__).name,FACT,CAPTURED)),
        'OWN_REVIEW_DRIVER_AND_FACTS_EXPLICITLY_PINNED')
    for name,pin in request['sources'].items():
        need(Path(name).name==name and '/' not in name and '\\' not in name and sha((HERE/name).read_bytes())==pin,'EXACT_SOURCE:'+name)
    raw=(HERE/CAPTURED).read_bytes();need(sha(raw)==ORIGINAL_REQUEST_SHA,'EXACT_ORIGINAL_REQUEST')
    captured=json.loads(raw)
    need(all(request['sources'].get(n)==pin for n,pin in captured['sources'].items()),'ALL_ORIGINAL_SOURCES_UNCHANGED')
    fact=json.loads((HERE/FACT).read_bytes());target=fact['target']
    need(target['artifact_id']==13581395529 and target['zip_sha256']=='ce2405785f528589717639bda16410b0597c971d73a08def39d711fbc36a2da8'
        and target['run_id']==42385528389 and target['head']=='77544e71403fdc0732dbb054e2e70b345ca1ddc8'
        and target['outer_sha256']=='3a7dbe9befba4316481b5955203302edd057e5e90b655ba2531c8ccd92f5d12a'
        and target['zip_bytes']==491500117 and target['manifest']==dict(member_count=335,raw_member_bytes=698976477)
        and (target['measured_closes'],target['selected_session'],len(target['repairs']))==(1677,'2024-08-30',12)
        and target['financial_authority'] is target['financial_predecessor_admitted'] is False
        and target['receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED' and target['review_sha256'] is None,
        'EXACT_UNADMITTED_STOPPED_TARGET')
    return fact,captured

def refusal_after_saved_prefix(record,status,parent_cursor,current_cursor):
    need(set(record)=={'session','cash','stock','risk','order','engine_calls','source','source_prior_absent','passed','error','financial_source_changed'}
        and record['passed'] is record['financial_source_changed'] is record['source_prior_absent'] is False
        and type(record['engine_calls']) is int and record['engine_calls']==0
        and all(record[k]==[] for k in ('cash','stock','risk','order','source')),
        'REFUSAL_MUST_HAVE_NO_HISTORICAL_OR_PARTIAL_CALLS')
    need(parent_cursor<current_cursor<record['session']==status['failed_session']
        and status['status']=='REFUSED' and current_cursor<status['session']<status['failed_session']
        and type(status['completed_sessions']) is int and status['completed_sessions']>1677
        and record['error']=='incomplete leadership cash terminal: 896501989594575427'
        and record['session']=='2024-09-27','REFUSAL_ONLY_EXACT_EXCLUDED_FUTURE_TAIL')
    return True

def allow_refusal(folder,parent,current,evidence):
    path=Path(folder)/'actual-future-event-refusal.json'
    if not path.exists():return True
    return refusal_after_saved_prefix(json.loads(path.read_bytes()),json.loads((Path(evidence)/'book/status.json').read_bytes()),
        parent['source_cursor'],current['source_cursor'])

def observer_review_tree(raw):
    need(sha(raw)==OBSERVER_SHA,'WHOLE_ORIGINAL_OBSERVER_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.UnaryOp) and ast.unparse(n)=="not (folder / 'actual-future-event-refusal.json').exists()"]
    class Adapt(ast.NodeTransformer):
        def visit_UnaryOp(self,n):
            return ast.copy_location(ast.parse('allow_refusal(folder,parent,current,evidence)',mode='eval').body,n) if n is site else self.generic_visit(n)
    return ast.fix_missing_locations(Adapt().visit(fn))

def observer_review():
    import system_campaign_p06_WWE12_observer as original
    scope=dict(vars(original),allow_refusal=allow_refusal)
    exec(compile(ast.Module(body=[observer_review_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-observer-review-excluded-tail-refusal-only>','exec'),scope)
    return scope['review']

def inspect(name,identity=None):
    import system_campaign_financial_resume as original
    raw=Path(original.__file__).read_bytes();fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/driver/system_campaign_financial_resume.py']
    need(len(sites)==1,'ONE_ORIGINAL_INSPECTOR_COMMAND_SITE');sites[0].value='/driver/system_campaign_stopped_review.py'
    scope=dict(vars(original));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-original-inspector-source-review-command>','exec'),scope)
    return scope['inspect'](name,identity)

def bind(fn,**changes):
    need(fn.__closure__ is None,'COMPLETE_FUNCTION_WITHOUT_CLOSURE')
    result=FunctionType(fn.__code__,dict(fn.__globals__,**changes),fn.__name__,fn.__defaults__);result.__kwdefaults__=fn.__kwdefaults__
    return result

def failed_admit(target,root,key):
    import system_campaign_financial_review_repair as original
    def exact(value):need(value==target,'EXACT_FAILED_TARGET');return True
    public=bind(original.public_names,validate_target=exact)
    def prove(value,inventory,folder):
        exact(value);raw=(folder/'stopped-review/worker.log').read_bytes()
        need(sha(raw)==target['review_log_sha256']==inventory['stopped-review/worker.log']['sha256']
            and b'P06_WWE12_NO_REEXECUTED_OLD_CASH_SOURCE_OBSERVATIONS_OR_REFUSAL' in raw
            and 'stopped-review/core-review.json' not in inventory,'ORIGINAL_DIAGNOSED_REFUSAL_PRESERVED')
    def request_guard(captured,value):
        exact(value);validate(json.loads((HERE/REQUEST).read_bytes()))
        need(sha(encoded(captured))==ORIGINAL_REQUEST_SHA,'CAPTURED_REQUEST_IS_PROVENANCE_ONLY')
    return bind(original.admit,public_names=public,prove_refusal=prove,request_only_readonly=request_guard,
        RUN=target['run_id'],HEAD=target['head'])(target,root,key,__import__('system_campaign_financial_resume').inspect)

def worker():
    from full_system_core import hosted
    hosted();need(str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_DRIVER_ONLY')
    request=json.loads((HERE/REQUEST).read_bytes());fact,captured=validate(request)
    import system_campaign_financial_resume as resume
    import system_campaign_p06_WWE12_runtime as runtime
    from system_campaign_financial_partial import root_spec
    from research.pooled_vacancy_funding import backtest,runtime as financial
    spec=json.loads(Path('/out/spec.json').read_bytes());need(spec==root_spec('P06',runtime.data.ROOT),'ORIGINAL_ADMITTED_PARENT_ONLY')
    def refuse(*a,**k):raise ValueError('STOPPED_REVIEW_FINANCIAL_ADVANCE_FORBIDDEN')
    saved=backtest.main,financial.advance,runtime.observations.review
    backtest.main=financial.advance=refuse;runtime.observations.review=observer_review()
    try:
        with runtime.entry_context(resume,spec,mode='review',old=Path('/old'),out=Path('/out'),request=captured,evidence=Path('/evidence')):
            from system_campaign_retained_cash_v2 import review_entry
            review_entry(Path('/evidence'),Path('/out'),spec,resume.review)
            from system_campaign_financial_partial import monthly_reproduction
            current=runtime.strict_json(Path('/evidence/book/checkpoint.json.gz').read_bytes())
            monthly_reproduction(Path('/evidence'),Path('/out'),fact['target'],current)
    finally:backtest.main,financial.advance,runtime.observations.review=saved
    core=json.loads(Path('/out/core-review.json').read_bytes());branch=json.loads(Path('/out/uncertainty-certificate-review.json').read_bytes())
    need(core['checkpoint_sha256']==branch['checkpoint_sha256']==fact['target']['outer_sha256']
        and core['counts']==dict(formation=126,daily=1677) and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True
        and branch['passed'] is True and (branch['rows'],branch['retained_rows'])==(251,173),'FULL_FRESH_CORE_AND_BRANCH_REVIEW')
    save('/out/stopped-review-summary.json',dict(passed=True,financial_authority=False,input_adopted=False,financial_sessions_advanced=0,
        checkpoint_sha256=core['checkpoint_sha256'],completed=1677,through='2024-08-30',monthly_reproduction_required=False,independent_root_admission_required=True))

def launch(request_path,staging,output):
    from probe import check_context
    from stage import SECRET
    from full_system_trials_job import command,seal
    from alpaca_fit_job import stopped_run,StopUnknown
    import system_campaign_financial_resume as resume
    import system_campaign_p06_WWE12_runtime as runtime
    import system_campaign_financial_review_repair as repair
    from system_campaign_financial_partial import root_spec
    from full_system_source import build
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_BLIND_RERUN')
    request=json.loads(Path(request_path).read_bytes());fact,captured=validate(request)
    resume.stage_valid(json.loads(Path(staging).read_bytes()))
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'SEPARATE_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);spec=root_spec('P06',runtime.data.ROOT)
    evidence=failed_admit(fact['target'],temp/'campaign-factual-transfer-stopped-review',key)
    saved=repair.applies;repair.applies=lambda v:False if runtime.candidate(v) else saved(v)
    try:
        with runtime.loader.context(spec,captured,mode='launch',profile_validator=runtime.request_financial):
            old=resume.admit_partial(spec,temp/'campaign-factual-transfer-stopped-review-origin',key,resume.inspect)
    finally:repair.applies=saved
    need((old/'source-bindings.json').read_bytes()==(evidence/'source-bindings.json').read_bytes(),'ORIGINAL_FINANCIAL_SOURCE_EPOCH')
    os.environ.pop('GH_TOKEN',None);os.environ.pop('GITHUB_TOKEN',None)
    frozen=temp/'capital-risk-stage-001/inputs';source=temp/'stopped-review-financial-source'
    binding=json.loads((old/'source-bindings.json').read_bytes());need(build(frozen/'source-fixed',source,binding['parameters'])==binding,'WHOLE_FINANCIAL_SOURCE_BUILD')
    for directory in (old,evidence,source):
        for p in directory.rglob('*'):p.chmod(0o555 if p.is_dir() else 0o444)
        directory.chmod(0o555)
    out=temp/'stopped-review-output';out.mkdir(mode=0o700);save(out/'spec.json',spec);save(out/'request.json',request)
    name='capital-system-resume-p06-review-'+os.environ['GITHUB_RUN_ID']+'-1'
    values=command(name,source,frozen,out,'review');i=values.index('--entrypoint')
    values[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly','--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    values[values.index('-B'):]=['-B','-u','/driver/system_campaign_stopped_review.py','--mode','review','--spec','/out/spec.json']
    receipt=dict(schema='research.stopped-evidence-review-receipt/1',run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha(Path(request_path).read_bytes()),protocol_sha256=request['protocol_sha256'],financial_authority=False,input_adopted=False,
        financial_sessions_advanced=0,original_financial_run=fact['target']['run_id'],status='READONLY_REVIEW_RUNNING')
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    try:receipt['reviewer']=stopped_run(values,name,out,deadline=2400,inspector=inspect)
    except StopUnknown:
        receipt['status']='REVIEW_UNKNOWN_NO_MUTABLE_EXPORT';save(output,receipt);raise
    stop=receipt['reviewer'];need(stop['stopped'] is True and type(stop['exit_code']) is int,'POSITIVE_STOP_BEFORE_EXPORT')
    receipt['status']='STOPPED_EVIDENCE_REVIEW_PASSED_PENDING_ROOT' if stop['exit_code']==0 and not stop['oom_killed'] else 'STOPPED_EVIDENCE_REVIEW_REFUSED_PRESERVED'
    receipt['encrypted_output']=seal(out,Path(output).with_suffix('.tar.crseal'),key,Path(request_path),'P06_STOPPED_REVIEW',stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    save(output,receipt);print(json.dumps(receipt),flush=True)
    return 0 if stop['exit_code']==0 and not stop['oom_killed'] else 2

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('launch','review'),required=True);p.add_argument('--request',type=Path);p.add_argument('--staging',type=Path);p.add_argument('--output',type=Path);p.add_argument('--spec',type=Path);a=p.parse_args()
    if a.mode=='review':worker()
    else:raise SystemExit(launch(a.request,a.staging,a.output))
if __name__=='__main__':main()
