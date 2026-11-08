"""One original retained worker and two original bounded-event layers."""
import ast,gzip,json,shutil,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_p03_STML_source as source
import system_campaign_p03_STML_history as history
import system_campaign_p03_STML_resources as resources
import system_campaign_bounded_sensor_runtime_v2 as previous
import system_campaign_financial_uncertainty as legacy
import system_campaign_bounded_sensor_observers_v2 as observations
HERE=Path(__file__).parent
BOUNDARY=history.PREFIX+'/boundary-review.json'
CONSTRUCTOR=history.PREFIX+'/constructor-canary.json'
VIEW=history.PREFIX+'/origin/temporary-seed-view.json'
CLEANUP=history.PREFIX+'/origin/temporary-seed-view-cleanup.json'
PREPARATION=history.PREFIX+'/zero-financial-preparation.json'

def original_seed(old,parent,spec):
 baseline=previous.seed(old,parent,spec);resources.seed_contract(parent,baseline[1],baseline[2])
 raw=(Path(old)/'uncertainty-certificate.jsonl').read_bytes();lines=raw.splitlines(keepends=True)
 need(dict(rows=len(lines),**resources.pin(raw))==resources.fact()['raw_proof']
  and all(json.loads(v)['session']>parent['source_cursor'] for v in lines[152:]),'STML_RUNTIME_ALL159_RAW_ROWS_PRESERVED_ONLY152_SEEDED')
 return baseline

