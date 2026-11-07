"""Qualified original failed book plus a distinct positive review capsule."""
import ast,json,os,shutil,stat
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha
from seal import sha256_file
HERE=Path(__file__).parent
CATALOG='system-campaign-stopped-parent-transports.json'
CATALOG_SHA='35f67f300f16acedf0ae5df332f54b404f6e8e8f8a51386cffd59a0e367a93ad'
CRYPTO_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'

def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def records():
 raw=(HERE/CATALOG).read_bytes();need(len(CATALOG_SHA)==64 and sha(raw)==CATALOG_SHA,'STOPPED_PARENT_EXACT_TRANSPORT_CATALOG')
 value=json.loads(raw);need(value['schema']=='research.qualified-stopped-parent-transports/1' and value['financial_authority'] is False,'STOPPED_PARENT_METADATA_ONLY')
 return value['roots']
def applies(spec):return isinstance(spec,dict) and spec.get('root_admission_sha256') in records()
def record(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);value=records()[spec['root_admission_sha256']]
 target={k:v for k,v in spec.items() if k not in ('root_admission','root_admission_sha256')};a=spec['root_admission']
 need(target==value['financial'] and a['original_failed_financial_receipt_preserved'] is True
  and a['original_failed_financial_receipt_sha256']==target['receipt_sha256']
  and a['original_failed_financial_stops']==target['prior_stops']
  and a['fresh_readonly_artifact_zip_sha256']==value['review']['zip_sha256'],
  'STOPPED_PARENT_EXACT_SEPARATELY_ADMITTED_FAILED_AND_POSITIVE_TRANSPORTS')
 proof=a['fresh_readonly_financial_review_requalification']
 need(proof['passed'] is proof['original_failed_stops_preserved'] is True and proof['financial_sessions_advanced']==0
  and proof['checkpoint_sha256']==spec['outer_sha256']
  and all(proof[k]==value['proof_sha256s'][n] for k,n in (('core_review_sha256','core-review.json'),('branch_review_sha256','uncertainty-certificate-review.json'),('source_review_sha256',value.get('source_review_name','p06-WWE-historical-observation-review.json')),('monthly_reproduction_sha256','monthly-reproduction.json'))),
  'STOPPED_PARENT_COMPLETE_ADMISSION_REVIEW_PROOF_BINDINGS')
 return value
def review_record(spec):
 matches=[(root,v) for root,v in records().items() if v['review']==spec];need(len(matches)==1,'STOPPED_PARENT_EXACT_POSITIVE_REVIEW_DESCRIPTOR')
 from system_campaign_financial_partial import root_spec
 root,value=matches[0];parent=root_spec(value['financial']['arm'],root);record(parent)
 return parent,value
def review_receipt_valid(r,spec,asset):
 parent,_=review_record(spec)
 need(r['schema']==spec['receipt_schema'] and int(r['run_id'])==spec['run_id'] and r['head']==spec['head']
  and r['request_sha256']==spec['request_sha256'] and r['protocol_sha256']==spec['protocol_sha256']
  and asset==spec['encrypted_output'] and r['status']=='STOPPED_EVIDENCE_REVIEW_PASSED_PENDING_ROOT'
  and r['financial_authority'] is r['input_adopted'] is False and r['financial_sessions_advanced']==0
  and r['original_financial_run']==parent['run_id'] and r['reviewer']==dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None),
  'STOPPED_PARENT_POSITIVE_READONLY_RECEIPT_NO_FINANCIAL_AUTHORITY')
 return True
def public_names(spec,z):
 review_record(spec);names=z.namelist();expected=spec['public_members']
 need(len(names)==len(set(names))==3 and set(names)==set(expected)|{spec['encrypted_output']['name']},'STOPPED_PARENT_EXACT_THREE_MEMBER_REVIEW_ARCHIVE')
 for n,pin in expected.items():
  raw=z.read(n);need(len(raw)<2*1024**2 and dict(bytes=len(raw),sha256=sha(raw))==pin,'STOPPED_PARENT_PUBLIC_BYTES:'+n)
 stage=json.loads(z.read('stopped-review-staging.json'))
 need(stage['status']=='STAGING_PASSED' and stage['run_id']==str(spec['run_id']) and stage['source_commit']==spec['head']
  and stage['source_files_verified']==514 and stage['members_verified']==591 and stage['authenticated_before_parsing'] is stage['offline_image_source_verified'] is stage['runtime_index_config_layer_chain_verified'] is True
  and stage['replay_started'] is False,'STOPPED_PARENT_AUTHENTICATED_ORIGINAL_FROZEN_STAGE')
 return set(names)
