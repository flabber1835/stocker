"""Stopped evidence equations and exhaustive training-only selection.

Never advances a financial Runtime. Reuses the independently qualified event
equations; dollar projection is reconstructed here from original Core rows.
"""
import argparse
from collections import Counter,defaultdict
from copy import deepcopy
from fractions import Fraction as Q
import gzip
import hashlib
import json
from pathlib import Path

from alpaca_fit_inputs import hosted,need
from alpaca_fit_baseline import source_check
from alpaca_fit_funded_source import Source,benchmark_inputs
from alpaca_fit_funded_book import model_basis
from alpaca_fit_account import Runtime
from alpaca_fit_policy import profiles,select
from selective_journal import encode,digest,load,verify_prefixes
from selective_screen import metrics
from risk_review_math import equation,nav,verify_observed_order_coverage


def rounded_rational(value,places=24):
    units,remainder=divmod(value.numerator*10**places,value.denominator)
    return Q(units+(2*remainder>value.denominator or 2*remainder==value.denominator and units%2==1),10**places)


def fill_signature(fills):
    return [(f['episode'],f['side'],f['filled_shares'],f['raw_open'],f['fees']) for f in fills if Q(f['filled_shares'])>0]


def treatment_days(candidate,baseline):
    need(set(candidate)==set(baseline),'TREATMENT_COMMON_DATES')
    return sum(1 for day,fills in candidate.items() if (fills or baseline[day]) and fills!=baseline[day])


def expected_pending(row,source,nav_,target,held_target,execution,initial=False):
    g=Q(str(target));held={};exits=[];opens={};targets={};core=Q(str(row['shadow_nav']))
    for e in row['wealth_core']['episodes'].values():
        key=e['signal_date']+'/'+str(e['slot_id'])
        need(key not in held,'REVIEW_UNIQUE_EPISODE')
        held[key]={k:e[k] for k in ('security_id','ticker','slot_id')}
    slots={v['slot_id']:k for k,v in held.items()}
    for o in row['pending']:
        if o['operation']=='CLOSE_POSITION':
            key=slots[o['slot_id']];need(held[key]['security_id']==o['security_id'],'REVIEW_CORE_EXIT_ID');exits.append(key)
        else:
            need(o['operation']=='OPEN_SLOT_POSITION','REVIEW_PENDING_KIND')
            origin=o['signal_session'];need(origin<=row['session'],'REVIEW_FUTURE_SIGNAL')
            original=Q(str(source.navs[origin]));need(abs(Q(str(o['intended_dollars']))-original/20)<=max(Q('1e-8'),original*Q('1e-10')),
                'REVIEW_ORIGINAL_ENTRY_BUDGET')
            key=origin+'/'+str(o['slot_id']);opens[key]={k:o[k] for k in ('security_id','ticker','slot_id')}
            opens[key]['origin_signal_session']=origin
            targets[key]={'dollars':str(nav_*g/20),'neutral_dollars':str(nav_*g/20),'cause':'CORE_OPEN','local_active':False}
    changed=g!=Q(held_target)
    if initial or changed:
        for e in row['wealth_core']['episodes'].values():
            key=e['signal_date']+'/'+str(e['slot_id'])
            if key in exits:continue
            dollars=nav_*g*Q(str(e['current_shares']))*Q(row['prices'][e['security_id']]['raw_close'])/core
            targets[key]={'dollars':str(dollars),'neutral_dollars':str(dollars),'cause':'INITIAL' if initial else 'GLOBAL','local_active':False}
    return {'signal_session':row['session'],'execution_session':execution,'source_state_sha256':row['state_sha256'],
        'source_input_sha256':row['input_sha256'],'source_chain_sha256':hashlib.sha256(encode(row)+b'\n').hexdigest(),
        'global_target':str(g),'global_changed':changed,'held':held,'exits':sorted(exits),'opens':opens,'targets':targets}


def journal_rows(path,commit):
    result=[];length=0;sha=hashlib.sha256()
    with gzip.open(path,'rb') as f:
        for raw in f:
            value=json.loads(raw);need(encode(value)+b'\n'==raw,'REVIEW_JOURNAL_ENCODING')
            if len(result)<commit['records']:
                result.append(value);length+=len(raw);sha.update(raw)
    need({'records':len(result),'bytes':length,'prefix_sha256':sha.hexdigest()}==commit,'REVIEW_COMMITTED_PREFIX')
    return result


