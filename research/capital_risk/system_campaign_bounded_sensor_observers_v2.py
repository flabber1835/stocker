"""One original observer over all authenticated inherited and later ordinary terms."""
from copy import deepcopy
from fractions import Fraction
import gzip,json
from pathlib import Path,PurePosixPath
from system_campaign_bounded_sensor_input import need,sha
from system_campaign_bounded_sensor_catalog import encoded
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_bounded_sensor_observer_data as data

DIRECTORY='bounded-contingent-observer'
CONTRACT='original-observation-contract.json'
REFERENCE='research:system-optimization-002/selected-future-ordinary-input/1/hydrated'
TERMINAL_SOURCE='shared/stock_strategy_shared/wealth_core/terminal.py'
TERMINAL_SHA='d145eb0787c58e092618d1b05f5f2d988449351ac146a050debd9e0cec1c44e6'

def merge(*groups):
    terms={}
    for group in groups:
        for t in group:
            a=t['added'];key=a['session'],t['security_id']
            need(a['kind'] in ('CASH_MERGER','CASH_PLUS_STOCK','CONVERSION') and not t.get('require_unowned_and_unordered',False)
                 and not any(marker in t.get('recognition_rule','') for marker in ('SOURCE_ONLY','UNHELD','SOURCE_EXIT'))
                 and (key not in terms or terms[key]==t),'BOUNDED_OBSERVER_NO_SOURCE_ONLY_UPGRADE_OR_CONFLICT')
            terms[key]=deepcopy(t)
    return list(terms.values())

def tail_materials(root,cp):
    root=Path(root);terms=[];resources={}
    candidates=[*root.glob('hydrated-future-financial-terminal-catalog-*.json'),
                *(root/DIRECTORY/'materials').glob('*/hydrated-future-financial-terminal-catalog-*.json')]
    for descriptor in cp['repairs'][16:]:
        need(descriptor['filename']==descriptor['sha256']+'.json' and Path(descriptor['filename']).name==descriptor['filename']
             and len(descriptor['sha256'])==64 and all(c in '0123456789abcdef' for c in descriptor['sha256']),
             'BOUNDED_OBSERVER_SAFE_COMMITTED_TAIL_FILENAME_BEFORE_READ')
        raw=(root/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'BOUNDED_OBSERVER_ALL_CURRENT_TAIL_DESCRIPTOR_BYTES')
        doc=json.loads(raw);pins=[x['sha256'] for x in doc['source_evidence'] if x['reference']==REFERENCE]
        need(doc['schema']=='terminal-repair/1' and len(pins)==1,'BOUNDED_OBSERVER_ONE_COMMITTED_TAIL_MATERIAL_PIN')
        found=[(p,p.read_bytes()) for p in candidates if sha(p.read_bytes())==pins[0]]
        need(found and all(raw==found[0][1] for p,raw in found),'BOUNDED_OBSERVER_AUTHENTIC_ALL_TAIL_MATERIALS')
        path,material_raw=found[0];material=json.loads(material_raw)
        need(all(p.name=='hydrated-future-financial-terminal-catalog-'+material['parent_outer_sha256']+'.json' for p,raw in found)
             and material['arm']=='P03' and material['financial_source_changed'] is material['provider_metadata_upgraded'] is False
             and doc['add']==[t['added'] for t in material['terms']], 'BOUNDED_OBSERVER_WHOLE_EXACT_TAIL_TERMS')
        terms=merge(terms,material['terms'])
        resources[DIRECTORY+'/materials/'+descriptor['sha256']+'/'+path.name]=material_raw
    return terms,resources

def stage_initial(root,parent,out):
    from full_system_core import hosted
    hosted()
    root,out=Path(root),Path(out);plan,expected=data.records()
    result=data.inventory(parent,plan,expected,lambda n:(root/n).read_bytes())
    resources=dict(result['resources']);resources['future-financial-overlay.json']=resources.pop('ordinary-overlay.json')
    for n,raw in resources.items():exact(out/DIRECTORY/n,raw)
    contract=dict(schema='research.bounded-inherited-observation-contract/1',terms=result['terms'],
        initial_parent_sha256=parent['sha256'],ordinary_metadata_parent_sha256=result['origin_metadata']['sha256'],
        ordinary_metadata_is_financial_seed=False,resources={n:sha(raw) for n,raw in resources.items()},
        forward_terms=17,observations=18,conversion_review_required=True,mixed_consideration_review_required=True)
    exact(out/DIRECTORY/CONTRACT,encoded(contract))
    for path in root.glob('actual-future-event-20*.json'):
        if path.stem.removeprefix('actual-future-event-')<=parent['source_cursor']:exact(out/DIRECTORY/path.name,path.read_bytes())
    return [DIRECTORY+'/'+n for n in resources]+[DIRECTORY+'/'+CONTRACT]