def adoption_tree():
 need(sha(Path(legacy.__file__).read_bytes())==previous.LEGACY_SHA,'STML_RUNTIME_WHOLE_CANONICAL_ADOPTER_SOURCE')
 fn,=[n for n in ast.parse(Path(legacy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
 site,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
 need(ast.unparse(site)=="{ORDINARY_ADOPTION: 'future-financial-overlay.json', DATE_ADOPTION: DATE_OVERLAY, MODEL_ADOPTION: 'branch-uncertainty-input.json'}",'STML_RUNTIME_ONE_ORIGINAL_ADOPTION_PATH_MAP')
 site.keys.append(ast.Constant(history.DIRECTORY));site.values.append(ast.Constant(history.OVERLAY))
 return ast.fix_missing_locations(fn)

def adopter():
 def boundary(root,directory,parent,overlay,earliest):
  need(directory==history.DIRECTORY and overlay==Path(history.OVERLAY).name and earliest==source.DAY,'STML_RUNTIME_EXACT_NESTED_OVERLAY_BOUNDARY')
  return legacy.boundary(root,directory,parent,history.OVERLAY,earliest)
 ns=dict(vars(legacy),boundary=boundary);exec(compile(ast.Module(body=[adoption_tree()],type_ignores=[]),'<whole-canonical-adopter-one-nested-STML-input>','exec'),ns)
 return ns['paused_own_adoption']

def prepare(parent,out,spec,old):
 from full_system_core import hosted
 hosted();source.parent_contract(parent,spec);out=Path(out)
 from research.pooled_vacancy_funding import backtest
 from system_campaign_bounded_sensor_preparation import no_financial_transitions,qualify_packets
 from system_campaign_second_bounded_codec import SuccessorCodec
 from system_campaign_bounded_sensor_lifecycle_data import evidence as old_evidence
 resources.canary(old,out);value=source.catalog()
 exact(out/history.CATALOG,source.encoded(value));exact(out/history.OVERLAY,source.encoded(source.document(parent,value=value)))
 native,market=source.hydrate(value,out/history.SOURCE)
 with no_financial_transitions(),SuccessorCodec(value['event'],source.evidence(value),native,
   previous_event=previous.catalog()['event'],previous_evidence=old_evidence(previous.catalog())) as codec:
  loaded=backtest.load_repair(out/history.OVERLAY,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
  packet=qualify_packets(parent,out/history.OVERLAY,loaded,codec,native,value,out)
 q=dict(passed=True,catalog_sha256=sha(source.encoded(value)),typed_document_sha256=sha((out/history.OVERLAY).read_bytes()),
  market_source_sha256=sha((out/history.SOURCE).read_bytes()),packet=packet,financial_sessions_advanced=0)
 exact(out/history.QUALIFICATION,source.encoded(q))
 result=dict(passed=True,parent_outer_sha256=parent['sha256'],root_admission_sha256=source.ROOT,parent_inputs=19,
  actual_neutral20_known=False,financial_sessions_advanced=0,packet_qualification_sha256=sha(source.encoded(q)),dependency_canary_sha256=sha((out/resources.CANARY).read_bytes()))
 exact(out/PREPARATION,source.encoded(result));return result

def require_preparation(parent,spec,proof,out):
 out=Path(out);p=json.loads((out/PREPARATION).read_bytes())
 need(p==proof['composite_preparation'] and p['passed'] is True and p['parent_outer_sha256']==parent['sha256']==spec['outer_sha256']
  and p['root_admission_sha256']==source.ROOT and p['parent_inputs']==19 and p['actual_neutral20_known'] is False
  and p['financial_sessions_advanced']==0 and sha((out/history.QUALIFICATION).read_bytes())==p['packet_qualification_sha256']
  and sha((out/resources.CANARY).read_bytes())==p['dependency_canary_sha256'],'STML_RUNTIME_STOPPED_PREFLIGHT_EXACT_PACKET_AND_COPY_CANARY')
 return True

def neutral(root,parent,rows):
 root=Path(root);actual=strict_json((root/history.NEUTRAL).read_bytes())
 proof=history.boundary(parent,actual,lambda n:(root/n).read_bytes(),rows)
 need(history.full(root,actual)['full_inputs']==20,'STML_RUNTIME_GENUINE_NEUTRAL20_COMPLETE19_HISTORY')
 return actual,proof

@contextmanager
def seed_view(old,out,parent,current,spec,evidence,rows):
 from full_system_core import hosted
 hosted();old,out,evidence=Path(old),Path(out),Path(evidence)
 original=(old/spec['selected_checkpoint']).read_bytes();history.boundary(parent,current,lambda n:(evidence/n).read_bytes(),rows)
 from system_campaign_p03_thor_runtime import owned_view_permissions
 with tempfile.TemporaryDirectory(prefix='p03-thor-owned-seed-view-',dir=out) as owned:
  view=Path(owned)/'view';shutil.copytree(old,view);permissions=owned_view_permissions(view,owned,out)
  names=(history.PARENT,history.NEUTRAL,history.PROOF,history.OVERLAY,history.SOURCE,history.CATALOG,history.QUALIFICATION,
   history.DIRECTORY+'-correlation-inputs.jsonl.gz','book/repairs/'+current['repairs'][-1]['filename'])
  inventory={}
  for n in names:
   raw=(evidence/n).read_bytes();exact(view/n,raw);inventory[n]=resources.pin(raw)
  watch=(evidence/'book/watch.jsonl').read_bytes();commit=current['journals']['watch'];need(sha(watch[:commit['bytes']])==commit['prefix_sha256'],'STML_RUNTIME_REAL_NEUTRAL_WATCH_PREFIX')
  (view/'book/watch.jsonl').write_bytes(watch[:commit['bytes']])
  need((view/spec['selected_checkpoint']).read_bytes()==original and resources.pin(original)==spec['selected_file'],
   'STML_RUNTIME_SELECTED_GENUINE606_FILE_NEVER_SUBSTITUTED')
  history.full(view,current)
  exact(out/VIEW,source.encoded(dict(passed=True,selected_checkpoint_replaced=False,selected_file=resources.pin(original),
   genuine_neutral_outer_sha256=current['sha256'],added_files=inventory,owned_copy_permissions=permissions,financial_sessions_advanced=0)))
  yield view
 need(not Path(owned).exists(),'STML_RUNTIME_TEMPORARY_SEED_VIEW_REMOVAL_OBSERVED')
 exact(out/CLEANUP,source.encoded(dict(passed=True,temporary_owned_copy_removal_observed=True,financial_sessions_advanced=0)))

def seed_resolver(view,parent,current,spec,evidence,rows,baseline):
 from system_campaign_bounded_sensor_seed_binding import bind_seed
 def contract(actual,target):
  need(actual==current and target==spec,'STML_RUNTIME_ONLY_GENUINE_NEUTRAL20_SEED')
  history.boundary(parent,current,lambda n:(Path(evidence)/n).read_bytes(),rows)
  return previous.retained_contract(parent,target,view)
 whole=bind_seed(validate_input=history.full,retained_contract=contract,retained_phase=previous.retained_phase)
 def seed(where,actual,target):
  need(Path(where)==view and actual==current and target==spec,'STML_RUNTIME_WHOLE_SEED_ONLY_OWNED_VIEW_AND_REAL_NEUTRAL')
  value=whole(view,current,spec);need(value==baseline and len(value[1])==152,'STML_RUNTIME_ENTIRE_NEUTRAL20_SEED_EQUALS_REAL606_SEED')
  return value
 return seed

def certificate(codec,native,market,parent,current,spec,baseline):
 from system_campaign_second_bounded_factory import first_factory,second_factory
 from system_campaign_p03_thor_qualification_reuse import bind_constructor
 old=codec.previous_owner();value=previous.catalog()
 first=first_factory(value['event'],value['market_source'],old,old.native,inherited_root=HERE)
 def consumed(seed,event,actual,target):
  need(actual==current and target==spec,'STML_RUNTIME_EXACT_CONSTRUCTOR_NEUTRAL_AND_ROOT')
  resources.seed_contract(parent,seed,baseline[2])
  need(event==value['event'] and event['native_session']<=seed[-1]['session'] and len(current['repairs'])==20
   and current['run']['state']==parent['run']['state'],'STML_RUNTIME_ONLY_ALREADY_CONSUMED_DOVA_CONSTRUCTOR')
 fn=FunctionType(bind_constructor.__code__,dict(bind_constructor.__globals__,constructor_seed=consumed),bind_constructor.__name__,bind_constructor.__defaults__)
 first=fn(first,value['event'],current,spec)
 return second_factory(source.catalog()['event'],market,codec,native,inherited_root=HERE,previous_class=first)

def ordinary(root,current,parent):
 history.full(root,current)
 observer=observations.observer(root,parent)
 contract=json.loads((Path(root)/observations.DIRECTORY/observations.CONTRACT).read_bytes())
 tail,_=observations.tail_materials(root,parent)
 need(len(observations.merge(contract['terms'],tail))==34,'STML_RUNTIME_ALL34_ORIGINAL_ORDINARY_TERMS')
 return observer

def preserve_archive(old,out):
 from full_system_core import hosted
 hosted()
 import system_campaign_uncertainty_archive as original
 path,proof=original.resolve(old);target=Path(out)/'book/pre-event'/path.name
 if not target.exists():return original.preserve(old,Path(out))
 need(target.read_bytes()==path.read_bytes(),'STML_RUNTIME_EXISTING_ORIGINAL_B19_ARCHIVE_EXACT_BYTES')
 exact(Path(out)/'uncertainty-event-archive-preservation.json',source.encoded(dict(**proof,preserved_as=target.relative_to(out).as_posix(),same_name_and_bytes=True)))
 return target

def retained_worker(bindings,parent,current,spec,baseline,view):
 import system_campaign_p03_thor_qualification_reuse as reuse
 original=previous.bound_body('run_retained',bindings)
 def qualification_contract(out,actual,target,old,rows,hashes,qualified):
  need(actual==current and target==spec and Path(old)==view and (hashes,rows,qualified)==baseline,
   'STML_RUNTIME_QUALIFICATION_ONLY_ACTUAL_NEUTRAL20_WHOLE152_SEED')
  resources.seed_contract(parent,rows,qualified);history.full(out,current)
 def present(*args):
  qualification_contract(*args);path=Path(args[0])/'branch-controller-qualification.json'
  if not path.exists():return False
  need(path.is_file() and not path.is_symlink() and path.read_bytes()==args[-1],
   'STML_RUNTIME_EXISTING_QUALIFICATION_ONLY_IDENTICAL_ORIGINAL_BYTES');return True
 def post(*args):
  qualification_contract(*args[:-1]);out=Path(args[0]);qualified=args[-2]
  need(type(args[-1])is bool and (out/'branch-controller-qualification.json').read_bytes()==qualified,
   'STML_RUNTIME_ORIGINAL_CREATE_OR_EXACT_REUSE_POSTCONDITION')
  exact(out/history.PREFIX/'qualification-reuse.json',source.encoded(dict(passed=True,retained_rows=152,
   qualification_sha256=sha(qualified),original_writer_used=not args[-1],financial_sessions_advanced=0)))
 tree=FunctionType(reuse.run_tree.__code__,dict(reuse.run_tree.__globals__,facts=resources.fact),reuse.run_tree.__name__,reuse.run_tree.__defaults__)()
 namespace=dict(original.__globals__,qualification_present=present,qualification_postcondition=post)
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-retained-worker-qualified-identical-DATA-reuse>','exec'),namespace)
 return namespace['run_retained']

def run(parent,out,args,rows,observer,execution,*,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);source.parent_contract(parent,spec);baseline=original_seed(old,parent,spec)
 resources.preserve(old,out)
 for n in (history.CATALOG,history.OVERLAY,history.SOURCE,history.QUALIFICATION):exact(out/n,(out/'parent-preflight'/n).read_bytes())
 value=source.catalog();native,market=source.hydrate(value,out/history.SOURCE)
 from system_campaign_second_bounded_codec import SuccessorCodec
 from system_campaign_bounded_sensor_lifecycle_data import evidence
 from research.pooled_vacancy_funding import backtest,journal
 with SuccessorCodec(value['event'],source.evidence(value),native,previous_event=previous.catalog()['event'],previous_evidence=evidence(previous.catalog())) as codec:
  source.parse_document(out/history.OVERLAY,parent)
  current=adopter()(parent,out,args,rows,out/history.OVERLAY,source.DAY,history.DIRECTORY)
  actual,proof=neutral(out,parent,rows);need(actual==current,'STML_RUNTIME_ACTUAL_NEUTRAL20_BEFORE_FINANCIAL_ENTRY');exact(out/BOUNDARY,source.encoded(proof))
  with seed_view(old,out,parent,current,spec,out,rows) as view:
   seeded=seed_resolver(view,parent,current,spec,out,rows,baseline);seeded(view,current,spec)
   C=certificate(codec,native,market,parent,current,spec,baseline)
   def active(module,where,cp):
    need(module is backtest and Path(where)==view and cp==current and getattr(backtest.load_repair,'__self__',None)is codec,'STML_RUNTIME_ACTUAL_TWO_CODECS_AND_GENUINE20')
    return legacy.active_codec(SimpleNamespace(load_repair=codec.previous_owner().original_load),view,current)
   lower=active(backtest,view,current)
   from system_campaign_alder_date_v2 import AlderDateV2
   alder=AlderDateV2(HERE/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/history.PREFIX/'constructor-alder-source.json')
   candidate=C(out,lower,alder.native,baseline[0],seed=baseline[1],event_source=json.loads((view/'hydrated-uncertainty-event.json').read_bytes()))
   events=ordinary(out,current,parent)
   need(candidate.seed==baseline[1] and candidate.append is not None and len(candidate.seed)==152,'STML_RUNTIME_ACTUAL_SHARED_CERTIFICATE_AND_ORIGINAL_OBSERVER_CONSTRUCTED')
   exact(out/CONSTRUCTOR,source.encoded(dict(passed=True,current_checkpoint_sha256=current['sha256'],retained_rows=152,full_inputs=20,original_observer_terms=34,financial_sessions_advanced=0)))
   fn=retained_worker(dict(Certificate=C,preserve=preserve_archive,retained_seed=seeded,active_codec=active,
    unchanged_input_phase=lambda s:s==spec,own_unchanged_input_phase=lambda s:False,unchanged_input_receipt=lambda cp,s:proof),parent,current,spec,baseline,view)
   with events:code=fn(current,out,args,observer,execution,spec,view)
  after=journal.read_checkpoint(out/'book/checkpoint.json.gz');history.full(out,after)
  need(after['repairs']==current['repairs'] and after['run']['input_sha256']==current['run']['input_sha256'],'STML_RUNTIME_ENTIRE20_FINANCIAL_SEGMENT_UNCHANGED_INPUT')
 return code

def suffix(root,parent,current,retained,rows,financial):
 from system_campaign_bounded_sensor_suffix_v2 import event_permissions
 import system_campaign_bounded_sensor_event_review as original
 from system_campaign_uncertainty_math import growth
 def permissions(where,new,catalog,*,through,input_descriptors):
  allowed,new_resolutions=original.permissions(where,new,catalog,through=through,input_descriptors=input_descriptors)
  old_allowed,old_resolutions=event_permissions(where,parent,retained,new,previous.catalog(),through=through,input_descriptors=input_descriptors)
  need(not old_allowed,'STML_REVIEW_NO_REEXECUTED_DOVA_PERMISSION')
  return allowed,old_resolutions+new_resolutions
 fn=FunctionType(original.suffix.__code__,dict(original.suffix.__globals__,permissions=permissions),original.suffix.__name__,original.suffix.__defaults__)
 return fn(root,parent,current,retained,rows,financial,source.catalog(),growth=growth)

def review(parent,evidence,out,*,spec,old):
 from full_system_core import hosted
 hosted();old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 from research.pooled_vacancy_funding import journal
 rows=seed_rows(old,parent,spec);baseline=original_seed(old,parent,spec);current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
 adopted,proof=neutral(evidence,parent,rows);history.full(evidence,current)
 closure=resources.verify(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes())
 need(json.loads((evidence/resources.RECEIPT).read_bytes())==closure,'STML_REVIEW_COMPLETE105_RESOURCE_PRESERVATION_RECEIPT')
 need(json.loads((evidence/CONSTRUCTOR).read_bytes())==dict(passed=True,current_checkpoint_sha256=adopted['sha256'],retained_rows=152,full_inputs=20,original_observer_terms=34,financial_sessions_advanced=0),
  'STML_REVIEW_ACTUAL_GENUINE20_CONSTRUCTOR_CANARY')
 def unchanged(before,after,where,target):
  need(before==adopted and target==spec and after['repairs']==adopted['repairs'] and after['run']['input_sha256']==adopted['run']['input_sha256']
   and json.loads((Path(where)/legacy.UNCHANGED_INPUT).read_bytes())==proof,'STML_REVIEW_REAL_NEUTRAL20_THEN_UNCHANGED_SEGMENT')
 with seed_view(old,out,parent,adopted,spec,evidence,rows) as view:
  seeded=seed_resolver(view,parent,adopted,spec,evidence,rows,baseline)
  fn=previous.bound_body('review_retained',dict(validate_input=history.full,retained_seed=seeded,own_unchanged_input_phase=lambda s:False,
   unchanged_input_phase=lambda s:s==spec,review_unchanged_input=unchanged,
   review_new_rows=lambda before,after,retained,new,financial,**k:suffix(evidence,before,after,retained,new,financial)))
  fn(adopted,evidence,out,spec,view)
 # Validate the old descriptor axis without narrowing the actual current book.
 history.full(evidence,current)
 old_tail=observations.tail_materials
 observations.tail_materials=lambda root,cp:old_tail(root,parent) if cp==current else old_tail(root,cp)
 try:observations.review(evidence,current,out)
 finally:observations.tail_materials=old_tail
 exact(out/BOUNDARY,source.encoded(proof))
