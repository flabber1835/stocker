"""Explicit host launch and hosted-core preparation/worker routing."""
import json
from pathlib import Path
from contextlib import contextmanager,ExitStack
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_source_exit_runtime as runtime
import system_campaign_stopped_parent as loader
HERE=Path(__file__).parent
CANARY='source-exit-successor-dependency-canary.json'
PREPARATION='source-exit-successor-zero-financial-preparation.json'

def source_names():
 names=('system_campaign_source_exit_entry.py','system_campaign_source_exit_runtime.py','system_campaign_source_exit_api.py','system_campaign_source_exit_history.py',
  'system_campaign_source_exit_input.py','system_campaign_source_exit_input_v1.py','P06-TBIO-source-exit-input-catalog.json','P06-TBIO-source-exit-DATA-qualification.json','P06-DM-source-exit-input-catalog-v2.json','P06-DM-boundary-export-DATA-qualification.json',
  'system_campaign_full_history_successor.py','system_campaign_retained_seed_successor.py','system-campaign-retained-seed-successors.json','P06-retained424-successor-DATA-qualification.json',
  'system_campaign_stopped_parent.py','system-campaign-stopped-parent-transports.json','P06-stopped-parent-transport-DATA-qualification.json',
  'system_campaign_source_exit_resources.py','system-campaign-source-exit-successor-resources.json','system_campaign_source_exit_observer.py',
  'P06-source-exit-API-history-DATA-qualification.json','system_campaign_source_exit_reporting.py','system_campaign_progress_observer.py','system_campaign_preflight_export.py',runtime.QUALIFICATION)
 return names if (HERE/runtime.QUALIFICATION).is_file() else tuple(n for n in names if n!=runtime.QUALIFICATION)

def expected_request(original,*,execution_mode,selected_arms,root_lookup):
 result=original();active=execution_mode==runtime.MODE and 'P06' in selected_arms and runtime.candidate(root_lookup('P06'))
 need(runtime.FIELD not in result,'SOURCE_EXIT_ENTRY_NO_REPLACED_DECLARATION')
 result[runtime.FIELD]={'P06':runtime.declaration(root_lookup('P06'))} if active else {}
 if active:result['arm_inputs']['P06']['new_factual_overlay']=True
 for n in source_names():
  pin=sha((HERE/n).read_bytes());need(n not in result['sources'] or result['sources'][n]==pin,'SOURCE_EXIT_ENTRY_NO_SOURCE_PIN_REPLACEMENT:'+n);result['sources'][n]=pin
 return result

def receipt(parent,spec,root):
 root=Path(root);api=runtime.input_api(parent,spec);doc=runtime.models.document(parent,spec,lambda n:(root/n).read_bytes(),visitor=runtime.previous.full)
 material=json.loads((root/api.hydration_name(parent)).read_bytes());runtime.models.packet_qualification(lambda n:(root/n).read_bytes(),material['terms'])
 canary=json.loads((root/CANARY).read_bytes());scopes=api.source_scopes(parent,material,sha((root/api.OVERLAY).read_bytes()),sha((root/api.hydration_name(parent)).read_bytes()))
 term=runtime.api_module.source.catalog()['term']
 need(len(scopes)==1 and scopes[0]['security_id']==term['security_id'] and scopes[0]['require_never_held'] is True
  and json.loads((root/api.SOURCE_SCOPES).read_bytes())==scopes,'SOURCE_EXIT_ENTRY_EXACT_SOURCE_EXIT_SCOPE_BEFORE_FINANCE')
 other=[t for t in material['terms'] if t['security_id']!=term['security_id']]
 need(all(t['added']['kind']=='CASH_MERGER' and t['added']['session']!=term['added']['session'] for t in other),
  'SOURCE_EXIT_ENTRY_EVERY_ORIGINAL_FORWARD_TERM_HAS_COMPLETE_OBSERVER_REVIEW')
 need(canary['passed'] is canary['actual_copy_verified'] is canary['owned_copy_removed'] is True and canary['financial_sessions_advanced']==0
  and len(canary['dependency_closure']['requirements'])==104 and canary['dependency_closure']['event_resolutions']==runtime.resources.plan(spec)['event_resolutions'],
  'SOURCE_EXIT_ENTRY_FRESH_ACTUAL104_RESOURCE_COPY_AND_REMOVAL_CANARY')
 need(json.loads((root/api.OVERLAY).read_bytes())==doc,'SOURCE_EXIT_ENTRY_COMPLETE_ORIGINAL_PREPARED_DOCUMENT')
 return dict(schema='research.source-exit-successor-zero-financial-preparation/1',passed=True,root_admission_sha256=spec['root_admission_sha256'],
  parent_outer_sha256=parent['sha256'],earliest_affected_session=runtime.models.earliest(doc),financial_sessions_advanced=0,parent_unchanged=True,checkpoint_adopted=False,
  files={n:dict(bytes=len((root/n).read_bytes()),sha256=sha((root/n).read_bytes())) for n in (api.OVERLAY,api.hydration_name(parent),api.SOURCE_SCOPES,api.QUALIFICATION,CANARY,runtime.resources.RECEIPT)})