def stage_retained(root,current,out):
    from full_system_core import hosted
    hosted()
    root,out=Path(root),Path(out);contract=json.loads((root/DIRECTORY/CONTRACT).read_bytes())
    for n,pin in contract['resources'].items():
        raw=(root/DIRECTORY/n).read_bytes();need(sha(raw)==pin,'BOUNDED_OBSERVER_RETAINED_STATIC_RESOURCES');exact(out/DIRECTORY/n,raw)
    exact(out/DIRECTORY/CONTRACT,(root/DIRECTORY/CONTRACT).read_bytes())
    for path in (root/DIRECTORY).glob('actual-future-event-20*.json'):
        if path.stem.removeprefix('actual-future-event-')<=current['source_cursor']:exact(out/DIRECTORY/path.name,path.read_bytes())
    _,resources=tail_materials(root,current)
    for n,raw in resources.items():exact(out/n,raw)
    return contract

def observer(root,current):
    from full_system_core import hosted
    hosted()
    import system_campaign_financial_future as original
    import system_campaign_retained_forward_cash as retained
    root=Path(root);contract=json.loads((root/DIRECTORY/CONTRACT).read_bytes())
    for n,pin in contract['resources'].items():need(sha((root/DIRECTORY/n).read_bytes())==pin,'BOUNDED_OBSERVER_CONSTRUCTOR_SOURCE_BYTES')
    old=json.loads(gzip.decompress((root/DIRECTORY/'observer-origin.json.gz').read_bytes()))
    need(old['sha256']==contract['ordinary_metadata_parent_sha256'] and contract['ordinary_metadata_is_financial_seed'] is False,
         'BOUNDED_OBSERVER_METADATA_ORIGIN_NEVER_FINANCIAL_SEED')
    Original=retained.observer_class(retained.plans()[0]);event=Original(root/DIRECTORY,'P03',cp=old)
    tail,_=tail_materials(root,current);terms=merge(contract['terms'],tail)
    for t in terms:
        a=t['added'];key=a['session'],t['security_id']
        need(key not in event.terms or event.terms[key]==a,'BOUNDED_OBSERVER_NO_DUPLICATE_OR_REPLACED_TERMINAL')
        event.terms[key]=deepcopy(a)
    need(event.scopes==[] and event.advance.__func__ is Original.advance and event.terminal.__func__ is Original.terminal,
         'BOUNDED_OBSERVER_ONE_ORIGINAL_CALLER_FRAME_METHOD_SET')
    return event

