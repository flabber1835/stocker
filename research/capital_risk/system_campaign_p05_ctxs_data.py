"""Exact actual own1175 source2 and retained CTXS closing-source fact; DATA only."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from system_campaign_facts import sha,digest
from full_system_benchmark import need
import system_campaign_financial_future as future
HERE=Path(__file__).parent
ROOT='baabf01e4e070faea5c03fb0055fa715ac075a0175d5bdcc24b356a922cb1026'
OUTER='9a7217195d3bb40e84ff158fbf7e2ceb3b4d122ed51bb951a51f7ea11b007318'
FACT='P05-CTX-source-only-fact-v1.json'
FACT_SHA='6bd4c8d5dc3e9f07f66713c8f044497a4b2e4fe52a093457619e89fcc4990b4b'
PINS={'P05-CTX-source-payload-v1.json':'e3b43db8d53d13d60e249131fe523d746a658ab3a995598216df96810ffdd38e',
    'P05-CTX-source-review-v1.json':'a62adf3765cec7ea1d4db0b515dfdcdd000c27d9000a852baca36de6e92d8644',
    'P05-CTX-source-qualification-v1.json':'4712fe21fdf966cd74f8ee37a328fcd3207e685659898aae1bfadae552f1eae9'}
FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
SID='554480052825212855'
FRESH=frozenset(('arm','parent_cursor','parent_outer_sha256','parent_root_admission_sha256','parent_positions','identity_witness','native','source_capture'))
CATALOG='P05-own1175-CTX-source-only-catalog.json'
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def source_names():return (Path(__file__).name,FACT,*PINS,'system_campaign_p05_ctxs_api.py')
def fact():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'P05_CTXS_EXACT_WHOLE_FACT_BYTES')
    value=json.loads(raw)
    need(value['passed'] is value['source_valuation_only'] is value['primary_fact_reused_without_policy_upgrade'] is True
        and value['financial_input_selected'] is value['financial_root_admitted'] is value['canonical_financial_source_changed']
            is value['portfolio_completion_authorized'] is value['preopen_completion_confirmed'] is value['local_canonical_runtime_executed'] is False
        and (value['root_admission_sha256'],value['parent_outer_sha256'],value['parent_completed'],value['parent_cursor'],value['full_parent_inputs'])
            ==(ROOT,OUTER,1175,'2022-08-31',19),'P05_CTXS_ONLY_CLOSED_SOURCE_FACT_NO_FINANCIAL_OR_HELD_UPGRADE')
    return value
def records():
    values=[]
    for name,pin in PINS.items():
        raw=(HERE/name).read_bytes();need(sha(raw)==pin,'P05_CTXS_EXACT_FULL_SOURCE331_BYTES:'+name);values.append(json.loads(raw))
    payload,review,q=values;f=fact()
    need(q['passed'] is q['source_identity_qualified_for_separate_future_input_review'] is True
        and q['source_value_or_settlement_timing_qualified'] is q['financial_authority'] is q['input_adopted'] is q['local_canonical_runtime_executed'] is False
        and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0
        and q['root_admission_sha256']==ROOT and q['payload_sha256']==f['source_payload_sha256']==sha(encoded(payload))
        and q['review_sha256']==f['source_review_sha256']==sha(encoded(review))
        and q['scope_sha256']==f['source_scope_sha256']==payload['scope_sha256']==digest(payload['scope']),
        'P05_CTXS_FULL_SOURCE331_DATA_QUALIFICATION_NO_AUTHORITY_UPGRADE')
    need(payload['schema']=='research.own-parent-frozen-source-witnesses/2' and payload['arm']=='P05'
        and payload['parent_outer_sha256']==OUTER and payload['parent_cursor']=='2022-08-31'
        and len(payload['terms'])==len(review['terms'])==36 and len(payload['additional_rows'])==len(review['additional_rows'])==1
        and review['terms']==payload['terms'] and review['additional_rows']==payload['additional_rows']
        and q['independent_raw_source_proof']['native_identities']==36 and q['independent_raw_source_proof']['full_observation_rows']==37,
        'P05_CTXS_GENUINE_COMPLETE_SOURCE2_36_NATIVE_PLUS_ONE_ADDITIONAL_AXIS')
    return payload,review,q
def original_term():
    need(sha(Path(future.__file__).read_bytes())==FUTURE_SHA,'P05_CTXS_WHOLE_ORIGINAL_FUTURE_INTERPRETATION')
    codec,name,terms=future.own_cash_selection('P04','2022-08-31');term,=terms;f=fact()
    need(name==future.OWN_CASH_CATALOG and codec.catalog_sha=='5a917388cfa61ed86d60792e263260fca876eaf3d8f3606ad95744d7a5ed7ed7'
        and term==f['original_term'] and digest(term)=='74a5fd451a07a84afa97251af048a427e7ca2c9aac11f9c057383719157e3515',
        'P05_CTXS_EXACT_REGISTERED_P04_ORIGINAL_SOURCE_ONLY_LEGAL_TERM')
    return term
def parent_contract(parent):
    from system_campaign_financial_partial import root_spec,validate_root_spec
    spec=root_spec('P05',ROOT);validate_root_spec(spec);f=fact();run=parent['run']
    need(parent['sha256']==OUTER==spec['outer_sha256']==digest({k:v for k,v in parent.items() if k!='sha256'})
        and (parent['completed'],parent['source_cursor'],len(parent['repairs']))==(1175,'2022-08-31',19)
        and parent['repairs']==f['parent_descriptors']==spec['repairs'] and parent['base']==spec['base']
        and digest(parent['base'])==f['parent_base_sha256'] and spec['selected_file']==f['parent_selected_file']
        and run['checkpoint_sha256']==f['parent_inner_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
        and run['state_sha256']==f['parent_state_sha256']==spec['state_sha256']==digest(run['state'])
        and run['input_sha256']==f['parent_input_sha256']==spec['input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs']))
        and run['state']['last_processed_session']==parent['source_cursor'],
        'P05_CTXS_ACTUAL_ADMITTED_OWN1175_FULL19_PARENT_WITH_ALL_COMMITMENTS')
    return spec
def validate_term(term):
    original=original_term();f=fact();payload,review,q=records()
    need(encoded(term)==encoded(f['term']) and set(term)==set(original)|FRESH|{'retained_original_source_only_term'}
        and all(term[k]==v for k,v in original.items() if k not in FRESH),
        'P05_CTXS_EVERY_ORIGINAL_LEGAL_CALENDAR_AND_SOURCE_ONLY_POLICY_FIELD_UNCHANGED')
    selected,=[v for v in payload['terms'] if v['native_term']['security_id']==SID]
    extra,=payload['additional_rows']
    need(selected==f['source_term'] and selected['parent_positions']==term['parent_positions']==[]
        and term['native']==selected['native_term'] and term['identity_witness']==selected['identity_witness']
        and term['native_term_sha256']==digest(term['native'])
        and extra==f['captured_additional_row'] and extra['source_row']['session']=='2022-09-29'
        and extra['identity_witness']['source_observation_sha256']=='eab8676d25273d7edd8394307dfc6f1db7d1015d48319a09bb3bff15efc0a67f',
        'P05_CTXS_EXACT_FRESH_NATIVE_PRIOR_WITNESS_AND_CAPTURED_LAST_TRADE_ROW')
    future.source_cash_term(term)
    future.completion_session(term,['2022-09-28','2022-09-29','2022-09-30','2022-10-03'])
    return term
def term():return deepcopy(validate_term(fact()['term']))
def catalog():
    payload,review,q=records();value=dict(schema='research.P05-own1175-CTX-source-only-catalog/1',arm='P05',root_admission_sha256=ROOT,
        parent_outer_sha256=OUTER,parent_cursor='2022-08-31',full_parent_inputs=19,terms=[term()],
        source_data=dict(payload=payload,review=review,qualification=q),canonical_financial_source_changed=False,
        portfolio_completion_authorized=False,historical_causality='UNVERIFIED')
    return value
def codec(parent):
    parent_contract(parent);value=catalog()
    return SimpleNamespace(catalog=value,catalog_sha=sha(encoded(value)),compiler_sha=sha(Path(__file__).read_bytes()),
        parent_outer_sha256=OUTER,parent_positions=[],validator_description='Exact retained104USD September30 closing source-only term with genuine SOURCE331 source2 identities; no held settlement or preopen authority.')
