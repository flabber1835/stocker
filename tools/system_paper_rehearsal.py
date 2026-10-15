"""Attended real-component rehearsal over an authenticated copy of the book.

The allocated account value is a test purse, not the actual Alpaca account NAV.
Production activation authority and economic history are never modified.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import time

from sentinel import binding, dual_plan_authority
from sentinel import rolling_checkpoint as origin, rolling_daily_checkpoint as daily
from sentinel.authority import load_rollout_state
from sentinel.core.decision import build_execution_plan
from sentinel.execution import executor, journal
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.feed import calendar, rolling_go_inputs as inputs, store
from sentinel.strategy import production_strategy
from tools.live_paper_rehearsal import PAPER,Refused
from tools.native_paper_rehearsal import NativeRun


async def await_quotes(run,instruments,*,timeout=300):
    deadline=time.monotonic()+timeout
    while True:
        unavailable=[]
        for item in instruments.values():
            try:await run.quote(item.symbol)
            except Refused as exc:unavailable.append(str(exc))
        if not unavailable:return
        run.ledger.record('quote_preflight_wait',reasons=unavailable)
        if time.monotonic()>=deadline:
            raise Refused('basket quote preflight deadline; no new basket transport attempted')
        await asyncio.sleep(5)


async def prepare_system(run):
    """Read-only authenticated historical input, actual account, canonical sizing."""
    source=store.connect(os.environ['REHEARSAL_DATABASE_URL'],statement_timeout_ms=90000)
    try:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        checkpoint=daily.read(source) or origin.read(source)
        context=dict(observation_id=checkpoint.observation_id,starting_cash=checkpoint.starting_cash,
            controller=production_strategy()[0],strategy=checkpoint.strategy_identity,runtime=checkpoint.runtime_identity)
        checkpoint,_,result=daily.load(source,context,status_only=True)
        if result.state.state_hash!=checkpoint.state_sha256:
            raise Refused('authenticated book differs from checkpoint')
        original=journal.latest_plan(source)
        sizing=dual_plan_authority.load_authority(source,plan_id=original.plan_id)
        if sizing is None or sizing['shadow_record_sha256']!=result.record_sha256:
            raise Refused('retained sizing belongs to another canonical book')
        tickers={**sizing['tickers'],'SPY':'SPY','SENTINEL:BIL':'BIL'}
        reverse={symbol:sid for sid,symbol in tickers.items()}
        if len(reverse)!=len(tickers):raise Refused('test ticker mapping is ambiguous')
        run.allowed_symbols=set(tickers.values())
        broker=AssetIdAlpacaExecutionBroker(api_key=os.environ['ALPACA_API_KEY'],
            secret_key=os.environ['ALPACA_SECRET_KEY'],base_url=PAPER,http_provider=run.provider,
            resolve_security_id=lambda symbol:reverse[symbol])
        account=await broker.account_snapshot()
        observation=await broker.observe()
        observation.require_complete('attended system preparation')
        if observation.positions or observation.orders:
            raise Refused('system rehearsal must prepare from a flat settled account')
        if account.cash<run.maximum:raise Refused('actual account cash is below the test allocation')
        allocation=replace(account,equity=run.maximum,cash=run.maximum,buying_power=run.maximum)
        with run.connect() as conn:bound=binding.require(conn)
        pub=inputs.current(source)
        selected=build_execution_plan(result.state,bound,pub,allocation,observation,
            {sid:Decimal(value) for sid,value in sizing['marks'].items()},tickers,
            date.fromisoformat(checkpoint.session),date.fromisoformat(calendar.next_session(checkpoint.session)),
            rollout_state=load_rollout_state(source))
        if selected.plan.opening_intents:
            raise Refused('this retained-book campaign requires resolved whole-share targets')
        instruments={}
        for sid,qty in selected.plan.target_basket.items():
            if not qty:continue
            instrument=await broker.resolve_instrument(security_id=sid,symbol=selected.target_tickers[sid])
            if sid!='SENTINEL:BIL' and instrument.broker_id!=sid:
                raise Refused('native asset identity differs from canonical source identity')
            instruments[sid]=instrument
            run.asset_symbols[instrument.broker_id]=instrument.symbol
        run.allow_batch=True
        run.ledger.record('canonical_system_prepared',source_session=checkpoint.session,
            source_state_sha256=result.state.state_hash,source_record_sha256=result.record_sha256,
            publication_version=pub.version,allocated_account_value=str(run.maximum),
            actual_account_value=str(account.equity),plan_id=selected.plan.plan_id,
            targets=[dict(security_id=sid,ticker=selected.target_tickers.get(sid,sid),quantity=str(qty))
                     for sid,qty in selected.plan.target_basket.items()],
            production_authority=False)
        return broker,selected.plan,instruments,checkpoint.state_sha256
    finally:
        source.rollback()
        source.close()


async def main_async(args):
    run=NativeRun(output=args.output,account_sha256=args.account_sha256,
                  maximum=args.maximum_open_usd,resume=True)
    run.acquire_owner()
    run.production_fenced()
    saved=args.output/'system-plan.json'
    if saved.exists():
        value=json.loads(saved.read_text())
        if value['complete']:
            raise Refused('this basket campaign already completed; preserve its evidence')
        with run.connect() as conn:plan=journal.load_plan(conn,value['plan']['plan_id'])
        if plan is None or plan.fingerprint()!=value['plan_fingerprint'] or plan.deployment_id!=run.deployment_id:
            raise Refused('saved basket differs from its durable test identity')
        tickers=value['tickers']
        run.allowed_symbols=set(tickers.values())|{'SPY'}
        reverse={symbol:sid for sid,symbol in tickers.items()}
        reverse['SPY']='SPY'
        broker=AssetIdAlpacaExecutionBroker(api_key=os.environ['ALPACA_API_KEY'],
            secret_key=os.environ['ALPACA_SECRET_KEY'],base_url=PAPER,http_provider=run.provider,
            resolve_security_id=lambda symbol:reverse[symbol])
        instruments={}
        for sid,symbol in tickers.items():
            instrument=await broker.resolve_instrument(security_id=sid,symbol=symbol)
            instruments[sid]=instrument
            run.asset_symbols[instrument.broker_id]=symbol
        run.allow_batch=True
    else:
        broker,plan,instruments,state_hash=await prepare_system(run)
        if not args.execute_basket:
            return
        value=dict(plan=plan.to_dict(),plan_fingerprint=plan.fingerprint(),
                   tickers={sid:item.symbol for sid,item in instruments.items()},
                   source_state_sha256=state_hash,complete=False)
        saved.write_text(json.dumps(value,sort_keys=True))
        with saved.open('rb') as stream:os.fsync(stream.fileno())
    if not args.execute_basket and not args.flatten_basket:
        raise Refused('an unfinished saved campaign requires explicit execute or flatten')
    with run.connect() as conn:
        current=journal.latest_plan(conn)
        cleanup=replace(plan,plan_id=plan.plan_id+'-cleanup',target_exposure=Decimal(0),
                        target_basket={sid:Decimal(0) for sid in plan.target_basket},superseded_by=None)
        if current.plan_id not in {plan.plan_id,cleanup.plan_id}:
            if not current.plan_id.startswith(run.plan_id) or not current.plan_id.endswith('-cleanup'):
                raise Refused('another durable plan owns the test journal')
            executor.adopt_plan(conn,plan)
        if not args.flatten_basket and current.plan_id!=cleanup.plan_id:
            # Preflight all symbols before the first possible transport. Every
            # individual buy independently rechecks prices and the account cap.
            await await_quotes(run,instruments)
            guarded=run.guarded(broker,plan)
            await run.converge(guarded,conn,plan,instruments)
            before={c.client_key for c in journal.load_commands(conn,binding.require(conn).identity)}
            await run.converge(guarded,conn,plan,instruments)
            after={c.client_key for c in journal.load_commands(conn,binding.require(conn).identity)}
            if before!=after:raise Refused('repeated basket execution created another command')
            account,positions,orders,exposure=await run.snapshot()
            run.ledger.record('canonical_basket_filled',positions=len(positions),
                working_orders=len(orders),open_position_value=str(exposure),
                maximum_open_usd=str(run.maximum),repeat_new_commands=0)
        executor.adopt_plan(conn,cleanup)
        await run.converge(run.guarded(broker,cleanup),conn,cleanup,instruments)
        account,positions,orders,_=await run.snapshot()
        if positions or orders:raise Refused('system basket test effects remain')
        commands=journal.load_commands(conn,binding.require(conn).identity)
        expected=Decimal(run.saved['starting_cash'])+sum(
            ((Decimal(1) if c.side.value=='SELL' else Decimal(-1))*c.filled_quantity*c.filled_average_price
             for c in commands if c.filled_quantity),Decimal(0))
        if abs(expected-Decimal(account['cash']))>Decimal('0.02'):
            raise Refused('basket journal cash does not reconcile with Alpaca')
        value['complete']=True
        saved.write_text(json.dumps(value,sort_keys=True))
        with saved.open('rb') as stream:os.fsync(stream.fileno())
        run.ledger.record('canonical_basket_complete',positions=0,working_orders=0,
            commands=len(commands),expected_cash=str(expected),provider_cash=str(account['cash']),
            source_state_sha256=value['source_state_sha256'],production_authority=False,
            scheduler_qualification='STILL_REQUIRED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--account-sha256',required=True)
    parser.add_argument('--maximum-open-usd',type=Decimal,required=True)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--execute-basket',action='store_true')
    actions.add_argument('--flatten-basket',action='store_true')
    parser.add_argument('--confirm-owner-authorized-current-paper-account',action='store_true',required=True)
    args=parser.parse_args()
    import asyncio
    asyncio.run(main_async(args))


if __name__=='__main__':main()
