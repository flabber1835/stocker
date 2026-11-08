"""Exact compact accounting DTO ledger-prefix binding; no checkpoint projection."""
import ast,json
from copy import deepcopy
from datetime import date
from pathlib import Path
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_observer as original

HERE=Path(__file__).parent
FACT='P06-FIN339-readonly-recovery-fact.json'
FACT_SHA='675f05967aaadd64604ddf5a11a565c8ff5769972ff19d804b45cfb2ba73c5a3'
OBSERVER_SHA='7e4e105d8061f629a634fbe902567d68dc9c5365f58abd9ff3cb6a3531b9ec08'
def fact():
    raw=(HERE/FACT).read_bytes();data.need(data.sha(raw)==FACT_SHA,'P06_REVIEW339_EXACT_CAPTURED_ACCOUNTING_AND_RECOVERY_FACT')
    value=json.loads(raw)
    data.need(value['original_root_admission_sha256']==data.ROOT and value['original_root_completed']==1383
        and value['original_root_inputs']==10 and (value['expected_new_rows'],value['expected_retained_rows'],value['actual_committed_proof_rows'])==(43,130,173)
        and value['actual_full_committed_events_count']==1251
        and value['scope']==dict(readonly_repair_only=True,financial_resume_authorized=False,input_adopted=False,
            financial_root_admitted=False,diagnostic_state_adopted=False,failed_receipt_relabelled=False,financial_transitions_reexecuted=0),
        'P06_REVIEW339_ONLY_ACTUAL1426_COMMITTED_DATA_NO_FINANCIAL_AUTHORITY')
    return value
def expand_accounting(snapshot,events):
    """Clone a published accounting DTO with its authentic committed event prefix."""
    value=fact();key=(snapshot.get('session'),snapshot.get('phase'))
    matches=[v for v in value['BBIG_compact_accounting'] if (v['session'],v['phase'])==key]
    data.need(len(matches)==1 and data.digest(snapshot)==matches[0]['sha256']
        and snapshot['schema']=='research.capital-risk-core-accounting/1'
        and set(snapshot['ledger'])=={'event_count','receivables'},
        'P06_REVIEW339_ONLY_EXACT_AUTHENTIC_COMPACT_ACCOUNTING_DTO')
    count=snapshot['ledger']['event_count'];day=snapshot['session']
    data.need(type(events)is list and len(events)==value['actual_full_committed_events_count']
        and data.digest(events)==value['actual_full_committed_events_sha256'],
        'P06_REVIEW339_FULL_ACTUAL_COMMITTED_LEDGER_EVENT_SOURCE')
    data.need(type(count)is int and 0<=count<=len(events) and count==matches[0]['event_count']
        and all(type(e['session'])is str and date.fromisoformat(e['session']).isoformat()==e['session'] for e in events)
        and [e['session'] for e in events]==sorted(e['session'] for e in events)
        and all(e['session']<=day for e in events[:count]) and all(e['session']>=day for e in events[count:])
        and (snapshot['phase']!='CLOSE_AFTER_DECISION' or all(e['session']>day for e in events[count:])),
        'P06_REVIEW339_EXACT_COUNT_BOUNDS_AND_ACCOUNTING_EVENT_CHRONOLOGY')
    result=deepcopy(snapshot);result['ledger']['events']=deepcopy(events[:count])
    data.need(snapshot['ledger']=={k:v for k,v in result['ledger'].items() if k!='events'}
        and len(result['ledger']['events'])==count,'P06_REVIEW339_CLONED_DTO_ONLY_ORIGINAL_SNAPSHOT_UNCHANGED')
    return result
def review_tree(raw):
    data.need(data.sha(raw)==OBSERVER_SHA,'P06_REVIEW339_WHOLE_FROZEN_OBSERVER_REVIEW_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review']
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='source_record']
    expected=["rows[i - 1]['evidence']['research_entry_audit']['closing_accounting']","rows[i]['evidence']['research_entry_audit']['opening_accounting']"]
    data.need(len(call.args)==6 and [ast.unparse(n) for n in call.args[3:5]]==expected
        and ast.unparse(call.args[5])=='events','P06_REVIEW339_EXACT_TWO_COMPACT_ACCOUNTING_ARGUMENT_SITES')
    for i in (3,4):call.args[i]=ast.Call(func=ast.Name(id='expand_accounting',ctx=ast.Load()),args=[call.args[i],ast.Name(id='events',ctx=ast.Load())],keywords=[])
    return ast.fix_missing_locations(fn)
def review_function():
    scope=dict(vars(original),expand_accounting=expand_accounting)
    exec(compile(ast.Module(body=[review_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-source-review-two-authentic-accounting-prefix-bindings>','exec'),scope)
    data.need(scope['source_record'] is original.source_record,'P06_REVIEW339_COMPLETE_ORIGINAL_SOURCE_NOOP_SCOPE_AND_DELEGATION_REVIEWER')
    return scope['review']
def source_names():return (Path(__file__).name,FACT)
