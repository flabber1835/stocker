"""The single-sale exact-key read wakes settlement; it never proves spending authority."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution import executor as E
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerExactOrderLookup, BrokerInstrument,
    BrokerObservation, BrokerOrder, Completeness, Side,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState as CS, RuntimeState


DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
ACCOUNT = BrokerAccountIdentity("sim", "SIM-ACCOUNT")
INSTRUMENT = BrokerInstrument(security_id="SEC-AAA", symbol="AAA")
NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
QTY = Decimal("22")


def command(state: CS = CS.ACKNOWLEDGED) -> Command:
    return Command(
        identity=CommandIdentity(DEPLOY, "plan-1", INSTRUMENT.security_id),
        instrument=INSTRUMENT, side=Side.SELL, quantity=QTY, state=state,
        broker_order_id="order-1",
        filled_quantity=QTY if state is CS.FILLED else Decimal(0),
        filled_average_price=Decimal("100") if state is CS.FILLED else None)


def order(state: CS = CS.ACKNOWLEDGED, **changes) -> BrokerOrder:
    return replace(BrokerOrder(
        broker_order_id="order-1", client_key=command().client_key,
        instrument=INSTRUMENT, side=Side.SELL, quantity=QTY, state=state,
        filled_quantity=QTY if state is CS.FILLED else Decimal(0),
        filled_average_price=Decimal("100") if state is CS.FILLED else None),
        **changes)


def lookup(found: BrokerOrder | None, *, account: BrokerAccountIdentity = ACCOUNT
           ) -> BrokerExactOrderLookup:
    return BrokerExactOrderLookup(
        client_key=command().client_key, request_started_at=NOW,
        request_completed_at=NOW, identity_before=account,
        identity_after=account, order=found)


def result(found: BrokerOrder, *,
           completeness: Completeness = Completeness.COMPLETE,
           foreign: bool = False) -> ReconciliationResult:
    return ReconciliationResult(
        runtime_state=RuntimeState.RUNNING,
        observation=BrokerObservation(
            observed_at=NOW, orders=(found,), completeness=completeness,
            account_identity=ACCOUNT),
        foreign_orders=(found,) if foreign else ())


def settlement(monkeypatch, *, after_hint: ReconciliationResult,
               final_command: Command, lookups: list[BrokerExactOrderLookup],
               first_command: Command | None = None, cycles: int = 6,
               window=lambda: True):
    reads = []
    first_command = first_command or command()

    async def reconcile(**_kwargs):
        reads.append(True)
        return result(order()) if len(reads) == 1 else after_hint

    class Broker:
        def __init__(self):
            self.lookup_count = 0

        async def find_by_client_key(self, key):
            assert key == first_command.client_key
            index = self.lookup_count
            self.lookup_count += 1
            return lookups[min(index, len(lookups) - 1)]

    broker = Broker()
    monkeypatch.setattr(E.R, "reconcile", reconcile)
    monkeypatch.setattr(
        E.journal, "load_commands",
        lambda *_args, **_kwargs: (first_command if len(reads) == 1
                                   else final_command,))
    monkeypatch.setattr(E, "SINGLE_SALE_HINT_INTERVAL_SECONDS", 0)
    settled, latest, reason = asyncio.run(E._settle_reductions(
        broker=broker, conn=object(), deployment=DEPLOY, plan_id="plan-1",
        client_keys=(first_command.client_key,), cycles=cycles, actions=None,
        informational_current_book=True, single_sale_hint_wait_seconds=1,
        buy_window_open=window))
    return settled, latest, reason, len(reads), broker.lookup_count


def test_fill_after_six_old_checks_gets_fresh_complete_reconciliation(monkeypatch):
    # The old six-read loop deferred this buy and then reran the full gateway.
    late = [lookup(order()) for _ in range(6)] + [lookup(order(CS.FILLED))]
    settled, latest, _, reads, hints = settlement(
        monkeypatch, after_hint=result(order(CS.FILLED)),
        final_command=command(CS.FILLED), lookups=late)
    assert settled
    assert latest.observation.by_client_key(command().client_key).state is CS.FILLED
    assert reads == 2
    assert hints == 7


@pytest.mark.parametrize("final_result,final_command", [
    (result(order()), command()),
    (result(order(CS.FILLED), completeness=Completeness.PARTIAL),
     command(CS.FILLED)),
    (result(order(CS.FILLED), foreign=True), command(CS.FILLED)),
])
def test_positive_hint_never_substitutes_for_clean_durable_full_fill(
        monkeypatch, final_result, final_command):
    settled, _, _, reads, hints = settlement(
        monkeypatch, after_hint=final_result, final_command=final_command,
        lookups=[lookup(order(CS.FILLED))])
    assert not settled
    assert reads == 2
    assert hints == 1


@pytest.mark.parametrize("hint", [
    lookup(None),
    lookup(order(CS.PARTIALLY_FILLED, filled_quantity=Decimal("10"),
                 filled_average_price=Decimal("100"))),
    lookup(order(CS.REJECTED)),
    lookup(order(CS.FILLED, broker_order_id="other-order")),
    lookup(order(CS.FILLED), account=BrokerAccountIdentity("sim", "OTHER")),
])
def test_absent_partial_rejected_or_mismatched_hint_cannot_settle(monkeypatch, hint):
    window_calls = 0

    def brief_window():
        nonlocal window_calls
        window_calls += 1
        return window_calls <= 4

    settled, _, _, reads, _ = settlement(
        monkeypatch, after_hint=result(order(CS.FILLED)),
        final_command=command(CS.FILLED), lookups=[hint],
        window=brief_window)
    assert not settled
    assert reads == 1


@pytest.mark.parametrize("open_window", [True, False])
def test_unknown_command_retains_conservative_reconciliation(
        monkeypatch, open_window):
    settled, _, _, reads, hints = settlement(
        monkeypatch, after_hint=result(order()),
        final_command=command(), lookups=[lookup(order(CS.FILLED))],
        first_command=command(CS.UNKNOWN), cycles=6,
        window=lambda: open_window)
    assert not settled
    assert reads == 6
    assert hints == 0


def test_cutoff_during_exact_lookup_prevents_final_reconciliation(monkeypatch):
    window_calls = 0

    def expires_during_lookup():
        nonlocal window_calls
        window_calls += 1
        return window_calls <= 2

    settled, _, reason, reads, hints = settlement(
        monkeypatch, after_hint=result(order(CS.FILLED)),
        final_command=command(CS.FILLED),
        lookups=[lookup(order(CS.FILLED))], window=expires_during_lookup)
    assert not settled
    assert "window expired" in reason
    assert reads == 1
    assert hints == 1


def test_cutoff_after_initial_read_skips_redundant_settlement_reads(monkeypatch):
    settled, _, reason, reads, hints = settlement(
        monkeypatch, after_hint=result(order(CS.FILLED)),
        final_command=command(CS.FILLED),
        lookups=[lookup(order(CS.FILLED))], window=lambda: False)
    assert not settled
    assert "window expired" in reason
    assert reads == 1
    assert hints == 0


def test_stalled_guarded_lookup_cannot_extend_the_wait_deadline():
    class StalledBroker:
        async def find_by_client_key(self, _key):
            await asyncio.Event().wait()

    signaled, reason = asyncio.run(E._wait_for_single_sale_fill_hint(
        broker=StalledBroker(), command=command(), deployment=DEPLOY,
        seconds=0.01, buy_window_open=lambda: True))
    assert not signaled
    assert "deadline" in reason


@pytest.mark.parametrize("open_window", [True, False])
def test_multiple_required_sales_keep_the_original_reconciliation_cycles(
        monkeypatch, open_window):
    second_instrument = BrokerInstrument(security_id="SEC-BBB", symbol="BBB")
    second_command = replace(
        command(), identity=CommandIdentity(DEPLOY, "plan-1", "SEC-BBB"),
        instrument=second_instrument, broker_order_id="order-2")
    second_order = replace(
        order(), broker_order_id="order-2",
        client_key=second_command.client_key, instrument=second_instrument)
    reads = []
    hints = []

    async def reconcile(**_kwargs):
        reads.append(True)
        return ReconciliationResult(
            runtime_state=RuntimeState.RUNNING,
            observation=BrokerObservation(
                observed_at=NOW, orders=(order(), second_order),
                account_identity=ACCOUNT))

    class Broker:
        async def find_by_client_key(self, _key):
            hints.append(True)
            return lookup(order(CS.FILLED))

    monkeypatch.setattr(E.R, "reconcile", reconcile)
    monkeypatch.setattr(
        E.journal, "load_commands",
        lambda *_args, **_kwargs: (command(), second_command))
    settled, _, _ = asyncio.run(E._settle_reductions(
        broker=Broker(), conn=object(), deployment=DEPLOY, plan_id="plan-1",
        client_keys=(command().client_key, second_command.client_key),
        cycles=3, actions=None, informational_current_book=True,
        single_sale_hint_wait_seconds=1,
        buy_window_open=lambda: open_window))
    assert not settled
    assert len(reads) == 3
    assert hints == []


@pytest.mark.parametrize("broker,fractional,current_book,has_window,expected", [
    ("alpaca", True, True, True, 75),
    ("alpaca-live", True, True, True, 0),
    ("alpaca-live", False, False, True, 75),
    ("alpaca-live", False, False, False, 0),
    ("alpaca", False, True, True, 0),
    ("alpaca", True, False, True, 0),
    ("alpaca", True, True, False, 0),
])
def test_wait_budget_is_selected_only_for_configured_opening_policies(
        broker, fractional, current_book, has_window, expected):
    deployment = DeploymentIdentity("nas-1", broker, "ACCOUNT", 1)
    assert E._single_sale_hint_budget(
        deployment=deployment, fractional=fractional,
        informational_current_book=current_book,
        market_buy_window_open=(lambda: True) if has_window else None,
    ) == expected
