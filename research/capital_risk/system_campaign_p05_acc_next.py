"""One exact owned-common ACC fact through the unchanged CashCalendar NEXT rule."""
import ast,json
from copy import deepcopy
from pathlib import Path
from system_campaign_facts import sha,digest
from full_system_benchmark import need

HERE=Path(__file__).parent
FACT='P05-ACC-next-cash-fact-v2.json'
FACT_SHA='12d487ea778d920c129f911977dfd9d0209cbabfbd093da87cef766b821ab6ea'
RAW='ACC-native-last-trade-raw-DATA.json'
RAW_SHA='9176ce10e23ba17688e5f1af5210dbde26f5d7f2cc55c83c3e3e4dcb273d1360'
CALENDAR_SHA='183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f'
BATCH_SHA='29da1d97e921ca8886d18365b16c944461090302df8da63f4f4d7cfeee1e972f'
NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY'
SID='209530306982231273'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def source_names():return (Path(__file__).name,FACT,RAW,'system_campaign_cash_calendar.py','system_campaign_cash_batch.py')

def fact():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'ACC_NEXT_EXACT_SEPARATE_LEGAL_AND_CALENDAR_FACT')
    value=json.loads(raw);raw=(HERE/RAW).read_bytes()
    need(sha(raw)==RAW_SHA==value['raw_DATA_sha256'],'ACC_NEXT_EXACT_INDEPENDENT_RAW_LAST_QUOTE_PREPARATION')
    proof=json.loads(raw)
    need(proof['total_2022_rows']==2080223 and proof['ACC_rows']==151 and proof['post_native_2022_rows']==0
         and proof['last_source_session']=='2022-08-09' and proof['next_frozen_session']=='2022-08-10'
         and proof['selected_rows'][0]==value['source_term']['source_row']
         and proof['selected_rows'][1]==value['independent_native_quote'],
         'ACC_NEXT_COMPLETE_ACTUAL_NATIVE_LAST_TRADE_AND_SOURCE_CAPTURE_DISTINCTION')
    return value

def term():return deepcopy(fact()['term'])

def qualified_term():return deepcopy(fact()['qualified_term'])

def validate_acc(t,*,source,source_qualification,parent):
    f=fact()
    need(sha(encoded(source))==f['source_payload_sha256'],'ACC_NEXT_FULL_EXACT_FRESH_SOURCE322_PAYLOAD')
    need(sha(encoded(source_qualification))==f['source_qualification_sha256'],
         'ACC_NEXT_FULL_EXACT_FRESH_SOURCE322_DATA_QUALIFICATION_V2')
    need(encoded(t) in (encoded(f['term']),encoded(f['qualified_term'])),
         'ACC_NEXT_ONLY_EXACT_SEPARATELY_QUALIFIED_TERM')
    need(parent['sha256']==f['parent_outer_sha256']==digest({k:v for k,v in parent.items() if k!='sha256'})
         and (parent['completed'],parent['source_cursor'])==(1152,'2022-07-29')
         and parent['repairs']==f['parent_descriptors'] and len(parent['repairs'])==16
         and parent['run']['checkpoint_sha256']==f['parent_inner_sha256']
         and parent['run']['state_sha256']==f['parent_state_sha256']==digest(parent['run']['state'])
         and parent['run']['input_sha256']==f['parent_input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs'])),
         'ACC_NEXT_ACTUAL_ORIGINAL_CURRENT_FULL16_PARENT_COMMITMENTS')
    q=source_qualification
    need(q['passed'] is q['source_identity_qualified_for_separate_future_input_review'] is True
         and q['source_value_or_settlement_timing_qualified'] is False
         and q['financial_authority'] is q['input_adopted'] is q['local_canonical_runtime_executed'] is False
         and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0
         and q['root_admission_sha256']==f['root_admission_sha256']
         and q['payload_sha256']==f['source_payload_sha256'] and q['review_sha256']==f['source_review_sha256'],
         'ACC_NEXT_ORIGINAL_SOURCE_ONLY_QUALIFICATION_NOT_UPGRADED')
    need(source['schema']=='research.own-parent-frozen-source-witnesses/1' and source['arm']=='P05'
         and source['parent_outer_sha256']==parent['sha256'] and source['parent_cursor']==parent['source_cursor']
         and source['scope_sha256']==f['source_scope_sha256'] and len(source['terms'])==102
         and type(source['financial_sessions_advanced']) is int and source['financial_sessions_advanced']==0
         and all(source[k] is False for k in ('financial_authority','input_adopted','provider_metadata_upgraded','production_contacted')),
         'ACC_NEXT_FRESH_FULL102_SOURCE_CLOCK_AND_AUTHORITY')
    captured,=[v for v in source['terms'] if v['native_term']['security_id']==SID]
    need(captured==f['source_term'] and captured['identity_witness']['session']=='2022-08-08'
         and captured['native_term']['session']=='2022-08-09' and captured['native_term']['cash_per_share'] is None
         and q['independent_raw_source_proof']['independently_read_native_quotes']['ACC']==f['independent_native_quote']
         and f['independent_native_quote']['session']=='2022-08-09'
         and f['independent_native_quote']['raw_close']=='65.420000000000002',
         'ACC_NEXT_CAPTURED_AUG8_IDENTITY_AND_INDEPENDENT_ACTUAL_AUG9_QUOTE')
    state=parent['run']['state'];wealth=state['wealth_core']
    positions=[dict(slot_id=e['slot_id'],ticker=e['ticker'],quantity=e['current_shares'],entry_date=e['entry_date'])
        for k,e in sorted(wealth['episodes'].items(),key=lambda kv:int(kv[0])) if e['security_id']==SID]
    need(positions==f['parent_ACC_positions']==captured['parent_positions']==
         [dict(slot_id=16,ticker='ACC',quantity=29,entry_date='2022-06-30')]
         and [p for p in state['pending'] if p['security_id']==SID]==f['parent_ACC_pending']==[]
         and wealth['slots']['16']['occupied_by']==SID and wealth['slots']['16']['reserved_for'] is None,
         'ACC_NEXT_EXACT_CURRENT_OWNED29_COMMON_ROLE_AND_NO_ORDER')
    import system_campaign_cash_calendar as calendar
    need(sha(Path(calendar.__file__).read_bytes())==CALENDAR_SHA and calendar.NEXT==NEXT,
         'ACC_NEXT_WHOLE_ORIGINAL_CALENDAR_IMPLEMENTATION')
    return calendar.validate_term(t)

def cash_tree(raw):
    """One additive NEXT dispatcher; undo restores the entire original constructor."""
    need(sha(raw)==BATCH_SHA,'ACC_NEXT_WHOLE_ORIGINAL_CASH_BATCH_IMPLEMENTATION')
    owner,=[n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='CashBatch']
    fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='__init__']
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='t' and ast.unparse(n.iter)=='terms']
    guard,=[n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
             and any(isinstance(v,ast.Constant) and v.value=='CASH_BATCH_EXACT_CONFIRMED_CASH_ONLY_SCOPE' for v in n.value.args)]
    branch=ast.parse("if t.get('recognition_rule') == ACC_NEXT:\n    validate_acc_bound(t)\nelse:\n    pass").body[0]
    branch.orelse=[guard];loop.body[loop.body.index(guard)]=branch
    return ast.fix_missing_locations(fn)