def preflight(parent,out,spec,old,request):
 from full_system_core import hosted
 hosted();runtime.request_financial(request,spec)
 from research.pooled_vacancy_funding import backtest,runtime as financial
 out,old=Path(out),Path(old);before=runtime.encoded(parent);forbidden=[out/'book/checkpoint.json.gz',out/runtime.models.NEUTRAL]
 need(not any(p.exists() for p in forbidden),'SOURCE_EXIT_ENTRY_PREFLIGHT_HAS_NO_FINANCIAL_OR_NEUTRAL_BOOK')
 def refuse(*a,**k):raise ValueError('SOURCE_EXIT_ENTRY_PREFLIGHT_FINANCIAL_ADVANCE_FORBIDDEN')
 saved=backtest.main,financial.advance;backtest.main=financial.advance=refuse
 try:
  baseline=runtime.seeds.original_seed(old,parent,spec,visitor=runtime.previous.full)
  result=runtime.resources.canary(old,out,parent,spec,resolutions=[baseline[3]]);exact(out/CANARY,runtime.encoded(result))
  runtime.resources.preserve(old,out,parent,spec,rows=baseline[1],resolutions=[baseline[3]])
  for entry in parent['repairs']:
   raw=(old/'book/repairs'/entry['filename']).read_bytes();need(sha(raw)==entry['sha256'],'SOURCE_EXIT_ENTRY_EXACT_ORIGINAL_INPUT_BYTES');exact(out/'book/repairs'/entry['filename'],raw)
  runtime.input_api(parent,spec).prepare(parent,out,spec['arm'])
 finally:backtest.main,financial.advance=saved
 need(runtime.encoded(parent)==before and not any(p.exists() for p in forbidden),'SOURCE_EXIT_ENTRY_NO_PREFLIGHT_FINANCIAL_STATE_MUTATION_OR_ADOPTION')
 result=receipt(parent,spec,out);exact(out/PREPARATION,runtime.encoded(result));return result

def require_preflight(parent,spec,proof,root):
 expected=receipt(parent,spec,root);need(proof['composite_preparation']==expected==json.loads((Path(root)/PREPARATION).read_bytes()),'SOURCE_EXIT_ENTRY_EXACT_STOPPED_PREPARATION_BEFORE_FINANCE');return True

