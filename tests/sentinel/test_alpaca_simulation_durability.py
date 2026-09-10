"""Real PostgreSQL journal/cash recovery driven by the Alpaca HTTP simulator."""
from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel import binding, schema
from sentinel.core import cashflow
from sentinel.execution import broker_cash, executor, journal, reconcile, recovery
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.feed import store
from sentinel.paper.cash import _cash_authority_or_refuse
from sentinel.paper.model import PaperActivationRefused
from tests.support.alpaca_simulator import AlpacaSimulator, EPOCH, Profile
from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from test_alpaca_simulation_harness import DEPLOY, command, run


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    try:
        server.start()
    except Exception as exc:
        server.stop()
        if os.environ.get("ALPACA_HARNESS_REQUIRE_POSTGRES") == "1":
            pytest.fail(f"required PostgreSQL unavailable: {exc}")
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg):
    with store.connect(pg.sync_dsn) as conn:
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        binding.bind(conn, deployment_id=DEPLOY.deployment_id, broker="alpaca",
                     broker_account_id=DEPLOY.broker_account_id)
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1",
                        (EPOCH - timedelta(days=1),))
        conn.commit()
        yield conn


@pytest.fixture(params=list(Profile), ids=lambda p: p.value)
def world(request):
    w = AlpacaSimulator(request.param)
    yield w
    assert not w.faults


def ingest(conn, world):
    state = run(broker_cash.ingest_account_cash(
        conn, broker_adapter=world.adapter(), broker="alpaca",
        account_id=DEPLOY.broker_account_id, through=world.now))
    conn.commit()
    return state


def test_unknown_restart_reconciles_broker_fill_and_durable_cash_once(conn, pg, world):
    world.timeout(after_effect=True)
    sent = run(executor._persist_and_send(conn, world.adapter(), command()))
    assert sent.state is S.UNKNOWN
    world.fill(next(iter(world.orders)), "4", "100")
    world.fill(next(iter(world.orders)), "6", "105")
    with store.connect(pg.sync_dsn) as resumed:
        result = run(reconcile.reconcile(broker=world.adapter(), conn=resumed,
                     binding=None, deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.RUNNING, result.detail
        loaded = journal.load_commands(resumed, DEPLOY)
        assert len(loaded) == 1
        assert (loaded[0].state, loaded[0].filled_quantity,
                loaded[0].filled_average_price) == (S.FILLED, D(10), D(103))
        again = run(reconcile.reconcile(broker=world.adapter(), conn=resumed,
                    binding=None, deployment=DEPLOY))
        assert again.runtime_state is RuntimeState.RUNNING, again.detail
    assert world.counts[("POST", "/v2/orders")] == 1
    assert world.cash == D(98970)
    world.assert_conservation()


def test_crash_after_broker_acceptance_before_journal_ack_is_recovered(conn, pg, world):
    original = command()
    journal.save_command(conn, original)
    pending = recovery.prepare_send(original)
    journal.save_command(conn, pending, previous=S.PLANNED)
    # Production dispatch executes; its result is lost with client memory.
    run(recovery.dispatch(world.adapter(), pending))
    world.fill(next(iter(world.orders)))
    with store.connect(pg.sync_dsn) as resumed:
        assert journal.load_commands(resumed, DEPLOY)[0].state is S.SEND_PENDING
        result = run(reconcile.reconcile(broker=world.adapter(), conn=resumed,
                     binding=None, deployment=DEPLOY))
        assert result.runtime_state is RuntimeState.RUNNING, result.detail
        assert journal.load_commands(resumed, DEPLOY)[0].state is S.FILLED
    assert world.counts[("POST", "/v2/orders")] == 1


def test_corrupt_exact_response_cannot_mutate_unknown_journal(conn, world):
    world.timeout(after_effect=True)
    run(executor._persist_and_send(conn, world.adapter(), command()))
    before = journal.load_commands(conn, DEPLOY)[0]
    for occurrence in (1, 3):  # open + closed, repeated
        world.reply("GET", "/v2/orders", [], occurrence=occurrence)
    world.reply("GET", "/v2/orders:by_client_order_id", {})
    result = run(reconcile.reconcile(broker=world.adapter(), conn=conn,
                 binding=None, deployment=DEPLOY))
    assert result.runtime_state is RuntimeState.BROKER_DEGRADED
    assert journal.load_commands(conn, DEPLOY)[0] == before
    assert len(world.orders) == 1


def test_foreign_fill_is_reported_and_does_not_become_owned_history(conn, world):
    from test_alpaca_simulation_harness import submit
    world.fill(submit(world, key="human-order").broker_order_id)
    result = run(reconcile.reconcile(broker=world.adapter(), conn=conn,
                 binding=None, deployment=DEPLOY))
    assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY, result.detail
    assert not journal.load_commands(conn, DEPLOY)
    assert world.counts[("POST", "/v2/orders")] == 1


def test_cash_replay_across_restart_deduplicates_and_excludes_external_capital(conn, pg, world):
    for kind, amount in [("CSD", "10000"), ("CSW", "-3000"),
                          ("JNLC", "500"), ("DIV", "25"), ("FEE", "-2")]:
        world.cash_event(kind, amount, adversarial=True)
    initial = ingest(conn, world)
    with store.connect(pg.sync_dsn) as resumed:
        again = ingest(resumed, world)
        assert again == initial
        assert cashflow.net_external(resumed, EPOCH.date(), EPOCH.date()) == D(7500)
        assert cashflow.strategy_pl(resumed, start=EPOCH.date(), end=EPOCH.date(),
                                    opening_nav=D(100000), closing_nav=world.cash) == D(23)
        assert len(cashflow.flows_between(resumed, EPOCH.date(), EPOCH.date())) == 5
        # Candidate parser success is explicitly insufficient for a plan baseline.
        assert again.activity_identity_scheme is None
        with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="certified"):
            broker_cash.record_plan_baseline(resumed, plan_id="candidate-plan",
                decision_session=EPOCH.date(), activity_state=again)


def test_cash_correction_rolls_back_new_rows_and_preserves_cursor(conn, world):
    world.cash_event("CSD", "1000", adversarial=True)
    initial = ingest(conn, world)
    world.advance(60)
    world.cash_event("CSW", "-100", adversarial=True)
    # A vendor silently revises a stable native identity.
    world.events[0]["net_amount"] = "1001"
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="changed economics"):
        ingest(conn, world)
    conn.rollback()
    assert broker_cash.load_activity_state(conn, broker="alpaca",
              account_id=DEPLOY.broker_account_id) == initial
    assert len(cashflow.flows_between(conn, EPOCH.date(), EPOCH.date())) == 1


