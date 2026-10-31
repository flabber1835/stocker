"""Hosted persistent-stock account on the explicitly frozen defensive proxy."""
from fractions import Fraction as Q
from decimal import Decimal as D,localcontext,ROUND_HALF_EVEN
from copy import deepcopy
from holding_account import Account,Intent,RawOpen,trade,mark,split,accrue,pay,cash_merger,commit,snapshot,restore,state,need,hosted
from holding_actions import Terms,convert,receive_spinoff,liquidate_children
from selective_policy import step,retention
from selective_input import observations
from selective_journal import digest


def project(frame,nav,states,transitions,held_global,execution_session=None):
    row=frame['row'];g=Q(row['economics']['pending_allocation']);changed=g!=Q(held_global)
    exit_slots={o['slot_id'] for o in row['evidence']['research_entry_audit']['operations'] if o['operation']=='CLOSE_POSITION'}
    local={x['episode']:x['transition'] for x in transitions};core=Q(row['economics']['parent_core_close_equity'])
    held={};targets={};exits=[];opens={}
    for b in frame['holdings']:
        key=b['episode'];sid=b['security_id'];held[key]=dict(security_id=sid,ticker=b['source_observation']['ticker'],slot_id=b['slot_id'])
        if b['slot_id'] in exit_slots:exits.append(key);continue
        if changed or key in local:
            weight=Q(b['shares'])*Q(frame['prices'][sid]['raw_close'])/core;neutral=nav*g*weight
            targets[key]=dict(dollars=str(neutral*retention(states,key)),neutral_dollars=str(neutral),
                cause='GLOBAL' if changed else 'LOCAL_'+local[key],local_active=retention(states,key)!=1)
    for o in row['evidence']['research_entry_audit']['operations']:
        if o['operation']!='OPEN_SLOT_POSITION':continue
        key=row['session']+'/'+str(o['slot_id']);need(Q(str(o['detail']['target_weight']))==Q('.05'),'REFUSED_SOURCE_ENTRY_BUDGET')
        opens[key]=dict(security_id=o['security_id'],ticker=o['ticker'],slot_id=o['slot_id'])
        targets[key]=dict(dollars=str(nav*g/20),neutral_dollars=str(nav*g/20),cause='CORE_OPEN',local_active=False)
    return dict(signal_session=row['session'],execution_session=execution_session,source_state_sha256=row['state_sha256'],source_input_sha256=row['input_sha256'],
        source_chain_sha256=row['chain_sha256'],global_target=str(g),global_changed=changed,held=held,exits=sorted(exits),
        opens=opens,targets=targets)


