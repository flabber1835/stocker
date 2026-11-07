"""Authenticated post-close distribution source, using original pure v2 functions."""
import ast,csv,gzip,json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import FunctionType
import system_campaign_financial_compound_input_v2 as original
import system_campaign_financial_distribution_source_v2 as source
from system_campaign_facts import sha,digest
from full_system_benchmark import need
HERE=Path(__file__).parent
CATALOG='P07-BWA-postclose-source-catalog.json'
CATALOG_SHA='6a6de9498afc77747b26a2ed36c5f153289894ec4567f7ac9fe85db9d67eedcd'
REVIEW='P07-BWA-source-DATA-review.json'
QUALIFICATION='P07-BWA-source-DATA-qualification.json'
MODEL_SHA='13207b6c2a2c36b7f7a1c09b70446b11942b9e1bc1f316643721d47ea3d87d9a'
SOURCE_SHA='820be270c8c84aa40e81c18cc92aed4e24f1f45d414f04f6f4b514464ab6de17'
AXIS_SHA='cc5c05fc2392dcb41ac0de142329e49d590b937b53c4fadc49b50f857ed7c34a'
encoded=original.encoded

def validate(value):
 from system_campaign_financial_partial import root_spec,validate_root_spec
 need(value['schema']=='research.batch-bound-postclose-distribution-source/1'
  and value['financial_authority'] is value['financial_profile_ready'] is value['input_adopted'] is value['canonical_runtime_executed'] is False
  and type(value['financial_sessions_advanced'])is int and value['financial_sessions_advanced']==0,'POSTCLOSE_SOURCE_NO_FINANCIAL_AUTHORITY')
 spec=root_spec(value['arm'],value['parent_root_admission_sha256']);validate_root_spec(spec)
 need(value['arm']=='P07' and value['parent_outer_sha256']==spec['outer_sha256'] and value['parent_state_sha256']==spec['state_sha256']
  and value['parent_input_sha256']==spec['input_sha256'] and value['parent_descriptors']==spec['repairs']
  and value['parent_selected_file']==spec['selected_file'] and value['parent_completed']==spec['measured_closes']==1383
  and value['parent_cursor']==spec['selected_session']=='2023-06-30' and len(spec['repairs'])==25,'POSTCLOSE_ENTIRE_EXACT_ADMITTED_PARENT')
 payload,request,mf,capture=[value[k] for k in ('source_payload','captured_source_request','source_manifest','authenticated_capture')]
 need(sha(encoded(payload))==mf['members']['source-evidence.json']['sha256']=='464b807d7f2c528f8634c00bafd26dcd9f773991973f59499b64591bb3b283ac'
  and len(encoded(payload))==mf['members']['source-evidence.json']['bytes']
  and sha(encoded(request))==payload['request_sha256']==mf['request_sha256']=='1c26566d3c2788cf6c229c3c06bb678cbcefcd4f39c15c5f3818725eb3ac4039'
  and payload['producer_sha256']==request['sources']['system_campaign_source_batch.py']
  and payload['original_parser_sha256']==source.PARSER_SHA
  and payload['schema']=='research.source-evidence-batch/1' and payload['context_is_not_event_date_ownership'] is True
  and payload['financial_authority'] is payload['input_adopted'] is payload['production_contacted'] is False
  and type(payload['financial_sessions_advanced'])is int and payload['financial_sessions_advanced']==0,'POSTCLOSE_AUTHENTICATED_WHOLE_BATCH_AND_ORIGINAL_REQUEST')
 need(capture['schema']=='research.authenticated-source-batch/1' and capture['source_rows_verified'] is capture['worker_fences_verified'] is True
  and capture['financial_authority'] is capture['input_adopted'] is False and capture['financial_sessions_advanced']==0
  and (capture['artifact'],capture['zip_bytes'],capture['zip_sha256'])==(13580637335,48413,'342b8110eac0159379d076e2c001585284f0d563adff5ec9250c42bb33740594')
  and str(capture['run'])==mf['run_id']=='42388826916' and capture['head']==mf['head']=='5be1be10d66c703af04adb8efce2ca8e43fbf599',
  'POSTCLOSE_EXACT_AUTHENTICATED_CAPTURE_NOT_EVENT_DATE_OWNERSHIP')
 context=payload['admitted_context']['P07']
 need(context==dict(root_admission_sha256=spec['root_admission_sha256'],outer_sha256=spec['outer_sha256'],
  completed=spec['measured_closes'],through=spec['selected_session'],input_sha256=spec['input_sha256'])
  and payload['archive_sha256']==spec['base']['archive_sha256'] and payload['bundle_sha256']==spec['base']['bundle_sha256'],
  'POSTCLOSE_SOURCE_SAME_ADMITTED_ROOT_AND_FROZEN_INPUTS')
 primary,axis=value['primary_clock'],value['frozen_axis']
 need(primary['url']=='https://www.sec.gov/Archives/edgar/data/908255/000090825523000036/bwa-20230703.htm'
  and primary['filing_date']=='2023-07-10' and primary['legal_distribution_date']=='2023-07-03'
  and primary['legal_distribution_time_EDT']=='17:00:00' and primary['record_date']=='2023-06-23'
  and primary['child_shares_per_original_parent']=='1/5' and primary['fractional_shares_paid_in_cash'] is True
  and primary['historical_availability']=='UNVERIFIED' and primary['actual_record_date_ownership_verified'] is False
  and axis==dict(gzip_sha256=AXIS_SHA,sessions=['2023-06-30','2023-07-03','2023-07-05','2023-07-06'],next_session_after_legal_date='2023-07-05')
  and value['event_date_ownership']=='UNKNOWN_UNTIL_ACTUAL_GUARDED_TRANSITION','POSTCLOSE_DISTINCT_PRIMARY_RECORD_LEGAL_NATIVE_AND_PUBLICATION_CLOCKS')
 need(sha(Path(source.__file__).read_bytes())==SOURCE_SHA and sha(Path(original.__file__).read_bytes())==MODEL_SHA,
  'POSTCLOSE_EXACT_UNCHANGED_SOURCE_AND_MODEL_IMPLEMENTATIONS')
 return spec

