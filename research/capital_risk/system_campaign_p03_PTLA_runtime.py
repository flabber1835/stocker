"""Original retained worker around full20/174 and one ordinary PTLA input."""
import ast,json
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_p03_STML_runtime as original
import system_campaign_p03_PTLA_history as history
import system_campaign_p03_PTLA_certificate as certificates
import system_campaign_p03_PTLA_observers as observations
data,resources=history.data,history.resources
legacy,dova=original.legacy,original.previous
PREPARATION=history.PREFIX+'/zero-financial-preparation.json'
BOUNDARY=history.PREFIX+'/neutral-boundary-review.json'
CONSTRUCTOR=history.PREFIX+'/constructor-canary.json'
VIEW=history.PREFIX+'/temporary-seed-view.json'
CLEANUP=history.PREFIX+'/temporary-seed-view-cleanup.json'
TEMPLATES=('adoption_tree','adopter','preserve_archive','seed_view','seed_resolver','neutral','retained_worker')


def phase(spec):
 need(spec==history.spec(),'PTLA_RUNTIME_ONLY_GENUINE_ADMITTED628_SPEC')
 proof=spec['root_admission']['branch_uncertainty_proof']
 need(proof['passed'] is True and (proof['rows'],proof.get('retained_rows',0))==(22,152),
  'PTLA_RUNTIME_EXACT174_COUNTS_FROM_ADMITTED_PROOF')
 return dict(rows=174,new_rows=22,retained_rows=152)


def physical(parent,spec,root):
 from full_system_core import hosted
 hosted();resources.parent_contract(parent,spec);history.full_parent(root,parent);hashes=resources.fact()['controller_sources']
 need(len(hashes)==6 and all(parent['base']['sources'].get(n)==h and sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),
  'PTLA_RUNTIME_ALL_SIX_UNCHANGED_PHYSICAL_CONTROLLER_SOURCES')
 return hashes


def seed_reader():
 from system_campaign_bounded_sensor_seed_binding import bind_seed
 def read(root,parent,spec):
  from full_system_core import hosted
  hosted();root=Path(root)
  whole=bind_seed(validate_input=history.full,retained_contract=lambda cp,target:physical(cp,target,root),retained_phase=phase)
  value=whole(root,parent,spec);resources.seed_contract(parent,value[1],value[2]);resources.raw_contract(lambda n:(root/n).read_bytes(),value[1])
  return value
 return read


def template_tree(name):
 need(name in TEMPLATES,'PTLA_RUNTIME_ONLY_DECLARED_WHOLE_STML_FUNCTIONS')
 fn=next(n for n in ast.parse(Path(original.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
 if name in ('neutral','seed_resolver'):
  expected,new,label=(20,21,"history.full(root, actual)['full_inputs']") if name=='neutral' else (152,174,'len(value[1])')
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)==label
   and len(n.comparators)==1 and isinstance(n.comparators[0],ast.Constant) and n.comparators[0].value==expected]
  need(len(sites)==1,'PTLA_RUNTIME_ONE_EXACT_ORIGINAL_COUNT_SITE:'+name);sites[0].comparators[0].value=new
 elif name=='retained_worker':
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.keyword) and n.arg=='retained_rows' and isinstance(n.value,ast.Constant) and n.value.value==152]
  need(len(sites)==1,'PTLA_RUNTIME_ONE_EXACT_ORIGINAL_QUALIFICATION_RECEIPT_COUNT');sites[0].value.value=174
 return ast.fix_missing_locations(fn)


def functions(parent):
 source=SimpleNamespace(**dict(vars(data),DAY=history.DAY))
 h=SimpleNamespace(**dict(vars(history),SOURCE=history.material_name(parent)))
 previous=SimpleNamespace(**dict(vars(dova),retained_contract=physical,retained_phase=phase))
 scope=dict(vars(original),source=source,history=h,resources=resources,previous=previous,VIEW=VIEW,CLEANUP=CLEANUP)
 exec(compile(ast.Module(body=[template_tree(n) for n in TEMPLATES],type_ignores=[]),
  '<whole-original-STML-lifecycle-explicit-PTLA-bindings>','exec'),scope)
 return SimpleNamespace(**{n:scope[n] for n in TEMPLATES})


