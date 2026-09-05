"""One assembled production day from Wealth Core state to reconciled fill."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState

from sentinel import binding, schema
from sentinel.binding import AccountBinding
from sentinel.core.decision import DEFENSIVE_SECURITY_ID, build_execution_plan
from sentinel.execution import executor, journal, reconcile
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store
from sentinel.feed.publication import Publication
from tests.sentinel.test_production_state import _advance, _fresh, _published
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


D = Decimal
DECISION_DAY = date(2026, 8, 10)
EXECUTION_DAY = date(2026, 8, 11)
DEPLOYMENT = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
INSTRUMENTS = {
    "1": BrokerInstrument("1", "AAA", "sim-1"),
    DEFENSIVE_SECURITY_ID: BrokerInstrument(
        DEFENSIVE_SECURITY_ID, "BIL", "sim-bil"),
}


def run(coro):
    return asyncio.run(coro)


def _known_book():
    config, state = _fresh()
    portfolio = PortfolioState.from_dict(state.wealth_core)
    portfolio.cash = 99_900
    episode = HoldingEpisode(
        security_id="1", ticker="AAA", issuer_id="P:1", slot_id=0,
        signal_date="2026-01-02", entry_date="2026-01-05",
        entry_raw_open=10.0, entry_split_adjusted_price=10.0,
        initial_shares=10, current_shares=10,
    )
    portfolio.episodes[0] = episode
    portfolio.slots[0].occupied_by = episode.security_id
    state.wealth_core = portfolio.to_dict()
    return config, state


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


def _connection(dsn, *, reset=False):
    conn = feed_store.connect(dsn)
    if reset:
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        feed_store.require_feed_schema(conn)
        binding.bind(
            conn,
            deployment_id=DEPLOYMENT.deployment_id,
            broker=DEPLOYMENT.broker,
            broker_account_id=DEPLOYMENT.broker_account_id,
        )
    return conn


def test_complete_production_day_reconciles_and_restart_is_a_noop(pg):
    config, prior = _known_book()

    # market data -> Wealth Core -> breadth/controller -> durable state envelope
    canonical = _advance(prior, _published(), config)
    assert canonical.last_processed_session == DECISION_DAY.isoformat()
    assert canonical.last_evidence["wealth_core"]["estimated_equity"] == 100_000
    restored = type(canonical).from_dict(canonical.to_dict())
    assert restored.state_hash == canonical.state_hash

    broker = SimulatedBroker(
        account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
        equity=D("100000"), cash=D("100000"),
    )
    observation = run(broker.observe())
    account = run(broker.account_snapshot())
    publication = Publication(
        version=7, previous_version=6, run_id="run-7",
        window_start=DECISION_DAY.isoformat(),
        window_end=DECISION_DAY.isoformat(), evidence={})

    # immutable production state -> exact next-open plan
    decision = build_execution_plan(
        state=restored,
        binding=AccountBinding("nas-1", "sim", "SIM-ACCOUNT", 1),
        publication=publication,
        account_snapshot=account,
        observation=observation,
        marks={"1": "10", DEFENSIVE_SECURITY_ID: "100"},
        tickers={"1": "AAA", DEFENSIVE_SECURITY_ID: "BIL"},
        decision_session=DECISION_DAY,
        effective_session=EXECUTION_DAY,
    )
    assert decision.plan.target_basket == {
        "1": D("10"), DEFENSIVE_SECURITY_ID: D("0")}

    conn = _connection(pg.sync_dsn, reset=True)
    try:
        executor.adopt_plan(conn, decision.plan)
        result = run(executor.execute_session(
            broker=broker,
            conn=conn,
            deployment=DEPLOYMENT,
            plan=decision.plan,
            instruments=INSTRUMENTS,
            today=EXECUTION_DAY,
        ))
        assert len(result.submitted) == 1
        command = result.submitted[0]
        assert command.quantity == D("10")
        broker.fill(command.client_key)

        reconciled = run(reconcile.reconcile(
            broker=broker, conn=conn, binding=None, deployment=DEPLOYMENT))
        final = journal.load_commands(conn, DEPLOYMENT)[0]
        assert final.state is CommandState.FILLED
        assert reconciled.observed == {"1": D("10")}
    finally:
        conn.close()

    # persisted journal -> fresh process connection -> no duplicate economics
    restarted = _connection(pg.sync_dsn)
    try:
        before = len([call for call in broker.calls if call.startswith("submit:")])
        repeated = run(executor.execute_session(
            broker=broker,
            conn=restarted,
            deployment=DEPLOYMENT,
            plan=decision.plan,
            instruments=INSTRUMENTS,
            today=EXECUTION_DAY,
        ))
        after = len([call for call in broker.calls if call.startswith("submit:")])
        assert repeated.submitted == ()
        assert after == before == 1
        assert journal.load_commands(restarted, DEPLOYMENT)[0].state \
            is CommandState.FILLED
    finally:
        restarted.close()