@pytest.mark.parametrize("missing", ["cursor", "ledger"])
def test_partial_cash_state_loss_refuses_recovery(conn, world, missing):
    world.cash_event("CSD", "1000", adversarial=True)
    ingest(conn, world)
    with conn.cursor() as cur:
        if missing == "cursor":
            cur.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-cash%'")
        else:
            cur.execute("DELETE FROM sentinel_cash_flows")
    conn.commit()
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused):
        ingest(conn, world)
    conn.rollback()


@pytest.mark.parametrize("amount", ["5000", "-5000"])
def test_deposit_or_withdrawal_during_plan_is_not_implicit_resizing(conn, world, amount):
    plan = ExecutionPlan(plan_id="cash-plan", decision_session=EPOCH.date(),
                         effective_session=(EPOCH + timedelta(days=1)).date(),
                         target_exposure=D(1), target_basket={"SEC-AAA": D(10)},
                         account_cash=D(100000), account_nav=D(100000),
                         broker="alpaca", broker_account_id=DEPLOY.broker_account_id)
    fingerprint = plan.fingerprint()
    world.cash_event("CSD" if D(amount) > 0 else "CSW", amount, adversarial=True)
    observation = run(world.adapter().observe())
    with pytest.raises(PaperActivationRefused, match="cash"):
        _cash_authority_or_refuse(conn, plan=plan, deployment=DEPLOY,
            account=run(world.adapter().account_snapshot()), observation=observation)
    assert plan.fingerprint() == fingerprint
    assert not world.orders
    rec = cashflow.reconcile_nav(conn, session=EPOCH.date(), previous_nav=D(100000),
                                observed_nav=world.cash, marked_pl=D(0))
    assert rec.attribution is cashflow.Attribution.UNEXPLAINED
    ingest(conn, world)
    rec = cashflow.reconcile_nav(conn, session=EPOCH.date(), previous_nav=D(100000),
                                observed_nav=world.cash, marked_pl=D(0))
    assert rec.attribution is cashflow.Attribution.DECLARED
    assert cashflow.strategy_pl(conn, start=EPOCH.date(), end=EPOCH.date(),
        opening_nav=D(100000), closing_nav=world.cash) == 0


def test_cash_cursor_never_rewinds_after_clock_rollback(conn, world):
    world.cash_event("CSD", "1000", adversarial=True)
    initial = ingest(conn, world)
    world.now -= timedelta(seconds=1)  # deliberately corrupt observation time
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="behind"):
        ingest(conn, world)
    conn.rollback()
    assert broker_cash.load_activity_state(conn, broker="alpaca",
        account_id=DEPLOY.broker_account_id) == initial
