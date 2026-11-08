"""Authenticate admitted1403 finance and its separate successful review."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_request231_review as quarantine
import system_campaign_p07_fin326_requalified_parent as original
HERE=Path(__file__).parent
ROOT='8571f67e874bc4cc4677b8e8876bc116186952f4f7307d651e0131fce0017be2'
FLAG='root_request231_requalified_review_parent'
CATALOG='P07-request233-independent-readonly-review-transport.json'
CATALOG_SHA='40b4190964c7765e2d5829d1271b11bf8b0bf31d4744b51987ab58d67fe491d6'
TARGET_SHA='3b0589405f1fb124e6898389b9285793d8b01c7f426a904f30318f66eaddcb49'
ORIGINAL_SHA='ca981e5bc69446730cc390093aaf59ed5eec310ac15e950feacb68d4bdb6f680'
PROVENANCE='lineage/request231-review-requalification'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def applies(spec):return isinstance(spec,dict) and spec.get(FLAG)is True and spec.get('root_admission_sha256')==ROOT

def source_names():return (Path(__file__).name,CATALOG,Path(original.__file__).name,*quarantine.source_names())

def transport():
 raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'PARENT231_EXACT_INDEPENDENTLY_ADMITTED_POSITIVE_REVIEW_TRANSPORT')
 v=json.loads(raw)
 need((v['run_id'],v['head'],v['artifact_id'],v['zip_bytes'],v['zip_sha256'])==(42438949829,'2af252611f6b1c55d9339490620e9675e8f8c026',13601296206,20019555,
  'f12ae887093c71b71152d8a61446a7770c357f540cb7643b41630f82c207515c')
  and v['manifest']==dict(member_count=100,raw_member_bytes=20790922) and v['original_failed_financial_transport_sha256']==TARGET_SHA
  and v['financial_authority'] is v['input_adopted'] is False and v['financial_workers']==0 and v['readonly_workers']==1,
  'PARENT231_ONLY_ACTUAL_SEPARATE_READONLY233_NO_FINANCIAL_BOOK')
 return v

def validated(spec):
 from system_campaign_financial_partial import validate_root_spec
 need(applies(spec),'PARENT231_ONLY_EXACT_INDEPENDENTLY_ADMITTED1403_ROOT');validate_root_spec(spec)
 target={k:deepcopy(v) for k,v in spec.items() if k not in (FLAG,'qualified_review_transport_sha256','root_admission','root_admission_sha256')}
 target[quarantine.MARKER]=True;target[quarantine.repair.FLAG]=True
 need(sha(encoded(target))==TARGET_SHA and target==quarantine.fact()['target'],'PARENT231_ORIGINAL_FAILED_FINANCIAL_TARGET_UNCHANGED')
 quarantine.validate_target(target);review=transport();a=spec['root_admission'];proof=a['failed_review_requalification']
 need(spec['qualified_review_transport_sha256']==CATALOG_SHA and a['completed']==1403 and a['source_cursor']=='2023-07-31'
  and len(a['repairs'])==26 and a['parent_root_admission_sha256']==quarantine.ORIGIN
  and proof==dict(schema='research.P07-request231-separate-positive-review/1',original_quarantine_target_sha256=TARGET_SHA,
   review_transport_sha256=CATALOG_SHA,core_review_sha256=review['core_review_sha256'],branch_review_sha256=review['branch_review_sha256'],
   distribution_review_sha256=review['distribution_review_sha256'],independent_review_sha256='3ad9419bbe87e61af3cd3488e27b63a97a4879ebf65d7c944a250541c6caebad',
   independent_validation_sha256='f0c1686b06293b0469c05f23cca51d011056cf3dcaf3601e329e21a189b97a23',original_failed_stops_preserved=True),
  'PARENT231_ENTIRE_ORIGINAL_INDEPENDENT_ADMISSION_AND_FRESH_REVIEW_PROOF')
 return target,review

def bind(fn,**changes):
 need(fn.__closure__ is None,'PARENT231_WHOLE_ORIGINAL_FUNCTION_WITHOUT_CLOSURE')
 value=FunctionType(fn.__code__,dict(fn.__globals__,**changes),fn.__name__,fn.__defaults__);value.__kwdefaults__=fn.__kwdefaults__;return value

def public_names(spec,archive):
 need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'PARENT231_ORIGINAL_REQUALIFIED_READER_SOURCE')
 return bind(original.public_names,transport=transport)(spec,archive)

def authenticate_review(spec,root,key,inspector):
 quarantine.launcher_guard();need(spec==transport(),'PARENT231_ONLY_EXACT_POSITIVE_REVIEW_ARCHIVE')
 return bind(original.authenticate_review,public_names=public_names)(spec,root,key,inspector)

def view_tree(raw):
 need(sha(raw)==ORIGINAL_SHA,'PARENT231_WHOLE_ORIGINAL_INPUT_VIEW_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualified_view']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='lineage/root-review-requalification'];site.value=PROVENANCE
 mapping,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='replacements']
 need(ast.literal_eval(mapping)=={'uncertainty-certificate-review.json':'uncertainty-certificate-review.json',
  'stopped-review/uncertainty-certificate-review.json':'uncertainty-certificate-review.json','stopped-review/core-review.json':'core-review.json'},
  'PARENT231_THREE_ORIGINAL_POSITIVE_REVIEW_REPLACEMENT_SITES')
 mapping.keys.append(ast.Constant(quarantine.runtime.EVENT_REVIEW));mapping.values.append(ast.Constant(quarantine.runtime.EVENT_REVIEW))
 return ast.fix_missing_locations(fn)

def view_function():
 scope=dict(vars(original),quarantine=quarantine,QUARANTINE_SHA=TARGET_SHA,CATALOG_SHA=CATALOG_SHA)
 exec(compile(ast.Module(body=[view_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-qualified-view-new-provenance-and-BWA-proof>','exec'),scope)
 return scope['qualified_view']

def qualified_view(financial,reviewed,view,target,review):
 quarantine.launcher_guard();quarantine.validate_target(target);need(review==transport(),'PARENT231_EXACT_POSITIVE_REVIEW_FOR_VIEW')
 need(sha((Path(reviewed)/'monthly-reproduction.json').read_bytes())==review['monthly_review_sha256'],'PARENT231_ORIGINAL_SUCCESSFUL_MONTHLY_PROOF')
 value=view_function()(financial,reviewed,view,target,review)
 need(sha((value/quarantine.runtime.EVENT_REVIEW).read_bytes())==review['distribution_review_sha256'],'PARENT231_FRESH_BWA_REVIEW_EXACTLY_PRESERVED')
 return value

def require_future_request(request,spec,authorize):
 validated(spec)
 need(callable(authorize) and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION' and request['financial_resume_authorized'] is True
  and request['readonly_partial_review'] is request['readonly_source_witnesses'] is False and 'P07' in request['arms']
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==len(request['arms'])
  and request['maximum_parallel_readonly_workers']==0 and request['admitted_checkpoints']['P07']==spec['outer_sha256'],
  'PARENT231_EXPLICIT_FUTURE_FINANCIAL_REQUEST_CALLER_REQUIRED')
 need(authorize(request,spec)is True,'PARENT231_CALLER_MUST_CERTIFY_ENTIRE_FUTURE_PROFILE')
 return True

def admit(spec,root,key,inspector,*,request,authorize):
 quarantine.launcher_guard();target,review=validated(spec);require_future_request(request,spec,authorize)
 def request_binding(actual,current):
  need(actual==request and current==target,'PARENT231_ONLY_EXACT_CURRENT_REQUEST_AND_ORIGINAL_FAILED_TARGET')
  return require_future_request(actual,spec,authorize)
 # Keep the whole original one-GiB crypto/extraction/process/capacity reader.
 fn=quarantine.legacy('admit');financial=bind(fn,request_only_readonly=request_binding)(target,root,key,inspector)
 reviewed=authenticate_review(review,Path(root).with_name(Path(root).name+'-request233-review'),key,inspector)
 need((financial/'source-bindings.json').read_bytes()==(reviewed/'source-bindings.json').read_bytes()
  and json.loads((reviewed/'spec.json').read_bytes())==target,'PARENT231_SAME_EXACT_FINANCIAL_SOURCE_AND_TARGET')
 return qualified_view(financial,reviewed,Path(root)/'qualified-request231-input-view',target,review)

def accounting_review(spec):
 _,review=validated(spec);return 'stopped-review/core-review.json',review['core_review_sha256']
