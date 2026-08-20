"""Focused adversarial regressions for the Alpaca boundary hardening."""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.support.postgres import _EphemeralPostgres, drop_public_tables

from sentinel import binding as B, schema
from sentinel.automation import store as automation_store
from sentinel.execution import journal
from sentinel.execution import alpaca_remediation_compat as compat
from sentinel.execution.alpaca import (
    AccountBoundObservation,
    ActivityCorrectionRequiresRecovery,
    AlpacaExecutionBroker,
    MalformedBrokerPayload,
    NativeBrokerFill,
    restore_increase_fence_reason,
)
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerInstrument, BrokerOrder, Completeness, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S
from sentinel.feed import store as feed_store

UTC = timezone.utc
PAPER = "https://paper-api.alpaca.markets"
ACCOUNT_UUID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_NUMBER = "PA-ALPACA-1"
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAPL", symbol="AAPL", broker_id="asset-aapl")
DEPLOYMENT = DeploymentIdentity(
    "nas-1", "alpaca", ACCOUNT_NUMBER, 1)


def run(coro):
    return asyncio.run(coro)


class Response:
    def __init__(self, payload=None, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            exc = RuntimeError(f"HTTP {self.status_code}")
            exc.response = self
            raise exc


class Httpx:
    def __init__(self, *, post=None, routes=None):
        self.post_result = post
        self.routes = routes or {}
        self.calls = []
        outer = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, url, headers=None, json=None):
                outer.calls.append(("POST", url, dict(json or {})))
                return outer.post_result

            async def get(self, url, headers=None, params=None):
                path = "/v2" + url.split("/v2", 1)[1]
                params = dict(params or {})
                outer.calls.append(("GET", path, params))
                value = outer.routes.get(path)
                if callable(value):
                    value = value(params)
                if isinstance(value, Response):
                    return value
                return Response(value if value is not None else [])

        self.AsyncClient = Client


def account_payload():
    return {"id": ACCOUNT_UUID, "account_number": ACCOUNT_NUMBER}


def adapter(*, post=None, routes=None):
    routes = dict(routes or {})
    routes.setdefault("/v2/account", account_payload())
    http = Httpx(post=post, routes=routes)
    broker = AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
        http_provider=lambda: http)
    return broker, http


def full_order(**changes):
    payload = {
        "id": "order-1",
        "client_order_id": "key-1",
        "symbol": "AAPL",
        "asset_id": "asset-aapl",
        "side": "buy",
        "status": "new",
        "qty": "2",
        "filled_qty": "0",
        "filled_avg_price": None,
        "submitted_at": "2026-08-19T17:00:00Z",
        "type": "market",
        "time_in_force": "day",
        # Alpaca documents both empty string and "simple" as simple orders.
        "order_class": "",
        "extended_hours": False,
    }
    payload.update(changes)
    return payload


def sse(*events):
    return "".join(
        "data: " + json.dumps(event, sort_keys=True) + "\n\n"
        for event in events)


def activity_event(**changes):
    event = {
        "account_id": ACCOUNT_UUID,
        "at": "2026-08-19T17:00:00Z",
        "event_id": "01J5R000000000000000000001",
        "activity_type": "CSD",
        "activity_subtype": None,
        "ref_id": "22222222-2222-2222-2222-222222222222",
        "status": "executed",
        "executed_at": "2026-08-19T17:00:00Z",
        "settle_date": "2026-08-19",
        "qty": None,
        "price": None,
        "net_amount": "25.00",
        "currency": "USD",
        "previous_id": None,
        "details": {},
    }
    event.update(changes)
    return event


def test_runtime_exports_final_hardened_adapter():
    assert AlpacaExecutionBroker.__name__ == "FinancialGradeAlpacaExecutionBroker"
    assert AlpacaExecutionBroker.capabilities.complete_order_pagination is False
    assert AlpacaExecutionBroker.capabilities.recent_fill_history is False
    assert AlpacaExecutionBroker.financial_activity_sse is True


def test_empty_order_class_is_accepted_and_post_targets_asset_id():
    broker, http = adapter(post=Response(full_order(), 200))
    outcome = run(broker.submit(
        client_key="key-1", instrument=INSTRUMENT,
        side=Side.BUY, quantity=Decimal(2)))
    assert outcome.state is S.ACKNOWLEDGED
    assert outcome.broker_order_id == "order-1"
    post = [call for call in http.calls if call[0] == "POST"]
    assert len(post) == 1
    assert post[0][2]["symbol"] == "asset-aapl"
    assert post[0][2]["symbol"] != "AAPL"


