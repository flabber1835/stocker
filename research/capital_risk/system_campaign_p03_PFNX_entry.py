"""One qualified671/217 P03 route around the complete original hosted context."""
import ast,json
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p03_PTLA_entry as previous
import system_campaign_p03_PFNX_runtime as runtime
history,source,resources,models=runtime.history,runtime.source,runtime.resources,runtime.models
HERE=Path(__file__).parent
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
FIELD='selected_p03_PFNX_third_bounded_event'
PROFILE='P03-PFNX-full22-whole-profile-qualification.json'
RUNTIME_QUALIFICATION='P03-PFNX-history-model-runtime-DATA-qualification.json'
selected=models.selected

def source_names(*,profile=True):
 names={Path(__file__).name,*runtime.source_names(),*previous.source_names(profile=False),
  'P03-PFNX-source-packet-DATA-qualification.json','P03-PFNX-retained217-resources-DATA-qualification.json',RUNTIME_QUALIFICATION}
 if profile:names.add(PROFILE)
 return tuple(sorted(names))

def qualification():
 raw=(HERE/PROFILE).read_bytes();q=json.loads(raw)
 need(q['passed'] is q['financial_profile_ready'] is True and q['root_admission_sha256']==source.ROOT
  and q['financial_authority'] is q['local_canonical_runtime_executed'] is q['actual_neutral22_known'] is False
  and q['actual_hosted_preparation_and_constructor_required'] is True
  and set(q['files'])==set(source_names(profile=False))|{'system_campaign_financial_resume.py'},
  'PFNX_ENTRY_COMPLETE_CLOSED_SOURCE_PROFILE_AND_MANDATORY_HOSTED_GATES')
 for name,pin in q['files'].items():need(resources.pin((HERE/name).read_bytes())==pin,'PFNX_ENTRY_EXACT_WHOLE_PROFILE_SOURCE:'+name)
 return sha(raw)

def declaration(spec):
 models.phase(spec);value=resources.fact();source.catalog()
 need(selected(spec) and len(spec['repairs'])==21 and value['committed_proof']['rows']==217,'PFNX_ENTRY_ACTUAL671_FULL21_AND217_COMMITTED_RECORDS')
 return dict(schema='research.P03-PFNX-third-bounded-financial-declaration/1',root_admission_sha256=source.ROOT,
  parent_outer_sha256=spec['outer_sha256'],parent_days=671,parent_inputs=21,required_neutral_inputs=22,retained_proofs=217,raw_old_proofs=237,
  excluded_tail_proofs=20,ordinary_terms=35,old_DOVA_and_STML_models_preserved=True,original_full_interval_growth_preserved=True,
  PFNX_full_legal_interval=['12.00','14.00'],native_session=source.NATIVE,effective_session=source.DAY,profile_sha256=qualification(),
  actual_neutral22_known=False,actual_hosted_constructor_required=True,financial_source_changed=False,future_ownership_inferred=False,owned_right_settlement_authorized=False)

def require_request(request,spec):
 need(selected(spec) and request['execution_mode']==MODE and request['financial_resume_authorized'] is True
  and request['readonly_partial_review'] is request['readonly_source_witnesses'] is False and 'P03'in request['arms']
  and len(request['arms'])==len(set(request['arms'])) and type(request['maximum_parallel_financial_workers']) is int
  and request['maximum_parallel_financial_workers']==len(request['arms']) and request['maximum_parallel_readonly_workers']==0
  and request.get(FIELD)=={'P03':declaration(spec)} and request['admitted_checkpoints']['P03']==spec['outer_sha256']
  and all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),
  'PFNX_ENTRY_EXACT_SELECTED_REQUEST_ROOT_WORKERS_DECLARATION_AND_ALL_SOURCE_PINS')
 return True

