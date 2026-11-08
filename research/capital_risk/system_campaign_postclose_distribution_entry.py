"""Explicit qualified P07 launch using original transport and financial workers."""
import ast,json
from contextlib import contextmanager
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_postclose_distribution_restart as runtime
import system_campaign_p07_vivo_profile as prior_profile
HERE=Path(__file__).parent
CANARY=runtime.resources.PREFIX+'/dependency-canary.json'
PREPARATION=runtime.resources.PREFIX+'/zero-financial-preparation.json'

def source_names(*,profile=True):
 names=('system_campaign_postclose_distribution_entry.py','system_campaign_postclose_distribution_restart.py',
  'system_campaign_postclose_distribution_models.py','system_campaign_postclose_distribution_resources.py',
  'system_campaign_postclose_distribution_runtime.py','system_campaign_postclose_distribution_history.py',
  'system_campaign_postclose_distribution_codec.py','system_campaign_postclose_distribution_input.py',
  'system_campaign_postclose_distribution_review.py','system_campaign_p07_saved_proofs.py',
  'P07-BWA-postclose-source-catalog.json','P07-BWA-source-DATA-review.json','P07-BWA-source-DATA-qualification.json',
  'P07-BWA-retained929-source.json','P07-BWA-saved-restart-DATA-qualification.json',
  'P07-BWA-typed-input-DATA-qualification.json','P07-BWA-runtime-DATA-qualification.json',
  'P07-BWA-saved-resources.json','P07-BWA-saved-resources-DATA-qualification.json','P07-BWA-model-bindings-DATA-qualification.json',
  'P07-admitted-ABMD-continuation-factory-DATA-SOURCE.txt','system_campaign_full_history_successor.py','system_campaign_dependencies.py')
 return (*names,runtime.PROFILE) if profile else names

def require_sources(request,spec):
 runtime.require_request(request,spec)
 need(all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),
  'POSTCLOSE_ENTRY_ALL_COMPLETE_PROFILE_SOURCE_PINS')
 return True

def preparation(parent,spec,root):
 root=Path(root);names=runtime.history.paths(spec);member=lambda n:(root/n).read_bytes()
 runtime.models.document(parent,member)
 canary=json.loads(member(CANARY));closure=runtime.resources.closure(lambda n:(root/n).read_bytes(),spec,
  [runtime.saved.metadata(spec)['historical_event_resolution']])
 need(canary==dict(passed=True,dependency_closure=closure,actual_copy_verified=True,owned_copy_removed=True,financial_sessions_advanced=0),
  'POSTCLOSE_ENTRY_ACTUAL_COMPLETE_COPY_AND_REMOVAL_CANARY')
 files=[names[k] for k in ('PARENT','OVERLAY','PAYLOAD','QUALIFICATION','RETAINED_QUALIFICATION')]
 files.extend((CANARY,runtime.resources.RECEIPT))
 return dict(schema='research.P07-postclose-zero-financial-preparation/1',passed=True,
  root_admission_sha256=spec['root_admission_sha256'],parent_outer_sha256=parent['sha256'],
  earliest_affected_session='2023-07-05',parent_unchanged=True,checkpoint_adopted=False,financial_sessions_advanced=0,
  files={n:dict(bytes=len(member(n)),sha256=sha(member(n))) for n in files})

def preflight(parent,out,spec,old,request):
 from full_system_core import hosted
 hosted();require_sources(request,spec)
 from research.pooled_vacancy_funding import backtest,runtime as financial
 out,old=Path(out),Path(old);names=runtime.history.paths(spec);before=runtime.saved.encoded(parent)
 forbidden=[out/'book/checkpoint.json.gz',out/names['NEUTRAL']]
 need(not any(p.exists() for p in forbidden),'POSTCLOSE_ENTRY_PREFLIGHT_HAS_NO_FINANCIAL_OR_NEW_NEUTRAL_BOOK')
 def refuse(*args,**kwargs):raise ValueError('POSTCLOSE_ENTRY_PREFLIGHT_FINANCIAL_ADVANCE_FORBIDDEN')
 previous=backtest.main,financial.advance;backtest.main=financial.advance=refuse
 try:
  baseline=runtime.saved.seed_reader()(old,parent,spec);resolutions=[runtime.saved.metadata(spec)['historical_event_resolution']]
  result=runtime.resources.canary(old,out,parent,spec,resolutions=resolutions)
  exact(out/CANARY,runtime.saved.encoded(result))
  runtime.resources.preserve(old,out,parent,spec,rows=baseline[1],resolutions=resolutions)
  runtime.inputs.prepare(parent,out,old=old)
 finally:backtest.main,financial.advance=previous
 need(runtime.saved.encoded(parent)==before and not any(p.exists() for p in forbidden),
  'POSTCLOSE_ENTRY_PREFLIGHT_ZERO_FINANCIAL_STATE_OR_ADOPTION')
 result=preparation(parent,spec,out);exact(out/PREPARATION,runtime.saved.encoded(result));return result

def require_preflight(parent,spec,proof,root):
 expected=preparation(parent,spec,root)
 need(proof['composite_preparation']==expected==json.loads((Path(root)/PREPARATION).read_bytes()),
  'POSTCLOSE_ENTRY_EXACT_STOPPED_PREPARATION_BEFORE_FINANCE')
 return True

