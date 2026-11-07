"""Profile-selected restart with whole original retained workers."""
import ast,gzip,json,shutil,tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_financial_uncertainty as legacy
import system_campaign_p06_abmd_retained as retained
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_WWE12_models as previous
import system_campaign_p06_BBIG_runtime as permissions
import system_campaign_source_exit_history as models
import system_campaign_source_exit_api as api_module
import system_campaign_source_exit_resources as resources
import system_campaign_source_exit_observer as observations
import system_campaign_retained_seed_successor as seeds
import system_campaign_source_exit_profiles as profiles
HERE=Path(__file__).parent
ROOT='ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845'
FIELD='selected_source_exit_successors'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
QUALIFICATION='P06-source-exit-whole-profile-qualification.json'
RECEIPT='source-exit-successor-adopted-input-receipt.json'
BOUNDARY='source-exit-successor-genuine-neutral-boundary.json'
PROVENANCE=models.PROVENANCE
FULL_PROOF='original-full442-uncertainty-certificate.jsonl'
RETAINED_SHA='978c3106655cb45dd91f14967f4fe42962cf1a0f3eae42cb353fb6b0086c2ac4'

def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def candidate(spec):return profiles.candidate(spec)

def previous_for(spec):return lambda root,current:profiles.previous(root,current,spec)

def seed_count(spec):return profiles.profile(spec)['seed_rows']
def qualification(spec):
 name=profiles.profile(spec)['qualification'] if candidate(spec) else QUALIFICATION
 need(candidate(spec) and (HERE/name).is_file(),'SOURCE_EXIT_RUNTIME_WHOLE_PROFILE_NOT_CLOSED')
 raw=(HERE/name).read_bytes();q=json.loads(raw)
 need(q['passed'] is True and q['root_admission_sha256']==spec['root_admission_sha256'] and q['financial_authority'] is q['canonical_runtime_executed'] is False
  and q.get('selected_job_neutral_checkpoint_known',q.get('actual_neutral_checkpoint_known',q.get('actual_neutral13_known'))) is False,
  'SOURCE_EXIT_RUNTIME_EXPLICIT_WHOLE_DATA_PROFILE_NO_CLAIMED_HOSTED_BOUNDARY')
 for n,pin in q['files'].items():
  b=(HERE/n).read_bytes();need(dict(bytes=len(b),sha256=sha(b))==pin,'SOURCE_EXIT_RUNTIME_COMPLETE_PROFILE_BYTES:'+n)
 return sha(raw)
def declaration(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);value=seeds.metadata(spec);resources.plan(spec);profiles.source(spec).catalog()
 return dict(schema='research.source-exit-successor-financial-declaration/1',root_admission_sha256=spec['root_admission_sha256'],parent_outer_sha256=spec['outer_sha256'],
  parent_inputs=len(spec['repairs']),required_neutral_inputs=len(spec['repairs'])+1,committed_seed_rows=value['committed_rows'],
  committed_seed_sha256=value['committed_proof']['sha256'],profile_qualification_sha256=qualification(spec),genuine_neutral_checkpoint_required=True,
  actual_neutral_checkpoint_known=False,actual_constructor_required_before_finance=True,held_settlement_authorized=False)
