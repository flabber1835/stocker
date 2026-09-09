"""Real PostgreSQL recovery for opening-sized paper command identity."""
import asyncio
from dataclasses import replace
from decimal import Decimal as D

import pytest

from sentinel.execution import executor, journal, opening_sizing
from sentinel.execution import target_reprojection as projections
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.plan import OpeningIntent
from sentinel.execution.simulator import FaultKind
from sentinel.execution.states import CommandState
from tests.sentinel.test_journal_and_reconcile import pg, DEPLOY, AAA
from tests.sentinel.test_projection_and_executor import broker, seed_held
from tests.support.postgres import drop_public_tables
from tests.v5.test_opening import case, base, prices


@pytest.fixture()
def conn(pg):
    from sentinel import binding, schema
    from sentinel.feed import store
    c = store.connect(pg.sync_dsn)
    try:
        drop_public_tables(c)
        schema.ensure_schema(c)
        store.migrate_schema(c)
        binding.bind(c, deployment_id=DEPLOY.deployment_id, broker=DEPLOY.broker,
                     broker_account_id=DEPLOY.broker_account_id)
        with c.cursor() as cur:
            cur.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1",
                        (broker().now,))
        c.commit()
        yield c
    finally:
        c.close()


def setup_plan(conn, **kwargs):
    env, plan = case(**kwargs)
    plan = replace(plan, deployment_id=DEPLOY.deployment_id, broker=DEPLOY.broker,
                   broker_account_id=DEPLOY.broker_account_id,
                   takeover_epoch=DEPLOY.takeover_epoch)
    plan = replace(plan, plan_id="sentinel-"+plan.fingerprint())
    executor.adopt_plan(conn, plan)
    return env, plan


def execute(conn, b, plan, projection, **kwargs):
    instruments = {"SEC-AAA": AAA, "SEC-X": BrokerInstrument("SEC-X", "X", "b-X")}
    return asyncio.run(executor.execute_session(conn=conn, broker=b,
        deployment=DEPLOY, plan=plan, instruments=instruments,
        today=plan.effective_session, target_projection=projection, **kwargs))


def test_opening_plan_round_trip_and_immutable_dollars(conn):
    env, plan = setup_plan(conn)
    restored = journal.load_plan(conn, plan.plan_id)
    assert restored == plan
    assert restored.fingerprint() == plan.fingerprint()
    changed = replace(plan, opening_intents=(OpeningIntent("SEC-AAA", 0, D(1)),))
    with pytest.raises(journal.PlanEconomicsChanged, match="opening_intents"):
        journal.save_plan(conn, changed)


def test_lost_opening_intent_record_refuses_plan_reload(conn):
    env, plan = setup_plan(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
                    (f"plan-opening-intents:v1:{plan.plan_id}",))
    conn.commit()
    with pytest.raises(journal.PlanAuthorityMissing, match="opening intent record"):
        journal.load_plan(conn, plan.plan_id)


def test_plan_and_dollar_intent_share_the_commit_boundary(conn):
    env, plan = case()
    journal.save_plan(conn, plan, commit=False)
    assert journal.load_plan(conn, plan.plan_id) == plan
    conn.rollback()
    assert journal.load_plan(conn, plan.plan_id) is None
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name=%s",
                    (f"plan-opening-intents:v1:{plan.plan_id}",))
        assert cur.fetchone()[0] == 0


def test_pending_entry_requires_durable_sizing_before_broker_calls(conn):
    env, plan = setup_plan(conn)
    b = broker()
    with pytest.raises(ValueError, match="opening-time projection"):
        execute(conn, b, plan, None)
    assert b.calls == []
    assert journal.load_commands(conn, DEPLOY) == ()


def test_unit_projection_cannot_erase_unresolved_entry(conn):
    env, plan = setup_plan(conn)
    unit_only = projections.record_projection(conn, base(env, plan))
    b = broker()
    with pytest.raises(projections.TargetProjectionRefused, match="sizing evidence"):
        execute(conn, b, plan, unit_only)
    assert b.calls == []


def test_unknown_submission_restart_keeps_original_open_price_and_quantity(conn):
    env, plan = setup_plan(conn)
    original = prices(env, plan, price="50")
    projection = projections.record_projection(conn,
        opening_sizing.resolve(env, plan, base(env, plan), original))
    b = broker()
    b.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)
    first = execute(conn, b, plan, projection)
    assert [(c.quantity, c.state) for c in first.submitted] == [(D(99), CommandState.UNKNOWN)]
    restored_plan = journal.load_plan(conn, plan.plan_id)
    restored = projections.load_projection(conn, plan_id=plan.plan_id)
    retained = asyncio.run(opening_sizing.prices_for_plan(conn, state=env,
        plan=restored_plan, broker=object()))
    assert retained == original
    assert opening_sizing.resolve(env, restored_plan, base(env, restored_plan), retained) == restored
    second = execute(conn, b, restored_plan, restored)
    assert second.submitted == ()
    assert len([call for call in b.calls if call.startswith("submit:")]) == 1
    assert journal.load_commands(conn, DEPLOY)[0].quantity == 99
    changed = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan, price="200"))
    with pytest.raises(projections.TargetProjectionRefused, match="immutable"):
        projections.record_projection(conn, changed)


def test_opening_buy_waits_for_pending_sale_settlement_and_recovers(conn):
    env, plan = setup_plan(conn, cash=100., sale=True)
    b = broker()
    seed_held(conn, b, BrokerInstrument("SEC-X", "X", "b-X"), 10)
    projection = projections.record_projection(conn,
        opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan)))
    first = execute(conn, b, plan, projection, settle_cycles=1)
    assert [(c.security_id, c.side) for c in first.submitted] == [("SEC-X", Side.SELL)]
    assert "SEC-AAA" in first.deferred
    b.fill(first.submitted[0].client_key)
    restored = projections.load_projection(conn, plan_id=plan.plan_id)
    second = execute(conn, b, journal.load_plan(conn, plan.plan_id), restored, settle_cycles=1)
    assert [(c.security_id, c.side, c.quantity) for c in second.submitted] == [
        ("SEC-AAA", Side.BUY, D(10))]