def checkpoints(root,kwargs):
    current=load(root/'checkpoint.json.gz');archive=journal_rows(root/'checkpoints.jsonl.gz',current['checkpoint_archive'])
    need(archive and {k:v for k,v in current.items() if k!='checkpoint_archive'}==archive[-1],'REVIEW_CURRENT_ARCHIVE')
    retained=[load(root/'origin.json.gz')]+archive+[current]
    # Include every inherited actual predecessor, with its original commitments.
    retained.extend(load(p) for p in (root/'lineage').rglob('exact-predecessor.json.gz'))
    for cp in retained:
        need(cp['model_sha256']==kwargs['model_sha256'] and cp['profile_id']==kwargs['profile_id'],'REVIEW_CP_IDENTITY')
        restored=Runtime(**kwargs,checkpoint=cp['runtime'])
        need(restored.checkpoint()==cp['runtime'],'REVIEW_EVERY_TYPED_ROUNDTRIP')
    proof={}
    for name in ('events','daily'):
        proof[name]=verify_prefixes(root/(name+'.jsonl.gz'),[cp['journals'][name] for cp in retained])
        # Tails are retained evidence, never incorporated into the economic path.
        proof[name]['uncommitted_records']=proof[name]['records']-current['journals'][name]['records']
    verify_prefixes(root/'checkpoints.jsonl.gz',[cp['checkpoint_archive'] for cp in retained if 'checkpoint_archive' in cp])
    for admission_path in (root/'lineage').rglob('prefix-admission.json'):
        lineage=admission_path.parent;a=json.loads(admission_path.read_bytes());old=lineage/'exact-predecessor.json.gz'
        need(a['own_profile']==kwargs['profile_id'] and hashlib.sha256(old.read_bytes()).hexdigest()==a['predecessor_file_sha256'],
             'REVIEW_EXACT_OWN_PREDECESSOR')
        original=load(old)
        for name in ('events','daily','checkpoints'):
            spec=original['checkpoint_archive'] if name=='checkpoints' else original['journals'][name]
            verify_prefixes(lineage/('original-'+name+'.jsonl.gz'),[spec])
            with gzip.open(lineage/('original-'+name+'.jsonl.gz'),'rb') as f:raw=f.read()
            tail=raw[spec['bytes']:];saved=a['recovered_tails'][name];actual=(lineage/saved['file']).read_bytes()
            need(actual==tail and len(tail)==saved['bytes'] and hashlib.sha256(tail).hexdigest()==saved['sha256'],'REVIEW_EVERY_RECOVERED_TAIL')
    return current,archive,proof,len(retained)


def factors(row):
    b=row['defensive_bar'];p=row['defensive_previous_bar']
    opening=Q(str(b['open_signal']))*Q(str(b['close_adjusted']))/Q(str(b['close_signal']))
    return opening/Q(str(p['close_adjusted'])),Q(str(b['close_adjusted']))/opening


def action_coverage(row,before,events):
    expected=[];seen=set();held=lambda sid:any(p['security_id']==sid for p in before['positions'].values())
    claims=set(before['claims'])
    for i,e in enumerate(row['ledger_today']):
        kind=e['event_type'];sid=e['security_id'];identifier=row['session']+'/ACTION/'+str(i)
        if kind=='SPLIT' and held(sid) and sid not in seen:expected.append(identifier);seen.add(sid)
        elif kind=='DIVIDEND_ACCRUED' and held(sid):expected.append(identifier)
        elif kind=='DIVIDEND_PAID' and sid+'/'+e['detail']['accrued_session'] in claims:expected.append(identifier)
        elif held(sid):need(kind in ('BUY','SELL','SPLIT'),'REVIEW_UNSUPPORTED_HELD_ACTION')
    observed=[e['record']['event']['event_id'] for e in events if '/ACTION/' in e['record']['event']['event_id']]
    need(expected==observed,'REVIEW_COMPLETE_ACTION_COVERAGE')


