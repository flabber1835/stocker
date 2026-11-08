"""Qualified1426/972 route through unchanged canonical and transport workers."""
import ast,json
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_ordinary28_runtime as runtime
import system_campaign_p07_request238_parent as parent_transport
import system_campaign_p07_KDNY_entry as previous
retained,resources,history,data=runtime.retained,runtime.resources,runtime.history,runtime.data
HERE=Path(__file__).parent
FIELD='selected_p07_ordinary28_retained_cash_batch'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
PROFILE='P07-ordinary28-whole-profile-qualification.json'

def source_names(*,profile=True):
 names=set((Path(__file__).name,*runtime.source_names(),*previous.source_names(profile=False),*parent_transport.source_names(),
  'P07-ordinary28-source-history-resources-DATA-qualification.json','P07-ordinary28-model-runtime-DATA-qualification.json'))
 if profile:names.add(PROFILE)
 return tuple(sorted(names))

def qualification():
 raw=(HERE/PROFILE).read_bytes();q=json.loads(raw)
 need(q['passed']is q['financial_profile_ready']is True and q['root_admission_sha256']==data.ROOT
  and q['financial_authority']is q['local_canonical_runtime_executed']is q['actual_neutral28_known']is False
  and q['actual_hosted_preparation_and_shared_constructor_required']is True
  and set(q['files'])==set(source_names(profile=False))|{'system_campaign_financial_resume.py'},
  'ORDINARY28_ENTRY_COMPLETE_CLOSED_PROFILE_AND_REQUIRED_HOSTED_GATES')
 for n,p in q['files'].items():need(resources.pin((HERE/n).read_bytes())==p,'ORDINARY28_ENTRY_EXACT_PROFILE_SOURCE:'+n)
 return sha(raw)

def declaration(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);need(retained.selected(spec),'ORDINARY28_ENTRY_ONLY_GENUINE1426_ROOT')
 parent_transport.validated(spec);resources.fact();data.catalog()
 return dict(schema='research.P07-ordinary28-financial-declaration/1',root_admission_sha256=data.ROOT,parent_outer_sha256=spec['outer_sha256'],
  parent_days=1426,parent_inputs=27,required_neutral_inputs=28,retained_proofs=972,raw_old_proofs=987,excluded_diagnostic_proofs=15,
  inherited_ordinary_terms=23,new_ordinary_terms=12,ordinary_terms=35,BWA_model_preserved=True,
  inherited_additional_model=spec['retained_additional_sensor'],inherited_ABMD_model=spec['retained_abmd'],KDNY_model_preserved=True,
  original_mixed_point_interval_growth_preserved=True,profile_sha256=qualification(),actual_new_constructor_required=True,
  actual_neutral28_known=False,owned_right_settlement_authorized=False,financial_source_changed=False)

def require_request(request,spec):
 need(retained.selected(spec) and request['execution_mode']==MODE and request['financial_resume_authorized']is True
  and request['readonly_partial_review']is request['readonly_source_witnesses']is False and 'P07'in request['arms']
  and len(request['arms'])==len(set(request['arms'])) and type(request['maximum_parallel_financial_workers'])is int
  and request['maximum_parallel_financial_workers']==len(request['arms']) and request['maximum_parallel_readonly_workers']==0
  and request.get(FIELD)=={'P07':declaration(spec)} and request['admitted_checkpoints']['P07']==spec['outer_sha256']
  and all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),
  'ORDINARY28_ENTRY_EXACT_CURRENT_FINANCIAL_REQUEST_AND_ALL_SOURCE_PINS')
 return True

def validate_metadata(spec):
 retained.phase(spec);v=resources.fact()
 def contract(cp,target):
  need(target==spec and cp==dict(sha256=spec['outer_sha256'],completed=1426,source_cursor='2023-08-31',base=spec['base']),
   'ORDINARY28_ENTRY_EXISTING_ADMISSION_METADATA_ONLY')
  need(len(v['controller_sources'])==6 and all(cp['base']['sources'][n]==h for n,h in v['controller_sources'].items())
   and sha((HERE/'system_campaign_financial_branches.py').read_bytes())==runtime.legacy.BRANCH_SHA,
   'ORDINARY28_ENTRY_ALL_SIX_CONTROLLER_AND_ORIGINAL_B19_SOURCE_IDENTITIES')
  return v['controller_sources']
 phase=dict(retained.phase(spec),completed=1426,source_cursor='2023-08-31')
 def point(target):
  need(target==spec and spec['base']['sources']['sentinel/controller/median5.py']==retained.prior_growth.WITNESS_SHA,
   'ORDINARY28_ENTRY_ORIGINAL_PHYSICAL_POINT_WITNESS');return True
 scope=dict(vars(runtime.legacy),unchanged_phase=lambda target:False,validate_admission_metadata=None,retained_contract=contract,retained_phase=lambda target:phase,point_return_phase=point)
 exec(compile(ast.Module(body=[previous.metadata_adapter.metadata_tree(Path(runtime.legacy.__file__).read_bytes())],type_ignores=[]),'<whole-original-admission-metadata-genuine1426-and972>','exec'),scope)
 return scope['validate_retained_admission_metadata'](spec)

def add_sources(value):
 for n in source_names():
  pin=sha((HERE/n).read_bytes());need(n not in value['sources'] or value['sources'][n]==pin,'ORDINARY28_ENTRY_NO_REPLACED_SOURCE_PIN:'+n);value['sources'][n]=pin
 return value

