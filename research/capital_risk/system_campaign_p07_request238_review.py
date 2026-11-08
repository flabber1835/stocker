"""Review the genuine saved August book with two authentic historical records."""
import ast,base64,json,shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_p07_request231_review as previous
import system_campaign_p07_KDNY_entry as entry
import system_campaign_p03_PTLA_entry as inactive_p03
runtime,retained,history=entry.runtime,entry.retained,entry.history
repair=previous.repair
HERE=Path(__file__).parent
FACT='P07-request238-readonly-recovery-fact.json'
FACT_SHA='586b883ecc962d9a4310ca18a603e9e894bfd0afc2e58a09607d5a3ff3532d4f'
FIELD='selected_p07_request238_readonly_recovery'
MARKER='p07_request238_readonly_recovery'
MODE=previous.MODE
ORIGIN=runtime.source.ROOT
OUTER='1dae9e15f725f65531d443bbad0a0a62ae05c46e827a2b5f674e05d9b682d037'
RUN=42456991175
HEAD='9654405fef39b38fff350eae7b88292f8664aacc'
ARTIFACT=13608369979
STATUS='FINANCIAL_REVIEW_REFUSED_PRESERVED'
encoded=previous.encoded
bind=previous.bind


def pin(raw):return dict(bytes=len(raw),sha256=sha(raw))


def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'REQUEST238_EXACT_AUTHENTICATED_RECOVERY_FACT')
 value=json.loads(raw)
 need(value['financial_authority'] is value['financial_root_admitted'] is value['canonical_runtime_executed'] is False
  and value['original_parent_root']==ORIGIN and value['original_stops']==[0,1,1], 'REQUEST238_NO_NEW_FINANCIAL_AUTHORITY')
 return value


def applies(spec):return isinstance(spec,dict) and spec.get(MARKER) is True


def target():return fact()['target']


def validate_target(spec):
 need(applies(spec) and spec==target(),'REQUEST238_ONLY_EXACT_SAVED1426_FULL27_TARGET')
 need(spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
  and spec['readonly_failed_review_requalification'] is True and spec['review_sha256'] is None
  and 'root_admission' not in spec and 'root_admission_sha256' not in spec
  and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(1426,'2023-08-31',27)
  and spec['manifest']==dict(member_count=639,raw_member_bytes=786073898)
  and spec['receipt_status']==STATUS and spec['monthly_seed_root_admission_sha256']==ORIGIN
  and all(spec['prior_stops'][r]==dict(stopped=True,exit_code=c,oom_killed=False,wait_error=None)
   and type(spec['prior_stops'][r]['exit_code'])is int for r,c in (('preflight',0),('worker',1),('reviewer',1))),
  'REQUEST238_ORIGINAL_FAILED_STOPS_AND_NO_REPLAY_OR_AUTHORITY')
 return True


def declaration(spec):
 validate_target(spec)
 return dict(fact_sha256=FACT_SHA,target_outer_sha256=OUTER,parent_root=ORIGIN,completed=1426,full_inputs=27,
  retained_proofs=949,new_days=23,financial_workers=0,financial_authority=False,observer_supplements=2,
  original_failed_stops_preserved=True,all639_original_members_unchanged=True)


def require_request(request,spec):
 validate_target(spec)
 need(request['execution_mode']==MODE and request['arms']==['P07'] and request['financial_resume_authorized'] is False
  and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==0
  and type(request['maximum_parallel_readonly_workers'])is int and request['maximum_parallel_readonly_workers']==1
  and request.get(FIELD)=={'P07':declaration(spec)},'REQUEST238_EXPLICIT_ZERO_FINANCIAL_READONLY_REQUEST')
 return True


def selected_request(request):return bool(request.get(FIELD)) and require_request(request,target())


def source_names():
 return tuple(sorted({Path(__file__).name,FACT,'P07-request238-readonly-partials.json',*entry.source_names(),*inactive_p03.source_names()}))