def stock_event(term,before,opened,events,record):
    a=term['added'];sid=a['security_id'];day=a['session']
    held=sorted((e for e in before['wealth_core']['episodes'].values() if e['security_id']==sid),key=lambda e:e['slot_id'])
    actual=[e for e in events if e['security_id']==sid and e['session']==day and e['event_type']=='CONVERSION']
    need(len(actual)==len(held) and not any(e['security_id']==sid and e['session']==day and e['event_type']=='CASH_MERGER' for e in events),
         'BOUNDED_ORDINARY_ONE_CONVERSION_PER_SOURCE_LOT_NO_SECOND_CASH')
    quantities=[Fraction(str(e['current_shares'])) for e in held];total=sum(quantities,Fraction(0))
    ratio=Fraction(str(a['exchange_ratio']));entitlement=total*ratio;whole=entitlement//1;fraction=entitlement-whole
    settled=fraction
    if {'terminal_terms_schema','cash_in_lieu_fraction_rounding'} & a.keys():
        need(a.get('terminal_terms_schema')=='terminal-cil-rounding/1'
             and a.get('cash_in_lieu_fraction_rounding')=='NEAREST_HUNDREDTH_HALF_UP',
             'BOUNDED_ORDINARY_ONLY_EXPLICIT_ORIGINAL_CIL_ROUNDING_CONTRACT')
        units,remainder=divmod(fraction.numerator*100,fraction.denominator);settled=Fraction(units+(2*remainder>=fraction.denominator),100)
    cashleg=total*Fraction(str(a['cash_per_share'] or 0));lieu=settled*Fraction(str(a['cash_in_lieu_price_per_delivered_share'] or 0))
    delivered_so_far=cash_so_far=lieu_so_far=0.;cumulative=Fraction(0);basecash=actual[0]['cash_before'] if actual else 0.;running=basecash
    for i,(lot,event,quantity) in enumerate(zip(held,actual,quantities,strict=True)):
        weight=quantity/total;cumulative+=weight;last=i==len(held)-1
        delivered=float(whole)-delivered_so_far if last else float(whole*weight)
        cash=float(cashleg)-cash_so_far if last else float(cashleg*weight)
        cil=float(lieu)-lieu_so_far if last else float(lieu*weight);after=basecash+float((cashleg+lieu)*cumulative);d=event['detail']
        need(event['reason']==a['kind'] and event['price']==a['cash_per_share'] and event['fees']==0.
             and event['cash_before']==running and event['cash_after']==after and event['cash_delta']==after-running
             and event['shares_delta']==delivered-lot['current_shares'] and d['shares_in']==lot['current_shares']
             and d['shares_delivered']==delivered and d['delivered_security_id']==a['delivered_security_id']
             and d['delivered_ticker']==a['delivered_ticker'] and d['exchange_ratio_exact']==str(a['exchange_ratio'])
             and d['exact_fractional_entitlement']==str(fraction*weight) and d['cash_consideration']==round(cash,10)
             and d['cash_in_lieu']==round(cil,10) and d['reference']==a['reference'] and d['entitlement_aggregation']=='HOLDER',
             'BOUNDED_ORDINARY_EXACT_HOLDER_DELIVERY_AND_ORIGINAL_CASH_OPERATION_ORDER')
        successors=[e for e in opened['wealth_core']['episodes'].values() if e['slot_id']==lot['slot_id']]
        if delivered<=0:
            need(successors==[],'BOUNDED_ORDINARY_ZERO_DELIVERY_RELEASES_ORIGINAL_SLOT')
        else:
            need(len(successors)==1,'BOUNDED_ORDINARY_ONE_ORIGINAL_CONTINUATION_SLOT')
            successor=successors[0]
            prior_keys=('signal_date','entry_date','market_sessions_held','review_completed','exit_pending','exit_reason')
            provenance=dict(kind=a['kind'],session=day,from_security_id=sid,from_ticker=lot['ticker'],
                shares_in=lot['current_shares'],exchange_ratio=float(ratio),exchange_ratio_exact=str(a['exchange_ratio']),
                entitlement_aggregation='HOLDER',shares_delivered=delivered,cash_consideration=round(cash,10),
                cash_in_lieu=round(cil,10),to_security_id=a['delivered_security_id'],to_ticker=a['delivered_ticker'],reference=a['reference'])
            if 'reference_rebase' in d:provenance['reference_rebase']=deepcopy(d['reference_rebase'])
            need(successor['security_id']==a['delivered_security_id'] and successor['ticker']==a['delivered_ticker']
                 and successor['issuer_id']==a.get('delivered_issuer_id') and successor['current_shares']==delivered
                 and successor['initial_shares']==max(1,int(round(lot['initial_shares']*float(ratio))))
                 and all(successor[k]==lot[k] for k in prior_keys)
                 and successor['source_lots']==lot['source_lots']+[provenance],
                 'BOUNDED_ORDINARY_EXACT_POSITION_CONTINUATION_AND_SOURCE_PROVENANCE')
        delivered_so_far+=delivered;cash_so_far+=cash;lieu_so_far+=cil;running=after
    need(not any(e['security_id']==sid for e in opened['wealth_core']['episodes'].values())
         and not any(e['security_id']==sid for e in opened['pending'])
         and sid not in opened['wealth_core'].get('terminal_pending_terms',{})
         and sid not in opened['wealth_core'].get('terminal_pending_sessions',{}), 'BOUNDED_ORDINARY_SOURCE_COMPLETELY_CLEARED')
    need(record['session']==day and record['passed'] is True and record['financial_source_changed'] is False and record['source']==record['cash']==record['risk']==[]
         and record['engine_calls']==0 and record['order']==[], 'BOUNDED_ORDINARY_ACTUAL_NONCASH_DAILY_CONTEXT')
    if a['kind']=='CASH_PLUS_STOCK':
        stock,=record['stock'];need(stock['security_id']==sid and stock['session']==day and stock['actual_context_call'] is True
            and stock['applied'] is bool(held),'BOUNDED_ORDINARY_ACTUAL_MIXED_CALL')
        if not held:
            need(stock.get('unheld_noop') is True and stock['postcondition']==dict(actual_held=False,quantity=0,nominal_cash=0.)
                 and stock['before_state_sha256']==stock['after_state_sha256']
                 and stock['before_ledger_sha256']==stock['after_ledger_sha256'],
                 'BOUNDED_ORDINARY_UNHELD_MIXED_EXACT_CANONICAL_NOOP')
    else:need(record['stock']==[],'BOUNDED_ORDINARY_CONVERSION_DELEGATES_WITHOUT_RECLASSIFICATION')
    return dict(ticker=term['ticker'],session=day,kind=a['kind'],source_lots=len(held),delivered_whole=whole,
                cash_consideration=str(cashleg),cash_in_lieu=str(lieu),actual_context_verified=True)