def review_book(root,source,protocol,profile,model):
    from sentinel.feed import calendar
    kwargs=dict(model_sha256=model,dataset_sha256=source.dataset_sha256,profile_id=profile,protocol=protocol,source_navs=source.navs)
    current,archive,prefix,ncp=checkpoints(root,kwargs)
    daily=journal_rows(root/'daily.jsonl.gz',current['journals']['daily']);events=journal_rows(root/'events.jsonl.gz',current['journals']['events'])
    need([v['session'] for v in daily]==[r['session'] for r in source.measured[:len(daily)]],'REVIEW_COMPLETE_DAILY_AXIS')
    byday=defaultdict(list)
    for e in events:byday[e['record']['event']['session']].append(e)
    origin=load(root/'origin.json.gz');anchor=source.anchor;capital=Q(protocol['capital'])
    pending=expected_pending(anchor,source,capital,anchor['owned55_profiles'][profile]['evidence']['target'],'0',protocol['measured_start'],True)
    need(origin['runtime']['account'] is None and origin['runtime']['pending']==pending and origin['runtime']['event_count']==0,
         'REVIEW_FIRST_UNFUNDED_ORIGIN')
    before={'schema_id':'research.persistent-funded-account-prototype/2','source_sha256':model,'cash':str(capital),
        'positions':{},'claims':{},'retired':[],'applied_events':[],'last_session':None,'chain_sha256':'0'*64}
    values=[];previous=capital;fees=Q(0);rounding=Q(0);turnover=Q(0);operations=Counter();snapshots={anchor['session']:origin['runtime']};funded_fills={}
    events_seen=0;target_changes=[]
    for d,row in zip(daily,source.measured):
        day=row['session'];first=not values;gap,intraday=factors(row);ev=byday.pop(day,[])
        need(d['source_row_sha256']==hashlib.sha256(encode(row)+b'\n').hexdigest() and d['profile_id']==profile
             and d['dataset_sha256']==source.dataset_sha256,'REVIEW_DAILY_SOURCE')
        need(d['first_funded_open']==d['unfunded_first_overnight_skipped']==first
             and d['gap_factor']==(None if first else str(gap)) and Q(d['intraday_factor'])==intraday,'REVIEW_CLOCK')
        phases=[e['record']['event']['phase'] for e in ev if e['record']['event']['operation']=='DEFENSIVE_FACTOR']
        need(phases==(['INTRADAY'] if first else ['GAP','INTRADAY']),'REVIEW_ALL_FACTOR_PHASES')
        labels={**pending['held'],**pending['opens']};opening=None;opening_state=None
        actual_ids={'holdings':[{'episode':e['signal_date']+'/'+str(e['slot_id']),**e} for e in row['wealth_core']['episodes'].values()]}
        live={e['episode']:e for e in actual_ids['holdings']}
        projected={k:v for k,v in pending['held'].items() if k not in pending['exits']}
        for key,v in live.items():
            if key in projected:continue
            need(key in pending['opens'] and v['signal_date']==pending['opens'][key]['origin_signal_session']<=pending['signal_session']<day
                and v['entry_date']==day and any(e['event_type']=='BUY' and e['security_id']==v['security_id'] for e in row['ledger_today']),
                'REVIEW_SOURCE_FILL_CAUSALITY');projected[key]=v
        need({k:(v['security_id'],v['slot_id']) for k,v in projected.items()}=={k:(v['security_id'],v['slot_id']) for k,v in live.items()},
             'REVIEW_NO_INVENTED_OR_MISSING_CORE_EPISODES')
        # Validate actual ex-date entitlements before sales/buys, after any split.
        action_state=None
        for observed in ev:
            e=observed['record']['event'];op=e['operation']
            if op!='DEFENSIVE_FACTOR' or e['phase']!='GAP':
                if action_state is None:action_state=deepcopy(before)
            if opening is None and (op in ('BUY','SELL','CORE_EXIT_RETIRED') or op=='DEFENSIVE_FACTOR' and e['phase']=='INTRADAY'):
                opening=nav(before,row['prices'],'raw_open');opening_state=deepcopy(before)
            if op in ('BUY','SELL'):
                c=observed['context'];need(c['signal_session']==pending['signal_session'] and c['source_state_sha256']==pending['source_state_sha256']
                    and c['source_input_sha256']==pending['source_input_sha256'],'REVIEW_FILL_PRIOR_INPUT')
                if c['cause']!='CORE_EXIT':need(c['target']==pending['targets'][e['episode']],'REVIEW_PRIOR_DOLLAR_TARGET')
                turnover+=Q(e['filled_shares'])*Q(e['raw_price'])/previous
            elif op=='DEFENSIVE_FACTOR':
                exact=Q(before['cash'])*Q(e['factor']);rounded=rounded_rational(exact)
                need(Q(observed['record']['cash_after'])==rounded and Q(e['rounding_residual'])==rounded-exact,'REVIEW_INDEPENDENT_INTEGER_ROUNDING')
            elif op in ('DIVIDEND_ACCRUED','SPLIT','DIVIDEND_PAID'):
                src=observed['context']['source_event'];i=int(e['event_id'].rsplit('/',1)[1]);need(src==row['ledger_today'][i],'REVIEW_EXACT_ACTION_PREIMAGE')
                if op=='SPLIT':need(Q(e['ratio'])==Q(str(src['detail']['ratio'])),'REVIEW_SOURCE_SPLIT_RATIO')
                if op=='DIVIDEND_ACCRUED':
                    claim=observed['record']['state_without_chain']['claims'][e['claim_id']]
                    need(Q(claim['cash_per_share'])==Q(str(src['price'])) and claim['pay_session']==calendar.next_session(day),
                         'REVIEW_CASH_AMOUNT_AND_RETAINED_SETTLEMENT_CONVENTION')
            before,fee,interest,residual=equation(before,observed,labels,row['prices'],{'gap_factor':str(gap),'intraday_factor':str(intraday)})
            fees+=fee;rounding+=abs(residual);events_seen+=1;operations[op]+=1
        need(opening is not None,'REVIEW_MISSING_INTRADAY_OR_OPEN')
        action_coverage(row,action_state or opening_state,ev)
        verify_observed_order_coverage(opening_state,pending,actual_ids,row['prices'],ev,d['fills'])
        funded_fills[day]=fill_signature(d['fills'])
        compact={k:v for k,v in before.items() if k!='applied_events'}
        need(d['account']==compact and d['applied_events_count']==len(before['applied_events'])
            and d['applied_events_sha256']==hashlib.sha256(json.dumps(before['applied_events'],separators=(',',':')).encode()).hexdigest(),
            'REVIEW_EVERY_ACCOUNT_FIELD')
        actual_nav=nav(before,row['prices'],'raw_close')
        need(Q(d['nav'])==actual_nav and Q(d['previous_nav'])==previous and Q(d['net_factor'])==actual_nav/previous
            and Q(d['opening_nav_before_fills'])==opening and Q(d['rounding_absolute_sum'])==rounding,'REVIEW_EVERY_FACTOR_FEE_AND_NAV')
        need(d['marks']=={p['security_id']:row['prices'][p['security_id']]['raw_close'] for p in before['positions'].values()},'REVIEW_COMPLETE_RAW_MARKS')
        held=pending['global_target'];need(d['held_target']==held,'REVIEW_HELD_EXPOSURE_LAG')
        target=row['owned55_profiles'][profile]['evidence']['target']
        pending=expected_pending(row,source,actual_nav,target,held,calendar.next_session(day))
        need(d['pending']==pending,'REVIEW_ALL_PRIOR_CLOSE_DOLLAR_GEOMETRY')
        if pending['global_changed']:target_changes.append(day)
        values.append((day,str(actual_nav)));previous=actual_nav
        snapshots[day]={'schema':'research.alpaca-owned55-funded-runtime/1','model_sha256':model,'dataset_sha256':source.dataset_sha256,
            'profile_id':profile,'session':day,'account':{'state':deepcopy(before),'state_sha256':digest(before)},'pending':pending,
            'held_global':held,'last_nav':str(actual_nav),'rounding_absolute_sum':str(rounding),'event_count':events_seen,
            'origin_signal':anchor['session'],'source_row_sha256':d['source_row_sha256']}
    need(not byday and events_seen==len(events),'REVIEW_ALL_COMMITTED_EVENTS')
    for cp in archive+[current]:need(cp['runtime']==snapshots[cp['runtime']['session']],'REVIEW_EVERY_CP_MATCHES_ACCOUNTING_PREFIX')
    need(current['runtime']['session']==(values[-1][0] if values else anchor['session']),'REVIEW_CURRENT_CURSOR')
    status=json.loads((root/'book-status.json').read_bytes())
    complete=len(values)==len(source.measured) and status['status']=='COMPLETE'
    blocks={'full':metrics(values,anchor=(protocol['measured_start'],capital))} if values else {}
    for month in sorted({day[:7] for day,_ in values}):
        subset=[v for v in values if v[0].startswith(month)];previous_values=[v for v in values if v[0]<subset[0][0]]
        blocks['month_'+month]=metrics(subset,anchor=previous_values[-1] if previous_values else (protocol['measured_start'],capital))
    return {'profile_id':profile,'status':'REVIEWED' if complete else 'PARTIAL_OR_REFUSED_REVIEWED','records':len(values),
        'metrics':blocks,'fees':str(fees),'turnover':str(turnover),'target_change_sessions':target_changes,'funded_fills':funded_fills,'operations':dict(operations),
        'checkpoints_reviewed':ncp,'all_prefixes':prefix,'events_reviewed':events_seen},values