def bind_expected_request(original,module):
 def expected():
  active=module.EXECUTION_MODE==MODE and list(module.SELECTED_ARMS)==['P07']
  if active:
   validate_target(target())
   from system_campaign_financial_partial import root_spec
   need(root_spec('P07')['root_admission_sha256']==ORIGIN,'REQUEST238_RETIRED_AFTER_NEW_ADMISSION')
  old_target=previous.target
  if active:previous.target=target
  try:value=original()
  finally:previous.target=old_target
  value[FIELD]={'P07':declaration(target())} if active else {}
  if active:value['arm_inputs']['P07']['new_factual_overlay']=False
  for name in source_names():
   h=sha((HERE/name).read_bytes());need(name not in value['sources'] or value['sources'][name]==h,'REQUEST238_NO_SOURCE_PIN_REPLACEMENT:'+name)
   value['sources'][name]=h
  if active:require_request(value,target())
  return value
 return expected


def legacy(name):
 return bind(previous.legacy,validate_target=validate_target,request_only_readonly=require_request,
  public_names=public_names,prove_refusal=prove_refusal,ORIGIN=ORIGIN,OUTER=OUTER,RUN=RUN,HEAD=HEAD,ARTIFACT=ARTIFACT,STATUS=STATUS)(name)


def public_names(spec,archive):return legacy('public_names')(spec,archive)


def prove_refusal(spec,inventory,root):
 from system_campaign_financial_partial import root_spec
 validate_target(spec);root=Path(root);value=fact();raw=(root/'stopped-review/worker.log').read_bytes()
 need(pin(raw)==value['original_review_log_commitment']==inventory['stopped-review/worker.log']
  and b'VIVO_ALL_REACHED23_CASH_EVENTS_REQUIRE_COMPLETE_ACTUAL_OBSERVER_RECORDS' in raw,
  'REQUEST238_EXACT_ORIGINAL_MISSING_JULY_OBSERVER_REFUSAL')
 origin=root_spec('P07',ORIGIN)
 need(json.loads((root/'spec.json').read_bytes())==origin,'REQUEST238_GENUINE_ADMITTED1403_ORIGIN')
 old=json.loads((root/'old-prefix-canonical-review.json').read_bytes())
 need(old['checkpoint_sha256']==origin['outer_sha256'] and old['counts']==dict(formation=126,daily=1403)
  and old['all_prefixes_verified'] is old['all_daily_factors_and_chains_verified'] is True,
  'REQUEST238_OLD1403_REVIEW_NEVER_NEW1426_AUTHORITY')


def supplement_records():
 value=fact();old=entry.resources.fact()
 need(value['original_resource_fact_sha256']==entry.resources.FACT_SHA,'REQUEST238_EXACT_PRIOR_RESOURCE_SOURCE')
 expected={f'p07-vivo-ordinary25-observation/actual-future-event-{day}.json' for day in ('2023-07-11','2023-07-28')}
 need(set(value['observer_supplements'])==expected,'REQUEST238_ONLY_TWO_AUTHENTIC_JULY_RECORDS')
 result={}
 for name,item in value['observer_supplements'].items():
  raw=base64.b64decode(item['base64'],validate=True)
  need(pin(raw)=={k:item[k] for k in ('bytes','sha256')}==old['actual_financial_manifest'][name]
   and name not in value['original_manifest'] and item['artifact_id']==13598958730,
   'REQUEST238_UNCHANGED_AUTHENTICATED_ORIGINAL_JULY_RECORD:'+name)
  result[name]=raw
 return result


def verify_members(root):
 root=Path(root);members=fact()['original_manifest']
 need(len(members)==639 and sum(v['bytes'] for v in members.values())==786073898,'REQUEST238_COMPLETE_ORIGINAL_INVENTORY')
 for name,expected in members.items():need(pin((root/name).read_bytes())==expected,'REQUEST238_ORIGINAL_MEMBER_UNCHANGED:'+name)
 return members


def admit(spec,root,key,inspector):
 previous.launcher_guard();validate_target(spec)
 original=legacy('admit')(spec,root,key,inspector);verify_members(original)
 view=Path(root)/'request238-review-input-view';shutil.copytree(original,view)
 records=supplement_records()
 for name,raw in records.items():exact(view/name,raw)
 verify_members(view)
 proof=dict(passed=True,original_artifact_id=ARTIFACT,original_manifest_sha256=sha(encoded(fact()['original_manifest'])),
  all639_original_members_unchanged=True,checkpoint_replaced=False,journals_changed=False,financial_sessions_advanced=0,
  supplements={name:pin(raw) for name,raw in records.items()})
 exact(view/'request238-readonly-input-view.json',encoded(proof));return view