def validate_retained_metadata(spec):
 runtime.saved.metadata(spec);need(runtime.candidate(spec),'POSTCLOSE_ENTRY_ONLY_REAL1383_ROOT_METADATA')
 def contract(cp,target):
  need(target==spec and cp==dict(sha256=spec['outer_sha256'],completed=1383,source_cursor='2023-06-30',base=spec['base']),
   'POSTCLOSE_ENTRY_EXACT_ORIGINAL_METADATA_FIELDS')
  hashes=runtime.saved.metadata(spec)['controller_sources']
  need(len(hashes)==6 and all(cp['base']['sources'].get(n)==h for n,h in hashes.items())
   and sha((HERE/'system_campaign_financial_branches.py').read_bytes())==runtime.legacy.BRANCH_SHA,
   'POSTCLOSE_ENTRY_ALL_SIX_ORIGINAL_CONTROLLER_AND_B19_IDENTITIES')
  return hashes
 phase=dict(runtime.saved.phase(spec),completed=1383,source_cursor='2023-06-30')
 def point(target):
  need(target==spec and spec['base']['sources']['sentinel/controller/median5.py']==runtime.saved.retained.WITNESS_SHA,
   'POSTCLOSE_ENTRY_EXACT_UNCHANGED_POINT_WITNESS')
  return True
 scope=dict(vars(runtime.legacy),unchanged_phase=lambda target:False,
  validate_admission_metadata=None,retained_contract=contract,retained_phase=lambda target:phase,point_return_phase=point)
 tree=prior_profile.metadata_tree(Path(runtime.legacy.__file__).read_bytes())
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-original-retained-admission-exact1383-929-source-bindings>','exec'),scope)
 return scope['validate_retained_admission_metadata'](spec)

@contextmanager
def context(module,spec,*,mode,old,out,request,evidence=None):
 from full_system_core import hosted
 hosted();require_sources(request,spec)
 need(mode in ('preflight','economic','review'),'POSTCLOSE_ENTRY_EXPLICIT_HOSTED_PROCESS_MODE')
 import system_campaign_financial_additional_sensor as additional
 import system_campaign_ordinary_augmentation_router as router
 life=runtime.models.lifecycle()
 previous=(additional.phase,router.implementation,runtime.legacy.uncertainty_phase)
 saved_module={n:getattr(module,n) for n in ('factual_overlay_needed','prepare_composite_before_finance','require_composite_preparation')}
 additional.phase=lambda target:life.phase(target) if runtime.candidate(target) else previous[0](target)
 router.implementation=lambda root,current,target:runtime.api(root,current,target,request=request) if runtime.candidate(target) else previous[1](root,current,target)
 runtime.legacy.uncertainty_phase=lambda target:runtime.candidate(target) or previous[2](target)
 module.factual_overlay_needed=lambda target:True if runtime.candidate(target) else saved_module['factual_overlay_needed'](target)
 module.prepare_composite_before_finance=lambda parent,folder,target:preflight(parent,folder,target,old,request) if runtime.candidate(target) else saved_module['prepare_composite_before_finance'](parent,folder,target)
 module.require_composite_preparation=lambda parent,target,proof,folder:require_preflight(parent,target,proof,folder) if runtime.candidate(target) else saved_module['require_composite_preparation'](parent,target,proof,folder)
 try:yield
 finally:
  additional.phase,router.implementation,runtime.legacy.uncertainty_phase=previous
  for n,value in saved_module.items():setattr(module,n,value)

def bind_expected_request(original,module):
 def expected():
  if module.EXECUTION_MODE!=runtime.MODE or 'P07' not in module.SELECTED_ARMS:return original()
  from system_campaign_financial_partial import root_spec
  spec=root_spec('P07')
  if not runtime.candidate(spec):return original()
  import system_campaign_bounded_lifecycle_dispatch as bounded
  previous=runtime.legacy.validate_retained_admission_metadata,bounded.expected_request
  runtime.legacy.validate_retained_admission_metadata=lambda target:validate_retained_metadata(target) if runtime.candidate(target) else previous[0](target)
  def other_profiles(base,*,execution_mode,selected_arms):
   return previous[1](base,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P07'))
  bounded.expected_request=other_profiles
  try:result=original()
  finally:runtime.legacy.validate_retained_admission_metadata,bounded.expected_request=previous
  need(runtime.FIELD not in result,'POSTCLOSE_ENTRY_NO_REPLACED_PROFILE_DECLARATION')
  result[runtime.FIELD]={'P07':runtime.declaration(spec)}
  result['arm_inputs']['P07']['new_factual_overlay']=True
  from system_campaign_preflight_export import FIELD,POLICY
  result[FIELD]=POLICY
  for n in source_names():
   pin=sha((HERE/n).read_bytes())
   need(n not in result['sources'] or result['sources'][n]==pin,'POSTCLOSE_ENTRY_NO_SOURCE_PIN_REPLACEMENT:'+n)
   result['sources'][n]=pin
  require_sources(result,spec);return result
 return expected

def bind_dispatch(original):
 @contextmanager
 def entry(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if runtime.candidate(spec) and request.get(runtime.FIELD):
   with context(module,spec,mode=mode,old=Path('/old'),out=out or Path('/out'),request=request,evidence=evidence):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return entry

def bind_launch(original,module):
 def launch(args):
  request=json.loads(Path(args.request).read_bytes())
  if args.arm=='P07' and request.get(runtime.FIELD):
   from system_campaign_financial_partial import root_spec
   require_sources(request,root_spec('P07'))
  return original(args)
 return launch

def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry)
 module.expected_request=bind_expected_request(module.expected_request,module)
 module.launch=bind_launch(module.launch,module)
