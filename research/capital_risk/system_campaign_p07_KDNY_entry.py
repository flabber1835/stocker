"""One explicitly qualified P07 restart around unchanged mature worker bodies."""
import ast,json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_KDNY_runtime as runtime
import system_campaign_p07_request231_parent as parent_transport
import system_campaign_p07_vivo_profile as metadata_adapter
retained,resources,history,source=runtime.retained,runtime.resources,runtime.history,runtime.source
HERE=Path(__file__).parent
FIELD='selected_p07_KDNY_second_bounded_event'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
PROFILE='P07-KDNY-full27-whole-profile-qualification.json'


def source_names(*,profile=True):
 names=(Path(__file__).name,'system_campaign_p07_KDNY_runtime.py','system_campaign_p07_KDNY_retained.py',
  'system_campaign_p07_KDNY_history.py','system_campaign_p07_KDNY_resources.py','system_campaign_p07_KDNY_certificate.py',
  'system_campaign_p07_KDNY_source.py','system_campaign_p07_KDNY_preparation.py',resources.FACT,source.CATALOG,
  'P07-KDNY-source-packet-DATA-qualification.json','P07-KDNY-retained949-DATA-qualification.json',
  'P07-KDNY-runtime-DATA-qualification.json','P07-request231-parent-transport-DATA-qualification.json',
  'system_campaign_bounded_sensor_seed_binding.py','system_campaign_second_bounded_codec.py','system_campaign_second_bounded_factory.py',
  'system_campaign_full_history_successor.py','system_campaign_dependencies.py','system_campaign_p03_thor_qualification_reuse.py',
  'system_campaign_postclose_distribution_models.py','system_campaign_postclose_distribution_restart.py',
  'system_campaign_postclose_distribution_runtime.py','system_campaign_p07_vivo_certificate.py',
  'P07-admitted-ABMD-continuation-factory-DATA-SOURCE.txt',*parent_transport.source_names())
 return tuple(sorted(set((*names,PROFILE) if profile else names)))


def qualification():
 raw=(HERE/PROFILE).read_bytes();q=json.loads(raw)
 need(q['passed'] is True and q['root_admission_sha256']==source.ROOT
  and q['financial_authority'] is q['local_canonical_runtime_executed'] is q['actual_neutral27_known'] is False
  and q['actual_hosted_preparation_and_shared_constructor_required'] is True
  and set(q['files'])==set(source_names(profile=False))|{'system_campaign_financial_resume.py'},
  'KDNY_ENTRY_COMPLETE_CLOSED_PROFILE_AND_MANDATORY_HOSTED_GATES')
 for name,pin in q['files'].items():need(resources.pin((HERE/name).read_bytes())==pin,'KDNY_ENTRY_EXACT_WHOLE_PROFILE_SOURCE:'+name)
 return sha(raw)


def declaration(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);need(retained.selected(spec),'KDNY_ENTRY_ONLY_EXACT_CURRENT1403_ROOT')
 parent_transport.validated(spec);source.catalog();resources.fact()
 return dict(schema='research.P07-KDNY-second-bounded-financial-declaration/1',root_admission_sha256=source.ROOT,
  parent_outer_sha256=spec['outer_sha256'],parent_days=1403,parent_inputs=26,required_neutral_inputs=27,
  retained_proofs=949,raw_old_proofs=956,excluded_diagnostic_proofs=7,ordinary_terms=23,
  inherited_additional_model=spec['retained_additional_sensor'],inherited_ABMD_model=spec['retained_abmd'],
  BWA_model_preserved=True,original_mixed_point_interval_growth_preserved=True,
  profile_sha256=qualification(),actual_new_constructor_required=True,actual_neutral27_known=False,
  owned_right_settlement_authorized=False,financial_source_changed=False)


def require_request(request,spec):
 need(retained.selected(spec) and request['execution_mode']==MODE and request['financial_resume_authorized'] is True
  and request['readonly_partial_review'] is request['readonly_source_witnesses'] is False and request['arms']==['P07']
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==1
  and request['maximum_parallel_readonly_workers']==0 and request.get(FIELD)=={'P07':declaration(spec)}
  and request['admitted_checkpoints']['P07']==spec['outer_sha256']
  and all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),
  'KDNY_ENTRY_EXACT_QUALIFIED_FINANCIAL_REQUEST_AND_ALL_SOURCE_PINS')
 return True


