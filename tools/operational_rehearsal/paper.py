"""Offline authority fixture around the real automated paper membrane."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from sentinel import binding, paper
from sentinel.config import DEFAULT_BASE_URL
from sentinel.execution import certification, journal
from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.execution.guarded import AutomationExecutionGrant
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import calendar
from sentinel.paper import preparation, inspection, execution, recovery, validation


class PaperTape:
    def __init__(self, conn, patch, *, observation_id):
        self.patch, self.observation_id = patch, observation_id
        self.bound = binding.bind(conn, deployment_id='joint-rehearsal',
                                 broker='alpaca', broker_account_id='offline-simulator')
        conn.execute("INSERT INTO sentinel_system_certificates "
            "(certificate_sha256,manifest_bytes,manifest,allowed_rollout_modes) "
            "VALUES (%s,'{}'::bytea,'{}'::jsonb,'[\"CONTROLLER\"]'::jsonb)", ('a'*64,))
        conn.execute("UPDATE sentinel_rollout_state SET mode='CONTROLLER',version=2,certificate_sha256=%s WHERE id=1", ('a'*64,))
        conn.execute("INSERT INTO sentinel_rollout_events (version,from_mode,to_mode,certificate_sha256,reason) "
            "VALUES (2,'PINNED_1_00','CONTROLLER',%s,'offline synthetic authority')", ('a'*64,))
        conn.commit()
        self.broker = SimulatedBroker(account=BrokerAccountIdentity('alpaca', 'offline-simulator'),
                                     equity=Decimal('50000'), cash=Decimal('50000'))
        self.broker.capabilities = replace(self.broker.capabilities,
            account_close_valuation=False, recent_fill_history=False)
        patch.setattr(inspection, 'require_certified', certification.require_certified_adapter)
        for module in (preparation, execution, recovery, validation):
            patch.setattr(module, 'require_current_authority', lambda *a, **k: SimpleNamespace(
                certificate_sha256='a'*64, authorization_mode='PAPER_OBSERVATION_ONLY'))
        for module in (preparation, execution):
            patch.setattr(module, '_guard_broker', lambda **kwargs: kwargs['broker'])

    def cycle(self, conn, *, day, now, state_sha256):
        args = dict(conn=conn, broker=self.broker, through=day,
            expected_account='offline-simulator', dual_shadow_observation_id=self.observation_id,
            dual_shadow_starting_cash=50000, now_et=now, base_url=DEFAULT_BASE_URL)
        plan = asyncio.run(paper.prepare_paper_plan(**args))
        assert plan.state_fingerprint == state_sha256
        assert plan.sessions_replayed == plan.warmup_sessions == 0
        assert asyncio.run(paper.prepare_paper_plan(**args)).plan == plan.plan
        grant = AutomationExecutionGrant('EXECUTE', 'joint-'+day, 1, 'offline', 1,
            'offline-simulator', self.bound.takeover_epoch, 'CONTROLLER', 2, 'a'*64)
        self.patch.setattr(execution, '_validate_automation_grant', lambda *a: (None,
            SimpleNamespace(plan_id=plan.plan.plan_id, plan_fingerprint=plan.plan.fingerprint())))
        opened, _ = calendar.session_window(plan.plan.effective_session)
        self.broker.now = opened + timedelta(seconds=60)
        def execute():
            return asyncio.run(paper.execute_automated_paper_plan(
                conn=conn, broker=self.broker, base_url=DEFAULT_BASE_URL,
                grant=grant, automation_config_sha256='b'*64, today=self.broker.now,
                dual_shadow_observation_id=self.observation_id, dual_shadow_starting_cash=50000))
        submitted = []
        # Reductions settle before a second attempt may fund increases.
        for _ in range(5):
            result = execute()
            commands = result.session.submitted
            if not commands:
                break
            for command in commands:
                self.broker.fill(command.client_key)
            submitted.extend(commands)
            self.broker.tick(1)
        else:
            raise AssertionError('simulated paper cycle did not converge')
        assert not execute().session.submitted
        commands = journal.load_commands(conn, self.bound.identity, plan_id=plan.plan.plan_id)
        assert len(commands) == len(submitted)
        assert all(c.state.value == 'FILLED' for c in commands)
        return dict(session=day, state_sha256=state_sha256,
                    plan_id=plan.plan.plan_id, commands=len(commands))