def test_ticker_only_submit_is_refused_before_transport():
    broker, http = adapter(post=Response(full_order(), 200))
    ticker_only = BrokerInstrument(security_id="SEC-AAPL", symbol="AAPL")
    with pytest.raises(Exception, match="durable broker asset_id"):
        run(broker.submit(
            client_key="key-1", instrument=ticker_only,
            side=Side.BUY, quantity=Decimal(2)))
    assert not [call for call in http.calls if call[0] == "POST"]


def test_activity_sse_unknown_nonzero_cash_type_fails_closed():
    event = activity_event(activity_type="FUTURE_CASH_TYPE")
    broker, http = adapter(routes={
        "/v2beta1/events/activities": Response(text=sse(event)),
    })
    with pytest.raises(MalformedBrokerPayload, match="unrecognized Activity SSE cash"):
        run(broker.account_cash_activities(
            after=datetime(2026, 8, 19, 16, tzinfo=UTC),
            through=datetime(2026, 8, 19, 18, tzinfo=UTC)))
    sse_calls = [call for call in http.calls
                 if call[1] == "/v2beta1/events/activities"]
    assert len(sse_calls) == 1
    assert set(sse_calls[0][2]) == {"since", "until"}


def test_activity_sse_correction_never_becomes_an_extra_positive_cash_row():
    corrected = activity_event(
        activity_type="TRD",
        previous_id="33333333-3333-3333-3333-333333333333",
        details={"execution_type": "trade_correct", "order_id": "order-1"})
    broker, _ = adapter(routes={
        "/v2beta1/events/activities": Response(text=sse(corrected)),
    })
    with pytest.raises(ActivityCorrectionRequiresRecovery, match="correction/bust"):
        run(broker.account_cash_activities(
            after=datetime(2026, 8, 19, 16, tzinfo=UTC),
            through=datetime(2026, 8, 19, 18, tzinfo=UTC)))


def test_activity_sse_loss_comment_is_not_complete_history():
    broker, _ = adapter(routes={
        "/v2beta1/events/activities": Response(
            text=": you are reading too slowly, dropped 12 messages\n"),
    })
    with pytest.raises(MalformedBrokerPayload, match="message loss"):
        run(broker.account_cash_activities(
            after=datetime(2026, 8, 19, 16, tzinfo=UTC),
            through=datetime(2026, 8, 19, 18, tzinfo=UTC)))


def test_native_fill_activity_ids_preserve_economic_multiplicity():
    common = dict(
        client_key=None,
        broker_order_id="order-1",
        quantity=Decimal(1),
        price=Decimal("100"),
        filled_at=datetime(2026, 8, 19, 17, tzinfo=UTC),
    )
    first = NativeBrokerFill(activity_id="fill-a", **common)
    second = NativeBrokerFill(activity_id="fill-b", **common)
    assert journal.fill_fingerprint(first) != journal.fill_fingerprint(second)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = feed_store.connect(pg.sync_dsn)
    drop_public_tables(c)
    schema.ensure_schema(c)
    feed_store.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="alpaca",
           broker_account_id=ACCOUNT_NUMBER)
    yield c
    c.close()


def command(*, broker_id="asset-aapl"):
    instrument = BrokerInstrument(
        security_id="SEC-AAPL", symbol="AAPL", broker_id=broker_id)
    return Command(
        identity=CommandIdentity(
            deployment=DEPLOYMENT, plan_id="plan-1",
            security_id=instrument.security_id),
        instrument=instrument,
        side=Side.BUY,
        quantity=Decimal(2),
        state=S.PLANNED,
    )


def test_broker_asset_id_is_immutable_under_one_client_key(conn):
    original = command()
    journal.save_command(conn, original)
    changed = replace(
        original,
        instrument=BrokerInstrument(
            security_id="SEC-AAPL", symbol="AAPL", broker_id="asset-relisted"))
    with pytest.raises(journal.CommandEconomicsChanged,
                       match="broker_instrument_id"):
        journal.save_command(conn, changed, previous=S.PLANNED)