@contextmanager
def context(module,spec,*,mode,old,out,request,evidence=None):
 from full_system_core import hosted
 hosted();runtime.request_financial(request,spec);need(mode in ('preflight','economic','review'),'SOURCE_EXIT_ENTRY_EXPLICIT_HOSTED_PROCESS_MODE')
 import system_campaign_financial_partial as partial
 import system_campaign_financial_requalified_parent as dispatch
 from system_campaign_registry_extension import RegistryExtension
 saved_partial={n:getattr(partial,n) for n in ('retained_models','model_context')};saved_dispatch={n:getattr(dispatch,n) for n in ('applies','accounting_review')}
 saved_legacy={n:getattr(runtime.legacy,n) for n in ('uncertainty_phase','run','review')}
 saved_module={n:getattr(module,n) for n in ('factual_overlay_needed','prepare_composite_before_finance','require_composite_preparation')}
 def retained_models(root,current,target):return runtime.models.full(root,current)['full_inputs'] in (12,13) if runtime.candidate(target) else saved_partial['retained_models'](root,current,target)
 @contextmanager
 def model_context(root,current,target):
  if not runtime.candidate(target):
   with saved_partial['model_context'](root,current,target):yield
   return
  from system_campaign_bounded_sensor_input import InputCodec
  from system_campaign_abmd_bounded_hydration import hydrate
  from system_campaign_abmd_bounded_catalog import evidence as event_evidence
  runtime.models.full(root,current);value=runtime.initial.catalog();native,_=hydrate(value,Path(out)/'source-exit-retained-codec-source.json')
  with InputCodec(value['event'],event_evidence(value),native):yield
 partial.retained_models,partial.model_context=retained_models,model_context
 dispatch.applies=lambda target:runtime.candidate(target) or saved_dispatch['applies'](target)
 dispatch.accounting_review=lambda target:loader.accounting_review(target) if runtime.candidate(target) else saved_dispatch['accounting_review'](target)
 runtime.legacy.uncertainty_phase=lambda target:runtime.candidate(target) or saved_legacy['uncertainty_phase'](target)
 runtime.legacy.run=lambda *a,spec=None,old=None,**k:runtime.run(*a,spec=spec,old=old,request=request,**k) if runtime.candidate(spec) else saved_legacy['run'](*a,spec=spec,old=old,**k)
 runtime.legacy.review=lambda *a,spec=None,old=None,**k:runtime.review(*a,spec=spec,old=old,request=request,**k) if runtime.candidate(spec) else saved_legacy['review'](*a,spec=spec,old=old,**k)
 module.factual_overlay_needed=lambda target:True if runtime.candidate(target) else saved_module['factual_overlay_needed'](target)
 module.prepare_composite_before_finance=lambda cp,folder,target:preflight(cp,folder,target,old,request) if runtime.candidate(target) else saved_module['prepare_composite_before_finance'](cp,folder,target)
 module.require_composite_preparation=lambda cp,target,proof,folder:require_preflight(cp,target,proof,folder) if runtime.candidate(target) else saved_module['require_composite_preparation'](cp,target,proof,folder)
 try:
  with ExitStack() as stack:
   stack.enter_context(RegistryExtension())
   if mode=='review':
    need(evidence is not None,'SOURCE_EXIT_ENTRY_REVIEW_REQUIRES_GENUINE_EVIDENCE');current=strict_json((Path(evidence)/'book/checkpoint.json.gz').read_bytes())
    scratch=Path(out)/'source-exit-review-codecs';scratch.mkdir();stack.enter_context(partial.financial_inputs(Path(evidence),current,scratch,spec))
   yield
   if mode=='review':
    from system_campaign_source_exit_reporting import reader as reporting_reader
    current=strict_json((Path(evidence)/'book/checkpoint.json.gz').read_bytes())
    reporting_reader(spec)(Path(evidence),Path(out),spec,current)
 finally:
  for n,v in saved_partial.items():setattr(partial,n,v)
  for n,v in saved_dispatch.items():setattr(dispatch,n,v)
  for n,v in saved_legacy.items():setattr(runtime.legacy,n,v)
  for n,v in saved_module.items():setattr(module,n,v)

def bind_launch(original,module):
 def launch(args):
  request=json.loads(args.request.read_bytes())
  from system_campaign_financial_partial import root_spec
  spec=root_spec(args.arm)
  if not runtime.candidate(spec) or request.get('execution_mode')!=runtime.MODE:return original(args)
  runtime.request_financial(request,spec)
  import system_campaign_financial_review_repair as repair
  saved=repair.applies;repair.applies=lambda target:False if runtime.candidate(target) else saved(target)
  try:
   with loader.context(spec,request,profile_validator=runtime.request_financial):return original(args)
  finally:repair.applies=saved
 return launch
