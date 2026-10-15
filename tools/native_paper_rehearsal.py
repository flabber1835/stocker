"""Attended native-journal PAPER rehearsal. No production activation authority.

Requires a fresh, separate rehearsal execution database and paused production.
The owner-approved test boundary wraps the canonical executor body; production
incarnation, signed-release and next-open fences are not changed or certified.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import time

from sentinel import binding, schema
from sentinel.execution import executor, journal
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.guarded import (
    BrokerOperation, ExecutionBrokerGuard, GuardedExecutionBroker,
    AttendedPaperExecutionGrant, PreTransportAuthorityRefused)
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import store
from tools.live_paper_rehearsal import AttendedRun, PAPER, Refused


def require_open_native_run(output):
    if (output/'native-run-closed.json').exists():
        raise Refused('native test run is closed; preserve its evidence and use a fresh test journal')


class RehearsalAlpacaBroker(AssetIdAlpacaExecutionBroker):
    """Actual PAPER transport with explicitly intraday quote acquisition."""

    def __init__(self,run,*,resolve_security_id=None):
        self.run=run
        super().__init__(api_key=os.environ['ALPACA_API_KEY'],
            secret_key=os.environ['ALPACA_SECRET_KEY'],base_url=PAPER,
            http_provider=run.provider,resolve_security_id=resolve_security_id)

    async def opening_prices(self,*,session,instruments):
        import httpx
        from sentinel.execution.opening_prices import QUOTE_ENDPOINT,FEED,parse_quotes
        from sentinel.feed import calendar
        self.run.production_fenced()
        opened,closed=calendar.session_window(session)
        if not opened<=self._now()<closed:
            raise Refused('attended quotes require the actual regular session')
        if not instruments or len(instruments)>40:
            raise Refused('invalid attended quote request')
        symbols={sid:self._to_symbol(item.symbol) for sid,item in instruments.items()}
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.get(QUOTE_ENDPOINT,headers=self._headers(),
                params={'symbols':','.join(sorted(symbols.values())),'feed':FEED})
            response.raise_for_status()
            payload=response.json(parse_float=Decimal)
        return parse_quotes(payload,session=session,instruments=instruments,
            observed_at=self._now(),broker_symbols=symbols)


class NativeRun(AttendedRun):
    def __init__(self, *, output, account_sha256, maximum, resume=False, crash=False):
        require_open_native_run(output)
        manifest=output/'native-run.json'
        saved=json.loads(manifest.read_text()) if resume else None
        super().__init__(output=output,account_sha256=account_sha256,maximum=maximum,resume=resume)
        self.dsn=os.environ['REHEARSAL_EXECUTION_DATABASE_URL']
        if self.dsn==os.environ['REHEARSAL_PRODUCTION_DATABASE_URL']:
            raise Refused('test journal cannot use production database')
        if saved:
            if saved['account_sha256']!=account_sha256 or Decimal(saved['maximum'])!=maximum:
                raise Refused('resume account/budget differs from original run')
            self.run_id=saved['run_id']
        self.saved=saved
        self.manifest=manifest
        self.crash_after_accept=crash
        self._transport_ticket=None
        self.plan_id='attended-probe-'+self.run_id
        self.deployment_id='attended-paper-'+self.run_id
        self.assert_isolated_database()
        if saved:
            with self.connect() as conn:
                bound=binding.require(conn)
                if bound.deployment_id!=self.deployment_id:
                    raise Refused('resume journal belongs to another test run')
                self.keys.update(c.client_key for c in journal.load_commands(conn,bound.identity))
                self.ids.update(c.broker_order_id for c in journal.load_commands(conn,bound.identity)
                                if c.broker_order_id)

    def connect(self):
        return store.connect(self.dsn,connect_timeout=3,statement_timeout_ms=10000)

    def assert_isolated_database(self):
        with self.connect() as test:
            name, system=test.execute('SELECT current_database(),system_identifier::text FROM pg_control_system()').fetchone()
        with store.connect(os.environ['REHEARSAL_PRODUCTION_DATABASE_URL']) as production:
            original=production.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        if not name.startswith('rehearsal_execution') or system==original:
            raise Refused('test journal requires an isolated rehearsal PostgreSQL server')

    async def authorize_command(self, method, url, body):
        if method=='POST':
            with self.connect() as conn:
                bound=binding.require(conn)
                if bound.deployment_id!=self.deployment_id:
                    raise Refused('test command namespace differs')
                commands=journal.load_commands(conn,bound.identity)
                command=next((c for c in commands if c.client_key==body.get('client_order_id')),None)
                plan=journal.latest_plan(conn)
                if (command is None or command.state is not CommandState.SEND_PENDING or plan is None
                        or command.identity.plan_id!=plan.plan_id or command.instrument.broker_id!=body.get('symbol')
                        or command.side.value.lower()!=body.get('side')
                        or command.quantity!=Decimal(body.get('qty','NaN'))):
                    raise Refused('transport requires the exact durable current test command')
                self.keys.update(c.client_key for c in commands)
                self.quantities[command.client_key]=command.quantity
        await super().authorize(method,url,body)

    def _issue_transport_ticket(self,method,url,body):
        self._transport_ticket=((method,str(url),json.dumps(body,sort_keys=True)),time.monotonic()+2)

    async def authorize(self,method,url,body):
        ticket=getattr(self,'_transport_ticket',None)
        self._transport_ticket=None
        request=(method,str(url),json.dumps(body,sort_keys=True))
        if ticket is None or ticket[0]!=request or time.monotonic()>ticket[1]:
            raise Refused('native HTTP mutation requires a fresh exact single-use pre-transport ticket')

    def guarded(self,raw,plan):
        with self.connect() as conn:bound=binding.require(conn)
        from sentinel.feed import calendar
        opened, closed=calendar.session_window(plan.effective_session)
        now=datetime.now(timezone.utc)
        grant=AttendedPaperExecutionGrant(run_id=self.run_id,
            paper_account_id=bound.broker_account_id,plan_id=plan.plan_id,
            effective_session=plan.effective_session,
            not_before=max(opened,now-timedelta(seconds=1)),
            not_after=min(closed,now+timedelta(minutes=29)))
        async def before_read(*_):self.production_fenced()
        async def after_read(*_):self.production_fenced()
        async def before_mutation(_grant,operation):
            self._transport_ticket=None
            with self.connect() as conn:
                current=binding.require(conn)
                latest=journal.latest_plan(conn)
                if latest is None or latest.plan_id!=_grant.plan_id:
                    raise Refused('attended grant does not name the current durable plan')
                commands=journal.load_commands(conn,current.identity,
                    states=((CommandState.SEND_PENDING,) if operation is BrokerOperation.SUBMIT
                            else (CommandState.CANCEL_PENDING,)))
                if len(commands)!=1:
                    raise Refused('attended transport requires one exact pending native command')
                command=commands[0]
            if operation is BrokerOperation.SUBMIT:
                method,url='POST',PAPER+'/v2/orders'
                body=dict(symbol=command.instrument.broker_id,qty=str(command.quantity),
                    side=command.side.value.lower(),type='market',time_in_force='day',
                    client_order_id=command.client_key,order_class='simple',extended_hours=False)
            elif operation is BrokerOperation.CANCEL and command.broker_order_id:
                method,url,body='DELETE',PAPER+'/v2/orders/'+command.broker_order_id,{}
            else:raise Refused('unsupported attended native mutation')
            await self.authorize_command(method,url,body)
            self.production_fenced()
            self._issue_transport_ticket(method,url,body)
        return GuardedExecutionBroker(inner=raw,grant=grant,
            guard=ExecutionBrokerGuard(before_read,after_read,before_mutation))

    async def converge(self, broker, conn, plan, instrument):
        executor._assert_executable(plan)
        instruments=instrument if isinstance(instrument,dict) else {'SPY':instrument}
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            self.production_fenced()
            try:
                with journal.writer_lock(conn):
                    executor._assert_current_plan(conn,plan)
                    result=await executor._execute_session_locked(
                        broker=broker,conn=conn,deployment=binding.require(conn).identity,plan=plan,
                        instruments=instruments,today=plan.effective_session,actions=None,
                        target_projection=None,min_increment=Decimal(1),informational_current_book=True)
            except PreTransportAuthorityRefused as exc:
                self._transport_ticket=None
                self.ledger.record('native_pretransport_refusal',detail=str(exc),
                    production_authority=False)
                await asyncio.sleep(2)
                continue
            commands=journal.load_commands(conn,binding.require(conn).identity)
            self.keys.update(c.client_key for c in commands)
            self.ledger.record('native_executor',plan=plan.plan_id,state=result.runtime_state.value,
                detail=result.detail,refused=dict(result.refused),
                commands=[dict(key=c.client_key,state=c.state.value,side=c.side.value,
                               quantity=str(c.quantity),filled=str(c.filled_quantity),
                               price=str(c.filled_average_price)) for c in commands])
            if result.refused:
                raise Refused('native executor refused an attended command')
            if any(c.identity.plan_id==plan.plan_id and c.state in {CommandState.REJECTED,CommandState.CANCELLED}
                   for c in commands):
                raise Refused('native test command failed terminally')
            rec=result.reconciliation
            expected={k:v for k,v in plan.target_basket.items() if v}
            if (rec is not None and rec.transport_ready and not result.submitted
                    and rec.observation.positions_by_security()==expected
                    and not journal.in_flight_commands(conn,binding.require(conn).identity)):
                return commands
            await asyncio.sleep(2)
        raise Refused('native convergence deadline; preserve journal and resolve before new purchases')

    async def campaign(self):
        self.acquire_owner()
        self.production_fenced()
        account,positions,orders,_=await self.snapshot()
        self.account_id=str(account.get('account_number') or account['id'])
        if not self.saved and (positions or orders):
            raise Refused('new native rehearsal requires a flat account')
        broker=RehearsalAlpacaBroker(self)
        instrument=await broker.resolve_instrument(security_id='SPY',symbol='SPY')
        self.asset_id=instrument.broker_id
        conn=self.connect()
        try:
            if not self.saved:
                if conn.execute("SELECT to_regclass('sentinel_account_binding')").fetchone()[0]:
                    raise Refused('new native run requires a fresh test journal; never erase an existing one')
                conn.rollback()
                schema.ensure_schema(conn)
                bound=binding.bind(conn,deployment_id=self.deployment_id,broker='alpaca',
                                   broker_account_id=self.account_id,notes='Owner-authorized attended PAPER test only')
                day=datetime.now(timezone.utc).date()
                from sentinel.feed import calendar
                prior=calendar.previous_sessions(day,2)[-2]
                plan=ExecutionPlan(plan_id=self.plan_id,decision_session=datetime.fromisoformat(prior).date(),
                    effective_session=day,target_exposure=Decimal(1),target_basket={'SPY':Decimal(1)},
                    deployment_id=bound.deployment_id,broker=bound.broker,broker_account_id=bound.broker_account_id,
                    takeover_epoch=bound.takeover_epoch,account_nav=self.maximum,account_cash=self.maximum)
                executor.adopt_plan(conn,plan)
                value=dict(run_id=self.run_id,account_sha256=self.account_sha256,maximum=str(self.maximum),
                           starting_cash=str(account['cash']),production_authority=False,profile='ATTENDED_PAPER_TEST_ONLY')
                self.manifest.write_text(json.dumps(value,sort_keys=True))
                with self.manifest.open('rb') as stream:os.fsync(stream.fileno())
                self.saved=value
                denied=await executor.execute_session(broker=broker,conn=conn,deployment=bound.identity,
                    plan=plan,instruments={'SPY':instrument},today=plan.effective_session,
                    informational_current_book=True)
                if denied.submitted or journal.load_commands(conn,bound.identity):
                    raise Refused('production incarnation fence unexpectedly permitted the test database')
                if not denied.deferred:
                    raise Refused('production incarnation fence was not exercised')
                self.ledger.record('production_entrypoint_expected_refusal',detail=denied.detail,
                    production_authority=False,transported=0)
            else:
                bound=binding.require(conn)
                if bound.deployment_id!=self.deployment_id:
                    raise Refused('resume journal belongs to another test run')
                commands=journal.load_commands(conn,bound.identity)
                self.keys.update(c.client_key for c in commands)
                plan=journal.latest_plan(conn)
                self.ledger.record('native_restart',commands=[dict(key=c.client_key,state=c.state.value) for c in commands])
            raw=broker
            broker=self.guarded(raw,plan)
            commands=await self.converge(broker,conn,plan,instrument)
            if not plan.plan_id.endswith('-cleanup'):
                if len(commands)!=1 or commands[0].state is not CommandState.FILLED:
                    raise Refused('buy restart created unexpected command count/state')
                await self.converge(broker,conn,plan,instrument)
                self.ledger.record('scenario_pass',scenario='native_send_pending_restart_exact_key_no_duplicate')
                cleanup=replace(plan,plan_id=self.plan_id+'-cleanup',target_basket={'SPY':Decimal(0)},target_exposure=Decimal(0))
                executor.adopt_plan(conn,cleanup)
                await self.converge(self.guarded(raw,cleanup),conn,cleanup,instrument)
            account,positions,orders,_=await self.snapshot()
            if positions or orders:raise Refused('native test effects remain')
            commands=journal.load_commands(conn,bound.identity)
            expected=Decimal(self.saved['starting_cash'])+sum(
                ((Decimal(1) if c.side.value=='SELL' else Decimal(-1))*c.filled_quantity*c.filled_average_price
                 for c in commands if c.filled_quantity),Decimal(0))
            if abs(expected-Decimal(account['cash']))>Decimal('0.02'):
                raise Refused('native fill cash does not reconcile with provider cash')
            self.ledger.record('native_rehearsal_complete',positions=0,working_orders=0,
                commands=len(commands),expected_cash=str(expected),provider_cash=str(account['cash']),
                production_authority=False,full_system_qualification='STILL_REQUIRED')
        finally:
            conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--account-sha256',required=True)
    parser.add_argument('--maximum-open-usd',type=Decimal,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--crash-after-first-accept',action='store_true')
    parser.add_argument('--confirm-owner-authorized-current-paper-account',action='store_true',required=True)
    args=parser.parse_args()
    asyncio.run(NativeRun(output=args.output,account_sha256=args.account_sha256,maximum=args.maximum_open_usd,
                         resume=args.resume,crash=args.crash_after_first_accept).campaign())


if __name__=='__main__':main()
