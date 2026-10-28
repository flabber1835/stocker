"""Independent equations over observed stopped evidence; no account/runtime imports."""
from pathlib import Path
from fractions import Fraction as Q
from decimal import Decimal as D,localcontext,ROUND_HALF_EVEN
from collections import Counter
from copy import deepcopy
import csv,gzip,hashlib,itertools,json,math,time
P=Path(__file__).resolve().parent;CASE=P.parent
OUT=P/'verified-output/comparison';ORIGINAL=CASE.parent/'zero-share-2008-20261026/output/fixed/run-001'
PRICES=CASE/'holding-action-price-002/verified-output/qualification/prices/price-bindings.jsonl'
def need(v,c):
    if not v:raise ValueError(c)
def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(encode(v)).hexdigest()
def load(p):return json.loads(p.read_bytes())
def gzload(p):
    with gzip.open(p,'rb') as f:return json.load(f)
def rows(p):
    opener=gzip.open if str(p).endswith('.gz') else open
    with opener(p,'rb') as f:
        for line in f:
            need(line.endswith(b'\n'),'COMPLETE_RECORD_'+str(p));yield json.loads(line)
def held(s,sid,kind=None):return {k:v for k,v in s['positions'].items() if v['security_id']==sid and (kind is None or v['kind']==kind)}
def qty(p):return Q(p['shares'])
def bounded_fee_statistic(value):
    with localcontext() as ctx:
        ctx.prec=80;rounded=(D(value.numerator)/D(value.denominator)).quantize(D('1e-36'),rounding=ROUND_HALF_EVEN)
    result=Q(rounded);need(abs(result-value)<=Q('5e-37'),'FEE_STATISTIC_ROUNDING_BOUND');return result
