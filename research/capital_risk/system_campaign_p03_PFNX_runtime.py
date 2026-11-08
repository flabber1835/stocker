"""Whole original financial worker after genuine full21-to22 PFNX preparation."""
import ast,json
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_p03_PTLA_runtime as templates
import system_campaign_p03_PFNX_history as history
import system_campaign_p03_PFNX_models as models
import system_campaign_p03_PFNX_certificate as certificates
import system_campaign_p03_PFNX_observers as observations
import system_campaign_p03_PFNX_preparation as packets
source,resources=history.source,history.resources
legacy,bodies=templates.legacy,templates.dova
PREPARATION=history.PREFIX+'/zero-financial-preparation.json'
BOUNDARY=history.PREFIX+'/neutral-boundary-review.json'
CONSTRUCTOR=history.PREFIX+'/constructor-canary.json'
VIEW=history.PREFIX+'/temporary-seed-view.json'
CLEANUP=history.PREFIX+'/temporary-seed-view-cleanup.json'
TEMPLATES=templates.TEMPLATES

def template_tree(name):
 need(name in TEMPLATES,'PFNX_RUNTIME_ONLY_DECLARED_WHOLE_ORIGINAL_FUNCTIONS');fn=templates.template_tree(name)
 if name in ('neutral','seed_resolver'):
  label,old,new=("history.full(root, actual)['full_inputs']",21,22) if name=='neutral' else ('len(value[1])',174,217)
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)==label and len(n.comparators)==1 and isinstance(n.comparators[0],ast.Constant) and n.comparators[0].value==old]
  need(len(sites)==1,'PFNX_RUNTIME_EXACT_ONE_ORIGINAL_COUNT:'+name);sites[0].comparators[0].value=new
 elif name=='retained_worker':
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.keyword) and n.arg=='retained_rows' and isinstance(n.value,ast.Constant) and n.value.value==174]
  need(len(sites)==1,'PFNX_RUNTIME_EXACT_ONE_ORIGINAL_RECEIPT_COUNT');sites[0].value.value=217
 return ast.fix_missing_locations(fn)

def functions(parent):
 previous=SimpleNamespace(**dict(vars(bodies),retained_contract=models.physical,retained_phase=models.phase))
 scope=dict(vars(templates.original),source=SimpleNamespace(**dict(vars(source),DAY=source.NATIVE)),history=history,resources=resources,previous=previous,VIEW=VIEW,CLEANUP=CLEANUP)
 exec(compile(ast.Module(body=[template_tree(name) for name in TEMPLATES],type_ignores=[]),'<whole-original-lifecycle-PFNX-native-boundary-and217>','exec'),scope)
 return SimpleNamespace(**{name:scope[name] for name in TEMPLATES})

def preparation(parent,spec,root):
 root=Path(root);source.parent_contract(parent,spec);history.document(parent,lambda n:(root/n).read_bytes())
 canary=json.loads((root/resources.CANARY).read_bytes())
 need(canary['passed'] is canary['actual_copy_verified'] is canary['owned_copy_removed'] is True and canary['financial_sessions_advanced']==0
  and len(canary['closure']['resources'])==151 and sum(x['bytes'] for x in canary['closure']['resources'].values())==85321622,
  'PFNX_RUNTIME_COMPLETE_ACTUAL151_COPY_AND_REMOVAL_CANARY')
 names=(history.PARENT,history.CATALOG,history.OVERLAY,history.SOURCE,history.QUALIFICATION,resources.CANARY,resources.RECEIPT)
 return dict(schema='research.P03-PFNX-stopped-preparation/1',passed=True,root_admission_sha256=source.ROOT,parent_outer_sha256=parent['sha256'],
  parent_inputs=21,required_neutral_inputs=22,retained_proofs=217,actual_neutral22_known=False,financial_sessions_advanced=0,
  files={n:resources.pin((root/n).read_bytes()) for n in names})