def capsule_tree(raw):
 need(sha(raw)==CRYPTO_SHA,'STOPPED_PARENT_WHOLE_ORIGINAL_CRYPTO_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
 scope,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FACTUAL_OLD_SCOPE' for a in n.args)]
 scope.args[0]=ast.parse('review_receipt_valid(r,spec,asset)',mode='eval').body
 class Public(ast.NodeTransformer):
  count=0
  def visit_Set(self,n):
   if ast.unparse(n)=="{spec['receipt_name'], 'full-core-staging.json', asset['name']}":
    self.count+=1;return ast.copy_location(ast.parse('public_names(spec,z)',mode='eval').body,n)
   return self.generic_visit(n)
 adapter=Public();fn=adapter.visit(fn);need(adapter.count==1,'STOPPED_PARENT_ONE_EXACT_PUBLIC_FORMAT_SITE')
 tail,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FACTUAL_OLD_SOURCE_REVIEW' for a in n.value.args)]
 fn.body=fn.body[:tail]+ast.parse('validate_capsule(spec,inventory,dest)\nreturn dest').body
 return ast.fix_missing_locations(fn)
def validate_capsule(spec,inventory,root):
 parent,value=review_record(spec);root=Path(root)
 need(len(inventory)==spec['manifest']['member_count'] and sum(v['bytes'] for v in inventory.values())==spec['manifest']['raw_member_bytes'],'STOPPED_PARENT_ENTIRE_POSITIVE_CAPSULE_INVENTORY')
 def member(n):
  raw=(root/n).read_bytes();need(dict(bytes=len(raw),sha256=sha(raw))==inventory[n],'STOPPED_PARENT_CAPSULE_MEMBER_AT_USE:'+n);return raw
 request_raw=member('request.json');q=json.loads(request_raw)
 need(dict(bytes=len(request_raw),sha256=sha(request_raw))==spec['original_request_member']
  and q['schema']=='research.stopped-evidence-review-request/1' and q['financial_authority'] is q['input_adopted'] is False
  and q['maximum_parallel_financial_workers']==0 and q['maximum_parallel_readonly_workers']==1,'STOPPED_PARENT_ORIGINAL_READONLY_REQUEST')
 from system_campaign_financial_partial import root_spec,archived_inspection
 original=root_spec(parent['arm'],parent['root_admission']['parent_root_admission_sha256'])
 need(json.loads(member('spec.json'))==original and original['base']==parent['base'] and original['source_binding_sha256']==parent['source_binding_sha256'],'STOPPED_PARENT_ORIGINAL_REVIEW_PARENT_AND_SAME_FINANCIAL_SOURCE_EPOCH')
 import system_campaign_financial_resume as resume
 raw=Path(resume.__file__).read_bytes();fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
 command=value.get('review_command','/driver/system_campaign_stopped_review.py')
 need(command in ('/driver/system_campaign_stopped_review.py','/driver/system_campaign_source_exit_stopped_review.py'),'STOPPED_PARENT_EXACT_KNOWN_READONLY_REVIEW_COMMAND')
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/driver/system_campaign_financial_resume.py'];site.value=command
 scope=dict(vars(resume));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-inspector-positive-review-command-only>','exec'),scope)
 for n,expected in spec['inspections'].items():archived_inspection(dict(spec,archive_format='FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1'),expected,json.loads(member(n)),scope['inspect'])
 for n,pin in value['proof_sha256s'].items():need(sha(member(n))==pin,'STOPPED_PARENT_SEPARATE_POSITIVE_PROOF_BYTES:'+n)
 core,branch,month,summary=[json.loads(member(n)) for n in ('core-review.json','uncertainty-certificate-review.json','monthly-reproduction.json','stopped-review-summary.json')]
 a=parent['root_admission'];bp=a['branch_uncertainty_proof']
 need(core['checkpoint_sha256']==branch['checkpoint_sha256']==month['checkpoint_sha256']==summary['checkpoint_sha256']==parent['outer_sha256']
  and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is branch['passed'] is branch['every_reachable_decision_identical'] is True
  and core['counts']==dict(formation=126,daily=parent['measured_closes']) and core['complete'] is False
  and (branch['rows'],branch['retained_rows'])==(bp['rows'],bp['retained_rows'])
  and month['passed'] is month['all_new_monthly_reports_exact'] is month['all_monthly_checkpoint_state_exact'] is True
  and month['financial_transitions_reexecuted']==0 and month['new_daily_records']==a['new_daily_records']
  and summary['passed'] is summary['independent_root_admission_required'] is True and summary['financial_sessions_advanced']==0,
  'STOPPED_PARENT_FULL_POSITIVE_CORE_BRANCH_AND_MONTHLY_CAPSULE')
 return True
def bind(fn,**changes):
 need(fn.__closure__ is None,'STOPPED_PARENT_EXPLICIT_WHOLE_FUNCTION_BINDINGS')
 result=FunctionType(fn.__code__,dict(fn.__globals__,**changes),fn.__name__,fn.__defaults__);result.__kwdefaults__=fn.__kwdefaults__;return result
def host_guard():
 from probe import check_context
 check_context(os.environ)
def qualified_view(financial,reviewed,view,spec):
 host_guard();value=record(spec);financial,reviewed,view=map(Path,(financial,reviewed,view))
 need(not view.exists() and all(not p.is_symlink() for p in financial.rglob('*')),'STOPPED_PARENT_FRESH_OWNED_VIEW_NO_SYMLINKS')
 before={p.relative_to(financial).as_posix():sha256_file(p) for p in financial.rglob('*') if p.is_file()}
 need(before['book/checkpoint.json.gz']==spec['selected_file']['sha256'],'STOPPED_PARENT_ORIGINAL_GENUINE_BOOK_BEFORE_COPY')
 shutil.copytree(financial,view)
 for p in [view,*view.rglob('*')]:
  if p.is_dir():p.chmod(stat.S_IMODE(p.stat().st_mode)|stat.S_IWUSR|stat.S_IXUSR)
 folder=view/value['review_directory'];need(not folder.exists() and view.resolve() in folder.resolve().parents,'STOPPED_PARENT_SEPARATE_POSITIVE_NAMESPACE')
 folder.mkdir(parents=True)
 for n,pin in value['proof_sha256s'].items():
  raw=(reviewed/n).read_bytes();need(sha(raw)==pin,'STOPPED_PARENT_REVIEW_BYTES_AT_COPY:'+n)
  with (folder/n).open('xb') as f:f.write(raw)
 need(all(sha256_file(view/n)==pin for n,pin in before.items()),'STOPPED_PARENT_ALL_ORIGINAL_FILES_UNCHANGED_AFTER_ADDING_POSITIVE_PROOFS')
 return view
def admit(spec,root,key,inspector,*,request,profile_validator):
 host_guard();value=record(spec);need(callable(profile_validator) and profile_validator(request,spec) is True,'STOPPED_PARENT_QUALIFIED_PROFILE_REQUIRED')
 import system_campaign_financial_review_repair as original
 target=value['financial']
 def exact(actual):need(actual==target,'STOPPED_PARENT_EXACT_FINANCIAL_QUARANTINE');return True
 public=bind(original.public_names,validate_target=exact)
 def guard(requested,actual):exact(actual);need(profile_validator(requested,spec) is True,'STOPPED_PARENT_EXACT_ACTIVE_REQUEST_AT_QUARANTINE')
 def refusal(actual,inventory,folder):
  exact(actual);raw=(folder/'stopped-review/worker.log').read_bytes()
  marker=value.get('original_review_failure_marker','P06_WWE12_NO_REEXECUTED_OLD_CASH_SOURCE_OBSERVATIONS_OR_REFUSAL').encode()
  need(sha(raw)==target['review_log_sha256']==inventory['stopped-review/worker.log']['sha256'] and marker in raw,'STOPPED_PARENT_ORIGINAL_FAILED_REVIEW_PRESERVED')
 fn,=[n for n in ast.parse(Path(original.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
 limit=value.get('archive_limit',512*1024**2)
 need(limit in (512*1024**2,1024**3) and target['zip_bytes']<limit,'STOPPED_PARENT_EXACT_EXISTING_ARCHIVE_SIZE_OPTION')
 site,=[kw for n in ast.walk(fn) if isinstance(n,ast.Call) for kw in n.keywords if kw.arg=='max_zip_bytes']
 need(ast.unparse(site.value)=='512 * 1024 ** 2','STOPPED_PARENT_ONE_ORIGINAL_DOWNLOAD_BOUND_SITE');site.value=ast.Constant(limit)
 scope=dict(vars(original),public_names=public,prove_refusal=refusal,request_only_readonly=guard,RUN=target['run_id'],HEAD=target['head'])
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-original-failed-parent-transport-existing-bound-option>','exec'),scope)
 financial=scope['admit'](target,root,key,inspector)
 import system_campaign_financial_partial as partial
 scope=dict(vars(partial.crypto),public_names=public_names,review_receipt_valid=review_receipt_valid,validate_capsule=validate_capsule)
 exec(compile(ast.Module(body=[capsule_tree(Path(partial.crypto.__file__).read_bytes())],type_ignores=[]),'<whole-original-authentication-positive-capsule-format>','exec'),scope)
 reviewed=scope['admit'](value['review'],Path(root).with_name(Path(root).name+'-review'),key,max_zip_bytes=512*1024**2)
 return qualified_view(financial,reviewed,Path(root)/'qualified-input-view',spec)
def accounting_review(spec):
 value=record(spec);return value['review_directory']+'/core-review.json',value['proof_sha256s']['core-review.json']
@contextmanager
def context(spec,request,*,profile_validator):
 host_guard()
 if not applies(spec):yield;return
 record(spec);need(callable(profile_validator) and profile_validator(request,spec) is True,'STOPPED_PARENT_EXPLICIT_QUALIFIED_CONTEXT')
 import system_campaign_financial_requalified_parent as dispatch
 saved={n:getattr(dispatch,n) for n in ('applies','admit','accounting_review')}
 dispatch.applies=lambda v:applies(v) or saved['applies'](v)
 dispatch.admit=lambda v,*a,**k:admit(v,*a,**k,request=request,profile_validator=profile_validator) if applies(v) else saved['admit'](v,*a,**k)
 dispatch.accounting_review=lambda v:accounting_review(v) if applies(v) else saved['accounting_review'](v)
 try:yield
 finally:
  for n,v in saved.items():setattr(dispatch,n,v)