def nav(s,prices,field):return Q(s['cash'])+sum((qty(v)*Q(prices[v['security_id']][field]) for v in s['positions'].values()),Q(0))+sum((Q(c['amount']) for c in s['claims'].values()),Q(0))
def verify_observed_order_coverage(before,previous_pending,current_ids,prices,events,fills):
    inventory={b['episode']:b for b in current_ids['holdings']};expected=[];retire=[]
    for key in previous_pending['exits']:
        if key in before['positions']:expected.append(('SELL',key,str(qty(before['positions'][key])),'CORE_EXIT',True))
        elif key not in before['retired']:retire.append(key)
    projected={}
    for key,t in previous_pending['targets'].items():
        if key not in inventory:continue
        current=qty(before['positions'][key]) if key in before['positions'] else Q(0)
        target=Q(Q(t['dollars'])//Q(prices[inventory[key]['security_id']]['raw_open']))
        if t['cause']=='LOCAL_ENTER':target=min(target,current)
        elif t['cause']=='LOCAL_RECOVER':target=max(target,current)
        if target>current:target=current+Q((target-current)//1)
        projected[key]=(target-current,t)
    keys=sorted(projected,key=lambda k:(inventory[k]['slot_id'],k))
    for side in ('SELL','BUY'):
        for key in keys:
            delta,t=projected[key]
            if (side=='SELL' and delta<0) or (side=='BUY' and delta>0):expected.append((side,key,str(abs(delta)),t['cause'],False))
    actual=[(e['record']['event']['operation'],e['record']['event']['episode'],e['record']['event']['requested_shares'],e['context']['cause'],e['context']['core_exit']) for e in events if e['record']['event']['operation'] in ('BUY','SELL')]
    need(actual==expected,'EVERY_COMMITTED_ORDER_COVERED_SELLS_BEFORE_BUYS')
    need([e['record']['event']['episode'] for e in events if e['record']['event']['operation']=='CORE_EXIT_RETIRED']==retire,'EVERY_EMPTY_CORE_EXIT_RETIRED')
    actual_fills=[(e['record']['event']['operation'],e['record']['event']['episode'],e['record']['event']['filled_shares'],e['record']['event']['fees']) for e in events if e['record']['event']['operation'] in ('BUY','SELL')]
    need(actual_fills==[(f['side'],f['episode'],f['filled_shares'],f['fees']) for f in fills],'DAILY_FILL_AUDIT_MATCHES_ACTUAL_EVENTS')
def labels_and_policy(source,ids,prices,proof,prior,enabled,profile=None):
    features=[];score={};exits={o['slot_id'] for o in source['evidence']['research_entry_audit']['operations'] if o['operation']=='CLOSE_POSITION'}
    available=lambda v:v is not None and math.isfinite(v)
    for b in ids['holdings']:
        o=b['source_observation'];dd=o['own_dd'];r21=o['r21'];r63=o['r63'];age=o['age_sessions']
        red=available(dd) and dd<=-.10 and available(r21) and r21<0
        green=available(dd) and dd>-.075 and available(r21) and r21>0 and (age<63 or available(r63) and r63>0)
        unknown=not all(available(v) for v in [dd,r21]+([r63] if age>=63 else []))
        weight=Q(b['shares'])*Q(prices[b['security_id']]['raw_close'])/Q(source['economics']['parent_core_close_equity'])
        damage=Q(str(max(0,-dd))) if available(dd) else Q(0);f=dict(episode=b['episode'],security_id=b['security_id'],red=red,green=green,unknown=unknown,weight=str(weight),drawdown=str(damage),core_exit=b['slot_id'] in exits)
        features.append(f)
        if red and not unknown:score[f['security_id']]=score.get(f['security_id'],Q(0))+weight*damage
    live=[f for f in features if not f['core_exit']]
    if profile is not None and profile.family not in ('ORACLE_H0','ORACLE_P2'):
        return check_profile_policy(features,proof,prior,profile,source['state_sha256'])
    if enabled is None:need(proof==[],'H0_BYPASS_POLICY');return {f['episode']:dict(active=False,entry=0,recovery=0) for f in live},[]
    need(len(proof)==len(live),'EVERY_POLICY_AUDIT');new={};transitions=[]
    for f,a in zip(live,proof,strict=True):
        for key in ('episode','security_id','red','green','unknown','core_exit'):need(a[key]==f[key],'CANONICAL_OWN_LABEL_'+key)
        for key in ('weight','drawdown'):need(Q(a[key])==Q(f[key]),'SOURCE_POLICY_'+key)
        impairment=score.get(f['security_id'],Q(0));need(Q(a['security_impairment'])==impairment,'SID_AGGREGATED_IMPAIRMENT')
        old=prior.get(f['episode'],dict(active=False,entry=0,recovery=0));need(a['state_before']==old,'OBSERVED_COUNTER_ADJACENCY')
        expected=dict(old);change=None
        if not enabled:expected=dict(active=False,entry=0,recovery=0)
        elif f['unknown']:expected.update(entry=0,recovery=0)
        elif old['active']:
            expected['entry']=0;expected['recovery']=old['recovery']+1 if f['green'] else 0
            if expected['recovery']>=8:expected=dict(active=False,entry=0,recovery=0);change='RECOVER'
        else:
            expected['recovery']=0;expected['entry']=old['entry']+1 if f['red'] and impairment>=Q('.02') else 0
            if expected['entry']>=5:expected=dict(active=True,entry=0,recovery=0);change='ENTER'
        need(a['state_after']==expected and a['transition']==change,'EXACT_FIVE_EIGHT_POLICY_EQUATIONS');new[f['episode']]=a['state_after']
        if change:transitions.append(dict(episode=f['episode'],security_id=f['security_id'],transition=change))
    return new,transitions

def check_profile_policy(features,proof,prior,p,source_state):
    need(set(proof)=={'profile_id','observations','book'} and proof['profile_id']==p.id,'EXACT_POLICY_PROFILE')
    live=[f for f in features if not f['core_exit']];audit=proof['observations'];need(len(audit)==len(live),'ALL_PROFILE_OBSERVATIONS')
    weights={};scores={}
    for f in features:
        sid=f['security_id'];weights[sid]=weights.get(sid,Q(0))+Q(f['weight'])
        if f['red'] and not f['unknown']:scores[sid]=scores.get(sid,Q(0))+Q(f['weight'])*Q(f['drawdown'])
    cold=lambda cap=False:dict(active=False,entry=0,recovery=0,**(dict(age=0,ratio='1') if cap else {}))
    def latch(old,entry,recovery,unknown):
        if unknown:return {**old,'entry':0,'recovery':0},None
        if old['active']:
            n=old['recovery']+1 if recovery else 0
            return (cold(),'RECOVER') if n>=p.recovery else (dict(active=True,entry=0,recovery=n),None)
        n=old['entry']+1 if entry else 0
        return (dict(active=True,entry=0,recovery=0),'ENTER') if n>=p.entry else (dict(active=False,entry=n,recovery=0),None)
    expected={};changes={};book=None
    if p.family=='BOOK_DAMAGE':
        total=sum(weights.values(),Q(0));risk=sum(scores.values(),Q(0));green=sum((Q(f['weight']) for f in features if f['green']),Q(0))/total if total else Q(0)
        unknown=not features or total==0 or any(f['unknown'] for f in features);before=prior.get('__book__',cold());book,change=latch(before,risk>=Q(p.threshold),green>=Q('.5'),unknown)
        b=proof['book'];need(b['state_before']==before and b['state_after']==book and Q(b['impairment'])==risk and Q(b['green_fraction'])==green and b['unknown']==unknown and b['transition']==change,'BOOK_RISK_LATCH_EQUATIONS')
        expected['__book__']=book
        for f in live:expected[f['episode']]=dict(active=book['active'],entry=0,recovery=0);changes[f['episode']]=change
    elif p.family=='CONCENTRATION_BAND':
        need(proof['book'] is None,'NO_UNDECLARED_BOOK_POLICY');groups={}
        for f in live:groups.setdefault(f['security_id'],[]).append(f['episode'])
        for sid,keys in groups.items():
            existing=[prior[k] for k in keys if k in prior];before=existing[0] if existing else cold(True)
            need(all(x==before for x in existing),'SHARED_SECURITY_STATE');w=weights[sid];change=None
            if before['active']:
                age=before['age']+1;n=before['recovery']+1 if w<=Q(p.release) else 0
                if n>=p.recovery:after=cold(True);change='RECOVER'
                else:
                    change='ENTER' if age>=p.rebalance else None;after=dict(active=True,entry=0,recovery=n,age=0 if change else age,ratio='1')
            else:
                n=before['entry']+1 if w>Q(p.threshold) else 0
                if n>=p.entry:after=dict(active=True,entry=0,recovery=0,age=0,ratio='1');change='ENTER'
                else:after={**before,'entry':n,'recovery':0}
            after['ratio']=str(min(Q(1),Q(p.release)/w)) if after['active'] and w else '1'
            for key in keys:expected[key]=after;changes[key]=change
    else:
        need(p.family=='LOCAL_RED' and proof['book'] is None,'LOCAL_PROFILE_FAMILY')
        for f in live:expected[f['episode']],changes[f['episode']]=latch(prior.get(f['episode'],cold()),f['red'],f['green'],f['unknown'])
    transitions=[]
    for f,a in zip(live,audit,strict=True):
        for k in ('episode','security_id','red','green','unknown','core_exit'):need(a[k]==f[k],'PROFILE_CANONICAL_LABEL_'+k)
        for k in ('weight','drawdown'):need(Q(a[k])==Q(f[k]),'PROFILE_SOURCE_'+k)
        need(a['source_state_sha256']==source_state and Q(a['security_impairment'])==scores.get(f['security_id'],Q(0)),'PROFILE_SOURCE_AND_IMPAIRMENT')
        before=prior.get(f['episode'],cold(p.family=='CONCENTRATION_BAND'));after=expected[f['episode']];change=changes[f['episode']]
        need(a['state_before']==before and a['state_after']==after and a['transition']==change,'PROFILE_STATE_EQUATIONS')
        if p.family=='CONCENTRATION_BAND':need(Q(a['security_weight'])==weights[f['security_id']],'PERMANENT_SECURITY_CAPITAL')
        if change:transitions.append(dict(episode=f['episode'],security_id=f['security_id'],transition=change))
    return expected,transitions
def equation(before,observed,labels,prices,cashrow):
    record=observed['record'];context=observed['context'];e=record['event'];op=e['operation'];after={**record['state_without_chain'],'chain_sha256':record['chain_sha256']}
    expected=deepcopy(before);cash=Q(before['cash']);positions=expected['positions'];claims=expected['claims'];retired=expected['retired']
    need(Q(record['cash_before'])==cash,'EVENT_CASH_BEFORE')
    fees=Q(0);interest=Q(0);rounding=Q(0)
    if op=='DEFENSIVE_FACTOR':
        phase=e['phase'];need(Q(e['factor'])==Q(cashrow['gap_factor' if phase=='GAP' else 'intraday_factor']),'ACTUAL_CASH_FACTOR')
        exact=cash*Q(e['factor'])
        with localcontext() as ctx:ctx.prec=80;rounded=(D(exact.numerator)/D(exact.denominator)).quantize(D('1e-24'),rounding=ROUND_HALF_EVEN)
        cash=Q(rounded);rounding=cash-exact;need(rounding==Q(e['rounding_residual']) and abs(rounding)<=Q('5e-25'),'FACTOR_ROUNDING')
        interest=cash-Q(before['cash'])
    elif op in ('BUY','SELL'):
        key=e['episode'];q=Q(e['filled_shares']);requested=Q(e['requested_shares']);price=Q(e['raw_price']);fees=q*price/1000;old=positions.get(key)
        need(price==Q(prices[e['security_id']]['raw_open']) and Q(e['fees'])==fees and 0<=q<=requested,'RAW_OPEN_FEE')
        need(context['signal_session']<e['session'] and key not in before['retired'],'LAG_RETIRED')
        if op=='BUY':
            need(requested.denominator==1 and q==min(requested,cash//(price*Q('1.001'))),'WHOLE_CASH_CLIPPED_BUY');cash-=q*price+fees
            if q:positions[key]=dict(episode=key,security_id=e['security_id'],ticker=old['ticker'] if old else labels[key]['ticker'],kind='EQUITY',shares=str(q+(qty(old) if old else 0)))
        else:
            need(old is not None and q==requested and 0<q<=qty(old),'LONG_ONLY_SELL');cash+=q*price-fees;remaining=qty(old)-q
            if remaining:positions[key]={**old,'shares':str(remaining)}
            else:del positions[key]
        need(e['outcome']==('FILLED' if q else 'CASH_CLIPPED_ZERO'),'FILL_OUTCOME')
        if context['core_exit']:need(key not in positions,'FULL_CORE_EXIT');retired.append(key)
    elif op=='CORE_EXIT_RETIRED':
        need(e['episode'] not in positions and e['episode'] not in retired,'EMPTY_EPISODE_RETIRE');retired.append(e['episode'])
    elif op in ('CONVERSION','SPINOFF_RECEIPT'):
        t=e['terms'];need(e['terms_sha256']==digest(t) and t['predecessor_sha256']==digest(before),'OWN_EXACT_ACTION_PREDECESSOR')
        need(t['session']==e['session'] and t['security_id']==e['security_id'],'ACTION_DATE_IDENTITY')
        source=held(before,t['security_id'],'EQUITY');total=sum((qty(v) for v in source.values()),Q(0));ent=total*Q(t['ratio']);whole=ent//1;fraction=ent-whole
        settled=fraction
        if t['rounding']=='NEAREST_HUNDREDTH_HALF_UP':units,rem=divmod(fraction.numerator*100,fraction.denominator);settled=Q(units+(rem*2>=fraction.denominator),100)
        need(not fraction or t['cil_price'] is not None,'MISSING_CIL_REFUSED');cil=settled*Q(t['cil_price'] or 0);cashleg=total*Q(t['cash_per_share'])
        need(Q(e['entitled_shares'])==total and e['whole_delivered']==whole and Q(e['exact_fraction'])==fraction and Q(e['cash_in_lieu'])==cil,'HOLDER_ENTITLEMENT')
        if op=='CONVERSION':
            need(Q(e['cash_leg'])==cashleg and Q(e['settlement_fraction'])==settled and Q(e['fees'])==0,'CONVERSION_CASH');cash+=cashleg+cil
            for key,v in source.items():
                q=Q(whole)*qty(v)/total;need(Q(e['delivered_lots'][key])==q,'PRO_RATA_FRACTION')
                if q:positions[key]={**v,'security_id':t['delivered_security_id'],'ticker':t['delivered_ticker'],'shares':str(q)}
                else:del positions[key];retired.append(key)
        else:
            need(cashleg==0 and t['rounding']=='EXACT','SPINOFF_TERMS');cash+=cil
            for key,v in source.items():
                q=Q(whole)*qty(v)/total;child=key+'/spin/'+e['event_id']
                if q:need(Q(e['delivered_lots'][child])==q,'CHILD_ENTITLEMENT');positions[child]=dict(episode=child,security_id=t['delivered_security_id'],ticker=t['delivered_ticker'],kind='ACTION_CHILD',shares=str(q))
    elif op=='SPINOFF_LIQUIDATION':
        source=held(before,e['security_id'],'ACTION_CHILD');q=sum((qty(v) for v in source.values()),Q(0));price=Q(e['raw_price']);gross=q*price;fees=gross/1000
        need(price==Q(prices[e['security_id']]['raw_open']) and Q(e['shares'])==q and Q(e['gross'])==gross and Q(e['fees'])==fees,'CHILD_RAW_OPEN_SINGLE_FEE');cash+=gross-fees
        for key in source:del positions[key];retired.append(key)
    elif op=='DIVIDEND_ACCRUED':
        q=sum((qty(v) for v in held(before,e['security_id']).values()),Q(0));claim=after['claims'][e['claim_id']]
        need(e['claim_id'] not in claims and Q(claim['entitled_shares'])==q==Q(e['entitled_shares']) and Q(claim['amount'])==q*Q(claim['cash_per_share'])==Q(e['amount']),'ACTUAL_DIVIDEND_ENTITLEMENT');claims[e['claim_id']]=claim
    elif op=='DIVIDEND_PAID':
        claim=claims.pop(e['claim_id']);need(e['session']>=claim['pay_session'] and Q(e['amount'])==Q(claim['amount']),'ONCE_ONLY_CLAIM_SETTLEMENT');cash+=Q(claim['amount'])
    elif op=='SPLIT':
        for key,v in held(before,e['security_id']).items():positions[key]={**v,'shares':str(qty(v)*Q(e['ratio']))}
    elif op=='CASH_MERGER':
        source=held(before,e['security_id']);q=sum((qty(v) for v in source.values()),Q(0));value=q*Q(e['cash_per_share'])
        need(Q(e['entitled_shares'])==q and Q(e['amount'])==value,'ACTUAL_CASH_MERGER_ENTITLEMENT');cash+=value
        for key in source:del positions[key];retired.append(key)
    else:raise ValueError('UNREVIEWED_OPERATION_'+op)
    need(cash>=0 and e['event_id'] not in before['applied_events'],'NO_LEVERAGE_DUPLICATE')
    expected.update(cash=str(cash),last_session=e['session'],applied_events=before['applied_events']+[e['event_id']])
    chain=digest(dict(previous=before['chain_sha256'],record={k:v for k,v in record.items() if k!='chain_sha256'}));expected['chain_sha256']=chain
    need(after==expected and Q(record['cash_after'])==cash,'EVERY_STATE_FIELD_AND_CHAIN')
    return after,fees,interest,rounding

def prefixes(root):
    paths=[root/'checkpoint.json.gz']+sorted((root/'month-end').glob('*.json.gz'))+sorted((root/'pre-event').glob('*.json.gz'))
    if (root/'restart-boundary.json.gz').exists():paths.append(root/'restart-boundary.json.gz')
    current=gzload(paths[0]);proof={};specs={n:{} for n in ('events','daily','formation')}
    for path in paths:
        c=gzload(path);s=c['runtime']['account'];need(digest(s['state'])==s['state_sha256'],'CHECKPOINT_ACCOUNT_HASH')
        for name in specs:
            s=c['journals'][name];n=s['records'];need(n not in specs[name] or specs[name][n]==s,'CONSISTENT_PREFIX');specs[name][n]=s
    for name in ('events','daily','formation'):
        wanted=specs[name]
        h=hashlib.sha256();size=count=0;seen=set()
        def check():
            if count in wanted:need(wanted[count]==dict(bytes=size,records=count,prefix_sha256=h.hexdigest()),'ALL_HISTORICAL_PREFIX_'+name);seen.add(count)
        check()
        with gzip.open(root/(name+'.jsonl.gz'),'rb') as f:
            for raw in f:need(raw.endswith(b'\n'),'NO_PARTIAL_LINE');h.update(raw);size+=len(raw);count+=1;check()
        need(seen==set(wanted),'EVERY_PREFIX_PRESENT');committed=current['journals'][name];proof[name]=dict(records=count,bytes=size,sha256=h.hexdigest(),tail_records=count-committed['records'],tail_bytes=size-committed['bytes'])
    return dict(checkpoints=len(paths),journals=proof),current

def review_book(arm,cashrows,*,profile=None):
    root=OUT/arm;cpfile=root/'checkpoint.json.gz'
    if not cpfile.exists():return dict(status='NO_ACCOUNT_CHECKPOINT'),[]
    prefix,current=prefixes(root);cursor=current['runtime']['session'];source_sha=current['runtime']['source_sha256']
    byevent=itertools.groupby(rows(root/'events.jsonl.gz'),lambda x:x['record']['event']['session']);ev=iter(byevent);group=next(ev,None)
    originals=itertools.chain(rows(ORIGINAL/'formation.jsonl'),rows(ORIGINAL/'daily.jsonl'));identities=rows(OUT/'identity/identity-bindings.jsonl');prices=rows(PRICES)
    daily=iter(rows(root/'daily.jsonl.gz'));actual=next(daily,None);formation=iter(rows(root/'formation.jsonl.gz'));values=[];before=None;fees=interest=rounding=Q(0);events=0;counts=Counter();previous=Q(50000);previous_pending=None;policy={};enabled=(None if profile.family=='ORACLE_H0' else True) if profile is not None else (True if arm=='P2' else False if arm=='H0-disabled' else None);formation_count=0
    daily_hash=hashlib.sha256();policy_transitions=0;dev_fees=Q(0);dev_fee_terms=0;dev_treatment=0
    for src,ids,ps in zip(originals,identities,prices,strict=True):
        day=src['session']
        if src['phase']=='FORMATION':
            observed=next(formation);need(observed['session']==day and observed['source_state_sha256']==src['state_sha256'],'FORMATION_SOURCE_BINDING')
            policy,_=labels_and_policy(src,ids,ps['prices'],observed['policy'],policy,enabled,profile);formation_count+=1;continue
        if actual is None:break
        need(actual['session']==day==ids['session']==ps['session'],'SOURCE_DAILY_AXIS')
        for key in ('state_sha256','input_sha256','chain_sha256'):need(actual['source_'+key]==src[key]==ps['source_'+key]==ids['source_'+key],'SOURCE_DAILY_BINDING')
        need(actual['price_chain_sha256']==ps['price_chain_sha256'] and actual['identity_chain_sha256']==ids['identity_chain_sha256'],'QUALIFIED_ROW_CHAINS')
        f=actual['finance'];labels={b['episode']:dict(ticker=b['source_observation']['ticker']) for b in ids['holdings']}
        if previous_pending:labels.update(previous_pending['held']);labels.update(previous_pending['opens'])
        if before is None:
            before=dict(schema_id='research.persistent-funded-account-prototype/2',source_sha256=source_sha,cash='50000',positions={},claims={},retired=[],applied_events=[],last_session=day,chain_sha256='0'*64);opening=Q(50000)
        else:
            need(previous_pending['signal_session']==values[-1][0] and previous_pending['execution_session']==day,'EXACT_NEXT_OPEN')
            opening=None;opening_state=None;day_events=[]
            if group and group[0]==day:day_events=list(group[1]);group=next(ev,None)
            need(day_events and day_events[0]['record']['event']['operation']=='DEFENSIVE_FACTOR' and day_events[0]['record']['event']['phase']=='GAP','OLD_CASH_GAP_FIRST')
            for observed in day_events:
                e=observed['record']['event'];op=e['operation']
                if opening is None and (op in ('BUY','SELL','CORE_EXIT_RETIRED') or op=='DEFENSIVE_FACTOR' and e['phase']=='INTRADAY'):opening=nav(before,ps['prices'],'raw_open');opening_state=deepcopy(before)
                if op in ('BUY','SELL') and observed['context']['cause']!='CORE_EXIT':
                    key=e['episode'];t=previous_pending['targets'][key];need(observed['context']['target']==t,'COMMITTED_PRIOR_CLOSE_TARGET')
                    current_q=qty(before['positions'][key]) if key in before['positions'] else Q(0);target=Q(Q(t['dollars'])//Q(e['raw_price']))
                    if t['cause']=='LOCAL_ENTER':target=min(target,current_q)
                    elif t['cause']=='LOCAL_RECOVER':target=max(target,current_q)
                    if target>current_q:target=current_q+Q((target-current_q)//1)
                    need(Q(e['requested_shares'])==abs(target-current_q) and (op=='BUY')==(target>current_q),'WHOLE_INCREMENT_FRACTION_CARRY_AND_DIRECTION')
                before,fee,earned,residual=equation(before,observed,labels,ps['prices'],cashrows[day]);fees+=fee;interest+=earned;rounding+=abs(residual);events+=1;counts[op]+=1
                if day<='2017-12-31':
                    dev_fees+=bounded_fee_statistic(fee/previous);dev_fee_terms+=1
                    target_info=observed['context'].get('target') or {}
                    if op in ('BUY','SELL') and target_info.get('local_active',False):
                        key=e['episode'];after_q=qty(before['positions'][key]) if key in before['positions'] else Q(0);filled=Q(e['filled_shares']);neutral=Q(Q(target_info['neutral_dollars'])//Q(e['raw_price']))
                        if op=='SELL':extra=max(Q(0),min(after_q+filled,neutral)-after_q)
                        else:
                            previous_q=after_q-filled;neutral_request=max(Q(0),Q((neutral-previous_q)//1));affordable=Q(observed['record']['cash_before'])//(Q(e['raw_price'])*Q('1.001'));extra=max(Q(0),min(neutral_request,affordable)-filled)
                        if extra>0:dev_treatment+=1
            need(opening is not None,'OPENING_CAPTURE')
            verify_observed_order_coverage(opening_state,previous_pending,ids,ps['prices'],day_events,f['fills'])
        compact={k:v for k,v in before.items() if k!='applied_events'}
        need(f['account']==compact and f['account_state_sha256']==digest(before) and f['applied_events_count']==len(before['applied_events']) and f['applied_events_sha256']==digest(before['applied_events']),'OBSERVED_COMPACT_ACCOUNT')
        close=nav(before,ps['prices'],'raw_close');need(close==Q(f['nav']) and Q(f['previous_nav'])==previous and Q(f['net_factor'])==close/previous and Q(f['opening_nav_before_fills'])==opening,'EVERY_RAW_NAV_AND_NEXT_OPEN_FACTOR')
        need(Q(f['rounding_absolute_sum'])==rounding,'CUMULATIVE_ROUNDING')
        for sid,price in f['marks'].items():need(Q(price)==Q(ps['prices'][sid]['raw_close']),'RAW_CLOSE_MARK')
        policy,expected_changes=labels_and_policy(src,ids,ps['prices'],actual['policy'],policy,enabled,profile);need(actual['transitions']==expected_changes,'EXACT_ACTUAL_TRANSITIONS')
        pending=f['pending'];original_g=Q(src['economics']['pending_allocation']);book_active=profile is not None and profile.family=='BOOK_DAMAGE' and policy.get('__book__',{}).get('active',False)
        effective=original_g*(Q(profile.retained) if book_active else 1)
        need(pending['signal_session']==day and Q(pending['global_target'])==effective,'PRIOR_CLOSE_TARGET_SOURCE')
        generic=profile is not None and profile.family not in ('ORACLE_H0','ORACLE_P2')
        if generic:need(pending['profile_id']==profile.id and pending['risk_scope']==profile.family and pending['risk_book_active']==book_active and Q(pending['original_global_target'])==original_g,'PROFILE_PROJECTION_PROVENANCE')
        need(f['held_global']==('0' if previous_pending is None else previous_pending['global_target']),'ACTUAL_HELD_GLOBAL_LAG')
        changed=Q(pending['global_target'])!=Q(f['held_global']);need(pending['global_changed']==changed,'ACTUAL_GLOBAL_TARGET_CHANGE')
        changes={c['episode']:c['transition'] for c in expected_changes};held_ids={b['episode']:b for b in ids['holdings']}
        exit_slots={o['slot_id'] for o in src['evidence']['research_entry_audit']['operations'] if o['operation']=='CLOSE_POSITION'}
        exits=sorted(k for k,b in held_ids.items() if b['slot_id'] in exit_slots);need(pending['exits']==exits,'SOURCE_CORE_EXITS_EXACT')
        newopens={day+'/'+str(o['slot_id']):dict(security_id=o['security_id'],ticker=o['ticker'],slot_id=o['slot_id']) for o in src['evidence']['research_entry_audit']['operations'] if o['operation']=='OPEN_SLOT_POSITION'}
        need(pending['opens']==newopens,'ONLY_ORIGINAL_CORE_OPENS')
        target_keys={k for k in held_ids if k not in exits and (changed or k in changes)}|set(newopens)
        need(set(pending['targets'])==target_keys,'NO_MISSING_OR_EXTRA_TARGETS')
        for key,t in pending['targets'].items():
            cause='CORE_OPEN' if key in newopens else 'GLOBAL' if changed else 'LOCAL_'+changes[key]
            state=policy.get(key,{})
            if book_active:ratio=Q(profile.retained)
            elif profile is not None and profile.family=='BOOK_DAMAGE':ratio=Q(1)
            elif key in newopens or not state.get('active'):ratio=Q(1)
            elif profile is not None and profile.family=='CONCENTRATION_BAND':ratio=Q(state['ratio'])
            else:ratio=Q(profile.retained) if profile is not None else Q('.55')
            active=ratio!=1
            need(t['cause']==cause and t['local_active']==active,'EXACT_TARGET_CAUSE_AND_RETENTION')
        need(not set(pending['exits'])&set(pending['targets']),'EXIT_DOMINATES_TARGET')
        for key,t in pending['targets'].items():
            if key in pending['opens']:neutral=close*original_g/20
            else:
                b=next(b for b in ids['holdings'] if b['episode']==key);neutral=close*original_g*Q(b['shares'])*Q(ps['prices'][b['security_id']]['raw_close'])/Q(src['economics']['parent_core_close_equity'])
            state=policy.get(key,{})
            if book_active:ratio=Q(profile.retained)
            elif profile is not None and profile.family=='BOOK_DAMAGE' or key in pending['opens'] or not state.get('active'):ratio=Q(1)
            elif profile is not None and profile.family=='CONCENTRATION_BAND':ratio=Q(state['ratio'])
            else:ratio=Q(profile.retained) if profile is not None else Q('.55')
            need(Q(t['neutral_dollars'])==neutral and Q(t['dollars'])==neutral*ratio,'OWN_NAV_CLOSE_DOLLAR_PROJECTION')
        daily_hash.update(encode(f)+b'\n');policy_transitions+=len(actual['transitions']);values.append((day,str(close)));previous=close;previous_pending=pending;actual=next(daily,None)
        if day==cursor:need(current['runtime']['account']['state']==before and current['runtime']['pending']==pending and current['runtime']['policy']==policy,'CURRENT_CP_MATCHES_COMMITTED_ROW')
    need(actual is None,'EVERY_EXPORTED_DAILY_ROW')
    tail=0
    if group:
        tail=sum(1 for _ in group[1])+sum(1 for _,g in ev for _ in g)
    return dict(status='OBSERVED_ACCOUNTING_PREFIX_PASSED',development_fee_burden=str(dev_fees),development_fee_statistic_rounding='36_DECIMAL_HALF_EVEN_TIE_BREAK_ONLY',development_fee_statistic_terms=dev_fee_terms,development_fee_statistic_error_bound=str(dev_fee_terms*Q('5e-37')),development_treatment_count=dev_treatment,formation_records=formation_count,records=len(values),last_close=values[-1][0] if values else None,events=events,operations=dict(counts),fees=str(fees),proxy_cash_earnings=str(interest),rounding_absolute_sum=str(rounding),finance_path_sha256=daily_hash.hexdigest(),policy_transitions=policy_transitions,prefix_review=prefix,uncommitted_event_tail_records=tail),values