def test_account_and_asset_provenance_is_retained_with_observation(conn):
    when = datetime.now(UTC)
    observation = AccountBoundObservation(
        observed_at=when,
        terminal_recovery_through=when,
        completeness=Completeness.COMPLETE,
        account_identity=BrokerAccountIdentity(
            broker="alpaca", account_id=ACCOUNT_NUMBER,
            raw=account_payload()),
        orders=(BrokerOrder(
            broker_order_id="order-1", client_key=None,
            instrument=INSTRUMENT, side=Side.BUY, state=S.ACKNOWLEDGED,
            quantity=Decimal(2)),),
    )
    seq = journal.record_observation(conn, observation, "RECONCILING")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (f"broker-observation:v2:{seq}",),
        )
        state = cur.fetchone()[0]
    if not isinstance(state, dict):
        state = json.loads(str(state))
    assert state["broker"] == "alpaca"
    assert state["account_id"] == ACCOUNT_NUMBER
    assert state["orders"][0]["broker_id"] == "asset-aapl"


def _strict_context():
    class Strict:
        def __enter__(self):
            self.token = compat._RECONCILING.set(True)
            return self

        def __exit__(self, *_args):
            compat._RECONCILING.reset(self.token)
    return Strict()


def test_naked_complete_observation_cannot_authenticate_corrupt_watermark(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT established_at FROM sentinel_account_binding WHERE id=1")
        established = cur.fetchone()[0]
    claimed = established + timedelta(hours=2)
    # Deliberately use the base observation type: this simulates legacy evidence
    # with no account/asset provenance and no completed-reconciliation witness.
    from sentinel.execution.contract import BrokerObservation
    journal.record_observation(conn, BrokerObservation(
        observed_at=claimed,
        terminal_recovery_through=claimed,
        completeness=Completeness.COMPLETE), "RECONCILING")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_terminal_recovery_watermark"
            " (id,broker,broker_account_id,processed_through)"
            " VALUES (1,'alpaca',%s,%s)",
            (ACCOUNT_NUMBER, claimed),
        )
    conn.commit()

    with _strict_context():
        assert journal.terminal_recovery_checkpoint(conn) == established


def test_watermark_cannot_advance_before_recovered_order_is_durable(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT established_at FROM sentinel_account_binding WHERE id=1")
        established = cur.fetchone()[0]
    through = established + timedelta(hours=1)
    unknown_key = "sntl-0123456789abcdef0123"
    observation = AccountBoundObservation(
        observed_at=through,
        terminal_recovery_through=through,
        completeness=Completeness.COMPLETE,
        account_identity=BrokerAccountIdentity(
            broker="alpaca", account_id=ACCOUNT_NUMBER,
            raw=account_payload()),
        orders=(BrokerOrder(
            broker_order_id="unknown-after-backup",
            client_key=unknown_key,
            instrument=INSTRUMENT,
            side=Side.BUY,
            state=S.CANCELLED,
            quantity=Decimal(2),
            submitted_at=through - timedelta(minutes=1)),),
    )
    journal.record_observation(conn, observation, "RECONCILING")

    with _strict_context(), pytest.raises(
            RuntimeError, match="not yet durably reconciled"):
        journal.advance_terminal_recovery_watermark(conn, through)


def test_physical_db_incarnation_change_requires_takeover_before_rerisk(conn):
    # First read establishes the current physical-DB anchor.
    assert restore_increase_fence_reason(
        conn, DEPLOYMENT, date.today()) == ""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name='broker-recovery-db-incarnation:v1'")
        state = cur.fetchone()[0]
    if not isinstance(state, dict):
        state = json.loads(str(state))
    # Simulate a restored/promoted PostgreSQL timeline while the durable takeover
    # epoch is still the pre-restore one.
    state["timeline_id"] = int(state["timeline_id"]) + 1
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_processed_sessions SET state=%s::jsonb"
            " WHERE cursor_name='broker-recovery-db-incarnation:v1'",
            (json.dumps(state),),
        )
    conn.commit()

    reason = restore_increase_fence_reason(conn, DEPLOYMENT, date.today())
    assert "adopt-restored-account" in reason


def test_kill_transition_waits_for_the_execution_writer_lock(conn, pg):
    other = feed_store.connect(pg.sync_dsn)
    entered = threading.Event()
    finished = threading.Event()

    def kill():
        entered.set()
        try:
            automation_store.engage_kill(
                other, actor="test", reason="concurrency falsifier")
        except Exception:
            # A fresh fixture may already have its kill engaged; the property
            # under test is that even that determination cannot occur until the
            # execution critical section releases the shared advisory lock.
            pass
        finally:
            finished.set()

    thread = threading.Thread(target=kill, daemon=True)
    try:
        with journal.writer_lock(conn):
            thread.start()
            assert entered.wait(1)
            assert not finished.wait(0.15)
        assert finished.wait(2)
    finally:
        other.close()
