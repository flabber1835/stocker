"""Whole original financial worker after authentic27-to28 cash preparation."""
import ast,json
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_p03_PTLA_runtime as templates
import system_campaign_p07_KDNY_runtime as prior
import system_campaign_p07_ordinary28_history as history
import system_campaign_p07_ordinary28_retained as retained
import system_campaign_p07_ordinary28_certificate as factories
import system_campaign_p07_ordinary28_observers as observations
data,resources=history.data,history.resources
legacy,bodies=templates.legacy,templates.dova
PREPARATION=history.PREFIX+'/zero-financial-preparation.json'
BOUNDARY=history.PREFIX+'/neutral-boundary-review.json'
CONSTRUCTOR=history.PREFIX+'/constructor-canary.json'
VIEW=history.PREFIX+'/temporary-seed-view.json'
CLEANUP=history.PREFIX+'/temporary-seed-view-cleanup.json'
TEMPLATES=('adoption_tree','adopter','seed_view','seed_resolver','neutral','retained_worker')
preserve_archive=prior.preserve_archive

def physical(parent,spec,root):
 history.full_parent(root,parent);return retained.physical(parent,spec)

def template_tree(name):
 need(name in TEMPLATES,'ORDINARY28_RUNTIME_ONLY_DECLARED_WHOLE_FUNCTIONS')
 fn=templates.template_tree(name)
 if name in ('neutral','seed_resolver'):
  label,old,new=("history.full(root, actual)['full_inputs']",21,28) if name=='neutral' else ('len(value[1])',174,972)
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)==label and len(n.comparators)==1 and isinstance(n.comparators[0],ast.Constant) and n.comparators[0].value==old]
  need(len(sites)==1,'ORDINARY28_RUNTIME_ONE_EXACT_ORIGINAL_COUNT:'+name);sites[0].comparators[0].value=new
 elif name=='retained_worker':
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.keyword) and n.arg=='retained_rows' and isinstance(n.value,ast.Constant) and n.value.value==174]
  need(len(sites)==1,'ORDINARY28_RUNTIME_ONE_EXACT_ORIGINAL_RECEIPT_COUNT');sites[0].value.value=972
 return ast.fix_missing_locations(fn)

def functions(parent):
 source=SimpleNamespace(**dict(vars(data),DAY=history.DAY));h=SimpleNamespace(**dict(vars(history),SOURCE=history.material_name(parent)))
 previous=SimpleNamespace(**dict(vars(bodies),retained_contract=physical,retained_phase=retained.phase))
 scope=dict(vars(templates.original),source=source,history=h,resources=resources,previous=previous,VIEW=VIEW,CLEANUP=CLEANUP)
 exec(compile(ast.Module(body=[template_tree(n) for n in TEMPLATES],type_ignores=[]),'<whole-original-lifecycle-current27to28-and972>','exec'),scope)
 return SimpleNamespace(**{n:scope[n] for n in TEMPLATES})

def preparation_history(old,out,parent):
 old,out=Path(old),Path(out)
 def validate(where,current):
  need(Path(where)==out and current==parent,'ORDINARY28_RUNTIME_ONLY_EXACT_PREPARATION_OUTPUT_AND_PARENT')
  return history.full(old,current)
 return validate