def prepare(parent,out,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);source.parent_contract(parent,spec)
 from research.pooled_vacancy_funding import backtest
 from system_campaign_bounded_sensor_preparation import no_financial_transitions
 before=source.encoded(parent);forbidden=(out/'book/checkpoint.json.gz',out/history.NEUTRAL)
 need(not any(p.exists() for p in forbidden),'PFNX_RUNTIME_PREFLIGHT_NO_ACTIVE_OR_NEUTRAL_BOOK')
 with no_financial_transitions():
  baseline=models.seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2]);resources.canary(old,out)
  raw=(old/spec['selected_checkpoint']).read_bytes();need(resources.pin(raw)==spec['selected_file'],'PFNX_RUNTIME_EXACT_ORIGINAL671_PARENT_GZIP');exact(out/history.PARENT,raw)
  value=source.catalog();exact(out/history.CATALOG,source.encoded(value));exact(out/history.OVERLAY,source.encoded(source.document(parent,value=value)))
  codec=models.installed();need((out/history.SOURCE).read_bytes()==source.encoded(value['market_source']),'PFNX_RUNTIME_ACTUAL_CONTEXT_HYDRATED_COMPLETE_SOURCE')
  objects=[backtest.load_repair(old/'book/repairs'/d['filename'],resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in parent['repairs']]
  typed=source.parse_document(out/history.OVERLAY,parent)
  loaded=backtest.load_repair(out/history.OVERLAY,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
  need(loaded.sha256==typed.sha256 and any(loaded is obj for obj in codec.objects),'PFNX_RUNTIME_ACTUAL_INSTALLED_TYPED_PARSER')
  proof=packets.qualify_packets(parent,out/history.OVERLAY,loaded,codec.native,value,objects)
  exact(out/history.QUALIFICATION,source.encoded(dict(passed=True,catalog_sha256=sha(source.encoded(value)),typed_document_sha256=loaded.sha256,
   market_source_sha256=sha((out/history.SOURCE).read_bytes()),packet=proof,financial_sessions_advanced=0)))
  history.document(parent,lambda n:(out/n).read_bytes())
 need(source.encoded(parent)==before and not any(p.exists() for p in forbidden),'PFNX_RUNTIME_PREFLIGHT_ZERO_FINANCIAL_CHANGE')
 result=preparation(parent,spec,out);exact(out/PREPARATION,source.encoded(result));return result

def require_preparation(parent,spec,proof,out):
 result=preparation(parent,spec,out)
 need(result==proof['composite_preparation']==json.loads((Path(out)/PREPARATION).read_bytes()),'PFNX_RUNTIME_ONLY_EXACT_POSITIVELY_STOPPED_PREPARATION');return True

def run(parent,out,args,rows,observer,execution,*,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);source.parent_contract(parent,spec)
 from research.pooled_vacancy_funding import backtest,journal
 baseline=models.seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2])
 for name in (history.PARENT,history.CATALOG,history.SOURCE,history.OVERLAY,history.QUALIFICATION,resources.CANARY):exact(out/name,(out/'parent-preflight'/name).read_bytes())
 codec=models.installed();api=functions(parent);current=api.adopter()(parent,out,args,rows,out/history.OVERLAY,source.NATIVE,history.DIRECTORY)
 actual,proof=api.neutral(out,parent,rows);need(actual==current,'PFNX_RUNTIME_ACTUAL_NEUTRAL22_BEFORE_FINANCIAL_CONSTRUCTOR');exact(out/BOUNDARY,source.encoded(proof))
 with api.seed_view(old,out,parent,current,spec,out,rows) as view:
  seed=api.seed_resolver(view,parent,current,spec,out,rows,baseline);seed(view,current,spec)
  C=certificates.certificate_class(codec,parent,current,spec,baseline,view)
  def active(module,where,cp):
   need(module is backtest and Path(where)==view and cp==current,'PFNX_RUNTIME_ONLY_ACTUAL_MODULE_OWNED_VIEW_AND_NEUTRAL22')
   return models.active_branch(module,view,current)
  lower=active(backtest,view,current)
  from system_campaign_alder_date_v2 import AlderDateV2
  alder=AlderDateV2(Path(__file__).parent/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/history.PREFIX/'constructor-alder-source.json')
  candidate=C(out,lower,alder.native,baseline[0],seed=baseline[1],event_source=json.loads((view/'hydrated-uncertainty-event.json').read_bytes()))
  events=observations.observer(out,current)
  need(candidate.seed==baseline[1] and len(candidate.seed)==217 and len(events.terms)==35,'PFNX_RUNTIME_ACTUAL217_THREE_EVENT_CONSTRUCTOR_AND35_TERMS')
  exact(out/CONSTRUCTOR,source.encoded(dict(passed=True,current_checkpoint_sha256=current['sha256'],retained_rows=217,full_inputs=22,ordinary_terms=35,financial_sessions_advanced=0)))
  fn=api.retained_worker(dict(Certificate=C,preserve=api.preserve_archive,retained_seed=seed,active_codec=active,unchanged_input_phase=lambda target:target==spec,
   own_unchanged_input_phase=lambda target:False,unchanged_input_receipt=lambda cp,target:proof),parent,current,spec,baseline,view)
  with events:code=fn(current,out,args,observer,execution,spec,view)
 after=journal.read_checkpoint(out/'book/checkpoint.json.gz');history.full(out,after)
 need(after['repairs']==current['repairs'] and after['run']['input_sha256']==current['run']['input_sha256'],'PFNX_RUNTIME_ALL22_INPUTS_UNCHANGED_THROUGH_FINANCIAL_SUFFIX');return code