def catalog():
 raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'POSTCLOSE_EXACT_CLOSED_SOURCE_CATALOG')
 value=json.loads(raw);validate(value);return value

def validate_axis(raw,value):
 need(sha(raw)==AXIS_SHA==value['frozen_axis']['gzip_sha256'],'POSTCLOSE_ACTUAL_FROZEN_AXIS_BYTES')
 days=[r['session'] for r in csv.DictReader(gzip.decompress(raw).decode().splitlines())]
 need(days==sorted(set(days)) and days[days.index(value['parent_cursor']):days.index(value['parent_cursor'])+4]==value['frozen_axis']['sessions'],
  'POSTCLOSE_ACTUAL_NEXT_FROZEN_SESSION_AFTER_LEGAL_DISTRIBUTION')
 return True

def source_rows(value):
 observations=[v for v in value['source_payload']['observations'] if v['query']['arm']=='P07']
 groups=[v for v in value['source_payload']['native_groups'] if v['query']['arm']=='P07']
 need(len(observations)==3 and len(groups)==1 and len({v['query']['name'] for v in observations})==3,'POSTCLOSE_COMPLETE_PARENT_CHILD_AND_PRIOR_SOURCE_QUERIES')
 group,=groups
 need(group['status']=='FOUND' and group['original_typed_terminals']==[] and len(group['raw_rows'])==len(group['original_typed_distributions'])==2
  and group['event_date_ownership']=='UNKNOWN_NOT_CAPTURED' and group['financial_authority'] is False,'POSTCLOSE_COMPLETE_TWO_NATIVE_ROWS_WITHOUT_TERMINAL')
 rows=[]
 for item in observations:
  need(item['status']=='FOUND' and len(item['rows'])==1 and item['event_date_ownership']=='UNKNOWN_NOT_CAPTURED'
   and item['financial_authority'] is False,'POSTCLOSE_COMPLETE_FOUND_SOURCE_ROWS_WITHOUT_OWNERSHIP_PROMOTION')
  row=item['rows'][0];query=item['query']
  need(row['source_row_sha256']==digest(row['source_row']) and row['source_row']['session']==query['session']
   and row['source_row']['ticker']==query['ticker'] and (query['security_id'] is None or row['source_row']['security_id']==query['security_id']),
   'POSTCLOSE_UNCHANGED_ENTIRE_SOURCE_OBSERVATION')
  rows.append(deepcopy(row['source_row']))
 need({(r['session'],r['security_id'],r['ticker']) for r in rows}=={
  ('2023-07-03',value['parent_security_id'],'BWA'),('2023-07-05',value['parent_security_id'],'BWA'),
  ('2023-07-05',value['child_security_id'],'PHIN')},'POSTCLOSE_EXACT_DISTINCT_NATIVE_PARENT_AND_CHILD_IDENTITIES')
 raw=[]
 for item in group['raw_rows']:
  need(digest(item['row'])==item['sha256'],'POSTCLOSE_ENTIRE_ORIGINAL_RAW_ACTION_ROW');raw.append(deepcopy(item['row']))
 return rows,raw,deepcopy(group['original_typed_distributions'])