def prepare(parent,out,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);data.parent_contract(parent,spec)
 from research.pooled_vacancy_funding import backtest
 from system_campaign_bounded_sensor_preparation import no_financial_transitions
 before=data.encoded(parent);forbidden=(out/'book/checkpoint.json.gz',out/history.NEUTRAL)
 need(not any(p.exists() for p in forbidden),'ORDINARY28_RUNTIME_PREFLIGHT_NO_CURRENT_OR_NEUTRAL_BOOK')
 with no_financial_transitions():
  baseline=retained.seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2]);resources.canary(old,out)
  selected=(old/spec['selected_checkpoint']).read_bytes();need(resources.pin(selected)==spec['selected_file'],'ORDINARY28_RUNTIME_GENUINE_SELECTED1426_ARCHIVE_BYTES')
  exact(out/history.PARENT,selected);exact(out/history.CATALOG,data.encoded(data.catalog()))
  objects=[backtest.load_repair(old/'book/repairs'/d['filename'],resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in parent['repairs']]
  need([obj.sha256 for obj in objects]==[d['sha256'] for d in parent['repairs']],'ORDINARY28_RUNTIME_ALL27_ACTUAL_ORIGINAL_TYPED_OBJECTS')
  api=history.api_module.api(parent,spec,validate_history=preparation_history(old,out,parent));path,loaded=api.prepare(parent,out,'P07')
  need(path==out/history.OVERLAY and loaded.earliest_affected_session==history.DAY,'ORDINARY28_RUNTIME_EXACT_ORIGINAL_PREPARATION_BOUNDARY')
  history.document(parent,lambda n:(out/n).read_bytes())
 need(data.encoded(parent)==before and not any(p.exists() for p in forbidden),'ORDINARY28_RUNTIME_PREFLIGHT_ZERO_FINANCIAL_PARENT_CHANGE')
 result=preparation(parent,spec,out);exact(out/PREPARATION,data.encoded(result));return result

def preparation(parent,spec,root):
 root=Path(root);data.parent_contract(parent,spec);history.document(parent,lambda n:(root/n).read_bytes())
 canary=json.loads((root/resources.CANARY).read_bytes());v=resources.fact()
 need(canary==dict(passed=True,requirements=v['requirements'],logical_bytes=v['logical_bytes'],complete_shared_copier_and_verifier=True,copy_removal_observed=True,financial_sessions_advanced=0,actual_neutral28_known=False),
  'ORDINARY28_RUNTIME_COMPLETE_ACTUAL245_COPY_CANARY')
 names=(history.PARENT,history.CATALOG,history.OVERLAY,history.material_name(parent),history.QUALIFICATION,resources.CANARY,resources.RECEIPT)
 return dict(schema='research.P07-ordinary28-stopped-preflight-preparation/1',passed=True,root_admission_sha256=data.ROOT,parent_outer_sha256=parent['sha256'],retained_proofs=972,parent_inputs=27,actual_neutral28_known=False,financial_sessions_advanced=0,files={n:resources.pin((root/n).read_bytes()) for n in names})

def require_preparation(parent,spec,proof,out):
 result=preparation(parent,spec,out)
 need(result==proof['composite_preparation']==json.loads((Path(out)/PREPARATION).read_bytes()),'ORDINARY28_RUNTIME_ONLY_EXACT_POSITIVELY_STOPPED_PREPARATION')
 return True

def run(parent,out,args,rows,observer,execution,*,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);data.parent_contract(parent,spec)
 from research.pooled_vacancy_funding import journal
 baseline=retained.seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2])
 for name in (history.PARENT,history.CATALOG,history.OVERLAY,history.material_name(parent),history.QUALIFICATION,resources.CANARY):exact(out/name,(out/'parent-preflight'/name).read_bytes())
 api=functions(parent);current=api.adopter()(parent,out,args,rows,out/history.OVERLAY,history.DAY,history.DIRECTORY)
 actual,proof=api.neutral(out,parent,rows);need(actual==current,'ORDINARY28_RUNTIME_REAL_NEUTRAL28_BEFORE_FINANCIAL_CONSTRUCTOR');exact(out/BOUNDARY,data.encoded(proof))
 with api.seed_view(old,out,parent,current,spec,out,rows) as view:
  seed=api.seed_resolver(view,parent,current,spec,out,rows,baseline);seed(view,current,spec)
  with retained.growth_scope(view,current,spec) as mixed:
   codec=retained.installed();C=factories.certificate_class(codec,parent,current,spec,baseline,view,mixed=mixed)
   constructor=factories.bind_arguments(C,**retained.zogenix_arguments(codec,view))
   def active(module,where,cp):
    need(Path(where)==view and cp==current,'ORDINARY28_RUNTIME_ACTUAL_NEUTRAL28_ACTIVE_BRANCH_ONLY')
    return retained.active_branch(module,view,current)
   lower=active(None,view,current)
   from system_campaign_alder_date_v2 import AlderDateV2
   alder=AlderDateV2(Path(__file__).parent/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/history.PREFIX/'constructor-alder-source.json')
   candidate=constructor(out,lower,alder.native,baseline[0],seed=baseline[1],event_source=json.loads((view/'hydrated-uncertainty-event.json').read_bytes()))
   events=observations.observer(view,parent,spec,out);distribution=prior.retained.previous.inputs.observer(out)
   need(candidate.seed==baseline[1] and len(candidate.seed)==972 and len(events.terms)==35,'ORDINARY28_RUNTIME_ACTUAL972_CONSTRUCTOR_AND35_TERM_OBSERVER')
   exact(out/CONSTRUCTOR,data.encoded(dict(passed=True,current_checkpoint_sha256=current['sha256'],retained_rows=972,full_inputs=28,ordinary_terms=35,BWA_observer_preserved=True,financial_sessions_advanced=0)))
   fn=api.retained_worker(dict(Certificate=constructor,preserve=preserve_archive,retained_seed=seed,active_codec=active,unchanged_input_phase=lambda target:target==spec,own_unchanged_input_phase=lambda target:False,unchanged_input_receipt=lambda cp,target:proof),parent,current,spec,baseline,view)
   with events,distribution:code=fn(current,out,args,observer,execution,spec,view)
 after=journal.read_checkpoint(out/'book/checkpoint.json.gz');history.full(out,after)
 need(after['repairs']==current['repairs'] and after['run']['input_sha256']==current['run']['input_sha256'],'ORDINARY28_RUNTIME_ALL28_INPUTS_UNCHANGED_DURING_FINANCIAL_SUFFIX')
 return code

