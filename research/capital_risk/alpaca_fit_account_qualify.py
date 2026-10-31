"""Hosted component cases for the new funded origin and continuation only."""
from copy import deepcopy
from fractions import Fraction as Q
from alpaca_fit_inputs import hosted,need
from alpaca_fit_account import Runtime


def cases():
    hosted();profile='COMPONENT';model='a'*64;dataset='b'*64
    protocol={'capital':'5000','measured_start':'2025-01-02'}
    episode={'security_id':'A','ticker':'A','slot_id':0,'signal_date':'2024-12-02','entry_date':'2024-12-03','current_shares':2.}
    anchor={'phase':'FORMATION','session':'2024-12-31','shadow_nav':1000.,'state_sha256':'1'*64,'input_sha256':'2'*64,
        'wealth_core':{'episodes':{'0':episode}},'prices':{'A':{'raw_close':'50'}},
        'pending':[{'operation':'OPEN_SLOT_POSITION','security_id':'B','ticker':'B','slot_id':1,
                    'signal_session':'2024-12-31','intended_dollars':50.}],
        'owned55_profiles':{profile:{'evidence':{'target':.5}}}}
    first=deepcopy(anchor);first.update(phase='MEASURED',session='2025-01-02',pending=[],
        prices={'A':{'raw_open':'50','raw_close':'150'},'B':{'raw_open':'25','raw_close':'25'}},
        ledger_today=[{'event_type':'BUY','security_id':'B'}],
        defensive_bar={'open_signal':100.,'close_signal':101.,'close_adjusted':101.},
        defensive_previous_bar={'close_adjusted':50.})
    first['wealth_core']['episodes']['1']={'security_id':'B','ticker':'B','slot_id':1,'signal_date':'2024-12-31',
        'entry_date':'2025-01-02','current_shares':2.}
    runtime=Runtime(model_sha256=model,dataset_sha256=dataset,profile_id=profile,protocol=protocol)
    runtime.start(anchor);origin=runtime.checkpoint()
    clone=Runtime(model_sha256=model,dataset_sha256=dataset,profile_id=profile,protocol=protocol,checkpoint=origin)
    need(clone.checkpoint()==origin,'FUNDED_UNFUNDED_ORIGIN_ROUNDTRIP')
    one=runtime.advance(first)
    need(Q(one['nav'])==Q('5545.87125') and one['first_funded_open'] and one['gap_factor'] is None,
         'FUNDED_FIRST_OPEN_FEES_OR_UNFUNDED_GAP')
    need({k:Q(p['shares']) for k,p in one['account']['positions'].items()}=={'2024-12-02/0':Q(5),'2024-12-31/1':Q(5)},
         'FUNDED_WHOLE_QUANTITIES')
    cp=runtime.checkpoint();restored=Runtime(model_sha256=model,dataset_sha256=dataset,profile_id=profile,protocol=protocol,checkpoint=cp)
    second=deepcopy(first);second.update(session='2025-01-03',ledger_today=[],
        prices={'A':{'raw_open':'60','raw_close':'60'},'B':{'raw_open':'25','raw_close':'25'}},
        defensive_bar={'open_signal':105.,'close_signal':105.,'close_adjusted':105.},defensive_previous_bar={'close_adjusted':101.})
    a=runtime.advance(second);b=restored.advance(second)
    need(a==b and runtime.checkpoint()==restored.checkpoint(),'FUNDED_ACTUAL_CONTINUATION_ROUNDTRIP')
    need(Q(a['nav'])==Q('5280.85625') and not a['fills'],'FUNDED_GAP_INTRADAY_OR_STABLE_QUANTITIES')
    return {'schema':'research.alpaca-funded-component-qualification/1','status':'PASSED','cases':4,
        'new_origin_and_fees':True,'gap_intraday_separated':True,'whole_quantities_preserved':True,
        'unfunded_and_funded_serialized_continuation':True,'historical_performance_result':False}