def normalize(value):
 spec=validate(value);rows,raw,natives=source_rows(value);positions=value['parent_positions'];parent=value['parent_security_id']
 need(set(positions)=={parent,value['child_security_id']} and positions[parent] and positions[value['child_security_id']]==[]
  and all(type(v['quantity'])is int and v['quantity']>0 for v in positions[parent]),'POSTCLOSE_REAL_ADMITTED_LONG_ONLY_PARENT_AND_ABSENT_CHILD')
 queries=[dict(schema='research.exact-native-distribution-query/1',session=n['session'],parent_security_id=n['parent_security_id'],
  parent_ticker=n['parent_ticker'],source_row_id=n['source_row_id'],native_term_sha256=digest(n),
  raw_source_row_sha256=digest(next(r for r in raw if sha(json.dumps(r,sort_keys=True).encode())==n['source_row_id'])),
  maximum_records=1,financial_use_authorized=False) for n in natives]
 scope=dict(schema=source.DISTRIBUTION_ONLY_SCOPE,parent_outer_sha256=spec['outer_sha256'],parent_cursor=spec['selected_session'],terms=[],
  additional_rows=[dict(session=r['session'],security_id=r['security_id'],ticker=r['ticker'],source_observation_sha256=digest(r),
   parent_positions=deepcopy(positions[r['security_id']])) for r in rows],native_distribution_queries=queries,expected_native_distribution_count=2)
 pairs=source.distribution_only_pairing(scope,raw,natives)
 material=source.distribution_only_material(scope,rows,pairs,positions)
 producer=sha(Path(__file__).read_bytes());witness=source.distribution_only_payload(spec,scope,material,producer)
 source.distribution_only_validate(witness,spec,scope,producer)
 return witness

def require_clock(model,value):
 need(model.actual_distribution_session==value['primary_clock']['legal_distribution_date']
  and model.recognition_session==value['frozen_axis']['next_session_after_legal_date']
  and model.actual_distribution_session<model.recognition_session and value['primary_clock']['legal_distribution_time_EDT']=='17:00:00'
  and Fraction(model.child_shares_per_original_parent)==Fraction(value['primary_clock']['child_shares_per_original_parent']),
  'POSTCLOSE_EXACT_PRIMARY_RATIO_AND_NEXT_SESSION_WITHOUT_RELABELING')
 return True