def suffix(root,parent,current,retained_rows,rows,financial,mixed):
 import system_campaign_bounded_sensor_event_review as original
 def permissions(where,new,catalog,*,through,input_descriptors):
  history.full(where,current);seed_parent=history.archived_parent(lambda n:(Path(where)/n).read_bytes())
  need(all(row['session']>seed_parent['source_cursor'] for row in new),'ORDINARY28_REVIEW_ONLY_STRICTLY_NEW_DAYS_NO_OLD_EVENT_REPLAY')
  q=(Path(where)/resources.QUALIFIED).read_bytes();saved,origin=factories.archived_bases(where,seed_parent,retained_rows,q)
  return {},[item[2] for item in saved]
 fn=FunctionType(original.suffix.__code__,dict(original.suffix.__globals__,permissions=permissions),original.suffix.__name__,original.suffix.__defaults__)
 return fn(root,parent,current,retained_rows,rows,financial,factories.original.source.catalog(),growth=mixed)

def review(parent,evidence,out,*,spec,old):
 from full_system_core import hosted
 hosted();old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 from research.pooled_vacancy_funding import journal
 rows=seed_rows(old,parent,spec);baseline=retained.seed_reader()(old,parent,spec);current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz');api=functions(parent)
 adopted,proof=api.neutral(evidence,parent,rows);history.full(evidence,current)
 need(resources.verify(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes())==json.loads((evidence/resources.RECEIPT).read_bytes()),'ORDINARY28_REVIEW_ALL245_PRESERVED_RESOURCES')
 need(json.loads((evidence/CONSTRUCTOR).read_bytes())==dict(passed=True,current_checkpoint_sha256=adopted['sha256'],retained_rows=972,full_inputs=28,ordinary_terms=35,BWA_observer_preserved=True,financial_sessions_advanced=0),'ORDINARY28_REVIEW_ACTUAL_SHARED_CONSTRUCTOR_CANARY')
 def unchanged(before,after,where,target):
  need(before==adopted and target==spec and after['repairs']==adopted['repairs'] and after['run']['input_sha256']==adopted['run']['input_sha256']
   and json.loads((Path(where)/legacy.UNCHANGED_INPUT).read_bytes())==proof,'ORDINARY28_REVIEW_GENUINE_NEUTRAL28_UNCHANGED_SUFFIX')
 with api.seed_view(old,out,parent,adopted,spec,evidence,rows) as view:
  seed=api.seed_resolver(view,parent,adopted,spec,evidence,rows,baseline)
  with retained.growth_scope(view,adopted,spec) as mixed:
   fn=bodies.bound_body('review_retained',dict(validate_input=history.full,retained_seed=seed,own_unchanged_input_phase=lambda target:False,unchanged_input_phase=lambda target:target==spec,review_unchanged_input=unchanged,review_new_rows=lambda before,after,retained,new,financial,**kwargs:suffix(evidence,before,after,retained,new,financial,mixed)))
   fn(adopted,evidence,out,spec,view)
 observations.review(evidence,current,out)
 result=prior.retained.previous.inputs.review_event(prior.retained.previous.inputs.payload(),evidence,current)
 exact(out/prior.retained.previous.EVENT_REVIEW,data.encoded(result));exact(out/BOUNDARY,data.encoded(proof))

def source_names():return (Path(__file__).name,Path(templates.__file__).name,Path(templates.original.__file__).name,Path(bodies.__file__).name,Path(legacy.__file__).name,Path(prior.__file__).name,*factories.source_names(),*retained.source_names(),*observations.source_names())