def validate_metadata(spec):
 models.phase(spec);value=resources.fact()
 def contract(cp,target):
  need(target==spec and cp==dict(sha256=spec['outer_sha256'],completed=671,source_cursor='2020-08-31',base=spec['base']),
   'PFNX_ENTRY_ONLY_ACTUAL_EXISTING671_ADMISSION_METADATA')
  need(len(value['controller_sources'])==6 and all(cp['base']['sources'][n]==h for n,h in value['controller_sources'].items())
   and sha((HERE/'system_campaign_financial_branches.py').read_bytes())==runtime.legacy.BRANCH_SHA,
   'PFNX_ENTRY_ALL_SIX_CONTROLLER_AND_ORIGINAL_B19_SOURCE_IDENTITIES')
  return value['controller_sources']
 phase=dict(models.phase(spec),completed=671,source_cursor='2020-08-31')
 scope=dict(vars(runtime.legacy),unchanged_phase=lambda target:False,validate_admission_metadata=None,
  retained_contract=contract,retained_phase=lambda target:phase,point_return_phase=lambda target:False,
  own_retained_phase=lambda target:None if selected(target) else runtime.legacy.own_retained_phase(target))
 exec(compile(ast.Module(body=[previous.metadata_adapter.metadata_tree(Path(runtime.legacy.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-admission-metadata-actual671-and217-full-interval>','exec'),scope)
 return scope['validate_retained_admission_metadata'](spec)

def add_sources(value):
 for name in source_names():
  pin=sha((HERE/name).read_bytes());need(name not in value['sources'] or value['sources'][name]==pin,'PFNX_ENTRY_NO_REPLACED_SOURCE_PIN:'+name);value['sources'][name]=pin
 return value

def bind_expected(original,module):
 def expected():
  active=module.EXECUTION_MODE==MODE and 'P03'in module.SELECTED_ARMS
  from system_campaign_financial_partial import root_spec
  spec=root_spec('P03') if active else None
  if active and selected(spec):
   declared=declaration(spec);validate_metadata(spec)
   import system_campaign_bounded_lifecycle_dispatch as bounded
   saved=runtime.legacy.validate_retained_admission_metadata,bounded.expected_request,runtime.legacy.own_policy_phase
   runtime.legacy.validate_retained_admission_metadata=lambda target:validate_metadata(target) if selected(target) else saved[0](target)
   bounded.expected_request=lambda base,*,execution_mode,selected_arms:saved[1](base,execution_mode=execution_mode,selected_arms=tuple(a for a in selected_arms if a!='P03'))
   runtime.legacy.own_policy_phase=lambda target:None if selected(target) else saved[2](target)
   try:value=original()
   finally:runtime.legacy.validate_retained_admission_metadata,bounded.expected_request,runtime.legacy.own_policy_phase=saved
   need(FIELD not in value,'PFNX_ENTRY_NO_REPLACED_NEW_DECLARATION');value[FIELD]={'P03':declared};value['arm_inputs']['P03']['new_factual_overlay']=True
   from system_campaign_preflight_export import FIELD as export_field,POLICY
   value[export_field]=POLICY;add_sources(value);require_request(value,spec);return value
  value=original();need(FIELD not in value,'PFNX_ENTRY_NO_REPLACED_INACTIVE_DECLARATION');value[FIELD]={};return add_sources(value)
 return expected

def verify_prior_data(root,parent,out,spec):
 resources.parent_contract(parent,spec);return resources.closure(lambda n:(Path(root)/n).read_bytes())

def context_tree(raw):
 need(sha(raw)==sha(Path(previous.__file__).read_bytes()),'PFNX_ENTRY_WHOLE_ORIGINAL_PTLA_HOSTED_CONTEXT')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='context'];hits=[0,0]
 for node in ast.walk(fn):
  if isinstance(node,ast.Call) and ast.unparse(node.func)=='patch' and len(node.args)>=3 and isinstance(node.args[1],ast.Constant) and node.args[1].value=='load':
   need(ast.unparse(node.args[0])=='history.previous.previous.origins' and ast.unparse(node.args[2])=='history.origin_reader()',
    'PFNX_ENTRY_EXACT_EXISTING_ORIGIN_LOADER_TWO_SOURCE_EXPRESSIONS')
   node.args[0]=ast.parse('history.previous.previous.previous.origins',mode='eval').body;hits[0]+=1
   node.args[2]=ast.parse('history.previous.origin_reader()',mode='eval').body;hits[1]+=1
 need(hits==[1,1],'PFNX_ENTRY_ONLY_TWO_ORIGINAL_ORIGIN_SOURCE_PATH_BINDINGS');return ast.fix_missing_locations(fn)

def context_function():
 scope=dict(vars(previous),runtime=runtime,models=models,history=history,data=source,resources=resources,selected=selected,
  require_request=require_request,verify_prior_data=verify_prior_data)
 exec(compile(ast.Module(body=[context_tree(Path(previous.__file__).read_bytes())],type_ignores=[]),'<whole-original-hosted-context-two-origin-path-bindings>','exec'),scope)
 return scope['context']

def context(*args,**kwargs):return context_function()(*args,**kwargs)

def bind_dispatch(original):
 fn=previous.bind_dispatch
 bound=FunctionType(fn.__code__,dict(fn.__globals__,selected=selected,context=context,FIELD=FIELD,HERE=HERE),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__;return bound(original)

def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry);module.expected_request=bind_expected(module.expected_request,module)