def preparation(parent,spec,root):
 root=Path(root);resources.parent_contract(parent,spec);history.document(parent,lambda n:(root/n).read_bytes())
 canary=json.loads((root/resources.CANARY).read_bytes())
 need(canary['passed'] is canary['actual_copy_verified'] is canary['owned_copy_removed'] is True
  and canary['financial_sessions_advanced']==0 and len(canary['closure']['resources'])==127,
  'PTLA_RUNTIME_COMPLETE_ACTUAL127_ASSET_COPY_CANARY')
 names=(history.PARENT,history.CATALOG,history.OVERLAY,history.material_name(parent),history.QUALIFICATION,resources.CANARY,resources.RECEIPT)
 return dict(schema='research.P03-PTLA-zero-financial-preparation/1',passed=True,root_admission_sha256=data.ROOT,
  parent_outer_sha256=parent['sha256'],retained_proofs=174,parent_inputs=20,actual_neutral21_known=False,
  financial_sessions_advanced=0,files={n:resources.pin((root/n).read_bytes()) for n in names})


def prepare(parent,out,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);resources.parent_contract(parent,spec)
 from system_campaign_bounded_sensor_preparation import no_financial_transitions
 before=data.encoded(parent);forbidden=(out/'book/checkpoint.json.gz',out/history.NEUTRAL)
 need(not any(p.exists() for p in forbidden),'PTLA_RUNTIME_PREFLIGHT_NO_CURRENT_OR_NEUTRAL_BOOK')
 with no_financial_transitions():
  baseline=seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2]);resources.canary(old,out)
  exact(out/history.CATALOG,data.encoded(data.catalog()))
  api=history.api_module.api(parent,spec,validate_history=history.full)
  path,loaded=api.prepare(parent,out,'P03')
  need(path==out/history.OVERLAY and loaded.earliest_affected_session==history.DAY,'PTLA_RUNTIME_ORIGINAL_PREPARATION_EXACT_NEW_INPUT_BOUNDARY')
  history.document(parent,lambda n:(out/n).read_bytes())
 need(data.encoded(parent)==before and not any(p.exists() for p in forbidden),'PTLA_RUNTIME_PREFLIGHT_ZERO_PARENT_CHANGE_OR_FINANCIAL_ADOPTION')
 result=preparation(parent,spec,out);exact(out/PREPARATION,data.encoded(result));return result


def require_preparation(parent,spec,proof,out):
 value=preparation(parent,spec,out)
 need(value==proof['composite_preparation']==json.loads((Path(out)/PREPARATION).read_bytes()),
  'PTLA_RUNTIME_ONLY_EXACT_POSITIVELY_STOPPED_ORIGINAL_PREPARATION')
 return True


def run(parent,out,args,rows,observer,execution,*,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);resources.parent_contract(parent,spec);baseline=seed_reader()(old,parent,spec)
 resources.preserve(old,out,parent,baseline[1],baseline[2])
 for name in (history.CATALOG,history.OVERLAY,history.material_name(parent),history.QUALIFICATION,resources.CANARY):
  exact(out/name,(out/'parent-preflight'/name).read_bytes())
 from research.pooled_vacancy_funding import backtest,journal
 from system_campaign_second_bounded_codec import SuccessorCodec
 codec=getattr(backtest.load_repair,'__self__',None)
 need(type(codec)is SuccessorCodec and codec.event==certificates.stml.catalog()['event'],
  'PTLA_RUNTIME_ACTUAL_INSTALLED_RETAINED_STML_CODEC')
 api=functions(parent);current=api.adopter()(parent,out,args,rows,out/history.OVERLAY,history.DAY,history.DIRECTORY)
 actual,proof=api.neutral(out,parent,rows);need(actual==current,'PTLA_RUNTIME_REAL_NEUTRAL21_BEFORE_FINANCE');exact(out/BOUNDARY,data.encoded(proof))
 with api.seed_view(old,out,parent,current,spec,out,rows) as view:
  seed=api.seed_resolver(view,parent,current,spec,out,rows,baseline);seed(view,current,spec)
  C=certificates.certificate_class(codec,parent,current,spec,baseline,view)
  def active(module,where,cp):
   need(module is backtest and Path(where)==view and cp==current and getattr(backtest.load_repair,'__self__',None)is codec,
    'PTLA_RUNTIME_ACTUAL_TWO_MODEL_CHAIN_AND_GENUINE_NEUTRAL21')
   return legacy.active_codec(SimpleNamespace(load_repair=codec.previous_owner().original_load),view,current)
  lower=active(backtest,view,current)
  from system_campaign_alder_date_v2 import AlderDateV2
  alder=AlderDateV2(Path(__file__).parent/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/history.PREFIX/'constructor-alder-source.json')
  candidate=C(out,lower,alder.native,baseline[0],seed=baseline[1],event_source=json.loads((view/'hydrated-uncertainty-event.json').read_bytes()))
  events=observations.observer(out,current)
  need(candidate.seed==baseline[1] and len(candidate.seed)==174 and len(events.terms)==35,
   'PTLA_RUNTIME_ACTUAL_COMPLETE174_CONSTRUCTOR_AND35_TERM_ORIGINAL_OBSERVER')
  exact(out/CONSTRUCTOR,data.encoded(dict(passed=True,current_checkpoint_sha256=current['sha256'],retained_rows=174,full_inputs=21,ordinary_terms=35,financial_sessions_advanced=0)))
  fn=api.retained_worker(dict(Certificate=C,preserve=api.preserve_archive,retained_seed=seed,active_codec=active,
   unchanged_input_phase=lambda target:target==spec,own_unchanged_input_phase=lambda target:False,unchanged_input_receipt=lambda cp,target:proof),parent,current,spec,baseline,view)
  with events:code=fn(current,out,args,observer,execution,spec,view)
 after=journal.read_checkpoint(out/'book/checkpoint.json.gz');history.full(out,after)
 need(after['repairs']==current['repairs'] and after['run']['input_sha256']==current['run']['input_sha256'],
  'PTLA_RUNTIME_ENTIRE21_INPUT_IDENTITY_UNCHANGED_THROUGH_FINANCE')
 return code