def grouped_records(terms,observed,through):
    expected={}
    for t in terms:
        if t['added']['session']<=through:expected.setdefault(t['added']['session'],[]).append(t)
    need(set(observed)==set(expected),'BOUNDED_ORDINARY_ENTIRE_COMMITTED_OBSERVATION_AXIS')
    cash_records={};other=[]
    for day,group in expected.items():
        record=observed[day];cash={t['security_id'] for t in group if t['added']['kind']=='CASH_MERGER'}
        mixed={t['security_id'] for t in group if t['added']['kind']=='CASH_PLUS_STOCK'}
        need(record['session']==day and record['passed'] is True and record['financial_source_changed'] is False
             and record['source']==record['risk']==[] and record['engine_calls']==0
             and len(record['cash'])==len(cash) and {v['security_id'] for v in record['cash']}==cash
             and len(record['stock'])==len(mixed) and {v['security_id'] for v in record['stock']}==mixed
             and len(record['order'])==len(cash) and set(record['order'])=={'CASH:'+sid for sid in cash},
             'BOUNDED_ORDINARY_EXACT_WHOLE_DAILY_CALL_SET_BEFORE_PROJECTION')
        if cash:
            projection=deepcopy(record);projection['stock']=[];cash_records[day]=projection
        for term in group:
            if term['added']['kind']=='CASH_MERGER':continue
            projection=deepcopy(record);projection['cash']=[];projection['order']=[]
            projection['stock']=[v for v in record['stock'] if v['security_id']==term['security_id']]
            other.append((term,projection))
    return cash_records,other

def review(root,current,out):
    from full_system_core import hosted
    hosted()
    from system_campaign_uncertainty_review import committed_rows
    from system_campaign_retained_forward_cash import verify_records
    root=Path(root);contract=json.loads((root/DIRECTORY/CONTRACT).read_bytes());tail,_=tail_materials(root,current)
    need(current['base']['sources'][TERMINAL_SOURCE]==TERMINAL_SHA
         and sha((Path('/variant')/TERMINAL_SOURCE).read_bytes())==TERMINAL_SHA,
         'BOUNDED_ORDINARY_FROZEN_PHYSICAL_TERMINAL_SOURCE')
    terms=merge(contract['terms'],tail);through=current['source_cursor'];rows=committed_rows(root/'book',current,'daily')
    expected={t['added']['session'] for t in terms if t['added']['session']<=through}
    observed={p.stem.removeprefix('actual-future-event-'):json.loads(p.read_bytes()) for p in (root/DIRECTORY).glob('actual-future-event-20*.json')
              if p.stem.removeprefix('actual-future-event-')<=through}
    cash_records,other=grouped_records(terms,observed,through)
    cash=[t for t in terms if t['added']['kind']=='CASH_MERGER'];cashdays={t['added']['session'] for t in cash if t['added']['session']<=through}
    events=current['run']['state']['ledger']['events']
    checked=verify_records(rows,events,cash_records,cash,through);stock=[]
    for t,record in other:
        day=t['added']['session'];indexes=[i for i,row in enumerate(rows) if row['session']==day]
        need(len(indexes)==1 and indexes[0]>0,'BOUNDED_ORDINARY_ACTUAL_ADJACENT_NONCASH_ACCOUNTING')
        i=indexes[0];stock.append(stock_event(t,rows[i-1]['evidence']['research_entry_audit']['closing_accounting'],
            rows[i]['evidence']['research_entry_audit']['opening_accounting'],events,record))
    result=dict(passed=True,observation_terms=len(terms),cash_events=checked,conversion_and_mixed_events=stock,
        all17_initial_forward_terms_preserved=True,original_observer_methods_unchanged=True,financial_sessions_reexecuted=0)
    exact(Path(out)/'bounded-ordinary-observation-review.json',encoded(result));return result
