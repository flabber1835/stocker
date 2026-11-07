"""One original observer; complete cash and source call sets reviewed separately."""
import json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p06_abmd_models as oldmodels
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models

DIRECTORY='p06-BBIG-combined-original-observation'
def cash_terms(root,current):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    root=Path(root);parent=journal.read_checkpoint(root/oldmodels.DIRECTORY/oldmodels.PARENT)
    data.need(parent['completed']==1238 and parent['sha256']==initial.catalog()['parent_outer_sha256']
        and current['repairs'][:8]==parent['repairs'],'P06_BBIG_ORIGINAL8_ONLY_OBSERVATION_METADATA')
    _,material=oldmodels.ordinary_material(root,parent,current['repairs'][8],lambda n:(root/n).read_bytes())
    terms=material['terms']+initial.forward_terms(initial.plan())
    data.need(len(terms)==2 and {t['ticker'] for t in terms}=={'TRQ','MYOV'}
        and next(t for t in terms if t['ticker']=='TRQ')['added']['cash_per_share']==31.575855485386988,
        'P06_BBIG_ALL_UNCHANGED_ORIGINAL_TRQ_MYOV_CASH_RECORDS')
    return terms
def merge_cash(event,terms):
    original_scopes=deepcopy(event.scopes)
    data.need(len(original_scopes)==1 and original_scopes[0]['security_id']==data.SID
        and original_scopes[0]['require_never_held'] is True,'P06_BBIG_ONLY_GENUINE_NEW_SOURCE_SCOPE')
    for term in terms:
        a=term['added'];key=a['session'],a['security_id']
        data.need(a['kind']=='CASH_MERGER' and not term.get('require_unowned_and_unordered',False)
            and term['ticker'] in ('TRQ','MYOV') and (key not in event.terms or event.terms[key]==a),
            'P06_BBIG_NO_SOURCE_UPGRADE_OR_CONFLICT_WHEN_RETAINING_OLD_CASH')
        event.terms[key]=deepcopy(a)
    data.need(event.scopes==original_scopes,'P06_BBIG_CASH_MERGE_PRESERVES_ONLY_ACTUAL_BBIG_SCOPE')
    return event
def observer(root,out,current,parent,spec,api):
    from full_system_core import hosted
    hosted()
    from system_campaign_bounded_sensor_origin_v2 import exact
    data.parent_contract(parent,spec);root,out=Path(root),Path(out);folder=out/DIRECTORY
    for name in (models.OVERLAY,original.hydration_name(parent),original.SOURCE_SCOPES):exact(folder/name,(out/name).read_bytes())
    fn=original.ActualEvents.__init__
    data.need(data.sha(Path(original.__file__).read_bytes())==data.FUTURE_SHA and fn.__closure__ is None,
        'P06_BBIG_WHOLE_ORIGINAL_OBSERVER_SOURCE_AND_INITIALIZER')
    initializer=FunctionType(fn.__code__,dict(fn.__globals__,OVERLAY=models.OVERLAY,source_scopes=api.source_scopes),fn.__name__,fn.__defaults__)
    initializer.__kwdefaults__=deepcopy(fn.__kwdefaults__)
    event=original.ActualEvents.__new__(original.ActualEvents);initializer(event,folder,'P06',cp=parent)
    merge_cash(event,cash_terms(root,current))
    data.need(event.advance.__func__ is original.ActualEvents.advance and event.terminal.__func__ is original.ActualEvents.terminal
        and event.source_values.__func__ is original.ActualEvents.source_values and initializer.__code__ is fn.__code__,
        'P06_BBIG_ONE_ENTIRE_ORIGINAL_ADAPTER_KERNEL_CALLER_FRAME_SET')
    exact(folder/'observer-origin.json',data.encoded(dict(schema='research.P06-original-combined-BBIG-source-cash-observer/1',
        original_financial_parent10=parent['sha256'],actual_neutral11=current['sha256'],old_cash_terms=['TRQ','MYOV'],
        original_TRQ_cash_per_share='31.575855485386988',one_actual_BBIG_scope=event.scopes[0],
        original_methods_unchanged=True,old_cash_scopes_upgraded=False,financial_checkpoint_adopted=False)))
    return event
