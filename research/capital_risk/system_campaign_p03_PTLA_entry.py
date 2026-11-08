"""One explicit full20/174 P03 financial restart around original mature workers."""
import ast,json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p03_PTLA_runtime as runtime
import system_campaign_p03_PTLA_models as models
import system_campaign_p07_KDNY_entry as inactive_p07
import system_campaign_p07_vivo_profile as metadata_adapter
history,data,resources=runtime.history,runtime.data,runtime.resources
HERE=Path(__file__).parent
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
FIELD='selected_p03_PTLA_ordinary21'
PROFILE='P03-PTLA-full21-whole-profile-qualification.json'
RUNTIME_QUALIFICATION='P03-PTLA-runtime-DATA-qualification.json'


def selected(spec):return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')==data.ROOT


def source_names(*,profile=True):
 names={Path(__file__).name,Path(runtime.__file__).name,Path(models.__file__).name,
  'system_campaign_p03_PTLA_history.py','system_campaign_p03_PTLA_certificate.py','system_campaign_p03_PTLA_observers.py',
  'system_campaign_p03_PTLA_resources.py',resources.FACT,'P03-PTLA-source-retained174-DATA-qualification.json',
  'P03-PTLA-history-and-consumed-models-DATA-qualification.json',RUNTIME_QUALIFICATION,
  'system_campaign_bounded_sensor_seed_binding.py','system_campaign_second_bounded_codec.py','system_campaign_second_bounded_factory.py',
  'system_campaign_p03_STML_runtime.py','system_campaign_p03_thor_qualification_reuse.py',
  'system_campaign_p07_saved_proofs.py','system_campaign_postclose_distribution_codec.py',
  'system_campaign_postclose_distribution_entry.py','system_campaign_postclose_distribution_history.py',
  'system_campaign_postclose_distribution_input.py','system_campaign_postclose_distribution_resources.py',
  *history.api_module.source_names(),*inactive_p07.source_names()}
 if profile:names.add(PROFILE)
 return tuple(sorted(names))


def qualification():
 raw=(HERE/PROFILE).read_bytes();q=json.loads(raw)
 need(q['passed'] is True and q['root_admission_sha256']==data.ROOT
  and q['financial_authority'] is q['local_canonical_runtime_executed'] is q['actual_neutral21_known'] is False
  and q['actual_hosted_preparation_and_constructor_required'] is True
  and set(q['files'])==set(source_names(profile=False))|{'system_campaign_financial_resume.py'},
  'PTLA_ENTRY_COMPLETE_CLOSED_PROFILE_AND_REQUIRED_HOSTED_GATES')
 for name,pin in q['files'].items():need(resources.pin((HERE/name).read_bytes())==pin,'PTLA_ENTRY_EXACT_WHOLE_PROFILE_SOURCE:'+name)
 return sha(raw)


def declaration(spec):
 runtime.phase(spec);value=resources.fact()
 need(selected(spec) and len(spec['repairs'])==20 and value['committed_proof']['rows']==174,'PTLA_ENTRY_EXACT_ADMITTED20_AND174_RECORDS')
 return dict(schema='research.P03-PTLA-ordinary21-financial-declaration/1',root_admission_sha256=data.ROOT,
  parent_outer_sha256=spec['outer_sha256'],parent_days=628,parent_inputs=20,required_neutral_inputs=21,
  retained_proofs=174,raw_old_proofs=174,excluded_tail_proofs=0,ordinary_terms=35,
  old_DOVA_and_STML_models_preserved=True,original_full_interval_growth_preserved=True,
  profile_sha256=qualification(),actual_neutral21_known=False,actual_hosted_constructor_required=True,
  financial_source_changed=False,future_ownership_inferred=False)


