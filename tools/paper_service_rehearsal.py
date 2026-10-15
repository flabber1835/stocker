"""Owner-authorized intraday PAPER service campaign; never production admission."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import hashlib
import json
import os
import uuid
from pathlib import Path

from sentinel import binding,schema
from sentinel.automation import schedule,store as automation_store
from sentinel.automation.model import (
    AutomationConfig,ControlBinding,CycleState,ExecuteDisposition,ExecuteResult,
    PrepareResult,RefreshResult,SessionSchedule,TransientInfrastructureFailure)
from sentinel.automation.service import AutomationService
from sentinel.execution import executor,journal,reconcile
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.guarded import PreTransportAuthorityRefused
from sentinel.execution.states import CommandState
from tools.live_paper_rehearsal import Refused
from tools.native_paper_rehearsal import NativeRun,RehearsalAlpacaBroker
from tools.system_paper_rehearsal import prepare_system


def durable_json(path,value):
    path.write_text(json.dumps(value,sort_keys=True,default=str))
    with path.open('rb') as stream:os.fsync(stream.fileno())


class AttendedService(AutomationService):
    def __init__(self,*,slot,**kwargs):
        self.slot=slot
        super().__init__(**kwargs)

    def _schedule(self,now):
        if now.date()!=self.slot.effective_session:
            raise Refused('attended service slot belongs to another actual session')
        return self.slot


class ServiceCampaign:
    def __init__(self,run,slot,config,*,crash=False):
        self.run,self.slot,self.config=run,slot,config
        self.stop=asyncio.Event()
        self.path=run.ledger.root/'service-plan.json'
        self.value=json.loads(self.path.read_text()) if self.path.exists() else None
        self.plan=None
        self.instruments={}
        self.broker=RehearsalAlpacaBroker(run,resolve_security_id=self.resolve)
        run.crash_after_accept=crash
        self.load_durable_plan()

    def load_durable_plan(self):
        if self.path.exists():
            self.value=json.loads(self.path.read_text())
            with self.run.connect() as conn:
                self.plan=journal.load_plan(conn,self.value['plan']['plan_id'])
            if (self.plan is None or self.plan.deployment_id!=self.run.deployment_id
                    or self.plan.fingerprint()!=self.value['plan']['fingerprint']):
                raise Refused('saved service plan differs from its durable test authority')
            self.instruments={sid:BrokerInstrument(**item) for sid,item in self.value['instruments'].items()}
            self.run.allowed_symbols={item.symbol for item in self.instruments.values()}|{'SPY'}
            self.run.asset_symbols={item.broker_id:item.symbol for item in self.instruments.values()}
            self.run.allow_batch=True

    def resolve(self,symbol):
        if symbol=='SPY':return symbol
        matches=[sid for sid,item in self.instruments.items() if item.symbol==symbol]
        if len(matches)!=1:raise Refused('unattributed service instrument')
        return matches[0]

    async def refresh(self,context):
        context.require_active();self.run.production_fenced()
        # Preparation authenticates the retained publication and full book.
        # No current-session close is invented while the market is open.
        return RefreshResult(already_published=True,
            diagnostic={'profile':'ATTENDED_RETAINED_BOOK','production_authority':False})

    async def prepare(self,context):
        context.require_active();self.run.production_fenced()
        self.load_durable_plan()
        if self.plan is None:
            self.broker,self.plan,self.instruments,state=await prepare_system(self.run)
            self.value=dict(plan=self.plan.to_dict(),source_state_sha256=state,
                instruments={sid:dict(security_id=item.security_id,symbol=item.symbol,broker_id=item.broker_id)
                             for sid,item in self.instruments.items()})
        with self.run.connect() as conn:
            executor.adopt_plan(conn,self.plan)
        durable_json(self.path,self.value)
        return PrepareResult(plan_id=self.plan.plan_id,
            state_fingerprint=self.value['source_state_sha256'],plan_fingerprint=self.plan.fingerprint(),
            diagnostic={'profile':'ATTENDED_PAPER_TEST_ONLY','production_authority':False})

    async def recover(self,context):
        context.require_active();self.run.production_fenced()
        self.load_durable_plan()
        if context.cycle.plan_id and (self.plan is None or self.plan.plan_id!=context.cycle.plan_id):
            raise Refused('post-prepare recovery requires the exact durable service plan')
        with self.run.connect() as conn:
            bound=binding.require(conn)
            broker=self.run.guarded(self.broker,self.plan) if self.plan else self.broker
            with journal.writer_lock(conn,recovery_only=True):
                result=await reconcile.reconcile(broker=broker,conn=conn,binding=bound,
                    deployment=bound.identity,informational_current_book=True)
            if not result.transport_ready or result.observation is None:
                return ExecuteResult(disposition=ExecuteDisposition.RECONCILE,
                    failure_detail=result.detail,diagnostic=result.to_dict())
            commands=journal.in_flight_commands(conn,bound.identity)
            if commands:
                return ExecuteResult(disposition=ExecuteDisposition.RECONCILE,
                    diagnostic=result.to_dict())
            expected={sid:qty for sid,qty in self.plan.target_basket.items() if qty} if self.plan else {}
            complete=result.observation.positions_by_security()==expected
            return ExecuteResult(disposition=(ExecuteDisposition.SUCCEEDED if complete else ExecuteDisposition.READY_TO_EXECUTE),
                last_clean_reconciliation_id=str(result.observation_id),diagnostic=result.to_dict())

    async def execute(self,context):
        context.require_active();self.run.production_fenced()
        self.load_durable_plan()
        if self.plan is None or context.cycle.plan_id!=self.plan.plan_id:
            raise Refused('service cycle differs from its canonical test plan')
        busy=self.run.ledger.root/'writer-contention.json'
        holder=None
        if not busy.exists():
            # Actual independent PostgreSQL session holds the exact writer key.
            # The ordinary executor boundary must refuse before any command.
            holder=self.run.connect()
            holder.execute('SELECT pg_advisory_lock(%s)',(journal.WRITER_LOCK_KEY,));holder.commit()
            durable_json(busy,{'introduced_at':datetime.now(timezone.utc).isoformat()})
        try:
            with self.run.connect() as conn:
                with journal.writer_lock(conn):
                    executor._assert_executable(self.plan)
                    executor._assert_current_plan(conn,self.plan)
                    result=await executor._execute_session_locked(broker=self.run.guarded(self.broker,self.plan),
                        conn=conn,deployment=binding.require(conn).identity,plan=self.plan,
                        instruments=self.instruments,today=datetime.now(timezone.utc).date(),actions=None,
                        target_projection=None,min_increment=Decimal(1),informational_current_book=True)
                rec=result.reconciliation
                self.run.ledger.record('service_executor',state=result.runtime_state.value,
                    submitted=[c.client_key for c in result.submitted],refused=dict(result.refused),detail=result.detail)
                if result.refused:raise Refused('service executor refused fixed plan economics')
                if rec is None or rec.observation is None:
                    return ExecuteResult(disposition=ExecuteDisposition.RECONCILE)
                expected={sid:qty for sid,qty in self.plan.target_basket.items() if qty}
                settled=(rec.transport_ready and not result.submitted
                    and rec.observation.positions_by_security()==expected
                    and not journal.in_flight_commands(conn,binding.require(conn).identity))
                return ExecuteResult(disposition=(ExecuteDisposition.SUCCEEDED if settled else ExecuteDisposition.RECONCILE),
                    last_clean_reconciliation_id=str(rec.observation_id) if settled else None,
                    diagnostic=rec.to_dict())
        except (journal.WriterLockUnavailable,PreTransportAuthorityRefused) as exc:
            self.run.ledger.record('service_pretransport_refusal',detail=str(exc),
                commands_created=0 if holder is not None else None)
            raise TransientInfrastructureFailure(str(exc)) from exc
        finally:
            if holder is not None:
                holder.execute('SELECT pg_advisory_unlock(%s)',(journal.WRITER_LOCK_KEY,));holder.commit();holder.close()

    async def notify(self,conn,result):
        from sentinel.automation_runtime import ProductionAutomation
        await ProductionAutomation.notify(self,conn,result)
        self.run.ledger.record('service_notification_enqueued',action=getattr(getattr(result,'action',None),'value',None))

    async def terminal(self,conn,result):
        self.run.ledger.record('service_terminal',state=result.cycle.state.value,reason=result.reason)
        self.stop.set()

    async def run_service(self):
        service=AttendedService(slot=self.slot,config=self.config,holder_id='attended-'+self.run.run_id+'-'+uuid.uuid4().hex[:8],
            refresh=self.refresh,prepare=self.prepare,recover=self.recover,execute=self.execute,
            notify=self.notify,terminal=self.terminal)
        await service.run(self.run.connect,stop=self.stop,max_ticks=1200,
            clock=lambda:datetime.now(timezone.utc))
        with self.run.connect() as conn:
            cycle=automation_store.latest_cycle(conn)
            if cycle is None or cycle.state is not CycleState.SUCCEEDED:
                raise Refused('attended automation service did not succeed')
        self.load_durable_plan()
        if self.plan is None:raise Refused('terminal service is missing its canonical plan')
        # A later tick must observe the durable terminal cycle without
        # executing the same plan again.
        with self.run.connect() as conn:
            before=len(journal.load_commands(conn,binding.require(conn).identity))
            repeat=await service.tick(conn,now=datetime.now(timezone.utc),
                heartbeat_conn_factory=self.run.connect,clock=lambda:datetime.now(timezone.utc))
            after=len(journal.load_commands(conn,binding.require(conn).identity))
            if repeat.cycle.state is not CycleState.SUCCEEDED or before!=after:
                raise Refused('terminal service replay created new execution')
        self.run.ledger.record('service_cycle_pass',commands=after,repeat_new_commands=0,
            production_authority=False)
        await self.cleanup()

    async def cleanup(self):
        if self.plan is None:raise Refused('cleanup requires the saved native test plan')
        cleanup=replace(self.plan,plan_id=self.plan.plan_id+'-cleanup',target_exposure=Decimal(0),
            target_basket={sid:Decimal(0) for sid in self.plan.target_basket},superseded_by=None)
        with self.run.connect() as conn:
            executor.adopt_plan(conn,cleanup)
            await self.run.converge(self.run.guarded(self.broker,cleanup),conn,cleanup,self.instruments)
            commands=journal.load_commands(conn,binding.require(conn).identity)
        account,positions,orders,_=await self.run.snapshot()
        expected=Decimal(self.run.saved['starting_cash'])+sum(
            ((Decimal(1) if c.side.value=='SELL' else Decimal(-1))*c.filled_quantity*c.filled_average_price
             for c in commands if c.filled_quantity),Decimal(0))
        if positions or orders or abs(expected-Decimal(account['cash']))>Decimal('0.02'):
            raise Refused('service cleanup/fill cash did not reconcile')
        self.run.ledger.record('service_campaign_complete',positions=0,working_orders=0,
            commands=len(commands),expected_cash=str(expected),provider_cash=str(account['cash']),
            production_authority=False)


async def main_async(args):
    run=NativeRun(output=args.output,account_sha256=args.account_sha256,
        maximum=args.maximum_open_usd,resume=args.resume)
    run.acquire_owner();run.production_fenced()
    config=AutomationConfig(lease_seconds=30,heartbeat_seconds=3,callback_deadline_seconds=600,
        retry_base_seconds=2,retry_max_seconds=10,execute_max_attempts=80,recover_max_attempts=80)
    slot_path=args.output/'service-slot.json'
    if args.resume:
        slot=SessionSchedule.model_validate_json(slot_path.read_text())
        # Wait for the dead process's real PostgreSQL lease to expire. Never
        # rewrite or steal it to make a restarted service appear to recover.
        while True:
            run.production_fenced()
            with run.connect() as conn:
                row=conn.execute('SELECT expires_at,clock_timestamp() FROM sentinel_automation_lease WHERE id=1').fetchone()
            if row is None or row[0] is None or row[0]<=row[1]:break
            await asyncio.sleep(min(5,(row[0]-row[1]).total_seconds()+0.05))
    else:
        account,positions,orders,_=await run.snapshot()
        if positions or orders:raise Refused('new service campaign requires a flat paper account')
        run.account_id=str(account.get('account_number') or account['id'])
        now=datetime.now(timezone.utc)
        ordinary=schedule.for_clock(now,config)
        if (ordinary.execution_close_at-now).total_seconds()<=1200:
            raise Refused('new service campaign requires twenty minutes before the actual close')
        slot=ordinary.model_copy(update={'execution_open_at':now+timedelta(minutes=5),
            'execute_at':now+timedelta(minutes=5,seconds=1)})
        # Revalidate ordering; the actual XNYS close remains unchanged.
        slot=SessionSchedule.model_validate(slot.model_dump())
        durable_json(slot_path,slot.model_dump(mode='json'))
        with run.connect() as conn:
            if conn.execute("SELECT to_regclass('sentinel_account_binding')").fetchone()[0]:
                raise Refused('new service campaign requires a fresh isolated journal')
            conn.rollback();schema.ensure_schema(conn)
            bound=binding.bind(conn,deployment_id=run.deployment_id,broker='alpaca',
                broker_account_id=run.account_id,notes='ATTENDED PAPER TEST ONLY; no production certification')
            # This digest is only the unsigned test profile's structural ID.
            # No signed certificate is created or admitted by this campaign.
            profile=hashlib.sha256(('UNSIGNED_ATTENDED_PAPER:'+run.run_id).encode()).hexdigest()
            control=ControlBinding(deployment_id=bound.deployment_id,broker=bound.broker,
                broker_account_id=bound.broker_account_id,takeover_epoch=bound.takeover_epoch,
                certificate_sha256=profile,rollout_mode='PINNED_1_00',rollout_version=1,
                config_sha256=config.fingerprint)
            automation_store.activate(conn,binding=control,actor='attended-rehearsal',reason='owner-approved isolated PAPER test')
            automation_store.release_kill(conn,expected_binding=control,actor='attended-rehearsal',reason='isolated test only')
        run.saved=dict(run_id=run.run_id,account_sha256=run.account_sha256,maximum=str(run.maximum),
            starting_cash=str(account['cash']),production_authority=False,profile='ATTENDED_PAPER_TEST_ONLY')
        durable_json(run.manifest,run.saved)
    campaign=ServiceCampaign(run,slot,config,crash=args.crash_after_first_accept)
    if args.cleanup:
        if not args.resume:raise Refused('cleanup requires explicit resume of the existing campaign')
        await campaign.cleanup()
    else:await campaign.run_service()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--account-sha256',required=True)
    parser.add_argument('--maximum-open-usd',type=Decimal,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--crash-after-first-accept',action='store_true')
    parser.add_argument('--cleanup',action='store_true')
    parser.add_argument('--confirm-owner-authorized-current-paper-account',action='store_true',required=True)
    asyncio.run(main_async(parser.parse_args()))


if __name__=='__main__':main()