def validate_metadata(spec):
 retained.phase(spec);value=resources.fact()
 def contract(cp,target):
  need(target==spec and cp==dict(sha256=spec['outer_sha256'],completed=1403,source_cursor='2023-07-31',base=spec['base']),
   'KDNY_ENTRY_EXACT_EXISTING_ADMISSION_METADATA_ONLY')
  need(len(value['controller_sources'])==6 and all(cp['base']['sources'].get(n)==h for n,h in value['controller_sources'].items())
   and sha((HERE/'system_campaign_financial_branches.py').read_bytes())==runtime.legacy.BRANCH_SHA,
   'KDNY_ENTRY_ALL_SIX_CONTROLLER_AND_ORIGINAL_B19_IDENTITIES')
  return value['controller_sources']
 phase=dict(retained.phase(spec),completed=1403,source_cursor='2023-07-31')
 def point(target):
  need(target==spec and spec['base']['sources']['sentinel/controller/median5.py']==retained.previous.saved.retained.WITNESS_SHA,
   'KDNY_ENTRY_ORIGINAL_POINT_WITNESS_SOURCE');return True
 scope=dict(vars(runtime.legacy),unchanged_phase=lambda target:False,validate_admission_metadata=None,
  retained_contract=contract,retained_phase=lambda target:phase,point_return_phase=point)
 exec(compile(ast.Module(body=[metadata_adapter.metadata_tree(Path(runtime.legacy.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-admission-metadata-exact1403-and949-proof-source>','exec'),scope)
 return scope['validate_retained_admission_metadata'](spec)


def bind_expected(original,module):
 def expected():
  if module.EXECUTION_MODE!=MODE or list(module.SELECTED_ARMS)!=['P07']:return original()
  from system_campaign_financial_partial import root_spec
  spec=root_spec('P07')
  if not retained.selected(spec):return original()
  declared=declaration(spec)
  import system_campaign_bounded_lifecycle_dispatch as bounded
  previous=runtime.legacy.validate_retained_admission_metadata,bounded.expected_request
  runtime.legacy.validate_retained_admission_metadata=lambda target:validate_metadata(target) if retained.selected(target) else previous[0](target)
  def old_profiles(base,*,execution_mode,selected_arms):
   return previous[1](base,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P07'))
  bounded.expected_request=old_profiles
  try:value=original()
  finally:runtime.legacy.validate_retained_admission_metadata,bounded.expected_request=previous
  need(FIELD not in value,'KDNY_ENTRY_NO_REPLACED_NEW_PROFILE_DECLARATION');value[FIELD]={'P07':declared}
  value['arm_inputs']['P07']['new_factual_overlay']=True
  value['selected_abmd_bounded_inputs']={'P07':retained.original_lifecycle.declaration(spec)}
  from system_campaign_preflight_export import FIELD as export_field,POLICY
  value[export_field]=POLICY
  for name in source_names():
   pin=sha((HERE/name).read_bytes());need(name not in value['sources'] or value['sources'][name]==pin,'KDNY_ENTRY_NO_SOURCE_PIN_REPLACEMENT:'+name);value['sources'][name]=pin
  require_request(value,spec);return value
 return expected


@contextmanager
def transport_context(spec,request):
 import system_campaign_financial_requalified_parent as requalified
 previous=requalified.applies,requalified.admit,requalified.accounting_review
 requalified.applies=lambda target:parent_transport.applies(target) or previous[0](target)
 requalified.admit=lambda target,root,key,inspector:parent_transport.admit(target,root,key,inspector,request=request,authorize=require_request) if parent_transport.applies(target) else previous[1](target,root,key,inspector)
 requalified.accounting_review=lambda target:parent_transport.accounting_review(target) if parent_transport.applies(target) else previous[2](target)
 try:yield
 finally:requalified.applies,requalified.admit,requalified.accounting_review=previous


def mature_review(module):
 names=('preflight','economic','review','launch')
 raw=Path(module.__file__).read_bytes();actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name in names}
 import system_campaign_p03_STML_resources as original
 need(actual==original.fact()['original4_AST'],'KDNY_ENTRY_ALL_FOUR_MATURE_WORKER_BODIES_UNCHANGED')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review'];scope=dict(vars(module))
 exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-mature-review-KDNY-installed-inputs>','exec'),scope);return scope['review']


@contextmanager
def context(module,spec,*,mode,out,request,evidence=None):
 from full_system_core import hosted
 hosted();require_request(request,spec);need(mode in ('preflight','economic','review'),'KDNY_ENTRY_EXPLICIT_HOSTED_WORKER_MODE')
 import system_campaign_financial_partial as partial
 import system_campaign_financial_additional_sensor as additional
 import system_campaign_ordinary_augmentation_router as router
 from system_campaign_registry_extension import RegistryExtension
 saved=[]
 def patch(owner,name,value):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
 old_phase,old_selected=additional.phase,additional.selected_declaration
 old_models,old_context=partial.retained_models,partial.model_context
 old_implementation=router.implementation
 def implementation(root,current,target):
  if not retained.selected(target):return old_implementation(root,current,target)
  def preserve(where,parent,folder,selected):
   baseline=retained.seed_reader()(where,parent,selected)
   return resources.preserve(where,folder,parent,baseline[1],baseline[2])
  return SimpleNamespace(preserve=preserve,retained_models=lambda where,parent,selected:history.full(where,parent))
 @contextmanager
 def models(root,current,target):
  if not retained.selected(target):
   with old_context(root,current,target):yield
  else:
   with retained.codecs(root,current,target,out):yield
 old_run,old_review,old_uncertainty=runtime.legacy.run,runtime.legacy.review,runtime.legacy.uncertainty_phase
 old_overlay=module.factual_overlay_needed
 patch(additional,'phase',lambda target:None if retained.selected(target) else old_phase(target))
 patch(additional,'selected_declaration',lambda where,current,target:None if retained.selected(target) else old_selected(where,current,target))
 patch(partial,'retained_models',lambda root,current,target:history.full(root,current) if retained.selected(target) else old_models(root,current,target))
 patch(partial,'model_context',models);patch(router,'implementation',implementation)
 patch(runtime.legacy,'uncertainty_phase',lambda target:retained.selected(target) or old_uncertainty(target))
 patch(runtime.legacy,'run',lambda *a,**k:runtime.run(*a,**k) if retained.selected(k.get('spec')) else old_run(*a,**k))
 patch(runtime.legacy,'review',lambda *a,**k:runtime.review(*a,**k) if retained.selected(k.get('spec')) else old_review(*a,**k))
 patch(module,'factual_overlay_needed',lambda target:True if retained.selected(target) else old_overlay(target))
 patch(module,'prepare_composite_before_finance',lambda parent,folder,target:runtime.prepare(parent,folder,target,Path('/old')))
 patch(module,'require_composite_preparation',runtime.require_preparation)
 whole=mature_review(module)
 def review(where,folder,target):
  current=strict_json((Path(where)/'book/checkpoint.json.gz').read_bytes())
  with models(where,current,target):result=whole(where,folder,target)
  if current['completed']>target['measured_closes']:
   reporting=dict(arm='P07',archive_format=partial.FORMAT,base=current['base'],measured_closes=current['completed'],
    selected_session=current['source_cursor'],original_parent_index_sha256=sha((HERE/partial.ORIGINALS).read_bytes()),monthly_seed_root_admission_sha256=source.ROOT)
   partial.monthly_reproduction(where,folder,reporting,current)
  return result
 # Keep the canonical core/reporting reader in the actual full input context.
 from system_campaign_bounded_sensor_origin_v2 import strict_json
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
   from system_campaign_financial_partial import root_spec
   spec=root_spec('P07');require_request(request,spec)
   with transport_context(spec,request):return original(args)
  return original(args)
 return launch


def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry);module.expected_request=bind_expected(module.expected_request,module);module.launch=bind_launch(module.launch)
