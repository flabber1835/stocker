"""Exact completed financial export and a separate zero-financial monthly check."""
import ast,json,os
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_financial_partial as partial
import system_campaign_source_exit_runtime as runtime
HERE=Path(__file__).parent
FACT='P06-request232-complete-reporting-target-fact.json'
FACT_SHA='865e04b1906e98d1c93f326769424b8cd3694c9473ba85cd5316f3a439db67ae'
FIELD='selected_p06_request232_final_reporting'
MARKER='p06_request232_final_reporting'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
OUTER='6fccc63619c482230049777fda2cc1e8ccc5e7e4b817311af1b03381c957e3c6'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def applies(spec):return isinstance(spec,dict) and spec.get(MARKER) is True

def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'REPORT232_EXACT_AUTHENTICATED_COMPLETE_RESULT_FACT')
 return json.loads(raw)

def target():return json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P06']

def validate_target(spec):
 need(applies(spec) and encoded(spec)==encoded(fact()['target']),'REPORT232_ONLY_EXACT2156_FULL15_FAILED_REPORTING_TRANSPORT')
 need(spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
  and spec['readonly_full_financial_target'] is spec['reuse_closed_hosted_prefix_review'] is True
  and 'root_admission' not in spec and 'root_admission_sha256' not in spec
  and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(2156,'2026-07-31',15)
  and spec['receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED'
  and all(spec['prior_stops'][r]==dict(stopped=True,exit_code=c,oom_killed=False,wait_error=None)
   and type(spec['prior_stops'][r]['exit_code'])is int for r,c in (('preflight',0),('worker',0),('reviewer',1)))
  and spec['manifest']==dict(member_count=539,raw_member_bytes=983860575),
  'REPORT232_ORIGINAL_COMPLETE_FINANCE_AND_FAILED_REPORTING_STOPS_UNCHANGED')
 return True

def complete_target(spec):
 validate_target(spec)
 core=fact()['actual_original_core']
 need(core['complete'] is core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True
  and core['checkpoint_sha256']==OUTER and core['counts']==dict(formation=126,daily=2156) and core['monthly_metrics']==103
  and set(core['preserved_tails'])=={'formation','daily','monthly','watch'}
  and all(v==dict(bytes=0,sha256=sha(b'')) for v in core['preserved_tails'].values()),
  'REPORT232_READONLY_COMPLETE_TARGET_REQUIRES_REAL_COMPLETE_CORE_AND_EMPTY_TAILS')
 return True

def declaration(spec):
 validate_target(spec)
 return dict(fact_sha256=FACT_SHA,target_outer_sha256=OUTER,completed=2156,full_inputs=15,parent_completed=2050,
  new_days=106,new_monthly_reports=5,financial_workers=0,financial_authority=False,original_failed_stops_preserved=True,
  original_complete_core_reused=True,original_monthly_reader_unchanged=True)

def require_request(request,spec):
 validate_target(spec)
 need(request['execution_mode']==MODE and request['arms']==['P06'] and request['financial_resume_authorized'] is False
  and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==0
  and type(request['maximum_parallel_readonly_workers'])is int and request['maximum_parallel_readonly_workers']==1
  and request.get(FIELD)=={'P06':declaration(spec)},'REPORT232_EXPLICIT_ZERO_FINANCIAL_MONTHLY_ONLY_REQUEST')
 return True

def retired():return 'P06' in partial.COMPLETED_ADMISSIONS
def source_names():return (Path(__file__).name,FACT)

def bind_expected_request(original,module):
 def expected():
  active=module.EXECUTION_MODE==MODE and list(module.SELECTED_ARMS)==['P06'] and applies(target())
  if active:need(not retired(),'REPORT232_ALREADY_COMPLETED_REQUEST_RETIRED')
  value=original();value[FIELD]={}
  if active:
   value[FIELD]={'P06':declaration(target())};value['arm_inputs']['P06']['new_factual_overlay']=False
  for n in source_names():
   pin=sha((HERE/n).read_bytes());need(n not in value['sources'] or value['sources'][n]==pin,'REPORT232_NO_SOURCE_PIN_REPLACEMENT')
   value['sources'][n]=pin
  return value
 return expected

def public_names(spec,archive):
 validate_target(spec)
 fn,=[n for n in ast.parse(Path(partial.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='public_names']
 status,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='status']
 status.value=ast.Constant('FINANCIAL_REVIEW_REFUSED_PRESERVED')
 namespace=dict(vars(partial));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
  '<whole-original-public-format-exact-request232-failed-reporting-status>','exec'),namespace)
 return namespace['public_names'](spec,archive)

