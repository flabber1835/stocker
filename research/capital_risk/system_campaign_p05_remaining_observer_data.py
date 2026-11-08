"""Complete observation call sets; independent original cash/source/stock review."""
import ast,json
from copy import deepcopy
from pathlib import Path
import system_campaign_p05_remaining_origin_data as origin
import system_campaign_retained_forward_cash as cash
import system_campaign_bounded_sensor_observers_v2 as stock
from system_campaign_facts import digest

need,sha=origin.need,origin.sha
CASH_SHA='19e27991d4c63cfc94c7f6a91173d131aec2358645320b68bd83d1bd4a593fef'

def source_projection(rows,events,observed,terms,scopes,through):
    source=[t for t in terms if t.get('require_unowned_and_unordered')]
    need(len(source)==len(scopes)==1 and source[0]['security_id']==scopes[0]['security_id']==origin.data.own.SID
        and source[0]['added']['session']==scopes[0]['session']=='2022-09-30'
        and scopes[0]['portfolio_completion_authorized'] is False,'P05_OBSERVER18_ONLY_ONE_EXACT_CTXS_SOURCE_SCOPE')
    source_term=source[0];scope=scopes[0];sid=scope['security_id'];projected={};checked=[]
    expected={}
    for term in terms:
        if term['added']['session']<=through:expected.setdefault(term['added']['session'],[]).append(term)
    need(set(observed)==set(expected),'P05_OBSERVER18_ENTIRE_REAL_COMMITTED_EVENT_AXIS')
    for day,group in expected.items():
        record=observed[day]
        cash_ids={t['security_id'] for t in group if t['added']['kind']=='CASH_MERGER'}
        mixed={t['security_id'] for t in group if t['added']['kind']=='CASH_PLUS_STOCK'}
        source_ids={t['security_id'] for t in group if t.get('require_unowned_and_unordered')}
        need(record['session']==day and record['passed'] is True and record['financial_source_changed'] is False
            and record['risk']==[] and type(record['engine_calls']) is int and record['engine_calls']==0
            and len(record['cash'])==len(cash_ids) and {v['security_id'] for v in record['cash']}==cash_ids
            and len(record['stock'])==len(mixed) and {v['security_id'] for v in record['stock']}==mixed
            and len(record['source'])==len(source_ids) and {v['security_id'] for v in record['source']}==source_ids
            and len(record['order'])==len(cash_ids) and set(record['order'])=={'CASH:'+i for i in cash_ids},
            'P05_OBSERVER18_WHOLE_DAILY_CALL_SET_BEFORE_SOURCE_PROJECTION')
        if not source_ids:projected[day]=deepcopy(record);continue
        need(day==scope['session'] and source_ids=={sid} and record['source_prior_absent'] is True,
            'P05_OBSERVER18_SOURCE_ONLY_EXACT_DATE_AND_ACTUAL_PRIOR_ABSENCE')
        noop,=[v for v in record['cash'] if v['security_id']==sid]
        need(noop==dict(session=day,security_id=sid,actual_context_call=True,
            postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.),source_only_noop=True)
            and noop['actual_context_call'] is noop['source_only_noop'] is True
            and noop['postcondition']['actual_held'] is False and type(noop['postcondition']['quantity']) is int,
            'P05_OBSERVER18_WHOLE_ORIGINAL_ACTUAL_SOURCE_ONLY_CASH_NOOP')
        delegated,=record['source']
        need(set(delegated)=={'security_id','actual_context_call','original_function_delegated','source_value_returned',
            'portfolio_completion_authorized','scope_sha256'} and delegated['security_id']==sid
            and delegated['actual_context_call'] is delegated['original_function_delegated'] is True
            and delegated['portfolio_completion_authorized'] is False and type(delegated['source_value_returned']) is bool
            and delegated['scope_sha256']==digest(scope),'P05_OBSERVER18_WHOLE_ORIGINAL_KERNEL_SOURCE_DELEGATION_NO_PORTFOLIO_AUTHORITY')
        indexes=[i for i,row in enumerate(rows) if row['session']==day]
        need(len(indexes)==1 and indexes[0]>0,'P05_OBSERVER18_REAL_ADJACENT_SOURCE_ACCOUNTING')
        i=indexes[0]
        before=rows[i-1]['evidence']['research_entry_audit']['closing_accounting']
        opened=rows[i]['evidence']['research_entry_audit']['opening_accounting']
        closed=rows[i]['evidence']['research_entry_audit']['closing_accounting']
        for snapshot in (before,opened,closed):
            origin.api_module.original.require_source_scope(snapshot['wealth_core'],snapshot['pending'],snapshot['ledger'],scope)
        if 'median5' in before:
            need(sid not in before['median5']['selected'] or delegated['source_value_returned'] is True,
                'P05_OBSERVER18_ACTUAL_SELECTED_SOURCE_RETURN_MUST_BE_SUPPLIED')
        need(not any(v['security_id']==sid and v['session']==day for v in events),'P05_OBSERVER18_SOURCE_ONLY_NO_FINANCIAL_LEDGER_EVENT')
        copy=deepcopy(record);copy['source']=[];copy['cash']=[v for v in copy['cash'] if v['security_id']!=sid]
        copy['order']=[v for v in copy['order'] if v!='CASH:'+sid]
        if any(t['security_id']!=sid for t in group):projected[day]=copy
        checked.append(dict(ticker=source_term['ticker'],session=day,actual_unowned_unordered_no_claims=True,
            original_adapter_noop_and_kernel_delegation=True,portfolio_completion_authorized=False))
    return [t for t in terms if t['security_id']!=sid],projected,checked