def main(a):
    hosted();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    request=json.loads(Path(a.request).read_bytes());protocol=json.loads(Path(a.protocol).read_bytes());root=Path(a.evidence)
    binding=source_check(Path('/src'),request['source_files']);source=Source(a.core_evidence,protocol,request['stage'])
    proof,spy=benchmark_inputs(a.inputs,a.prefix_inputs,a.bil_inputs,protocol,source)
    basis=model_basis(request,source);model=digest(basis)
    need(json.loads((root/'financial-model-basis.json').read_bytes())==basis,'REVIEW_FINANCIAL_SOURCE_BASIS')
    need(json.loads((root/'component-qualification.json').read_bytes())['status']=='PASSED','REVIEW_HOSTED_COMPONENT_CASES')
    status=json.loads((root/'fit-status.json').read_bytes());reports=[];paths={}
    for p in status['required_profiles']:
        if not (root/'books'/p/'checkpoint.json.gz').is_file():
            reports.append({'profile_id':p,'status':'UNSTARTED_NO_NEW_ORIGIN'});continue
        r,v=review_book(root/'books'/p,source,protocol,p,model);reports.append(r);paths[p]=v
    _,baseline=profiles(protocol);base=next((r for r in reports if r['profile_id']==baseline.id),None)
    complete=all(r['status']=='REVIEWED' for r in reports);selection=None
    if request['stage']=='TRAINING' and complete:
        records=[]
        for r in reports:
            records.append({'profile_id':r['profile_id'],'period':'TRAINING','candidate_validation_metrics_included':False,
                'status':'REVIEWED','metrics':r['metrics']['full'],'turnover':r['turnover'],
                'additional_funded_transitions':treatment_days(r['funded_fills'],base['funded_fills'])})
        selection=select(records,protocol);(out/'locked-selection.json').write_bytes(encode(selection)+b'\n')
        (out/'all-108-training.json').write_bytes(encode(records)+b'\n')
    result={'schema':'research.alpaca-funded-independent-review/1','stage':request['stage'],
        'status':'COMPLETE_REVIEWED' if complete else 'PARTIAL_PREFIXES_REVIEWED','financial_model_sha256':model,
        'source_execution_sha256':binding,'source_training_prefix':source.training_prefix,'profiles':reports,
        'benchmark_proof':proof,'spy_gross_metrics':metrics(spy,anchor=(protocol['measured_start'],Q(protocol['capital']))),
        'selection_locked':selection is not None,'core_or_account_sessions_advanced':0,'production_contacted':False}
    (out/'independent-review.json').write_bytes(encode(result)+b'\n');print('STOPPED_FUNDED_EQUATIONS_REVIEWED')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','protocol','evidence','core-evidence','inputs','prefix-inputs','bil-inputs','output'):p.add_argument('--'+name,required=True)
    main(p.parse_args())
