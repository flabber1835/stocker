"""Exact FIN366 read-only recovery; never reexecute a financial transition."""
import argparse,ast,base64,json,os
from pathlib import Path
import system_campaign_stopped_review as common
from system_campaign_stopped_review import sha,need,encoded,save,bind
HERE=Path(__file__).parent
REQUEST='system-campaign-stopped-review-request.json'
FACT='P06-FIN366-stopped-review-fact.json'
CAPTURED='P06-FIN366-captured-financial-request.json'
PROFILE='P06_FIN366_FULL13_STOPPED_REVIEW'
REQUEST_SHA='23febbfdcfc9aac6e37d0a76988c58316ed6c41906be8e687c8f64269f02762a'
ROOT='ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845'
CHANGED=frozenset(('ephemeral_runner_capacity.py','system_campaign_financial_resume.py','system_campaign_source_exit_entry.py',
 'system_campaign_source_exit_observer.py','P06-source-exit-whole-profile-qualification.json'))
ADDED=frozenset((Path(__file__).name,FACT,CAPTURED,'system_campaign_source_exit_reporting.py','system_campaign_progress_observer.py'))


def validate(request):
 need(request.get('review_profile')==PROFILE and request['schema']=='research.stopped-evidence-review-request/1'
  and request['financial_authority'] is request['input_adopted'] is False
  and request['maximum_parallel_financial_workers']==0 and request['maximum_parallel_readonly_workers']==1,'FIN366_ZERO_FINANCIAL_AUTHORITY')
 raw=(HERE/CAPTURED).read_bytes();need(sha(raw)==REQUEST_SHA,'FIN366_EXACT_CAPTURED_REQUEST225');captured=json.loads(raw)
 expected=set(captured['sources'])|ADDED
 need(set(request['sources'])==expected and set(request['review_source_changes'])==CHANGED,'FIN366_CLOSED_REVIEW_SOURCE_DELTA')
 for name,pin in request['sources'].items():
  need(Path(name).name==name and '/' not in name and '\\' not in name and sha((HERE/name).read_bytes())==pin,'FIN366_EXACT_REVIEW_SOURCE:'+name)
  if name in captured['sources']:
   if name in CHANGED:need(request['review_source_changes'][name]==dict(original=captured['sources'][name],review=pin)
    and pin!=captured['sources'][name],'FIN366_EXPLICIT_REVIEW_SOURCE_DIFFERENCE:'+name)
   else:need(pin==captured['sources'][name],'FIN366_ALL_OTHER_CAPTURED_SOURCES_UNCHANGED:'+name)
 fact=json.loads((HERE/FACT).read_bytes());target=fact['target']
 need(fact['schema']=='research.stopped-evidence-review-fact/1' and fact['financial_authority'] is fact['input_adopted'] is False
  and fact['original_admitted_root']==ROOT and target['monthly_seed_root_admission_sha256']==ROOT,'FIN366_REAL_ADMITTED_PARENT')
 need((target['run_id'],target['head'],target['artifact_id'],target['zip_bytes'],target['zip_sha256'])==
  (42403944223,'cda95aa922085aa5b1bfb1a2d5b2337eb2a06abf',13587599730,737497136,'079552b2cf2ccd1f11ee3a9efbd082f2a7908784bbd1c39b64bf02af3f1c3a6a')
  and target['outer_sha256']=='8e9ca16b18cf79928e6e2d7320defacfdecca781447a5a8bd6fd803db02fe6c7'
  and target['manifest']==dict(member_count=456,raw_member_bytes=980668378)
  and (target['measured_closes'],target['selected_session'],len(target['repairs']))==(1821,'2025-03-31',13)
  and target['financial_authority'] is target['financial_predecessor_admitted'] is False
  and target['receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED' and target['request_sha256']==REQUEST_SHA
  and target['review_sha256'] is None and 'root_admission' not in target,'FIN366_EXACT_UNADMITTED_SAVED_TARGET')
 need(all(target['prior_stops'][role]==dict(stopped=True,exit_code=code,oom_killed=False,wait_error=None)
  for role,code in (('preflight',0),('worker',1),('reviewer',1))),'FIN366_ORIGINAL_FAILED_STOPS_PRESERVED')
 return fact,captured


def profile_request(captured,spec):
 from system_campaign_financial_partial import root_spec
 validate(json.loads((HERE/REQUEST).read_bytes()))
 need(sha(encoded(captured))==REQUEST_SHA and spec==root_spec('P06',ROOT),'FIN366_PROVENANCE_REQUEST_AND_GENUINE_PARENT_ONLY')
 return True


def inspect(name,identity=None):
 import system_campaign_financial_resume as resume
 fn,=[n for n in ast.parse(Path(resume.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/driver/system_campaign_financial_resume.py']
 site.value='/driver/system_campaign_source_exit_stopped_review.py';scope=dict(vars(resume))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-original-inspector-FIN366-readonly-command>','exec'),scope)
 return scope['inspect'](name,identity)


def failed_admit(target,root,key):
 import system_campaign_financial_review_repair as repair
 import system_campaign_financial_partial as partial
 import system_campaign_financial_resume as resume
 def exact(value):need(value==target,'FIN366_EXACT_QUARANTINE_TARGET');return True
 def refusal(value,inventory,folder):
  exact(value);raw=(folder/'stopped-review/worker.log').read_bytes()
  need(sha(raw)==target['review_log_sha256']==inventory['stopped-review/worker.log']['sha256']
   and b"KeyError: 'events'" in raw and b'system_campaign_source_exit_observer.py' in raw
   and 'stopped-review/core-review.json' not in inventory,'FIN366_ACTUAL_FAILED_COMPACT_INTERFACE_UNCHANGED')
 def request_guard(captured,value):exact(value);need(sha(encoded(captured))==REQUEST_SHA,'FIN366_CAPTURED_REQUEST_IS_PROVENANCE_ONLY')
 fn,=[n for n in ast.parse(Path(repair.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
 bound,=[k for n in ast.walk(fn) if isinstance(n,ast.Call) for k in n.keywords if k.arg=='max_zip_bytes']
 need(ast.unparse(bound.value)=='512 * 1024 ** 2','FIN366_ONE_ORIGINAL_ARCHIVE_BOUND_SITE')
 # Select an existing crypto option only for the exact source-pinned archive;
 # its actual737497136-byte length/hash and complete manifest remain required.
 fact,_=validate(json.loads((HERE/REQUEST).read_bytes()));need(target==fact['target'],'FIN366_ONLY_EXACT_ARCHIVE_USES_ONE_GIB_OPTION')
 bound.value=ast.parse('1024 ** 3',mode='eval').body
 scope=dict(vars(repair),public_names=bind(repair.public_names,validate_target=exact),prove_refusal=refusal,request_only_readonly=request_guard,RUN=target['run_id'],HEAD=target['head'])
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-failed-artifact-transport-exact-FIN366-ZIP-bound>','exec'),scope)
 return scope['admit'](target,root,key,resume.inspect)


def worker():
 from full_system_core import hosted
 hosted();need(str(Path(__file__).resolve()).startswith('/driver/'),'FIN366_HOSTED_DRIVER_ONLY')
 request=json.loads((HERE/REQUEST).read_bytes());fact,captured=validate(request)
 import system_campaign_source_exit_runtime as runtime
 import system_campaign_source_exit_entry as entry
 import system_campaign_financial_resume as resume
 from system_campaign_financial_partial import root_spec
 from research.pooled_vacancy_funding import backtest,runtime as financial
 spec=json.loads(Path('/out/spec.json').read_bytes());need(spec==root_spec('P06',ROOT),'FIN366_ORIGINAL1677_PARENT_ONLY')
 def refuse(*a,**k):raise ValueError('FIN366_READONLY_FINANCIAL_ADVANCE_FORBIDDEN')
 saved=backtest.main,financial.advance,runtime.request_financial
 backtest.main=financial.advance=refuse;runtime.request_financial=profile_request
 try:
  with entry.context(resume,spec,mode='review',old=Path('/old'),out=Path('/out'),request=captured,evidence=Path('/evidence')):
   from system_campaign_retained_cash_v2 import review_entry
   review_entry(Path('/evidence'),Path('/out'),spec,resume.review)
 finally:backtest.main,financial.advance,runtime.request_financial=saved
 core=json.loads(Path('/out/core-review.json').read_bytes());branch=json.loads(Path('/out/uncertainty-certificate-review.json').read_bytes())
 month=json.loads(Path('/out/monthly-reproduction.json').read_bytes())
 need(core['checkpoint_sha256']==branch['checkpoint_sha256']==month['checkpoint_sha256']==fact['target']['outer_sha256']
  and core['counts']==dict(formation=126,daily=1821) and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True
  and branch['passed'] is True and (branch['rows'],branch['retained_rows'])==(144,424)
  and month['passed'] is month['all_new_monthly_reports_exact'] is month['all_monthly_checkpoint_state_exact'] is True
  and month['financial_transitions_reexecuted']==0,'FIN366_FULL_CORE_BRANCH_EVENT_AND_MONTHLY_REVIEW')
 save('/out/stopped-review-summary.json',dict(passed=True,financial_authority=False,input_adopted=False,financial_sessions_advanced=0,
  checkpoint_sha256=core['checkpoint_sha256'],completed=1821,through='2025-03-31',independent_root_admission_required=True))


def launch(request_path,staging,output):
 from probe import check_context
 from stage import SECRET
 from full_system_trials_job import command,seal
 from alpaca_fit_job import stopped_run,StopUnknown
 import system_campaign_source_exit_runtime as runtime
 import system_campaign_financial_resume as resume
 import system_campaign_financial_review_repair as repair
 import system_campaign_stopped_parent as loader
 from system_campaign_financial_partial import root_spec
 from system_campaign_variants import build
 check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','FIN366_NO_BLIND_RERUN')
 request=json.loads(Path(request_path).read_bytes());fact,captured=validate(request)
 resume.stage_valid(json.loads(Path(staging).read_bytes()))
 key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'FIN366_SEPARATE_KEY')
 temp=Path(os.environ['RUNNER_TEMP']);spec=root_spec('P06',ROOT)
 evidence=failed_admit(fact['target'],temp/'campaign-factual-transfer-FIN366-review',key)
 saved=repair.applies;repair.applies=lambda v:False if runtime.candidate(v) else saved(v)
 try:
  with loader.context(spec,captured,profile_validator=profile_request):
   old=resume.admit_partial(spec,temp/'campaign-factual-transfer-FIN366-origin',key,resume.inspect)
 finally:repair.applies=saved
 need((old/'source-bindings.json').read_bytes()==(evidence/'source-bindings.json').read_bytes(),'FIN366_ORIGINAL_FINANCIAL_SOURCE_EPOCH')
 os.environ.pop('GH_TOKEN',None);os.environ.pop('GITHUB_TOKEN',None)
 frozen=temp/'capital-risk-stage-001/inputs';source=temp/'FIN366-review-financial-source'
 binding=json.loads((old/'source-bindings.json').read_bytes());need(build(frozen/'source-fixed',source,binding['parameters'])==binding,'FIN366_WHOLE_FINANCIAL_SOURCE_BUILD')
 for directory in (old,evidence,source):
  for p in directory.rglob('*'):p.chmod(0o555 if p.is_dir() else 0o444)
  directory.chmod(0o555)
 out=temp/'FIN366-readonly-output';out.mkdir(mode=0o700);save(out/'spec.json',spec);save(out/'request.json',request)
 name='capital-system-resume-p06-review-'+os.environ['GITHUB_RUN_ID']+'-1'
 values=command(name,source,frozen,out,'review');i=values.index('--entrypoint')
 values[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly','--mount',f'type=bind,source={evidence},target=/evidence,readonly']
 values[values.index('-B'):]=['-B','-u','/driver/system_campaign_source_exit_stopped_review.py','--mode','review','--spec','/out/spec.json']
 receipt=dict(schema='research.stopped-evidence-review-receipt/1',review_profile=PROFILE,run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
  request_sha256=sha(Path(request_path).read_bytes()),protocol_sha256=request['protocol_sha256'],financial_authority=False,input_adopted=False,
  financial_sessions_advanced=0,original_financial_run=fact['target']['run_id'],status='READONLY_REVIEW_RUNNING')
 Path(output).parent.mkdir(parents=True,exist_ok=True)
 try:receipt['reviewer']=stopped_run(values,name,out,deadline=2400,inspector=inspect)
 except StopUnknown:
  receipt['status']='REVIEW_UNKNOWN_NO_MUTABLE_EXPORT';save(output,receipt);raise
 stop=receipt['reviewer'];need(stop['stopped'] is True and type(stop['exit_code'])is int,'FIN366_POSITIVE_STOP_BEFORE_EXPORT')
 receipt['status']='STOPPED_EVIDENCE_REVIEW_PASSED_PENDING_ROOT' if stop['exit_code']==0 and not stop['oom_killed'] else 'STOPPED_EVIDENCE_REVIEW_REFUSED_PRESERVED'
 receipt['encrypted_output']=seal(out,Path(output).with_suffix('.tar.crseal'),key,Path(request_path),'P06_STOPPED_REVIEW',stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
 save(output,receipt);print(json.dumps(receipt),flush=True)
 return 0 if stop['exit_code']==0 and not stop['oom_killed'] else 2


def main():
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=('launch','review'),required=True);p.add_argument('--request',type=Path);p.add_argument('--staging',type=Path);p.add_argument('--output',type=Path);p.add_argument('--spec',type=Path);a=p.parse_args()
 if a.mode=='review':worker()
 else:
  selected=json.loads(a.request.read_bytes()).get('review_profile')==PROFILE
  raise SystemExit((launch if selected else common.launch)(a.request,a.staging,a.output))
if __name__=='__main__':main()