def admit_origin(spec,root,key,inspector,request):
 parent=entry.parent_transport;parent.validated(spec);require_request(request,target())
 def readonly(actual,current,authorize):
  need(actual==request and current==spec,'REQUEST238_ONLY_EXACT_READONLY_PARENT_TRANSPORT')
  return require_request(actual,target())
 # Whole existing reader, old231+233 authentication and qualified view unchanged.
 return bind(parent.admit,require_future_request=readonly)(spec,root,key,inspector,request=request,authorize=require_request)


def require_requalified_review(root,spec):
 validate_target(spec);root=Path(root)
 core=json.loads((root/'core-review.json').read_bytes());branch=json.loads((root/'uncertainty-certificate-review.json').read_bytes())
 need(core['checkpoint_sha256']==branch['checkpoint_sha256']==OUTER and core['counts']==dict(formation=126,daily=1426)
  and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True and core['complete'] is False
  and branch['passed'] is True and (branch['retained_rows'],branch['rows'])==(949,23)
  and branch['through']=='2023-08-31'
  and branch['all_financial_watch_and_proof_identities_verified'] is branch['every_reachable_decision_identical'] is True,
  'REQUEST238_FRESH_WHOLE1426_CORE_AND949_PLUS23_BRANCH_REVIEW')
 full=json.loads((root/'request238-full27-history-review.json').read_bytes())
 need(full==dict(passed=True,checkpoint_sha256=OUTER,full_inputs=27,descriptors=spec['repairs']),
  'REQUEST238_FRESH_ENTIRE27_INPUT_HISTORY_REVIEW')
 event=json.loads((root/retained.previous.EVENT_REVIEW).read_bytes());cash=json.loads((root/'p07-vivo-ordinary25-cash-review.json').read_bytes())
 need(event['passed'] is event['event_committed'] is cash['passed'] is cash['complete_observer_records_preserved'] is True,
  'REQUEST238_COMPLETE_VIVO_CASH_AND_BWA_DISTRIBUTION_REVIEW')
 return dict(passed=True,checkpoint_sha256=OUTER,financial_authority=False,financial_sessions_advanced=0,
  original_financial_artifact_id=ARTIFACT,original_failed_stops_preserved=True,
  core_review_sha256=sha((root/'core-review.json').read_bytes()),branch_review_sha256=sha((root/'uncertainty-certificate-review.json').read_bytes()),
  distribution_review_sha256=sha((root/retained.previous.EVENT_REVIEW).read_bytes()),cash_review_sha256=sha((root/'p07-vivo-ordinary25-cash-review.json').read_bytes()))


def deny(*args,**kwargs):raise ValueError('REQUEST238_READONLY_FINANCIAL_CALLBACK_FORBIDDEN')


