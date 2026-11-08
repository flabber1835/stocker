"""One failed immutable export, a fresh complete review, and no financial run."""
import ast,json,os
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_postclose_distribution_restart as runtime
import system_campaign_financial_review_repair as repair

HERE=Path(__file__).parent
FACT='P07-request231-readonly-recovery-fact.json'
FACT_SHA='f0064c4c904ae07e0fcdd5893ac9c6baf4c878292d9ba37b7afe8b850852d491'
FIELD='selected_p07_request231_readonly_recovery'
MARKER='p07_request231_readonly_recovery'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
ORIGIN=runtime.saved.ROOT
OUTER='c7067ac86c8eda4e034a3b813a699f174c7216e462f3e123f6017aa26d825937'
RUN=42432498836
HEAD='cdfc263f2d2d1cf30708d422e21e9c5d11707027'
ARTIFACT=13598958730
STATUS='REFUSED_STOPPED_EVIDENCE_PRESERVED'
LEGACY_SHA='9d4d9e938685926838e229f05f064803137f47d53bfdacf406bee7a1bffcfa5e'
_ORIGINALS={n:getattr(repair,n) for n in ('public_names','admit')}

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'REQUEST231_EXACT_AUTHENTICATED_RECOVERY_FACT')
 return json.loads(raw)

def applies(spec):return isinstance(spec,dict) and spec.get(MARKER) is True

def validate_target(spec):
 need(applies(spec) and encoded(spec)==encoded(fact()['target']),'REQUEST231_ONLY_EXACT_FAILED_FULL26_READONLY_TARGET')
 need(spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
  and spec['readonly_failed_review_requalification'] is True
  and 'root_admission' not in spec and 'root_admission_sha256' not in spec and spec['review_sha256'] is None
  and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(1403,'2023-07-31',26)
  and spec['manifest']==dict(member_count=583,raw_member_bytes=995686191)
  and spec['zip_bytes']==760027846 and spec['receipt_status']==STATUS
  and all(spec['prior_stops'][r]==dict(stopped=True,exit_code=c,oom_killed=False,wait_error=None)
   and type(spec['prior_stops'][r]['exit_code'])is int for r,c in (('preflight',0),('worker',1),('reviewer',1))),
  'REQUEST231_ORIGINAL_FAILED_STOPS_ONE_GIB_AND_NO_AUTHORITY')
 return True

def target():return json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P07']

def declaration(spec):
 validate_target(spec)
 return dict(fact_sha256=FACT_SHA,original_parent_root=ORIGIN,target_outer_sha256=OUTER,completed=1403,full_inputs=26,
  retained_proofs=929,new_days=20,financial_workers=0,financial_authority=False,original_failed_stops_preserved=True)

def request_only_readonly(request,spec):
 validate_target(spec)
 need(request['execution_mode']==MODE and request['arms']==['P07'] and request['financial_resume_authorized'] is False
  and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==0
  and type(request['maximum_parallel_readonly_workers'])is int and request['maximum_parallel_readonly_workers']==1
  and request.get(FIELD)=={'P07':declaration(spec)},'REQUEST231_EXPLICIT_ZERO_FINANCIAL_READONLY_REQUEST')
 return True

def selected_request(request):
 if not request.get(FIELD):return False
 return request_only_readonly(request,target())

def source_names():return (Path(__file__).name,FACT,'system_campaign_postclose_distribution_runtime.py')

def bind_expected_request(original,module):
 def expected():
  value=original();value[FIELD]={}
  if module.EXECUTION_MODE==MODE and list(module.SELECTED_ARMS)==['P07'] and applies(target()):
   value[FIELD]={'P07':declaration(target())};value['arm_inputs']['P07']['new_factual_overlay']=False
  for n in source_names():
   pin=sha((HERE/n).read_bytes());need(n not in value['sources'] or value['sources'][n]==pin,'REQUEST231_NO_SOURCE_PIN_REPLACEMENT')
   value['sources'][n]=pin
  return value
 return expected

def bind(fn,**changes):
 need(fn.__closure__ is None,'REQUEST231_COMPLETE_ORIGINAL_FUNCTION_WITHOUT_HIDDEN_CLOSURE')
 value=FunctionType(fn.__code__,dict(fn.__globals__,**changes),fn.__name__,fn.__defaults__)
 value.__kwdefaults__=fn.__kwdefaults__;return value