class Runtime:
    def __init__(self,source_sha256,canonical,*,enabled,recorder=None,checkpoint=None):
        hosted();self.source_sha256=source_sha256;self.canonical=canonical;self.enabled=enabled;self.recorder=recorder
        self.rounding=Q(0);self.event_count=0
        if checkpoint is None:
            self.account=None;self.policy={};self.pending=None;self.held_global='0';self.last=None
        else:
            need(checkpoint['source_sha256']==source_sha256,'REFUSED_P2_RUNTIME_SOURCE')
            need(checkpoint['policy_enabled'] is enabled,'REFUSED_P2_RESTORE_MODE')
            self.account=restore(checkpoint['account'],source_sha256);self.policy=checkpoint['policy'];self.pending=checkpoint['pending']
            self.held_global=checkpoint['held_global'];self.last=checkpoint['session'];self.rounding=Q(checkpoint['rounding_absolute_sum'])
            self.event_count=checkpoint['event_count'];self.last_nav=Q(checkpoint['last_nav'])

    def apply(self,result,context=None):
        self.account,record=result;self.event_count+=1
        if self.recorder:self.recorder.write(dict(record=record,context=context or {}))
        return record

    def factor(self,day,phase,factor):
        factor=Q(factor);need(factor>0,'REFUSED_DEFENSIVE_FACTOR')
        exact=self.account.cash*factor
        with localcontext() as ctx:
            ctx.prec=80;rounded=(D(exact.numerator)/D(exact.denominator)).quantize(D('1e-24'),rounding=ROUND_HALF_EVEN)
        cash=Q(rounded);residual=cash-exact;need(abs(residual)<=Q('0.0000000000000000000000005'),'REFUSED_PROXY_ROUNDING')
        self.rounding+=abs(residual)
        self.apply(commit(self.account,event=dict(event_id=day+'/PROXY_'+phase,session=day,operation='DEFENSIVE_FACTOR',
            phase=phase,factor=str(factor),rounding_residual=str(residual)),cash=cash))

    def source_actions(self,frame,source):
        day=frame['row']['session'];split_done=set();conversion_done=set()
        for index,e in enumerate(frame['source_events']):
            kind=e['event_type'];sid=e['security_id'];held=[p for p in self.account.positions.values() if p.security_id==sid]
            identifier=day+'/ACTION/'+str(index);detail=e['detail'];context=dict(source_event=e)
            if kind=='SPLIT' and held and sid not in split_done:
                split_done.add(sid)
                self.apply(split(self.account,event_id=identifier,session=day,security_id=sid,ratio=str(detail['ratio']),
                    canonical_split=self.canonical['shares'].split_shares,raw_price=frame['prices'][sid]['raw_open']),context)
            elif kind=='CASH_MERGER' and held:
                self.apply(cash_merger(self.account,event_id=identifier,session=day,security_id=sid,cash_per_share=str(e['price'])),context)
            elif kind=='CONVERSION' and held and sid not in conversion_done:
                conversion_done.add(sid);fact=source.terms[(day,sid)]
                t=Terms(event_id=identifier,session=day,security_id=sid,delivered_security_id=fact['delivered_security_id'],
                    delivered_ticker=fact['delivered_ticker'],ratio=fact['ratio'],cash_per_share=fact['cash_per_share'],
                    cil_price=fact['cil_price'],reference=fact['reference'],input_sha256=frame['row']['input_sha256'],
                    predecessor_sha256=snapshot(self.account)['state_sha256'])
                terminal=self.canonical['terminal']
                def cil(fraction,terms):
                    original=terminal.TerminalTerms(day,sid,terminal.TerminalKind.CONVERSION,exchange_ratio=terms.ratio,
                        cash_in_lieu_price_per_delivered_share=None if terms.cil_price is None else float(terms.cil_price))
                    return terminal._cash_in_lieu(fraction,original)
                self.apply(convert(self.account,t,canonical_entitlement=terminal._split_entitlement,canonical_cil=cil),context)
            elif kind=='SPINOFF_RECEIPT':
                parent=detail['parent_security_id'];parents=[p for p in self.account.positions.values() if p.security_id==parent]
                if parents:
                    fact=source.spins[(day,parent)]
                    t=Terms(event_id=identifier,session=day,security_id=parent,delivered_security_id=sid,
                        delivered_ticker=e['ticker'],ratio=fact['child_shares_per_parent'],cil_price=fact['cash_in_lieu_price'] or None,
                        reference=fact['reference'],input_sha256=frame['row']['input_sha256'],predecessor_sha256=snapshot(self.account)['state_sha256'])
                    self.apply(receive_spinoff(self.account,t),context)
                    quote=RawOpen(session=day,security_id=sid,price=frame['prices'][sid]['raw_open'])
                    self.apply(liquidate_children(self.account,event_id=identifier+'/LIQUIDATE',session=day,security_id=sid,quote=quote),context)
            elif kind=='DIVIDEND_ACCRUED' and held:
                key=sid+'/'+day
                paid=[x for x in source.events if x['event_type']=='DIVIDEND_PAID' and x['security_id']==sid and x['detail']['accrued_session']==day]
                need(len(paid)==1,'REFUSED_SOURCE_DIVIDEND_SETTLEMENT')
                self.apply(accrue(self.account,event_id=identifier,session=day,claim_id=key,security_id=sid,
                    cash_per_share=str(e['price']),pay_session=paid[0]['session']),context)
            elif kind=='DIVIDEND_PAID':
                key=sid+'/'+detail['accrued_session']
                if key in self.account.claims:self.apply(pay(self.account,event_id=identifier,session=day,claim_id=key),context)

    def opening_identities(self,frame):
        pending=self.pending;inventory=deepcopy(pending['held']);day=frame['row']['session']
        for e in frame['source_events']:
            if e['event_type']=='CASH_MERGER':inventory={k:v for k,v in inventory.items() if v['security_id']!=e['security_id']}
            elif e['event_type']=='CONVERSION':
                for v in inventory.values():
                    if v['security_id']==e['security_id']:v.update(security_id=e['detail']['delivered_security_id'],ticker=e['detail']['delivered_ticker'])
        for key in pending['exits']:inventory.pop(key,None)
        for e in frame['row']['retry_diagnostics']['events']:
            if e['outcome']!='FILLED':continue
            key=e['signal_session']+'/'+str(e['slot_id']);need(key in pending['opens'],'REFUSED_UNCOMMITTED_OPENING')
            v=pending['opens'][key];need(v['security_id']==(e.get('filled_security_id') or e['security_id']) and e['signal_session']==pending['signal_session']<day,'REFUSED_OPENING_CAUSALITY')
            inventory[key]=v
        actual={b['episode']:dict(security_id=b['security_id'],ticker=b['source_observation']['ticker'],slot_id=b['slot_id']) for b in frame['holdings']}
        need({k:(v['security_id'],v['slot_id']) for k,v in inventory.items()}==
             {k:(v['security_id'],v['slot_id']) for k,v in actual.items()},'REFUSED_CAUSAL_OPENING_INVENTORY')
        # Ticker is a corroborating display field; permanent SID and origin select ownership.
        for key in inventory:inventory[key]['ticker']=actual[key]['ticker']
        return inventory

    def fills(self,frame,inventory):
        day=frame['row']['session'];pending=self.pending;fills=[]
        def order(key,quantity,side,cause,core_exit=False,target=None):
            p=self.account.positions.get(key);v=inventory.get(key) or pending['held'].get(key)
            sid=p.security_id if p is not None else v['security_id'];ticker=p.ticker if p is not None else v['ticker']
            quote=RawOpen(session=day,security_id=sid,price=frame['prices'][sid]['raw_open'])
            context=dict(cause=cause,core_exit=core_exit,target=target,signal_session=pending['signal_session'],
                source_state_sha256=pending['source_state_sha256'],source_input_sha256=pending['source_input_sha256'])
            before=self.account.positions.get(key);before_q=Q(0) if before is None else before.shares
            record=self.apply(trade(self.account,Intent(event_id=day+'/'+cause+'/'+key,signal_session=pending['signal_session'],
                execution_session=day,episode=key,security_id=sid,ticker=ticker,side=side,shares=quantity,
                source_episode_live=key in inventory,core_exit=core_exit),quote),context)
            fills.append(dict(episode=key,security_id=sid,side=side,cause=cause,before_shares=str(before_q),
                filled_shares=record['event']['filled_shares'],raw_open=str(quote.price),fees=record['event']['fees'],target=target))
        for key in pending['exits']:
            if key in self.account.positions:order(key,self.account.positions[key].shares,'SELL','CORE_EXIT',True)
            elif key not in self.account.retired:
                self.apply(commit(self.account,event=dict(event_id=day+'/RETIRE/'+key,session=day,operation='CORE_EXIT_RETIRED',episode=key),
                    retired=self.account.retired+(key,)))
        desired={}
        for key,t in pending['targets'].items():
            if key not in inventory:continue
            quote=Q(frame['prices'][inventory[key]['security_id']]['raw_open']);target=Q(Q(t['dollars'])//quote)
            current=self.account.positions[key].shares if key in self.account.positions else Q(0)
            if t['cause']=='LOCAL_ENTER':target=min(target,current)
            elif t['cause']=='LOCAL_RECOVER':target=max(target,current)
            if target>current:target=current+Q((target-current)//1)
            desired[key]=(target,current,t)
        keys=sorted(desired,key=lambda k:(inventory[k]['slot_id'],k))
        for side in ('SELL','BUY'):
            for key in keys:
                target,current,t=desired[key];delta=target-current
                if side=='SELL' and delta<0:order(key,-delta,side,t['cause'],target=t)
                elif side=='BUY' and delta>0:
                    need(delta.denominator==1,'REFUSED_FRACTIONAL_INCREASE_PROJECTION')
                    order(key,delta,side,t['cause'],target=t)
        return fills

    def checkpoint(self):
        return dict(schema='research.selective-runtime/1',source_sha256=self.source_sha256,session=self.last,
            policy_enabled=self.enabled,
            account=snapshot(self.account),policy=self.policy,pending=self.pending,held_global=self.held_global,
            last_nav=str(self.last_nav),rounding_absolute_sum=str(self.rounding),event_count=self.event_count)

    def advance(self,frame,source):
        hosted();row=frame['row'];day=row['session'];feature=observations(frame,self.canonical['classifier'])
        if row['phase']=='FORMATION':
            if self.enabled is None:
                self.policy={r['episode']:dict(active=False,entry=0,recovery=0) for r in feature if not r['core_exit']};proof=[]
            else:self.policy,_,proof=step(self.policy,feature,enabled=self.enabled)
            return None,proof
        if self.account is None:
            need(day=='2008-02-22' and Q(source.last_formation_global)==0,'REFUSED_P2_ANCHOR_ORIGIN')
            self.account=Account(source_sha256=self.source_sha256,cash='50000',last_session=day);self.held_global='0';opening=Q(50000);fills=[];prior=Q(50000)
        else:
            need(self.last<day and self.pending['signal_session']==self.last and self.pending['execution_session']==day,'REFUSED_P2_NEXT_SESSION')
            previous=self.account;prior=self.last_nav
            self.factor(day,'GAP',frame['cash']['gap_factor']);self.source_actions(frame,source)
            inventory=self.opening_identities(frame)
            opens={p.security_id:frame['prices'][p.security_id]['raw_open'] for p in self.account.positions.values()}
            opening=mark(self.account,opens);fills=self.fills(frame,inventory);self.held_global=self.pending['global_target']
            self.factor(day,'INTRADAY',frame['cash']['intraday_factor'])
        closes={p.security_id:frame['prices'][p.security_id]['raw_close'] for p in self.account.positions.values()}
        nav=mark(self.account,closes);need(nav>0,'REFUSED_NONPOSITIVE_FUNDED_NAV')
        if self.enabled is None:
            self.policy={r['episode']:dict(active=False,entry=0,recovery=0) for r in feature if not r['core_exit']};transitions=[];proof=[]
        else:self.policy,transitions,proof=step(self.policy,feature,enabled=self.enabled)
        self.pending=project(frame,nav,self.policy,transitions,self.held_global,source.next_session[day])
        self.last=day;self.last_nav=nav
        full=state(self.account);history=full.pop('applied_events')
        finance=dict(account=full,applied_events_count=len(history),applied_events_sha256=digest(history),
            account_state_sha256=snapshot(self.account)['state_sha256'],nav=str(nav),previous_nav=str(prior),
            net_factor=str(nav/prior),opening_nav_before_fills=str(opening),marks=closes,fills=fills,pending=self.pending,
            held_global=self.held_global,rounding_absolute_sum=str(self.rounding))
        record=dict(session=day,source_state_sha256=row['state_sha256'],source_input_sha256=row['input_sha256'],
            source_chain_sha256=row['chain_sha256'],price_chain_sha256=frame['price_chain_sha256'],
            identity_chain_sha256=frame['identity_chain_sha256'],finance=finance,policy=proof,transitions=transitions)
        return record,proof