@contextmanager
def worker_context(module,spec,*,mode,out,request):
 from full_system_core import hosted
 hosted();require_request(request,target());need(mode in ('preflight','review'),'REQUEST238_NO_ECONOMIC_WORKER')
 import system_campaign_financial_partial as partial
 import system_campaign_financial_additional_sensor as additional
 import system_campaign_ordinary_augmentation_router as router
 from system_campaign_registry_extension import RegistryExtension
 from system_campaign_bounded_sensor_preparation import no_financial_transitions
 origin=partial.root_spec('P07',ORIGIN)
 need(applies(spec) if mode=='preflight' else spec==origin,'REQUEST238_EXACT_TARGET_OR_GENUINE_ORIGIN_CONTEXT')
 if applies(spec):validate_target(spec)
 saved=[]
 def patch(owner,name,value):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
 def selected(value):return applies(value) or value==origin
 old_models,old_context,old_implementation=partial.retained_models,partial.model_context,router.implementation
 def models(root,current,target_spec):
  if selected(target_spec):return history.full(root,current)
  return old_models(root,current,target_spec)
 @contextmanager
 def codecs(root,current,target_spec):
  if selected(target_spec):
   with retained.codecs(root,current,origin,out):yield
  else:
   with old_context(root,current,target_spec):yield
 def implementation(root,current,target_spec):
  if selected(target_spec):return SimpleNamespace(preserve=lambda *a:history.full(root,current),retained_models=models)
  return old_implementation(root,current,target_spec)
 patch(partial,'retained_models',models);patch(partial,'model_context',codecs);patch(router,'implementation',implementation)
 old_phase=additional.phase;patch(additional,'phase',lambda s:None if selected(s) else old_phase(s))
 old_uncertainty=runtime.legacy.uncertainty_phase;patch(runtime.legacy,'uncertainty_phase',lambda s:s==origin or old_uncertainty(s))
 old_review=runtime.legacy.review;patch(runtime.legacy,'review',lambda *a,**k:runtime.review(*a,**k) if k.get('spec')==origin else old_review(*a,**k))
 patch(module,'economic',deny);patch(runtime.legacy,'run',deny)
 whole=entry.mature_review(module)
 def review(where,folder,target_spec):
  need(target_spec==origin,'REQUEST238_REVIEW_ONLY_GENUINE1403_PARENT');current=strict_json((Path(where)/'book/checkpoint.json.gz').read_bytes())
  with codecs(where,current,target_spec):result=whole(where,folder,target_spec)
  checked=history.full(where,current);need(checked['full_inputs']==27,'REQUEST238_ACTUAL_FULL27_HISTORY_AFTER_REVIEW')
  exact(Path(folder)/'request238-full27-history-review.json',encoded(dict(passed=True,checkpoint_sha256=current['sha256'],full_inputs=27,descriptors=current['repairs'])))
  return result
 patch(module,'review',review)
 try:
  with RegistryExtension(),no_financial_transitions():
   if mode=='preflight':exact(Path(out)/'request238-readonly-input-view.json',(Path('/old')/'request238-readonly-input-view.json').read_bytes())
   yield
 finally:
  for owner,name,value in reversed(saved):setattr(owner,name,value)


@contextmanager
def context(request,*,mode,module=None,spec=None,out=None):
 require_request(request,target());need(mode in ('launch','preflight','review'),'REQUEST238_ECONOMIC_MODE_FORBIDDEN')
 if mode=='launch':previous.launcher_guard()
 import system_campaign_financial_requalified_parent as parent
 saved={n:getattr(repair,n) for n in ('applies','admit','ORIGIN','require_requalified_review')}
 parents={n:getattr(parent,n) for n in ('applies','admit')}
 repair.applies=lambda s:applies(s) or saved['applies'](s)
 repair.admit=lambda s,*a,**k:admit(s,*a,**k) if applies(s) else saved['admit'](s,*a,**k)
 repair.ORIGIN=ORIGIN;repair.require_requalified_review=lambda root,s:require_requalified_review(root,s) if applies(s) else saved['require_requalified_review'](root,s)
 parent.applies=lambda s:entry.parent_transport.applies(s) or parents['applies'](s)
 parent.admit=lambda s,*a,**k:admit_origin(s,*a,request=request,**k) if entry.parent_transport.applies(s) else parents['admit'](s,*a,**k)
 try:
  if mode=='launch':yield
  else:
   with worker_context(module,spec,mode=mode,out=out,request=request):yield
 finally:
  for name,value in saved.items():setattr(repair,name,value)
  for name,value in parents.items():setattr(parent,name,value)


def bind_launch(original):
 def launch(args):
  request=json.loads(Path(args.request).read_bytes())
  if not selected_request(request):return original(args)
  need(args.arm=='P07','REQUEST238_ONLY_SELECTED_P07_REVIEW')
  with context(request,mode='launch'):return original(args)
 return launch


def bind_dispatch(original):
 @contextmanager
 def dispatch(module,spec,*,mode,evidence=None,out=None):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
  if request.get(FIELD):
   with context(request,mode=mode,module=module,spec=spec,out=out):yield
  else:
   with original(module,spec,mode=mode,evidence=evidence,out=out):yield
 return dispatch


def install(module):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 bounded.entry=bind_dispatch(bounded.entry);module.expected_request=bind_expected_request(module.expected_request,module)
 module.launch=bind_launch(module.launch)