def legacy_tree(name):
 raw=Path(repair.__file__).read_bytes();need(sha(raw)==LEGACY_SHA,'REQUEST231_WHOLE_ORIGINAL_FAILED_TRANSPORT_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
 if name=='admit':
  site,=[n for n in ast.walk(fn) if isinstance(n,ast.BinOp) and ast.unparse(n)=='512 * 1024 ** 2']
  site.left.value=1024
 return ast.fix_missing_locations(fn)

def legacy(name):
 scope=dict(_ORIGINALS[name].__globals__,validate_target=validate_target,request_only_readonly=request_only_readonly,
  public_names=public_names,prove_refusal=prove_refusal,ORIGIN=ORIGIN,OUTER=OUTER,RUN=RUN,HEAD=HEAD,ARM='P07',ARTIFACT=ARTIFACT,STATUS=STATUS)
 exec(compile(ast.Module(body=[legacy_tree(name)],type_ignores=[]),'<whole-original-failed-transport-exact-request231-one-gib>','exec'),scope)
 return scope[name]

def public_names(spec,archive):return legacy('public_names')(spec,archive)

def prove_refusal(spec,inventory,root):
 from system_campaign_financial_partial import root_spec
 validate_target(spec);root=Path(root);value=fact();raw=(root/'driver-failure.txt').read_bytes()
 need(dict(bytes=len(raw),sha256=sha(raw))==value['driver_failure_commitment']==inventory['driver-failure.txt']
  and b'shutil.copytree(audit' in raw and b'FileExistsError' in raw and b'/stopped-review' in raw,
  'REQUEST231_EXACT_AUTHENTICATED_REVIEW_COPY_COLLISION')
 origin=root_spec('P07',ORIGIN);need(json.loads((root/'spec.json').read_bytes())==origin,'REQUEST231_GENUINE_ORIGINAL1383_PARENT')
 old=json.loads((root/'old-prefix-canonical-review.json').read_bytes())
 need(old['checkpoint_sha256']==origin['outer_sha256'] and old['counts']==dict(formation=126,daily=1383)
  and old['all_prefixes_verified'] is old['all_daily_factors_and_chains_verified'] is True
  and 'stopped-review/core-review.json' not in inventory,'REQUEST231_OLD_REVIEW_IS_NOT_CURRENT1403_REVIEW')
 historical=(root/'stopped-review/uncertainty-certificate-review.json').read_bytes()
 need(dict(bytes=len(historical),sha256=sha(historical))==value['preserved_historical_branch_review_commitment']
  and json.loads(historical)['through']=='2023-06-30','REQUEST231_KEEP_OLD_REVIEW_AND_UNKNOWN_NEW_ERROR_DISTINCT')

def launcher_guard():
 from probe import check_context
 check_context(os.environ)

def admit(spec,root,key,inspector):launcher_guard();return legacy('admit')(spec,root,key,inspector)

def require_requalified_review(root,spec):
 validate_target(spec);root=Path(root)
 core=json.loads((root/'core-review.json').read_bytes());branch=json.loads((root/'uncertainty-certificate-review.json').read_bytes())
 need(core['checkpoint_sha256']==branch['checkpoint_sha256']==OUTER and core['counts']==dict(formation=126,daily=1403)
  and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True and core['complete'] is False
  and branch['passed'] is True and (branch['retained_rows'],branch['rows'])==(929,20)
  and branch['full_input_descriptors']==26 and branch['through']=='2023-07-31'
  and branch['all_financial_watch_and_proof_identities_verified'] is branch['every_reachable_decision_identical'] is True,
  'REQUEST231_FRESH_WHOLE1403_CORE_AND_ALL929_PLUS20_BRANCH_REVIEW')
 event=json.loads((root/runtime.EVENT_REVIEW).read_bytes())
 need(event['passed'] is event['event_committed'] is True,'REQUEST231_ACTUAL_BWA_DISTRIBUTION_REVIEW_REQUIRED')
 return dict(passed=True,checkpoint_sha256=OUTER,financial_authority=False,financial_sessions_advanced=0,
  original_financial_artifact_id=ARTIFACT,original_failed_stops_preserved=True,
  core_review_sha256=sha((root/'core-review.json').read_bytes()),branch_review_sha256=sha((root/'uncertainty-certificate-review.json').read_bytes()),
  distribution_review_sha256=sha((root/runtime.EVENT_REVIEW).read_bytes()))

def deny(*args,**kwargs):raise ValueError('REQUEST231_READONLY_FINANCIAL_CALLBACK_FORBIDDEN')

@contextmanager
def worker_context(module,spec,*,mode,out):
 from full_system_core import hosted
 hosted();need(mode in ('preflight','review'),'REQUEST231_NO_ECONOMIC_WORKER_CONTEXT')
 import system_campaign_financial_partial as partial
 import system_campaign_financial_additional_sensor as additional
 import system_campaign_ordinary_augmentation_router as router
 origin=partial.root_spec('P07',ORIGIN)
 need(applies(spec) if mode=='preflight' else spec==origin,'REQUEST231_ONLY_TARGET_PREFLIGHT_OR_GENUINE_ORIGINAL_REVIEW_PARENT')
 if applies(spec):validate_target(spec)
 actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(Path(module.__file__).read_bytes()).body
  if isinstance(n,ast.FunctionDef) and n.name in fact()['original4_AST']}
 need(actual==fact()['original4_AST'],'REQUEST231_FOUR_MATURE_FINANCIAL_WORKER_BODIES_UNCHANGED')
 previous=partial.financial_inputs,module.financial_inputs,additional.phase,router.implementation,runtime.legacy.uncertainty_phase
 @contextmanager
 def inputs(root,current,output,target_spec):
  need(target_spec==origin or applies(target_spec),'REQUEST231_READONLY_ONLY_DECLARED_FULL_INPUT_CONTEXT')
  if applies(target_spec):validate_target(target_spec)
  scope,_=runtime.base_api(root,current,origin)
  with scope['original_chain'](root,current,origin):yield
 def implementation(root,current,target_spec):
  if target_spec!=origin:return previous[3](root,current,target_spec)
  scope,_=runtime.base_api(root,current,origin)
  def review_request(request,actual_spec):
   need(actual_spec==origin,'REQUEST231_REVIEW_REQUIRES_GENUINE1383_SPEC');return request_only_readonly(request,target())
  original_review=bind(runtime.review,require_request=review_request)
  def review(parent,evidence,output,actual_spec,old):
   return original_review(parent,evidence,output,spec=actual_spec,old=old,request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes()))
  return SimpleNamespace(**dict(scope,run=deny,run_retained=deny,review=review))
 partial.financial_inputs=module.financial_inputs=inputs
 additional.phase=lambda s:runtime.models.lifecycle().phase(s) if s==origin else previous[2](s)
 router.implementation=implementation
 runtime.legacy.uncertainty_phase=lambda s:s==origin or previous[4](s)
 try:yield
 finally:partial.financial_inputs,module.financial_inputs,additional.phase,router.implementation,runtime.legacy.uncertainty_phase=previous