def source_record(record,term,scope,before,opened,events,*,source_was_selected):
    a=term['added'];day=a['session'];sid=a['security_id']
    data.need(record['session']==day and record['passed'] is True and record['financial_source_changed'] is False
        and record['stock']==record['risk']==[] and record['engine_calls']==0
        and record['order']==['CASH:'+sid] and len(record['cash'])==len(record['source'])==1,
        'P06_BBIG_EXACT_ENTIRE_SOURCE_DAY_CALL_SET')
    c,=record['cash'];s,=record['source']
    data.need(c==dict(session=day,security_id=sid,actual_context_call=True,
        postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.),source_only_noop=True)
        and s['security_id']==sid and s['actual_context_call'] is s['original_function_delegated'] is True
        and s['portfolio_completion_authorized'] is False and s['scope_sha256']==data.digest(scope)
        and type(source_was_selected) is bool and type(s['source_value_returned']) is bool
        and (source_was_selected is False or s['source_value_returned'] is True),
        'P06_BBIG_ACTUAL_ZERO_VALUE_NOOP_AND_UNCHANGED_SOURCE_DELEGATION')
    for state in (before,opened):original.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],scope)
    data.need(not original.mentions_source(events,(sid,term['ticker'])),'P06_BBIG_NO_ACTUAL_HISTORICAL_PORTFOLIO_OR_CASH_EVENT')
    result=SimpleNamespace(state=SimpleNamespace(wealth_core=opened['wealth_core'],pending=opened['pending'],ledger=opened['ledger']))
    original.actual_source_phase(record,result,[scope])
    return dict(ticker='BBIG',session=day,actual_noop=True,original_kernel_source_delegated=True,
        portfolio_completion_authorized=False,actual_settlement_claimed=False)
def review(parent,current,evidence,out):
    from full_system_core import hosted
    hosted()
    from system_campaign_uncertainty_review import committed_rows
    from system_campaign_retained_forward_cash import verify_records
    from system_campaign_bounded_sensor_origin_v2 import exact
    evidence,out=Path(evidence),Path(out);folder=evidence/DIRECTORY
    origin=json.loads((folder/'observer-origin.json').read_bytes());scope=origin['one_actual_BBIG_scope']
    terms=cash_terms(evidence,current);bbig=data.catalog()['terms'][-1]
    data.need(origin['original_financial_parent10']==parent['sha256'] and origin['old_cash_terms']==['TRQ','MYOV']
        and scope in json.loads((folder/original.SOURCE_SCOPES).read_bytes()),'P06_BBIG_REVIEW_EXACT_ORIGINAL_OBSERVER_ORIGIN')
    observed={p.stem.removeprefix('actual-future-event-'):json.loads(p.read_bytes()) for p in folder.glob('actual-future-event-20*.json')
        if parent['source_cursor']<p.stem.removeprefix('actual-future-event-')<=current['source_cursor']}
    active=[t for t in terms if parent['source_cursor']<t['added']['session']<=current['source_cursor']]
    cashdays={t['added']['session'] for t in active};sourcedays={bbig['added']['session']} if bbig['added']['session']<=current['source_cursor'] else set()
    data.need(not cashdays&sourcedays and set(observed)==cashdays|sourcedays,
        'P06_BBIG_COMPLETE_COMBINED_CASH_AND_SOURCE_OBSERVATION_AXIS')
    rows=committed_rows(evidence/'book',current,'daily');events=current['run']['state']['ledger']['events']
    cash=verify_records(rows,events,{day:observed[day] for day in cashdays},active,current['source_cursor']);source=[]
    for day in sourcedays:
        i,=[i for i,v in enumerate(rows) if v['session']==day];data.need(i>0,'P06_BBIG_ADJACENT_ACTUAL_SOURCE_ACCOUNTING')
        certificate,=[json.loads(v) for v in (evidence/'uncertainty-certificate.jsonl').read_bytes().splitlines() if json.loads(v)['session']==day]
        selected=data.SID in [item['security_id'] for item in certificate['material']['rows']]
        source.append(source_record(observed[day],bbig,scope,rows[i-1]['evidence']['research_entry_audit']['closing_accounting'],
            rows[i]['evidence']['research_entry_audit']['opening_accounting'],events,source_was_selected=selected))
    result=dict(passed=True,cash_events=cash,source_events=source,all_committed_dates_and_calls_accounted=True,
        original_TRQ_MYOV_preserved=True,original_observer_methods_unchanged=True,financial_sessions_reexecuted=0)
    exact(out/'p06-BBIG-combined-observation-review.json',data.encoded(result));return result
def source_names():return (Path(__file__).name,*models.source_names())
