"""Whole private worker death and real-lease takeover; no opening/live claim.

Service-loop UTC, host/Postgres skew sampling and DB leases use actual clocks.
The inherited BusinessClock remains synthetic for financial, authority,
observation and calendar-input modules throughout setup AND recovery callbacks.
This is generated functional process/lease proof, never real-clock financial
callback, provider, exchange-session or live-money qualification.
"""
from __future__ import annotations

import asyncio
import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import json
import os
from pathlib import Path
import sys

import pytest
from psycopg.pq import TransactionStatus

from sentinel import automation_runtime, binding, rolling_checkpoint, rolling_initialization, rolling_runtime
from sentinel.authority import load_rollout_state
from sentinel.automation import schedule, store as automation_store
from sentinel.automation.model import (AutomationConfig, ControlBinding, CycleContext, CycleSpec,
    CycleState, ExecuteResult, PrepareResult, RefreshResult)
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.execution import journal, protected_funding
from sentinel.execution.states import CommandState
from tests.sentinel.test_current_operational_workflow import OBSERVATION, cluster, conn, current  # noqa: F401
from tests.support.current_workflow_authority import issue_current_paper_authority
from tests.support.current_workflow_faults import fenced_private_control
from tests.support.current_workflow_run import _assets, live_lease
from tests.support.current_service_faults import (ServiceProxyTransport, assert_owned_worker,
    independent_service_provider, linux_process_identity, process_gone_or_zombie,
    wait_until, whole_service_process)


def _require_final_order_witness(ordinary_sequences, exact_sequences):
    """Positive canonical evidence is required; its lookup route is incidental."""
    sequences = set(ordinary_sequences) | set(exact_sequences)
    assert sequences, 'final positive order witness is missing from both canonical routes'
    return sequences


@pytest.mark.parametrize('ordinary,exact', [([3], []), ([], [3]), ([3], [4])])
def test_final_order_witness_accepts_either_existing_canonical_route(ordinary, exact):
    assert _require_final_order_witness(ordinary, exact) == set(ordinary) | set(exact)


def test_final_order_witness_refuses_missing_both_routes():
    with pytest.raises(AssertionError, match='missing from both'):
        _require_final_order_witness([], [])