def model_tree(raw):
 need(sha(raw)==MODEL_SHA,'POSTCLOSE_WHOLE_ORIGINAL_V2_MODEL_VALIDATOR')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_model']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=='model.actual_distribution_session == model.recognition_session']
 class Clock(ast.NodeTransformer):
  def visit_Compare(self,node):
   return ast.copy_location(ast.parse('require_clock(model)',mode='eval').body,node) if node is site else self.generic_visit(node)
 return ast.fix_missing_locations(Clock().visit(fn))

def validate_model(model,value=None):
 value=catalog() if value is None else value;validate(value)
 namespace=dict(vars(original),require_clock=lambda model:require_clock(model,value))
 exec(compile(ast.Module(body=[model_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-v2-validator-one-postclose-clock>','exec'),namespace)
 return namespace['validate_model'](model)

def qualified_source(value):
 witness=normalize(value);qraw=(HERE/QUALIFICATION).read_bytes();q=json.loads(qraw);review=(HERE/REVIEW).read_bytes()
 need(q['passed'] is q['source_closed'] is True and q['financial_authority'] is q['financial_profile_ready'] is q['canonical_runtime_executed'] is False
  and q['catalog_sha256']==sha(encoded(value)) and q['normalized_payload_sha256']==sha(encoded(witness))
  and q['review_sha256']==sha(review) and json.loads(review)['passed'] is True,'POSTCLOSE_COMPLETE_SOURCE_DATA_QUALIFICATION_ONLY')
 for name,pin in q['files'].items():
  raw=(HERE/name).read_bytes();need(dict(bytes=len(raw),sha256=sha(raw))==pin,'POSTCLOSE_QUALIFIED_SOURCE_BYTES:'+name)
 return witness,dict(independent_DATA_passed=True,independent_qualification_passed=True,payload_sha256=sha(encoded(witness)),
  payload_digest=digest(witness),scope_sha256=witness['scope_sha256'],distribution_producer_sha256=witness['distribution_producer_sha256'],
  independent_data_review_sha256=sha(review),independent_qualification_sha256=sha(qraw))

def bound_builder(value):
 fn=original.build_terms
 need(fn.__closure__ is None,'POSTCLOSE_WHOLE_ORIGINAL_TERM_BUILDER_WITHOUT_CLOSURE')
 return FunctionType(fn.__code__,dict(fn.__globals__,validate_model=lambda model:validate_model(model,value)),fn.__name__,fn.__defaults__)

def build_terms(value=None):
 value=catalog() if value is None else value;witness,proof=qualified_source(value)
 return bound_builder(value)(value['research_assumption'],witness,child_security_id=value['child_security_id'],
  reference=value['primary_clock']['url']+' | Disclosed daily post-close distribution assumption; record-date ownership and actual settlement unverified.',
  source_proof=proof)

def projection_type(value=None):
 value=catalog() if value is None else value;fn=original.EventSessionProjection.__init__
 bound=FunctionType(fn.__code__,dict(fn.__globals__,validate_model=lambda model:validate_model(model,value)),fn.__name__,fn.__defaults__)
 return type('PostCloseDistributionProjection',(original.EventSessionProjection,),{'__init__':bound})

def validate_parent(value,parent):
 from system_campaign_full_history_successor import current_commitments
 spec=validate(value);current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(parent['sha256']==spec['outer_sha256'] and parent['repairs']==spec['repairs'] and parent['completed']==spec['measured_closes']
  and parent['source_cursor']==spec['selected_session'],'POSTCLOSE_ACTUAL_COMPLETE_ADMITTED_PARENT_DATA')
 binding=build_terms(value);original.actual_role(parent['run']['state'],parent['run']['state']['pending'],binding)
 return dict(passed=True,admitted_parent_sha256=parent['sha256'],admitted_positions_verified=True,event_date_ownership_verified=False,financial_sessions_advanced=0)

def require_financial_profile():
 need(False,'POSTCLOSE_SOURCE_COMPONENT_HAS_NO_FINANCIAL_PROFILE')
