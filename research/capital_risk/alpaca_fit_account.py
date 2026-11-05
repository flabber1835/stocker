"""New 2025-origin adapter on existing persistent-account financial primitives.

This module does not advance Core, select stocks or call the old date-bound
Runtime.advance. Actual financial operations remain hosted-only.
"""
from copy import deepcopy
from fractions import Fraction as Q
import hashlib
import json

from alpaca_fit_inputs import hosted,need
from holding_account import Account,mark,split,accrue,pay,snapshot,restore,state
from selective_model import Runtime as FinancialPrimitives


def episode_key(episode):return episode['signal_date']+'/'+str(episode['slot_id'])


def inventory(row):
    return {episode_key(e):{'security_id':e['security_id'],'ticker':e['ticker'],'slot_id':e['slot_id']}
            for e in row['wealth_core']['episodes'].values()}


def projection(row,*,nav,target,held_target,execution_session,initial=False,source_navs=None):
    """Prior-close dollar geometry only; no account transition or future mark."""
    target,nav=Q(str(target)),Q(nav);need(0<=target<=1 and nav>0,'PROJECTION_DOMAIN')
    changed=target!=Q(held_target);held=inventory(row);core=Q(str(row['shadow_nav']))
    need(core>0,'SOURCE_NAV');exits=[];opens={};targets={}
    by_slot={e['slot_id']:e for e in row['wealth_core']['episodes'].values()}
    for order in row['pending']:
        if order['operation']=='CLOSE_POSITION':
            episode=by_slot[order['slot_id']]
            need(episode['security_id']==order['security_id'],'EXIT_IDENTITY');exits.append(episode_key(episode))
        elif order['operation']=='OPEN_SLOT_POSITION':
            origin=order['signal_session'];need(origin<=row['session'],'FUTURE_CORE_SIGNAL')
            source_nav=core if origin==row['session'] else Q(str((source_navs or {})[origin]))
            dollars=Q(str(order['intended_dollars']))
            need(abs(dollars-source_nav/20)<=max(Q('0.00000001'),source_nav*Q('0.0000000001')),'SOURCE_NAV20_ENTRY')
            key=order['signal_session']+'/'+str(order['slot_id'])
            opens[key]={'security_id':order['security_id'],'ticker':order['ticker'],'slot_id':order['slot_id'],
                'origin_signal_session':origin}
            value=nav*target/20
            targets[key]={'dollars':str(value),'neutral_dollars':str(value),'cause':'CORE_OPEN','local_active':False}
        else:raise ValueError('REFUSED_ALPACA_FIT_PENDING_OPERATION')
    if initial or changed:
        for episode in row['wealth_core']['episodes'].values():
            key=episode_key(episode)
            if key in exits:continue
            sid=episode['security_id'];weight=Q(str(episode['current_shares']))*Q(row['prices'][sid]['raw_close'])/core
            need(0<weight<=1,'SOURCE_HOLDING_WEIGHT');value=nav*target*weight
            targets[key]={'dollars':str(value),'neutral_dollars':str(value),'cause':'INITIAL' if initial else 'GLOBAL','local_active':False}
    return {'signal_session':row['session'],'execution_session':execution_session,'source_state_sha256':row['state_sha256'],
        'source_input_sha256':row['input_sha256'],'source_chain_sha256':hashlib.sha256(
            json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n').hexdigest(),
        'global_target':str(target),'global_changed':changed,'held':held,'exits':sorted(exits),'opens':opens,'targets':targets}


def defensive_factors(row):
    def adjusted_open(bar):return Q(str(bar['open_signal']))*Q(str(bar['close_adjusted']))/Q(str(bar['close_signal']))
    current,previous=row['defensive_bar'],row['defensive_previous_bar'];opening=adjusted_open(current)
    return opening/Q(str(previous['close_adjusted'])),Q(str(current['close_adjusted']))/opening


class Runtime(FinancialPrimitives):
    def __init__(self,*,model_sha256,dataset_sha256,profile_id,protocol,source_navs=None,recorder=None,checkpoint=None):
        hosted();super().__init__(model_sha256,{},enabled=False,recorder=recorder)
        self.model_sha256=model_sha256;self.dataset_sha256=dataset_sha256;self.profile_id=profile_id;self.protocol=protocol
        self.source_navs=source_navs or {}
        self.origin_signal=None;self.last_row_sha256=None
        from stock_strategy_shared.wealth_core.shares import split_shares
        self.canonical_split=split_shares
        if checkpoint is not None:
            need(checkpoint['schema']=='research.alpaca-owned55-funded-runtime/1'
                and checkpoint['model_sha256']==model_sha256 and checkpoint['dataset_sha256']==dataset_sha256
                and checkpoint['profile_id']==profile_id,'FUNDED_RESTORE_IDENTITY')
            self.account=None if checkpoint['account'] is None else restore(checkpoint['account'],model_sha256)
            self.pending=deepcopy(checkpoint['pending'])
            self.held_global=checkpoint['held_global'];self.last=checkpoint['session'];self.last_nav=Q(checkpoint['last_nav'])
            self.rounding=Q(checkpoint['rounding_absolute_sum']);self.event_count=checkpoint['event_count']
            self.origin_signal=checkpoint['origin_signal'];self.last_row_sha256=checkpoint['source_row_sha256']

    def start(self,anchor):
        from sentinel.feed import calendar
        need(self.account is None and self.pending is None,'DUPLICATE_FUNDED_ORIGIN')
        expected=calendar.previous_sessions(self.protocol['measured_start'],2)[0]
        need(anchor['phase']=='FORMATION' and anchor['session']==expected,'FUNDED_FORMATION_BOUNDARY')
        self.origin_signal=expected;self.last=expected;self.last_nav=Q(self.protocol['capital'])
        self.last_row_sha256=hashlib.sha256(json.dumps(anchor,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n').hexdigest()
        target=anchor['owned55_profiles'][self.profile_id]['evidence']['target']
        self.pending=projection(anchor,nav=self.last_nav,target=target,held_target='0',
            execution_session=self.protocol['measured_start'],initial=True,source_navs=self.source_navs)

    def actions(self,row):
        from sentinel.feed import calendar
        day=row['session'];seen=set()
        for index,event in enumerate(row['ledger_today']):
            sid=event['security_id'];kind=event['event_type'];held=any(p.security_id==sid for p in self.account.positions.values())
            identifier=day+'/ACTION/'+str(index);context={'source_event':event}
            if kind=='SPLIT' and held and sid not in seen:
                seen.add(sid);self.apply(split(self.account,event_id=identifier,session=day,security_id=sid,
                    ratio=str(event['detail']['ratio']),canonical_split=self.canonical_split,raw_price=row['prices'][sid]['raw_open']),context)
            elif kind=='DIVIDEND_ACCRUED' and held:
                self.apply(accrue(self.account,event_id=identifier,session=day,claim_id=sid+'/'+day,security_id=sid,
                    cash_per_share=str(event['price']),pay_session=calendar.next_session(day)),context)
            elif kind=='DIVIDEND_PAID':
                key=sid+'/'+event['detail']['accrued_session']
                if key in self.account.claims:self.apply(pay(self.account,event_id=identifier,session=day,claim_id=key),context)
            elif held and kind not in ('BUY','SELL','SPLIT'):
                raise ValueError('REFUSED_ALPACA_FIT_FUNDED_UNSUPPORTED_ACTION:'+kind)

    def opening_inventory(self,row):
        expected=deepcopy(self.pending['held']);day=row['session']
        for key in self.pending['exits']:expected.pop(key,None)
        actual=inventory(row);episodes={episode_key(e):e for e in row['wealth_core']['episodes'].values()}
        for key,value in actual.items():
            if key in expected:continue
            episode=episodes[key]
            need(key in self.pending['opens'] and self.pending['opens'][key]['security_id']==value['security_id']
                 and episode['entry_date']==day and episode['signal_date']==self.pending['opens'][key]['origin_signal_session']
                 and episode['signal_date']<=self.pending['signal_session']<day
                 and any(e['event_type']=='BUY' and e['security_id']==value['security_id'] for e in row['ledger_today']),'FUNDED_CORE_OPENING_LINEAGE')
            expected[key]=value
        need({k:(v['security_id'],v['slot_id']) for k,v in expected.items()}==
             {k:(v['security_id'],v['slot_id']) for k,v in actual.items()},'FUNDED_CAUSAL_INVENTORY')
        for key in expected:expected[key]['ticker']=actual[key]['ticker']
        return expected

    def advance(self,row):
        from sentinel.feed import calendar
        hosted();day=row['session'];need(row['phase']=='MEASURED' and self.pending is not None,'FUNDED_PHASE_OR_ORIGIN')
        need(day==calendar.next_session(self.last)==self.pending['execution_session'],'FUNDED_NEXT_SESSION')
        gap,intraday=defensive_factors(row);prior=self.last_nav
        first=self.account is None
        if first:
            need(day==self.protocol['measured_start'],'FUNDED_ANCHOR_DATE')
            self.account=Account(source_sha256=self.model_sha256,cash=self.protocol['capital'])
        else:
            self.factor(day,'GAP',gap);self.actions(row)
        opened=mark(self.account,{p.security_id:row['prices'][p.security_id]['raw_open'] for p in self.account.positions.values()})
        live=self.opening_inventory(row)
        fills=self.fills({'row':row,'prices':row['prices']},live);self.held_global=self.pending['global_target']
        self.factor(day,'INTRADAY',intraday)
        marks={p.security_id:row['prices'][p.security_id]['raw_close'] for p in self.account.positions.values()}
        nav=mark(self.account,marks);need(nav>0,'FUNDED_NONPOSITIVE_NAV')
        target=row['owned55_profiles'][self.profile_id]['evidence']['target']
        self.pending=projection(row,nav=nav,target=target,held_target=self.held_global,execution_session=calendar.next_session(day),source_navs=self.source_navs)
        self.last=day;self.last_nav=nav
        self.last_row_sha256=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n').hexdigest()
        account_state=state(self.account);applied=account_state.pop('applied_events')
        return {'schema':'research.alpaca-owned55-funded-day/1','session':day,'profile_id':self.profile_id,
            'source_row_sha256':self.last_row_sha256,'dataset_sha256':self.dataset_sha256,'nav':str(nav),'previous_nav':str(prior),
            'net_factor':str(nav/prior),'opening_nav_before_fills':str(opened),'fills':fills,'marks':marks,'account':account_state,
            'applied_events_count':len(applied),'applied_events_sha256':hashlib.sha256(json.dumps(applied,separators=(',',':')).encode()).hexdigest(),
            'pending':self.pending,'held_target':self.held_global,'first_funded_open':first,
            'unfunded_first_overnight_skipped':first,'gap_factor':None if first else str(gap),'intraday_factor':str(intraday),
            'rounding_absolute_sum':str(self.rounding)}

    def checkpoint(self):
        hosted();need(self.pending is not None,'NO_FUNDED_ORIGIN')
        return {'schema':'research.alpaca-owned55-funded-runtime/1','model_sha256':self.model_sha256,
            'dataset_sha256':self.dataset_sha256,'profile_id':self.profile_id,'session':self.last,
            'account':None if self.account is None else snapshot(self.account),
            'pending':deepcopy(self.pending),'held_global':self.held_global,'last_nav':str(self.last_nav),
            'rounding_absolute_sum':str(self.rounding),'event_count':self.event_count,'origin_signal':self.origin_signal,
            'source_row_sha256':self.last_row_sha256}
