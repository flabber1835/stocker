"""A positive protected receipt reduces only the proved live remainder."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
import textwrap

import pytest

from sentinel.execution import alpaca, recovery
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerExactOrderLookup, BrokerObservation, BrokerOrder,
    CommandOutcome, Completeness, OrderTerms, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_limit_day_transport import (
    INSTRUMENT, LIMIT, ROUTES, broker_for, limited)
from tests.sentinel.test_order_terms_journal import conn, pg


OWNER = DeploymentIdentity("receipt-test", "alpaca", "private-account", 1)


def pending():
    return Command(CommandIdentity(OWNER, "receipt-plan", INSTRUMENT.security_id),
        INSTRUMENT, Side.BUY, D(2), state=S.SEND_PENDING, order_terms=LIMIT)


def positive(command, **changes):
    value = BrokerOrder("native-receipt", command.client_key, command.instrument,
        Side.BUY, S.FILLED, command.quantity, command.quantity, D("101"),
        datetime.now(timezone.utc), order_terms=command.order_terms)
    return replace(value, **changes)


def dispatch(outcome, command=None):
    class Broker:
        async def submit(self, **_kwargs):
            return outcome
    return asyncio.run(recovery.dispatch(Broker(), pending() if command is None else command))


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("status,filled,average", [
    ("new", "0", None), ("partially_filled", "1", "101"), ("filled", "2", "101")])
def test_native_protected_receipt_persists_counters_with_ack_only(route, status, filled, average):
    command = pending()
    broker, http = broker_for(route, payload=limited(client_order_id=command.client_key,
        status=status, filled_qty=filled, filled_avg_price=average))
    restored = asyncio.run(recovery.dispatch(broker, command))
    assert restored.state is S.ACKNOWLEDGED
    assert restored.filled_quantity == D(filled)
    assert restored.filled_average_price == (None if average is None else D(average))
    assert restored.order_terms == LIMIT and restored.broker_order_id == "order-1"
    assert [call[0] for call in http.calls] == ["POST"]


def test_receipt_keyword_preserves_retryable_positional_contract():
    outcome = alpaca.RetryableCommandOutcome(S.UNKNOWN, "native", "throttle", D("0.1"))
    assert outcome.retry_after_seconds == D("0.1") and outcome.receipt is None
    with pytest.raises(TypeError):
        CommandOutcome(S.ACKNOWLEDGED, "native", "human", positive(pending()))
    with pytest.raises(TypeError, match="typed"):
        CommandOutcome(S.ACKNOWLEDGED, receipt={"filled": "2"})


@pytest.mark.parametrize("route", ROUTES)
def test_legacy_market_outcomes_never_forward_fill_receipts(route):
    from tests.sentinel.test_limit_day_transport import full_order
    command = replace(pending(), order_terms=OrderTerms())
    broker, _http = broker_for(route, payload=full_order(client_order_id=command.client_key,
        status="filled", filled_qty="2", filled_avg_price="101"))
    restored = asyncio.run(recovery.dispatch(broker, command))
    assert restored.state is S.ACKNOWLEDGED and restored.filled_quantity == 0
    assert restored.filled_average_price is None


@pytest.mark.parametrize("state", [S.ACKNOWLEDGED, S.UNKNOWN, S.REJECTED])
def test_absent_receipt_keeps_existing_hold_and_outcome(state):
    result = dispatch(CommandOutcome(state, "native"))
    assert result.state is state and result.filled_quantity == 0
    assert result.filled_average_price is None


@pytest.mark.parametrize("damage", ["client_key", "side", "quantity", "security", "symbol", "asset",
    "terms", "unreported_terms", "native_id", "lifecycle", "replacement", "lineage", "above_limit",
    "unknown_outcome", "rejected_outcome"])
def test_contradictory_receipt_is_unknown_with_native_identity_and_full_hold(damage):
    command = pending()
    receipt = positive(command)
    changes = {
        "client_key": {"client_key": "another-key"}, "side": {"side": Side.SELL},
        "quantity": {"quantity": D(3), "filled_quantity": D(3)},
        "security": {"instrument": replace(INSTRUMENT, security_id="another-security")},
        "symbol": {"instrument": replace(INSTRUMENT, symbol="OTHER")},
        "asset": {"instrument": replace(INSTRUMENT, broker_id="another-asset")},
        "terms": {"order_terms": replace(LIMIT, limit_price=D("102.26"))},
        "unreported_terms": {"order_terms": None},
        "lifecycle": {"state": S.CANCELLED}, "replacement": {"external_replacement": True},
        "lineage": {"replaces": "another-order"}, "above_limit": {"filled_average_price": D("102.26")},
    }
    if damage in changes:
        receipt = replace(receipt, **changes[damage])
    state = {"unknown_outcome": S.UNKNOWN, "rejected_outcome": S.REJECTED}.get(damage, S.ACKNOWLEDGED)
    native = "conflicting-native" if damage == "native_id" else receipt.broker_order_id
    result = dispatch(CommandOutcome(state, native, receipt=receipt), command)
    assert result.state is S.UNKNOWN and result.broker_order_id == native
    assert result.filled_quantity == command.filled_quantity == 0
    assert result.filled_average_price is None


@pytest.mark.parametrize("field", ["instrument", "side"])
def test_unusable_nested_receipt_preserves_unknown_native_id_and_full_hold(field):
    command = pending()
    receipt = replace(positive(command), **{field: object()})
    result = dispatch(CommandOutcome(S.ACKNOWLEDGED, receipt.broker_order_id, receipt=receipt), command)
    assert result.state is S.UNKNOWN and result.broker_order_id == receipt.broker_order_id
    assert result.filled_quantity == command.filled_quantity == 0
    assert result.filled_average_price is None


def test_same_key_rate_limit_retry_persists_only_positive_retry_receipt():
    command = pending()
    identity = BrokerAccountIdentity(OWNER.broker, OWNER.broker_account_id)
    now = datetime.now(timezone.utc)
    class Broker:
        def __init__(self):
            self.posts = []
        async def submit(self, **kwargs):
            self.posts.append(kwargs)
            if len(self.posts) == 1:
                return alpaca.RetryableCommandOutcome(S.UNKNOWN, None, "throttle", D(0))
            return CommandOutcome(S.ACKNOWLEDGED, "native-receipt", receipt=positive(command))
        async def find_by_client_key(self, key):
            return BrokerExactOrderLookup(key, now, now, identity, identity, None)
        async def observe(self):
            return BrokerObservation(observed_at=now, started_at=now, orders=(), positions=(),
                completeness=Completeness.COMPLETE, account_identity=identity)
    broker = Broker()
    result = asyncio.run(recovery.dispatch(broker, command))
    assert result.state is S.ACKNOWLEDGED and result.filled_quantity == command.quantity
    assert result.filled_average_price == D(101)
    assert len(broker.posts) == 2
    assert all(row["client_key"] == command.client_key and row["order_terms"] == LIMIT for row in broker.posts)


@pytest.mark.parametrize("filled", ["0", "1", "10"])
def test_positive_receipt_is_durable_before_next_leg_without_invented_fills(conn, filled):
    from sentinel.execution import executor, journal
    from tests.sentinel.test_order_terms_journal import cmd, DEPLOY, LIMIT as STORED_LIMIT
    command = replace(cmd(), order_terms=STORED_LIMIT)
    receipt = BrokerOrder("durable-native", command.client_key, command.instrument,
        command.side, S.FILLED if filled == "10" else S.PARTIALLY_FILLED if filled == "1" else S.ACKNOWLEDGED,
        command.quantity, D(filled), D(100) if D(filled) else None,
        datetime.now(timezone.utc), order_terms=STORED_LIMIT)
    class Broker:
        async def submit(self, **_kwargs):
            return CommandOutcome(S.ACKNOWLEDGED, receipt.broker_order_id, receipt=receipt)
    # This component owns the real session lock; full gateway qualification
    # separately earns the restore-horizon authority before invoking it.
    conn.execute("SELECT pg_advisory_lock(%s)", (journal.WRITER_LOCK_KEY,))
    try:
        result = asyncio.run(executor._persist_and_send(conn, Broker(), command))
    finally:
        conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (journal.WRITER_LOCK_KEY,))
        conn.commit()
    stored, = journal.load_commands(conn, DEPLOY)
    assert stored.state is result.state is S.ACKNOWLEDGED
    assert stored.filled_quantity == D(filled)
    assert stored.filled_average_price == receipt.filled_average_price
    assert stored.broker_order_id == receipt.broker_order_id
    assert conn.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0


def _receipt_lag_case(conn, filled="4"):
    from sentinel.execution import executor, journal, reconcile
    from sentinel.execution.contract import BrokerPosition
    from sentinel.execution.simulator import SimulatedBroker
    from tests.sentinel.test_order_terms_journal import cmd, DEPLOY, LIMIT as STORED_LIMIT
    command = replace(cmd(), order_terms=STORED_LIMIT)
    native = BrokerOrder("lag-native", command.client_key, command.instrument,
        command.side, S.FILLED if filled == "10" else S.PARTIALLY_FILLED,
        command.quantity, D(filled), D(100), datetime.now(timezone.utc), order_terms=STORED_LIMIT)
    broker = SimulatedBroker(account=BrokerAccountIdentity(DEPLOY.broker, DEPLOY.broker_account_id))
    current = {"order": native, "position": D(0)}
    async def submit(**_kwargs):
        return CommandOutcome(S.ACKNOWLEDGED, native.broker_order_id, receipt=native)
    async def snapshot(**_kwargs):
        positions = (() if not current["position"] else
            (BrokerPosition(command.instrument, current["position"]),))
        return BrokerObservation(observed_at=broker.now, started_at=broker.now-timedelta(milliseconds=1),
            orders=(current["order"],), positions=positions, completeness=Completeness.COMPLETE,
            terminal_recovery_through=broker.now, account_identity=broker.account)
    broker.submit = submit
    broker.observe_with_terminal_recovery = snapshot
    conn.execute("SELECT pg_advisory_lock(%s)", (journal.WRITER_LOCK_KEY,))
    try:
        asyncio.run(executor._persist_and_send(conn, broker, command))
    finally:
        conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (journal.WRITER_LOCK_KEY,))
        conn.commit()
    first_seen, = conn.execute("SELECT at FROM sentinel_command_events WHERE client_key=%s"
        " AND from_state='SEND_PENDING' AND to_state='ACKNOWLEDGED'", (command.client_key,)).fetchone()
    broker.now = first_seen + timedelta(seconds=5)
    def recover(reader=conn):
        return asyncio.run(reconcile.reconcile(broker=broker, conn=reader, binding=None, deployment=DEPLOY))
    return command, broker, current, first_seen, recover


@pytest.mark.parametrize("filled", ["4", "10"])
def test_receipt_position_lag_survives_restart_then_converges(conn, filled):
    import psycopg
    command, broker, current, first_seen, recover = _receipt_lag_case(conn, filled)
    first = recover()
    assert first.runtime_state.value == "RECONCILING" and first.foreign_positions == ()
    conn.rollback()
    before = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-position-lag:v2:%'").fetchall()
    assert len(before) == 1 and datetime.fromisoformat(before[0][0]["first_observed_at"]) == first_seen
    broker.now = first_seen + timedelta(seconds=35)
    current["position"] = D(2)
    with psycopg.connect(conn.info.dsn) as restarted:
        repeated = recover(restarted)
        assert repeated.runtime_state.value == "RECONCILING" and repeated.foreign_positions == ()
        assert restarted.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-position-lag:v2:%'").fetchall() == before
    broker.now = first_seen + timedelta(seconds=60)
    current["position"] = D(filled)
    converged = recover()
    assert converged.runtime_state.value == "RUNNING" and converged.clean
    assert conn.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0


def test_receipt_lag_expiry_uses_event_clock_even_on_first_late_recovery(conn):
    command, broker, current, first_seen, recover = _receipt_lag_case(conn)
    broker.now = first_seen + timedelta(seconds=121)
    result = recover()
    assert result.runtime_state.value == "FOREIGN_ACTIVITY"
    assert result.foreign_positions == (command.security_id,)
    state, = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-position-lag:v2:%'").fetchone()
    assert datetime.fromisoformat(state["first_observed_at"]) == first_seen


def test_new_fill_does_not_refresh_the_older_receipt_generation(conn):
    command, broker, current, first_seen, recover = _receipt_lag_case(conn)
    assert recover().runtime_state.value == "RECONCILING"
    broker.now = first_seen + timedelta(seconds=35)
    current["order"] = replace(current["order"], filled_quantity=D(6))
    current["position"] = D(2)
    assert recover().runtime_state.value == "RECONCILING"
    rows = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-position-lag:v2:%'").fetchall()
    assert len(rows) == 2
    assert {row[0]["signed_capacity"] for row in rows} == {"4", "2"}
    broker.now = first_seen + timedelta(seconds=121)
    result = recover()
    assert result.runtime_state.value == "FOREIGN_ACTIVITY" and result.foreign_positions == (command.security_id,)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "quantity", "future", "native_id", "terms"])
def test_receipt_lag_never_invents_capacity_from_bad_history_or_identity(conn, damage):
    command, broker, current, first_seen, recover = _receipt_lag_case(conn)
    clause = " WHERE client_key=%s AND from_state='SEND_PENDING' AND to_state='ACKNOWLEDGED'"
    if damage == "missing":
        conn.execute("DELETE FROM sentinel_command_events" + clause, (command.client_key,))
    elif damage == "duplicate":
        conn.execute("INSERT INTO sentinel_command_events(client_key,from_state,to_state,filled_quantity,detail,at)"
            " SELECT client_key,from_state,to_state,filled_quantity,detail,at FROM sentinel_command_events" + clause,
            (command.client_key,))
    elif damage == "quantity":
        conn.execute("UPDATE sentinel_command_events SET filled_quantity=5" + clause, (command.client_key,))
    elif damage == "future":
        conn.execute("UPDATE sentinel_command_events SET at=%s" + clause,
            (broker.now+timedelta(minutes=1), command.client_key))
    elif damage == "native_id":
        current["order"] = replace(current["order"], broker_order_id="contradictory-native")
    else:
        current["order"] = replace(current["order"], order_terms=OrderTerms())
    conn.commit()
    result = recover()
    assert result.runtime_state.value in {"FOREIGN_ACTIVITY", "RECONCILING"}
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-position-lag:v2:%'").fetchone()[0] == 0


def _broken(function, before, after):
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(before) == 1
    namespace = {}
    exec(compile(source.replace(before, after), "<private-receipt-falsifier>", "exec"),
        function.__globals__, namespace)
    return namespace[function.__name__]


def test_receipt_terms_falsifier_detects_removed_command_match(monkeypatch):
    monkeypatch.setattr(recovery, "_command_from_submit_outcome", _broken(
        recovery._command_from_submit_outcome,
        '_assert_order_matches_command(command, receipt, where="submit receipt")', 'pass'))
    with pytest.raises(AssertionError):
        test_contradictory_receipt_is_unknown_with_native_identity_and_full_hold("terms")


def test_receipt_counter_falsifier_detects_discarded_positive_fill(monkeypatch):
    monkeypatch.setattr(recovery, "_command_from_submit_outcome", _broken(
        recovery._command_from_submit_outcome,
        'changes = {"filled_quantity": receipt.filled_quantity,\n'
        '                       "filled_average_price": receipt.filled_average_price}', 'changes = {}'))
    with pytest.raises(AssertionError):
        test_native_protected_receipt_persists_counters_with_ack_only(ROUTES[0], "filled", "2", "101")


def test_receipt_unknown_falsifier_detects_unearned_counter_release(monkeypatch):
    monkeypatch.setattr(recovery, "_command_from_submit_outcome", _broken(
        recovery._command_from_submit_outcome,
        'or outcome.state is not S.ACKNOWLEDGED', 'or False'))
    with pytest.raises(AssertionError):
        test_contradictory_receipt_is_unknown_with_native_identity_and_full_hold("unknown_outcome")


@pytest.mark.parametrize("field", ["instrument", "side"])
def test_nested_receipt_falsifier_detects_unhandled_post_transport_evidence(monkeypatch, field):
    monkeypatch.setattr(recovery, "_command_from_submit_outcome", _broken(
        recovery._command_from_submit_outcome,
        'except (BrokerAuthorityRefused, ValueError, TypeError, AttributeError):',
        'except (BrokerAuthorityRefused, ValueError, TypeError):'))
    with pytest.raises(AttributeError):
        test_unusable_nested_receipt_preserves_unknown_native_id_and_full_hold(field)


def test_receipt_lag_clock_falsifier_detects_restarted_grace(conn, monkeypatch):
    from sentinel.execution import reconcile
    monkeypatch.setattr(reconcile, "_receipt_fill_episode", _broken(reconcile._receipt_fill_episode,
        '"first_observed_at": first_seen', '"first_observed_at": observed_at'))
    with pytest.raises(AssertionError):
        test_receipt_lag_expiry_uses_event_clock_even_on_first_late_recovery(conn)


def test_receipt_lag_quantity_falsifier_detects_unproved_capacity(conn, monkeypatch):
    from sentinel.execution import reconcile
    monkeypatch.setattr(reconcile, "_receipt_fill_episode", _broken(reconcile._receipt_fill_episode,
        'or filled != command.filled_quantity', 'or False'))
    with pytest.raises(AssertionError):
        test_receipt_lag_never_invents_capacity_from_bad_history_or_identity(conn, "quantity")
