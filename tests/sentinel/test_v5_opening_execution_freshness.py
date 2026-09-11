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
from sentinel.execution.plan import OpeningIntent
from sentinel.feed import calendar
from sentinel.paper import execution as paper_execution


# Reuse the production-grade PostgreSQL/simulator paper-activation fixtures.
pg = activation.pg
conn = activation.conn
simulator_is_certified = activation.simulator_is_certified


def _install_unresolved_v5_opening(conn):
    _bound, _pinned, _state, current = activation._install_current_authorities(conn)
    basket = dict(current.target_basket)
    basket[activation.AAA.security_id] = D(0)
    pending = replace(
        current,
        plan_id="pending",
        target_basket=basket,
        opening_intents=(
            OpeningIntent(
                security_id=activation.AAA.security_id,
                slot_id=0,
                intended_dollars=D("500")),
        ))
    plan = replace(pending, plan_id=f"sentinel-{pending.fingerprint()}")
    return journal.adopt_current_plan(conn, plan)


def test_public_paper_execution_refuses_unresolved_v5_opening_at_noon_before_broker_io(
        conn, monkeypatch):
    plan = _install_unresolved_v5_opening(conn)
    activation._ready(monkeypatch)
    broker = activation._broker()
    noon = dt.datetime(
        activation.EFFECTIVE.year,
        activation.EFFECTIVE.month,
        activation.EFFECTIVE.day,
        12, 0,
        tzinfo=ZoneInfo(calendar.EXCHANGE_TZ))

    with pytest.raises(
            paper.PaperActivationRefused,
            match="unresolved V5 opening intent expired"):
        activation._execute(
            conn, broker,
            install_preopen_authority=False,
            today=noon)

    assert broker.calls == []
    assert activation._mutations(broker) == []
    assert target_reprojection.load_projection(
        conn, plan_id=plan.plan_id) is None


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
