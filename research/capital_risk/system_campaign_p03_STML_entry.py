"""Explicit P03 second-event request around the unchanged mature workers."""
import ast,json
from contextlib import contextmanager
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p03_STML_runtime as runtime
source,history,resources=runtime.source,runtime.history,runtime.resources
HERE=Path(__file__).parent
FIELD='selected_p03_STML_second_bounded_event'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
PROFILE='P03-STML-full20-whole-profile-qualification.json'

def candidate(spec):return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')==source.ROOT

def source_names(*,profile=True):
 names=(Path(__file__).name,Path(runtime.__file__).name,Path(resources.__file__).name,resources.FACT,
  Path(source.__file__).name,source.CATALOG,Path(history.__file__).name,'system_campaign_second_bounded_codec.py',
  'system_campaign_second_bounded_factory.py','system_campaign_p03_thor_qualification_reuse.py')
 return (*names,PROFILE) if profile else names

def qualification():
 raw=(HERE/PROFILE).read_bytes();q=json.loads(raw)
 need(q['passed'] is True and q['root_admission_sha256']==source.ROOT and q['actual_neutral20_known'] is q['canonical_runtime_executed'] is q['financial_authority'] is False,
  'STML_ENTRY_WHOLE_DATA_PROFILE_REQUIRED_NO_CLAIMED_HOSTED_BOUNDARY')
 for n,pin in q['files'].items():need(resources.pin((HERE/n).read_bytes())==pin,'STML_ENTRY_ENTIRE_QUALIFIED_PROFILE_SOURCE:'+n)
 return sha(raw)

def declaration(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);v=resources.fact()
 need(candidate(spec) and {k:x for k,x in spec.items() if k not in ('root_admission','root_admission_sha256')}==v['parent_transport'],
  'STML_ENTRY_EXACT_REAL606_ADMITTED_FULL19_TRANSPORT')
 return dict(schema='research.P03-STML-second-bounded-financial-declaration/1',root_admission_sha256=source.ROOT,
  parent_outer_sha256=spec['outer_sha256'],parent_days=606,parent_inputs=19,required_neutral_inputs=20,
  retained_proofs=152,raw_old_proofs=159,excluded_tail_proofs=7,ordinary_terms=34,
  old_DOVA_and_B19_retained=True,actual_new_constructor_required=True,actual_neutral20_known=False,
  profile_sha256=qualification(),financial_source_changed=False,owned_right_settlement_authorized=False)

def require_request(request,spec):
 need(candidate(spec) and request['execution_mode']==MODE and request['financial_resume_authorized'] is True
  and request['readonly_partial_review'] is request['readonly_source_witnesses'] is False and request['arms']==['P03']
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==1
  and request['maximum_parallel_readonly_workers']==0 and request.get(FIELD)=={'P03':declaration(spec)}
  and request['admitted_checkpoints']['P03']==spec['outer_sha256']
  and all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),
  'STML_ENTRY_EXPLICIT_QUALIFIED_FINANCIAL_REQUEST_AND_ALL_SOURCE_PINS')
 return True

