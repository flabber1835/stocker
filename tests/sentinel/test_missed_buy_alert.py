"""Positive and adversarial evidence for a BUY-only opening cutoff alert."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime, timezone
from decimal import Decimal
from inspect import getsource
from types import SimpleNamespace

import pytest

from sentinel.automation import missed_buy_alert, outbox, store
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


NOW = datetime(2026, 11, 25, 14, 31, tzinfo=timezone.utc)
EXECUTE = datetime(2026, 11, 25, 14, 30, tzinfo=timezone.utc)
OBSERVED = datetime(2026, 11, 25, 14, 30, 40, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def automation_conn(pg):
    from sentinel import schema
    from sentinel.panel import operational_schema

    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    connection.commit()
    schema.ensure_schema(connection)
    feed_store.migrate_schema(connection)
    operational_schema.install(connection)
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Evidence:
    def __init__(self):
        self.cycle = SimpleNamespace(
            cycle_id="cycle-1", state=SimpleNamespace(value="RECONCILING"),
            historical_state_only=False, attempt_count=2, plan_id="plan-1",
            plan_fingerprint=FINGERPRINT, decision_session=date(2026, 11, 24),
            effective_session=date(2026, 11, 25), deployment_id="paper-1",
            broker="alpaca", broker_account_id="account-1", takeover_epoch=1,
            control_generation=3, config_sha256="config-1", execute_at=EXECUTE,
            execution_open_at=EXECUTE)
        self.control = SimpleNamespace(
            generation=3, config_sha256="config-1",
            binding=SimpleNamespace(deployment_id="paper-1", broker="alpaca",
                broker_account_id="account-1", takeover_epoch=1))
        self.plan = SimpleNamespace(
            plan_id="plan-1", fingerprint=lambda: FINGERPRINT,
            decision_session=date(2026, 11, 24),
            effective_session=date(2026, 11, 25), deployment_id="paper-1",
            broker="alpaca", broker_account_id="account-1", takeover_epoch=1,
            target_basket={}, target_exposure=Decimal("0.55"),
            account_nav=Decimal("1000"), opening_intents=())
        self.projection = SimpleNamespace(
            plan_fingerprint=FINGERPRINT,
            through_session=date(2026, 11, 25))
        self.legs = [
            SimpleNamespace(security_id="sell", action="SELL",
                            change_quantity=Decimal("-5")),
            SimpleNamespace(security_id="buy-planned", action="BUY",
                            change_quantity=None),
            SimpleNamespace(security_id="buy-filled", action="BUY",
                            change_quantity=None),
            SimpleNamespace(security_id="buy-unplanned", action="BUY",
                            change_quantity=None),
        ]
        self.sale = SimpleNamespace(
            client_key="sale-key", security_id="sell",
            side=SimpleNamespace(value="SELL"),
            state=SimpleNamespace(value="FILLED"),
            quantity=Decimal("5"), notional=None,
            filled_quantity=Decimal("5"), broker_order_id="native-sale")
        self.buy = SimpleNamespace(
            client_key="planned-key", security_id="buy-planned",
            side=SimpleNamespace(value="BUY"),
            state=SimpleNamespace(value="PLANNED"),
            quantity=None, notional=Decimal("100"),
            filled_quantity=Decimal(0), broker_order_id=None)
        self.filled_buy = SimpleNamespace(
            client_key="filled-buy-key", security_id="buy-filled",
            side=SimpleNamespace(value="BUY"),
            state=SimpleNamespace(value="FILLED"),
            quantity=Decimal("2"), notional=None,
            filled_quantity=Decimal("2"), broker_order_id="native-buy")
        self.commands = [self.sale, self.buy, self.filled_buy]
        self.diagnostic = {
            "clean": True, "runtime_state": "RUNNING", "terminal_reason": None,
            "unresolved": [], "foreign_orders": [], "foreign_positions": [],
            "restricted_securities": {}, "observation_id": 1,
            "expected": {}, "observed": {},
            "actionable_deltas": [
                {"security_id": "buy-planned", "side": "BUY",
                 "remaining": "0", "remaining_notional": "100"},
                {"security_id": "buy-unplanned", "side": "BUY",
                 "remaining": "0", "remaining_notional": "150"},
            ],
        }
        # A known prior-plan fill may remain in the broker's order history.
        native = [
            {"client_key": "sale-key", "security_id": "sell", "state": "FILLED"},
            {"client_key": "prior-key", "security_id": "buy-unplanned",
             "state": "FILLED"},
        ]
        self.payloads = {
            seq: {"completeness": "COMPLETE", "broker": "alpaca",
                  "account_id": "account-1", "positions": [],
                  "orders": [dict(order) for order in native],
                  "exact_evidence": []}
            for seq in (1, 2)
        }
        self.known = {
            "sale-key": ("plan-1", "sell"),
            "planned-key": ("plan-1", "buy-planned"),
            "filled-buy-key": ("plan-1", "buy-filled"),
            "prior-key": ("prior-plan", "buy-unplanned"),
        }
        self.active = [("planned-key", "PLANNED")]
        self.events = [
            (None, "PLANNED", Decimal(0), "created", EXECUTE.replace(second=10)),
            ("PLANNED", "SEND_PENDING", Decimal(0), "checkpoint",
             EXECUTE.replace(second=11)),
            ("SEND_PENDING", "PLANNED", Decimal(0),
             "PRE_TRANSPORT_CHECKPOINT_RESTORED: broker was not called",
             EXECUTE.replace(second=12)),
        ]

    def execute(self, sql, params=None):
        if sql.startswith("SELECT created_at FROM sentinel_execution_plans"):
            return Result([(EXECUTE.replace(minute=29),)])
        if sql.startswith("SELECT clock_timestamp()"):
            return Result([(NOW,)])
        if sql.startswith("SELECT from_state,to_state,filled_quantity"):
            return Result(self.events)
        if sql.startswith("SELECT client_key,state FROM sentinel_commands"):
            return Result(self.active)
        if sql.startswith("SELECT observed_at,runtime_state,completeness"):
            return Result([(OBSERVED, "RUNNING", "COMPLETE")])
        if sql.startswith("SELECT seq,observed_at FROM sentinel_observations"):
            return Result([(2, OBSERVED)])
        if sql.startswith("SELECT client_key,plan_id,deployment_id"):
            return Result([
                (key, self.known[key][0], "paper-1", "alpaca", "account-1",
                 1, self.known[key][1])
                for key in params[0] if key in self.known])
        raise AssertionError(f"unexpected proof read: {sql}")


@pytest.fixture
def evidence(monkeypatch):
    from sentinel import dual_plan_authority, paper_plan_preview
    from sentinel.execution import journal, target_reprojection

    value = Evidence()
    monkeypatch.setattr(journal, "load_plan", lambda _c, _id: value.plan)
    monkeypatch.setattr(journal, "load_commands",
                        lambda _c, _identity, *, plan_id: tuple(value.commands))
    monkeypatch.setattr(journal, "load_observation_payload",
                        lambda _c, seq: value.payloads[seq])
    monkeypatch.setattr(target_reprojection, "load_projection",
                        lambda _c, *, plan_id: value.projection)
    monkeypatch.setattr(target_reprojection, "assert_projection",
                        lambda _c, *, plan, projection, through_session: None)
    monkeypatch.setattr(dual_plan_authority, "load_authority",
                        lambda _c, *, plan_id: {"saved": True})
    monkeypatch.setattr(paper_plan_preview, "project_original_intent",
                        lambda _plan, _authority: SimpleNamespace(legs=value.legs))
    return value


def prove(value):
    return missed_buy_alert.prove(
        value, value.cycle, value.control,
        diagnostic=value.diagnostic, clean_id="1")


def test_no_command_buy_and_restored_planned_buy_can_warn(evidence):
    witness = prove(evidence)
    assert witness is not None
    assert witness["remaining_buy_security_ids"] == ["buy-planned", "buy-unplanned"]
    assert witness["unsent_buy_keys"] == ["planned-key"]
    assert witness["filled_sell_keys"] == ["sale-key"]
    detail = {"failure_code": "MAX_EXECUTION_LATENESS_EXCEEDED",
              "last_clean_reconciliation_id": "1",
              "diagnostic": evidence.diagnostic,
              "missed_window_buy_only": witness}
    assert outbox._cycle_event_alert(
        (9, "cycle-1", "SUPERSEDED", 3, 7, detail))["severity"] == "WARN"
    detail["missed_window_buy_only"]["latest_observation_id"] = 0
    assert outbox._cycle_event_alert(
        (9, "cycle-1", "SUPERSEDED", 3, 7, detail))["severity"] == "CRITICAL"


@pytest.mark.parametrize("fault", [
    "unfinished-sale", "sell-delta", "unknown", "unrestored-checkpoint",
    "saved-same-key", "latest-same-key", "exact-same-key",
    "current-plan-unplanned", "malformed-fractional", "nonzero-fractional",
    "prior-rejected", "foreign-order",
])
def test_uncertain_buy_only_cutoff_stays_critical(evidence, fault):
    if fault == "unfinished-sale":
        evidence.sale.state = SimpleNamespace(value="CANCELLED")
    elif fault == "sell-delta":
        evidence.diagnostic["actionable_deltas"][1]["side"] = "SELL"
    elif fault == "unknown":
        evidence.active.append(("unresolved-key", "UNKNOWN"))
    elif fault == "unrestored-checkpoint":
        evidence.events.append(("PLANNED", "SEND_PENDING", Decimal(0), "pending", NOW))
    elif fault in {"saved-same-key", "latest-same-key"}:
        seq = 1 if fault == "saved-same-key" else 2
        evidence.payloads[seq]["orders"].append(
            {"client_key": "planned-key", "security_id": "buy-planned",
             "state": "FILLED"})
    elif fault == "exact-same-key":
        evidence.payloads[1]["exact_evidence"].append({
            "client_key": "planned-key",
            "order": {"client_key": "planned-key", "security_id": "buy-planned",
                      "state": "FILLED"}})
    elif fault == "current-plan-unplanned":
        evidence.known["other-current"] = ("plan-1", "buy-unplanned")
        evidence.payloads[2]["orders"].append({
            "client_key": "other-current", "security_id": "buy-unplanned",
            "state": "FILLED"})
    elif fault == "malformed-fractional":
        evidence.diagnostic["actionable_deltas"][0]["remaining"] = "bad"
    elif fault == "nonzero-fractional":
        evidence.diagnostic["actionable_deltas"][0]["remaining"] = "1"
    elif fault == "prior-rejected":
        evidence.payloads[1]["orders"][1]["state"] = "REJECTED"
    elif fault == "foreign-order":
        evidence.payloads[2]["orders"].append({
            "client_key": "foreign-key", "security_id": "buy-unplanned",
            "state": "FILLED"})
    assert prove(evidence) is None


def test_removing_native_order_guard_is_caught(evidence, monkeypatch):
    evidence.payloads[1]["orders"].append({
        "client_key": "planned-key", "security_id": "buy-planned",
        "state": "FILLED"})
    assert prove(evidence) is None
    source = getsource(missed_buy_alert._observation)
    guard = 'or order["client_key"] in planned_keys'
    assert source.count(guard) == 1
    namespace = vars(missed_buy_alert).copy()
    exec(compile(source.replace(guard, "or False"),
                 "<removed-native-order-guard>", "exec"), namespace)
    monkeypatch.setattr(missed_buy_alert, "_observation", namespace["_observation"])
    with pytest.raises(AssertionError):
        assert prove(evidence) is None


def test_optional_control_read_error_keeps_connection_usable(conn, monkeypatch):
    def failed_control(connection):
        connection.execute("SELECT 1/0")

    monkeypatch.setattr(store, "load_control", failed_control)
    assert store._missed_buy_alert_witness(
        conn, SimpleNamespace(), diagnostic={}, clean_id="1") is None
    assert conn.execute("SELECT 1").fetchone() == (1,)
    source = getsource(store._missed_buy_alert_witness)
    guard = "with conn.transaction():"
    assert source.count(guard) == 1
    namespace = {**vars(store), "nullcontext": nullcontext}
    exec(compile(source.replace(guard, "with nullcontext():"),
                 "<removed-buy-alert-savepoint>", "exec"), namespace)
    assert namespace["_missed_buy_alert_witness"](
        conn, SimpleNamespace(), diagnostic={}, clean_id="1") is None
    with pytest.raises(Exception):
        conn.execute("SELECT 1")
    conn.rollback()


@pytest.mark.parametrize("failure", ["timeout", "soft-refusal"])
def test_optional_proof_timeout_or_refusal_restores_caller_budget(
        conn, monkeypatch, failure):
    original = conn.execute("SHOW statement_timeout").fetchone()[0]
    monkeypatch.setattr(store, "load_control", lambda _conn: SimpleNamespace())

    def read(connection, *_args, **_kwargs):
        if failure == "timeout":
            connection.execute("SELECT pg_sleep(2)")
        return None

    monkeypatch.setattr(missed_buy_alert, "prove", read)
    assert store._missed_buy_alert_witness(
        conn, SimpleNamespace(), diagnostic={}, clean_id="1") is None
    assert conn.execute("SHOW statement_timeout").fetchone()[0] == original
    assert conn.execute("SELECT 1").fetchone() == (1,)


def test_terminal_writer_persists_witness_for_reconstructed_alert(
        automation_conn, monkeypatch):
    from sentinel.automation.model import AutomationConfig, CycleState
    from tests.sentinel.test_automation_store import cycle_spec, enable

    connection = automation_conn
    config = AutomationConfig(publication_delay_seconds=0,
                              execution_delay_seconds=0)
    control = enable(connection, config)
    permit = store.acquire_lease(
        connection, holder_id="buy-alert-writer", lease_seconds=30)
    cycle = store.create_cycle(
        connection, permit=permit, spec=cycle_spec(control, config))
    for state in (CycleState.PREPARING, CycleState.PLAN_READY,
                  CycleState.RECONCILING):
        cycle = store.transition_cycle(
            connection, permit=permit, cycle_id=cycle.cycle_id,
            to_state=state, increment_attempt=state is CycleState.RECONCILING)
    diagnostic = {
        "clean": True, "runtime_state": "RUNNING", "observation_id": 1,
        "terminal_reason": None, "expected": {}, "observed": {},
        "unresolved": [], "foreign_orders": [], "foreign_positions": [],
        "restricted_securities": {},
        "actionable_deltas": [{"security_id": "buy", "side": "BUY",
                               "remaining": "0", "remaining_notional": "100"}],
    }
    witness = {
        "schema": "sentinel.missed-window-buy-only/1",
        "cycle_id": cycle.cycle_id, "plan_id": "plan-1",
        "plan_fingerprint": FINGERPRINT,
        "from_state": "RECONCILING", "attempt_count": 1,
        "observation_id": 1, "latest_observation_id": 1,
        "remaining_buy_security_ids": ["buy"],
        "unsent_buy_keys": [], "filled_sell_keys": [],
        "journal": "RESTORED_PRETRANSPORT_ONLY",
    }
    monkeypatch.setattr(missed_buy_alert, "prove",
                        lambda *_args, **_kwargs: witness)
    retired = store.transition_cycle(
        connection, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.SUPERSEDED,
        last_clean_reconciliation_id="1",
        failure_code="MAX_EXECUTION_LATENESS_EXCEEDED",
        diagnostic=diagnostic)
    assert retired.state is CycleState.SUPERSEDED
    event = connection.execute(
        "SELECT detail FROM sentinel_automation_cycle_events "
        "WHERE cycle_id=%s AND to_state='SUPERSEDED' ORDER BY seq DESC LIMIT 1",
        (cycle.cycle_id,)).fetchone()[0]
    assert event["missed_window_buy_only"] == witness
    outbox._reconstruct_missing_transition_alerts(connection)
    connection.commit()
    alert = connection.execute(
        "SELECT severity,payload FROM sentinel_alert_outbox "
        "WHERE event_type='AUTOMATION_SUPERSEDED'").fetchone()
    assert alert[0] == "WARN"
    assert alert[1]["detail"] == event