def selected(spec,request):
 return candidate(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True \
  and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False and request.get(FIELD)=={'P06':declaration(spec)}
def request_financial(request,spec):
 need(selected(spec,request) and request['arms']==['P06'] and request['admitted_checkpoints']['P06']==spec['outer_sha256'],
  'SOURCE_EXIT_RUNTIME_ONLY_EXACT_QUALIFIED_ACTIVE_PARENT')
 from system_campaign_source_exit_entry import source_names
 need(request['maximum_parallel_financial_workers']==1 and request['maximum_parallel_readonly_workers']==0
  and all(request['sources'].get(n)==sha((HERE/n).read_bytes()) for n in source_names()),'SOURCE_EXIT_RUNTIME_ALL_CURRENT_SOURCE_PINS_AND_ONE_QUALIFIED_WORKER')
 return True

def input_api(parent,spec):return models.input_api(parent,spec,previous_for(spec))
def relation(parent,neutral,spec,member,rows):return models.boundary_relation(parent,neutral,spec,member,rows,previous_history=previous_for(spec))
def boundary(root,parent,spec,rows):
 root=Path(root);names=profiles.paths(spec);neutral=strict_json((root/names['NEUTRAL']).read_bytes());proof=relation(parent,neutral,spec,lambda n:(root/n).read_bytes(),rows)
 need(models.full(root,neutral)['full_inputs']==len(spec['repairs'])+1,'SOURCE_EXIT_RUNTIME_COMPLETE_GENUINE13_HISTORY')
 return neutral,proof

def adoption_tree(raw,*,directory=models.DIRECTORY,overlay=models.OVERLAY):
 need(sha(raw)==seeds.U_SHA,'SOURCE_EXIT_RUNTIME_WHOLE_ORIGINAL_CANONICAL_ADOPTER')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
 mapping,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
 need(ast.unparse(mapping)=="{ORDINARY_ADOPTION: 'future-financial-overlay.json', DATE_ADOPTION: DATE_OVERLAY, MODEL_ADOPTION: 'branch-uncertainty-input.json'}",'SOURCE_EXIT_RUNTIME_ONE_ORIGINAL_DIRECTORY_OVERLAY_MAP')
 mapping.keys.append(ast.Constant(directory));mapping.values.append(ast.Constant(overlay));return ast.fix_missing_locations(fn)
def adoption_boundary(spec,original):
 names=profiles.paths(spec)
 def boundary(root,directory,parent,overlay,earliest):
  need(directory==names['DIRECTORY'] and overlay==Path(names['OVERLAY']).name,
   'SOURCE_EXIT_RUNTIME_EXACT_SELECTED_BOUNDARY_FILENAME')
  return original(root,directory,parent,names['OVERLAY'],earliest)
 return boundary

def adopter(spec):
 names=profiles.paths(spec);scope=dict(vars(legacy),boundary=adoption_boundary(spec,legacy.boundary));exec(compile(ast.Module(body=[adoption_tree(Path(legacy.__file__).read_bytes(),directory=names['DIRECTORY'],overlay=names['OVERLAY'])],type_ignores=[]),'<whole-original-canonical-adopter-one-successor-filename>','exec'),scope)
 return scope['paused_own_adoption']

@contextmanager
def seed_view(old,out,parent,neutral,spec,evidence,rows):
 from full_system_core import hosted
 hosted();old,out,evidence=Path(old),Path(out),Path(evidence);original=(old/spec['selected_checkpoint']).read_bytes()
 need(dict(bytes=len(original),sha256=sha(original))==spec['selected_file'] and strict_json(original)==parent,'SOURCE_EXIT_RUNTIME_REAL_SELECTED_PARENT12_FILE_NEVER_SUBSTITUTED')
 proof=relation(parent,neutral,spec,lambda n:(evidence/n).read_bytes(),rows);api=input_api(parent,spec);names=profiles.paths(spec)
 with tempfile.TemporaryDirectory(prefix='p06-BBIG-real-neutral-seed-view-',dir=out) as owned:
  view=Path(owned)/'view';shutil.copytree(old,view);permitted=permissions.owned_view_permissions(view,owned,out)
  files=[names['OVERLAY'],api.hydration_name(parent),api.SOURCE_SCOPES,api.QUALIFICATION,names['PARENT'],names['NEUTRAL'],names['PROOF'],
   names['DIRECTORY']+'-correlation-inputs.jsonl.gz','book/repairs/'+neutral['repairs'][-1]['filename']]
  inventory={}
  for n in files:
   raw=(evidence/n).read_bytes();exact(view/n,raw);inventory[n]=dict(bytes=len(raw),sha256=sha(raw))
  watch=(evidence/'book/watch.jsonl').read_bytes();commit=neutral['journals']['watch']
  need(sha(watch[:commit['bytes']])==commit['prefix_sha256'],'SOURCE_EXIT_RUNTIME_ACTUAL_NEUTRAL_COMMITTED_WATCH_PREFIX')
  (view/'book/watch.jsonl').write_bytes(watch[:commit['bytes']])
  need((view/spec['selected_checkpoint']).read_bytes()==original,'SOURCE_EXIT_RUNTIME_OWNED_VIEW_KEEPS_GENUINE_SELECTED_PARENT12')
  exact(out/names['PROVENANCE']/'temporary-seed-view-receipt.json',encoded(dict(passed=True,selected_parent_file_sha256=sha(original),
   actual_neutral_file_sha256=proof['neutral_gzip_sha256'],actual_added_files=inventory,selected_checkpoint_replaced=False,
   owned_copy_permissions=permitted,financial_sessions_advanced=0)))
  yield view
 need(not Path(owned).exists(),'SOURCE_EXIT_RUNTIME_OWNED_TEMPORARY_VIEW_REMOVAL_OBSERVED')
 exact(out/names['PROVENANCE']/'temporary-seed-view-cleanup.json',encoded(dict(passed=True,temporary_owned_view_removal_observed=True,financial_sessions_advanced=0)))

def neutral_seed(view,parent,neutral,spec,evidence,rows,baseline):
 view,evidence=Path(view),Path(evidence)
 def contract(current,target):
  need(current==neutral and target==spec,'SOURCE_EXIT_RUNTIME_SEED_BRIDGE_ONLY_GENUINE_NEUTRAL13_AND_ORIGINAL_SPEC12')
  relation(parent,current,target,lambda n:(evidence/n).read_bytes(),rows);return seeds.contract(parent,target)
 whole=seeds.bind_seed(contract=contract,visitor=models.full,reader=seeds.initial.seed_reader(inherited_root=HERE))
 def seed(root,current,target):
  need(Path(root)==view and current==neutral and target==spec,'SOURCE_EXIT_RUNTIME_ONLY_ACTUAL_OWNED_INVENTORIED_SEED_VIEW')
  value=whole(view,current,target);need(value==baseline[:3] and len(value[1])==seed_count(spec),'SOURCE_EXIT_RUNTIME_WHOLE_NEUTRAL13_SEED_EQUALS_ACTUAL_PARENT12_424')
  return (*value,baseline[3])
 return seed

def certificate_class(event,source,codec,native,*,inherited_root,retained_root,current_checkpoint,admitted_spec):
 from full_system_core import hosted
 hosted();root=Path(retained_root);spec=admitted_spec;parent=strict_json((root/profiles.paths(spec)['PARENT']).read_bytes())
 from system_campaign_financial_resume import seed_rows
 rows=seed_rows(root,parent,spec)
 def checked_boundary():
  relation(parent,current_checkpoint,spec,lambda n:(root/n).read_bytes(),rows);models.full(root,current_checkpoint);return True
 return seeds.factory(event,source,codec,native,inherited_root=inherited_root,retained_root=root,parent=parent,spec=spec,visitor=previous_for(spec),boundary=checked_boundary)

def suffix(parent,current,retained,rows,financial,*,median5,champion_config):
 from full_system_core import hosted
 hosted()
 from system_campaign_p06_abmd_retained_suffix import bind_review
 counts=[v['seed_rows'] for v in profiles.records().values() if v['parent_inputs']+1==len(parent['repairs'])]
 need(len(counts)==1 and len(retained)==counts[0] and not any(r['session']=='2022-12-22' for r in rows),'SOURCE_EXIT_RUNTIME_ALL424_RETAINED_NO_REPLAYED_ABMD_EVENT')
 return bind_review()(parent,current,retained,rows,financial,median5=median5,champion_config=champion_config)

def retained_tree(raw,name,*,committed_rows=424):
 need(sha(raw)==RETAINED_SHA and name in ('run','review'),'SOURCE_EXIT_RUNTIME_WHOLE_ORIGINAL_RETAINED_WORKER_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
 module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
 imp,=[n for n in ast.walk(fn) if isinstance(n,ast.ImportFrom) and n.module==module]
 need([(v.name,v.asname) for v in imp.names]==([('certificate_class',None)] if name=='run' else [('review','suffix')]),'SOURCE_EXIT_RUNTIME_ONE_ORIGINAL_FACTORY_OR_SUFFIX_IMPORT')
 imp.module='system_campaign_source_exit_runtime'
 if name=='review':imp.names[0].name='suffix'
 counts=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and type(n.value)is int and n.value==6]
 need(len(counts)==(1 if name=='run' else 5),'SOURCE_EXIT_RUNTIME_EXACT_COMMITTED_SEED_COUNT_SITES')
 for n in counts:n.value=committed_rows
 if name=='run':
  block,=[n for n in fn.body if isinstance(n,ast.With) and [ast.unparse(i.context_expr) for i in n.items]==['certificate','observer','execution','events']]
  fn.body.insert(fn.body.index(block),ast.parse('constructor_canary(parent,out,certificate,events)').body[0])
 return ast.fix_missing_locations(fn)

def bind_retained(name,seed,request,parent,rows,baseline,*,spec):
 active=[None];target=[None];old=[None]
 def receipt(current,spec):return relation(parent,current,spec,lambda n:(active[0]/n).read_bytes(),rows)
 names=profiles.paths(spec)
 facade=SimpleNamespace(selected=selected,UNCHANGED=names['RECEIPT'],receipt=receipt,PROVENANCE=names['PROVENANCE'],FULL_PROOF=Path(names['OLD_PROOF']).name,encoded=encoded,OBSERVATIONS=names['OBSERVATION'])
 def review_unchanged(neutral,current,evidence,spec):
  boundary(evidence,parent,spec,rows)
  need(current['base']==neutral['base'] and current['repairs']==neutral['repairs'] and current['run']['input_sha256']==neutral['run']['input_sha256']
   and json.loads((Path(evidence)/names['RECEIPT']).read_bytes())==receipt(neutral,spec),'SOURCE_EXIT_RUNTIME_FINANCIAL_SEGMENT_AFTER_GENUINE13_ADOPTION')
 facade.review_unchanged=review_unchanged
 def preserved(root,out,current,proof,resolution):return resources.verify_preserved(lambda n:(Path(root)/n).read_bytes(),lambda n:(Path(out)/n).read_bytes(),target[0],rows=proof,resolutions=[resolution])
 def constructor_canary(current,out,certificate,events):
  resources.verify_preserved(lambda n:(old[0]/n).read_bytes(),lambda n:(Path(out)/n).read_bytes(),target[0],rows=baseline[1],resolutions=[baseline[3]])
  need(models.full(out,current)['full_inputs']==len(spec['repairs'])+1 and len(certificate.seed)==seed_count(spec)
   and len(events.scopes)==profiles.profile(spec)['retained_scope_count']+1,'SOURCE_EXIT_RUNTIME_ACTUAL_CERTIFICATE_AND_ORIGINAL_OBSERVER_CONSTRUCTED')
  exact(Path(out)/'continuation-constructor-canary.json',encoded(dict(passed=True,actual_certificate_and_original_observer_constructed=True,
   all_referenced_archives_preserved=True,current_checkpoint_sha256=current['sha256'],financial_sessions_advanced=0)))
 scope=dict(vars(retained),data=facade,seed=seed,full=models.full,preserve=preserved,constructor_canary=constructor_canary,
  prior_event=lambda root,current,proof:seeds.prior_event(root,parent,proof,target[0])[1][0],
  ordinary_observer=lambda root,out,current:observations.observer(root,out,current,parent,target[0],input_api(parent,target[0])),
  review_cash=lambda neutral,current,evidence,out:observations.review(parent,current,evidence,out,spec=target[0],old=old[0],neutral=neutral,api=input_api(parent,target[0])))
 exec(compile(ast.Module(body=[retained_tree(Path(retained.__file__).read_bytes(),name,committed_rows=seed_count(spec))],type_ignores=[]),'<whole-original-retained-worker-explicit-committed-bindings>','exec'),scope)
 def bound(*args,**kwargs):
  active[0]=Path(args[1]);target[0]=kwargs['spec'];old[0]=Path(kwargs['old']);return scope[name](*args,**kwargs,request=request)
 return bound

def run(parent,out,args,rows,observer,execution,*,spec,old,request):
 from full_system_core import hosted
 hosted();request_financial(request,spec);old,out=Path(old),Path(out);names=profiles.paths(spec);baseline=seeds.original_seed(old,parent,spec,visitor=previous_for(spec))
 resources.preserve(old,out,parent,spec,rows=baseline[1],resolutions=[baseline[3]])
 exact(out/names['CANARY'],(out/'parent-preflight'/names['CANARY']).read_bytes())
 exact(out/names['PARENT'],(old/spec['selected_checkpoint']).read_bytes());api=input_api(parent,spec)
 path,loaded=api.prepare(parent,out,spec['arm']);neutral=adopter(spec)(parent,out,args,rows,path,loaded.earliest_affected_session,names['DIRECTORY'])
 actual,proof=boundary(out,parent,spec,rows);need(actual==neutral,'SOURCE_EXIT_RUNTIME_REAL_NEUTRAL13_BEFORE_FINANCIAL_MAIN');exact(out/names['BOUNDARY'],encoded(proof))
 with seed_view(old,out,parent,neutral,spec,out,rows) as view:
  return bind_retained('run',neutral_seed(view,parent,neutral,spec,out,rows,baseline),request,parent,rows,baseline,spec=spec)(neutral,out,args,rows,observer,execution,spec=spec,old=view)

def review(parent,evidence,out,*,spec,old,request):
 from full_system_core import hosted
 hosted();request_financial(request,spec);old,evidence,out=Path(old),Path(evidence),Path(out)
 from system_campaign_financial_resume import seed_rows
 names=profiles.paths(spec);rows=seed_rows(old,parent,spec);baseline=seeds.original_seed(old,parent,spec,visitor=previous_for(spec));neutral,proof=boundary(evidence,parent,spec,rows)
 need(json.loads((evidence/names['BOUNDARY']).read_bytes())==proof,'SOURCE_EXIT_RUNTIME_INDEPENDENT_COMPLETE_NEUTRAL13_BOUNDARY')
 need(json.loads((evidence/'continuation-constructor-canary.json').read_bytes())==dict(passed=True,actual_certificate_and_original_observer_constructed=True,
  all_referenced_archives_preserved=True,current_checkpoint_sha256=neutral['sha256'],financial_sessions_advanced=0),'SOURCE_EXIT_RUNTIME_INDEPENDENT_ACTUAL_CONSTRUCTOR_CANARY')
 resources.verify_preserved(lambda n:(old/n).read_bytes(),lambda n:(evidence/n).read_bytes(),spec,rows=baseline[1],resolutions=[baseline[3]])
 api=input_api(parent,spec);need(api.review_input(parent,evidence,spec['arm'])==proof['earliest_affected_session'],'SOURCE_EXIT_RUNTIME_INDEPENDENT_COMPLETE_ORIGINAL_INPUT_RECONSTRUCTION')
 with seed_view(old,out,parent,neutral,spec,evidence,rows) as view:
  bind_retained('review',neutral_seed(view,parent,neutral,spec,evidence,rows,baseline),request,parent,rows,baseline,spec=spec)(neutral,evidence,out,spec=spec,old=view)
 exact(out/names['BOUNDARY'],encoded(proof))
