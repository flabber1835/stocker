"""Transport falsifiers for scoped, automatically clearing action restrictions."""
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from sentinel.execution import executor, journal, reconcile as R
from sentinel.execution.commands import Command
from sentinel.execution.contract import Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.paper.reconciliation_evidence import _transport_observation_or_refuse

from test_projection_and_executor import (  # noqa: F401 - shared real PostgreSQL fixtures
    AAA, BBB, DEPLOY, INSTRUMENTS, TODAY, broker, conn, pg, plan, run)


def seed(conn, b, instrument=AAA, quantity="10"):
    b.seed_position(instrument, quantity)
    journal.save_command(conn, Command(
        identity=CommandIdentity(DEPLOY, "old-plan", instrument.security_id),
        instrument=instrument, side=Side.BUY, quantity=Decimal(quantity),
        state=CommandState.FILLED, filled_quantity=Decimal(quantity),
        created_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc)))
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_commands SET created_at=%s WHERE plan_id=%s AND security_id=%s",
                    (datetime(2026, 8, 10, 14, tzinfo=timezone.utc), "old-plan", instrument.security_id))
    conn.commit()


def execute(conn, b, basket, actions):
    p = replace(plan(), target_basket={sid: Decimal(qty) for sid, qty in basket.items()})
    executor.adopt_plan(conn, p)
    return run(executor.execute_session(
        broker=b, conn=conn, deployment=DEPLOY, plan=p,
        instruments=INSTRUMENTS, today=TODAY, actions=actions))


def split_actions():
    return R.CorpusActionLookup(
        start=date(2026, 8, 9), events={AAA.security_id: ((TODAY, Decimal(2)),)})


def test_paper_split_omission_defers_only_affected_buy(conn):
    b = broker()
    seed(conn, b)
    result = execute(conn, b, {AAA.security_id: "20", BBB.security_id: "5"}, split_actions())
    assert [c.security_id for c in result.submitted] == [BBB.security_id]
    assert AAA.security_id in result.deferred
    assert AAA.security_id in result.restricted_securities
    assert not result.reconciliation.clean
    assert result.reconciliation.transport_ready
    assert _transport_observation_or_refuse(result.reconciliation) is not None
    assert len(journal.load_commands(conn, DEPLOY, plan_id="plan-1")) == 1


def test_split_restriction_clears_without_acknowledgement(conn):
    b = broker()
    seed(conn, b)
    first = execute(conn, b, {AAA.security_id: "20"}, split_actions())
    assert first.submitted == ()
    assert first.restricted_securities
    b.seed_position(AAA, "20")
    second = execute(conn, b, {AAA.security_id: "20"}, split_actions())
    assert second.submitted == ()  # no compensating purchase or needless sale
    assert second.reconciliation.clean
    assert second.restricted_securities == {}


def test_restricted_sale_does_not_fund_another_purchase(conn):
    b = broker()
    seed(conn, b)
    result = execute(conn, b, {AAA.security_id: "0", BBB.security_id: "5"}, split_actions())
    assert result.submitted == ()
    assert set(result.deferred) == {AAA.security_id, BBB.security_id}
    assert "not submitted" in result.detail


def test_unrelated_reduction_runs_during_split_restriction(conn):
    b = broker()
    seed(conn, b)
    seed(conn, b, BBB, "5")
    result = execute(conn, b, {AAA.security_id: "20", BBB.security_id: "0"}, split_actions())
    assert [(c.security_id, c.side, c.quantity) for c in result.submitted] == [
        (BBB.security_id, Side.SELL, Decimal(5))]


def test_arbitrary_quantity_discrepancy_is_not_excused_by_split(conn):
    b = broker()
    seed(conn, b)
    b.seed_position(AAA, "13")
    rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                          deployment=DEPLOY, actions=split_actions()))
    assert rec.runtime_state is RuntimeState.FOREIGN_ACTIVITY
    assert rec.foreign_positions == (AAA.security_id,)
    assert not rec.transport_ready


def test_non_scalar_target_defers_only_that_security(conn):
    b = broker()
    event = R.CorporateActionEvent(
        security_id=AAA.security_id, ticker="AAA", session=TODAY,
        action="merger", value=None, contraticker="CCC",
        source_row_id="merger-source", reason="terms unavailable")
    actions = R.CorpusActionLookup(start=date(2026, 8, 10), events={}, unsupported_events=(event,))
    result = execute(conn, b, {AAA.security_id: "10", BBB.security_id: "5"}, actions)
    assert [c.security_id for c in result.submitted] == [BBB.security_id]
    assert AAA.security_id in result.deferred


def test_ordinary_book_does_not_need_negative_event_certificate(conn):
    b = broker()
    result = execute(conn, b, {AAA.security_id: "10"}, R.CorpusActionLookup(TODAY, {}))
    assert [c.quantity for c in result.submitted] == [Decimal(10)]
    key = result.submitted[0].client_key
    b.fill(key)
    retry = execute(conn, b, {AAA.security_id: "10"}, R.CorpusActionLookup(TODAY, {}))
    assert retry.submitted == ()
    assert len(journal.load_commands(conn, DEPLOY, plan_id="plan-1")) == 1


def test_material_notice_cannot_excuse_unattributed_broker_position(conn):
    b = broker()
    b.seed_position(AAA, "10")
    event = R.CorporateActionEvent(
        security_id=AAA.security_id, ticker="AAA", session=TODAY,
        action="merger", value=None, contraticker="CCC",
        source_row_id="merger-source", reason="terms unavailable")
    actions = R.CorpusActionLookup(
        start=date(2026, 8, 10), events={}, unsupported_events=(event,))
    rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                          deployment=DEPLOY, actions=actions))
    assert rec.runtime_state is RuntimeState.FOREIGN_ACTIVITY
    assert rec.foreign_positions == (AAA.security_id,)
    assert not rec.transport_ready
