"""Attended PAPER gateway qualification; explicit unsigned authority fixtures.

Production callbacks and paper decision bodies are used unchanged. This process
cannot qualify a signed release: its reviewed substitutions are the owner test
grant/signature boundary, retained source-runtime context, a $5,000 purse and
intraday quotes/schedule. Every mutation still needs NativeRun's exact durable
command, exclusive owner, current production fence and cash/exposure envelope.
"""
import argparse, asyncio, hashlib, json, os
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sentinel import binding, rolling_checkpoint as origin, rolling_daily_checkpoint as daily
from sentinel import rolling_initialization as initial, automation_runtime
from sentinel.authority import load_rollout_state
from sentinel.automation import schedule, store as automation_store
from sentinel.automation.model import AutomationConfig, ControlBinding, SessionSchedule
from sentinel.config import SentinelConfig
from sentinel.execution import certification, journal
from sentinel.execution import alpaca
from sentinel.execution.guarded import ExecutionBrokerGuard, GuardedExecutionBroker, PaperPreparationGrant
from sentinel.paper import preparation, execution, recovery, validation
from sentinel.strategy import production_strategy
from tools.live_paper_rehearsal import Refused
from tools.native_paper_rehearsal import NativeRun
from tools.paper_service_rehearsal import ServiceCampaign, durable_json
from tools.system_paper_rehearsal import AttendedQuoteBroker


class GatewayCampaign(automation_runtime.ProductionAutomation, ServiceCampaign):
    def __init__(self, run, slot, config, retained, reserve):
        self.run, self.slot, self.config = run, slot, config
        self.automation_config = config
        self.sentinel_config = replace(SentinelConfig.from_env(), database_url=run.dsn)
        self.holder_id = 'attended-gateway-'+run.run_id
        self._dual_run_enabled, self._operational_source_only = True, True
        self._shadow_observation_enabled = False
        self._shadow_observation_id = retained.observation_id
        self._shadow_starting_cash = retained.starting_cash
        self.reserve = reserve
        self.stop = asyncio.Event()
        self.path = run.ledger.root/'service-plan.json'
        self.plan, self.value, self.instruments = None, None, {}
        self.broker = None

    def _broker(self, conn, session):
        raw = automation_runtime.ProductionAutomation._broker(self, conn, session)
        raw._http_provider = self.run.provider
        return raw

    def _assert_control_authority(self, conn, permit):
        # The signature itself is a named test fixture. Local lease/control and
        # cancellation remain real; this method never creates a certificate.
        self.run.production_fenced()
        automation_store.require_leader(conn, permit)
        control = automation_store.load_control(conn)
        if not control.enabled or control.kill_switch_engaged or control.binding is None:
            raise Refused('isolated gateway control is fenced')
        return control, self.certificate

    def _record_authority_verdict(self,conn,permit,*,verdict,detail):
        return super()._record_authority_verdict(conn,permit,verdict=verdict,
            detail='UNSIGNED ATTENDED FIXTURE; '+detail)

    async def refresh(self, context):
        return await ServiceCampaign.refresh(self, context)

    async def prepare(self, context):
        result = await automation_runtime.ProductionAutomation.prepare(self, context)
        with self.run.connect() as conn:
            self.plan = journal.load_plan(conn, result.plan_id)
            proof = __import__('sentinel.dual_plan_authority', fromlist=['load_authority']).load_authority(conn, plan_id=result.plan_id)
            self.broker = self._broker(conn, self.slot.effective_session.isoformat())
            for sid, quantity in self.plan.target_basket.items():
                if not quantity:
                    continue
                instrument = await self.broker.resolve_instrument(security_id=sid, symbol=proof['tickers'][sid])
                self.instruments[sid] = instrument
        self.run.allowed_symbols = {item.symbol for item in self.instruments.values()}
        self.run.asset_symbols = {item.broker_id:item.symbol for item in self.instruments.values()}
        self.run.allow_batch = True
        self.value = dict(plan=self.plan.to_dict(), source_state_sha256=result.state_fingerprint,
            instruments={sid:dict(security_id=sid,symbol=item.symbol,broker_id=item.broker_id) for sid,item in self.instruments.items()})
        durable_json(self.path,self.value)
        self.run.ledger.record('full_production_prepare_pass',plan_id=result.plan_id,targets=len(self.instruments))
        return result

    def load_durable_plan(self):
        ServiceCampaign.load_durable_plan(self)

    async def cleanup(self):
        self.load_durable_plan()
        if self.path.exists() and self.broker is None:
            with self.run.connect() as source:
                source.execute('SET TRANSACTION READ ONLY')
                self.broker = self._broker(source,self.slot.effective_session.isoformat())
        await ServiceCampaign.cleanup(self)

    def fixture_guard(self, *, conn, broker, grant, **kwargs):
        certification.require_certified_adapter(broker,expected='alpaca')
        broker = AttendedQuoteBroker(broker,self.run,reserve=self.reserve)
        def validate():
            self.run.production_fenced()
            with self.run.connect() as fresh:
                validation._validate_automation_grant(fresh,grant)
        async def before(*_): validate()
        async def after(*_): validate()
        if grant.operation_scope == 'EXECUTE':
            plan = journal.latest_plan(conn)
            end = min(self.slot.execution_close_at,self.slot.execute_at+timedelta(seconds=self.config.maximum_execution_lateness_seconds))
            attended = self.run.guarded(broker,plan,not_after=end)
            async def mutation(current, operation):
                validate()
                await attended.guard.before_mutation(current,operation)
            return GuardedExecutionBroker(inner=broker,grant=attended.grant,
                guard=ExecutionBrokerGuard(before,after,mutation))
        async def forbidden(*_): raise Refused('read-only gateway fixture cannot mutate')
        return GuardedExecutionBroker(inner=broker,
            grant=PaperPreparationGrant(grant.broker_account_id,self.slot.decision_session),
            guard=ExecutionBrokerGuard(before,after,forbidden))

    def admit_fixture_transport(self, broker, **_):
        if not isinstance(broker,AttendedQuoteBroker) or broker.run is not self.run:
            raise Refused('only this attended factory wrapper is admitted by the test fixture')
        certification.require_certified_adapter(broker.raw,expected='alpaca')
        with __import__('contextlib').suppress(certification.AdapterNotCertified):
            certification.require_certified_adapter(broker)
            raise Refused('attended wrapper unexpectedly received production certification')
        self.run.production_fenced()

    async def recover(self, context):
        self.load_durable_plan()
        return await automation_runtime.ProductionAutomation.recover(self,context)

    async def execute(self, context):
        self.load_durable_plan()
        result = await automation_runtime.ProductionAutomation.execute(self,context)
        self.run.ledger.record('full_production_execute',disposition=result.disposition.value,
            failure_code=result.failure_code,detail=result.failure_detail)
        return result


