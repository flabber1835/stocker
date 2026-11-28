"""PAPER cash attribution and restart using the actual reservation and journal."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sentinel import schema
from sentinel.execution import journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerFill, BrokerInstrument, BrokerObservation, BrokerOrder, BrokerPosition, Side
from sentinel.execution.fractional_progress import PostingFunds
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE
from sentinel.paper import market_reservations as funding
from tests.sentinel.test_order_terms_schema import database, pg, _compiled
from tests.sentinel.test_parallel_open_rehearsal import pg as backed_exit_pg
from tests.v5.test_opening import case, EFFECTIVE_SESSION


DEPLOY = DeploymentIdentity("reserved-account", "alpaca", "TEST", 1)
ACCOUNT = BrokerAccountIdentity("alpaca", "TEST")
NOW = datetime(EFFECTIVE_SESSION.year, EFFECTIVE_SESSION.month, EFFECTIVE_SESSION.day, 13, 35, tzinfo=timezone.utc)
FUNDS = PostingFunds(D(100), D(100), D(0), D(5))


def command(plan, sid, *, amount="45", side=Side.BUY):
    return Command(CommandIdentity(DEPLOY, plan.plan_id, sid), BrokerInstrument(sid, sid, sid + "-asset"),
        side, quantity=D(1) if side is Side.SELL else None, notional=D(amount) if side is Side.BUY else None)


def native(c, **kwargs):
    return BrokerOrder(c.broker_order_id or c.security_id, c.client_key, c.instrument, c.side,
        kwargs.pop("state", S.ACKNOWLEDGED), c.quantity, notional=c.notional, **kwargs)


def book(*orders):
    return BrokerObservation(observed_at=NOW, account_identity=ACCOUNT, orders=tuple(orders))


def result(observation):
    return SimpleNamespace(observation=observation, observation_id=1, transport_ready=True, restricted_securities={})


@pytest.fixture
def subject(database):
    schema.ensure_schema(database)
    _, plan = case()
    plan = replace(plan, deployment_id=DEPLOY.deployment_id, broker=DEPLOY.broker,
        broker_account_id=DEPLOY.broker_account_id, takeover_epoch=DEPLOY.takeover_epoch, target_exposure=D(0))
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    journal.save_plan(database, plan)
    projection = SimpleNamespace(opening_sizing={"mode": FRACTIONAL_MODE, "purchases": {"SENTINEL:BIL": {"budget": "100"}}},
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(), through_session=plan.effective_session,
        target_basket={"SENTINEL:BIL": D(0)}, pending_share_targets={},
        fingerprint=lambda: "projection")
    return {"plan": plan, "projection": projection, "deployment": DEPLOY}


def enroll(conn, commands, subject, observation, funds=FUNDS, sells=()):
    journal.reserve_planned_commands(conn, commands)
    return funding.reserve(conn, commands, **subject, reconciliation=result(observation), funds=funds,
                           activity=None, sells=sells)


def transition(conn, c, state, **kwargs):
    updated = replace(c, state=state, **kwargs)
    journal.save_command(conn, updated, previous=c.state)
    return updated


def test_overallocation_leaves_no_reservation_or_partial_journal(database, subject):
    plan = subject["plan"]
    commands = (command(plan, "AAA", amount="47"), command(plan, "BBB", amount="47"))
    with journal.writer_lock(database, recovery_only=True):
        with pytest.raises(OrderEvidenceNotReady, match="headroom exceed"):
            enroll(database, commands, subject, book())
        database.rollback()
        assert funding.load(database, plan) is None
        assert not journal.load_commands(database, DEPLOY, plan_id=plan.plan_id)


def test_new_basket_retains_prior_funding_and_detects_damaged_history(database, subject):
    from sentinel.execution import market_reservation_record as record
    from sentinel.execution.protected_funding import _sha
    from sentinel.execution.target_reprojection import TargetProjectionRefused
    plan = subject["plan"]
    first, second = (command(plan, sid) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        original = enroll(database, (first,), subject, book())
        database.commit()
        transition(database, first, S.SUPERSEDED)
        current = enroll(database, (second,), subject, book())
        database.commit()
        key = record.PREFIX + "history:" + _sha(original)
        assert database.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (key,)).fetchone()[0] == original
        assert funding.load(database, plan) == current
        database.execute("UPDATE sentinel_processed_sessions SET state='{}'::jsonb WHERE cursor_name=%s",
                         (record.PREFIX + "history:" + _sha(current),))
        with pytest.raises(TargetProjectionRefused, match="invalid immutable"):
            funding.load(database, plan)


@pytest.mark.parametrize("problem", ["", "foreign", "unknown", "unexplained_hold", "partial_hold", "cash_drift", "position_drift"])
def test_reserved_restart_checks_current_native_cash_and_all_working_orders(database, subject, problem):
    plan = subject["plan"]
    first, second = (command(plan, sid) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        enroll(database, (first, second), subject, book())
        database.commit()
    with journal.writer_lock(database, recovery_only=True):
        retained = funding.load(database, plan)
        first = transition(database, first, S.SEND_PENDING)
        first = transition(database, first, S.UNKNOWN if problem == "unknown" else S.ACKNOWLEDGED,
                           broker_order_id="owned")
        observation = book(native(first))
        if problem == "unknown":
            with pytest.raises(OrderEvidenceNotReady):
                funding.remaining_keys(database, basis=retained, **subject, reconciliation=result(observation))
        else:
            assert funding.remaining_keys(database, basis=retained, **subject, reconciliation=result(observation)) == {
                second.client_key}
        second = transition(database, second, S.SEND_PENDING)
        if problem == "foreign":
            observation = book(native(first), replace(native(first), client_key="foreign", broker_order_id="foreign"))
        if problem == "position_drift":
            observation = replace(observation, positions=(BrokerPosition(first.instrument, D(1)),))
        broker = SimpleNamespace(observe=AsyncMock(return_value=observation))
        account = BrokerAccountSnapshot(ACCOUNT, D(100), D(99 if problem == "cash_drift" else 100),
            D({"unexplained_hold": 50, "partial_hold": 70}.get(problem, 55)), D(1), "ACTIVE")
        proof = funding.prove(database, basis=retained, **subject, broker=broker, account=account,
                              activity=None, candidate_key=second.client_key)
        if problem:
            with pytest.raises(OrderEvidenceNotReady):
                asyncio.run(proof)
        else:
            assert asyncio.run(proof) is observation


def test_nineteen_fills_one_partial_bil_and_last_sale_at_0715_after_restart(database, subject):
    plan = subject["plan"]
    sales = [command(plan, f"SALE{i:02}", side=Side.SELL) for i in range(19)]
    working = command(plan, "LAST", side=Side.SELL)
    bil = command(plan, "SENTINEL:BIL", amount="94")
    with journal.writer_lock(database, recovery_only=True):
        for c in [*sales, working]:
            journal.save_command(database, c)
            transition(database, c, S.SEND_PENDING)
        for c in sales:
            transition(database, replace(c, state=S.SEND_PENDING), S.FILLED, broker_order_id=c.security_id,
                       filled_quantity=D(1), filled_average_price=D(5))
            journal.record_fills(database, [BrokerFill(c.client_key, c.security_id, D(1), D(5), NOW)])
        working = transition(database, replace(working, state=S.SEND_PENDING), S.ACKNOWLEDGED, broker_order_id="last")
        observation = book(native(working))
        assert funding.defensive_sells(database, **subject, observation=observation) == [working.client_key]
        assert funding.defensive_sells(database, **subject, observation=book(
            replace(native(working), client_key="foreign"))) is None
        enroll(database, (bil,), subject, observation, sells=[working.client_key])
        database.commit()
    with journal.writer_lock(database, recovery_only=True):
        basis = funding.load(database, plan)
        assert funding.remaining_keys(database, basis=basis, **subject, reconciliation=result(observation)) == {bil.client_key}
        assert not funding.sweep_attempted(database, basis=basis, deployment=DEPLOY, plan=plan)
        pending = transition(database, bil, S.SEND_PENDING)
        assert funding.sweep_attempted(database, basis=basis, deployment=DEPLOY, plan=plan)
        broker = SimpleNamespace(observe=AsyncMock(return_value=observation))
        params = dict(basis=basis, **subject, broker=broker, activity=None, candidate_key=bil.client_key,
                      account=BrokerAccountSnapshot(ACCOUNT, D(100), D(100), D(100), D(1), "ACTIVE"))
        assert asyncio.run(funding.prove(database, **params, sweep_due=True)) is observation
        with pytest.raises(OrderEvidenceNotReady, match="window closed"):
            asyncio.run(funding.prove(database, **params, sweep_due=False))
        from sentinel.execution.market_reservation_record import completed_partial_sweep
        bil_fill = transition(database, pending, S.FILLED, broker_order_id="bil", filled_quantity=D(1),
                              filled_average_price=D(94))
        journal.record_fills(database, [BrokerFill(bil.client_key, "bil", D(1), D(94), NOW + timedelta(minutes=4))])
        assert completed_partial_sweep(database, command=bil_fill, projection=subject["projection"], deployment=DEPLOY)
    with journal.writer_lock(database, recovery_only=True):
        from sentinel.execution import fractional_progress
        last_fill = NOW.replace(hour=14, minute=15)  # 07:15 Pacific on the effective session.
        transition(database, working, S.FILLED, filled_quantity=D(1), filled_average_price=D(5))
        journal.record_fills(database, [BrokerFill(working.client_key, "last", D(1), D(5), last_fill)])
        retained = funding.load(database, plan)
        assert funding.sweep_attempted(database, basis=retained, deployment=DEPLOY, plan=plan)
        progress = fractional_progress.derive(database, projection=subject["projection"], deployment=DEPLOY,
                                              require_terminal=True)
        assert progress.acquired_targets["SENTINEL:BIL"] == 1
        assert not progress.blocked and "SENTINEL:BIL" not in progress.budgets
        history = journal.load_commands(database, DEPLOY, plan_id=plan.plan_id)
        assert len([c for c in history if c.side is Side.SELL and c.state is S.FILLED]) == 20
        assert [c.client_key for c in history if c.side is Side.BUY] == [bil.client_key]


def test_terminal_native_fill_can_fund_sibling_without_recycling_cash(database, subject):
    from sentinel.execution.alpaca import NativeBrokerFill
    plan = subject["plan"]
    first, second = (command(plan, sid) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        basis = enroll(database, (first, second), subject, book())
        database.commit()
        transition(database, first, S.SEND_PENDING)
        transition(database, second, S.SEND_PENDING)
        when = NOW - timedelta(seconds=5)
        order = native(first, state=S.FILLED, filled_quantity=D(3), filled_average_price=D(15),
                       submitted_at=when)
        observation = replace(book(order), positions=(BrokerPosition(first.instrument, D(3)),))
        fill = NativeBrokerFill(first.client_key, order.broker_order_id, D(3), D(15), when,
            activity_id="fill", asset_id=first.instrument.broker_id, side=Side.BUY, cash_amount=D(-45))
        broker = SimpleNamespace(observe=AsyncMock(return_value=observation), supports_owned_order_fills=True,
                                 owned_order_fills=AsyncMock(return_value=(fill,)))
        params = dict(basis=basis, **subject, broker=broker, activity=None, candidate_key=second.client_key)
        account = BrokerAccountSnapshot(ACCOUNT, D(100), D(55), D(55), D(1), "ACTIVE")
        assert asyncio.run(funding.prove(database, **params, account=account)) is observation
        with pytest.raises(OrderEvidenceNotReady, match="posted purchases"):
            asyncio.run(funding.prove(database, **params, account=replace(account, cash=D(56))))
        broker.owned_order_fills.return_value = ()
        with pytest.raises(OrderEvidenceNotReady, match="confirmed native fill cash"):
            asyncio.run(funding.prove(database, **params, account=account))


@pytest.mark.parametrize("previous", [S.SEND_PENDING, S.ACKNOWLEDGED])
@pytest.mark.parametrize("owned", [True, False])
def test_completed_order_absent_from_open_list_before_next_buy(database, subject, previous, owned):
    from sentinel.execution.alpaca import NativeBrokerFill
    from sentinel.execution.contract import BrokerExactOrderLookup

    plan = subject["plan"]
    first, second = (command(plan, sid) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        basis = enroll(database, (first, second), subject, book())
        database.commit()
        first = transition(database, first, S.SEND_PENDING)
        transition(database, second, S.SEND_PENDING)
        order = native(first, state=S.FILLED, filled_quantity=D(3), filled_average_price=D(15),
                       submitted_at=NOW - timedelta(seconds=5))
        if previous is S.ACKNOWLEDGED:
            transition(database, first, previous, broker_order_id=order.broker_order_id)
        held = first.instrument if owned else command(plan, "FOREIGN").instrument
        observation = replace(book(), positions=(BrokerPosition(held, D(3)),))
        lookup = BrokerExactOrderLookup(first.client_key, NOW, NOW, ACCOUNT, ACCOUNT, order)
        fill = NativeBrokerFill(first.client_key, order.broker_order_id, D(3), D(15), NOW,
            activity_id="native-fill", asset_id=first.instrument.broker_id, side=Side.BUY, cash_amount=D(-45))
        broker = SimpleNamespace(observe=AsyncMock(return_value=observation), supports_owned_order_fills=True,
            find_by_client_key=AsyncMock(return_value=lookup), owned_order_fills=AsyncMock(return_value=(fill,)))
        params = dict(basis=basis, **subject, broker=broker, activity=None, candidate_key=second.client_key,
            terminal_receipts={}, account=BrokerAccountSnapshot(ACCOUNT, D(100), D(55), D(55), D(1), "ACTIVE"))
        if owned:
            assert asyncio.run(funding.prove(database, **params)) is observation
            # A later buy must see fresh economics even with the verified terminal identity.
            broker.owned_order_fills.return_value = ()
            with pytest.raises(OrderEvidenceNotReady, match="confirmed native fill cash"):
                asyncio.run(funding.prove(database, **params))
            assert broker.owned_order_fills.await_count == 2
        else:
            with pytest.raises(OrderEvidenceNotReady, match="holdings"):
                asyncio.run(funding.prove(database, **params))
        broker.find_by_client_key.assert_awaited_once_with(first.client_key)


@pytest.mark.parametrize("settles", [True, False])
def test_one_complete_reread_when_native_account_changes_during_funding(database, subject, settles):
    from sentinel.execution.contract import Completeness

    plan = subject["plan"]
    candidate = command(plan, "AAA")
    account = BrokerAccountSnapshot(ACCOUNT, D(100), D(100), D(100), D(1), "ACTIVE")
    unstable = replace(book(), completeness=Completeness.INCONSISTENT)
    stable = book()
    reader = SimpleNamespace(account_snapshot=AsyncMock(return_value=account),
                             observe=AsyncMock(return_value=stable if settles else unstable))
    with journal.writer_lock(database, recovery_only=True):
        basis = enroll(database, (candidate,), subject, book())
        database.commit()
        transition(database, candidate, S.SEND_PENDING)
        operation = funding.current_book(database, binding=SimpleNamespace(identity=DEPLOY), expected_account="TEST",
            account=account, clock=lambda: NOW, basis=basis, broker=reader, plan=plan, projection=subject["projection"],
            candidate_key=candidate.client_key, settled_observation=unstable, sweep_due=lambda: False)
        if settles:
            assert asyncio.run(operation) is stable
        else:
            with pytest.raises(funding.ReservationBookChanged):
                asyncio.run(operation)
        reader.account_snapshot.assert_awaited_once()
        reader.observe.assert_awaited_once()


@pytest.mark.parametrize("change,replays", [("none", 0), ("gap", 1), ("prior_order_event", 1), ("new_scope", 1)])
def test_native_activity_cursor_carries_only_unchanged_terminal_cash(change, replays):
    from sentinel.execution.alpaca import NativeBrokerFill
    from sentinel.execution.trade_activity_window import TradeWindow

    _, plan = case()
    commands = [command(plan, sid) for sid in ("AAA", "BBB")]
    orders = [native(c, state=S.FILLED, filled_quantity=D(3), filled_average_price=D(15),
                     submitted_at=NOW-timedelta(seconds=10)) for c in commands]
    fills = [NativeBrokerFill(o.client_key, o.broker_order_id, D(3), D(15), NOW-timedelta(seconds=3),
            activity_id="fill-"+o.client_key, asset_id=o.instrument.broker_id, side=Side.BUY, cash_amount=D(-45))
             for o in orders]
    raw = [{"details":{"order_id":f.broker_order_id, "client_order_id":f.client_key, "execution_type":"fill"},
            "ref_id":f.activity_id, "at":NOW.isoformat()} for f in fills]
    decode = {f.activity_id:f for f in fills}
    scope = ("plan","projection",("alpaca","TEST","test-native"),None)
    cache = funding.VerifiedFillCash()
    broker = SimpleNamespace(supports_owned_order_fills=True, owned_order_fills=AsyncMock())
    observation = book(*orders)
    inputs = dict(broker=broker, commands={c.client_key:c for c in commands}, observation=observation,cache=cache)
    window = TradeWindow(scope[2],None,"head-1",NOW,(raw[0],),lambda row:decode[row["ref_id"]])
    start,cached = asyncio.run(funding._filled_cash(orders[:1], **inputs,window=window,scope=scope))
    assert start == {commands[0].client_key:-45}
    broker.owned_order_fills.assert_not_awaited()
    cache.scope,cache.cursor,cache.through,cache.terminal=scope,"head-1",NOW,cached
    recent = tuple(raw if change=="prior_order_event" else raw[1:])
    next_window = replace(window,after="unseen" if change=="gap" else "head-1", cursor="head-2",trades=recent)
    async def fetch(*,orders,**kw):
        assert [o.client_key for o in orders]==[commands[0].client_key]
        return (fills[0],)
    broker.owned_order_fills.side_effect=fetch
    scope = ("unrelated", *scope[1:]) if change=="new_scope" else scope
    debits,verified = asyncio.run(funding._filled_cash(orders,**inputs,window=next_window,scope=scope))
    assert debits==dict.fromkeys((c.client_key for c in commands),-45) and len(verified)==2
    assert broker.owned_order_fills.await_count==replays


def test_broken_event_contiguity_guard_is_detected(monkeypatch):
    monkeypatch.setattr(funding, "_filled_cash", _compiled(funding._filled_cash,"cache.cursor == window.after","True"))
    with pytest.raises(AssertionError):
        test_native_activity_cursor_carries_only_unchanged_terminal_cash("gap",1)


def test_native_window_binds_account_time_frontier_and_refuses_amendments():
    from sentinel.execution import trade_activity_window as native
    account = ("alpaca","TEST","native-uuid")
    batch = SimpleNamespace(native_account=account,trade_amendments=(),processed_through=NOW,last_event_id="x")
    state = SimpleNamespace(broker="alpaca",account_id="TEST",processed_through=NOW,last_event_id="x")
    observation = replace(book(),account_identity=BrokerAccountIdentity(*account[:2],raw={"id":account[2]}))
    with native.capture() as captured:
        native.observe(batch=batch,after=None,events=[],decode=lambda x:x)
        window, = captured
        assert window.covers(state,observation)
        assert not replace(window,cursor="others").covers(state,observation)
        assert not replace(window,account=("alpaca","TEST","wrong-uuid")).covers(state,observation)
        assert not window.covers(state,replace(observation,observed_at=NOW+timedelta(microseconds=1)))
    batch.trade_amendments=(object(),)
    with native.capture() as captured:
        native.observe(batch=batch,after="x",events=[],decode=lambda x:x)
        assert not captured


def test_real_cash_adapter_shares_only_fresh_native_trade_publications():
    from sentinel.execution import trade_activity_window
    from tests.sentinel.test_alpaca_trade_amendments import _adapter, _trade, START, UPPER, ACCOUNT_UUID
    first, second = _trade(1), _trade(2)
    broker, _ = _adapter(first, second)
    with trade_activity_window.capture() as captured:
        result = asyncio.run(broker.account_cash_activities(after=START, through=UPPER,
            since_event_id=first["event_id"]))
        window, = captured
    assert result.native_account[2] == ACCOUNT_UUID
    assert window.after == first["event_id"] and window.cursor == second["event_id"]
    assert [row["event_id"] for row in window.trades] == [second["event_id"]]
    fill, = window.fills(window.trades)
    assert fill.activity_id == second["ref_id"] and fill.cash_amount == D("-112.50")


def test_confirmed_rejection_does_not_block_independently_reserved_sibling(database, subject):
    from sentinel.execution.contract import BrokerExactOrderLookup
    plan = subject["plan"]
    first, second = (command(plan, sid) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        basis = enroll(database, (first, second), subject, book())
        database.commit()
        first = transition(database, first, S.SEND_PENDING)
        transition(database, first, S.REJECTED)
        transition(database, second, S.SEND_PENDING)
        lookup = BrokerExactOrderLookup(first.client_key, NOW, NOW, ACCOUNT, ACCOUNT, None)
        broker = SimpleNamespace(observe=AsyncMock(return_value=book()), find_by_client_key=AsyncMock(return_value=lookup))
        params = dict(basis=basis, **subject, broker=broker, activity=None, candidate_key=second.client_key,
                      account=BrokerAccountSnapshot(ACCOUNT, D(100), D(100), D(100), D(1), "ACTIVE"))
        assert asyncio.run(funding.prove(database, **params)) == book()
        wrong = BrokerAccountIdentity("alpaca", "another account")
        broker.find_by_client_key.return_value = replace(lookup, identity_before=wrong, identity_after=wrong)
        with pytest.raises(OrderEvidenceNotReady, match="changed account"):
            asyncio.run(funding.prove(database, **params))


def test_recovery_routes_only_current_observed_work_and_original_window(database, subject, monkeypatch):
    from sentinel.execution import target_reprojection
    from sentinel.automation.model import ExecuteDisposition
    from tests.sentinel.test_market_buy_policy import MARKET_ENV
    for key, val in {**MARKET_ENV, "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE}.items():
        monkeypatch.setenv(key, val)
    plan = subject["plan"]
    cfg = SimpleNamespace(debug_window_for=lambda cycle: None, maximum_execution_lateness_seconds=600)
    cycle = SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(), execute_at=NOW,
                            execution_open_at=NOW, execution_close_at=NOW + timedelta(hours=6))
    monkeypatch.setattr(target_reprojection, "load_projection", lambda *a, **kw: subject["projection"])
    first, second = (command(plan, sid) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        enroll(database, (first, second), subject, book())
        database.commit()
        first = transition(database, first, S.SEND_PENDING)
        first = transition(database, first, S.ACKNOWLEDGED, broker_order_id="owned")

        def route(seconds, *orders, age=0):
            when = NOW + timedelta(seconds=seconds)
            rec = result(replace(book(*orders), observed_at=when - timedelta(seconds=age)))
            rec.clean, rec.cash_plan_superseded = True, False
            return funding.recovery_route(database, cycle=cycle, deployment=DEPLOY, reconciliation=rec,
                config=cfg, now=when, in_flight=journal.in_flight_commands(database, DEPLOY))

        assert route(120, native(first)).disposition is ExecuteDisposition.READY_TO_EXECUTE
        assert route(600, native(first)).disposition is ExecuteDisposition.RECONCILE
        assert route(120, native(first), age=61) is None
        assert route(120, replace(native(first), broker_order_id="different")) is None
        assert route(120) is None


def test_native_hold_falsifier_detects_removed_attribution(database, subject, monkeypatch):
    monkeypatch.setattr(funding, "prove", _compiled(funding.prove,
        "if abs(gap) > 1 and abs(gap - holds) > 1:", "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_reserved_restart_checks_current_native_cash_and_all_working_orders(database, subject, "partial_hold")


def test_restart_continues_independent_sales_without_waiting_for_previous_fill(database, subject, monkeypatch):
    from sentinel.automation.model import ExecuteDisposition
    from sentinel.execution import target_reprojection
    from tests.sentinel.test_market_buy_policy import MARKET_ENV
    for key, val in {**MARKET_ENV, "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE}.items():
        monkeypatch.setenv(key, val)
    plan = subject["plan"]
    cfg = SimpleNamespace(debug_window_for=lambda cycle: None, maximum_execution_lateness_seconds=600)
    cycle = SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(), execute_at=NOW,
                            execution_open_at=NOW, execution_close_at=NOW + timedelta(hours=6))
    monkeypatch.setattr(target_reprojection, "load_projection", lambda *a, **kw: subject["projection"])
    first, second = (command(plan, sid, side=Side.SELL) for sid in ("AAA", "BBB"))
    with journal.writer_lock(database, recovery_only=True):
        journal.save_command(database, first)
        first = transition(database, first, S.SEND_PENDING)
        first = transition(database, first, S.PARTIALLY_FILLED, broker_order_id="one",
                           filled_quantity=D(".5"), filled_average_price=D(10))
        order = native(first, state=S.PARTIALLY_FILLED, filled_quantity=D(".5"), filled_average_price=D(10))

        def route(at, order, *, uncertain=False, include_unsent=True):
            rec = result(replace(book(order), observed_at=at, positions=(BrokerPosition(first.instrument, D(".5")),
                                                                       BrokerPosition(second.instrument, D(1)))))
            rec.clean, rec.cash_plan_superseded = True, False
            commands = (replace(first, state=S.UNKNOWN),) if uncertain else (first,)
            return funding.recovery_route(database, cycle=cycle, deployment=DEPLOY, reconciliation=rec, config=cfg,
                now=at, in_flight=commands, actionable_deltas=lambda _: [second] if include_unsent else [])

        for at in (NOW, NOW + timedelta(minutes=45)):
            restored = route(at, order)
            assert restored.disposition is ExecuteDisposition.READY_TO_EXECUTE
            assert restored.reduction_only_continuation and restored.reduction_only_required
            assert restored.diagnostic["remaining_reductions"] == ["BBB"]
        assert route(NOW, replace(order, client_key="foreign")) is None
        assert route(NOW, order, uncertain=True) is None
        assert route(NOW, order, include_unsent=False).disposition is ExecuteDisposition.RECONCILE
        assert route(NOW + timedelta(seconds=539), order, include_unsent=False).disposition is ExecuteDisposition.RECONCILE
        staged = route(NOW + timedelta(seconds=540), order, include_unsent=False)
        assert staged.disposition is ExecuteDisposition.READY_TO_EXECUTE and not staged.reduction_only_required
        assert route(NOW + timedelta(seconds=600), order, include_unsent=False).disposition is ExecuteDisposition.RECONCILE
        assert route(cycle.execution_close_at, order).disposition is ExecuteDisposition.RECONCILE


@pytest.fixture
def backed_exit_database(backed_exit_pg):
    import psycopg
    from tests.support.postgres import drop_public_tables
    with psycopg.connect(backed_exit_pg.sync_dsn) as connection:
        drop_public_tables(connection)
        yield connection


def test_live_nineteen_sales_never_release_partial_bil_and_last_fill_is_observed_at_0715(backed_exit_database, monkeypatch):
    from sentinel.automation.model import ExecuteDisposition
    from sentinel.execution import executor, reconcile, target_reprojection
    from sentinel.execution.contract import BrokerCapabilities, BrokerExactOrderLookup
    from sentinel.execution.plan import ExecutionPlan
    from sentinel.execution.states import RuntimeState
    from tests.sentinel.test_live_reduction_fallback import INCREMENT
    from tests.sentinel.test_production_decision import DECISION_SESSION

    database = backed_exit_database
    live = DeploymentIdentity("live-defensive-rehearsal", "alpaca-live", "private", 1)
    identity = BrokerAccountIdentity(live.broker, live.broker_account_id)
    symbols = [f"SALE{i:02}" for i in range(20)]
    instruments = {s: BrokerInstrument(s, s, s + "-native") for s in [*symbols, "SENTINEL:BIL"]}
    plan = ExecutionPlan("live-exit", DECISION_SESSION, EFFECTIVE_SESSION, D(0),
        deployment_id=live.deployment_id, broker=live.broker, broker_account_id=live.broker_account_id,
        takeover_epoch=live.takeover_epoch, target_basket={**dict.fromkeys(symbols, D(0)), "SENTINEL:BIL": D("2.25")})
    schema.ensure_schema(database)
    from sentinel import binding
    binding.bind(database, deployment_id=live.deployment_id, broker=live.broker, broker_account_id=live.broker_account_id)
    journal.save_plan(database, plan)
    projection = target_reprojection.project_target(plan, through_session=EFFECTIVE_SESSION,
        action_multipliers={}, minimum_quantity_increment=INCREMENT)
    target_reprojection.record_projection(database, projection)
    cfg = SimpleNamespace(debug_window_for=lambda cycle: None, maximum_execution_lateness_seconds=600)
    opened = NOW - timedelta(minutes=5)
    cycle = SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(), execute_at=opened,
                            execution_open_at=opened, execution_close_at=opened + timedelta(hours=6))
    with journal.writer_lock(database, recovery_only=True):
        for i, sid in enumerate(symbols):
            sale = Command(CommandIdentity(live, plan.plan_id, sid), instruments[sid], Side.SELL, quantity=D("1.25"))
            journal.save_command(database, sale)
            pending = transition(database, sale, S.SEND_PENDING)
            last = transition(database, pending, S.ACKNOWLEDGED, broker_order_id="owned-" + sid)
            if i == 3:
                from sentinel.automation_runtime import _actionable_projection_deltas
                positions = tuple(BrokerPosition(instruments[s], sale.quantity) for s in symbols[i:])
                earlier_book = replace(book(native(last)), account_identity=identity, positions=positions)
                early = reconcile.ReconciliationResult(RuntimeState.RUNNING, observation=earlier_book, observation_id=8)
                recovered = funding.recovery_route(database, cycle=cycle, deployment=live, reconciliation=early,
                    config=cfg, now=NOW, in_flight=journal.in_flight_commands(database, live),
                    actionable_deltas=lambda p: _actionable_projection_deltas(database, plan=p,
                        effective_session=EFFECTIVE_SESSION, observation=earlier_book, minimum_quantity_increment=INCREMENT))
                assert recovered.reduction_only_required and recovered.reduction_only_continuation
                assert set(recovered.diagnostic["remaining_reductions"]) == set(symbols[4:])
            if i < 19:
                transition(database, last, S.FILLED, filled_quantity=sale.quantity, filled_average_price=D(100))
                journal.record_fills(database, [BrokerFill(sale.client_key, last.broker_order_id, sale.quantity, D(100), NOW)])
    observation = replace(book(native(last)), account_identity=identity, positions=(BrokerPosition(last.instrument, last.quantity),),
                          observed_at=opened + timedelta(minutes=9, seconds=30))
    rec = reconcile.ReconciliationResult(RuntimeState.RUNNING, observation=observation, observation_id=10,
                                         expected={last.security_id: last.quantity}, observed={last.security_id: last.quantity})
    market_clock = [observation.observed_at]
    async def lookup_sale(key):
        assert key == last.client_key
        market_clock[0] = opened + timedelta(minutes=10)
        return BrokerExactOrderLookup(key, observation.observed_at, market_clock[0], identity, identity, native(last))

    broker = SimpleNamespace(capabilities=BrokerCapabilities(stable_client_key=True, single_order_cancel=True,
        fractional_quantities=True, minimum_quantity_increment=INCREMENT), identify_account=AsyncMock(return_value=identity),
        find_by_client_key=lookup_sale,
        submit=AsyncMock(side_effect=AssertionError("LIVE cannot stage a partial BIL")))
    monkeypatch.setattr(reconcile, "reconcile", AsyncMock(return_value=rec))
    from sentinel.execution import alpaca
    monkeypatch.setattr(alpaca, "upgrade_restore_reason", lambda _: "")
    monkeypatch.setattr(alpaca, "execution_increase_fence_reason", lambda **_: "")
    session = asyncio.run(executor.execute_session(conn=database, deployment=live, broker=broker, plan=plan,
        instruments=instruments, today=EFFECTIVE_SESSION, target_projection=projection, min_increment=INCREMENT,
        settle_cycles=1, market_buy_window_open=lambda: market_clock[0] < opened + timedelta(minutes=10)))
    assert "SENTINEL:BIL" in session.deferred and not session.submitted, (session.detail, session.refused)
    before = journal.in_flight_commands(database, live)
    assert [c.client_key for c in before] == [last.client_key]
    for when in (observation.observed_at, opened + timedelta(minutes=44, seconds=59)):
        rec.observation = replace(observation, observed_at=when)
        route = funding.recovery_route(database, cycle=cycle, deployment=live, reconciliation=rec,
            config=cfg, now=when, in_flight=before)
        assert route.disposition is ExecuteDisposition.RECONCILE
        assert route.failure_code == "OWNED_MARKET_ORDERS_WORKING"
    late = opened + timedelta(minutes=45)
    assert late.hour == 14 and late.minute == 15  # 07:15 Pacific.
    # The broker's DAY sale still exists; the opening deadline only cut off new buys.
    filled = native(last, state=S.FILLED, filled_quantity=last.quantity, filled_average_price=D(100), submitted_at=NOW)
    from sentinel.execution import recovery
    recorded = recovery.apply_observation(last, replace(observation, observed_at=late, positions=(), orders=(filled,)))
    with journal.writer_lock(database, recovery_only=True):
        journal.save_command(database, recorded, previous=last.state)
        journal.record_fills(database, [BrokerFill(last.client_key, last.broker_order_id, last.quantity, D(100), late)])
    rows = journal.load_commands(database, live, plan_id=plan.plan_id)
    assert len(rows) == 20 and all(c.state is S.FILLED and c.side is Side.SELL for c in rows)
    broker.submit.assert_not_awaited()