def test_final_order_witness_falsifier_observes_removed_positive_evidence_guard(monkeypatch):
    test_final_order_witness_refuses_missing_both_routes()
    tree = ast.parse(inspect.getsource(_require_final_order_witness))
    function = tree.body[0]
    guards = [node for node in function.body if isinstance(node, ast.Assert)]
    assert len(guards) == 1
    function.body.remove(guards[0])
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), '<final-order-evidence-mutant>', 'exec'), namespace)
    monkeypatch.setitem(globals(), '_require_final_order_witness', namespace['_require_final_order_witness'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_final_order_witness_refuses_missing_both_routes()


@pytest.mark.parametrize('changed', [
    {'pid': 1}, {'parent_pid': 1}, {'state': 'Z'}, {'state': 'X'},
    {'start_ticks': 0}, {'start_ticks': 2},
])
def test_private_worker_signal_owner_refuses_mismatched_or_dead_incarnation(changed):
    parent = os.getpid()
    child = parent + 1000000
    material = {'pid': child, 'parent_pid': parent, 'state': 'S', 'start_ticks': 1}
    assert_owned_worker(material, expected_parent_pid=parent, expected_pid=child, expected_start_ticks=1)
    if 'parent_pid' in changed:
        # pytest is PID 1 in the isolated test image. A literal 1 is therefore
        # not necessarily a mismatched parent; derive a different identity.
        changed = {**changed, 'parent_pid': parent + 1}
    with pytest.raises(AssertionError):
        assert_owned_worker({**material, **changed}, expected_parent_pid=parent, expected_pid=child,
            expected_start_ticks=1)


def test_private_worker_signal_owner_refuses_test_process():
    own = os.getpid()
    with pytest.raises(AssertionError):
        assert_owned_worker({'pid': own, 'parent_pid': own, 'state': 'S', 'start_ticks': 1},
            expected_parent_pid=own, expected_pid=own, expected_start_ticks=1)


@pytest.mark.parametrize('boundary,changed', [
    ("identity['parent_pid'] == expected_parent_pid", {'parent_pid': 1}),
    ("identity['start_ticks'] == expected_start_ticks", {'start_ticks': 2}),
])
def test_private_worker_signal_ownership_falsifier_observes_removed_boundary(
        monkeypatch, boundary, changed):
    """The same public refusal assertion must fail with each guard removed.

    Mutate only an in-memory copied function. Never rewrite source or replace
    production process supervision while the composed campaign is running.
    """
    original = assert_owned_worker
    test_private_worker_signal_owner_refuses_mismatched_or_dead_incarnation(changed)
    tree = ast.parse(inspect.getsource(original))
    function = tree.body[0]
    matches = [node for node in function.body if isinstance(node, ast.Assert)
        and ast.unparse(node.test) == boundary]
    assert len(matches) == 1, 'the exact owned-signal boundary must exist'
    function.body.remove(matches[0])
    namespace = {'os': os}
    exec(compile(ast.fix_missing_locations(tree), '<owned-signal-boundary-mutant>', 'exec'), namespace)
    monkeypatch.setitem(globals(), 'assert_owned_worker', namespace['assert_owned_worker'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_private_worker_signal_owner_refuses_mismatched_or_dead_incarnation(changed)


@pytest.mark.skipif(sys.platform != 'linux', reason='actual Linux pidfd/fork/parent-death supervision')
def test_current_whole_service_restart_takes_over_real_lease_without_reposting_unknown(
        conn, current, monkeypatch, tmp_path):
    actual_now = datetime.now(timezone.utc)
    config = AutomationConfig()
    actual_schedule = schedule.for_clock(actual_now, config)
    if actual_now >= actual_schedule.execute_at:
        pytest.skip('whole-service functional recovery profile needs a real pre-open obligation; '
                    'no host/DB clock, exchange date or submission window is changed')
    prices, published, clock = current
    formed = rolling_initialization.initialize(conn, observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert formed.state.wealth_core['episodes']
    origin = rolling_checkpoint.read(conn).model_dump(by_alias=True)
    resumed = rolling_initialization.resume(conn, observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert resumed.state.state_hash == formed.state.state_hash
    attested = rolling_runtime.advance(conn, through=str(prices.window.end),
        observation_id=OBSERVATION, starting_cash=Decimal('50000'))
    assert attested.verification == 'VERIFIED' and attested.state.state_hash == formed.state.state_hash
    conn.rollback()
    controller, strategy = production_strategy_for_test()
    certificate = issue_current_paper_authority(conn, monkeypatch, tmp_path, now=clock.now(),
        observation_id=OBSERVATION, controller=controller, strategy=strategy,
        automation_config_sha256=config.fingerprint)
    bound, rollout = binding.require(conn), load_rollout_state(conn)
    timing = schedule.for_decision_session(origin['session'], config)
    actual_schedule = schedule.for_clock(datetime.now(timezone.utc), config)
    assert actual_schedule == timing, 'whole-service real UTC must name the generated source obligation'
    # No moved host/DB clock, skew allowance or out-of-session execution.
    assert datetime.now(timezone.utc) < timing.execute_at
    assets, dsn = _assets(conn, published), conn.info.dsn
    conn.rollback()
    monkeypatch.setenv('SENTINEL_FEED_SERVICE_MODE', 'AUTOMATION')
    state_path = tmp_path / 'independent-whole-service-provider.json'

    with independent_service_provider(state_path=state_path, clock=clock,
            account=bound.broker_account_id, cash='50000', assets=assets,
            window=lambda: (timing.execution_open_at, timing.execution_close_at),
            forbid_quotes=True, marketable_limit_fills=True) as (provider, provider_pid), \
            fenced_private_control(dsn, provider) as owned:

        def factory(holder):
            transport = ServiceProxyTransport(provider, worker_pid=os.getpid())
            class Campaign(automation_runtime.ProductionAutomation):
                def _broker(self, reader, session):
                    broker = super()._broker(reader, session)
                    broker._http_provider = lambda: transport
                    broker._clock_provider = clock.now
                    return broker
            return Campaign(sentinel_config=SentinelConfig(database_url=dsn,
                alpaca_key='isolated', alpaca_secret='no-network', base_url=DEFAULT_BASE_URL,
                state_dir=tmp_path/'state', max_cycles=1, poll_seconds=0),
                automation_config=config, holder_id=holder)

        setup = factory('private-whole-service-setup')
        control = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
            broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
            certificate_sha256=certificate, rollout_mode=rollout.mode.value,
            rollout_version=rollout.version, config_sha256=config.fingerprint)
        automation_store.activate(conn, binding=control, actor='ISOLATED_QUALIFICATION',
            reason='whole private service generated functional campaign')
        automation_store.release_kill(conn, expected_binding=control, actor='ISOLATED_QUALIFICATION',
            reason='independent local simulated provider; no native network')
        permit = automation_store.acquire_lease(conn, holder_id=setup.holder_id, lease_seconds=config.lease_seconds)
        owned['permit'] = permit
        spec = CycleSpec(**timing.model_dump(), **control.model_dump(), control_generation=permit.control_generation)
        cycle = automation_store.create_cycle(conn, permit=permit, spec=spec, now=clock.now(), config=config)
        conn.rollback()

        def transition(state, **fields):
            return automation_store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=state, **fields)

        def invoke(callback, phase, result_type):
            conn.rollback()
            assert conn.info.transaction_status is TransactionStatus.IDLE
            value = asyncio.run(setup.service._invoke(callback, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase=phase, heartbeat_conn_factory=setup.connect))
            return result_type.model_validate(value)

        with live_lease(dsn, permit, config):
            assert invoke(setup.recover, 'RECOVER', ExecuteResult).disposition.value == 'SUCCEEDED'
            cycle = transition(CycleState.REFRESHING_DATA)
            assert invoke(setup.refresh, 'REFRESH', RefreshResult).already_published
            cycle = transition(CycleState.PREPARING)
            prepared = invoke(setup.prepare, 'PREPARE', PrepareResult)
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
            invoke(setup.execute, 'EXECUTE', ExecuteResult)
            first = provider.snapshot()
            assert len(first['state']['orders']) == 1
            assert first['state']['requests']['POST /v2/orders'] == 1
            key = first['first_key']
            original = next(row for row in journal.load_commands(conn, bound.identity,
                plan_id=plan.plan_id) if row.client_key == key)
            assert original.state in {CommandState.UNKNOWN, CommandState.SEND_PENDING}
            assert original.filled_quantity == 0 and original.quantity > 1
            assert original.order_terms.order_type == 'limit' and original.order_terms.time_in_force == 'day'
            basis = protected_funding.load_basis(conn, plan_id=plan.plan_id)
            assert basis is not None
            maximum = protected_funding.maximum_cost(original)
            conn.rollback()
            cycle = transition(CycleState.RECONCILING)
        automation_store.release_lease(conn, permit=permit)
        owned['permit'] = None
        conn.rollback()

        def current_command():
            conn.rollback()
            commands = journal.load_commands(conn, bound.identity, plan_id=plan.plan_id)
            conn.rollback()
            return next(row for row in commands if row.client_key == key)

        def load_cycle():
            conn.rollback()
            value = automation_store.latest_cycle(conn)
            conn.rollback()
            return value

        def lease():
            conn.rollback()
            value = conn.execute('SELECT holder_id,fence_token,expires_at,clock_timestamp() '
                'FROM sentinel_automation_lease WHERE id=1').fetchone()
            conn.rollback()
            return value

        def coherent_order(command):
            assert command.client_key == original.client_key
            assert command.quantity == original.quantity and command.order_terms == original.order_terms
            assert protected_funding.maximum_cost(command) == maximum
            assert protected_funding.load_basis(conn, plan_id=plan.plan_id) == basis
            conn.rollback()

        provider.set_mode('BLOCK_LOOKUP')
        print('CURRENT_SERVICE_RECOVERY start complete worker A with real UTC', flush=True)
        with whole_service_process(factory, name='private-whole-service-A',
                evidence_path=tmp_path/'worker-A.json') as worker_a:
            fault = wait_until(lambda: next((item for item in provider.snapshot()['faults']
                if item['point'] == 'BLOCKED_LOOKUP'), None),
                seconds=180, description='whole worker A reaches blocked native recovery lookup')
            assert fault['worker_pid'] == worker_a['process'].pid
            callback = linux_process_identity(fault['callback_pid'])
            assert callback['parent_pid'] == worker_a['process'].pid
            assert callback['pid'] not in {os.getpid(), provider_pid}
            lost_lease = lease()
            assert lost_lease[0] == 'private-whole-service-A' and lost_lease[2] > lost_lease[3]
            coherent_order(current_command())
            worker_a['kill']()
            wait_until(lambda: process_gone_or_zombie(callback['pid'], start_ticks=callback['start_ticks']),
                seconds=10, description='production parent-death signal kills orphan callback')
        provider.set_mode('DISCONNECTED')
        # Do not release, rewrite, renew or resurrect the dead owner's lease.
        wait_until(lambda: lease()[2] <= lease()[3], seconds=config.lease_seconds+15,
            description='real database lease of dead worker A expires')

        print('CURRENT_SERVICE_RECOVERY fresh whole worker B during transport outage', flush=True)
        with whole_service_process(factory, name='private-whole-service-B',
                evidence_path=tmp_path/'worker-B.json') as worker_b:
            def refused_recovery():
                value = load_cycle()
                return (value if value.last_fence_token > lost_lease[1]
                    and value.state is CycleState.RETRY_WAIT
                    and value.diagnostic.get('retry_phase') == 'RECOVER' else None)
            refused = wait_until(refused_recovery, seconds=180,
                description='fresh leader durably defers UNKNOWN through transport outage')
            assert lease()[0] == 'private-whole-service-B'
            unknown = current_command()
            assert unknown.state in {CommandState.UNKNOWN, CommandState.SEND_PENDING}
            assert unknown.filled_quantity == 0
            coherent_order(unknown)
            assert provider.snapshot()['state']['requests']['POST /v2/orders'] == 1
            assert any(item['point'] == 'TRANSPORT_DISCONNECTED' for item in provider.snapshot()['faults'])
            provider.set_mode('CONNECTED')

            partial = wait_until(lambda: (value if (value := current_command()).state is CommandState.PARTIALLY_FILLED
                else None), seconds=180, description='whole worker B positively recovers original partial fill')
            coherent_order(partial)
            assert partial.filled_quantity == 1
            waited = wait_until(lambda: (value if (value := load_cycle()).state is CycleState.RETRY_WAIT
                and value.diagnostic.get('retry_phase') == 'EXECUTE' else None),
                seconds=60, description='new submissions wait for immutable future execution wake')
            assert waited.next_wake_at == cycle.execute_at == timing.execute_at
            cohort = waited.diagnostic.get('protected_cohort')
            assert cohort is not None
            assert Decimal(cohort['reserved_cash']) == partial.remaining * partial.order_terms.limit_price
            assert provider.snapshot()['state']['requests']['POST /v2/orders'] == 1
            second_lease = lease()
            worker_b['kill']()

        provider.complete_first()
        wait_until(lambda: lease()[2] <= lease()[3], seconds=config.lease_seconds+15,
            description='real database lease of dead worker B expires')
        print('CURRENT_SERVICE_RECOVERY fresh whole worker C records completed fill', flush=True)
        with whole_service_process(factory, name='private-whole-service-C',
                evidence_path=tmp_path/'worker-C.json') as worker_c:
            final = wait_until(lambda: (value if (value := current_command()).state is CommandState.FILLED
                else None), seconds=180, description='fresh whole worker records provider completion')
            coherent_order(final)
            assert final.filled_quantity == original.quantity
            deferred = wait_until(lambda: (value if (value := load_cycle()).state is CycleState.RETRY_WAIT
                and value.diagnostic.get('retry_phase') == 'EXECUTE' else None),
                seconds=60, description='remaining basket stays deferred until original wake')
            assert deferred.last_fence_token > second_lease[1] > lost_lease[1]
            assert lease()[0] == 'private-whole-service-C'
            assert deferred.next_wake_at == timing.execute_at
            assert deferred.plan_id == cycle.plan_id and deferred.plan_fingerprint == cycle.plan_fingerprint
            final_state = provider.snapshot()
            assert final_state['provider_pid'] == provider_pid
            assert len(final_state['state']['orders']) == 1
            assert final_state['state']['requests']['POST /v2/orders'] == 1
            assert len(final_state['state']['events']) == 2
            assert sum(Decimal(event['qty']) for event in final_state['state']['events']) == original.quantity
            order = next(iter(final_state['state']['orders'].values()))
            assert Decimal(final_state['state']['positions'][order['asset_id']]) == original.quantity
            assert final_state['state']['requests'].get('GET /v2/stocks/quotes/latest', 0) == 0
            assert json.loads(state_path.read_text()) == final_state
            # Current dual PAPER reconciliation accepts positive cumulative
            # order evidence. It deliberately does not claim accepted native
            # activity history or project provider events into a fill ledger.
            assert setup._broker(conn,
                cycle.effective_session.isoformat()).capabilities.recent_fill_history is False
            assert conn.execute('SELECT count(*) FROM sentinel_fills').fetchone() == (0,)
            assert not any(name.startswith('GET /v2/account/activities')
                or name.startswith('GET /v2beta1/events/activities')
                for name in final_state['state']['requests'])
            assert conn.execute('SELECT count(*) FROM sentinel_commands WHERE client_key=%s',
                (key,)).fetchone() == (1,)
            history = journal.command_history(conn, key)
            partial_events = [index for index, event in enumerate(history)
                if event['to'] == 'PARTIALLY_FILLED' and Decimal(event['filled']) == 1]
            final_events = [index for index, event in enumerate(history)
                if event['to'] == 'FILLED' and Decimal(event['filled']) == original.quantity]
            assert partial_events and final_events and min(final_events) > min(partial_events)
            cumulative = [Decimal(event['filled']) for event in history if event['filled'] is not None]
            assert cumulative == sorted(cumulative) and max(cumulative) == original.quantity

            partial_witnesses, final_witnesses = [], []
            exact_partial_witnesses, ordinary_final_witnesses, exact_final_witnesses = [], [], []
            sequences = conn.execute('SELECT seq FROM sentinel_observations ORDER BY seq').fetchall()
            assert 0 < len(sequences) <= 128, 'bounded fresh private observation history'
            for (sequence,) in sequences:
                # This real canonical loader validates primary/provenance rows,
                # their full digest and immutable processed-session witness.
                payload = journal.load_observation_payload(conn, sequence)
                assert payload['broker'] == bound.broker
                assert payload['account_id'] == bound.broker_account_id
                orders = [(value, False) for value in payload['orders']]
                for exact in payload['exact_evidence']:
                    if exact['client_key'] == key and exact['order'] is not None:
                        expected_identity = {'broker': bound.broker, 'account_id': bound.broker_account_id}
                        assert exact['identity_before'] == exact['identity_after'] == expected_identity
                        orders.append((exact['order'], True))
                for witnessed, exact in orders:
                    if witnessed['client_key'] != key:
                        continue
                    assert witnessed['broker_order_id'] == order['id'] == final.broker_order_id
                    assert witnessed['security_id'] == original.security_id
                    assert witnessed['broker_id'] == order['asset_id'] == original.instrument.broker_id
                    assert witnessed['symbol'] == order['symbol'] == original.instrument.symbol
                    assert witnessed['side'] == original.side.value == 'BUY'
                    assert Decimal(witnessed['quantity']) == original.quantity
                    assert witnessed['order_terms'] == original.order_terms.to_dict()
                    assert Decimal(witnessed['filled_average_price']) == Decimal(order['filled_avg_price'])
                    assert witnessed['submitted_at'] == order['submitted_at']
                    positions = {item['security_id']: Decimal(item['quantity']) for item in payload['positions']}
                    filled = Decimal(witnessed['filled_quantity'])
                    if witnessed['state'] == 'PARTIALLY_FILLED':
                        assert filled == 1 and positions[original.security_id] == 1
                        partial_witnesses.append(sequence)
                        if exact:
                            exact_partial_witnesses.append(sequence)
                    elif witnessed['state'] == 'FILLED':
                        assert filled == original.quantity and positions[original.security_id] == original.quantity
                        final_witnesses.append(sequence)
                        if exact:
                            exact_final_witnesses.append(sequence)
                        else:
                            ordinary_final_witnesses.append(sequence)
            assert partial_witnesses and final_witnesses
            assert exact_partial_witnesses
            assert _require_final_order_witness(ordinary_final_witnesses,
                exact_final_witnesses) == set(final_witnesses)
            assert min(final_witnesses) > min(partial_witnesses)
            assert rolling_checkpoint.read(conn).model_dump(by_alias=True) == origin
            conn.rollback()
            worker_c['stop'].set()
            worker_c['process'].join(timeout=30)
            assert not worker_c['process'].is_alive(), 'whole worker C must stop before cleanup fallback'
            assert worker_c['process'].exitcode == 0
            stopped = json.loads((tmp_path/'worker-C.json').read_text())
            assert stopped['status'] == 'STOPPED' and stopped['ticks'] > 0


def production_strategy_for_test():
    from sentinel.strategy import production_strategy
    return production_strategy()
