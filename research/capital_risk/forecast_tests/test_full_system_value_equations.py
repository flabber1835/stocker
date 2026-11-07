"""Synthetic allocation/accounting checks only; no historical replay."""
from decimal import Decimal as D
from pathlib import Path
import importlib.util,sys
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from full_system_controller_review import independent_factor,check_factor
from full_system_controller_vector import targets
from full_system_controller_policy import profiles

def test_overnight_exposure_is_old_holding_and_turnover_cost_is_charged():
    row={'economics':{'parent_core_open_equity':'110','parent_core_close_equity':'121',
        'bil_open_adjusted':'1','bil_close_adjusted':'1','bil_previous_close_adjusted_current_publication':'1'}}
    prior={'held_allocation':'1','pending_allocation':'0','parent_core_close_equity':'100'}
    actual=independent_factor(prior,row,[])
    assert actual=={'gross':D('1.1'),'net':D('1.0989'),'turnover':D('1'),'cost':D('.999')}
    bad={k:str(v) for k,v in actual.items()};bad['net']='1.099'
    with pytest.raises(ValueError,match='FACTOR_net'):check_factor(bad,actual)

def test_fresh_formed_entry_uses_actual_notional_and_removes_shadow_trade_fees():
    row={'economics':{'parent_core_open_equity':'100','parent_core_close_equity':'109.9',
        'bil_open_adjusted':'1','bil_close_adjusted':'1','bil_previous_close_adjusted_current_publication':'1',
        'formed_startup_marks':{'S':'10'}},'evidence':{'research_entry_audit':{
        'opening_accounting':{'ledger':{'event_count':0}},'closing_accounting':{'wealth_core':{'episodes':{'0':{'security_id':'S','current_shares':5}}},'ledger':{'event_count':1}}}}}
    events=[{'event_type':'BUY','fees':.1}]
    actual=independent_factor({'held_allocation':None,'pending_allocation':'1'},row,events)
    assert actual['gross']==D('1.1') and actual['turnover']==D('.5') and actual['net']==D('1.0995')

def test_independent_controller_extreme_immediate_risk_and_recovery_cases():
    healthy={'evidence':{'observation':dict(shadow_drawdown=0,shadow_r5=.01,shadow_r10=.01,shadow_r20=.05,shadow_r40=.01,
        damaged_breadth=0,green_breadth=1,damaged_breadth_delta5=0,spy_r20=.01,spy_vol_ratio=.01,stops20=0,shadow_nav=100),
        'recent_leadership':{'recent_r20':.01,'recent_r40':.01}}}
    damaged={'evidence':{'observation':dict(healthy['evidence']['observation'],shadow_drawdown=-.3,shadow_r5=-.2,shadow_r10=-.2,
        shadow_r20=-.2,shadow_r40=-.2,damaged_breadth=1,green_breadth=0,damaged_breadth_delta5=1,spy_r20=-.2,spy_vol_ratio=1),
        'recent_leadership':{'recent_r20':-.2,'recent_r40':-.2}}}
    import numpy as np
    with np.errstate(invalid='ignore'):
        assert (targets([healthy]*12,profiles())==1).all()
        values=targets([damaged]+[healthy]*20,profiles())
    assert (values[:,0]==0).all() and (values[:,-1]==1).all()

def test_stale_stop_receipt_refuses_before_any_worker_launch(tmp_path):
    from unittest.mock import patch
    import alpaca_fit_job as driver
    (tmp_path/'worker-inspect.json').write_text('{}')
    with patch.object(driver.subprocess,'run') as called:
        with pytest.raises(ValueError,match='STALE_WORKER_RECEIPT_BEFORE_LAUNCH'):
            driver.stopped_run(['synthetic-no-real-command'],'synthetic',tmp_path,1)
        called.assert_not_called()
    text=(HERE/'alpaca_fit_job.py').read_text()
    guard="    for filename in ('worker-inspect.json','worker.log'):\n        need(not (output/filename).exists(),'STALE_WORKER_RECEIPT_BEFORE_LAUNCH')"
    assert text.count(guard)==1
    broken=text.replace(guard,'    pass',1);ns={'__name__':'broken_receipt_guard'};exec(compile(broken,'broken-receipt-guard','exec'),ns)
    from types import SimpleNamespace
    with patch.object(driver.subprocess,'run',return_value=SimpleNamespace(stdout=b'a'*64)) as called:
        with pytest.raises(ns['StopUnknown']):ns['stopped_run'](['synthetic-no-real-command'],'synthetic',tmp_path,1)
        assert called.called
