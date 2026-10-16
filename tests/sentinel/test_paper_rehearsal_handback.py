"""Handback cannot hide unmatched cash, unknown orders or surviving shares."""
from copy import deepcopy
from decimal import Decimal as D
from fractions import Fraction
from types import SimpleNamespace

import pytest

from tools import paper_rehearsal_handback as module
from tools.live_paper_rehearsal import Refused
import test_paper_activation as activation

pg, conn = activation.pg, activation.conn


def orders():
    return [dict(client_order_id='sntl-'+('a' if side=='buy' else 'b')*20,
        id=side+'-native',asset_id='native-class-asset',symbol='PBR.A',status='filled',
        side=side,qty='2',filled_qty='2',filled_avg_price=price)
        for side,price in [('buy','23.01'),('sell','23.02')]]


def test_handback_explains_actual_test_gain_without_a_cash_constant():
    native=orders()
    flow=module.qualify_orders(native,[o['client_order_id'] for o in native])
    assert flow==Fraction(2,100)
    assert module.explain_cash(plan_cash=D('50000'),starting_cash=D('49999.85'),
        current_cash=D('49999.87'),native_cash_flow=flow)==D('49999.87')


@pytest.mark.parametrize('damage',['foreign','duplicate','unknown','shares','price','fractional','missing'])
def test_handback_native_proof_rejects_incomplete_or_unsafe_evidence(damage):
    native=orders()
    keys=[o['client_order_id'] for o in native]
    if damage=='foreign':native[0]['client_order_id']='sntl-'+'c'*20
    elif damage=='duplicate':native[1]=deepcopy(native[0])
    elif damage=='unknown':native[0]['status']='pending_new'
    elif damage=='shares':native[0]['asset_id']='another-class'
    elif damage=='price':native[0]['filled_avg_price']='NaN'
    elif damage=='fractional':native[0].update(qty='1.5',filled_qty='1.5')
    elif damage=='missing':native.pop()
    with pytest.raises(Refused):module.qualify_orders(native,keys)


@pytest.mark.parametrize('before,after',[(D('49998'),D('49998.02')),(D('50000'),D('50002'))])
def test_handback_keeps_existing_cash_tolerance(before,after):
    with pytest.raises(Refused,match='unexplained'):
        module.explain_cash(plan_cash=D('50000'),starting_cash=before,
            current_cash=after,native_cash_flow=Fraction(2,100))


@pytest.mark.parametrize('enabled,killed,active,counts',[
    (True,True,False,(0,0)),(False,False,False,(0,0)),
    (False,True,True,(0,0)),(False,True,False,(1,0)),(False,True,False,(0,1)),
])
def test_handback_refuses_live_authority_or_any_production_history(monkeypatch,enabled,killed,active,counts):
    monkeypatch.setattr(module.automation_store,'load_control',lambda _:SimpleNamespace(enabled=enabled,kill_switch_engaged=killed))
    class Connection:
        def execute(self,sql):
            return SimpleNamespace(fetchone=lambda:(active,) if 'EXISTS' in sql else counts)
    with pytest.raises(Refused):module.require_local(Connection(),SimpleNamespace(expected_plan_id='unused'))


@pytest.mark.parametrize('fail_after_receipt',[False,True])
def test_handback_commits_receipt_and_retirement_atomically_preserving_book(
        conn,monkeypatch,tmp_path,fail_after_receipt):
    import asyncio, hashlib, json
    from dataclasses import replace
    from datetime import date,datetime,timezone,timedelta
    from sentinel import binding
    from sentinel.execution import journal
    from sentinel.execution.plan import ExecutionPlan
    bound=binding.bind(conn,deployment_id='handback-test',broker='alpaca',broker_account_id='paper')
    pending=ExecutionPlan('pending',date(2026,8,11),date(2026,8,12),D(1),
        target_basket={'security':D(1)},deployment_id=bound.deployment_id,broker=bound.broker,
        broker_account_id=bound.broker_account_id,takeover_epoch=bound.takeover_epoch,
        account_nav=D(50000),account_cash=D(50000))
    plan=replace(pending,plan_id='sentinel-'+pending.fingerprint())
    journal.adopt_current_plan(conn,plan)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES('preserved-book',%s,%s::jsonb)",
        (plan.decision_session,json.dumps({'kind':'immutable-test-book','value':42})))
    opened=datetime(2026,8,12,13,30,tzinfo=timezone.utc)
    conn.execute("INSERT INTO sentinel_automation_cycles(cycle_id,state,decision_session,effective_session,deployment_id,broker,broker_account_id,takeover_epoch,control_generation,certificate_sha256,rollout_mode,rollout_version,config_sha256,decision_close_at,prepare_at,execution_open_at,execute_at,execution_close_at,plan_id) VALUES(%s,'SUPERSEDED',%s,%s,%s,%s,%s,1,1,%s,'PINNED_1_00',1,%s,%s,%s,%s,%s,%s,%s)",
        ('test-cycle',plan.decision_session,plan.effective_session,bound.deployment_id,bound.broker,bound.broker_account_id,
         'a'*64,'b'*64,opened-timedelta(hours=17),opened-timedelta(hours=16),opened,opened+timedelta(minutes=1),opened+timedelta(hours=6),plan.plan_id))
    conn.commit()
    native=orders()
    account=dict(id='native-paper',account_number='paper',cash='50000.02',equity='50000.02',
        buying_power='50000.02',multiplier='1',status='ACTIVE',trading_blocked=False,account_blocked=False,trade_suspended_by_user=False)
    class Owner:
        def __init__(self,**kwargs):kwargs['output'].mkdir()
        def acquire_owner(self):pass
        def production_fenced(self):pass
        async def read(self,path,params=None):
            return deepcopy(account if path=='/v2/account' else [] if path=='/v2/positions' or params.get('status')=='open' else native)
    monkeypatch.setattr(module,'AttendedRun',Owner)
    monkeypatch.setenv('REHEARSAL_PRODUCTION_DATABASE_URL',conn.info.dsn)
    request=tmp_path/'request.json'
    request.write_text(json.dumps(dict(expected_plan_id=plan.plan_id,
        account_sha256=hashlib.sha256(b'paper').hexdigest(),since='2026-08-12T13:00:00+00:00',
        starting_cash='50000',approved_client_keys=[o['client_order_id'] for o in native],actor='owner',reason='authorized paper qualification')))
    args=SimpleNamespace(confirm_retire_unsent_plan=True,request=request,output=tmp_path/'output')
    if fail_after_receipt:
        def fail(*_):raise RuntimeError('injected retirement failure')
        monkeypatch.setattr(journal,'supersede_plan',fail)
        with pytest.raises(RuntimeError,match='injected retirement failure'):asyncio.run(module.handback(args))
    else:
        asyncio.run(module.handback(args))
    conn.rollback()
    assert conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name='preserved-book'").fetchone()[0]=={'kind':'immutable-test-book','value':42}
    receipts=conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE 'attended-paper-handback:v1:%%'").fetchall()
    assert len(receipts)==(0 if fail_after_receipt else 1)
    assert journal.load_plan(conn,plan.plan_id).target_basket==plan.target_basket
    assert (journal.latest_plan(conn) is not None)==fail_after_receipt
