"""Immutable account-wide fill evidence is complete and account bound."""
from __future__ import annotations

import json
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel import trial_fills
from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution import authority_gate
from sentinel.execution.contract import (
    BrokerAccountFill,
    BrokerAccountIdentity,
    BrokerCapabilities,
    BrokerFillIntervalEvidence,
    Completeness,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.guarded import (
    BrokerOperation,
    ExecutionBrokerGuard,
    GuardedExecutionBroker,
    PaperPreparationGrant,
)


SESSION = date(2026, 8, 20)
CLOSE = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)
INTERVAL_START = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
PROCESSED = CLOSE + timedelta(minutes=5)
STARTED = PROCESSED + timedelta(seconds=1)
COMPLETED = STARTED + timedelta(seconds=1)


class JsonStateConnection:
    def __init__(self):
        self.rows = {}
        self.result = None
        self.commits = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split()).lower()
        if normalized.startswith(
                "select session,state from sentinel_processed_sessions"):
            self.result = self.rows.get(params[0])
            return
        if normalized.startswith("insert into sentinel_processed_sessions"):
            name, raw_session, raw_state = params
            self.rows.setdefault(
                name, (date.fromisoformat(str(raw_session)),
                       json.loads(raw_state)))
            return
        raise AssertionError(f"unexpected fill-evidence SQL: {statement}")

    def fetchone(self):
        return self.result

    def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def exact_close(monkeypatch):
    monkeypatch.setattr(trial_fills, "_official_close", lambda _session: CLOSE)


@pytest.fixture
def deployment():
    return DeploymentIdentity(
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=3)


@pytest.fixture
def account_fill():
    return BrokerAccountFill(
        activity_id="fill-activity-1", broker_order_id="order-1",
        client_key="sentinel-command-1", quantity=Decimal("2"),
        price=Decimal("10.25"),
        filled_at=CLOSE - timedelta(hours=2),
        raw={"id": "fill-activity-1"})


@pytest.fixture
def interval(account_fill):
    return BrokerFillIntervalEvidence(
        identity=BrokerAccountIdentity("alpaca", "PA-1"),
        requested_session=SESSION, interval_start=INTERVAL_START,
        processed_through=PROCESSED, fills=(account_fill,),
        completeness=Completeness.COMPLETE,
        source="accepted_account_fill_ledger",
        semantics=trial_fills.FILL_INTERVAL_SEMANTICS,
        request_started_at=STARTED, request_completed_at=COMPLETED,
        query=(("after", INTERVAL_START.isoformat()),
               ("through", PROCESSED.isoformat())),
        raw={"activities": [{"id": "fill-activity-1"}],
             "complete": True})


def test_capability_is_separate_and_false_for_production_alpaca():
    assert BrokerCapabilities().account_fill_interval_evidence is False
    assert AlpacaExecutionBroker.capabilities.account_fill_interval_evidence \
        is False


def test_guard_refuses_false_capability_before_transport(interval):
    class Adapter:
        capabilities = BrokerCapabilities()

        def __init__(self):
            self.calls = 0

        async def account_fill_interval_evidence(self, **_kwargs):
            self.calls += 1
            return interval

    adapter = Adapter()
    guarded = GuardedExecutionBroker(
        inner=adapter,
        grant=PaperPreparationGrant(
            expected_account="PA-1", decision_session=SESSION),
        guard=ExecutionBrokerGuard(
            before_read=lambda *_: None, after_read=lambda *_: None,
            before_mutation=lambda *_: None))

    assert guarded.supports_account_fill_interval_evidence is False
    with pytest.raises(AttributeError, match="no certified account fill interval"):
        asyncio.run(guarded.account_fill_interval_evidence(
            session=SESSION, interval_start=INTERVAL_START))
    assert adapter.calls == 0


def test_certified_fill_interval_crosses_account_bound_read_guard(interval):
    class Adapter:
        capabilities = BrokerCapabilities(account_fill_interval_evidence=True)

        async def account_fill_interval_evidence(self, **_kwargs):
            return interval

    events = []

    async def before(_grant, operation):
        events.append(("before", operation))

    async def after(_grant, operation, result):
        events.append(("after", operation, result.identity.account_id))

    guarded = GuardedExecutionBroker(
        inner=Adapter(),
        grant=PaperPreparationGrant(
            expected_account="PA-1", decision_session=SESSION),
        guard=ExecutionBrokerGuard(
            before_read=before, after_read=after,
            before_mutation=before))

    result = asyncio.run(guarded.account_fill_interval_evidence(
        session=SESSION, interval_start=INTERVAL_START))

    operation = BrokerOperation.ACCOUNT_FILL_INTERVAL_EVIDENCE
    assert events == [("before", operation), ("after", operation, "PA-1")]
    assert authority_gate._result_account(result) == result.identity  # noqa: SLF001
    assert operation in authority_gate._READ_OPERATIONS  # noqa: SLF001


