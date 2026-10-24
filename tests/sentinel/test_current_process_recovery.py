"""Current protected DAY callback recovery, never opening-latency evidence.

One canonical generated formation and genuine private PAPER authority. Actual
AutomationService fork/lease/deadline supervision remains active. State changes
after a dead callback are explicit legal private recovery transitions; this is
not evidence of full unattended worker, laptop or database restart behavior.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from psycopg.pq import TransactionStatus

from sentinel import automation_runtime, binding, rolling_checkpoint, rolling_initialization, rolling_runtime
from sentinel.authority import load_rollout_state
from sentinel.automation import schedule, store as automation_store
from sentinel.automation.model import (AutomationConfig, ControlBinding, CycleContext, CycleSpec,
    CycleState, ExecuteDisposition, ExecuteResult, PrepareResult, RefreshResult, SoftwareDefect)
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.execution import journal, protected_funding
from sentinel.execution.states import CommandState
from sentinel.core.formation_inputs import FormationInputs
from sentinel.feed import normalized_layout, operational_snapshot as snapshots, rolling_store
from sentinel.strategy import production_strategy
from tests.sentinel.test_current_operational_workflow import OBSERVATION, cluster, conn, current  # noqa: F401
from tests.support.current_workflow_authority import issue_current_paper_authority
from tests.support.current_workflow_faults import (ProxyTransport, fenced_private_control,
    independent_provider, kill_owned_callback)
from tests.support.current_workflow_run import _assets, live_lease


@pytest.mark.skipif(sys.platform != 'linux', reason='actual fork/SIGKILL and durable directory fsync')
def test_current_protected_day_survives_two_callback_deaths_without_duplicate_economics(
        conn, current, monkeypatch, tmp_path):
    prices, published, clock = current
    assert len(prices.window.sessions) == 426
    formed = rolling_initialization.initialize(conn, observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert formed.state.last_processed_session == str(prices.window.end)
    assert formed.state.wealth_core['episodes']
    original_hash = formed.state.state_hash
    resumed = rolling_initialization.resume(conn, observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert resumed.state.state_hash == original_hash
    # Initial formation creates canonical state. The ordinary runtime advance
    # independently verifies that state and earns the retained runtime receipt
    # required by the issuer; formation alone is not execution admission.
    attested = rolling_runtime.advance(conn, through=str(prices.window.end),
        observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert attested.verification == 'VERIFIED' and attested.state.state_hash == original_hash
    with snapshots.pinned(conn) as (publication, source_bound):
        assert FormationInputs(conn, source_bound, publication) is not None
        source_manifest = rolling_store.manifest(conn, published['candidate_id'])
        normalized_layout.require_layout(conn, published['candidate_id'], source_manifest)
    conn.rollback()
    canonical = rolling_checkpoint.read(conn).model_dump(by_alias=True)
    config = AutomationConfig()
    controller, strategy = production_strategy()
    certificate = issue_current_paper_authority(conn, monkeypatch, tmp_path, now=clock.now(),
        observation_id=OBSERVATION, controller=controller, strategy=strategy,
        automation_config_sha256=config.fingerprint)
    bound, rollout = binding.require(conn), load_rollout_state(conn)
    timing = schedule.for_decision_session(canonical['session'], config)
    assets, dsn = _assets(conn, published), conn.info.dsn
    conn.rollback()
    monkeypatch.setenv('SENTINEL_FEED_SERVICE_MODE', 'AUTOMATION')
    parent_pid = os.getpid()
    state_path = tmp_path / 'independent-provider-state.json'
    with independent_provider(state_path=state_path, clock=clock, account=bound.broker_account_id,
            cash='50000', assets=assets, window=lambda: (timing.execution_open_at, timing.execution_close_at),
            forbid_quotes=True, marketable_limit_fills=True) as (provider, provider_pid), \
            fenced_private_control(dsn, provider) as owned:
        transport = ProxyTransport(provider, parent_pid=parent_pid)

        class Campaign(automation_runtime.ProductionAutomation):
            def _broker(self, reader, session):
                broker = super()._broker(reader, session)
                broker._http_provider = lambda: transport
                broker._clock_provider = clock.now
                return broker

        campaign = Campaign(sentinel_config=SentinelConfig(database_url=dsn, alpaca_key='isolated',
            alpaca_secret='no-network', base_url=DEFAULT_BASE_URL, state_dir=tmp_path/'state',
            max_cycles=1, poll_seconds=0), automation_config=config, holder_id='current-private-fault-worker')
        control = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
            broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
            certificate_sha256=certificate, rollout_mode=rollout.mode.value,
            rollout_version=rollout.version, config_sha256=config.fingerprint)
        automation_store.activate(conn, binding=control, actor='ISOLATED_QUALIFICATION',
            reason='generated current callback fault composition')
        automation_store.release_kill(conn, expected_binding=control, actor='ISOLATED_QUALIFICATION',
            reason='independent local simulated provider only')
        permit = automation_store.acquire_lease(conn, holder_id=campaign.holder_id, lease_seconds=config.lease_seconds)
        owned['permit'] = permit
        spec = CycleSpec(**timing.model_dump(), **control.model_dump(), control_generation=permit.control_generation)
        cycle = automation_store.create_cycle(conn, permit=permit, spec=spec, now=clock.now(), config=config)
        conn.rollback()

        def transition(state, **fields):
            return automation_store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                                                     to_state=state, **fields)

        def invoke(callback, phase, result_type=ExecuteResult):
            # Actual production process supervision and real independent DB
            # heartbeat; never direct in-process callback execution.
            conn.rollback()
            assert conn.info.transaction_status is TransactionStatus.IDLE
            raw = asyncio.run(campaign.service._invoke(callback, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase=phase, heartbeat_conn_factory=campaign.connect))
            return result_type.model_validate(raw)

        with live_lease(dsn, permit, config):
            assert invoke(campaign.recover, 'RECOVER').disposition is ExecuteDisposition.SUCCEEDED
            cycle = transition(CycleState.REFRESHING_DATA)
            assert invoke(campaign.refresh, 'REFRESH', RefreshResult).already_published
            cycle = transition(CycleState.PREPARING)
            prepared = invoke(campaign.prepare, 'PREPARE', PrepareResult)
            cycle = transition(CycleState.PLAN_READY, plan_id=prepared.plan_id,
                plan_fingerprint=prepared.plan_fingerprint, state_fingerprint=prepared.state_fingerprint,
                data_version=prepared.data_version, publication_fingerprint=prepared.publication_fingerprint)
            plan = journal.latest_plan(conn)
            assert plan.plan_id == prepared.plan_id and plan.target_basket
            conn.rollback()
            cycle = transition(CycleState.WAITING_OPEN)
            clock.instant = cycle.execute_at + timedelta(seconds=1)
            provider.set_clock(clock.instant)
            cycle = transition(CycleState.EXECUTING)
            print('CURRENT_PROCESS_RECOVERY accepted-partial response-loss SIGKILL', flush=True)
            with pytest.raises((SoftwareDefect, EOFError)):
                invoke(campaign.execute, 'EXECUTE')
            first = provider.snapshot()
            assert len(first['state']['orders']) == 1 and len(first['state']['events']) == 1
            key = first['first_key']
            order = next(iter(first['state']['orders'].values()))
            pending = journal.load_commands(conn, bound.identity, plan_id=plan.plan_id)
            original = next(command for command in pending if command.client_key == key)
            assert original.state is CommandState.SEND_PENDING and original.filled_quantity == 0
            assert original.order_terms.order_type == 'limit' and original.order_terms.time_in_force == 'day'
            assert original.quantity == Decimal(order['qty']) > 1
            assert original.order_terms.limit_price == Decimal(order['limit_price'])
            promise = protected_funding.maximum_cost(original)
            basis = protected_funding.load_basis(conn, plan_id=plan.plan_id)
            assert basis is not None
            conn.rollback()
            cycle = transition(CycleState.RECONCILING)
            partial = invoke(campaign.recover, 'RECOVER')
            assert partial.disposition in {ExecuteDisposition.READY_TO_EXECUTE, ExecuteDisposition.RECONCILE}
            recovered = next(command for command in journal.load_commands(conn, bound.identity,
                plan_id=plan.plan_id) if command.client_key == key)
            assert recovered.state is CommandState.PARTIALLY_FILLED and recovered.filled_quantity == 1
            assert recovered.quantity == original.quantity and recovered.order_terms == original.order_terms
            assert protected_funding.maximum_cost(recovered) == promise
            assert protected_funding.load_basis(conn, plan_id=plan.plan_id) == basis
            cohort = partial.diagnostic.get('protected_cohort') or partial.diagnostic.get('protected_day_wait')
            assert cohort is not None, partial
            remaining_principal = recovered.remaining * recovered.order_terms.limit_price
            assert Decimal(cohort['reserved_cash']) == remaining_principal
            assert provider.snapshot()['state']['requests']['POST /v2/orders'] == 1
            conn.rollback()
            # A second native delivery/poll cannot invent another fill/order.
            again = invoke(campaign.recover, 'RECOVER')
            assert again.disposition in {ExecuteDisposition.READY_TO_EXECUTE, ExecuteDisposition.RECONCILE}
            assert provider.snapshot()['state']['requests']['POST /v2/orders'] == 1
            provider.complete_first()

            async def recover_before_filled_persistence(context):
                real_save = journal.save_command
                def stop_before_save(connection, command, **kwargs):
                    if command.client_key == key and command.state is CommandState.FILLED:
                        provider.record_fault('BEFORE_FILLED_PERSISTENCE', os.getpid(), key)
                        kill_owned_callback(parent_pid=parent_pid)
                    return real_save(connection, command, **kwargs)
                with patch.object(journal, 'save_command', stop_before_save):
                    return await campaign.recover(context)

            print('CURRENT_PROCESS_RECOVERY before-FILLED-persistence SIGKILL', flush=True)
            with pytest.raises((SoftwareDefect, EOFError)):
                invoke(recover_before_filled_persistence, 'RECOVER')
            uncommitted = next(command for command in journal.load_commands(conn, bound.identity,
                plan_id=plan.plan_id) if command.client_key == key)
            assert uncommitted.state is CommandState.PARTIALLY_FILLED and uncommitted.filled_quantity == 1
            conn.rollback()
            settled = invoke(campaign.recover, 'RECOVER')
            assert settled.disposition in {ExecuteDisposition.READY_TO_EXECUTE, ExecuteDisposition.SUCCEEDED}
            final = next(command for command in journal.load_commands(conn, bound.identity,
                plan_id=plan.plan_id) if command.client_key == key)
            assert final.state is CommandState.FILLED and final.filled_quantity == original.quantity
            assert final.quantity == original.quantity and final.order_terms == original.order_terms
            assert protected_funding.maximum_cost(final) == promise
            assert protected_funding.load_basis(conn, plan_id=plan.plan_id) == basis
            conn.rollback()
            # Another freshly forked recovery consumes the same native
            # executions and must preserve the already recorded economics.
            assert invoke(campaign.recover, 'RECOVER').disposition is settled.disposition
            final_state = provider.snapshot()
            assert final_state['provider_pid'] == provider_pid != parent_pid
            assert len(final_state['state']['orders']) == 1
            assert final_state['state']['requests']['POST /v2/orders'] == 1
            assert len(final_state['state']['events']) == 2
            assert sum(Decimal(row['qty']) for row in final_state['state']['events']) == original.quantity
            assert Decimal(final_state['state']['positions'][order['asset_id']]) == original.quantity
            assert final_state['state']['orders'][order['id']]['client_order_id'] == key
            assert [fault['point'] for fault in final_state['faults']] == [
                'ACCEPTED_PARTIAL_BEFORE_RESPONSE', 'BEFORE_FILLED_PERSISTENCE']
            for fault in final_state['faults']:
                assert fault['callback_pid'] not in {parent_pid, provider_pid}
                assert not Path(f'/proc/{fault["callback_pid"]}').exists()
            assert json.loads(state_path.read_text()) == final_state
            assert rolling_checkpoint.read(conn).model_dump(by_alias=True) == canonical
            conn.rollback()
