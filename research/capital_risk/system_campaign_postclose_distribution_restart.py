"""Hosted complete saved P07 restart; original workers and financial operations."""
import ast,json,shutil,tempfile
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_postclose_distribution_models as models
import system_campaign_postclose_distribution_runtime as inputs
import system_campaign_postclose_distribution_resources as resources
import system_campaign_p07_vivo_runtime as vivo
import system_campaign_p07_vivo_api as vivo_input
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
from full_system_benchmark import need
saved=models.saved
history=models.history
legacy=saved.uncertainty
HERE=Path(__file__).parent
FIELD='selected_postclose_distribution_inputs'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
PROFILE='P07-BWA-whole-profile-qualification.json'
RETAINED_SHA='87b4c0110e3d46af35491389fd301cb49e11ac6b71d8ec0610e74f3c3a417968'
CANARY='continuation-constructor-canary.json'
BOUNDARY=resources.PREFIX+'/neutral-boundary-review.json'
EVENT_REVIEW=resources.PREFIX+'/actual-distribution-review.json'

def candidate(spec):
 return isinstance(spec,dict) and spec.get('arm')=='P07' and spec.get('root_admission_sha256')==saved.ROOT

def declaration(spec):
 need(candidate(spec) and (HERE/PROFILE).is_file(),'POSTCLOSE_RESTART_WHOLE_PROFILE_NOT_QUALIFIED')
 saved.metadata(spec);raw=(HERE/PROFILE).read_bytes();q=json.loads(raw)
 need(q['passed'] is True and q['root_admission_sha256']==saved.ROOT
  and q['financial_authority'] is q['canonical_runtime_executed'] is q['actual_neutral26_known'] is False,
  'POSTCLOSE_RESTART_EXPLICIT_COMPLETE_SOURCE_PROFILE_WITH_REAL_HOSTED_GATES')
 from system_campaign_postclose_distribution_entry import source_names
 need(set(q['files'])==set(source_names(profile=False))|{'system_campaign_financial_resume.py'},
  'POSTCLOSE_RESTART_COMPLETE_SOURCE_PROFILE_INVENTORY')
 for n,pin in q['files'].items():
  value=(HERE/n).read_bytes();need(dict(bytes=len(value),sha256=sha(value))==pin,'POSTCLOSE_RESTART_WHOLE_PROFILE_BYTES:'+n)
 return dict(schema='research.P07-postclose-distribution-financial-declaration/1',root_admission_sha256=saved.ROOT,
  parent_outer_sha256=spec['outer_sha256'],parent_inputs=25,required_actual_neutral_inputs=26,
  committed_seed_rows=929,profile_qualification_sha256=sha(raw),genuine_adoption_and_constructor_required=True)