def require_request(request,spec):
 need(selected(spec) and request['execution_mode']==MODE and request['financial_resume_authorized'] is True
  and request['readonly_partial_review'] is request['readonly_source_witnesses'] is False and request['arms']==['P03']
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==1
  and request['maximum_parallel_readonly_workers']==0 and request.get(FIELD)=={'P03':declaration(spec)}
  and request['admitted_checkpoints']['P03']==spec['outer_sha256']
  and all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),
  'PTLA_ENTRY_EXACT_NEW_FINANCIAL_REQUEST_AND_ALL_SOURCE_PINS')
 return True


def validate_metadata(spec):
 runtime.phase(spec);value=resources.fact()
 def contract(cp,target):
  need(target==spec and cp==dict(sha256=spec['outer_sha256'],completed=628,source_cursor='2020-06-30',base=spec['base']),
   'PTLA_ENTRY_EXISTING_ADMITTED_METADATA_ONLY')
  need(len(value['controller_sources'])==6 and all(cp['base']['sources'].get(n)==h for n,h in value['controller_sources'].items())
   and sha((HERE/'system_campaign_financial_branches.py').read_bytes())==runtime.legacy.BRANCH_SHA,
   'PTLA_ENTRY_ALL_SIX_CONTROLLER_AND_ORIGINAL_B19_SOURCE_IDENTITIES')
  return value['controller_sources']
 phase=dict(runtime.phase(spec),completed=628,source_cursor='2020-06-30')
 scope=dict(vars(runtime.legacy),unchanged_phase=lambda target:False,validate_admission_metadata=None,
  retained_contract=contract,retained_phase=lambda target:phase,point_return_phase=lambda target:False,
  own_retained_phase=lambda target:None if selected(target) else runtime.legacy.own_retained_phase(target))
 exec(compile(ast.Module(body=[metadata_adapter.metadata_tree(Path(runtime.legacy.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-admission-metadata-current628-and174-interval>','exec'),scope)
 return scope['validate_retained_admission_metadata'](spec)


def add_sources(value):
 for name in source_names():
  pin=sha((HERE/name).read_bytes());need(name not in value['sources'] or value['sources'][name]==pin,'PTLA_ENTRY_NO_SOURCE_PIN_REPLACEMENT:'+name)
  value['sources'][name]=pin
 return value


def bind_expected(original,module):
 def expected():
  active=module.EXECUTION_MODE==MODE and list(module.SELECTED_ARMS)==['P03']
  from system_campaign_financial_partial import root_spec
  spec=root_spec('P03') if active else None
  if active and selected(spec):
   declared=declaration(spec);validate_metadata(spec)
   import system_campaign_bounded_lifecycle_dispatch as bounded
   old=runtime.legacy.validate_retained_admission_metadata,bounded.expected_request,runtime.legacy.own_policy_phase
   runtime.legacy.validate_retained_admission_metadata=lambda target:validate_metadata(target) if selected(target) else old[0](target)
   bounded.expected_request=lambda base,*,execution_mode,selected_arms:old[1](base,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P03'))
   runtime.legacy.own_policy_phase=lambda target:None if selected(target) else old[2](target)
   try:value=original()
   finally:runtime.legacy.validate_retained_admission_metadata,bounded.expected_request,runtime.legacy.own_policy_phase=old
   need(FIELD not in value,'PTLA_ENTRY_NO_REPLACED_NEW_FINANCIAL_DECLARATION');value[FIELD]={'P03':declared}
   value['arm_inputs']['P03']['new_factual_overlay']=True
   from system_campaign_preflight_export import FIELD as export_field,POLICY
   value[export_field]=POLICY
   add_sources(value);require_request(value,spec);return value
  value=original();need(FIELD not in value,'PTLA_ENTRY_NO_REPLACED_INACTIVE_DECLARATION');value[FIELD]={}
  return add_sources(value)
 return expected


def verify_prior_data(root,parent,out,spec):
 resources.parent_contract(parent,spec)
 return resources.closure(lambda n:(Path(root)/n).read_bytes())


def mature_review(module):
 expected=resources.original.fact()['original4_AST'];raw=Path(module.__file__).read_bytes()
 actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name in expected}
 need(actual==expected,'PTLA_ENTRY_ALL_FOUR_MATURE_WORKER_BODIES_UNCHANGED')
 fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review');scope=dict(vars(module))
 exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-mature-review-full21-codecs>','exec'),scope);return scope['review']


@contextmanager
def context(module,spec,*,mode,out,request):
 from full_system_core import hosted
 hosted();require_request(request,spec);need(mode in ('preflight','economic','review'),'PTLA_ENTRY_EXPLICIT_HOSTED_WORKER_MODE')
 import system_campaign_financial_partial as partial
 import system_campaign_financial_additional_sensor as additional
 import system_campaign_ordinary_augmentation_router as router
 from system_campaign_registry_extension import RegistryExtension
 saved=[]
 def patch(owner,name,value):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
 patch(history.previous.previous.origins,'load',history.origin_reader())
 old_models,old_context=partial.retained_models,partial.model_context
 old_implementation=router.implementation;old_phase,old_selected=additional.phase,additional.selected_declaration
 def implementation(root,current,target):
  if not selected(target):return old_implementation(root,current,target)
  return SimpleNamespace(preserve=verify_prior_data,retained_models=lambda where,cp,scope:history.full(where,cp))
 @contextmanager
 def model_context(root,current,target):
  if not selected(target):
   with old_context(root,current,target):yield
  else:
   with models.codecs(root,current,target,out,base_context=old_context):yield
 patch(additional,'phase',lambda target:None if selected(target) else old_phase(target))
 patch(additional,'selected_declaration',lambda root,cp,target:None if selected(target) else old_selected(root,cp,target))
 patch(partial,'retained_models',lambda root,cp,target:history.full(root,cp) if selected(target) else old_models(root,cp,target))
 patch(partial,'model_context',model_context);patch(router,'implementation',implementation)
 old_run,old_review,old_uncertainty=runtime.legacy.run,runtime.legacy.review,runtime.legacy.uncertainty_phase
 old_policy=runtime.legacy.own_policy_phase
 patch(runtime.legacy,'own_policy_phase',lambda target:None if selected(target) else old_policy(target))
 patch(runtime.legacy,'uncertainty_phase',lambda target:selected(target) or old_uncertainty(target))
 patch(runtime.legacy,'run',lambda *a,**k:runtime.run(*a,**k) if selected(k.get('spec')) else old_run(*a,**k))
 patch(runtime.legacy,'review',lambda *a,**k:runtime.review(*a,**k) if selected(k.get('spec')) else old_review(*a,**k))
 old_overlay=module.factual_overlay_needed
 patch(module,'factual_overlay_needed',lambda target:True if selected(target) else old_overlay(target))
 patch(module,'prepare_composite_before_finance',lambda parent,folder,target:runtime.prepare(parent,folder,target,Path('/old')))
 patch(module,'require_composite_preparation',runtime.require_preparation)
 whole=mature_review(module)
 def review(root,folder,target):
  current=runtime.strict_json((Path(root)/'book/checkpoint.json.gz').read_bytes())
  with model_context(root,current,target):result=whole(root,folder,target)
  if current['completed']>target['measured_closes']:
   reporting=dict(arm='P03',archive_format=partial.FORMAT,base=current['base'],measured_closes=current['completed'],
    selected_session=current['source_cursor'],original_parent_index_sha256=sha((HERE/partial.ORIGINALS).read_bytes()),monthly_seed_root_admission_sha256=data.ROOT)
   partial.monthly_reproduction(root,folder,reporting,current)
  return result
 patch(module,'review',review)
 try:
  with RegistryExtension():yield
 finally:
  for owner,name,value in reversed(saved):setattr(owner,name,value)


def bind_dispatch(original):
 @contextmanager
 def dispatch(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if selected(spec) and request.get(FIELD):
   with context(module,spec,mode=mode,out=out or Path('/out'),request=request):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return dispatch


def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry);module.expected_request=bind_expected(module.expected_request,module)
