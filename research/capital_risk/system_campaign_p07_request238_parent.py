"""Authenticate saved1426 finance and its separate complete successful review."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_p07_request238_review as quarantine
import system_campaign_p07_request231_parent as previous
original=previous.original
bind=previous.bind
HERE=Path(__file__).parent
ROOT='b134772ff8128b4f97a16dabbc357f07e019351c529c03419cb778726fad5a59'
FLAG='root_request238_requalified_review_parent'
CATALOG='P07-request243-independent-readonly-review-transport.json'
CATALOG_SHA='8c77332fec0eccfc9948e57296588a460235c6cda4ba7d52511c2e0ebdcbd891'
TARGET_SHA='e2012209f49f9a97cf05b67c6ee90099615a43ae9952deccef9ef6696c5b63fb'
QUALIFICATION='P07-request238-independent-DATA-qualification.json'
PROVENANCE='lineage/request238-review-requalification'


def applies(spec):return isinstance(spec,dict) and spec.get(FLAG) is True


def encoded(value):return quarantine.encoded(value)


def transport():
 raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'PARENT238_EXACT_POSITIVE_READONLY_TRANSPORT')
 value=json.loads(raw)
 need((value['run_id'],value['head'],value['artifact_id'],value['manifest'])==
  (42464937189,'5b70978428fe3e9c86a62ce8c060aea5a4e1bed1',13611423500,dict(member_count=67,raw_member_bytes=5797037))
  and value['original_failed_financial_transport_sha256']==TARGET_SHA and value['financial_workers']==0
  and value['financial_authority'] is value['input_adopted'] is False
  and all(value['prior_stops'][role]==dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
   for role in ('preflight','repair_reviewer')),'PARENT238_EXACT_ZERO_FINANCIAL_SUCCESSFUL_REVIEW243')
 return value


def validated(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec)
 need(applies(spec) and spec['root_admission_sha256']==ROOT and spec['qualified_review_transport_sha256']==CATALOG_SHA,
  'PARENT238_ONLY_EXACT_INDEPENDENTLY_ADMITTED1426_ROOT')
 target={k:deepcopy(v) for k,v in spec.items() if k not in (FLAG,'qualified_review_transport_sha256','root_admission','root_admission_sha256')}
 target[quarantine.MARKER]=True;target[quarantine.repair.FLAG]=True
 need(sha(encoded(target))==TARGET_SHA and target==quarantine.target(),'PARENT238_ORIGINAL_FAILED_FINANCIAL_TARGET_UNCHANGED')
 quarantine.validate_target(target);review=transport();a=spec['root_admission'];proof=a['failed_review_requalification']
 need((a['completed'],a['source_cursor'],len(a['repairs']))==(1426,'2023-08-31',27)
  and a['parent_root_admission_sha256']==quarantine.ORIGIN
  and sha((HERE/QUALIFICATION).read_bytes())==a['independent_validation_sha256']
  and proof==dict(schema='research.P07-request238-separate-positive-review/1',original_quarantine_target_sha256=TARGET_SHA,
   review_transport_sha256=CATALOG_SHA,core_review_sha256=review['core_review_sha256'],branch_review_sha256=review['branch_review_sha256'],
   distribution_review_sha256=review['distribution_review_sha256'],cash_review_sha256=review['cash_review_sha256'],
   independent_review_sha256=a['independent_review_sha256'],independent_validation_sha256=a['independent_validation_sha256'],
   original_failed_stops_preserved=True),'PARENT238_ENTIRE_ORIGINAL_ROOT_AND_FRESH_REVIEW_PROOF')
 return target,review


def public_names(spec,archive):
 need(sha(Path(original.__file__).read_bytes())==previous.ORIGINAL_SHA,'PARENT238_WHOLE_ORIGINAL_REVIEW_READER_SOURCE')
 return bind(original.public_names,transport=transport)(spec,archive)


def authenticate_review(spec,root,key,inspector):
 quarantine.previous.launcher_guard();need(spec==transport(),'PARENT238_ONLY_EXACT_POSITIVE_REVIEW_ARCHIVE')
 return bind(original.authenticate_review,public_names=public_names)(spec,root,key,inspector)


def view_tree(raw):
 need(sha(raw)==previous.ORIGINAL_SHA,'PARENT238_WHOLE_ORIGINAL_IMMUTABLE_VIEW_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualified_view']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='lineage/root-review-requalification'];site.value=PROVENANCE
 mapping,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='replacements']
 need(ast.literal_eval(mapping)=={'uncertainty-certificate-review.json':'uncertainty-certificate-review.json',
  'stopped-review/uncertainty-certificate-review.json':'uncertainty-certificate-review.json','stopped-review/core-review.json':'core-review.json'},
  'PARENT238_THREE_ORIGINAL_REVIEW_REPLACEMENT_SITES')
 for destination,source in ((quarantine.retained.previous.EVENT_REVIEW,quarantine.retained.previous.EVENT_REVIEW),
  ('stopped-review/p07-vivo-ordinary25-cash-review.json','p07-vivo-ordinary25-cash-review.json'),
  ('stopped-review/request238-full27-history-review.json','request238-full27-history-review.json')):
  mapping.keys.append(ast.Constant(destination));mapping.values.append(ast.Constant(source))
 return ast.fix_missing_locations(fn)


def view_function():
 api=SimpleNamespace(**dict(vars(quarantine),launcher_guard=quarantine.previous.launcher_guard))
 scope=dict(vars(original),quarantine=api,QUARANTINE_SHA=TARGET_SHA,CATALOG_SHA=CATALOG_SHA)
 exec(compile(ast.Module(body=[view_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-qualified-view-with-explicit-six-positive-proofs>','exec'),scope)
 return scope['qualified_view']


def qualified_view(financial,reviewed,view,target,review):
 quarantine.previous.launcher_guard();quarantine.validate_target(target);need(review==transport(),'PARENT238_EXACT_POSITIVE_REVIEW_FOR_VIEW')
 need(sha((Path(reviewed)/'monthly-reproduction.json').read_bytes())==review['monthly_review_sha256'],'PARENT238_EXACT_SUCCESSFUL_MONTHLY_PROOF')
 value=view_function()(financial,reviewed,view,target,review)
 records=quarantine.supplement_records()
 for name,raw in records.items():exact(value/name,raw)
 exact(value/PROVENANCE/'historical-observer-supplements.json',encoded(dict(passed=True,original_artifact_id=13598958730,
  records={n:quarantine.pin(raw) for n,raw in records.items()},financial_book_changed=False,financial_sessions_advanced=0)))
 exact(value/PROVENANCE/'prior-monthly-reproduction.json',(Path(reviewed)/'monthly-reproduction.json').read_bytes())
 return value


def require_future_request(request,spec,authorize):
 validated(spec)
 need(callable(authorize) and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION' and request['financial_resume_authorized'] is True
  and request['readonly_partial_review'] is request['readonly_source_witnesses'] is False and 'P07' in request['arms']
  and type(request['maximum_parallel_financial_workers'])is int and request['maximum_parallel_financial_workers']==len(request['arms'])
  and request['maximum_parallel_readonly_workers']==0 and request['admitted_checkpoints']['P07']==spec['outer_sha256'],
  'PARENT238_EXPLICIT_FUTURE_FINANCIAL_REQUEST_CALLER_REQUIRED')
 need(authorize(request,spec)is True,'PARENT238_CALLER_MUST_CERTIFY_ENTIRE_FUTURE_PROFILE');return True


def admit(spec,root,key,inspector,*,request,authorize):
 quarantine.previous.launcher_guard();target,review=validated(spec);require_future_request(request,spec,authorize)
 def request_binding(actual,current):
  need(actual==request and current==target,'PARENT238_ONLY_EXACT_CURRENT_REQUEST_AND_ORIGINAL_FAILED_TARGET')
  return require_future_request(actual,spec,authorize)
 fn=quarantine.legacy('admit');financial=bind(fn,request_only_readonly=request_binding)(target,root,key,inspector)
 reviewed=authenticate_review(review,Path(root).with_name(Path(root).name+'-request243-review'),key,inspector)
 need((financial/'source-bindings.json').read_bytes()==(reviewed/'source-bindings.json').read_bytes()
  and json.loads((reviewed/'spec.json').read_bytes())==target,'PARENT238_EXACT_FINANCIAL_SOURCE_AND_REVIEW_TARGET')
 return qualified_view(financial,reviewed,Path(root)/'qualified-request238-input-view',target,review)


def accounting_review(spec):
 _,review=validated(spec);return 'stopped-review/core-review.json',review['core_review_sha256']


def source_names():return (Path(__file__).name,CATALOG,QUALIFICATION,*quarantine.source_names())
