"""Canonical neutral append and whole original retained P07 financial workers."""
import ast,json,shutil,tempfile
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_p07_KDNY_retained as retained
import system_campaign_p07_KDNY_certificate as factories
import system_campaign_p07_KDNY_preparation as packets
resources,history,source=retained.resources,retained.history,retained.source
legacy=retained.bodies.legacy
PREPARATION=history.PREFIX+'/zero-financial-preparation.json'
BOUNDARY=history.PREFIX+'/neutral-boundary-review.json'
CONSTRUCTOR=history.PREFIX+'/constructor-canary.json'
VIEW=history.PREFIX+'/temporary-seed-view.json'
CLEANUP=history.PREFIX+'/temporary-seed-view-cleanup.json'


def prepare(parent,out,spec,old):
 from full_system_core import hosted
 hosted();source.parent_contract(parent,spec);out,old=Path(out),Path(old)
 from research.pooled_vacancy_funding import backtest
 from system_campaign_bounded_sensor_preparation import no_financial_transitions
 before=source.encoded(parent);forbidden=(out/'book/checkpoint.json.gz',out/history.NEUTRAL)
 need(not any(p.exists() for p in forbidden),'KDNY_RUNTIME_PREFLIGHT_NO_FINANCIAL_OR_NEW_NEUTRAL_BOOK')
 with no_financial_transitions():
  baseline=retained.seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2]);resources.canary(old,out)
  value=source.catalog();codec=retained.installed()
  exact(out/history.CATALOG,source.encoded(value));exact(out/history.OVERLAY,source.encoded(source.document(parent,value=value)))
  need((out/history.SOURCE).read_bytes()==source.encoded(value['market_source'])
   and (out/history.PRIVATE).read_bytes()==source.encoded(value['original_chinook_private_event']),
   'KDNY_RUNTIME_ACTUAL_ORIGINAL_FROZEN_SOURCE_HYDRATION_BEFORE_PREPARATION')
  objects=[backtest.load_repair(old/'book/repairs'/d['filename'],resume_session=d['resume_session'],
   predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in parent['repairs']]
  loaded=backtest.load_repair(out/history.OVERLAY,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
  need(any(loaded is obj for obj in codec.objects),'KDNY_RUNTIME_ACTUAL_INSTALLED_NEW_TYPED_OBJECT')
  result=packets.qualify_packets(parent,out/history.OVERLAY,loaded,codec.native,value,objects)
  q=dict(schema='research.P07-KDNY-zero-financial-packet-preparation/1',passed=True,catalog_sha256=sha(source.encoded(value)),
   typed_document_sha256=sha((out/history.OVERLAY).read_bytes()),market_source_sha256=value['market_source_sha256'],
   original_private_event_sha256=value['original_chinook_private_event_sha256'],financial_sessions_advanced=0,
   retained_inputs=[dict(descriptor=d,loaded_sha256=obj.sha256) for d,obj in zip(parent['repairs'],objects)],packet=result)
  exact(out/history.QUALIFICATION,source.encoded(q));history.document(parent,lambda n:(out/n).read_bytes())
 need(source.encoded(parent)==before and not any(p.exists() for p in forbidden),'KDNY_RUNTIME_PREFLIGHT_ZERO_PARENT_CHANGE_OR_ADOPTION')
 result=preparation(parent,spec,out);exact(out/PREPARATION,source.encoded(result));return result


def preparation(parent,spec,root):
 root=Path(root);source.parent_contract(parent,spec);history.document(parent,lambda n:(root/n).read_bytes())
 canary=json.loads((root/resources.CANARY).read_bytes())
 need(canary==dict(passed=True,requirements=216,logical_bytes=366268272,complete_shared_copier_and_verifier=True,
  copy_removal_observed=True,financial_sessions_advanced=0,actual_neutral27_known=False),'KDNY_RUNTIME_COMPLETE_ACTUAL_COPY_CANARY')
 names=(history.PARENT,history.OVERLAY,history.CATALOG,history.SOURCE,history.PRIVATE,history.QUALIFICATION,resources.CANARY,resources.RECEIPT)
 return dict(schema='research.P07-KDNY-stopped-preflight-preparation/1',passed=True,root_admission_sha256=source.ROOT,
  parent_outer_sha256=parent['sha256'],financial_sessions_advanced=0,actual_neutral27_known=False,
  files={n:resources.pin((root/n).read_bytes()) for n in names})


def require_preparation(parent,spec,proof,out):
 result=preparation(parent,spec,out)
 need(result==proof['composite_preparation']==json.loads((Path(out)/PREPARATION).read_bytes()),
  'KDNY_RUNTIME_EXACT_POSITIVELY_STOPPED_PREPARATION_BEFORE_FINANCE')
 return True


def adoption_tree():
 need(sha(Path(legacy.__file__).read_bytes())==retained.bodies.LEGACY_SHA,'KDNY_RUNTIME_WHOLE_ORIGINAL_CANONICAL_ADOPTER')
 fn,=[n for n in ast.parse(Path(legacy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
 mapping,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
 need(ast.unparse(mapping)=="{ORDINARY_ADOPTION: 'future-financial-overlay.json', DATE_ADOPTION: DATE_OVERLAY, MODEL_ADOPTION: 'branch-uncertainty-input.json'}",
  'KDNY_RUNTIME_ONE_ORIGINAL_ADOPTION_PATH_MAP')
 mapping.keys.append(ast.Constant(history.DIRECTORY));mapping.values.append(ast.Constant(history.OVERLAY));return ast.fix_missing_locations(fn)


def adopter():
 def boundary(root,directory,parent,overlay,earliest):
  need(directory==history.DIRECTORY and overlay==Path(history.OVERLAY).name and earliest==source.NATIVE,
   'KDNY_RUNTIME_EXACT_NESTED_TYPED_INPUT_BOUNDARY')
  return legacy.boundary(root,directory,parent,history.OVERLAY,earliest)
 scope=dict(vars(legacy),boundary=boundary)
 exec(compile(ast.Module(body=[adoption_tree()],type_ignores=[]),'<whole-canonical-adopter-one-KDNY-input>','exec'),scope)
 return scope['paused_own_adoption']


def neutral(root,parent,rows):
 root=Path(root);current=strict_json((root/history.NEUTRAL).read_bytes())
 proof=history.boundary(parent,current,lambda n:(root/n).read_bytes(),rows)
 need(history.full(root,current)['full_inputs']==27,'KDNY_RUNTIME_GENUINE_NEUTRAL27_ENTIRE26_HISTORY')
 return current,proof


@contextmanager
def seed_view(old,out,parent,current,spec,evidence,rows):
 from full_system_core import hosted
 hosted();old,out,evidence=Path(old),Path(out),Path(evidence)
 original=(old/spec['selected_checkpoint']).read_bytes();history.boundary(parent,current,lambda n:(evidence/n).read_bytes(),rows)
 from system_campaign_p07_vivo_runtime import owned_view_permissions
 with tempfile.TemporaryDirectory(prefix='p07-vivo-owned-seed-view-',dir=out) as owned:
  view=Path(owned)/'view';shutil.copytree(old,view);permissions=owned_view_permissions(view,owned,out)
  names=(history.PARENT,history.NEUTRAL,history.PROOF,history.OVERLAY,history.SOURCE,history.CATALOG,history.QUALIFICATION,history.PRIVATE,
   history.DIRECTORY+'-correlation-inputs.jsonl.gz','book/repairs/'+current['repairs'][-1]['filename'])
  inventory={}
  for name in names:
   raw=(evidence/name).read_bytes();exact(view/name,raw);inventory[name]=resources.pin(raw)
  watch=(evidence/'book/watch.jsonl').read_bytes();commit=current['journals']['watch']
  need(sha(watch[:commit['bytes']])==commit['prefix_sha256'],'KDNY_RUNTIME_REAL_NEUTRAL_WATCH_PREFIX')
  (view/'book/watch.jsonl').write_bytes(watch[:commit['bytes']])
  need((view/spec['selected_checkpoint']).read_bytes()==original and resources.pin(original)==spec['selected_file'],
   'KDNY_RUNTIME_GENUINE_SELECTED1403_GZIP_NEVER_REPLACED')
  history.full(view,current)
  exact(out/VIEW,source.encoded(dict(passed=True,selected_checkpoint_replaced=False,selected_file=resources.pin(original),
   genuine_neutral_outer_sha256=current['sha256'],added_files=inventory,owned_copy_permissions=permissions,financial_sessions_advanced=0)))
  yield view
 need(not Path(owned).exists(),'KDNY_RUNTIME_TEMPORARY_OWNED_SEED_VIEW_REMOVAL_OBSERVED')
 exact(out/CLEANUP,source.encoded(dict(passed=True,temporary_owned_copy_removal_observed=True,financial_sessions_advanced=0)))


def neutral_seed(view,parent,current,spec,evidence,rows,baseline):
 from system_campaign_bounded_sensor_seed_binding import bind_seed
 def contract(actual,target):
  need(actual==current and target==spec,'KDNY_RUNTIME_ONLY_GENUINE_NEUTRAL27_SEED')
  history.boundary(parent,current,lambda n:(Path(evidence)/n).read_bytes(),rows);return retained.physical(parent,spec)
 whole=bind_seed(validate_input=history.full,retained_contract=contract,retained_phase=retained.phase)
 def seed(where,actual,target):
  need(Path(where)==view and actual==current and target==spec,'KDNY_RUNTIME_ONLY_OWNED_VIEW_AND_ACTUAL_NEUTRAL27')
  value=whole(view,current,spec);need(value==baseline and len(value[1])==949,'KDNY_RUNTIME_ENTIRE_ORIGINAL949_SEED_UNCHANGED')
  resources.seed_contract(parent,value[1],value[2]);return value
 return seed


def preserve_archive(old,out):
 from full_system_core import hosted
 hosted()
 import system_campaign_uncertainty_archive as original
 old,out=Path(old),Path(out);path,_=original.resolve(old);target=out/'book/pre-event'/path.name
 if not target.exists():return original.preserve(old,out)
 need(target.read_bytes()==path.read_bytes(),'KDNY_RUNTIME_EXISTING_ORIGINAL_B19_ARCHIVE_IDENTICAL')
 name='uncertainty-event-archive-preservation.json';raw=(old/name).read_bytes()
 need(resources.pin(raw)=={k:resources.fact()['resources'][name][k] for k in ('bytes','sha256')},
  'KDNY_RUNTIME_EXACT_ORIGINAL_PRESERVATION_RECEIPT')
 exact(out/name,raw);return target


def retained_worker(bindings,parent,current,spec,baseline,view):
 import system_campaign_p03_thor_qualification_reuse as reuse
 original=retained.bodies.bound_body('run_retained',bindings)
 def contract(out,actual,target,old,rows,hashes,qualified):
  need(actual==current and target==spec and Path(old)==view and (hashes,rows,qualified)==baseline,
   'KDNY_RUNTIME_QUALIFICATION_EXACT_NEUTRAL27_WHOLE949_SEED')
  resources.seed_contract(parent,rows,qualified);history.full(out,current)
 def present(*args):
  contract(*args);path=Path(args[0])/'branch-controller-qualification.json'
  if not path.exists():return False
  need(path.is_file() and not path.is_symlink() and path.read_bytes()==args[-1],
   'KDNY_RUNTIME_EXISTING_QUALIFICATION_ONLY_IDENTICAL_ORIGINAL_BYTES');return True
 def post(*args):
  contract(*args[:-1]);out=Path(args[0])
  need(type(args[-1])is bool and (out/'branch-controller-qualification.json').read_bytes()==args[-2],
   'KDNY_RUNTIME_ORIGINAL_EXCLUSIVE_CREATE_OR_EXACT_REUSE_POSTCONDITION')
  exact(out/history.PREFIX/'qualification-reuse.json',source.encoded(dict(passed=True,retained_rows=949,
   qualification_sha256=sha(args[-2]),original_writer_used=not args[-1],financial_sessions_advanced=0)))
 tree=FunctionType(reuse.run_tree.__code__,dict(reuse.run_tree.__globals__,facts=resources.fact),reuse.run_tree.__name__,reuse.run_tree.__defaults__)()
 scope=dict(original.__globals__,qualification_present=present,qualification_postcondition=post)
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-retained-worker-original-exclusive-writer-or-identical-reuse>','exec'),scope)
 return scope['run_retained']


def ordinary(root,out):
 from full_system_core import hosted
 hosted()
 from system_campaign_financial_partial import root_spec
 previous=retained.previous;vivo=previous.vivo
 prior_spec=root_spec('P07',vivo.data.ROOT);prior=strict_json((Path(root)/vivo.boundary.SELECTED).read_bytes())
 vivo.data.parent_contract(prior,prior_spec);api=previous.vivo_input.api(prior,prior_spec)
 event=previous.legacy_future_event(root,prior,api);event.out=Path(out)/vivo.OBSERVATION;event.out.mkdir(parents=True,exist_ok=True)
 return event


def run(parent,out,args,rows,observer,execution,*,spec,old):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);source.parent_contract(parent,spec)
 baseline=retained.seed_reader()(old,parent,spec);resources.preserve(old,out,parent,baseline[1],baseline[2])
 for name in (history.CATALOG,history.OVERLAY,history.SOURCE,history.PRIVATE,history.QUALIFICATION):exact(out/name,(out/'parent-preflight'/name).read_bytes())
 codec=retained.installed();source.parse_document(out/history.OVERLAY,parent)
 current=adopter()(parent,out,args,rows,out/history.OVERLAY,source.NATIVE,history.DIRECTORY)
 actual,proof=neutral(out,parent,rows);need(actual==current,'KDNY_RUNTIME_ACTUAL_NEUTRAL27_BEFORE_FINANCIAL_ENTRY');exact(out/BOUNDARY,source.encoded(proof))
 with seed_view(old,out,parent,current,spec,out,rows) as view:
  seed=neutral_seed(view,parent,current,spec,out,rows,baseline);seed(view,current,spec)
  with retained.growth_scope(current,spec) as mixed:
   C=factories.certificate_class(codec,codec.native,source.catalog()['market_source'],parent,current,spec,baseline,view,mixed=mixed)
   def active(module,where,cp):
    need(Path(where)==view and cp==current,'KDNY_RUNTIME_ACTUAL_NEUTRAL27_ACTIVE_BRANCH_ONLY')
    return retained.active_branch(module,view,current)
   lower=active(None,view,current)
   from system_campaign_alder_date_v2 import AlderDateV2
   alder=AlderDateV2(Path(__file__).parent/'system-campaign-alder-unresolved-date.json');alder.hydrate(out/history.PREFIX/'constructor-alder-source.json')
   candidate=C(out,lower,alder.native,baseline[0],seed=baseline[1],event_source=json.loads((view/'hydrated-uncertainty-event.json').read_bytes()))
   events=ordinary(view,out);distribution=retained.previous.inputs.observer(out)
   need(candidate.seed==baseline[1] and len(candidate.seed)==949 and candidate.append is not None,
    'KDNY_RUNTIME_ACTUAL_SHARED_CERTIFICATE_AND_ORIGINAL_OBSERVERS_CONSTRUCTED')
   exact(out/CONSTRUCTOR,source.encoded(dict(passed=True,current_checkpoint_sha256=current['sha256'],retained_rows=949,
    full_inputs=27,ordinary_terms=23,BWA_observer_preserved=True,financial_sessions_advanced=0)))
   fn=retained_worker(dict(Certificate=C,preserve=preserve_archive,retained_seed=seed,active_codec=active,
    unchanged_input_phase=lambda s:s==spec,own_unchanged_input_phase=lambda s:False,unchanged_input_receipt=lambda cp,s:proof),parent,current,spec,baseline,view)
   with events,distribution:code=fn(current,out,args,observer,execution,spec,view)
 from research.pooled_vacancy_funding import journal
 after=journal.read_checkpoint(out/'book/checkpoint.json.gz');history.full(out,after)
 need(after['repairs']==current['repairs'] and after['run']['input_sha256']==current['run']['input_sha256'],
  'KDNY_RUNTIME_ENTIRE27_INPUT_FINANCIAL_SEGMENT_UNCHANGED')
 return code


def suffix(root,parent,current,retained_rows,rows,financial,mixed):
 import system_campaign_bounded_sensor_event_review as original
 def permissions(where,new,catalog,*,through,input_descriptors):
  history.full(where,current);old_parent=history.archived_parent(lambda n:(Path(where)/n).read_bytes())
  value=retained.original_lifecycle.catalog();axis=history.previous.actual_event_descriptors(where,old_parent['repairs'])
  old_allowed,old_resolutions=original.permissions(where,retained_rows,value,through=old_parent['source_cursor'],input_descriptors=axis)
  need(len(old_resolutions)==1 and old_resolutions[0] in resources.fact()['historical_archive_resolutions']
   and not(set(old_allowed)&{source.digest(v) for v in new}),'KDNY_REVIEW_PRIOR_ABMD_ARCHIVE_REVALIDATED_NO_REPLAY')
  allowed,resolutions=original.permissions(where,new,catalog,through=through,input_descriptors=input_descriptors)
  return allowed,old_resolutions+resolutions
 fn=FunctionType(original.suffix.__code__,dict(original.suffix.__globals__,permissions=permissions),original.suffix.__name__,original.suffix.__defaults__)
 return fn(root,parent,current,retained_rows,rows,financial,source.catalog(),growth=mixed)


def review(parent,evidence,out,*,spec,old):
 from full_system_core import hosted
 hosted();old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 from research.pooled_vacancy_funding import journal
 rows=seed_rows(old,parent,spec);baseline=retained.seed_reader()(old,parent,spec);current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
 adopted,proof=neutral(evidence,parent,rows);history.full(evidence,current)
 need(resources.verify(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes())
  ==json.loads((evidence/resources.RECEIPT).read_bytes()),'KDNY_REVIEW_COMPLETE216_RESOURCE_PRESERVATION')
 need(json.loads((evidence/CONSTRUCTOR).read_bytes())==dict(passed=True,current_checkpoint_sha256=adopted['sha256'],
  retained_rows=949,full_inputs=27,ordinary_terms=23,BWA_observer_preserved=True,financial_sessions_advanced=0),
  'KDNY_REVIEW_ACTUAL_NEUTRAL27_SHARED_CONSTRUCTOR_CANARY')
 def unchanged(before,after,where,target):
  need(before==adopted and target==spec and after['repairs']==adopted['repairs']
   and after['run']['input_sha256']==adopted['run']['input_sha256']
   and json.loads((Path(where)/legacy.UNCHANGED_INPUT).read_bytes())==proof,
   'KDNY_REVIEW_REAL_NEUTRAL27_AND_UNCHANGED_SEGMENT')
 with seed_view(old,out,parent,adopted,spec,evidence,rows) as view:
  seed=neutral_seed(view,parent,adopted,spec,evidence,rows,baseline)
  with retained.growth_scope(adopted,spec) as mixed:
   fn=retained.bodies.bound_body('review_retained',dict(validate_input=history.full,retained_seed=seed,own_unchanged_input_phase=lambda s:False,
    unchanged_input_phase=lambda s:s==spec,review_unchanged_input=unchanged,
    review_new_rows=lambda before,after,retained_rows,new,financial,**k:suffix(evidence,before,after,retained_rows,new,financial,mixed)))
   fn(adopted,evidence,out,spec,view)
 retained.previous.vivo.review_cash(evidence,current,out)
 result=retained.previous.inputs.review_event(retained.previous.inputs.payload(),evidence,current)
 exact(out/retained.previous.EVENT_REVIEW,source.encoded(result));exact(out/BOUNDARY,source.encoded(proof))