def prove_refusal(spec,inventory,root):
 validate_target(spec);root=Path(root);value=fact();raw=(root/'stopped-review/worker.log').read_bytes()
 need(dict(bytes=len(raw),sha256=sha(raw))==value['actual_original_review_log_commitment']==inventory['stopped-review/worker.log']
  and b'monthly_reproduction' in raw and b'PARTIAL_EXACT_RETAINED_ORIGINAL_INDEX' in raw,
  'REPORT232_EXACT_ORIGINAL_POST_CORE_REPORTING_INDEX_FAILURE')
 for n,key in (('stopped-review/core-review.json','actual_original_core'),
  ('stopped-review/uncertainty-certificate-review.json','actual_original_branch'),
  ('stopped-review/source-exit-successor-observation-review.json','actual_original_source_observer')):
  raw=(root/n).read_bytes()
  need(dict(bytes=len(raw),sha256=sha(raw))==inventory[n] and json.loads(raw)==value[key],
   'REPORT232_ENTIRE_ACTUAL_COMPLETED_CORE_BRANCH_SOURCE_PROOF:'+n)
 need('stopped-review/monthly-reproduction.json' not in inventory and 'monthly-reproduction.json' not in inventory,
  'REPORT232_NO_ORIGINAL_SUCCESSFUL_MONTHLY_PROOF_INVENTED')
 parent=partial.root_spec('P06',spec['monthly_seed_root_admission_sha256'])
 old=json.loads((root/'spec.json').read_bytes())
 need(old==parent and old['original_parent_index_sha256']==value['original_admitted_seed_index_sha256']
  and spec['original_parent_index_sha256']==value['new_reporting_index_sha256']
  and value['new_reporting_index_file']==partial.ORIGINALS
  and sha((HERE/partial.ORIGINALS).read_bytes())==value['new_reporting_index_sha256'],
  'REPORT232_OLD_FAILED_SPEC_AND_NEW_GENUINE_INDEX_BINDING_DISTINCT')

def launcher_guard():
 from probe import check_context
 check_context(os.environ)

def archive_limit(spec):validate_target(spec);return 1024**3

def admit(spec,root,key,inspector):
 launcher_guard();validate_target(spec)
 crypto=SimpleNamespace(**dict(vars(partial.crypto),prove_review_refusal=prove_refusal))
 fn=partial.admit
 need(fn.__closure__ is None,'REPORT232_WHOLE_ORIGINAL_ADMISSION_WITHOUT_CLOSURE')
 namespace=dict(fn.__globals__,crypto=crypto,public_names=public_names,reviewed_archive_limit=archive_limit)
 whole=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__);whole.__kwdefaults__=fn.__kwdefaults__
 return whole(spec,root,key,inspector)

def deny(*args,**kwargs):raise ValueError('REPORT232_ECONOMIC_OR_REVIEW_CALLBACK_FORBIDDEN')

@contextmanager
def worker_context(module,spec,*,mode,out,request):
 from full_system_core import hosted
 hosted();require_request(request,spec);need(mode=='preflight','REPORT232_ONLY_READONLY_PREFLIGHT_NO_FINANCIAL_OR_REVIEW_WORKER')
 actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(Path(module.__file__).read_bytes()).body
  if isinstance(n,ast.FunctionDef) and n.name in fact()['original4_AST']}
 need(actual==fact()['original4_AST'],'REPORT232_ALL_FOUR_MATURE_WORKER_BODIES_UNCHANGED')
 from system_campaign_registry_extension import RegistryExtension
 from system_campaign_bounded_sensor_input import InputCodec
 from system_campaign_abmd_bounded_hydration import hydrate
 from system_campaign_abmd_bounded_catalog import evidence
 old=partial.retained_models,partial.model_context,module.economic,module.review
 def models(root,current,target_spec):
  validate_target(target_spec)
  need(current['sha256']==OUTER and current['repairs']==target_spec['repairs'],'REPORT232_ONLY_ACTUAL2156_FULL15_MODEL_CONTEXT')
  return runtime.models.full(root,current)['full_inputs']==15
 @contextmanager
 def codec(root,current,target_spec):
  models(root,current,target_spec);value=runtime.initial.catalog();native,_=hydrate(value,Path(out)/'report232-original-ABMD-source.json')
  with InputCodec(value['event'],evidence(value),native):yield
 partial.retained_models,partial.model_context=models,codec
 module.economic=module.review=deny
 try:
  with RegistryExtension():yield
 finally:partial.retained_models,partial.model_context,module.economic,module.review=old

def bind_dispatch(original):
 @contextmanager
 def entry(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if request.get(FIELD):
   with worker_context(module,spec,mode=mode,out=out,request=request):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return entry

def bind_launch(original,module):
 def launch(args):
  request=json.loads(Path(args.request).read_bytes())
  if not request.get(FIELD):return original(args)
  launcher_guard();need(args.arm=='P06' and not retired(),'REPORT232_ONLY_UNCOMPLETED_P06_REPORTING_REQUEST')
  require_request(request,target());old=module.admit_partial
  module.admit_partial=lambda spec,*a,**k:admit(spec,*a,**k) if applies(spec) else old(spec,*a,**k)
  try:return original(args)
  finally:module.admit_partial=old
 return launch

def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry)
 module.expected_request=bind_expected_request(module.expected_request,module)
 module.launch=bind_launch(module.launch,module)
