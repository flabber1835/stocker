"""Trial close cash needs a complete account fill interval, not a plan JOIN."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import trial, trial_fills
from sentinel.execution import broker_cash, journal
from sentinel.execution.contract import (
    BrokerAccountFill,
    BrokerAccountIdentity,
    BrokerFillIntervalEvidence,
    Completeness,
)
from sentinel.execution.identity import DeploymentIdentity


SESSION = date(2026, 8, 20)
DECISION = date(2026, 8, 19)
BASELINE_AT = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)
ACCOUNT_AT = CLOSE + timedelta(minutes=2)
PROCESSED = CLOSE + timedelta(minutes=3)
DEPLOYMENT = DeploymentIdentity(
    deployment_id="trial-appliance", broker="alpaca",
    broker_account_id="PA-1", takeover_epoch=2)
PLAN = SimpleNamespace(
    plan_id="plan-fill-proof", broker="alpaca", broker_account_id="PA-1",
    decision_session=DECISION, account_cash=Decimal("100"))
BASELINE = broker_cash.PlanCashBaseline(
    plan_id=PLAN.plan_id, broker="alpaca", account_id="PA-1",
    decision_session=DECISION, processed_through=BASELINE_AT,
    balance_total=Decimal("0"), last_activity_id="cash-before-plan",
    activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
COMMANDS = [{
    "client_key": "sentinel-key-1", "broker_order_id": "order-1",
    "side": "BUY", "filled_quantity": "2",
}]
ACTIVITY = {
    "balance_total": "0",
    "last_activity_id": "cash-before-plan",
    "activity_identity_scheme": broker_cash.ACTIVITY_IDENTITY_SCHEME,
}


class FillConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        self.statements.append((" ".join(str(statement).split()), params))

    def fetchall(self):
        return self.rows


def _fill(*, activity_id="fill-native-1", broker_order_id="order-1",
          client_key="sentinel-key-1", filled_at=CLOSE - timedelta(hours=1),
          quantity="2", price="10"):
    return BrokerAccountFill(
        activity_id=activity_id, broker_order_id=broker_order_id,
        client_key=client_key, quantity=Decimal(quantity),
        price=Decimal(price), filled_at=filled_at)


def _evidence(fill_rows=(), *, interval_start=BASELINE_AT):
    interval = BrokerFillIntervalEvidence(
        identity=BrokerAccountIdentity("alpaca", "PA-1"),
        requested_session=SESSION, interval_start=interval_start,
        processed_through=PROCESSED, fills=tuple(fill_rows),
        completeness=Completeness.COMPLETE,
        source="accepted_account_fill_ledger",
        semantics=trial_fills.FILL_INTERVAL_SEMANTICS,
        request_started_at=PROCESSED + timedelta(seconds=1),
        request_completed_at=PROCESSED + timedelta(seconds=2),
        query=(("after", interval_start.isoformat()),
               ("through", PROCESSED.isoformat())), raw={"complete": True})
    return trial_fills.build_fill_interval_evidence(
        deployment=DEPLOYMENT, plan_id=PLAN.plan_id, interval=interval)


@pytest.fixture(autouse=True)
def baseline(monkeypatch):
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: BASELINE)
    monkeypatch.setattr(
        broker_cash.PlanCashBaseline,
        "close_cash_finality_authoritative", property(lambda _self: True))
    monkeypatch.setattr(trial_fills, "_official_close", lambda _session: CLOSE)


def _reconstruct(conn, evidence, *, commands=COMMANDS):
    return trial._reconstruct_close_cash(  # noqa: SLF001
        conn, plan=PLAN, commands=list(commands), activity=ACTIVITY,
        close_at=CLOSE, fill_interval_evidence=evidence,
        required_fill_through=ACCOUNT_AT)


def test_complete_account_interval_drives_cash_and_sql_is_account_wide():
    fill = _fill()
    conn = FillConnection(rows=[(
        fill.broker_order_id, journal.fill_fingerprint(fill), fill.client_key,
        fill.quantity, fill.price, fill.filled_at)])

    cash, rows = _reconstruct(conn, _evidence((fill,)))

    assert cash == Decimal("80")
    assert rows[0]["fill_key"] == "fill-native-1"
    statement, params = conn.statements[-1]
    assert "FROM sentinel_fills WHERE" in statement
    assert "JOIN sentinel_commands" not in statement
    assert "filled_at IS NULL OR filled_at >= %s" in statement
    assert params == (BASELINE_AT,)


def test_durable_fill_must_match_native_activity_identity_not_only_economics():
    authoritative = _fill(activity_id="native-authority")
    aliased = _fill(activity_id="different-native-id")
    conn = FillConnection(rows=[(
        authoritative.broker_order_id, journal.fill_fingerprint(aliased),
        authoritative.client_key, authoritative.quantity,
        authoritative.price, authoritative.filled_at)])

    with pytest.raises(
            trial._CloseBookIntervalUnproven,  # noqa: SLF001
            match="absent or economically different"):
        _reconstruct(conn, _evidence((authoritative,)))


@pytest.mark.parametrize(
    ("fill", "message"),
    [
        (_fill(client_key=None), "foreign, or off-plan"),
        (_fill(client_key="another-plan-key"), "foreign, or off-plan"),
        (_fill(broker_order_id="wrong-order"), "broker order identity"),
        (_fill(filled_at=CLOSE + timedelta(seconds=1)), "outside the plan-to-close"),
    ],
)
def test_foreign_off_plan_wrong_order_and_post_close_authoritative_fills_block(
        fill, message):
    with pytest.raises(trial._CloseBookIntervalUnproven, match=message):  # noqa: SLF001
        _reconstruct(FillConnection(), _evidence((fill,)))


def test_missing_or_wrong_lower_boundary_and_omitted_command_fill_block():
    with pytest.raises(
            trial._CloseBookIntervalUnproven, match="no complete account-wide"):  # noqa: SLF001
        _reconstruct(FillConnection(), None)

    wrong_start = BASELINE_AT + timedelta(seconds=1)
    with pytest.raises(
            trial._CloseBookIntervalUnproven,  # noqa: SLF001
            match="immutable plan cash baseline"):
        _reconstruct(FillConnection(), _evidence((), interval_start=wrong_start))

    with pytest.raises(
            trial._CloseBookIntervalUnproven,  # noqa: SLF001
            match="do not prove its filled quantity"):
        _reconstruct(FillConnection(), _evidence(()))


@pytest.mark.parametrize("durable", [
    ("wrong-order", "legacy-key", "sentinel-key-1", Decimal("2"),
     Decimal("10"), CLOSE - timedelta(hours=1)),
    ("order-1", "legacy-key", "other-plan-key", Decimal("2"),
     Decimal("10"), CLOSE - timedelta(hours=1)),
    ("order-1", "legacy-key", "sentinel-key-1", Decimal("2"),
     Decimal("10"), CLOSE + timedelta(seconds=1)),
    ("order-1", "legacy-key", "sentinel-key-1", Decimal("2"),
     Decimal("10"), None),
    ("order-1", "legacy-key", "sentinel-key-1", Decimal("3"),
     Decimal("10"), CLOSE - timedelta(hours=1)),
])
def test_stale_mislinked_foreign_post_close_or_different_durable_rows_block(
        durable):
    with pytest.raises(trial._CloseBookIntervalUnproven):  # noqa: SLF001
        _reconstruct(FillConnection((durable,)), _evidence((_fill(),)))