async def main(args):
    run = NativeRun(output=args.output,account_sha256=args.account_sha256,maximum=args.maximum_open_usd)
    run.acquire_owner();run.production_fenced()
    account,positions,orders,_ = await run.snapshot()
    if positions or orders: raise Refused('gateway campaign requires a flat settled account')
    run.account_id = str(account.get('account_number') or account['id'])
    reserve = Decimal(account['cash'])-run.maximum
    if reserve < 0: raise Refused('paper account cannot fund the authorized test purse')
    config = AutomationConfig(lease_seconds=30,heartbeat_seconds=3,callback_deadline_seconds=600,
        retry_base_seconds=2,retry_max_seconds=10,execute_max_attempts=30,recover_max_attempts=30)
    now = datetime.now(timezone.utc)
    ordinary = schedule.for_clock(now,config)
    slot = SessionSchedule.model_validate(ordinary.model_copy(update={
        'execution_open_at':now+timedelta(minutes=5),'execute_at':now+timedelta(minutes=5,seconds=1)}).model_dump())
    with run.connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        original_binding = binding.require(conn)
        if journal.load_commands(conn,original_binding.identity):
            raise Refused('gateway fixture must contain no prior production commands')
        retained = daily.read(conn) or origin.read(conn)
        controller = production_strategy()[0]
        retained_context = dict(observation_id=retained.observation_id,starting_cash=retained.starting_cash,
            controller=controller,strategy=retained.strategy_identity,runtime=retained.runtime_identity)
        daily.load(conn,retained_context,status_only=True)
        conn.rollback()
        journal.supersede_all_but(conn,'attended-fixture-retirement-'+run.run_id)
        # This modifies only the distinct private fixture's account namespace;
        # neither the canonical ledger nor production binding is edited.
        conn.execute("UPDATE sentinel_account_binding SET deployment_id=%s,notes=%s WHERE id=1",
            (run.deployment_id,'ISOLATED ATTENDED GATEWAY FIXTURE; never a production binding'))
        conn.commit()
        bound = binding.require(conn)
        rollout = load_rollout_state(conn)
        control = ControlBinding(deployment_id=bound.deployment_id,broker=bound.broker,
            broker_account_id=bound.broker_account_id,takeover_epoch=bound.takeover_epoch,
            certificate_sha256=rollout.certificate_sha256,rollout_mode=rollout.mode.value,
            rollout_version=rollout.version,config_sha256=config.fingerprint)
        automation_store.activate(conn,binding=control,actor='owner-attended-audit',reason='ISOLATED unsigned gateway fixture')
        automation_store.release_kill(conn,expected_binding=control,actor='owner-attended-audit',reason='paper test grant only')
    run.saved = dict(run_id=run.run_id,account_sha256=run.account_sha256,maximum=str(run.maximum),
        starting_cash=str(account['cash']),reserve=str(reserve),production_authority=False,
        profile='UNSIGNED_ATTENDED_GATEWAY_FIXTURE')
    with run.connect() as conn:
        database,system,started=conn.execute('SELECT current_database(),system_identifier::text,pg_postmaster_start_time() FROM pg_control_system()').fetchone()
        if journal.load_commands(conn,binding.require(conn).identity):
            raise Refused('fresh attended restart proof requires an empty test command journal')
        run.saved.update(test_database=database,test_system_id=system,test_postmaster_start=started.isoformat())
    durable_json(run.manifest,run.saved)
    durable_json(args.output/'service-slot.json',slot.model_dump(mode='json'))
    campaign = GatewayCampaign(run,slot,config,retained,reserve)
    campaign.certificate = SimpleNamespace(certificate_sha256=rollout.certificate_sha256,
        authorization_mode='PAPER_OBSERVATION_ONLY',maximum_exposure=Decimal(1))
    def fixture_authority(*a,**k):
        run.production_fenced()
        return campaign.certificate
    def fixture_context(observation_id,starting_cash):
        if observation_id != retained.observation_id or Decimal(starting_cash) != Decimal(retained.starting_cash):
            raise Refused('retained context fixture belongs to another book')
        return dict(retained_context)
    original_restart_fence=alpaca.postmaster_day_order_fence_reason
    def attended_fresh_database(conn,today,*,recovery_generation=None):
        reason=original_restart_fence(conn,today,recovery_generation=recovery_generation)
        if not reason:
            return reason
        database,system,started=conn.execute('SELECT current_database(),system_identifier::text,pg_postmaster_start_time() FROM pg_control_system()').fetchone()
        current=binding.require(conn)
        if (reason.startswith('PostgreSQL restarted during XNYS session ')
                and database==run.saved['test_database'] and database.startswith('rehearsal_execution')
                and system==run.saved['test_system_id']
                and started.isoformat()==run.saved['test_postmaster_start']
                and current.deployment_id==run.deployment_id):
            run.production_fenced()
            return ''
        return reason
    with ExitStack() as stack:
        stack.enter_context(patch.object(alpaca,'postmaster_day_order_fence_reason',attended_fresh_database))
        stack.enter_context(patch.object(initial,'_context',fixture_context))
        for owner in (preparation,execution,recovery,validation):
            stack.enter_context(patch.object(owner,'require_current_authority',fixture_authority))
            stack.enter_context(patch.object(owner,'_guard_broker',campaign.fixture_guard))
        for owner in (preparation,execution,recovery):
            stack.enter_context(patch.object(owner,'_default_paper_strategy',lambda:(controller,retained.strategy_identity)))
        run.ledger.record('qualification_boundary',callbacks='ProductionAutomation.prepare/recover/execute',
            gateway='paper.prepare_paper_plan/execute_automated_paper_plan/recover_automated_paper_cycle',
            substitutions=['owner unsigned signature/grant fixture','authenticated retained runtime context',
                'fixed cash reserve test purse','attended regular-session quote/schedule',
                'fresh empty private database startup, pinned to its unchanged real postmaster identity'],production_authority=False)
        try:
            await campaign.run_service()
        finally:
            if campaign.path.exists():
                campaign.load_durable_plan()
                # The shared runner cleans up after success; failures must also
                # close their attributable positions before returning.
                events = [json.loads(line) for line in run.ledger.path.read_text().splitlines()]
                if not any(event['event']=='service_campaign_complete' for event in events):
                    await campaign.cleanup()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--account-sha256',required=True)
    parser.add_argument('--maximum-open-usd',type=Decimal,required=True)
    parser.add_argument('--confirm-owner-authorized-current-paper-account',action='store_true',required=True)
    asyncio.run(main(parser.parse_args()))