def bind_expected(original,module):
 def expected():
  active=module.EXECUTION_MODE==MODE and list(module.SELECTED_ARMS)==['P03']
  spec=None
  if active:
   from system_campaign_financial_partial import root_spec
   spec=root_spec('P03')
   active=candidate(spec)
  if active:
   declared=declaration(spec)
   import system_campaign_bounded_lifecycle_dispatch as bounded
   prior=bounded.expected_request
   def old_profiles(base,*,execution_mode,selected_arms):
    return prior(base,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P03'))
   bounded.expected_request=old_profiles
   try:value=original()
   finally:bounded.expected_request=prior
  else:value=original()
  value[FIELD]={}
  if active:
   value[FIELD]={'P03':declared};value['arm_inputs']['P03']['new_factual_overlay']=True
   need(not value.get('selected_bounded_models',{}),'STML_ENTRY_NO_REPLACED_OLD_PROFILE_MODEL')
   value['selected_bounded_models']={'P03':runtime.previous.declaration(spec)}
  for n in source_names():
   pin=sha((HERE/n).read_bytes());need(n not in value['sources'] or value['sources'][n]==pin,'STML_ENTRY_NO_SOURCE_PIN_REPLACEMENT:'+n);value['sources'][n]=pin
  if value[FIELD]:require_request(value,spec)
  return value
 return expected

def mature_review(module):
 fn,=[n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='review']
 need(sha(ast.dump(fn,include_attributes=False).encode())==resources.fact()['original4_AST']['review'],'STML_ENTRY_EXACT_WHOLE_MATURE_REVIEW_BODY')
 scope=dict(vars(module));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-mature-review-with-original-two-bounded-codecs>','exec'),scope);return scope['review']

@contextmanager
def review_context(root,out,spec):
 import system_campaign_financial_partial as partial
 from system_campaign_second_bounded_codec import SuccessorCodec
 from system_campaign_bounded_sensor_lifecycle_data import evidence
 root,out=Path(root),Path(out);parent=history.archived_parent(lambda n:(root/n).read_bytes())
 current=runtime.strict_json((root/'book/checkpoint.json.gz').read_bytes());history.full(root,current)
 with partial.model_context(root,parent,spec):
  exact_source=(root/history.SOURCE).read_bytes();runtime.exact(out/history.SOURCE,exact_source)
  value=source.catalog();native,_=source.hydrate(value,out/history.SOURCE)
  with SuccessorCodec(value['event'],source.evidence(value),native,previous_event=runtime.previous.catalog()['event'],previous_evidence=evidence(runtime.previous.catalog())):yield current

@contextmanager
def context(module,spec,*,mode,out,request):
 from full_system_core import hosted
 from system_campaign_registry_extension import RegistryExtension
 hosted();require_request(request,spec);need(mode in ('preflight','economic','review'),'STML_ENTRY_EXPLICIT_MATURE_HOSTED_MODE')
 actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(Path(module.__file__).read_bytes()).body
  if isinstance(n,ast.FunctionDef) and n.name in resources.fact()['original4_AST']}
 need(actual==resources.fact()['original4_AST'],'STML_ENTRY_ALL_FOUR_MATURE_WORKER_BODIES_UNCHANGED')
 with RegistryExtension(),runtime.previous.entry_context(module,spec):
  saved={n:getattr(module,n) for n in ('prepare_composite_before_finance','require_composite_preparation','factual_overlay_needed','review')}
  prior=runtime.legacy.run,runtime.legacy.review,runtime.legacy.uncertainty_phase
  old=Path('/old')
  module.prepare_composite_before_finance=lambda parent,folder,target:runtime.prepare(parent,folder,target,old)
  module.require_composite_preparation=lambda parent,target,proof,folder:runtime.require_preparation(parent,target,proof,folder)
  module.factual_overlay_needed=lambda target:True if candidate(target) else saved['factual_overlay_needed'](target)
  runtime.legacy.run=lambda *a,**k:runtime.run(*a,**k) if candidate(k.get('spec')) else prior[0](*a,**k)
  runtime.legacy.review=lambda *a,**k:runtime.review(*a,**k) if candidate(k.get('spec')) else prior[1](*a,**k)
  runtime.legacy.uncertainty_phase=lambda target:candidate(target) or prior[2](target)
  whole=mature_review(module)
  def review(evidence,folder,target):
   with review_context(evidence,folder,target) as current:
    result=whole(evidence,folder,target)
    if current['completed']>spec['measured_closes']:
     import system_campaign_financial_partial as partial
     reporting=dict(arm='P03',archive_format=partial.FORMAT,base=current['base'],measured_closes=current['completed'],
      selected_session=current['source_cursor'],original_parent_index_sha256=sha((HERE/partial.ORIGINALS).read_bytes()),
      monthly_seed_root_admission_sha256=source.ROOT)
     partial.monthly_reproduction(evidence,folder,reporting,current)
    return result
  module.review=review
  try:yield
  finally:
   runtime.legacy.run,runtime.legacy.review,runtime.legacy.uncertainty_phase=prior
   for n,v in saved.items():setattr(module,n,v)

def bind_dispatch(original):
 @contextmanager
 def entry(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if request.get(FIELD):
   with context(module,spec,mode=mode,out=out or Path('/out'),request=request):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return entry

def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry);module.expected_request=bind_expected(module.expected_request,module)
