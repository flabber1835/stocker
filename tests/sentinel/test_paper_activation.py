"""Paper activation orchestration, exercised only with PostgreSQL and simulator.

The end-to-end test drives the explicit production migration state machine
through a test-only bridge over the same simulated paper book. No Alpaca
adapter, network request, or real broker account is involved.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import (  # noqa: E402
    _EphemeralPostgres,
    drop_public_tables,
)

from sentinel import authority, binding, handover, paper, schema  # noqa: E402
from sentinel.broker import CloseResult  # noqa: E402
from sentinel.config import DEFAULT_BASE_URL, LiveEndpointRefused  # noqa: E402
from sentinel.controller.frozen_rule import (  # noqa: E402
    ControllerConfig,
    HealthyConfig,
    RampConfig,
)
from sentinel.controller.machine import Controller  # noqa: E402
from sentinel.core import catchup  # noqa: E402
from sentinel.core.decision import (  # noqa: E402
    DEFENSIVE_SECURITY_ID,
    publication_fingerprint,
)
from sentinel.core.loader import CorpusWindow  # noqa: E402
from sentinel.core.production import PublishedSession, SessionState  # noqa: E402
from sentinel.execution import alpaca, journal  # noqa: E402
from sentinel.execution.commands import Command  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    IncompleteObservation,
    BrokerInstrument,
    BrokerObservation,
    BrokerPosition,
    Side,
)
from sentinel.execution.identity import CommandIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import (  # noqa: E402
    FaultKind,
    SimulatedBroker,
)
from sentinel.execution.states import CommandState, RuntimeState  # noqa: E402
from sentinel.feed import publication, store as feed_store  # noqa: E402
from sentinel.ownership import AccountObservation, OpenOrder  # noqa: E402
from stock_strategy_shared.wealth_core.feed import (  # noqa: E402
    SecurityMeta,
    VendorBar,
)
from stock_strategy_shared.wealth_core.state import (  # noqa: E402
    HoldingEpisode,
    PortfolioState,
)

D = Decimal
DECISION = dt.date(2026, 8, 11)
EFFECTIVE = dt.date(2026, 8, 12)
PRIOR = dt.date(2026, 8, 7)
HALF_DAY_DECISION = dt.date(2024, 11, 27)
HALF_DAY_EFFECTIVE = dt.date(2024, 11, 29)
ACCOUNT = "SIM-PAPER"
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA")
IDENTITY = {
    "strategy": "paper-activation-test",
    "controller_rule_sha256": "controller-test-sha",
    "wealth_core_source_sha256": "wealth-core-test-sha",
}
CONFIG = ControllerConfig(
    ordinary_stress_drawdown=-0.10,
    ordinary_target_core=0.55,
    severe_target_core=0.0,
    slow_entry={}, slow_recovery={}, fast_entry={}, fast_recovery={},
    ramp=RampConfig(
        gate_horizon_sessions=5, fragile_if_delta_r40_5_lte=0.0,
        steps=(0.55, 0.65, 1.0), confirmation_sessions=(10, 10),
        not_fragile_target=1.0, renewed_severe_target=0.0),
    healthy=HealthyConfig(
        shadow_r20_strictly_greater_than=0.0,
        max_damaged_breadth=0.5, min_green_breadth=0.5),
    strategy_id=IDENTITY["strategy"],
    digest=IDENTITY["controller_rule_sha256"],
)


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
    connection = feed_store.connect(pg.sync_dsn)
    drop_public_tables(connection)
    feed_store.ensure_schema(connection)
    schema.ensure_schema(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def simulator_is_certified(monkeypatch):
    """Certification is covered elsewhere; these tests exercise orchestration."""
    monkeypatch.setattr(paper, "require_certified", lambda _adapter: None)
    monkeypatch.setattr(paper, "load_controller", lambda: CONFIG)
    monkeypatch.setattr(
        paper, "runtime_strategy_identity", lambda _config: dict(IDENTITY))
    monkeypatch.setattr(
        paper, "require_current_authority",
        lambda *_args, **_kwargs: SimpleNamespace(
            certificate_sha256="test-system-certificate"))
    monkeypatch.setattr(
        paper.system_identity, "rehearsal_identity",
        lambda: {"identity_hash": "test-runtime"})


def _broker(*, equity="1000", cash="1000", account=ACCOUNT):
    return SimulatedBroker(
        account=BrokerAccountIdentity("sim", account),
        equity=D(equity), cash=D(cash))


def _bind(conn):
    return binding.bind(
        conn, deployment_id="sentinel-paper-test", broker="sim",
        broker_account_id=ACCOUNT)


def _publish(conn):
    return publication.publish(
        conn, window_start=PRIOR.isoformat(), window_end=DECISION.isoformat(),
        evidence={"frontier": DECISION.isoformat(), "test": True})


def _ready(monkeypatch, *, frontier=DECISION.isoformat()):
    monkeypatch.setattr(
        paper.readiness, "check_readiness",
        lambda _conn, **_kwargs: SimpleNamespace(ready=True, failures=[]))
    monkeypatch.setattr(
        paper.feed_store, "latest_visible_session", lambda _conn: frontier)
    monkeypatch.setattr(
        paper.calendar, "latest_closed_session",
        lambda _now_et=None: DECISION.isoformat())
    monkeypatch.setattr(
        paper.calendar, "sessions_in_range",
        lambda start, end: ["2026-08-10", "2026-08-11"]
        if (dt.date.fromisoformat(str(start)), dt.date.fromisoformat(str(end)))
        == (dt.date(2026, 8, 8), DECISION) else [])
    monkeypatch.setattr(
        paper.calendar, "next_session",
        lambda session: EFFECTIVE.isoformat()
        if str(session) == DECISION.isoformat()
        else (dt.date.fromisoformat(str(session))
              + dt.timedelta(days=1)).isoformat())


def _episode() -> HoldingEpisode:
    return HoldingEpisode(
        security_id=AAA.security_id, ticker=AAA.symbol,
        issuer_id="issuer-aaa", slot_id=0,
        signal_date="2026-08-06", entry_date="2026-08-07",
        entry_raw_open=100.0, entry_split_adjusted_price=100.0,
        initial_shares=10.0, current_shares=10.0)


def _state(*, session=PRIOR, data_version=1, with_target=False) -> SessionState:
    state = SessionState.fresh(
        starting_cash=1000, controller=Controller(CONFIG),
        strategy_identity=IDENTITY)
    if with_target:
        portfolio = PortfolioState.from_dict(state.wealth_core)
        portfolio.episodes[0] = _episode()
        state.wealth_core = portfolio.to_dict()
        state.last_known = {AAA.security_id: 100.0}
        state.feed["series"][AAA.security_id] = {
            "security_id": AAA.security_id,
            "ticker": AAA.symbol,
            "issuer_id": "issuer-aaa",
            "split_factor": 1.0,
            "sessions": [],
            "session_indices": [],
            "signal_closes": [],
            "raw_closes": [],
            "volumes": [],
        }
    state.last_processed_session = session.isoformat()
    state.data_version = data_version
    state.last_decision = {
        "session": session.isoformat(),
        "target_core_exposure": "1",
        "reason": "TEST",
        "evidence": {},
    }
    state.last_evidence = {
        "wealth_core": {"estimated_equity": "1000"},
        "observation": {},
    }
    return state


def _persist_state(conn, state: SessionState) -> None:
    catchup._mark_processed(                              # noqa: SLF001
        conn, dt.date.fromisoformat(state.last_processed_session),
        state.to_dict())
    conn.commit()


def _plan(state: SessionState, pinned, bound, *, plan_id=None,
          basket=None) -> ExecutionPlan:
    plan = ExecutionPlan(
        plan_id="pending", decision_session=DECISION,
        effective_session=EFFECTIVE, target_exposure=D("1"),
        target_basket=dict(basket or {DEFENSIVE_SECURITY_ID: D(0)}),
        data_version=pinned.version,
        shadow_snapshot_hash=state.state_hash,
        sentinel_transition_hash=paper._hash(state.last_decision),  # noqa: SLF001
        strategy_fingerprint=paper._hash(state.strategy_identity),  # noqa: SLF001
        deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id,
        takeover_epoch=bound.takeover_epoch,
        publication_fingerprint=publication_fingerprint(pinned),
        account_nav=D("1000"), account_cash=D("1000"), cash_residual=D(0),
        defensive_security=DEFENSIVE_SECURITY_ID)
    return ExecutionPlan(**{
        **plan.__dict__,
        "plan_id": plan_id or f"sentinel-{plan.fingerprint()}",
    })


def _install_current_authorities(conn, *, with_target=False):
    bound = _bind(conn)
    pinned = _publish(conn)
    state = _state(
        session=DECISION, data_version=pinned.version,
        with_target=with_target)
    _persist_state(conn, state)
    basket = ({AAA.security_id: D("10"), DEFENSIVE_SECURITY_ID: D(0)}
              if with_target else None)
    plan = journal.adopt_current_plan(
        conn, _plan(state, pinned, bound, basket=basket))
    return bound, pinned, state, plan


def _advance_stub(_conn, session, prior, **_kwargs):
    """A deterministic canonical-v3 transition at the orchestration seam."""
    state = SessionState.from_dict(prior)
    state.last_processed_session = session
    state.data_version = 1
    state.controller_session_history = [
        *state.controller_session_history, session]
    state.last_decision = {
        "session": session,
        "target_core_exposure": "1",
        "reason": "TEST",
        "evidence": {},
    }
    state.last_evidence = {
        "wealth_core": {"estimated_equity": "1000"},
        "observation": {},
    }
    return state.to_dict()


def _prepare(conn, broker, **overrides):
    kwargs = {
        "conn": conn,
        "broker": broker,
        "base_url": DEFAULT_BASE_URL,
        "through": DECISION,
        "expected_account": ACCOUNT,
        "controller_config": CONFIG,
        "strategy_identity": IDENTITY,
    }
    kwargs.update(overrides)
    return asyncio.run(paper.prepare_paper_plan(**kwargs))


def _execute(conn, broker, **overrides):
    plan = journal.latest_plan(conn)
    kwargs = {
        "conn": conn,
        "broker": broker,
        "base_url": DEFAULT_BASE_URL,
        "confirm_account": ACCOUNT,
        "confirm_plan_id": plan.plan_id if plan else "missing",
        "confirm_effective_session": EFFECTIVE,
        "confirm_submit": True,
        "today": EFFECTIVE,
    }
    kwargs.update(overrides)
    return asyncio.run(paper.execute_paper_plan(**kwargs))


def _mutations(broker):
    return [call for call in broker.calls
            if call.startswith("submit:") or call.startswith("cancel:")]


class TestPaperAccountInspection:
    def test_complete_unbound_inherited_book_is_visible_without_mutation(
            self, conn):
        broker = _broker(equity="12345.67", cash="2345.67")
        broker.seed_position(AAA, "5.25")
        broker.seed_foreign_order(
            AAA, side=Side.SELL, qty="2", order_id="legacy-open-1")

        result = asyncio.run(paper.inspect_paper_account(
            conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
            expected_account=ACCOUNT))
        output = result.to_dict()

        assert output["endpoint"] == DEFAULT_BASE_URL
        assert output["account"] == {
            "broker": "sim", "account_id": ACCOUNT, "status": "ACTIVE",
            "trading_blocked": False, "account_blocked": False,
            "trade_suspended_by_user": False, "multiplier": "1",
            "equity": "12345.67", "cash": "2345.67",
            "buying_power": "2345.67"}
        assert output["binding_state"] == "UNBOUND"
        assert output["binding"] is None
        assert output["observation_complete"] is True
        assert output["approval_ready"] is True
        assert output["approval_blockers"] == []
        assert output["positions"] == [{
            "security_id": AAA.security_id, "symbol": AAA.symbol,
            "broker_instrument_id": None, "quantity": "5.25"}]
        assert output["working_open_orders"] == [{
            "broker_order_id": "legacy-open-1", "client_key": None,
            "security_id": AAA.security_id, "symbol": AAA.symbol,
            "broker_instrument_id": None, "side": "SELL",
            "state": "ACKNOWLEDGED", "quantity": "2",
            "filled_quantity": "0", "remaining_quantity": "2",
            "submitted_at": broker.now.isoformat()}]
        assert output["broker_mutations_permitted"] is False
        assert _mutations(broker) == []

    def test_clean_database_without_binding_table_is_read_only_unbound(
            self, conn):
        """The mandatory pre-migration inspection does not install a schema."""
        with conn.cursor() as cur:
            cur.execute("DROP TABLE sentinel_account_binding")
        conn.commit()
        broker = _broker()

        output = asyncio.run(paper.inspect_paper_account(
            conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
            expected_account=ACCOUNT)).to_dict()

        assert output["binding_state"] == "UNBOUND"
        assert output["binding"] is None
        assert output["approval_ready"] is True
        assert output["broker_mutations_permitted"] is False
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('public.sentinel_account_binding')")
            assert cur.fetchone()[0] is None
        assert _mutations(broker) == []

    @pytest.mark.parametrize(
        ("attribute", "value", "blocker"),
        [
            pytest.param("status", "INACTIVE", "account_status:INACTIVE",
                         id="inactive"),
            pytest.param("trading_blocked", True, "trading_blocked",
                         id="blocked"),
            pytest.param("multiplier", D(2), "cash_only_multiplier:2",
                         id="margin-multiplier"),
            pytest.param("buying_power", D("900"),
                         "unsettled_buying_power:900:cash:1000",
                         id="unsettled"),
            pytest.param("buying_power", D("1100"),
                         "margin_buying_power:1100:cash:1000",
                         id="margin-buying-power"),
        ])
    def test_well_formed_unsafe_facts_remain_visible_but_not_approval_ready(
            self, conn, attribute, value, blocker):
        broker = _broker()
        setattr(broker, attribute, value)

        output = asyncio.run(paper.inspect_paper_account(
            conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
            expected_account=ACCOUNT)).to_dict()

        assert output["approval_ready"] is False
        assert blocker in output["approval_blockers"]
        assert output["broker_mutations_permitted"] is False
        assert _mutations(broker) == []

    def test_existing_matching_binding_is_reported_but_not_migration_ready(
            self, conn):
        bound = _bind(conn)
        broker = _broker()

        output = asyncio.run(paper.inspect_paper_account(
            conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
            expected_account=ACCOUNT)).to_dict()

        assert output["binding"] == bound.to_dict()
        assert output["binding_state"] == binding.SENTINEL_OWNED
        assert output["binding_matches_account"] is True
        assert output["approval_ready"] is False
        assert output["approval_blockers"] == [
            f"account_already_bound:{binding.SENTINEL_OWNED}"]
        assert _mutations(broker) == []

    def test_account_confirmation_mismatch_refuses_before_observation(
            self, conn):
        broker = _broker()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="connected to paper account.*expected WRONG"):
            asyncio.run(paper.inspect_paper_account(
                conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
                expected_account="WRONG"))

        assert broker.calls == ["account_snapshot"]
        assert _mutations(broker) == []

    def test_existing_binding_mismatch_refuses(self, conn):
        _bind(conn)
        broker = _broker(account="OTHER-PAPER")

        with pytest.raises(
                paper.PaperActivationRefused,
                match="canonical binding names.*but the broker reports"):
            asyncio.run(paper.inspect_paper_account(
                conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
                expected_account="OTHER-PAPER"))

        assert "get_positions" in broker.calls
        assert _mutations(broker) == []

    def test_live_endpoint_refuses_before_any_broker_read(self, conn):
        broker = _broker()

        with pytest.raises(LiveEndpointRefused):
            asyncio.run(paper.inspect_paper_account(
                conn=conn, broker=broker,
                base_url="https://api.alpaca.markets",
                expected_account=ACCOUNT))

        assert broker.calls == []

    def test_incomplete_observation_refuses_without_mutation(self, conn):
        broker = _broker()
        broker.schedule_observe(FaultKind.TRUNCATED_ORDERS)

        with pytest.raises(IncompleteObservation, match="requires a COMPLETE"):
            asyncio.run(paper.inspect_paper_account(
                conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
                expected_account=ACCOUNT))

        assert "get_positions" in broker.calls
        assert _mutations(broker) == []

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            pytest.param("status", "", "missing account status",
                         id="missing-status"),
            pytest.param("trading_blocked", "false", "non-boolean block flags",
                         id="malformed-block-flag"),
            pytest.param("buying_power", None, "malformed Decimal fields",
                         id="missing-buying-power"),
        ])
    def test_malformed_account_evidence_refuses(
            self, conn, monkeypatch, field, value, message):
        broker = _broker()
        valid = asyncio.run(broker.account_snapshot())
        malformed = BrokerAccountSnapshot(**{
            **valid.__dict__, field: value})

        async def account_snapshot():
            broker.calls.append("account_snapshot:malformed")
            return malformed

        monkeypatch.setattr(broker, "account_snapshot", account_snapshot)
        calls_before = list(broker.calls)

        with pytest.raises(paper.PaperActivationRefused, match=message):
            asyncio.run(paper.inspect_paper_account(
                conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
                expected_account=ACCOUNT))

        assert broker.calls == [*calls_before, "account_snapshot:malformed"]
        assert "get_positions" not in broker.calls
        assert _mutations(broker) == []


class _MigrationBridge:
    """Legacy administrative seam backed by the simulated paper book."""

    adapter = SimpleNamespace(name="sim")

    def __init__(self, execution_broker):
        self.execution_broker = execution_broker
        self.closes = []
        self.liquidation_keys = {}
        self.liquidation_orders = {}
        self.observations = []

    async def account(self):
        return BrokerAccountIdentity("sim", ACCOUNT)

    async def observe(self):
        observed = await self.execution_broker.observe()
        positions = {
            position.instrument.symbol: position.quantity
            for position in observed.positions if position.quantity
        }
        identities = {
            position.instrument.symbol: (
                position.instrument.broker_id
                or f"asset-{position.instrument.security_id}")
            for position in observed.positions if position.quantity
        }
        orders = tuple(
            OpenOrder(
                order_id=order.broker_order_id,
                ticker=order.instrument.symbol,
                side=order.side.value,
                client_key=order.client_key, state=order.state,
                quantity=order.quantity,
                filled_quantity=order.filled_quantity,
                filled_average_price=order.filled_average_price,
                broker_instrument_id=(order.instrument.broker_id
                                      or f"asset-{order.instrument.security_id}"))
            for order in observed.orders if order.is_working)
        result = AccountObservation(
            positions=positions, position_security_ids=identities,
            open_orders=orders)
        self.observations.append(result)
        return result

    async def cancel_orders(self, _order_ids):
        raise AssertionError("this inherited-book fixture has no legacy orders")

    async def close_position(self, ticker):
        self.closes.append(ticker)
        for _security_id, (instrument, quantity) in list(
                self.execution_broker._positions.items()):
            if instrument.symbol == ticker:
                key = f"legacy-migration:{ticker}"
                outcome = await self.execution_broker.submit(
                    client_key=key, instrument=instrument,
                    side=Side.SELL, quantity=quantity)
                self.liquidation_keys[ticker] = key
                return CloseResult(
                    ticker=ticker, broker_order_id=outcome.broker_order_id,
                    status=outcome.state.value, error=None)
        return CloseResult(
            ticker=ticker, broker_order_id=None,
            status=None, error="position disappeared before close")

    async def submit_liquidation(self, command):
        ticker = command.instrument.symbol
        self.closes.append(ticker)
        outcome = await self.execution_broker.submit(
            client_key=command.client_key,
            instrument=BrokerInstrument(
                security_id="LEGACY", symbol=ticker,
                broker_id=command.instrument.broker_id),
            side=Side.SELL, quantity=command.quantity)
        self.liquidation_keys[ticker] = command.client_key
        self.liquidation_orders[command.client_key] = outcome.broker_order_id
        return outcome

    async def find_liquidation(self, client_key):
        order = await self.execution_broker.find_by_client_key(client_key)
        if order is None:
            return None
        return OpenOrder(
            order_id=order.broker_order_id,
            ticker=order.instrument.symbol, side=order.side.value,
            client_key=order.client_key, state=order.state,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            filled_average_price=order.filled_average_price,
            broker_instrument_id=order.instrument.broker_id)


async def _nosleep(_seconds):
    return None


def test_fresh_boot_warms_exactly_252_feature_sessions_without_path_history(
        monkeypatch):
    sessions = [f"S{i:04d}" for i in range(1, 254)]
    warm = sessions[:-1]
    meta = {AAA.security_id: SecurityMeta(
        AAA.security_id, AAA.symbol, category="Domestic Common Stock",
        permaticker=AAA.security_id, first_session=warm[0])}
    window = CorpusWindow(
        sessions=warm, meta=meta,
        bars_by_session={session: [VendorBar(
            session=session, security_id=AAA.security_id, ticker=AAA.symbol,
            raw_close=100.0, raw_open=100.0, volume=1_000_000.0)]
            for session in warm})
    monkeypatch.setattr(
        paper.calendar, "previous_sessions",
        lambda through, count: sessions if (through, count) == (sessions[-1], 253)
        else [])
    monkeypatch.setattr(
        paper, "load_window",
        lambda _conn, *, start, end: window
        if (start, end) == (warm[0], warm[-1]) else None)
    account = BrokerAccountSnapshot(
        identity=BrokerAccountIdentity("sim", ACCOUNT),
        equity=D("1000"), cash=D("1000"))

    state = paper._fresh_warmed_state(                    # noqa: SLF001
        object(), through=sessions[-1], count=252, account=account,
        controller_config=CONFIG, strategy_identity=IDENTITY,
        publication_version=7)

    portfolio = PortfolioState.from_dict(state.wealth_core)
    assert state.version == 3
    assert state.data_version == 7
    assert state.feed["session_index"] == 251
    assert len(state.feed["series"][AAA.security_id]["sessions"]) == 127
    assert state.last_processed_session is None
    assert state.last_decision is None
    assert state.controller_session_history == []
    assert portfolio.episodes == {}
    assert state.pending == []
    assert state.ledger["events"] == []


def test_real_fresh_boot_pipeline_is_restart_equivalent_and_adopts_one_plan(
        conn, pg, monkeypatch):
    """Fresh preparation crosses every durable production seam exactly once."""
    config = ControllerConfig(
        ordinary_stress_drawdown=CONFIG.ordinary_stress_drawdown,
        ordinary_target_core=CONFIG.ordinary_target_core,
        severe_target_core=CONFIG.severe_target_core,
        slow_entry=CONFIG.slow_entry, slow_recovery=CONFIG.slow_recovery,
        fast_entry={
            "max_shadow_drawdown": -0.10,
            "min_damaged_breadth": 0.85,
            "max_green_breadth": 0.20,
            "short_loss_or": [
                {"max_shadow_r5": -0.05},
                {"max_shadow_r10": -0.08},
            ],
            "min_damaged_breadth_delta5": 0.40,
            "min_spy_vol5_over_vol20_minus_1": 0.04,
            "confirmation_or": [
                {"max_spy_r20": -0.01},
                {"max_shadow_r10": -0.10},
            ],
        },
        fast_recovery=CONFIG.fast_recovery, ramp=CONFIG.ramp,
        healthy=CONFIG.healthy, strategy_id=CONFIG.strategy_id,
        digest=CONFIG.digest)
    sessions = [
        (DECISION - dt.timedelta(days=offset)).isoformat()
        for offset in range(252, -1, -1)
    ]
    warm = sessions[:-1]
    meta = {AAA.security_id: SecurityMeta(
        AAA.security_id, AAA.symbol, category="Domestic Common Stock",
        permaticker=AAA.security_id, first_session=sessions[0])}

    def bar(session, index):
        price = 100.0 + index / 10.0
        return VendorBar(
            session=session, security_id=AAA.security_id, ticker=AAA.symbol,
            raw_close=price, raw_open=price, volume=1_000_000.0)

    window = CorpusWindow(
        sessions=warm, meta=meta,
        bars_by_session={
            session: [bar(session, index)]
            for index, session in enumerate(warm)
        })
    pinned = _publish(conn)
    current = PublishedSession(
        session=DECISION.isoformat(), data_version=pinned.version,
        bars=(bar(DECISION.isoformat(), len(warm)),), meta=meta,
        sectors={AAA.security_id: "Information Technology"},
        spy_sessions=tuple(sessions[-41:]),
        spy_expected_sessions=tuple(sessions[-41:]),
        spy_closeadj=tuple(
            400.0 + index + (0.25 if index % 3 == 0 else 0.0)
            for index in range(41)))
    _bind(conn)
    _ready(monkeypatch)

    window_loads = []
    published_loads = []

    def load_window(_conn, *, start, end):
        window_loads.append((start, end))
        assert (start, end) == (warm[0], warm[-1])
        return window

    def load_published(_conn, session, *, known_feed_security_ids):
        published_loads.append((session, tuple(known_feed_security_ids)))
        assert session == DECISION.isoformat()
        assert AAA.security_id in known_feed_security_ids
        return current

    monkeypatch.setattr(
        paper.calendar, "previous_sessions",
        lambda through, count: sessions
        if (str(through), count) == (DECISION.isoformat(), 253) else [])
    monkeypatch.setattr(
        paper.calendar, "sessions_in_range",
        lambda start, end: [DECISION.isoformat()]
        if (dt.date.fromisoformat(str(start)), dt.date.fromisoformat(str(end)))
        == (DECISION, DECISION) else [])
    monkeypatch.setattr(paper, "load_window", load_window)
    monkeypatch.setattr(paper, "load_published_session", load_published)
    broker = _broker(equity="100000", cash="100000")

    first = _prepare(
        conn, broker, controller_config=config, strategy_identity=IDENTITY)
    first_state = catchup.resume_state(conn)
    canonical = SessionState.from_dict(first_state)

    assert first.sessions_replayed == 1
    assert first.warmup_sessions == 252
    assert canonical.version == 3
    assert canonical.last_processed_session == DECISION.isoformat()
    assert canonical.feed["session_index"] == 252
    assert first.plan.shadow_snapshot_hash == canonical.state_hash
    assert journal.latest_plan(conn) == first.plan
    assert window_loads == [(warm[0], warm[-1])]
    assert [session for session, _known in published_loads] == [
        DECISION.isoformat()]
    # The equality/inspection reads above opened a PostgreSQL transaction on
    # this connection. End it before a second process runs schema checks; the
    # restart is about durable state, not lock contention between two active
    # transactions in one test.
    conn.commit()

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        second = _prepare(
            restarted, broker, controller_config=config,
            strategy_identity=IDENTITY)

        assert second.sessions_replayed == 0
        assert second.warmup_sessions == 0
        assert catchup.resume_state(restarted) == first_state
        assert SessionState.from_dict(
            catchup.resume_state(restarted)).version == 3
        assert second.plan == first.plan
        assert journal.latest_plan(restarted) == first.plan
        with restarted.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_execution_plans"
                " WHERE superseded_by IS NULL")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM sentinel_execution_plans")
            assert cur.fetchone()[0] == 1
    finally:
        restarted.close()

    assert window_loads == [(warm[0], warm[-1])]
    assert len(published_loads) == 1
    assert _mutations(broker) == []


def test_prepare_resumes_v3_across_missed_sessions_and_restart_is_equivalent(
        conn, monkeypatch):
    bound = _bind(conn)
    pinned = _publish(conn)
    prior = _state(session=PRIOR, data_version=pinned.version)
    _persist_state(conn, prior)
    old = _plan(
        prior, pinned, bound, plan_id="plan-before-catchup",
        basket={DEFENSIVE_SECURITY_ID: D(0)})
    old = ExecutionPlan(**{
        **old.__dict__, "decision_session": PRIOR,
        "effective_session": dt.date(2026, 8, 10)})
    journal.adopt_current_plan(conn, old)
    _ready(monkeypatch)
    monkeypatch.setattr(paper, "advance_and_persist", _advance_stub)
    broker = _broker()

    first = _prepare(conn, broker)
    state_after_first = catchup.resume_state(conn)
    restarted = _prepare(conn, broker)

    assert first.sessions_replayed == 2
    assert first.superseded_plans == 1
    assert SessionState.from_dict(state_after_first).version == 3
    assert catchup.last_processed_session(conn) == DECISION
    assert restarted.sessions_replayed == 0
    assert catchup.resume_state(conn) == state_after_first
    assert restarted.plan == first.plan
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_execution_plans"
                    " WHERE superseded_by IS NULL")
        assert cur.fetchone()[0] == 1


def test_unbound_preparation_refuses_before_any_broker_read(conn):
    broker = _broker()

    with pytest.raises(binding.AccountNotBound):
        _prepare(conn, broker)

    assert broker.calls == []


def test_missing_canonical_state_never_bootstraps_over_a_surviving_book(
        conn, monkeypatch):
    _bind(conn)
    _publish(conn)
    _ready(monkeypatch)
    broker = _broker()
    observation = BrokerObservation(
        observed_at=broker.now,
        positions=(BrokerPosition(instrument=AAA, quantity=D("5")),))
    preflight = SimpleNamespace(
        runtime_state=RuntimeState.RUNNING, clean=True,
        observation=observation, detail="attributed restored book")

    async def reconcile(**_kwargs):
        return preflight

    monkeypatch.setattr(paper.reconciliation, "reconcile", reconcile)

    with pytest.raises(
            paper.PaperActivationRefused,
            match="Feature warm-up cannot reconstruct"):
        _prepare(conn, broker)

    assert catchup.resume_state(conn) is None
    assert journal.latest_plan(conn) is None
    assert _mutations(broker) == []


def test_preparation_is_read_only_at_the_broker(conn, monkeypatch):
    _bind(conn)
    pinned = _publish(conn)
    _persist_state(conn, _state(session=PRIOR, data_version=pinned.version))
    _ready(monkeypatch)
    monkeypatch.setattr(paper, "advance_and_persist", _advance_stub)
    broker = _broker()

    result = _prepare(conn, broker)

    assert result.plan == journal.latest_plan(conn)
    assert _mutations(broker) == []
    assert "account_snapshot" in broker.calls
    assert "get_positions" in broker.calls


def test_preparation_snapshots_cash_after_reconciling_a_boundary_fill(
        conn, monkeypatch):
    bound = _bind(conn)
    pinned = _publish(conn)
    _persist_state(conn, _state(session=PRIOR, data_version=pinned.version))
    _ready(monkeypatch)
    monkeypatch.setattr(paper, "advance_and_persist", _advance_stub)
    broker = _broker()
    identity = CommandIdentity(
        deployment=bound.identity, plan_id="prior-plan",
        security_id=AAA.security_id)
    outcome = asyncio.run(broker.submit(
        client_key=identity.client_key, instrument=AAA,
        side=Side.BUY, quantity=D(1)))
    journal.save_command(conn, Command(
        identity=identity, instrument=AAA, side=Side.BUY, quantity=D(1),
        state=outcome.state, broker_order_id=outcome.broker_order_id))
    broker.observe_hooks = [lambda sim: sim.fill(identity.client_key)]
    mutations_before = list(_mutations(broker))

    result = _prepare(conn, broker)

    assert result.plan.account_cash == D("900")
    assert broker.calls.index("get_positions") \
        < broker.calls.index("account_snapshot")
    assert _mutations(broker) == mutations_before


def test_preparation_refuses_an_early_current_session_frontier_with_real_calendar(
        conn, monkeypatch):
    """Fresh is not closed: the real XNYS clock keeps an early bar out.

    Readiness intentionally accepts today's real session before its close as
    early rather than stale.  Preparation needs the stronger proposition that
    the close which defines the immutable decision has actually happened.  Do
    not monkeypatch ``paper.calendar`` in this falsifier.
    """
    _bind(conn)
    _publish(conn)
    monkeypatch.setattr(
        paper.readiness, "check_readiness",
        lambda _conn, **_kwargs: SimpleNamespace(ready=True, failures=[]))
    monkeypatch.setattr(
        paper.feed_store, "latest_visible_session",
        lambda _conn: EFFECTIVE.isoformat())
    broker = _broker()
    before_close = dt.datetime(
        EFFECTIVE.year, EFFECTIVE.month, EFFECTIVE.day, 15, 59,
        tzinfo=ZoneInfo(paper.calendar.EXCHANGE_TZ))

    with pytest.raises(
            paper.PaperActivationRefused,
            match="not the latest closed XNYS session"):
        _prepare(
            conn, broker, through=EFFECTIVE, now_et=before_close)

    assert paper.calendar.latest_closed_session(before_close) \
        == DECISION.isoformat()
    assert broker.calls == []
    assert _mutations(broker) == []


def test_preparation_recognizes_the_real_half_day_close_at_1300(
        conn, monkeypatch):
    """The half-day decision may advance after its actual XNYS close.

    Stop deliberately at the typed account-snapshot boundary: reaching it after
    reconciliation proves the stronger preparation close gate accepted 13:01
    ET without needing a corpus fixture for this historical session. Do not
    monkeypatch ``paper.calendar``.
    """
    _bind(conn)
    _publish(conn)
    monkeypatch.setattr(
        paper.readiness, "check_readiness",
        lambda _conn, **_kwargs: SimpleNamespace(ready=True, failures=[]))
    monkeypatch.setattr(
        paper.feed_store, "latest_visible_session",
        lambda _conn: HALF_DAY_EFFECTIVE.isoformat())
    broker = _broker()
    after_half_day_close = dt.datetime(
        2024, 11, 29, 13, 1,
        tzinfo=ZoneInfo(paper.calendar.EXCHANGE_TZ))

    class ReachedBrokerRead(RuntimeError):
        pass

    async def stop_at_first_read():
        broker.calls.append("account_snapshot")
        raise ReachedBrokerRead

    monkeypatch.setattr(broker, "account_snapshot", stop_at_first_read)

    assert paper.calendar.latest_closed_session(after_half_day_close) \
        == HALF_DAY_EFFECTIVE.isoformat()
    with pytest.raises(ReachedBrokerRead):
        _prepare(
            conn, broker, through=HALF_DAY_EFFECTIVE,
            now_et=after_half_day_close)

    assert "account_snapshot" in broker.calls
    assert _mutations(broker) == []


@pytest.mark.parametrize("equity", ["999", "1001"], ids=["lower", "higher"])
def test_same_session_prepare_allows_market_nav_move_without_replacing_plan(
        conn, monkeypatch, equity):
    _bound, _pinned, _state_value, durable_plan = \
        _install_current_authorities(conn)
    durable_state = catchup.resume_state(conn)
    _ready(monkeypatch)
    broker = _broker(equity=equity)

    result = _prepare(conn, broker)

    assert result.plan == durable_plan
    assert journal.latest_plan(conn) == durable_plan
    assert catchup.resume_state(conn) == durable_state
    assert "account_snapshot" in broker.calls
    assert "get_positions" in broker.calls
    assert _mutations(broker) == []


@pytest.mark.parametrize("cash", ["998", "1002"], ids=["lower", "higher"])
def test_same_session_prepare_refuses_unexplained_cash_without_replacing_plan(
        conn, monkeypatch, cash):
    _bound, _pinned, _state_value, durable_plan = \
        _install_current_authorities(conn)
    durable_state = catchup.resume_state(conn)
    _ready(monkeypatch)
    broker = _broker(cash=cash)

    with pytest.raises(paper.PaperActivationRefused, match="account cash"):
        _prepare(conn, broker)

    assert journal.latest_plan(conn) == durable_plan
    assert catchup.resume_state(conn) == durable_state
    assert "get_positions" in broker.calls
    assert _mutations(broker) == []


def test_restart_cash_authority_uses_durable_average_fill_price(conn, pg):
    bound, _pinned, _state_value, durable_plan = \
        _install_current_authorities(conn)
    filled = Command(
        identity=CommandIdentity(
            deployment=bound.identity, plan_id=durable_plan.plan_id,
            security_id=AAA.security_id),
        instrument=AAA, side=Side.BUY, quantity=D(1),
        state=CommandState.FILLED, broker_order_id="sim-filled-1",
        filled_quantity=D(1), filled_average_price=D("100.25"))
    journal.save_command(conn, filled)

    # A new database connection is the durable restart boundary. The complete
    # open observation contains no terminal-history row; the journaled Decimal
    # average is sufficient to explain the cash movement.
    restarted = feed_store.connect(pg.sync_dsn)
    try:
        plan_after_restart = journal.load_plan(
            restarted, durable_plan.plan_id)
        account = BrokerAccountSnapshot(
            identity=BrokerAccountIdentity("sim", ACCOUNT),
            equity=D("1000"), cash=D("899.75"),
            buying_power=D("899.75"), multiplier=D(1), status="ACTIVE")
        observation = BrokerObservation(
            observed_at=dt.datetime.now(dt.timezone.utc), orders=(), positions=())

        paper._cash_authority_or_refuse(                 # noqa: SLF001
            restarted, plan=plan_after_restart,
            deployment=bound.identity, account=account,
            observation=observation)

        loaded = journal.load_commands(
            restarted, bound.identity, plan_id=durable_plan.plan_id)
        assert loaded[0].filled_average_price == D("100.25")
    finally:
        restarted.close()


class TestStrictExecutionGate:
    def test_missing_system_certificate_refuses_before_broker_read(
            self, conn, pg, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)

        def refuse(*_args, **_kwargs):
            other = feed_store.connect(pg.sync_dsn)
            try:
                with other.cursor() as cur:
                    cur.execute(
                        "SELECT pg_try_advisory_lock(%s)",
                        (journal.WRITER_LOCK_KEY,))
                    acquired = cur.fetchone()[0]
                    if acquired:
                        cur.execute(
                            "SELECT pg_advisory_unlock(%s)",
                            (journal.WRITER_LOCK_KEY,))
                other.commit()
            finally:
                other.close()
            assert acquired is False, (
                "system certificate was checked outside the writer lock")
            raise authority.AuthorityRefused(
                "no active system certificate is installed")

        monkeypatch.setattr(paper, "require_current_authority", refuse)
        broker = _broker()

        with pytest.raises(authority.AuthorityRefused, match="no active"):
            _execute(conn, broker)

        assert broker.calls == []
        assert _mutations(broker) == []

    def test_rollout_version_change_stales_plan_before_broker_read(
            self, conn, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        certificate_sha = "d" * 64
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_system_certificates"
                " (certificate_sha256,manifest_bytes,manifest,"
                "  allowed_rollout_modes)"
                " VALUES (%s,'{}'::bytea,'{}'::jsonb,"
                "         '[\"CONTROLLER\"]'::jsonb)",
                (certificate_sha,))
            cur.execute(
                "UPDATE sentinel_rollout_state"
                " SET mode='CONTROLLER',version=2,certificate_sha256=%s"
                " WHERE id=1", (certificate_sha,))
            cur.execute(
                "INSERT INTO sentinel_rollout_events"
                " (version,from_mode,to_mode,certificate_sha256,reason)"
                " VALUES (2,'PINNED_1_00','CONTROLLER',%s,"
                "         'test coherent authority transition')",
                (certificate_sha,))
        conn.commit()
        broker = _broker()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="rollout mode/version authority is stale"):
            _execute(conn, broker)

        assert broker.calls == []
        assert _mutations(broker) == []

    def test_half_day_after_close_refuses_before_broker_read(
            self, conn, monkeypatch):
        """A DAY order at 13:01 must not queue into the next session."""
        bound = _bind(conn)
        pinned = publication.publish(
            conn, window_start=HALF_DAY_DECISION.isoformat(),
            window_end=HALF_DAY_DECISION.isoformat(),
            evidence={"frontier": HALF_DAY_DECISION.isoformat(),
                      "test": "half-day"})
        state = _state(
            session=HALF_DAY_DECISION, data_version=pinned.version)
        _persist_state(conn, state)
        plan = ExecutionPlan(
            plan_id="pending", decision_session=HALF_DAY_DECISION,
            effective_session=HALF_DAY_EFFECTIVE, target_exposure=D("1"),
            target_basket={DEFENSIVE_SECURITY_ID: D(0)},
            data_version=pinned.version,
            shadow_snapshot_hash=state.state_hash,
            sentinel_transition_hash=paper._hash(               # noqa: SLF001
                state.last_decision),
            strategy_fingerprint=paper._hash(                   # noqa: SLF001
                state.strategy_identity),
            deployment_id=bound.deployment_id, broker=bound.broker,
            broker_account_id=bound.broker_account_id,
            takeover_epoch=bound.takeover_epoch,
            publication_fingerprint=publication_fingerprint(pinned),
            account_nav=D("1000"), account_cash=D("1000"),
            cash_residual=D(0), defensive_security=DEFENSIVE_SECURITY_ID)
        plan = ExecutionPlan(**{
            **plan.__dict__, "plan_id": f"sentinel-{plan.fingerprint()}",
        })
        journal.adopt_current_plan(conn, plan)
        monkeypatch.setattr(
            paper.readiness, "check_readiness",
            lambda _conn, **_kwargs: SimpleNamespace(ready=True, failures=[]))
        monkeypatch.setattr(
            paper.feed_store, "latest_visible_session",
            lambda _conn: HALF_DAY_DECISION.isoformat())
        broker = _broker()
        after_close = dt.datetime(
            2024, 11, 29, 13, 1,
            tzinfo=ZoneInfo(paper.calendar.EXCHANGE_TZ))

        assert paper.calendar.session_window(HALF_DAY_EFFECTIVE)[1].hour == 13
        with pytest.raises(
                paper.PaperActivationRefused,
                match="outside the certified XNYS execution window"):
            _execute(
                conn, broker, confirm_effective_session=HALF_DAY_EFFECTIVE,
                today=after_close)

        assert broker.calls == []
        assert _mutations(broker) == []

    def test_wrong_session_refuses_before_broker_read(self, conn, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker()

        with pytest.raises(paper.PaperActivationRefused, match="not today"):
            _execute(conn, broker, today=dt.date(2026, 8, 13))

        assert broker.calls == []

    def test_account_confirmation_refuses_before_broker_read(
            self, conn, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="paper-account confirmation mismatch"):
            _execute(conn, broker, confirm_account="SOME-OTHER-PAPER")

        assert broker.calls == []

    def test_connected_account_mismatch_refuses_before_submission(
            self, conn, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker(account="WRONG-SIM-PAPER")

        with pytest.raises(
                paper.PaperActivationRefused,
                match="does not match the durable binding"):
            _execute(conn, broker)

        assert "account_snapshot" in broker.calls
        assert _mutations(broker) == []

    @pytest.mark.parametrize(
        "equity", ["999", "1001"], ids=["lower", "higher"])
    def test_market_nav_move_does_not_invalidate_fixed_share_plan(
            self, conn, monkeypatch, equity):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker(equity=equity)

        result = _execute(conn, broker)

        assert result.session.submitted == ()
        assert "account_snapshot" in broker.calls
        assert "get_positions" in broker.calls
        assert _mutations(broker) == []

    def test_unknown_submit_is_reconciled_before_market_nav_authority(
            self, conn, monkeypatch):
        _bound, _pinned, _state_value, durable_plan = \
            _install_current_authorities(conn, with_target=True)
        _ready(monkeypatch)
        broker = _broker()
        broker.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)

        first = _execute(conn, broker)
        assert first.session.submitted[0].state is CommandState.UNKNOWN
        first_submit_count = len(_mutations(broker))

        # This is mark-to-market evidence, not cash movement. Restart must ask
        # for the durable key and recover the resting order before considering
        # any further command; an equity equality check ahead of reconciliation
        # would strand UNKNOWN forever.
        broker.equity = D("1100")
        second = _execute(conn, broker)
        commands = journal.load_commands(
            conn, binding.require(conn).identity,
            plan_id=durable_plan.plan_id)

        assert second.session.submitted == ()
        assert commands[0].state is CommandState.ACKNOWLEDGED
        assert len(_mutations(broker)) == first_submit_count

    @pytest.mark.parametrize("cash", ["998", "1002"], ids=["lower", "higher"])
    def test_unexplained_cash_mismatch_refuses_after_read_before_mutation(
            self, conn, monkeypatch, cash):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker(cash=cash)

        with pytest.raises(paper.PaperActivationRefused, match="account cash"):
            _execute(conn, broker)

        assert "get_positions" in broker.calls
        assert _mutations(broker) == []

    @pytest.mark.parametrize(
        ("multiplier", "buying_power", "message"),
        [
            pytest.param(D(2), D("2000"), "multiplier", id="margin-multiplier"),
            pytest.param(D(1), D("2000"), "buying power", id="margin-power"),
            pytest.param(D(1), D("900"), "buying power", id="unsettled-cash"),
        ])
    def test_margin_capable_paper_account_refuses_before_observation(
            self, conn, monkeypatch, multiplier, buying_power, message):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker()
        broker.multiplier = multiplier
        broker.buying_power = buying_power

        with pytest.raises(paper.PaperActivationRefused, match=message):
            _execute(conn, broker)

        assert "account_snapshot" in broker.calls
        assert "get_positions" not in broker.calls
        assert _mutations(broker) == []

    @pytest.mark.parametrize(
        ("attribute", "value", "message"),
        [
            pytest.param("status", "INACTIVE", "not ACTIVE", id="inactive"),
            pytest.param(
                "trading_blocked", True, "trading_blocked",
                id="trading-blocked"),
            pytest.param(
                "account_blocked", True, "account_blocked",
                id="account-blocked"),
            pytest.param(
                "trade_suspended_by_user", True, "trade_suspended_by_user",
                id="user-suspended"),
        ])
    def test_unavailable_paper_account_refuses_before_observation(
            self, conn, monkeypatch, attribute, value, message):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker()
        setattr(broker, attribute, value)

        with pytest.raises(paper.PaperActivationRefused, match=message):
            _execute(conn, broker)

        assert "account_snapshot" in broker.calls
        assert "get_positions" not in broker.calls
        assert _mutations(broker) == []

    def test_post_decision_split_refuses_the_stale_share_target(
            self, conn, monkeypatch):
        _install_current_authorities(conn, with_target=True)
        _ready(monkeypatch)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_bars (security_id,session,ticker,"
                " close_unadjusted) VALUES (%s,%s,%s,%s)",
                (AAA.security_id, DECISION, AAA.symbol, 100))
            cur.execute(
                "INSERT INTO sentinel_actions (ticker,session,action,value)"
                " VALUES (%s,%s,'split',2)",
                (AAA.symbol, EFFECTIVE))
        conn.commit()
        broker = _broker()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="corporate action.*changed target share counts"):
            _execute(conn, broker)

        assert "account_snapshot" in broker.calls
        assert "get_positions" not in broker.calls
        assert _mutations(broker) == []

    def test_pre_decision_split_ages_history_without_staling_current_target(
            self, conn, monkeypatch):
        bound, _pinned, _state_value, durable_plan = \
            _install_current_authorities(conn, with_target=True)
        _ready(monkeypatch)
        historical = Command(
            identity=CommandIdentity(
                deployment=bound.identity, plan_id="historical-plan",
                security_id=AAA.security_id, revision=0),
            instrument=AAA, side=Side.BUY, quantity=D("10"),
            state=CommandState.FILLED, filled_quantity=D("10"),
            filled_average_price=D("100"))
        journal.save_command(conn, historical)
        action_session = dt.date(2026, 8, 10)
        with conn.cursor() as cur:
            # Force the reconciliation history floor before the old split. The
            # current target was fixed one session later and must not inherit
            # that wider recovery horizon as a stale-target verdict.
            cur.execute(
                "UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s",
                (dt.datetime(2026, 8, 7, tzinfo=dt.timezone.utc),
                 historical.client_key))
            cur.execute(
                "INSERT INTO sentinel_bars (security_id,session,ticker,"
                " close_unadjusted) VALUES (%s,%s,%s,%s)",
                (AAA.security_id, action_session, AAA.symbol, 50))
            cur.execute(
                "INSERT INTO sentinel_actions (ticker,session,action,value)"
                " VALUES (%s,%s,'split',2)",
                (AAA.symbol, action_session))
        conn.commit()
        broker = _broker()
        broker.seed_position(AAA, "20")

        full_history = paper._action_lookup(               # noqa: SLF001
            conn, _state_value, EFFECTIVE)
        target_history = paper._target_action_lookup(      # noqa: SLF001
            conn, durable_plan, EFFECTIVE)
        assert full_history(AAA.security_id) == D("2")
        assert target_history(AAA.security_id) == D("1")

        result = _execute(conn, broker)

        assert [(command.side, command.quantity)
                for command in result.session.submitted] == [
                    (Side.SELL, D("10"))]
        assert len(_mutations(broker)) == 1

    @pytest.mark.parametrize(
        ("condition", "detail"),
        [
            pytest.param(
                "not active", "asset 'AAA' is not active", id="inactive"),
            pytest.param(
                "not tradable", "asset 'AAA' is not tradable",
                id="nontradable"),
        ])
    def test_increase_revalidates_held_instrument_and_refuses_unavailable_asset(
            self, conn, monkeypatch, condition, detail):
        _install_current_authorities(conn, with_target=True)
        _ready(monkeypatch)
        broker = _broker()
        observed_instrument = BrokerInstrument(
            security_id=AAA.security_id, symbol=AAA.symbol,
            broker_id="sim-held-asset")
        observation = BrokerObservation(
            observed_at=broker.now,
            positions=(BrokerPosition(
                instrument=observed_instrument, quantity=D("5")),))
        preflight = SimpleNamespace(
            runtime_state=RuntimeState.RUNNING, clean=True,
            observation=observation, detail="reconciled")

        async def reconcile(**_kwargs):
            return preflight

        async def refuse_resolution(*, security_id, symbol):
            broker.calls.append(
                f"resolve_instrument:{security_id}:{symbol}")
            raise alpaca.MalformedBrokerPayload(detail)

        monkeypatch.setattr(paper.reconciliation, "reconcile", reconcile)
        monkeypatch.setattr(broker, "resolve_instrument", refuse_resolution)

        with pytest.raises(
                paper.PaperActivationRefused,
                match=f"cannot resolve broker instrument.*{condition}"):
            _execute(conn, broker)

        assert (f"resolve_instrument:{AAA.security_id}:{AAA.symbol}"
                in broker.calls)
        assert _mutations(broker) == []

    def test_changed_publication_refuses_before_broker_read(
            self, conn, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        publication.publish(
            conn, window_start=PRIOR.isoformat(),
            window_end=DECISION.isoformat(), evidence={"replacement": True})
        broker = _broker()

        with pytest.raises(paper.PaperActivationRefused, match="publication"):
            _execute(conn, broker)

        assert broker.calls == []

    def test_changed_state_refuses_before_broker_read(self, conn, monkeypatch):
        _bound, _pinned, state, _plan_current = \
            _install_current_authorities(conn)
        _ready(monkeypatch)
        state.shadow_peak_nav += 1
        _persist_state(conn, state)
        broker = _broker()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="state fingerprint is stale"):
            _execute(conn, broker)

        assert broker.calls == []

    def test_changed_plan_economics_with_retained_stamps_and_id_refuse_every_load(
            self, conn, monkeypatch):
        _bound, _pinned, _state_value, durable_plan = \
            _install_current_authorities(conn)
        _ready(monkeypatch)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_execution_plans"
                " SET target_basket = %s::jsonb WHERE plan_id = %s",
                (json.dumps({"CORRUPTED": "1"}), durable_plan.plan_id))
        conn.commit()

        corrupted = journal.latest_plan(conn)
        assert corrupted.plan_id == durable_plan.plan_id
        assert corrupted.fingerprint() != durable_plan.fingerprint()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="does not match its deterministic economic identity"):
            paper.current_paper_plan(conn)

        prepare_broker = _broker()
        with pytest.raises(
                paper.PaperActivationRefused,
                match="does not match its deterministic economic identity"):
            _prepare(conn, prepare_broker)
        assert prepare_broker.calls == []

        execute_broker = _broker()
        with pytest.raises(
                paper.PaperActivationRefused,
                match="does not match its deterministic economic identity"):
            _execute(conn, execute_broker)
        assert execute_broker.calls == []
        assert _mutations(execute_broker) == []

    def test_failed_readiness_refuses_before_broker_read(
            self, conn, monkeypatch):
        _install_current_authorities(conn)
        failure = SimpleNamespace(name="continuity", detail="missing session")
        monkeypatch.setattr(
            paper.readiness, "check_readiness",
            lambda _conn, **_kwargs: SimpleNamespace(
                ready=False, failures=[failure]))
        broker = _broker()

        with pytest.raises(
                paper.PaperActivationRefused,
                match="corpus readiness failed"):
            _execute(conn, broker)

        assert broker.calls == []

    def test_live_url_refuses_before_broker_read(self, conn, monkeypatch):
        _install_current_authorities(conn)
        _ready(monkeypatch)
        broker = _broker()

        with pytest.raises(LiveEndpointRefused):
            _execute(
                conn, broker, base_url="https://api.alpaca.markets")

        assert broker.calls == []


def test_explicit_simulated_migration_then_prepare_and_restart_to_target(
        conn, pg, monkeypatch):
    """Inspect -> real legacy SELL -> settle -> prepare -> target BUY."""
    broker = _broker()
    legacy = BrokerInstrument(security_id="LEGACY", symbol="OLD")
    broker.seed_position(legacy, "25")

    with pytest.raises(binding.AccountNotBound):
        _prepare(conn, broker)
    assert broker.calls == []

    inspected = asyncio.run(paper.inspect_paper_account(
        conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
        expected_account=ACCOUNT)).to_dict()
    assert inspected["approval_ready"] is True
    assert inspected["binding_state"] == "UNBOUND"
    assert inspected["positions"] == [{
        "security_id": legacy.security_id, "symbol": legacy.symbol,
        "broker_instrument_id": None, "quantity": "25"}]
    assert inspected["working_open_orders"] == []
    assert inspected["broker_mutations_permitted"] is False
    assert _mutations(broker) == []

    migration = _MigrationBridge(broker)
    # Cycle 1 submits the administrative legacy SELL. Cycle 2 must observe it
    # still working and the inherited position still held. Only cycle 3 fills
    # it, making settlement/re-observation an explicit boundary rather than an
    # in-memory deletion masquerading as liquidation.
    broker.observe_hooks = [
        None,
        None,
        lambda sim: sim.fill(migration.liquidation_keys["OLD"]),
    ]
    migrated = asyncio.run(handover.migrate_account(
        broker=migration, conn=conn,
        deployment_id="sentinel-paper-test", expected_account=ACCOUNT,
        max_cycles=8, poll_seconds=0, sleep=_nosleep,
        notes="simulator handover test"))
    assert migrated.binding.is_owned
    assert migrated.cycles == 3
    assert migration.closes == ["OLD"]
    legacy_key = migration.liquidation_keys["OLD"]
    assert migration.observations[0].positions == {"OLD": 25.0}
    assert migration.observations[0].open_orders == ()
    assert migration.observations[1].positions == {"OLD": 25.0}
    assert [order.order_id for order in migration.observations[1].open_orders] \
        == ["sim-1"]
    assert migration.observations[2].is_flat()
    assert migration.observations[3].is_flat()
    assert migration.observations[4].is_flat()
    assert all(quantity == 0 for _instrument, quantity
               in broker._positions.values())
    assert _mutations(broker) == [f"submit:{legacy_key}"]

    # A new connection proves the durable migration/binding boundary before
    # preparation begins. The fixture-owned connection remains open for its
    # teardown, while the local connection models the restarted process.
    restarted_after_migration = feed_store.connect(pg.sync_dsn)
    assert binding.require(restarted_after_migration) == migrated.binding
    restarted_after_migration.close()
    pinned = _publish(conn)
    _persist_state(conn, _state(
        session=PRIOR, data_version=pinned.version, with_target=True))
    _ready(monkeypatch)
    monkeypatch.setattr(paper, "advance_and_persist", _advance_stub)
    monkeypatch.setattr(
        paper, "_load_marks_and_tickers",
        lambda _conn, _state_value, _session: (
            {AAA.security_id: D("100"), DEFENSIVE_SECURITY_ID: D("90")},
            {AAA.security_id: AAA.symbol, DEFENSIVE_SECURITY_ID: "BIL"}))

    prepared = _prepare(conn, broker)
    durable_state = catchup.resume_state(conn)
    assert prepared.plan.account_nav == D("3500")
    assert prepared.plan.target_basket[AAA.security_id] == D("35")
    assert journal.latest_plan(conn).plan_id == prepared.plan.plan_id
    assert _mutations(broker) == [f"submit:{legacy_key}"]

    first = _execute(conn, broker)
    assert [command.security_id for command in first.session.submitted] == [
        AAA.security_id]
    key = first.session.submitted[0].client_key

    # A new connection is a process restart at the durable ACKNOWLEDGED boundary.
    restarted = feed_store.connect(pg.sync_dsn)
    try:
        second = _execute(restarted, broker)
        assert second.session.submitted == ()
        assert catchup.resume_state(restarted) == durable_state
        assert journal.latest_plan(restarted).plan_id == prepared.plan.plan_id
    finally:
        restarted.close()

    broker.fill(key)

    # And another restart adopts the observed fill without duplicating the BUY.
    restarted = feed_store.connect(pg.sync_dsn)
    try:
        third = _execute(restarted, broker)
        commands = journal.load_commands(
            restarted, binding.require(restarted).identity,
            plan_id=prepared.plan.plan_id)
        assert third.session.submitted == ()
        assert len(commands) == 1
        assert commands[0].state is CommandState.FILLED
        assert commands[0].filled_quantity == D("35")
    finally:
        restarted.close()

    assert _mutations(broker) == [
        f"submit:{legacy_key}", f"submit:{key}"]
    assert broker.calls.index(f"submit:{legacy_key}") \
        < broker.calls.index(f"submit:{key}")
    held = asyncio.run(broker.observe()).positions_by_security()
    assert held == {AAA.security_id: D("35")}
