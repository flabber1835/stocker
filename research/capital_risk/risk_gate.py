"""Actual hosted integration of each new architecture before historical trials."""
from datetime import date,timedelta
from fractions import Fraction as Q
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path
import json
from holding_account import Account,Position,need
from risk_adapter import install
from risk_profiles import selected
from selective_journal import encode

def run(canonical,output):
    cases=[];days=[];day=date(2026,1,6)
    while len(days)<34:
        if day.weekday()<5:days.append(day.isoformat())
        day+=timedelta(days=1)
    key='2025-12-01/0'
    for name in ('L3_KEEP55','B04_C3','C15_C3'):
        p=selected(name);Runtime=install(p);source=sha256(name.encode()).hexdigest();r=Runtime(source,canonical,enabled=True)
        r.account=Account(source_sha256=source,cash='800',positions={key:Position(episode=key,security_id='S',ticker='S',shares='20')},last_session='2026-01-05')
        r.last='2026-01-05';r.last_nav=Q(1000);r.held_global='1';r.pending=dict(signal_session=r.last,execution_session=days[0],source_state_sha256='b'*64,source_input_sha256='c'*64,source_chain_sha256='d'*64,global_target='1',global_changed=False,held={key:dict(security_id='S',ticker='S',slot_id=0)},exits=[],opens={},targets={})
        fake=SimpleNamespace(last_formation_global='0',next_session={d:days[i+1] if i+1<len(days) else None for i,d in enumerate(days)})
        actual=[];cut=None
        for index,day in enumerate(days[:29] if p.family=='CONCENTRATION_BAND' else days[:8]):
            green=index>=(25 if p.family=='CONCENTRATION_BAND' else 4)
            price='1' if green and p.family=='CONCENTRATION_BAND' else '40' if p.family=='CONCENTRATION_BAND' and index>=22 else '13'
            obs=dict(ticker='S',age_sessions=10,own_dd=-.01 if green else -.25,r21=.1 if green else -.05,r63=None)
            row=dict(session=day,phase='MEASURED',state_sha256='b'*64,input_sha256='c'*64,chain_sha256='d'*64,economics=dict(pending_allocation='1',parent_core_close_equity='1000'),evidence=dict(research_entry_audit=dict(operations=[])),retry_diagnostics=dict(events=[]))
            frame=dict(row=row,holdings=[dict(episode=key,security_id='S',slot_id=0,shares='20',source_observation=obs)],prices={'S':dict(raw_open=price,raw_close=price)},source_events=[],cash=dict(gap_factor='1',intraday_factor='1'),price_chain_sha256='e'*64,identity_chain_sha256='f'*64)
            before=encode(frame);record,_=r.advance(frame,fake);need(encode(frame)==before,'SEARCH_GATE_FROZEN_FRAME_CHANGED');actual.append(record)
            if index==3:
                cut=r.account.positions.get(key);quantity=Q(0) if cut is None else cut.shares
                need(quantity<20 and record['finance']['fills'],'SEARCH_GATE_ACTUAL_FUNDED_REDUCTION')
                for fill in record['finance']['fills']:need(Q(fill['fees'])==Q(fill['filled_shares'])*Q(fill['raw_open'])/1000,'SEARCH_GATE_ACTUAL_FEE')
                cut=str(quantity)
            if p.family=='CONCENTRATION_BAND' and index==24:need(any(f['side']=='SELL' and Q(f['filled_shares'])>0 for f in record['finance']['fills']),'SEARCH_GATE_ACTUAL_21_CLOSE_REBALANCE')
        need(not r.policy.get('__book__',r.policy.get(key,{})).get('active',False),'SEARCH_GATE_ACTUAL_RECOVERY')
        cp=r.checkpoint();restored=Runtime(source,canonical,enabled=True,checkpoint=json.loads(json.dumps(cp)));need(restored.checkpoint()==cp,'SEARCH_GATE_EXACT_RUNTIME_RESTORE')
        try:Runtime('0'*64,canonical,enabled=True,checkpoint=cp)
        except ValueError:pass
        else:raise AssertionError('SEARCH_GATE_WRONG_PROFILE_SOURCE_ACCEPTED')
        cases.append(dict(profile=name,cut_shares=cut,records=actual,final=cp,source_frame_unchanged=True,wrong_source_restore_refused=True))
    result=dict(status='THREE_ARCHITECTURES_ACTUALLY_EXERCISED',historical_accounts_started=0,cases=cases,production_contacted=False)
    Path(output).write_bytes(encode(result)+b'\n');return result