def suffix(root,parent,current,retained,rows,financial):
 import system_campaign_bounded_sensor_event_review as induction
 from system_campaign_uncertainty_math import growth
 def permissions(where,new,catalog,*,through,input_descriptors):
  allowed={};resolutions=[]
  for value in (dova.catalog(),certificates.stml.catalog()):
   old,found=certificates.event_review.event_permissions(where,parent,retained,new,value,through=through,input_descriptors=input_descriptors)
   need(old=={} and len(found)==1,'PTLA_REVIEW_BOTH_OLD_EVENTS_REVALIDATED_WITHOUT_NEW_PERMISSION')
   certificates.require_resolution(found[0],resources.fact()['historical_archive_resolutions']);resolutions.extend(found)
  return allowed,resolutions
 whole=FunctionType(induction.suffix.__code__,dict(induction.suffix.__globals__,permissions=permissions),induction.suffix.__name__,induction.suffix.__defaults__)
 return whole(root,parent,current,retained,rows,financial,certificates.stml.catalog(),growth=growth)


def review(parent,evidence,out,*,spec,old):
 from full_system_core import hosted
 hosted();old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 from research.pooled_vacancy_funding import journal
 rows=seed_rows(old,parent,spec);baseline=seed_reader()(old,parent,spec);current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz');api=functions(parent)
 adopted,proof=api.neutral(evidence,parent,rows);history.full(evidence,current)
 closure=resources.verify(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes())
 need(json.loads((evidence/resources.RECEIPT).read_bytes())==closure,'PTLA_REVIEW_COMPLETE127_RESOURCE_RECEIPT')
 need(json.loads((evidence/CONSTRUCTOR).read_bytes())==dict(passed=True,current_checkpoint_sha256=adopted['sha256'],retained_rows=174,full_inputs=21,ordinary_terms=35,financial_sessions_advanced=0),
  'PTLA_REVIEW_ACTUAL_NEUTRAL21_CONSTRUCTOR_AND35_TERM_CANARY')
 def unchanged(before,after,where,target):
  need(before==adopted and target==spec and after['repairs']==adopted['repairs'] and after['run']['input_sha256']==adopted['run']['input_sha256']
   and json.loads((Path(where)/legacy.UNCHANGED_INPUT).read_bytes())==proof,'PTLA_REVIEW_REAL_NEUTRAL21_THEN_UNCHANGED_INPUTS')
 with api.seed_view(old,out,parent,adopted,spec,evidence,rows) as view:
  seed=api.seed_resolver(view,parent,adopted,spec,evidence,rows,baseline)
  fn=dova.bound_body('review_retained',dict(validate_input=history.full,retained_seed=seed,own_unchanged_input_phase=lambda target:False,
   unchanged_input_phase=lambda target:target==spec,review_unchanged_input=unchanged,
   review_new_rows=lambda before,after,retained,new,financial,**kw:suffix(evidence,before,after,retained,new,financial)))
  fn(adopted,evidence,out,spec,view)
 observations.review(evidence,current,out);exact(out/BOUNDARY,data.encoded(proof))