def suffix(root,parent,current,retained,rows,financial):
 from types import FunctionType
 from system_campaign_uncertainty_math import growth
 import system_campaign_bounded_sensor_event_review as original
 def permissions(where,new,catalog,*,through,input_descriptors):
  allowed={};resolutions=[]
  for value in (certificates.previous.dova.catalog(),certificates.previous.stml.catalog(),source.catalog()):
   extra,found=certificates.previous.event_review.event_permissions(where,parent,retained,new,value,through=through,input_descriptors=input_descriptors)
   if value['event']['effective_session']<=parent['source_cursor']:
    need(extra=={} and len(found)==1,'PFNX_REVIEW_OLD_EVENTS_NO_NEW_PERMISSION_OR_REPLAY')
    certificates.previous.require_resolution(found[0],resources.fact()['historical_archive_resolutions'])
   need(not (set(allowed)&set(extra)),'PFNX_REVIEW_ONLY_ONE_EXACT_NEW_EVENT_PERMISSION');allowed.update(extra);resolutions.extend(found)
  return allowed,resolutions
 fn=FunctionType(original.suffix.__code__,dict(original.suffix.__globals__,permissions=permissions),original.suffix.__name__,original.suffix.__defaults__)
 return fn(root,parent,current,retained,rows,financial,source.catalog(),growth=growth)

def review(parent,evidence,out,*,spec,old):
 from full_system_core import hosted
 hosted();old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 from research.pooled_vacancy_funding import journal
 rows=seed_rows(old,parent,spec);baseline=models.seed_reader()(old,parent,spec);current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz');api=functions(parent)
 adopted,proof=api.neutral(evidence,parent,rows);history.full(evidence,current)
 need(resources.verify(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes())==json.loads((evidence/resources.RECEIPT).read_bytes()),'PFNX_REVIEW_ALL151_PRESERVED_RESOURCES')
 need(json.loads((evidence/CONSTRUCTOR).read_bytes())==dict(passed=True,current_checkpoint_sha256=adopted['sha256'],retained_rows=217,full_inputs=22,ordinary_terms=35,financial_sessions_advanced=0),
  'PFNX_REVIEW_ACTUAL_SHARED_THREE_EVENT_CONSTRUCTOR_CANARY')
 def unchanged(before,after,where,target):
  need(before==adopted and target==spec and after['repairs']==adopted['repairs'] and after['run']['input_sha256']==adopted['run']['input_sha256']
   and json.loads((Path(where)/legacy.UNCHANGED_INPUT).read_bytes())==proof,'PFNX_REVIEW_GENUINE_NEUTRAL22_AND_UNCHANGED_SUFFIX')
 with api.seed_view(old,out,parent,adopted,spec,evidence,rows) as view:
  seed=api.seed_resolver(view,parent,adopted,spec,evidence,rows,baseline)
  fn=bodies.bound_body('review_retained',dict(validate_input=history.full,retained_seed=seed,own_unchanged_input_phase=lambda target:False,
   unchanged_input_phase=lambda target:target==spec,review_unchanged_input=unchanged,review_new_rows=lambda before,after,retained,new,financial,**kwargs:suffix(evidence,before,after,retained,new,financial)))
  fn(adopted,evidence,out,spec,view)
 observations.review(evidence,current,out);exact(out/BOUNDARY,source.encoded(proof))

def source_names():return (Path(__file__).name,Path(templates.__file__).name,Path(templates.original.__file__).name,Path(bodies.__file__).name,Path(legacy.__file__).name,*models.source_names(),*certificates.source_names(),*observations.source_names())
