"""Bound repeated observation and command reads without changing authority."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution import commands, executor, journal
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerExactOrderEvidence, BrokerInstrument,
    BrokerObservation, BrokerOrder, Completeness, Side,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState, RuntimeState


NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
ACCOUNT = BrokerAccountIdentity("sim", "SIM-ACCOUNT")
DEPLOYMENT = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
INSTRUMENT = BrokerInstrument("SEC-AAA", "AAA")


def order(key="key-1", broker_id="order-1"):
    return BrokerOrder(
        broker_order_id=broker_id, client_key=key, instrument=INSTRUMENT,
        side=Side.BUY, state=CommandState.ACKNOWLEDGED,
        quantity=Decimal("10"), filled_quantity=Decimal("0"))


def exact(key="key-1", found=None):
    return BrokerExactOrderEvidence(
        client_key=key, request_started_at=NOW, request_completed_at=NOW,
        identity_before=ACCOUNT, identity_after=ACCOUNT,
        initial_order_id=None, order=found)


class CountedTuple(tuple):
    def __new__(cls, values):
        instance = super().__new__(cls, values)
        instance.iterations = 0
        return instance

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def test_observation_indexes_scan_each_immutable_tuple_only_once():
    orders = CountedTuple(order(f"key-{i}", f"order-{i}") for i in range(100))
    evidence = CountedTuple(exact(f"key-{i}") for i in range(100))
    observed = BrokerObservation(
        NOW, orders=orders, exact_order_evidence=evidence)
    orders.iterations = evidence.iterations = 0

    for _ in range(10):
        assert observed.by_client_key("key-99") is orders[99]
        assert observed.by_client_key("absent") is None
        assert observed.exact_by_client_key("key-99") is evidence[99]
        assert observed.exact_by_client_key("absent") is None

    assert orders.iterations == evidence.iterations == 1


def test_observation_indexes_preserve_first_unowned_match_and_serialized_fields():
    first, second = order("", "first"), order("", "second")
    observed = BrokerObservation(NOW, orders=(first, second),
                                 exact_order_evidence=(exact(),))
    before = asdict(observed)

    assert observed.by_client_key("") is first
    assert observed.exact_by_client_key("key-1") is not None

    assert asdict(observed) == before
    assert observed == replace(observed)


def test_replaced_observation_rebuilds_indexes_for_new_positive_evidence():
    prior_order = order()
    prior_exact = exact()
    observed = BrokerObservation(NOW, orders=(prior_order,),
                                 exact_order_evidence=(prior_exact,))
    assert observed.by_client_key("key-1") is prior_order
    assert observed.exact_by_client_key("key-1") is prior_exact
    filled = replace(prior_order, state=CommandState.FILLED,
                     filled_quantity=Decimal("10"),
                     filled_average_price=Decimal("100.001"))
    positive = exact(found=filled)

    updated = replace(observed, orders=(filled,),
                      exact_order_evidence=(positive,))

    assert updated.by_client_key("key-1") is filled
    assert updated.exact_by_client_key("key-1") is positive
    assert observed.by_client_key("key-1") is prior_order
    assert observed.exact_by_client_key("key-1") is prior_exact


def test_mutable_evidence_sequences_remain_uncached():
    orders, evidence = [order()], [exact()]
    observed = BrokerObservation(NOW, orders=orders,
                                 exact_order_evidence=evidence)
    assert observed.by_client_key("key-1") is orders[0]
    assert observed.exact_by_client_key("key-1") is evidence[0]
    orders[0], evidence[0] = order("key-2"), exact("key-2")

    assert observed.by_client_key("key-1") is None
    assert observed.by_client_key("key-2") is orders[0]
    assert observed.exact_by_client_key("key-1") is None
    assert observed.exact_by_client_key("key-2") is evidence[0]


@pytest.mark.parametrize("changes, message", [
    ({"orders": (order(), order())}, "repeats broker order id"),
    ({"orders": (order(), order(broker_id="other"))}, "multiple broker ids"),
    ({"exact_order_evidence": (exact(), exact())}, "repeats exact key"),
])
def test_observation_indexes_never_hide_ambiguous_evidence(changes, message):
    with pytest.raises(ValueError, match=message):
        BrokerObservation(NOW, **changes)


def test_revision_read_selects_only_the_plan_and_security(monkeypatch):
    calls = []

    def load(_conn, deployment, **scope):
        assert deployment == DEPLOYMENT
        calls.append(scope)
        return ()

    monkeypatch.setattr(journal, "load_commands", load)
    delta = commands.compute_delta(
        security_id=INSTRUMENT.security_id, desired=Decimal("10"),
        observation=BrokerObservation(NOW))

    built, already_planned = executor._command_for_delta(
        conn=object(), deployment=DEPLOYMENT, plan_id="plan-1", delta=delta,
        instrument=INSTRUMENT)

    assert calls == [{"plan_id": "plan-1", "security_id": "SEC-AAA"}]
    assert built.identity.revision == 0
    assert not already_planned


@pytest.mark.asyncio
async def test_settlement_read_keeps_missing_required_keys_closed(monkeypatch):
    calls = []
    observed = BrokerObservation(NOW, completeness=Completeness.COMPLETE)

    async def reconcile(**_kwargs):
        return ReconciliationResult(
            runtime_state=RuntimeState.RUNNING, observation=observed)

    def load(_conn, deployment, **scope):
        assert deployment == DEPLOYMENT
        calls.append(scope)
        return ()

    monkeypatch.setattr(executor.R, "reconcile", reconcile)
    monkeypatch.setattr(journal, "load_commands", load)

    settled, _, reason = await executor._settle_reductions(
        broker=object(), conn=object(), deployment=DEPLOYMENT, plan_id="plan-1",
        client_keys={"missing-sale"}, cycles=1, actions=None)

    assert calls == [{"client_keys": ["missing-sale"]}]
    assert not settled
    assert "absent from the journal" in reason