def bind_expected(original,module):
 def expected():
  active=module.EXECUTION_MODE==MODE and 'P07'in module.SELECTED_ARMS
  from system_campaign_financial_partial import root_spec
  spec=root_spec('P07') if active else None
  if active and retained.selected(spec):
   declared=declaration(spec);validate_metadata(spec)
   import system_campaign_bounded_lifecycle_dispatch as bounded
   old=runtime.legacy.validate_retained_admission_metadata,bounded.expected_request,runtime.legacy.own_policy_phase
   runtime.legacy.validate_retained_admission_metadata=lambda target:validate_metadata(target) if retained.selected(target) else old[0](target)
   bounded.expected_request=lambda base,*,execution_mode,selected_arms:old[1](base,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P07'))
   runtime.legacy.own_policy_phase=lambda target:None if retained.selected(target) else old[2](target)
   try:value=original()
   finally:runtime.legacy.validate_retained_admission_metadata,bounded.expected_request,runtime.legacy.own_policy_phase=old
   need(FIELD not in value,'ORDINARY28_ENTRY_NO_REPLACED_DECLARATION');value[FIELD]={'P07':declared};value['arm_inputs']['P07']['new_factual_overlay']=True
   from system_campaign_preflight_export import FIELD as export_field,POLICY
   value[export_field]=POLICY;add_sources(value);require_request(value,spec);return value
  value=original();need(FIELD not in value,'ORDINARY28_ENTRY_NO_REPLACED_INACTIVE_DECLARATION');value[FIELD]={};return add_sources(value)
 return expected

@contextmanager
def transport_context(spec,request):
 fn=previous.transport_context.__wrapped__
 bound=FunctionType(fn.__code__,dict(fn.__globals__,parent_transport=parent_transport,require_request=require_request),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 with contextmanager(bound)(spec,request):yield

def verify_prior_data(root,parent,out,spec):
 retained.seed_reader()(root,parent,spec);return resources.closure(lambda n:(Path(root)/n).read_bytes())

@contextmanager
def context(module,spec,*,mode,out,request,evidence=None):
 from full_system_core import hosted
 hosted();require_request(request,spec);need(mode in ('preflight','economic','review'),'ORDINARY28_ENTRY_EXPLICIT_HOSTED_MODE')
 import system_campaign_financial_partial as partial
 import system_campaign_financial_additional_sensor as additional
 import system_campaign_ordinary_augmentation_router as router
 from system_campaign_registry_extension import RegistryExtension
 saved=[]
 def patch(owner,name,value):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
 old_models,old_context=partial.retained_models,partial.model_context;old_implementation=router.implementation
 def implementation(root,current,target):
  if not retained.selected(target):return old_implementation(root,current,target)
  return SimpleNamespace(preserve=verify_prior_data,retained_models=lambda where,cp,scope:history.full(where,cp))
 @contextmanager
 def models(root,current,target):
  if not retained.selected(target):
   with old_context(root,current,target):yield
  else:
   with retained.codecs(root,current,target,out):yield
 old_phase,old_selected=additional.phase,additional.selected_declaration
 patch(additional,'phase',lambda target:None if retained.selected(target) else old_phase(target))
 patch(additional,'selected_declaration',lambda root,cp,target:None if retained.selected(target) else old_selected(root,cp,target))
 patch(partial,'retained_models',lambda root,cp,target:history.full(root,cp) if retained.selected(target) else old_models(root,cp,target))
 patch(partial,'model_context',models);patch(router,'implementation',implementation)
 old_run,old_review,old_uncertainty=runtime.legacy.run,runtime.legacy.review,runtime.legacy.uncertainty_phase;old_policy=runtime.legacy.own_policy_phase
 patch(runtime.legacy,'own_policy_phase',lambda target:None if retained.selected(target) else old_policy(target))
 patch(runtime.legacy,'uncertainty_phase',lambda target:retained.selected(target) or old_uncertainty(target))
 patch(runtime.legacy,'run',lambda *args,**kwargs:runtime.run(*args,**kwargs) if retained.selected(kwargs.get('spec')) else old_run(*args,**kwargs))
 patch(runtime.legacy,'review',lambda *args,**kwargs:runtime.review(*args,**kwargs) if retained.selected(kwargs.get('spec')) else old_review(*args,**kwargs))
 old_overlay=module.factual_overlay_needed;patch(module,'factual_overlay_needed',lambda target:True if retained.selected(target) else old_overlay(target))
 patch(module,'prepare_composite_before_finance',lambda parent,folder,target:runtime.prepare(parent,folder,target,Path('/old')))
 patch(module,'require_composite_preparation',runtime.require_preparation)
 whole=previous.mature_review(module)
 def review(root,folder,target):
  current=runtime.strict_json((Path(root)/'book/checkpoint.json.gz').read_bytes())
  with models(root,current,target):result=whole(root,folder,target)
  if current['completed']>target['measured_closes']:
   reporting=dict(arm='P07',archive_format=partial.FORMAT,base=current['base'],measured_closes=current['completed'],selected_session=current['source_cursor'],original_parent_index_sha256=sha((HERE/partial.ORIGINALS).read_bytes()),monthly_seed_root_admission_sha256=data.ROOT)
   partial.monthly_reproduction(root,folder,reporting,current)
  return result
 patch(module,'review',review)
 try:
  with RegistryExtension(),transport_context(spec,request):yield
 finally:
  for owner,name,value in reversed(saved):setattr(owner,name,value)

def bind_dispatch(original):
 @contextmanager
 def dispatch(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if retained.selected(spec) and request.get(FIELD):
   with context(module,spec,mode=mode,out=out or Path('/out'),request=request,evidence=evidence):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return dispatch

def bind_launch(original):
 def launch(args):
  request=json.loads(Path(args.request).read_bytes())
  if args.arm=='P07' and request.get(FIELD):
   spec=resources.spec();require_request(request,spec)
   with transport_context(spec,request):return original(args)
  return original(args)
 return launch

def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry);module.expected_request=bind_expected(module.expected_request,module);module.launch=bind_launch(module.launch)
