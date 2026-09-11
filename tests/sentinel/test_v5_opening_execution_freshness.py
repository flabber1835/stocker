"""V5 opening-intent freshness at the public paper execution membrane."""
from dataclasses import replace
import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import test_paper_activation as activation
from sentinel import paper
from sentinel.execution import journal, opening_sizing, target_reprojection
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState
from sentinel.feed import calendar
from sentinel.paper import execution as paper_execution
from tests.v5.test_opening import case


# Reuse the production-grade PostgreSQL/simulator paper-activation fixtures.
pg = activation.pg
conn = activation.conn
simulator_is_certified = activation.simulator_is_certified


def _install_unresolved_v5_opening(conn, monkeypatch, *, sale):
    import sentinel.strategy
    bound, pinned = activation._bind(conn), activation._publish(conn)
    state, template = case(sale=sale)
    state.data_version = pinned.version
    config = sentinel.strategy.controller_for_identity(state.strategy_identity)
    monkeypatch.setattr(sentinel.strategy, "production_strategy",
                        lambda: (config, dict(state.strategy_identity)))
    activation._persist_state(conn, state)
    pending = replace(activation._plan(
        state, pinned, bound, basket=template.target_basket),
        opening_intents=template.opening_intents)
    plan = replace(pending, plan_id=f"sentinel-{pending.fingerprint()}")
    return bound, journal.adopt_current_plan(conn, plan)


@pytest.mark.parametrize("sale", [False, True])
def test_public_late_opening_suppresses_buy_and_preserves_pending_sale(
        conn, monkeypatch, sale):
    bound, plan = _install_unresolved_v5_opening(conn, monkeypatch, sale=sale)
    activation._ready(monkeypatch)
    broker = activation._broker()
    if sale:
        instrument = BrokerInstrument("SEC-X", "X", "sim-asset-SEC-X")
        broker.seed_position(instrument, "10")
        journal.save_command(conn, Command(
            identity=CommandIdentity(deployment=bound.identity,
                plan_id="historical-plan", security_id=instrument.security_id),
            instrument=instrument, side=Side.BUY, quantity=D(10),
            state=CommandState.FILLED, filled_quantity=D(10),
            filled_average_price=D(100)))
    noon = dt.datetime(
        activation.EFFECTIVE.year,
        activation.EFFECTIVE.month,
        activation.EFFECTIVE.day,
        12, 0,
        tzinfo=ZoneInfo(calendar.EXCHANGE_TZ))

    async def forbidden_opening_read(*args, **kwargs):
        pytest.fail("expired opening attempted to fetch opening prices")
    monkeypatch.setattr(paper_execution, "_opening_prices_or_retry",
                        forbidden_opening_read)
    activation._execute(conn, broker, today=noon)

    projected = target_reprojection.load_projection(conn, plan_id=plan.plan_id)
    assert projected.opening_sizing["mode"] == opening_sizing.UNAVAILABLE_MODE
    assert projected.target_basket["SEC-AAA"] == 0
    assert "expired" in projected.opening_sizing["reason"]
    commands = journal.load_commands(conn, bound.identity, plan_id=plan.plan_id)
    assert [(c.security_id, c.side, c.quantity) for c in commands] == (
        [("SEC-X", Side.SELL, D(10))] if sale else [])


def test_late_restart_with_durable_opening_projection_remains_permitted(monkeypatch):
    plan = SimpleNamespace(effective_session=activation.EFFECTIVE)
    deployment = object()
    seen = []

    def already_resolved(conn, *, plan, deployment):
        seen.append((conn, plan, deployment))
        return False

    monkeypatch.setattr(
        opening_sizing, "requires_initial_projection", already_resolved)
    opened, _closed = calendar.session_window(plan.effective_session)

    paper_execution._opening_resolution_freshness_or_refuse(
        object(), plan=plan, deployment=deployment,
        now_et=opened + dt.timedelta(hours=2))

    assert len(seen) == 1
    assert seen[0][1:] == (plan, deployment)
