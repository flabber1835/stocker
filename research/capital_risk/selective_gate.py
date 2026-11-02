"""Actual composed-account gates, hosted before historical financial paths."""
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace,ModuleType
import sys,json
from holding_account import Account,Position,state,snapshot,need
from selective_model import Runtime
from selective_journal import encode

def run(canonical,output):
    source='a'*64;day='2026-01-06';prior='2026-01-05'
    b=dict(episode='2025-12-01/0',security_id='S',slot_id=0,shares='20',source_observation=dict(ticker='S',age_sessions=10,own_dd=-.25,r21=-.05,r63=None))
    row=dict(session=day,phase='MEASURED',state_sha256='b'*64,input_sha256='c'*64,chain_sha256='d'*64,
        economics=dict(pending_allocation='1',parent_core_close_equity='1000'),
        evidence=dict(research_entry_audit=dict(operations=[])),retry_diagnostics=dict(events=[]))
    frame=dict(row=row,holdings=[b],prices={'S':dict(raw_open='12',raw_close='13')},
        source_events=[],cash=dict(gap_factor='1.01',intraday_factor='1.001'),price_chain_sha256='e'*64,identity_chain_sha256='f'*64)
    def runtime(enabled=None,cash='800',shares='20',targets=None,exits=None):
        r=Runtime(source,canonical,enabled=enabled);r.account=Account(source_sha256=source,cash=cash,
            positions={'2025-12-01/0':Position(episode='2025-12-01/0',security_id='S',ticker='S',shares=shares)},last_session=prior)
        r.last=prior;r.last_nav=Q(cash)+Q(shares)*10;r.held_global='1'
        r.pending=dict(signal_session=prior,execution_session=day,source_state_sha256='b'*64,source_input_sha256='c'*64,source_chain_sha256='d'*64,
            global_target='1',global_changed=False,held={'2025-12-01/0':dict(security_id='S',ticker='S',slot_id=0)},
            exits=exits or [],opens={},targets=targets or {})
        return r
    fake=SimpleNamespace(last_formation_global='0',next_session={day:'2026-01-07'});cases=[]
    before=encode(frame);left=runtime();right=runtime(False)
    a,_=left.advance(frame,fake);b0,_=right.advance(frame,fake)
    need(a['finance']==b0['finance'] and left.account.positions['2025-12-01/0'].shares==20,'COMPOSED_DISABLED_EQUALITY')
    need(Q(a['finance']['opening_nav_before_fills'])==1048 and Q(a['finance']['nav'])==Q('1068.808'),'OLD_HOLDINGS_OWN_GAP')
    need(encode(frame)==before,'SOURCE_CORE_MUTATED')
    cases.append(dict(case='disabled_equal_old_gap_persistent_quantity',before_cash='800',before_shares='20',result=a['finance']))
    targets={'2025-12-01/0':dict(dollars='110',neutral_dollars='200',cause='LOCAL_ENTER',local_active=True)}
    reduced=runtime(True,targets=targets);reduced.policy={'2025-12-01/0':dict(active=True,entry=0,recovery=0)};actual,_=reduced.advance(frame,fake)
    need(reduced.account.positions['2025-12-01/0'].shares==9 and reduced.account.cash==Q('940.807868'),'COMPOSED_SELECTIVE_TRIM_CASH_FEES')
    cases.append(dict(case='local_trim_after_old_gap',result=actual['finance']))
    recovered=runtime(True,cash='20',shares='9',targets={'2025-12-01/0':dict(dollars='200',neutral_dollars='200',cause='LOCAL_RECOVER',local_active=False)})
    rec,_=recovered.advance(frame,fake)
    need(rec['finance']['fills'][0]['filled_shares']=='1' and recovered.account.positions['2025-12-01/0'].shares==10,'COMPOSED_POSITIVE_CASH_CLIP')
    cases.append(dict(case='local_recovery_cash_clipped',result=rec['finance']))
    checkpoint=left.checkpoint();restored=Runtime(source,canonical,enabled=None,checkpoint=json.loads(json.dumps(checkpoint)))
    need(restored.checkpoint()==checkpoint,'COMPOSED_RUNTIME_ROUNDTRIP')
    try:Runtime(source,canonical,enabled=True,checkpoint=checkpoint)
    except ValueError:pass
    else:raise AssertionError('CROSS_MODE_RESTORE_ACCEPTED')
    cases.append(dict(case='complete_runtime_roundtrip_and_cross_mode_refusal',state=checkpoint))
    # Removing the actual adjacency guard must admit a duplicated cash-return session.
    import selective_model as module
    text=Path(module.__file__).read_text();guard="need(self.last<day and self.pending['signal_session']==self.last and self.pending['execution_session']==day,'REFUSED_P2_NEXT_SESSION')"
    broken=text.replace(guard,"need(True,'REFUSED_P2_NEXT_SESSION')");need(broken!=text,'COMPOSED_GUARD_REMOVAL_MATCH')
    mutant=ModuleType('selective_removed_adjacency');sys.modules[mutant.__name__]=mutant
    exec(compile(broken,'removed-selective-adjacency','exec'),mutant.__dict__)
    original=runtime();original.last=day
    try:original.advance(frame,fake)
    except ValueError:pass
    else:raise AssertionError('SAME_CLOSE_SESSION_ACCEPTED')
    removed=mutant.Runtime(source,canonical,enabled=None)
    seed=runtime();removed.__dict__.update(seed.__dict__);removed.last=day
    removed.advance(frame,fake)
    cases.append(dict(case='actual_adjacency_guard_removal',original_refused=True,removed_guard_accepted=True))
    result=dict(status='COMPOSED_H0_P2_GATE_PASSED',cases=cases,production_contacted=False)
    Path(output).write_bytes(encode(result)+b'\n');return result
