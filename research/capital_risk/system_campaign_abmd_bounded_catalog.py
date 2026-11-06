"""Closed original ABMD source generations with an absent completion-session quote."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from system_campaign_bounded_sensor_input import Event,SCHEMA,need,sha,digest

HERE=Path(__file__).parent
SID='1050970006012443443'
PRIMARY='ABMD-primary-source-facts.json'
PREPARATION='ABMD-raw-event-source-preparation.json'
PRIMARY_SHA='dbbd6ef79557720f8e2f60ce4336bc684dab88303451a8bd78c97127b1289e81'
PREPARATION_SHA='cd9153160449aa28b5f11634fa91a5a7baa19d59f590086a43d69397e81d2a91'
CATALOG_SCHEMA='research.qualified-abmd-bounded-sensor-catalog/1'
COMMON=frozenset(('system_campaign_bounded_sensor_input.py','system_campaign_bounded_sensor_binding.py',
    'system_campaign_financial_branches.py','system_campaign_uncertainty_context.py','system_campaign_uncertainty_math.py',
    'system_campaign_abmd_bounded_catalog.py','system_campaign_abmd_bounded_hydration.py'))
INHERITED={'system_campaign_financial_branches.py':'b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef',
 'system_campaign_uncertainty_context.py':'b9a51977d6456c5684564f74927d2a5585db2208156269c077b9d35eb8373610',
 'system_campaign_uncertainty_math.py':'a53a3a7b463659eb3788923d504c402a2edd183a3922f20abe51c55dcd303213'}
CASES={
 'P06':dict(root='947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e',
   outer='615f8daa736504d3ee8f9c17515e6fc4d014fd4f5a2fa4bd5e1af640249c942f',inputs=8,source_schema='research.own-parent-frozen-source-witnesses/1',terms=115,
   payload='402eb579e76eb4e4b276aa366286d60d09ee0689e33f12a38a35d35aa17a6328',
   review='dae384fa40fe89c38dc45fb0c284ea1cfdf45a49fba2be3d89e6509c43c7e74e',
   qualification='e12d8d4057d55cd5d58396a0f4535d9de84a831246f64afcc05516fdf645167b',
   binding='system_campaign_p06_abmd_initial_certificate.py',
   bindings=('system_campaign_p06_abmd_initial_certificate.py','system_campaign_p06_abmd_models.py')),
 'P07':dict(root='475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d',
   outer='efc954aafff81ce10213b5a6ec62f765b7120734a076459e0b04d9b468ed6277',inputs=23,source_schema='research.own-parent-frozen-source-witnesses/2',terms=1,
   payload='c1e381ac683e9dbe54970ae99988bef88152384ed4d8cc2047d151f5ec9fe647',
   review='c7d51f4a387190c4b883365317c708c599cc435124efccff27b3486e6de5e44d',
   qualification='97fca41a1f66d9abaec1e064b6dca68c34ffb0403f9b4fba29f804eeb842e472',
   binding='system_campaign_p07_abmd_certificate.py',
   bindings=('system_campaign_p07_abmd_certificate.py','system_campaign_p07_abmd_models.py'))}

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def event(native):
    return Event.model_validate(dict(ticker='ABMD',security_id=SID,native_session='2022-12-21',effective_session='2022-12-22',
        prior_session='2022-12-21',native_term_sha256=digest(native),currency='USD',upfront_cash_per_share='380.00',
        right_lower_per_share='0',right_upper_per_share='35.00',right_kind='NONTRANSFERABLE_CONTINGENT_VALUE_RIGHT',
        ownership_scope='UNOWNED_UNORDERED_SENSOR_ONLY',treatment='EVERY_REACHABLE_CANONICAL_DECISION_MUST_MATCH',
        price_or_probability_selected=False,cash_settlement_authorized=False,historical_causality='UNVERIFIED')).model_dump()

def verify_semantics(catalog,*,source_bytes=None,require_runtime=True):
    reader=(lambda name:(HERE/name).read_bytes()) if source_bytes is None else source_bytes
    pins=catalog['input_semantics_sources'];case=CASES[catalog['arm']]
    required=COMMON|(set(case['bindings']) if require_runtime else set())
    need(set(pins)==required and all(type(pin) is str and len(pin)==64 and sha(reader(name))==pin for name,pin in pins.items()),
         'ABMD_COMPLETE_EXACT_INTERPRETATION_SOURCE_BYTES')
    need(all(pins[n]==pin for n,pin in INHERITED.items()),'ABMD_IMMUTABLE_B19_CONTEXT_AND_MATH')
    return True

def validate(catalog,*,root_lookup,source_bytes=None,require_runtime=True):
    arm=catalog['arm'];need(arm in CASES,'ABMD_ONLY_SEPARATELY_QUALIFIED_OWN_ARMS');case=CASES[arm]
    need(catalog['schema']==CATALOG_SCHEMA and catalog['financial_authority'] is catalog['input_adopted']
         is catalog['local_canonical_runtime_executed'] is False,'ABMD_CATALOG_NO_FINANCIAL_AUTHORITY')
    root=root_lookup(arm,case['root'])
    need(catalog['parent_root_admission_sha256']==root['root_admission_sha256']==case['root']
         and catalog['parent_outer_sha256']==root['outer_sha256']==case['outer']
         and catalog['parent_inner_sha256']==root['inner_sha256']
         and catalog['parent_descriptors']==root['repairs'] and len(root['repairs'])==case['inputs']
         and catalog['parent_completed']==root['measured_closes']==1238
         and catalog['parent_cursor']==root['selected_session']=='2022-11-30',
         'ABMD_EXACT_FULL_CURRENT_OWN_PARENT')
    source=catalog['source_data'];payload,review,q=(source[n] for n in ('payload','review','qualification'))
    need(all(sha(encoded(source[n]))==source[n+'_sha256']==case[n] for n in ('payload','review','qualification')),
         'ABMD_ENTIRE_ORIGINAL_SOURCE_GENERATION_BYTES')
    need(payload['schema']==case['source_schema'] and review['schema']=='research.independent-frozen-source-data-review/1'
         and q['schema']=='research.independent-frozen-source-data-validation/1' and review['passed'] is q['passed'] is True
         and review['payload_sha256']==q.get('payload_sha256',case['payload'])==case['payload']
         and q['review_sha256']==case['review']
         and len(payload['terms'])==case['terms']
         and payload['arm']==review['arm']==q['arm']==arm
         and payload['parent_outer_sha256']==review['parent_outer_sha256']==case['outer']
         and review['parent_root_admission_sha256']==case['root'] and payload['parent_cursor']=='2022-11-30'
         and payload['scope_sha256']==review['scope_sha256']==digest(payload['scope']),
         'ABMD_ORIGINAL_SCHEMA_COMPLETE_MEMBERS_AND_OWN_SCOPE')
    need(all(v[k] is False for v in (review,q) for k in ('financial_authority','input_adopted','local_canonical_runtime_executed',
             'source_value_or_settlement_timing_qualified'))
         and review['source_identity_qualified_for_separate_future_input_review'] is q['source_identity_qualified_for_separate_future_input_review'] is True
         and type(review['financial_sessions_advanced']) is int and review['financial_sessions_advanced']==0
         and type(q['financial_workers_launched']) is int and q['financial_workers_launched']==0,
         'ABMD_CLOSED_SOURCE_IDENTITY_ONLY')
    captured=[t for t in payload['terms'] if t['native_term']['security_id']==SID]
    checked=[t for t in review['terms'] if t['native_term']['security_id']==SID]
    need(len(captured)==len(checked)==1,'ABMD_ONE_COMPLETE_NATIVE_SOURCE_MEMBER');actual,=captured;checked,=checked
    need(set(checked)<={'identity_witness','native_term','parent_positions','source_row'}
         and all(checked[k]==actual[k] for k in checked) and actual['parent_positions']==[]
         and review['parent_pending_context'][SID]==[] and actual['native_term']==catalog['native']
         and actual['identity_witness']==catalog['identity_witness'] and actual['identity_witness']['session']=='2022-12-20'
         and actual['native_term']['session']=='2022-12-21' and actual['native_term']['cash_per_share'] is None
         and actual['native_term']['kind']=='CASH_MERGER', 'ABMD_ACTUAL_UNOWNED_NATIVE_AND_ORIGINAL_IDENTITY')
    e=Event.model_validate(catalog['event']).model_dump();need(e==event(catalog['native']),'ABMD_EXACT_LEGAL_EVENT_AND_RECALENDARING')
    primary=catalog['primary_facts'];preparation=catalog['raw_quote_preparation'];market=catalog['market_source']
    need(sha(encoded(primary))==catalog['primary_facts_sha256']==PRIMARY_SHA
         and sha(encoded(preparation))==catalog['raw_quote_preparation_sha256']==PREPARATION_SHA,
         'ABMD_EXACT_PRIMARY_AND_FULL_SCAN_PREPARATION_BYTES')
    need(primary['ticker']=='ABMD' and primary['event_date']=='2022-12-22' and primary['preopen_completion_confirmed'] is True
         and primary['last_trading_session']=='2022-12-21' and primary['upfront_cash_per_share']=='380.00'
         and primary['rights_per_share']=='1' and primary['right_transferable'] is False
         and (primary['right_lower_per_share'],primary['right_upper_per_share'])==('0','35.00')
         and primary['settlement_authorized'] is primary['probability_selected'] is primary['portfolio_completion_authorized']
             is primary['financial_input_selected'] is False,'ABMD_SEPARATE_MANDATORY_LEGAL_ENDPOINTS_ONLY')
    rows={r['session']:r for r in preparation['rows']};prior=rows['2022-12-21'];identity_row=rows['2022-12-20']
    need(preparation['full_annual_rows_scanned']==2080223 and preparation['actual_sid_rows']==245
         and preparation['actual_native_quote_present'] is True and preparation['actual_completion_quote_present'] is False
         and preparation['last_actual_source_session']=='2022-12-21'
         and preparation['financial_authority'] is preparation['local_canonical_runtime_executed'] is False
         and preparation['primary_facts_sha256']==PRIMARY_SHA
         and preparation['row_commitments']==[dict(session=r['session'],sha256=digest(r)) for r in preparation['rows']]
         and digest(identity_row)==actual['identity_witness']['source_observation_sha256'],
         'ABMD_FULL_ANNUAL_ABSENCE_AND_PRIOR_IDENTITY_PROOF')
    expected=dict(schema='research.abmd-absent-completion-quote-source/1',session='2022-12-22',security_id=SID,
        source_quote_present=False,source_observation_sha256=None,raw_event_row=None,raw_prior_row=prior,raw_identity_row=identity_row,
        split_ratio='1',split_rule='CANONICAL_NO_EVENT_BAR_UNIT_SPLIT',event_contract_sha256=digest(e),
        archive_sha256=preparation['archive_sha256'],annual_member_sha256=preparation['annual_member_sha256'],
        full_annual_rows_scanned=2080223,actual_sid_rows=245,last_actual_source_session='2022-12-21',
        raw_quote_preparation_sha256=PREPARATION_SHA,financial_authority=False,right_price_selected=False,portfolio_cash_settlement_authorized=False)
    need(market==expected and sha(encoded(market))==catalog['market_source_sha256'],'ABMD_EXACT_ABSENT_EVENT_QUOTE_AND_ACTUAL_PRIOR_ANCHOR')
    if arm=='P07':
        extra=[t for t in payload['additional_rows'] if t['source_row']['security_id']==SID]
        need(len(extra)==1 and extra[0]['source_row']==prior and extra[0]['parent_positions']==[],
             'ABMD_P07_COMPLETE_CAPTURED_NATIVE_DAY_ROW')
    else:need(payload.get('additional_rows',[])==[],'ABMD_P06_NO_ADDITIONAL_CAPTURE_CLAIM')
    verify_semantics(catalog,source_bytes=source_bytes,require_runtime=require_runtime)
    return deepcopy(catalog)

def evidence(catalog):
    values=[('catalog',sha(encoded(catalog))),('source-payload',catalog['source_data']['payload_sha256']),
        ('source-review',catalog['source_data']['review_sha256']),('source-qualification',catalog['source_data']['qualification_sha256']),
        ('primary-facts',catalog['primary_facts_sha256']),('full-annual-absence-preparation',catalog['raw_quote_preparation_sha256']),
        ('event-market-source',catalog['market_source_sha256']),('event-contract',digest(catalog['event']))]
    return [dict(reference='research.abmd-bounded-sensor/'+name,sha256=pin,
        description='Exact own source identity, legal endpoint or absent-quote event evidence; no cash settlement authority.') for name,pin in values]

def document(catalog,*,predecessor_checkpoint_sha256=None):
    # Callers qualify the actual full parent/neutral lineage before supplying a different predecessor.
    predecessor=catalog['parent_inner_sha256'] if predecessor_checkpoint_sha256 is None else predecessor_checkpoint_sha256
    need(type(predecessor) is str and len(predecessor)==64 and all(c in '0123456789abcdef' for c in predecessor),
         'ABMD_EXACT_ACTUAL_PREDECESSOR_DIGEST')
    return dict(schema=SCHEMA,predecessor_checkpoint_sha256=predecessor,event=deepcopy(catalog['event']),source_evidence=evidence(catalog))

def load(path):
    from system_campaign_financial_partial import root_spec
    raw=Path(path).read_bytes();need(len(raw)<=2*1024**2,'ABMD_BOUNDED_CATALOG_SIZE')
    return validate(json.loads(raw),root_lookup=root_spec)