def test_complete_native_interval_is_recorded_and_bound(
        deployment, interval):
    conn = JsonStateConnection()

    evidence = trial_fills.record_fill_interval_evidence(
        conn, deployment=deployment, plan_id="plan-1", interval=interval)

    cursor = "trial-fill-interval:v1:2026-08-20"
    assert set(conn.rows) == {cursor}
    assert evidence["kind"] == "sentinel-trial-fill-interval/v1"
    assert evidence["plan_id"] == "plan-1"
    assert evidence["deployment"]["broker_account_id"] == "PA-1"
    assert evidence["interval_start"] == INTERVAL_START.isoformat()
    assert evidence["processed_through"] == PROCESSED.isoformat()
    assert evidence["official_xnys_close_at"] == CLOSE.isoformat()
    assert evidence["fills"] == [{
        "activity_id": "fill-activity-1",
        "broker_order_id": "order-1",
        "client_key": "sentinel-command-1",
        "quantity": "2",
        "price": "10.25",
        "filled_at": (CLOSE - timedelta(hours=2)).isoformat(),
    }]
    assert trial_fills.load_fill_interval_evidence(
        conn, session=SESSION, deployment=deployment,
        plan_id="plan-1") == evidence
    assert conn.commits == 1


def test_retry_keeps_first_request_bracket_but_source_change_refuses(
        deployment, interval):
    conn = JsonStateConnection()
    first = trial_fills.record_fill_interval_evidence(
        conn, deployment=deployment, plan_id="plan-1", interval=interval)
    later = replace(
        interval, request_started_at=STARTED + timedelta(minutes=5),
        request_completed_at=COMPLETED + timedelta(minutes=5))

    assert trial_fills.record_fill_interval_evidence(
        conn, deployment=deployment, plan_id="plan-1",
        interval=later) == first

    changed = replace(interval, processed_through=PROCESSED + timedelta(seconds=1),
                      request_started_at=STARTED + timedelta(seconds=1),
                      request_completed_at=COMPLETED + timedelta(seconds=1))
    with pytest.raises(
            trial_fills.TrialFillIntervalHistoricalRevision,
            match="revision refused"):
        trial_fills.record_fill_interval_evidence(
            conn, deployment=deployment, plan_id="plan-1",
            interval=changed)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"completeness": Completeness.TRUNCATED}, "not explicitly COMPLETE"),
        ({"semantics": "RECENT_FILLS_BEST_EFFORT"}, "not certified"),
        ({"processed_through": CLOSE - timedelta(seconds=1),
          "request_started_at": CLOSE + timedelta(seconds=1)},
         "does not reach"),
    ],
)
def test_incomplete_unpinned_or_short_interval_refuses(
        deployment, interval, change, message):
    with pytest.raises(trial_fills.TrialFillIntervalRefused, match=message):
        trial_fills.build_fill_interval_evidence(
            deployment=deployment, plan_id="plan-1",
            interval=replace(interval, **change))


def test_wrong_account_and_duplicate_native_identity_refuse(
        deployment, interval, account_fill):
    wrong = replace(
        interval, identity=BrokerAccountIdentity("alpaca", "PA-OTHER"))
    with pytest.raises(trial_fills.TrialFillIntervalRefused, match="binding"):
        trial_fills.build_fill_interval_evidence(
            deployment=deployment, plan_id="plan-1", interval=wrong)

    with pytest.raises(ValueError, match="repeats a native activity id"):
        replace(interval, fills=(account_fill, account_fill))


def test_load_rejects_hash_plan_and_binding_corruption(deployment, interval):
    conn = JsonStateConnection()
    trial_fills.record_fill_interval_evidence(
        conn, deployment=deployment, plan_id="plan-1", interval=interval)
    cursor = trial_fills.fill_interval_cursor(SESSION)

    conn.rows[cursor][1]["fills"][0]["quantity"] = "999"
    with pytest.raises(trial_fills.TrialFillIntervalRefused, match="hash is corrupt"):
        trial_fills.load_fill_interval_evidence(
            conn, session=SESSION, deployment=deployment, plan_id="plan-1")

    clean = JsonStateConnection()
    trial_fills.record_fill_interval_evidence(
        clean, deployment=deployment, plan_id="plan-1", interval=interval)
    with pytest.raises(trial_fills.TrialFillIntervalRefused, match="another plan"):
        trial_fills.load_fill_interval_evidence(
            clean, session=SESSION, deployment=deployment, plan_id="plan-2")