def require_request(request,spec):
 need(candidate(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
  and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False
  and 'P07' in request.get('arms',[]) and request.get(FIELD)=={'P07':declaration(spec)}
  and request['admitted_checkpoints']['P07']==spec['outer_sha256']
  and type(request['maximum_parallel_financial_workers'])is int and 1<=request['maximum_parallel_financial_workers']<=4
  and request['maximum_parallel_readonly_workers']==0,'POSTCLOSE_RESTART_ONLY_EXACT_QUALIFIED_FINANCIAL_REQUEST')
 return True

def boundary(root,parent,spec,rows):
 root=Path(root);names=history.paths(spec);member=lambda n:(root/n).read_bytes()
 neutral=strict_json(member(names['NEUTRAL']))
 proof=history.boundary(parent,neutral,spec,member,rows,document=models.document,packet_qualification=inputs.packet_qualification)
 need(models.full(root,neutral)['full_inputs']==26,'POSTCLOSE_RESTART_COMPLETE_GENUINE_NEUTRAL26')
 return neutral,proof

def adoption_tree(raw,spec):
 need(sha(raw)==saved.retained.U_SHA,'POSTCLOSE_RESTART_WHOLE_ORIGINAL_CANONICAL_ADOPTER')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
 mapping,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
 need(ast.unparse(mapping)=="{ORDINARY_ADOPTION: 'future-financial-overlay.json', DATE_ADOPTION: DATE_OVERLAY, MODEL_ADOPTION: 'branch-uncertainty-input.json'}",
  'POSTCLOSE_RESTART_ONE_ORIGINAL_DIRECTORY_MAP')
 names=history.paths(spec);mapping.keys.append(ast.Constant(names['DIRECTORY']));mapping.values.append(ast.Constant(names['OVERLAY']))
 return ast.fix_missing_locations(fn)

def adopter(spec):
 names=history.paths(spec)
 def bound(root,directory,parent,overlay,earliest):
  need(directory==names['DIRECTORY'] and overlay==Path(names['OVERLAY']).name,
   'POSTCLOSE_RESTART_ONLY_SELECTED_NESTED_BOUNDARY')
  return legacy.boundary(root,directory,parent,names['OVERLAY'],earliest)
 scope=dict(vars(legacy),boundary=bound)
 exec(compile(ast.Module(body=[adoption_tree(Path(legacy.__file__).read_bytes(),spec)],type_ignores=[]),
  '<whole-original-adopter-one-postclose-input-and-complete-boundary-path>','exec'),scope)
 return scope['paused_own_adoption']

@contextmanager
def seed_view(old,out,parent,neutral,spec,evidence,rows):
 from full_system_core import hosted
 hosted();old,out,evidence=Path(old),Path(out),Path(evidence);names=history.paths(spec)
 original=(old/spec['selected_checkpoint']).read_bytes()
 need(dict(bytes=len(original),sha256=sha(original))==spec['selected_file'] and strict_json(original)==parent,
  'POSTCLOSE_RESTART_GENUINE_SELECTED25_NEVER_SUBSTITUTED')
 actual,_=boundary(evidence,parent,spec,rows);need(actual==neutral,'POSTCLOSE_RESTART_ONLY_ACTUAL_NEUTRAL_SEED_VIEW')
 with tempfile.TemporaryDirectory(prefix='p07-vivo-owned-seed-view-',dir=out) as owned:
  view=Path(owned)/'view';shutil.copytree(old,view);permissions=vivo.owned_view_permissions(view,owned,out)
  files=[names[k] for k in ('PARENT','NEUTRAL','PROOF','OVERLAY','PAYLOAD','QUALIFICATION','RETAINED_QUALIFICATION')]
  files.extend((names['DIRECTORY']+'-correlation-inputs.jsonl.gz','book/repairs/'+neutral['repairs'][-1]['filename']))
  inventory={}
  for n in files:
   raw=(evidence/n).read_bytes();exact(view/n,raw);inventory[n]=dict(bytes=len(raw),sha256=sha(raw))
  watch=(evidence/'book/watch.jsonl').read_bytes();commit=neutral['journals']['watch']
  need(sha(watch[:commit['bytes']])==commit['prefix_sha256'],'POSTCLOSE_RESTART_ACTUAL_NEUTRAL_WATCH_PREFIX')
  (view/'book/watch.jsonl').write_bytes(watch[:commit['bytes']])
  need((view/spec['selected_checkpoint']).read_bytes()==original,'POSTCLOSE_RESTART_VIEW_STILL_HAS_ORIGINAL25_GZIP')
  exact(out/resources.PREFIX/'temporary-seed-view-receipt.json',saved.encoded(dict(passed=True,selected_checkpoint_replaced=False,
   actual_added_files=inventory,owned_copy_permissions=permissions,financial_sessions_advanced=0)))
  yield view
 need(not Path(owned).exists(),'POSTCLOSE_RESTART_OWNED_SEED_VIEW_CLEANUP_OBSERVED')
 exact(out/resources.PREFIX/'temporary-seed-view-cleanup.json',saved.encoded(dict(passed=True,owned_copy_removed=True,financial_sessions_advanced=0)))

def neutral_seed(view,parent,neutral,spec,evidence,rows,baseline):
 from full_system_core import hosted
 hosted();view,evidence=Path(view),Path(evidence)
 def contract(current,target):
  need(current==neutral and target==spec,'POSTCLOSE_RESTART_SEED_ONLY_REAL_NEUTRAL26')
  actual,_=boundary(evidence,parent,spec,rows);need(actual==current,'POSTCLOSE_RESTART_SEED_BOUNDARY_AT_USE')
  return saved.physical_contract(parent,spec)
 scope=dict(vars(legacy),retained_contract=contract,retained_phase=saved.phase,validate_input=models.full)
 exec(compile(ast.Module(body=[saved.retained.seed_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-retained-seed-complete-real26-history>','exec'),scope)
 whole=scope['retained_seed']
 def seed(where,current,target):
  need(Path(where)==view and current==neutral and target==spec,'POSTCLOSE_RESTART_ONLY_ACTUAL_OWNED_SEED_VIEW')
  result=whole(view,current,target)
  need(result==baseline and len(result[1])==929,'POSTCLOSE_RESTART_ALL929_AND_QUALIFICATION_IDENTICAL_NO_REPLAY')
  saved.literal_prefix((view/'uncertainty-certificate.jsonl').read_bytes(),result[1],spec);return result
 return seed

def proof_tree(raw):
 need(sha(raw)==RETAINED_SHA,'POSTCLOSE_RESTART_WHOLE_ORIGINAL_POINT_WITNESS_CONTEXT')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='proof_scope']
 saved.models.replace_count(fn,'(24, 25)','(25, 26)',1,'POSTCLOSE_RESTART_ONE_ACTUAL_INPUT_COUNT_SITE')
 return ast.fix_missing_locations(fn)

def growth_scope(root,namespace):
 scope=dict(vars(saved.retained),data=SimpleNamespace(**dict(vars(saved.retained.data),ROOT=saved.ROOT)))
 exec(compile(ast.Module(body=[proof_tree(Path(saved.retained.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-point-witness-context-exact-current-root>','exec'),scope)
 def proof(current,spec):
  models.full(root,current);return scope['proof_scope'](current,spec)
 fn=saved.retained.growth_scope
 bound=FunctionType(fn.__code__,dict(fn.__globals__,proof_scope=proof),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__;return bound(namespace)

def without_distribution(installed):
 owner=getattr(installed,'__self__',None)
 if not isinstance(owner,inputs.typed.InputCodec):return installed
 need(owner.active is True and installed==owner.load and owner.document==inputs.typed.document()
  and callable(owner.original_load),'POSTCLOSE_RESTART_ONLY_EXACT_ACTIVE_DISTRIBUTION_LAYER_CAN_BE_INSPECTED')
 return owner.original_load

@contextmanager
def projection(root):
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 owner=getattr(backtest.load_repair,'__self__',None)
 if isinstance(owner,inputs.typed.InputCodec):
  without_distribution(backtest.load_repair)
  need((Path(root)/history.paths(inputs.selected_spec())['OVERLAY']).read_bytes()==inputs.source.encoded(owner.document),
   'POSTCLOSE_RESTART_REUSED_LAYER_EXACT_SOURCE_BYTES')
  yield owner
 else:
  with inputs.ProjectionContext(root) as ctx:yield ctx.codec

def base_api(root,current,spec):
 from full_system_core import hosted
 hosted();need(candidate(spec),'POSTCLOSE_RESTART_ONLY_CURRENT_ADMITTED_PARENT')
 models.full(root,current);life=models.lifecycle();value=life.catalog()
 result=life.runtime_api(root,current,spec,value);scope=result.run.__globals__
 previous=scope['qualified_lower_loader'];scope['qualified_lower_loader']=lambda installed:previous(without_distribution(installed))
 old_chain=scope['original_chain']
 @contextmanager
 def chain(where,actual,target):
  with old_chain(where,actual,target) as previous_chain:
   if len(actual['repairs'])==26:
    with projection(where):yield previous_chain
   else:yield previous_chain
 scope['original_chain']=chain;return scope,life

def worker_tree(raw):
 need(sha(raw)==saved.retained.models_original.plan()['source_files'][Path(saved.retained.additional_runtime.__file__).name],
  'POSTCLOSE_RESTART_WHOLE_ORIGINAL_RETAINED_FINANCIAL_WORKER')
 tree=saved.retained.legacy_original.runtime_tree(raw)
 fn,=[n for n in tree.body if n.name=='run_retained']
 block,=[n for n in ast.walk(fn) if isinstance(n,ast.With)
  and [ast.unparse(v.context_expr) for v in n.items]==['ordinary_observers(out, out, p, cp0)']]
 need(len(block.body)==1 and ast.unparse(block.body[0])=='code = backtest.main(args)',
  'POSTCLOSE_RESTART_ONE_ORIGINAL_FINANCIAL_MAIN_SITE')
 block.body.insert(0,ast.parse('constructor_canary(cp,out,certificate)').body[0]);return ast.fix_missing_locations(fn)

def whole_api(view,neutral,parent,spec,evidence,rows,baseline):
 from full_system_core import hosted
 hosted();view=Path(view);scope,life=base_api(view,neutral,spec);value=life.catalog()
 scope['preserve_event']=preserved_archive(scope['preserve_event'],view,evidence,spec)
 seed=neutral_seed(view,parent,neutral,spec,evidence,rows,baseline)
 scope['retained_seed']=lambda where,current,target,p:seed(where,current,target)
 scope['growth_scope']=growth_scope(view,scope)
 def joint(mixed):
  from research.pooled_vacancy_funding import backtest
  installed=without_distribution(backtest.load_repair);scope['qualified_lower_loader'](backtest.load_repair)
  codec=getattr(installed,'__self__',None)
  need(codec is not None and codec.event==value['event'] and codec.objects,'POSTCLOSE_RESTART_ACTUAL_ORIGINAL_ABMD_FACTORY_CODEC')
  return saved.certificate_class(value['event'],value['market_source'],codec,codec.native,mixed=mixed,
   inherited_root=life.models.legacy.HERE,retained_root=view,current_checkpoint=parent,admitted_spec=spec,catalog=value)
 scope['joint_certificate']=joint;old_observers=scope['ordinary_observers']
 @contextmanager
 def observers(where,out,p,cp0):
  from system_campaign_financial_partial import root_spec
  prior_spec=root_spec('P07',vivo.data.ROOT);prior=strict_json((Path(where)/vivo.boundary.SELECTED).read_bytes())
  vivo.data.parent_contract(prior,prior_spec);api=vivo_input.api(prior,prior_spec)
  event=legacy_future_event(where,prior,api);event.out=Path(out)/vivo.OBSERVATION;event.out.mkdir(parents=True,exist_ok=True)
  with old_observers(where,out,p,cp0) as inherited:
   with event,inputs.observer(out):yield inherited
 scope['ordinary_observers']=observers
 def constructor_canary(current,out,certificate):
  actual,_=boundary(out,parent,spec,rows)
  resources.verify_preserved(lambda n:(view/n).read_bytes(),lambda n:(Path(out)/n).read_bytes(),spec,
   rows=baseline[1],resolutions=[saved.metadata(spec)['historical_event_resolution']])
  need(current==actual==neutral and certificate.seed==baseline[1] and len(certificate.seed)==929,
   'POSTCLOSE_RESTART_ACTUAL_NEUTRAL_AND_COMPLETE_CONSTRUCTOR_SEED929')
  exact(Path(out)/CANARY,saved.encoded(dict(passed=True,actual_certificate_and_original_observers_constructed=True,
   all_referenced_archives_preserved=True,current_checkpoint_sha256=current['sha256'],committed_seed_rows=929,financial_sessions_advanced=0)))
 scope['constructor_canary']=constructor_canary
 exec(compile(ast.Module(body=[worker_tree(Path(saved.retained.additional_runtime.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-retained-worker-one-before-main-constructor-canary>','exec'),scope)
 return SimpleNamespace(**scope)

def preserved_archive(original,source,output,spec):
 """Reuse an exact already copied archive in this private restart only."""
 source,output=Path(source),Path(output)
 need(original.__name__=='preserve' and callable(original.__globals__.get('same_existing_archive')),
  'POSTCLOSE_ARCHIVE_WHOLE_ORIGINAL_ADAPTED_PRESERVER')
 resolutions=resources.plan(spec)['historical_archive_resolutions']
 def selected(actual,target,proof):
  pin={k:proof[k] for k in ('actual','outer_sha256','state_sha256','input_sha256')}
  pin['gzip_sha256']=proof['file_sha256']
  need(proof==dict(schema='research.uncertainty-readonly-archive-resolution/1',
   requested='book/pre-event/2019-10-22.json.gz',actual=pin['actual'],file_sha256=pin['gzip_sha256'],
   outer_sha256=pin['outer_sha256'],source_cursor='2019-10-21',state_sha256=pin['state_sha256'],
   input_sha256=pin['input_sha256'],exact_first_certificate_identity=True,checkpoint_bytes_or_name_changed=False,
   new_checkpoint_or_alias_created=False,financial_sessions_advanced=0) and pin in resolutions
   and Path(actual)==source/proof['actual']
   and Path(target)==output/proof['actual'],'POSTCLOSE_ARCHIVE_ONLY_EXACT_PLANNED_SOURCE_AND_OUTPUT')
  return Path(actual),Path(target)
 def identical(actual,target,proof):
  actual,target=selected(actual,target,proof)
  return (actual.is_file() and target.is_file() and actual.read_bytes()==target.read_bytes()
   and sha(target.read_bytes())==proof['file_sha256'])
 old_copy=original.__globals__['shutil'].copyfile
 def copy(actual,target):
  actual,target=Path(actual),Path(target)
  choices=[p for p in resolutions if actual==source/p['actual'] and target==output/p['actual']]
  need(len(choices)==1,'POSTCLOSE_ARCHIVE_COPY_ONLY_ORIGINAL_PLANNED_PATH')
  if target.exists():
   need(actual.is_file() and target.is_file() and actual.read_bytes()==target.read_bytes()
    and sha(target.read_bytes())==choices[0]['gzip_sha256'],'POSTCLOSE_ARCHIVE_NO_OVERWRITE_DIFFERENT_BYTES')
   return str(target)
  need(sha(actual.read_bytes())==choices[0]['gzip_sha256'],'POSTCLOSE_ARCHIVE_ABSENT_TARGET_EXACT_SOURCE')
  return old_copy(actual,target)
 namespace=dict(original.__globals__,same_existing_archive=identical,
  shutil=SimpleNamespace(**dict(vars(shutil),copyfile=copy)))
 bound=FunctionType(original.__code__,namespace,original.__name__,original.__defaults__)
 bound.__kwdefaults__=original.__kwdefaults__
 def preserve(where,out):
  need(Path(where)==source and Path(out)==output,'POSTCLOSE_ARCHIVE_ONLY_SELECTED_RESTART_DIRECTORIES')
  return bound(where,out)
 return preserve

def legacy_future_event(root,parent,api):
 from full_system_core import hosted
 hosted()
 import system_campaign_financial_future as future
 init=future.ActualEvents.__init__
 bound=FunctionType(init.__code__,dict(init.__globals__,OVERLAY=vivo.boundary.OVERLAY,source_scopes=api.source_scopes),init.__name__,init.__defaults__)
 bound.__kwdefaults__=init.__kwdefaults__;event=future.ActualEvents.__new__(future.ActualEvents)
 bound(event,Path(root),'P07',cp=parent)
 need(event.scopes==[] and len(event.terms)==23 and all(t['kind']=='CASH_MERGER' for t in event.terms.values()),
  'POSTCLOSE_RESTART_ENTIRE_ORIGINAL_VIVO23_CASH_OBSERVER')
 return event

def run(parent,out,args,rows,observer,execution,*,spec,old,request):
 from full_system_core import hosted
 hosted();require_request(request,spec);old,out=Path(old),Path(out);saved.parent_contract(parent,spec)
 baseline=saved.seed_reader()(old,parent,spec);resolutions=[saved.metadata(spec)['historical_event_resolution']]
 resources.preserve(old,out,parent,spec,rows=baseline[1],resolutions=resolutions)
 path,loaded=inputs.prepare(parent,out,old=old)
 with projection(out):neutral=adopter(spec)(parent,out,args,rows,path,loaded.earliest_affected_session,history.paths(spec)['DIRECTORY'])
 actual,proof=boundary(out,parent,spec,rows);need(actual==neutral,'POSTCLOSE_RESTART_ACTUAL_CANONICAL_ADOPTION_BEFORE_FINANCIAL_MAIN')
 exact(out/BOUNDARY,saved.encoded(proof))
 with seed_view(old,out,parent,neutral,spec,out,rows) as view:
  api=whole_api(view,neutral,parent,spec,out,rows,baseline)
  with projection(out):return api.run_retained(neutral,out,args,rows,observer,execution,spec,view,models.lifecycle().phase(spec))

def review(parent,evidence,out,*,spec,old,request):
 from full_system_core import hosted
 hosted();require_request(request,spec);old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 saved.parent_contract(parent,spec);rows=seed_rows(old,parent,spec);baseline=saved.seed_reader()(old,parent,spec)
 neutral,proof=boundary(evidence,parent,spec,rows)
 need(json.loads((evidence/BOUNDARY).read_bytes())==proof,'POSTCLOSE_RESTART_INDEPENDENT_COMPLETE_NEUTRAL_BOUNDARY')
 need(json.loads((evidence/CANARY).read_bytes())==dict(passed=True,actual_certificate_and_original_observers_constructed=True,
  all_referenced_archives_preserved=True,current_checkpoint_sha256=neutral['sha256'],committed_seed_rows=929,financial_sessions_advanced=0),
  'POSTCLOSE_RESTART_INDEPENDENT_ACTUAL_CONSTRUCTOR_CANARY')
 resources.verify_preserved(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes(),spec,
  rows=baseline[1],resolutions=[saved.metadata(spec)['historical_event_resolution']])
 value,raw=inputs.verify_payload(evidence)
 with seed_view(old,out,parent,neutral,spec,evidence,rows) as view:
  api=whole_api(view,neutral,parent,spec,evidence,rows,baseline)
  with projection(evidence):api.review(neutral,evidence,out,spec,view)
 current=strict_json((evidence/'book/checkpoint.json.gz').read_bytes());models.full(evidence,current)
 vivo.review_cash(evidence,current,out);event=inputs.review_event(value,evidence,current)
 exact(out/EVENT_REVIEW,saved.encoded(event))
 exact(out/BOUNDARY,saved.encoded(proof))

def api(root,current,spec,*,request):
 from full_system_core import hosted
 hosted();require_request(request,spec);scope,_=base_api(root,current,spec)
 def calculate(parent,out,args,rows,observer,execution,target,old):
  return run(parent,out,args,rows,observer,execution,spec=target,old=old,request=request)
 def verify(parent,evidence,out,target,old):
  return review(parent,evidence,out,spec=target,old=old,request=request)
 return SimpleNamespace(**dict(scope,run=calculate,review=verify))