@contextmanager
def context(request,*,mode,module=None,spec=None,out=None):
 launcher_guard() if mode=='launch' else None
 need(mode in ('launch','preflight','review'),'REQUEST231_ECONOMIC_MODE_FORBIDDEN');need(selected_request(request),'REQUEST231_EXACT_ACTIVE_READONLY_REQUEST')
 previous={n:getattr(repair,n) for n in ('applies','admit','ORIGIN','require_requalified_review')}
 repair.applies=lambda s:applies(s) or previous['applies'](s)
 repair.admit=lambda s,*a,**k:admit(s,*a,**k) if applies(s) else previous['admit'](s,*a,**k)
 repair.ORIGIN=ORIGIN
 repair.require_requalified_review=lambda root,s:require_requalified_review(root,s) if applies(s) else previous['require_requalified_review'](root,s)
 try:
  if mode=='launch':yield
  else:
   with worker_context(module,spec,mode=mode,out=out):yield
 finally:
  for n,value in previous.items():setattr(repair,n,value)

def bind_launch(original):
 def launch(args):
  request=json.loads(Path(args.request).read_bytes())
  if not selected_request(request):return original(args)
  need(args.arm=='P07','REQUEST231_ONLY_P07_READONLY_LAUNCH')
  with context(request,mode='launch'):return original(args)
 return launch

def bind_dispatch(original):
 @contextmanager
 def entry(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if request.get(FIELD):
   with context(request,mode=mode,module=module,spec=spec,out=out):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return entry

def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry)
 module.expected_request=bind_expected_request(module.expected_request,module)
 module.launch=bind_launch(module.launch)