def review_data(current,rows,observed,terms,scopes):
    need(current['base']['sources'][stock.TERMINAL_SOURCE]==stock.TERMINAL_SHA,'P05_OBSERVER18_ORIGINAL_FROZEN_TERMINAL_SOURCE')
    through=current['source_cursor'];events=current['run']['state']['ledger']['events']
    ordinary,projected,source=source_projection(rows,events,observed,terms,scopes,through)
    cash_records,others=stock.grouped_records(ordinary,projected,through)
    ordinary_cash=[t for t in ordinary if t['added']['kind']=='CASH_MERGER']
    cash_result=cash.verify_records(rows,events,cash_records,ordinary_cash,through)
    stock_result=[]
    for term,record in others:
        indexes=[i for i,row in enumerate(rows) if row['session']==term['added']['session']]
        need(len(indexes)==1 and indexes[0]>0,'P05_OBSERVER18_REAL_ADJACENT_STOCK_ACCOUNTING')
        i=indexes[0]
        stock_result.append(stock.stock_event(term,rows[i-1]['evidence']['research_entry_audit']['closing_accounting'],
            rows[i]['evidence']['research_entry_audit']['opening_accounting'],events,record))
    return dict(passed=True,observation_terms=len(terms),ordinary_cash_terms=len(ordinary_cash),source_only_terms=1,
        original_cash_events=cash_result,original_stock_events=stock_result,source_only_events=source,
        original_observer_methods_unchanged=True,financial_sessions_reexecuted=0)

def merge_tree(raw):
    need(sha(raw)==CASH_SHA,'P05_OBSERVER18_ENTIRE_ORIGINAL_CASH_OBSERVER_SOURCE')
    fn,=[deepcopy(n) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='merge_terms']
    candidates=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
        and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='RETAINED_CASH_NO_SOURCE_ONLY_AUTHORITY_UPGRADE']
    need(len(candidates)==1 and ast.unparse(candidates[0].args[0])=='event.scopes == []','P05_OBSERVER18_ONE_EXACT_ORIGINAL_EMPTY_SCOPE_PREDICATE')
    predicate=deepcopy(candidates[0].args[0]);candidates[0].args[0]=ast.parse('allowed_scopes(event)',mode='eval').body
    undo=deepcopy(fn)
    c,=[n for n in ast.walk(undo) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
        and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='RETAINED_CASH_NO_SOURCE_ONLY_AUTHORITY_UPGRADE']
    c.args[0]=predicate
    old,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='merge_terms']
    need(ast.dump(undo,include_attributes=False)==ast.dump(old,include_attributes=False),'P05_OBSERVER18_WHOLE_CASH_MERGE_AST_EXACT_PREDICATE_UNDO')
    return ast.fix_missing_locations(fn)

def merge_function(allowed_scopes):
    raw=Path(cash.__file__).read_bytes();namespace=dict(vars(cash),allowed_scopes=allowed_scopes)
    exec(compile(ast.Module(body=[merge_tree(raw)],type_ignores=[]),'<whole-original-cash-merge-one-exact-scope-predicate>','exec'),namespace)
    return namespace['merge_terms']

def exact_scope(event,expected):
    need(len(expected)==1 and expected[0]['security_id']==origin.data.own.SID
        and expected[0]['portfolio_completion_authorized'] is False and expected[0]['source_valuation_phase']=='CLOSE'
        and origin.encoded(event.scopes)==origin.encoded(expected)
        and digest(event.terms.get((expected[0]['session'],expected[0]['security_id'])))==expected[0]['terminal_sha256'],
        'P05_OBSERVER18_ONLY_COMPLETE_VALIDATED_CTXS_SCOPE_AND_EXACT_TERMINAL')
    return True
