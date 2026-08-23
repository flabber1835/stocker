"""Issue #211 — financial green is an earned, immutable session fact."""
from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import trial, trial_close, trial_fills
from sentinel.automation.model import CycleState
from sentinel.execution import broker_cash, target_reprojection
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerCloseValuation,
    BrokerFillIntervalEvidence,
    BrokerObservation,
    Completeness,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import RuntimeState


NOW = datetime(2026, 8, 20, 21, 5, tzinfo=timezone.utc)


class JsonStateConnection:
    """The exact two-statement namespace store used by trial evidence."""

    def __init__(self):
        self.rows = {}
        self.cash_rows = []
        self.cash_rows_by_session = {}
        self.automation_cycles = []
        self.result = None
        self.pending = None
        self.last_statement = None
        self.last_params = None
        self.statements = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split()).lower()
        self.last_statement = normalized
        self.last_params = params
        self.statements.append((normalized, params))
        if normalized.startswith(
                "select cycle_id,effective_session,state from "
                "sentinel_automation_cycles"):
            self.result = list(self.automation_cycles)
            return
        if normalized.startswith(
                "select flow_id,amount,detail,recorded_at from sentinel_cash_flows"):
            self.result = list(
                self.cash_rows_by_session.get(params[0], self.cash_rows))
            return
        if normalized.startswith("select session,state from sentinel_processed_sessions"):
            if "cursor_name like" in normalized:
                prefix = str(params[0]).removesuffix("%")
                self.result = [
                    row for name, row in sorted(self.rows.items())
                    if (name.startswith(prefix)
                        and ("session <" not in normalized
                             or row[0] < params[1]))]
            else:
                self.result = self.rows.get(params[0])
            return
        if normalized.startswith("insert into sentinel_processed_sessions"):
            name, session, raw = params
            self.pending = (name, date.fromisoformat(str(session)), json.loads(raw))
            return
        raise AssertionError(f"unexpected trial SQL: {statement}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def commit(self):
        if self.pending is not None:
            name, session, state = self.pending
            self.rows[name] = (session, state)
            self.pending = None


class VerificationConnection:
    def __init__(self, plan_id, *, command_rows=(), fill_rows=()):
        self.plan_id = plan_id
        self.command_rows = list(command_rows)
        self.fill_rows = list(fill_rows)
        self.result = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=()):
        normalized = " ".join(str(statement).split()).lower()
        if normalized.startswith(
                "select plan_id from sentinel_execution_plans"):
            self.result = [(self.plan_id,)]
        elif normalized.startswith("select client_key,security_id"):
            self.result = self.command_rows
        elif normalized.startswith("select broker_order_id,fill_key"):
            self.result = self.fill_rows
        else:
            raise AssertionError(f"unexpected verification SQL: {statement}")

    def fetchall(self):
        return self.result


def _clean_account_evidence():
    identity = BrokerAccountIdentity(broker="alpaca", account_id="PA-1")
    deployment = DeploymentIdentity(
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=4)
    observation = BrokerObservation(
        observed_at=NOW, started_at=NOW,
        completeness=Completeness.COMPLETE)
    reconciliation = ReconciliationResult(
        runtime_state=RuntimeState.RUNNING, observation=observation,
        expected={"SEC-A": Decimal("20")},
        corporate_actions={"SEC-A": Decimal("2")}, observation_id=17)
    snapshot = BrokerAccountSnapshot(
        identity=identity, equity=Decimal("100123.45"),
        cash=Decimal("20123.45"), buying_power=Decimal("20123.45"),
        multiplier=Decimal("1"), status="ACTIVE")
    activity = SimpleNamespace(
        broker="alpaca", account_id="PA-1", processed_through=NOW,
        last_activity_id="activity-9", last_event_id="event-9",
        balance_total=Decimal("125.00"),
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    return deployment, reconciliation, snapshot, activity


def _account_plan_projection(conn, *, target=Decimal("10"),
                             multiplier=Decimal("2")):
    plan = ExecutionPlan(
        plan_id="trial-account-plan", decision_session=date(2026, 8, 19),
        effective_session=date(2026, 8, 20),
        target_exposure=Decimal(1), target_basket={"SEC-A": target})
    projection = target_reprojection.project_target(
        plan, through_session=plan.effective_session,
        action_multipliers={"SEC-A": multiplier})
    conn.rows[
        f"{target_reprojection.CURSOR_PREFIX}{plan.plan_id}"] = (
            projection.through_session, projection.payload())
    return plan, projection


def test_account_evidence_is_observation_bound_and_immutable():
    conn = JsonStateConnection()
    deployment, reconciliation, snapshot, activity = _clean_account_evidence()
    plan, projection = _account_plan_projection(conn)

    first = trial.record_account_evidence(
        conn, session=date(2026, 8, 20), observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=reconciliation, activity_state=activity,
        plan=plan, target_projection=projection,
        observation_post_projection_actions={})
    again = trial.record_account_evidence(
        conn, session=date(2026, 8, 20), observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=reconciliation, activity_state=activity,
        plan=plan, target_projection=projection,
        observation_post_projection_actions={})

    assert first == again
    assert first["account"] == {
        "equity": "100123.45", "cash": "20123.45", "status": "ACTIVE",
        "trading_blocked": False, "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    assert first["reconciliation"]["expected"] == {"SEC-A": "20"}
    assert first["reconciliation"]["corporate_actions"] == {"SEC-A": "2"}
    assert first["reconciliation"]["plan_target"] == {"SEC-A": "10"}
    assert first["reconciliation"]["target_projection"] == \
        projection.payload()
    assert first["reconciliation"]["target"] == {"SEC-A": "20"}
    assert first["reconciliation"]["target_corporate_actions"] == {
        "SEC-A": "2"}
    assert first["reconciliation"]["observation_target"] == {
        "SEC-A": "20"}
    assert first["reconciliation"][
        "observation_target_corporate_actions"] == {}
    assert first["cash_activity"] == {
        "processed_through": NOW.isoformat(),
        "last_activity_id": "activity-9",
        "last_event_id": "event-9",
        "activity_identity_scheme": broker_cash.ACTIVITY_IDENTITY_SCHEME,
        "balance_total": "125.00",
    }
    changed = BrokerAccountSnapshot(
        **{**snapshot.__dict__, "equity": Decimal("100123.46")})
    with pytest.raises(trial.TrialEvidenceRefused, match="immutable"):
        trial.record_account_evidence(
            conn, session=date(2026, 8, 20), observation_id=17,
            observation_started_at=NOW, observed_at=NOW,
            snapshot=changed, deployment=deployment,
            reconciliation=reconciliation, activity_state=activity,
            plan=plan, target_projection=projection,
            observation_post_projection_actions={})


def test_account_evidence_fingerprint_corruption_is_not_read_as_truth():
    conn = JsonStateConnection()
    deployment, reconciliation, snapshot, activity = _clean_account_evidence()
    plan, projection = _account_plan_projection(conn)
    trial.record_account_evidence(
        conn, session=date(2026, 8, 20), observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=reconciliation, activity_state=activity,
        plan=plan, target_projection=projection,
        observation_post_projection_actions={})
    conn.rows[f"{trial.ACCOUNT_PREFIX}17"][1]["account"]["cash"] = "999999"

    with pytest.raises(trial.TrialEvidenceRefused, match="fingerprint"):
        trial.load_account_evidence(conn, 17)


def test_account_evidence_uses_projected_pending_open_cancellation():
    conn = JsonStateConnection()
    deployment, reconciliation, snapshot, activity = _clean_account_evidence()
    plan = ExecutionPlan(
        plan_id="trial-cancelled-open",
        decision_session=date(2026, 8, 19),
        effective_session=date(2026, 8, 20),
        target_exposure=Decimal(1),
        target_basket={"SEC-A": Decimal("3")})
    projection = target_reprojection.project_target(
        plan, through_session=plan.effective_session,
        action_multipliers={"SEC-A": Decimal("0.1")},
        action_evidence=({
            "security_id": "SEC-A", "session": "2026-08-20",
            "action": "split", "value": "0.1",
            "canonical_multiplier": "0.1",
            "source_row_id": "pending-open-split",
        },),
        canonical_target_shares={"SEC-A": Decimal("3")},
        pending_open_shares={"SEC-A": (Decimal("3"),)},
        minimum_quantity_increment=Decimal("0.000000001"))
    conn.rows[
        f"{target_reprojection.CURSOR_PREFIX}{plan.plan_id}"] = (
            projection.through_session, projection.payload())
    cancelled_reconciliation = ReconciliationResult(
        runtime_state=RuntimeState.RUNNING,
        observation=reconciliation.observation, expected={},
        corporate_actions={"SEC-A": Decimal("0.1")}, observation_id=17)

    evidence = trial.record_account_evidence(
        conn, session=plan.effective_session, observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=cancelled_reconciliation, activity_state=activity,
        plan=plan, target_projection=projection,
        observation_post_projection_actions={})

    retained = evidence["reconciliation"]
    assert retained["plan_target"] == {"SEC-A": "3"}
    assert retained["target"] == {"SEC-A": "0"}
    assert retained["observation_target"] == {"SEC-A": "0"}
    assert retained["target_projection"]["cancelled_pending_opens"] == {
        "SEC-A": ["3"]}
    assert retained["target_projection"]["projection_fingerprint"] == \
        projection.fingerprint()


def test_plan_cash_baseline_v3_retains_certified_native_activity_identity():
    conn = JsonStateConnection()
    activity = broker_cash.CashActivityState(
        broker="alpaca", account_id="PA-1", processed_through=NOW,
        last_activity_id="cash-native-9", last_event_id="event-19",
        balance_total=Decimal("12.50"),
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)

    baseline = broker_cash.record_plan_baseline(
        conn, plan_id="plan-cash-v3", decision_session=date(2026, 8, 19),
        activity_state=activity)
    conn.commit()
    loaded = broker_cash.load_plan_baseline(conn, plan_id="plan-cash-v3")

    assert loaded == baseline
    assert loaded.last_activity_id == "cash-native-9"
    assert loaded.activity_identity_scheme == broker_cash.ACTIVITY_IDENTITY_SCHEME
    assert loaded.activity_identity_authoritative is True
    assert loaded.close_cash_finality_authoritative is False
    _session, stored = next(iter(conn.rows.values()))
    assert stored["kind"] == "broker-cash-plan/v3"
    assert stored["last_activity_id"] == "cash-native-9"
    assert stored["activity_identity_scheme"] == (
        broker_cash.ACTIVITY_IDENTITY_SCHEME)


def test_global_scheme_string_cannot_retroactively_promote_cash_finality(
        monkeypatch):
    baseline = broker_cash.PlanCashBaseline(
        plan_id="plan-no-retroactive-finality", broker="alpaca",
        account_id="PA-1", decision_session=date(2026, 8, 19),
        processed_through=NOW, balance_total=Decimal("12.50"),
        last_activity_id="cash-native-9",
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)

    monkeypatch.setattr(
        broker_cash, "CLOSE_FINALITY_IDENTITY_SCHEMES",
        frozenset({broker_cash.ACTIVITY_IDENTITY_SCHEME}))

    assert baseline.close_cash_finality_authoritative is False


def test_retained_verified_cash_finality_is_revalidated_and_revocable(
        monkeypatch):
    baseline = broker_cash.PlanCashBaseline(
        plan_id="plan-finality-reference", broker="alpaca",
        account_id="PA-1", decision_session=date(2026, 8, 19),
        processed_through=NOW, balance_total=Decimal("12.50"),
        last_activity_id="cash-native-9",
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: baseline)
    monkeypatch.setattr(
        broker_cash.PlanCashBaseline,
        "close_cash_finality_authoritative", property(lambda _self: True))
    verification = {
        "cycle": {"state": "SUCCEEDED"},
        "verdict": "VERIFIED",
        "plan": {
            "plan_id": baseline.plan_id,
            "decision_session": baseline.decision_session.isoformat(),
            "deployment": {
                "broker": baseline.broker,
                "broker_account_id": baseline.account_id,
            },
        },
        "cash_baseline_evidence": trial._cash_baseline_reference(  # noqa: SLF001
            baseline),
    }

    trial._validate_cash_finality_reference(  # noqa: SLF001
        object(), verification)

    monkeypatch.setattr(
        broker_cash.PlanCashBaseline,
        "close_cash_finality_authoritative", property(lambda _self: False))
    with pytest.raises(
            trial.TrialEvidenceRefused, match="finality authority changed"):
        trial._validate_cash_finality_reference(  # noqa: SLF001
            object(), verification)


def test_plan_cash_baseline_refuses_timestamp_paged_activity_identity():
    activity = broker_cash.CashActivityState(
        broker="alpaca", account_id="PA-1", processed_through=NOW,
        last_activity_id="cash-native-9", last_event_id=None,
        balance_total=Decimal("12.50"), activity_identity_scheme=None)

    with pytest.raises(
            broker_cash.BrokerCashAuthorityRefused,
            match="certified append-only Activity SSE"):
        broker_cash.record_plan_baseline(
            JsonStateConnection(), plan_id="plan-cash-rest",
            decision_session=date(2026, 8, 19), activity_state=activity)

    wrong_broker = broker_cash.PlanCashBaseline(
        plan_id="plan-cash-other", broker="other", account_id="OTHER-1",
        decision_session=date(2026, 8, 19), processed_through=NOW,
        balance_total=Decimal("12.50"), last_activity_id="cash-native-9",
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    assert wrong_broker.activity_identity_authoritative is False


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_verification_cannot_enter_the_corrected_v3_chain(version):
    session = date(2026, 8, 20)
    legacy = {
        "kind": f"sentinel-trial-verification/v{version}",
        "session": session.isoformat(),
        "verdict": "VERIFIED",
    }
    legacy["evidence_sha256"] = trial._sha(legacy)  # noqa: SLF001

    assert trial.VERIFICATION_PREFIX == "trial-verification:v3:"
    with pytest.raises(trial.TrialEvidenceRefused, match="fingerprint"):
        trial._validate_verification(session, legacy)  # noqa: SLF001


@pytest.mark.parametrize(
    ("state", "expected"),
    ((CycleState.MISSED_STATE_ONLY, "CYCLE_MISSED_STATE_ONLY"),
     (CycleState.SUPERSEDED, "CYCLE_SUPERSEDED"),
     (CycleState.BLOCKED, "CYCLE_BLOCKED")),
)
def test_safe_terminal_cycles_earn_durable_not_verified_records(
        monkeypatch, state, expected):
    from sentinel.automation import store

    cycle = SimpleNamespace(
        cycle_id="cycle-211", state=state,
        decision_session=date(2026, 8, 19),
        effective_session=date(2026, 8, 20),
        failure_code="TEST_FAILURE", failure_detail="financial gap")
    monkeypatch.setattr(store, "load_cycle", lambda _conn, _cycle_id: cycle)
    conn = JsonStateConnection()

    result = trial.record_cycle_verification(
        conn, cycle_id=cycle.cycle_id, now=NOW)

    assert result["verdict"] == "NOT_VERIFIED"
    assert expected in result["reason_codes"]
    assert "TEST_FAILURE" in result["reason_codes"]
    assert conn.rows[f"{trial.VERIFICATION_PREFIX}2026-08-20"][1] == result


def _terminal_cycle(*, state="SUCCEEDED", epoch=4):
    return SimpleNamespace(
        cycle_id="cycle-terminal", state=state,
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=epoch,
        effective_session=date(2026, 8, 20))


def _terminal_row(*, version, cycle_id="cycle-terminal",
                  state="SUCCEEDED"):
    session = date(2026, 8, 19)
    result = {
        "kind": f"sentinel-trial-verification/v{version}",
        "session": session.isoformat(), "verdict": "VERIFIED",
        "cycle": {"cycle_id": cycle_id, "state": state},
    }
    result["evidence_sha256"] = trial._sha(result)  # noqa: SLF001
    return session, result


def test_terminal_verification_debt_catches_callback_crash_and_nonterminal():
    conn = JsonStateConnection()
    conn.automation_cycles = [
        ("cycle-terminal", date(2026, 8, 19), "SUCCEEDED"),
        ("cycle-pending", date(2026, 8, 19), "RETRY_WAIT"),
    ]

    debt = trial._terminal_verification_debt(  # noqa: SLF001
        conn, _terminal_cycle())

    assert debt == (
        {"cycle_id": "cycle-terminal", "session": "2026-08-19",
         "state": "SUCCEEDED", "reason": "TERMINAL_V3_MISSING"},
        {"cycle_id": "cycle-pending", "session": "2026-08-19",
         "state": "RETRY_WAIT", "reason": "OLDER_CYCLE_NONTERMINAL"},
    )
    debt_query, debt_params = next(
        item for item in conn.statements
        if item[0].startswith(
            "select cycle_id,effective_session,state from "))
    assert "takeover_epoch=%s" not in debt_query
    assert debt_params == (
        "trial-appliance", "alpaca", "PA-1", date(2026, 8, 20))


@pytest.mark.parametrize("version", [1, 2, 3])
def test_exact_terminal_verdict_satisfies_callback_debt_across_upgrade(version):
    conn = JsonStateConnection()
    conn.automation_cycles = [
        ("cycle-terminal", date(2026, 8, 19), "SUCCEEDED")]
    session, result = _terminal_row(version=version)
    conn.rows[f"trial-verification:v{version}:{session.isoformat()}"] = (
        session, result)

    assert trial._terminal_verification_debt(  # noqa: SLF001
        conn, _terminal_cycle()) == ()


def test_terminal_verdict_identity_mismatch_is_integrity_refusal():
    conn = JsonStateConnection()
    conn.automation_cycles = [
        ("cycle-terminal", date(2026, 8, 19), "SUCCEEDED")]
    session, result = _terminal_row(version=3, cycle_id="other-cycle")
    conn.rows[f"{trial.VERIFICATION_PREFIX}{session.isoformat()}"] = (
        session, result)

    with pytest.raises(
            trial.TrialEvidenceRefused,
            match="disagrees with its v3 verification"):
        trial._terminal_verification_debt(  # noqa: SLF001
            conn, _terminal_cycle())


@pytest.mark.parametrize("pending_reason", [
    "CLOSE_NAV_EVIDENCE_MISSING",
    "CLOSE_NAV_EVIDENCE_FUTURE",
    "CLOSE_FILL_INTERVAL_EVIDENCE_MISSING",
    "CLOSE_FILL_INTERVAL_EVIDENCE_FUTURE",
    "CLOSE_CASH_FINALITY_UNAVAILABLE",
])
def test_succeeded_cycle_cannot_freeze_v3_with_pending_source_evidence(
        monkeypatch, pending_reason):
    from sentinel.automation import store

    cycle = SimpleNamespace(
        cycle_id="cycle-close-pending", state=CycleState.SUCCEEDED,
        effective_session=date(2026, 8, 20))
    monkeypatch.setattr(store, "load_cycle", lambda *_: cycle)
    monkeypatch.setattr(
        trial, "build_cycle_verification",
        lambda *_args, **_kwargs: {
            "kind": trial.VERIFICATION_KIND,
            "session": cycle.effective_session.isoformat(),
            "cycle": {"cycle_id": cycle.cycle_id, "state": "SUCCEEDED"},
            "verdict": "NOT_VERIFIED",
            "reason_codes": [pending_reason],
        })
    conn = JsonStateConnection()

    with pytest.raises(trial.TrialEvidenceRefused, match="cannot freeze"):
        trial.record_cycle_verification(
            conn, cycle_id=cycle.cycle_id, now=NOW)

    assert conn.rows == {}


@pytest.mark.parametrize(
    "economic_reason",
    ["CLOSE_BOOK_INTERVAL_UNPROVEN", "CLOSE_CASH_UNPROVEN"],
)
def test_succeeded_cycle_economic_mismatch_freezes_immutable_red(
        monkeypatch, economic_reason):
    from sentinel.automation import store

    cycle = SimpleNamespace(
        cycle_id="cycle-economic-red", state=CycleState.SUCCEEDED,
        effective_session=date(2026, 8, 20))
    monkeypatch.setattr(store, "load_cycle", lambda *_: cycle)
    result = {
        "kind": trial.VERIFICATION_KIND,
        "session": cycle.effective_session.isoformat(),
        "cycle": {"cycle_id": cycle.cycle_id, "state": "SUCCEEDED"},
        "verdict": "NOT_VERIFIED",
        "reason_codes": [economic_reason],
        "cash": {"rows": [], "external": "0", "internal": "0"},
    }
    monkeypatch.setattr(
        trial, "build_cycle_verification", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(trial, "_validate_close_reference", lambda *_: None)
    monkeypatch.setattr(trial, "_validate_fill_reference", lambda *_: None)
    conn = JsonStateConnection()

    recorded = trial.record_cycle_verification(
        conn, cycle_id=cycle.cycle_id, now=NOW)

    assert recorded["verdict"] == "NOT_VERIFIED"
    assert recorded["reason_codes"] == [economic_reason]
    assert conn.rows[f"{trial.VERIFICATION_PREFIX}2026-08-20"][1] == recorded


def test_retained_success_revalidates_its_close_source(monkeypatch):
    from sentinel.automation import store

    session = date(2026, 8, 20)
    cycle = SimpleNamespace(
        cycle_id="cycle-retained-close", state=CycleState.SUCCEEDED,
        effective_session=session)
    monkeypatch.setattr(store, "load_cycle", lambda *_: cycle)
    monkeypatch.setattr(
        trial, "_validate_cash_finality_reference", lambda *_: None)
    close = {
        "requested_session": session.isoformat(),
        "deployment": {
            "deployment_id": "trial-appliance", "broker": "alpaca",
            "broker_account_id": "PA-1", "takeover_epoch": 4,
        },
        "evidence_sha256": "a" * 64,
    }
    fill_interval = {
        "plan_id": "plan-retained-close",
        "deployment": dict(close["deployment"]),
        "evidence_sha256": "f" * 64,
    }
    stored = {
        "kind": trial.VERIFICATION_KIND,
        "session": session.isoformat(),
        "cycle": {"cycle_id": cycle.cycle_id, "state": "SUCCEEDED"},
        "close_nav_evidence": close,
        "fill_interval_evidence": fill_interval,
        "cash": {"rows": [], "external": "0", "internal": "0"},
        "verdict": "VERIFIED",
        "reason_codes": [],
    }
    stored["evidence_sha256"] = trial._sha(stored)  # noqa: SLF001
    conn = JsonStateConnection()
    conn.rows[f"{trial.VERIFICATION_PREFIX}{session.isoformat()}"] = (
        session, stored)

    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence", lambda *_args, **_kwargs: None)
    with pytest.raises(trial.TrialEvidenceRefused, match="source row is missing"):
        trial.record_cycle_verification(conn, cycle_id=cycle.cycle_id)

    changed = {**close, "evidence_sha256": "b" * 64}
    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence",
        lambda *_args, **_kwargs: changed)
    with pytest.raises(trial.TrialEvidenceRefused, match="changed after"):
        trial.record_cycle_verification(conn, cycle_id=cycle.cycle_id)

    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence",
        lambda *_args, **_kwargs: close)
    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: None)
    with pytest.raises(trial.TrialEvidenceRefused, match="fill-interval source row is missing"):
        trial.record_cycle_verification(conn, cycle_id=cycle.cycle_id)

    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: {
            **fill_interval, "evidence_sha256": "e" * 64})
    with pytest.raises(trial.TrialEvidenceRefused, match="fill-interval source row changed"):
        trial.record_cycle_verification(conn, cycle_id=cycle.cycle_id)

    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: fill_interval)
    assert trial.record_cycle_verification(
        conn, cycle_id=cycle.cycle_id) == stored
    assert trial.load_verifications(conn) == [stored]

    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: None)
    with pytest.raises(
            trial.TrialEvidenceRefused,
            match="fill-interval source row is missing"):
        trial.load_verifications(conn)


def test_late_cash_backfill_invalidates_ancestor_and_descendant_chain(
        monkeypatch):
    first_session = date(2026, 8, 19)
    second_session = date(2026, 8, 20)
    conn = JsonStateConnection()
    monkeypatch.setattr(trial, "_validate_close_reference", lambda *_: None)
    monkeypatch.setattr(trial, "_validate_fill_reference", lambda *_: None)

    for session in (first_session, second_session):
        stored = {
            "kind": trial.VERIFICATION_KIND,
            "session": session.isoformat(),
            "cycle": {"cycle_id": f"cycle-{session}", "state": "SUCCEEDED"},
            "cash": {"rows": [], "external": "0", "internal": "0"},
            "verdict": "VERIFIED",
            "reason_codes": [],
        }
        stored["evidence_sha256"] = trial._sha(stored)  # noqa: SLF001
        conn.rows[f"{trial.VERIFICATION_PREFIX}{session}"] = (session, stored)

    conn.cash_rows_by_session[first_session] = [(
        "late-deposit", Decimal("25"), "late broker publication", NOW)]

    with pytest.raises(
            trial.TrialEvidenceRefused,
            match="cash-flow source rows changed after verification"):
        trial._previous_verification(  # noqa: SLF001
            conn, date(2026, 8, 21))
    with pytest.raises(
            trial.TrialEvidenceRefused,
            match="cash-flow source rows changed after verification"):
        trial.load_verifications(conn)


def test_renderer_exposes_owner_audit_without_a_write_control():
    from sentinel.panel import model
    from sentinel.panel.render import render

    latest = {
        "reconciliation": {
            "positions": {"SEC-A": "10"}, "target": {"SEC-A": "10"},
            "deltas": {"SEC-A": "0"}, "orders": []},
        "marks": {"SEC-A": {"ticker": "AAA", "close": "80"}},
        "commands": [], "fills": [],
        "cash": {"external": "0", "internal": "12.50", "rows": [{
            "classification": "INTERNAL", "amount": "12.50",
            "detail": "broker-cash/v1;class=INTERNAL;type=DIV;id=d1",
            "recorded_at": NOW.isoformat()}]},
        "nav_attribution": {"marked_nav": "100123.45", "unexplained": "0",
                            "tolerance": "1.00"},
        "account_evidence": {"reconciliation": {
            "corporate_actions": {"SEC-A": "2"}}},
        "paper_limitations": {"compensation_applied": False,
                              "expected_dividends": [{
                                  "security_id": "SEC-A", "ticker": "AAA",
                                  "shares": "10", "per_share": "0.5",
                                  "amount": "5.0"}]},
    }
    panel = model.Panel(
        rows=[model.trial_verification_row(
            verdict="VERIFIED", session="2026-08-20", verified_at=NOW)],
        now=NOW, trial_details=latest,
        trial_history=[{"session": "2026-08-20", "verdict": "VERIFIED",
                        "cycle": {"state": "SUCCEEDED"}, "performance": {},
                        "cash": {}, "reason_codes": []}])
    html = render(panel)

    assert "Positions — target vs Alpaca" in html
    assert "Orders and commands" in html
    assert "Cash and NAV attribution" in html and "type=DIV" in html
    assert "Corporate actions and terminals" in html
    assert "SEC-A dividend entitlement" in html
    assert "Alpaca paper unsupported; no compensation applied" in html
    assert "Trial session history" in html
    for forbidden in ("<form", "<button", "<input", 'type="submit"'):
        assert forbidden not in html.lower()


def test_split_ages_plan_target_before_position_comparison():
    aged = trial._age_plan_target(  # noqa: SLF001 - financial falsifier
        {"SEC-A": "10", "SEC-B": "4"}, {"SEC-A": "2"})

    assert aged == {"SEC-A": Decimal("20"), "SEC-B": Decimal("4")}


def test_corporate_action_cannot_introduce_an_unplanned_security():
    with pytest.raises(trial.TrialEvidenceRefused, match="outside plan target"):
        trial._age_plan_target(  # noqa: SLF001 - financial falsifier
            {"SEC-A": "10"}, {"SPINOFF": "1"})


def test_reconciled_book_treats_omitted_zero_sleeve_as_economic_zero():
    assert trial._economic_book_equal(  # noqa: SLF001 - financial falsifier
        {"CORE": Decimal("10")},
        {"CORE": Decimal("10"), "BIL": Decimal("0")})
    assert not trial._economic_book_equal(  # noqa: SLF001
        {"CORE": Decimal("10")},
        {"CORE": Decimal("10"), "BIL": Decimal("0.000002")})


def test_external_flow_has_pl_but_never_an_assumed_twr():
    result = trial._performance_attribution(  # noqa: SLF001
        opening=Decimal("100"), ending=Decimal("165"),
        external=Decimal("50"), prior_cumulative_factor=Decimal("1.10"))

    assert result == (Decimal("15"), None, Decimal("1.10"), None)


def test_offsetting_external_events_never_manufacture_a_no_flow_return():
    result = trial._performance_attribution(  # noqa: SLF001
        opening=Decimal("100"), ending=Decimal("105"),
        external=Decimal("0"), external_event_count=2,
        prior_cumulative_factor=Decimal("1.10"))

    assert result == (Decimal("5"), None, Decimal("1.10"), None)


def test_no_flow_return_extends_the_exact_verified_chain():
    result = trial._performance_attribution(  # noqa: SLF001
        opening=Decimal("100"), ending=Decimal("105"), external=Decimal("0"),
        prior_cumulative_factor=Decimal("1.10"))

    assert result == (
        Decimal("5"), Decimal("0.05"), Decimal("1.1550"),
        Decimal("0.1550"))


def test_annualization_counts_return_intervals_not_the_anchor_mark():
    from sentinel.panel import sources

    assert sources._annualized_twr(  # noqa: SLF001
        current_factor=1.0, verified_mark_count=1,
        return_interval_count=0) is None
    got = sources._annualized_twr(  # noqa: SLF001
        current_factor=1.02, verified_mark_count=3,
        return_interval_count=2)
    assert got == pytest.approx(1.02 ** 126 - 1)
    assert got != pytest.approx(1.02 ** 84 - 1)


def test_panel_metrics_slice_to_latest_certified_performance_chain():
    from sentinel.panel import sources

    history = [
        {"session": "2026-08-18", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1",
                         "chain": {"chain_id": "epoch-4"}}},
        {"session": "2026-08-19", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1.20",
                         "chain": {"chain_id": "epoch-4"}}},
        {"session": "2026-08-20", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1",
                         "chain": {"chain_id": "epoch-5",
                                   "reset_reason":
                                       "TAKEOVER_EPOCH_CHANGED"}}},
        {"session": "2026-08-21", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1.10",
                         "chain": {"chain_id": "epoch-5"}}},
    ]

    current = sources._latest_verified_chain(history)  # noqa: SLF001

    assert [row["session"] for row in current] == [
        "2026-08-20", "2026-08-21"]
    assert [row["performance"]["cumulative_factor"] for row in current] == [
        "1", "1.10"]

    current_red = [*history, {
        "session": "2026-08-24", "verdict": "NOT_VERIFIED",
        "performance": {"cumulative_factor": "1", "chain": {
            "chain_id": "epoch-6", "reset_reason":
                "TERMINAL_NOT_VERIFIED"}},
    }]
    assert sources._latest_verified_chain(current_red) == []  # noqa: SLF001

    upgrade_history = [
        {"session": "2026-08-18", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1",
                         "daily_return": None}},
        {"session": "2026-08-19", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1.20",
                         "daily_return": "0.20"}},
        {"session": "2026-08-20", "verdict": "VERIFIED",
         "performance": {"cumulative_factor": "1.32",
                         "daily_return": "0.10", "chain": {
                             "chain_id": "epoch-4", "continuous": True,
                             "predecessor_session": "2026-08-19",
                             "reset_reason": None}}},
    ]
    assert [row["session"] for row in sources._latest_verified_chain(  # noqa: SLF001
            upgrade_history)] == [
                "2026-08-18", "2026-08-19", "2026-08-20"]


def test_current_operational_failure_removes_all_verified_styling():
    from sentinel.panel import model
    from sentinel.panel.render import render

    panel = model.Panel(rows=[
        model.trial_verification_row(
            verdict="VERIFIED", session="2026-08-20", verified_at=NOW),
        model.trial_metric_row(
            "trial_return", "Trial total return", "+5.00%", verified=True,
            detail="actual equity", as_of=NOW),
        model.Row("ownership", "Ownership", "UNREADABLE", model.UNKNOWN,
                  "binding row is corrupt"),
    ], now=NOW)

    html = render(panel)

    assert "TRIAL NOT VERIFIED — CURRENT OPERATIONAL CONDITION UNKNOWN" in html
    assert 'data-key="trial_verification" data-status="fail"' in html
    assert 'data-key="trial_return" data-status="warn"' in html
    assert 'data-key="trial_return" data-status="ok"' not in html


def test_success_certificate_binds_strategy_evidence_and_split_target(
        monkeypatch):
    from sentinel import trial_evidence
    from sentinel.automation import store as automation_store
    from sentinel.core import decision
    from sentinel.feed import calendar, publication
    from sentinel.feed import store as feed_store
    from sentinel.execution import broker_cash, journal

    # This test exercises downstream close arithmetic with a hypothetical
    # accepted plan/session-bound finality source. Production has no such
    # source; the explicit property override is test-only and cannot promote
    # retained rows by adding a global scheme string.

    decision_session = date(2026, 8, 19)
    effective_session = date(2026, 8, 20)
    strategy_identity = {"strategy": "simplified-concordance", "version": 3}
    strategy_sha = hashlib.sha256(
        trial._canonical(strategy_identity).encode("ascii")).hexdigest()  # noqa: SLF001
    plan = ExecutionPlan(
        plan_id="sentinel-plan-211", decision_session=decision_session,
        effective_session=effective_session, target_exposure=Decimal("1"),
        target_basket={"SEC-A": Decimal("10")}, data_version=41,
        shadow_snapshot_hash="state-sha", strategy_fingerprint=strategy_sha,
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=4,
        publication_fingerprint="decision-publication",
        account_nav=Decimal("100"), account_cash=Decimal("0"))
    target_projection = target_reprojection.project_target(
        plan, through_session=effective_session,
        action_multipliers={"SEC-A": Decimal("2")})
    cycle = SimpleNamespace(
        cycle_id="cycle-211", state=CycleState.SUCCEEDED,
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        decision_session=decision_session, effective_session=effective_session,
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=4,
        rollout_mode="PINNED_1_00", rollout_version=1,
        certificate_sha256=None, state_fingerprint="state-sha",
        data_version="41", publication_fingerprint="decision-publication",
        last_clean_reconciliation_id="17", completed_at=NOW - timedelta(hours=8))
    state = SimpleNamespace(
        last_processed_session=decision_session.isoformat(),
        state_hash="state-sha", data_version=41,
        strategy_identity=strategy_identity, wealth_core={},
        ledger={"events": [], "receivables": []},
        last_decision={"allocation": "1"},
        last_evidence={"session": decision_session.isoformat()})
    observed_at = NOW - timedelta(minutes=1)
    observation = {
        "observed_at": observed_at, "completeness": "COMPLETE",
        "runtime_state": "RUNNING", "positions": {"SEC-A": "20"},
        "orders": []}
    account = {
        "session": effective_session.isoformat(), "observation_id": 17,
        "observation_started_at": observed_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "reconciliation_started_at": observed_at.isoformat(),
        "reconciliation_observed_at": observed_at.isoformat(),
        "deployment": {"deployment_id": "trial-appliance", "broker": "alpaca",
                       "broker_account_id": "PA-1", "takeover_epoch": 4},
        # Deliberately later live values: v3 performance must use the immutable
        # historical close point and independently reconstructed close cash.
        "account": {"equity": "999", "cash": "777", "status": "ACTIVE",
                    "trading_blocked": False, "account_blocked": False,
                    "trade_suspended_by_user": False},
        "reconciliation": {
            "plan_target": {"SEC-A": "10"}, "target": {"SEC-A": "20"},
            "target_projection": target_projection.payload(),
            "target_corporate_actions": {"SEC-A": "2"},
            "observation_target": {"SEC-A": "20"},
            "observation_target_corporate_actions": {},
            "expected": {"SEC-A": "20"},
            "corporate_actions": {"SEC-A": "2"}},
        "cash_activity": {"processed_through": NOW.isoformat(),
                          "last_activity_id": "cash-before-plan",
                          "last_event_id": "event-after-close",
                          "activity_identity_scheme":
                              broker_cash.ACTIVITY_IDENTITY_SCHEME,
                          "balance_total": "0"}}
    strategy = {
        "session": decision_session.isoformat(), "data_version": 41,
        "state_sha256": "state-sha", "strategy_identity": strategy_identity,
        "decision": state.last_decision, "evidence": state.last_evidence,
        "recent_leadership": {}, "ldrc": {}, "payload_sha256": "evidence-sha",
        "recorded_at": NOW - timedelta(hours=9)}
    current_publication = SimpleNamespace(version=42)
    readiness = {
        "snapshot_id": 9, "computed_at": NOW - timedelta(minutes=2),
        "ready": True, "checks_passed": 4, "checks_total": 4, "checks": []}
    _opened, official_close = calendar.session_window(effective_session)
    deployment = DeploymentIdentity(
        deployment_id="trial-appliance", broker="alpaca",
        broker_account_id="PA-1", takeover_epoch=4)
    close_valuation = BrokerCloseValuation(
        identity=BrokerAccountIdentity(broker="alpaca", account_id="PA-1"),
        requested_session=effective_session, equity=Decimal("100"),
        source_timestamp=int(_opened.timestamp()),
        source_timeframe="1D", source="alpaca_portfolio_history",
        semantics="ACCEPTED_1D_CLOSE_POINT",
        request_started_at=official_close + timedelta(minutes=1),
        request_completed_at=(
            official_close + timedelta(minutes=1, seconds=1)),
        query=(("cashflow_types", "ALL"), ("timeframe", "1D")),
        source_timestamp_unit="epoch_seconds", valuation_at=official_close,
        raw={"timestamp": [int(_opened.timestamp())],
             "equity": ["100"], "timeframe": "1D"})
    close_evidence = trial_close.build_close_nav_evidence(
        deployment=deployment, valuation=close_valuation)
    baseline = broker_cash.PlanCashBaseline(
        plan_id=plan.plan_id, broker="alpaca", account_id="PA-1",
        decision_session=decision_session,
        processed_through=NOW - timedelta(hours=9),
        balance_total=Decimal("0"),
        last_activity_id="cash-before-plan",
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    fill_interval = BrokerFillIntervalEvidence(
        identity=BrokerAccountIdentity(broker="alpaca", account_id="PA-1"),
        requested_session=effective_session,
        interval_start=baseline.processed_through,
        processed_through=NOW - timedelta(seconds=30), fills=(),
        completeness=Completeness.COMPLETE,
        source="accepted_account_fill_ledger",
        semantics=trial_fills.FILL_INTERVAL_SEMANTICS,
        request_started_at=NOW - timedelta(seconds=20),
        request_completed_at=NOW - timedelta(seconds=10),
        query=(("after", baseline.processed_through.isoformat()),
               ("through", (NOW - timedelta(seconds=30)).isoformat())),
        raw={"activities": [], "complete": True})
    fill_evidence = trial_fills.build_fill_interval_evidence(
        deployment=deployment, plan_id=plan.plan_id,
        interval=fill_interval)

    monkeypatch.setattr(automation_store, "load_cycle", lambda *_: cycle)
    monkeypatch.setattr(journal, "load_plan", lambda *_: plan)
    monkeypatch.setattr(
        target_reprojection, "load_projection",
        lambda *_args, **_kwargs: target_projection)
    monkeypatch.setattr(trial, "_read_binding", lambda *_: {
        "deployment_id": "trial-appliance", "broker": "alpaca",
        "broker_account_id": "PA-1", "takeover_epoch": 4,
        "ownership_state": "OWNED"})
    monkeypatch.setattr(
        trial, "_read_state", lambda *_: (state, decision_session,
                                           NOW - timedelta(hours=9)))
    monkeypatch.setattr(
        trial_evidence, "load_strategy_session", lambda *_: strategy)
    monkeypatch.setattr(trial, "_read_observation", lambda *_: observation)
    monkeypatch.setattr(trial, "load_account_evidence", lambda *_: account)
    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence",
        lambda *_args, **_kwargs: close_evidence)
    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: fill_evidence)
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: baseline)
    monkeypatch.setattr(trial, "_read_readiness", lambda *_: readiness)
    monkeypatch.setattr(publication, "current", lambda *_: current_publication)
    monkeypatch.setattr(
        decision, "publication_fingerprint", lambda *_: "valuation-publication")
    monkeypatch.setattr(
        feed_store, "latest_visible_session",
        lambda *_: effective_session.isoformat())
    monkeypatch.setattr(
        calendar, "freshness",
        lambda *_: SimpleNamespace(evaluable=True, sessions_behind=0, ahead=False))
    monkeypatch.setattr(
        trial, "_publication_time", lambda *_: NOW - timedelta(minutes=3))
    monkeypatch.setattr(
        trial, "_cash_rows", lambda *_: ([], Decimal("0"), Decimal("0")))
    monkeypatch.setattr(
        trial, "_marks",
        lambda *_: ({"SEC-A": {"ticker": "AAA", "close": "5"}},
                    Decimal("100")))
    monkeypatch.setattr(trial, "_previous_verification", lambda *_: None)
    monkeypatch.setattr(
        trial, "_terminal_verification_debt", lambda *_: ())
    defensive_calls = []

    def no_defensive_dividend(_conn, session, positions, commands):
        defensive_calls.append((session, positions, commands))
        return []

    monkeypatch.setattr(
        trial, "_expected_effective_equity_dividends", lambda *_: [])
    monkeypatch.setattr(
        trial, "_expected_defensive_dividends", no_defensive_dividend)

    unfinal_cash = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert unfinal_cash["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_CASH_FINALITY_UNAVAILABLE" in unfinal_cash["reason_codes"]
    monkeypatch.setattr(
        broker_cash.PlanCashBaseline,
        "close_cash_finality_authoritative", property(lambda _self: True))

    result = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)

    expected_chain_id = hashlib.sha256(trial._canonical({  # noqa: SLF001
        "deployment_id": "trial-appliance", "broker": "alpaca",
        "broker_account_id": "PA-1", "takeover_epoch": 4,
    }).encode("ascii")).hexdigest()

    assert result["verdict"] == "VERIFIED", result["reason_codes"]
    assert result["nav_attribution"]["unexplained"] == "0"
    assert result["nav_attribution"]["independent_close_nav"] == "100"
    assert result["nav_attribution"]["close_cash"] == "0"
    assert result["nav_attribution"]["live_account_equity"] == "999"
    assert result["nav_attribution"]["live_account_cash"] == "777"
    assert result["performance"] == {
        "opening_equity": None, "ending_equity": "100",
        "actual_cash": "0", "strategy_pl": None, "daily_return": None,
        "cumulative_factor": "1", "total_return": None,
        "chain": {"chain_id": expected_chain_id,
                  "predecessor_session": None, "continuous": False,
                  "reset_reason": "INITIAL_V3_ANCHOR"},
    }
    assert result["close_nav_evidence"]["evidence_sha256"] == (
        close_evidence["evidence_sha256"])
    assert result["fill_interval_evidence"]["evidence_sha256"] == (
        fill_evidence["evidence_sha256"])
    assert defensive_calls[-1] == (
        effective_session, {"SEC-A": "20"}, [])
    assert result["reconciliation"]["plan_target"] == {"SEC-A": "10"}
    assert result["reconciliation"]["target"] == {"SEC-A": "20"}
    assert result["reconciliation"]["observation_target"] == {"SEC-A": "20"}
    assert result["reconciliation"]["deltas"] == {"SEC-A": "0"}
    assert result["state"]["strategy_evidence"]["payload_sha256"] == "evidence-sha"
    assert result["paper_limitations"] == {
        "expected_dividends": [], "compensation_applied": False}

    # A later observation can legitimately be in post-close split units.  The
    # live reconciliation is checked against that later action-aged book while
    # historical close marks remain bound to the close-time target.
    delayed_observation = {
        **observation, "positions": {"SEC-A": "40"}}
    delayed_account = {
        **account,
        "reconciliation": {
            **account["reconciliation"],
            "observation_target": {"SEC-A": "40"},
            "observation_target_corporate_actions": {"SEC-A": "2"},
            "expected": {"SEC-A": "40"},
            "corporate_actions": {"SEC-A": "4"},
        },
    }
    marked_books = []

    def close_marks(_conn, _session, book):
        marked_books.append(book)
        return {"SEC-A": {"ticker": "AAA", "close": "5"}}, Decimal("100")

    monkeypatch.setattr(
        trial, "_read_observation", lambda *_: delayed_observation)
    monkeypatch.setattr(
        trial, "load_account_evidence", lambda *_: delayed_account)
    monkeypatch.setattr(trial, "_marks", close_marks)
    monkeypatch.setattr(
        feed_store, "latest_visible_session",
        lambda *_: calendar.next_session(effective_session.isoformat()))
    delayed_split = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert delayed_split["verdict"] == "VERIFIED", delayed_split["reason_codes"]
    assert delayed_split["reconciliation"]["target"] == {"SEC-A": "20"}
    assert delayed_split["reconciliation"]["observation_target"] == {
        "SEC-A": "40"}
    assert delayed_split["reconciliation"]["deltas"] == {"SEC-A": "0"}
    assert marked_books[-1] == {"SEC-A": "20"}
    monkeypatch.setattr(trial, "_read_observation", lambda *_: observation)
    monkeypatch.setattr(trial, "load_account_evidence", lambda *_: account)
    monkeypatch.setattr(
        feed_store, "latest_visible_session",
        lambda *_: effective_session.isoformat())
    monkeypatch.setattr(
        trial, "_marks",
        lambda *_: ({"SEC-A": {"ticker": "AAA", "close": "5"}},
                    Decimal("100")))

    # A durable terminal state without its exact callback certificate is a
    # visible gap; a later success cannot silently become a fresh green anchor.
    callback_debt = ({
        "cycle_id": "cycle-missed", "session": decision_session.isoformat(),
        "state": "MISSED_STATE_ONLY", "reason": "TERMINAL_V3_MISSING",
    },)
    monkeypatch.setattr(
        trial, "_terminal_verification_debt", lambda *_: callback_debt)
    missing_callback = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert missing_callback["verdict"] == "NOT_VERIFIED"
    assert "VERIFICATION_GAP" in missing_callback["reason_codes"]
    assert missing_callback["terminal_verification_debt"] == list(callback_debt)
    monkeypatch.setattr(
        trial, "_terminal_verification_debt", lambda *_: ())

    # The first close is only an anchor.  An adjacent prior VERIFIED close,
    # never the later plan-sizing snapshot, opens the next return interval.
    monkeypatch.setattr(trial, "_previous_verification", lambda *_: {
        "session": decision_session.isoformat(),
        "verdict": "VERIFIED",
        "binding": {
            "deployment_id": "trial-appliance", "broker": "alpaca",
            "broker_account_id": "PA-1", "takeover_epoch": 4,
            "ownership_state": "OWNED"},
        "performance": {
            "ending_equity": "80", "cumulative_factor": "1.10"},
    })
    chained = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert chained["verdict"] == "VERIFIED", chained["reason_codes"]
    assert chained["performance"] == {
        "opening_equity": "80", "ending_equity": "100",
        "actual_cash": "0", "strategy_pl": "20", "daily_return": "0.25",
        "cumulative_factor": "1.3750", "total_return": "0.3750",
        "chain": {
            "chain_id": expected_chain_id,
            "predecessor_session": decision_session.isoformat(),
            "continuous": True, "reset_reason": None},
    }

    # A new account/deployment or explicit takeover epoch is a certified
    # performance reset, never a cross-account return and never an immortal
    # false-red chain.
    for changed_binding, reset_reason in (
        ({"deployment_id": "trial-appliance", "broker": "alpaca",
          "broker_account_id": "PA-OTHER", "takeover_epoch": 4},
         "DEPLOYMENT_OR_ACCOUNT_CHANGED"),
        ({"deployment_id": "trial-appliance", "broker": "alpaca",
          "broker_account_id": "PA-1", "takeover_epoch": 3},
         "TAKEOVER_EPOCH_CHANGED"),
    ):
        monkeypatch.setattr(trial, "_previous_verification", lambda *_args,
                            changed=changed_binding: {
            "session": decision_session.isoformat(),
            "verdict": "VERIFIED", "binding": changed,
            "performance": {
                "ending_equity": "80", "cumulative_factor": "9"},
        })
        reset = trial.build_cycle_verification(
            VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
            observation_id=17, now=NOW)
        assert reset["verdict"] == "VERIFIED", reset["reason_codes"]
        assert reset["performance"]["opening_equity"] is None
        assert reset["performance"]["daily_return"] is None
        assert reset["performance"]["cumulative_factor"] == "1"
        assert reset["performance"]["chain"]["reset_reason"] == reset_reason

    monkeypatch.setattr(trial, "_previous_verification", lambda *_: {
        "session": decision_session.isoformat(), "verdict": "NOT_VERIFIED",
        "binding": {
            "deployment_id": "trial-appliance", "broker": "alpaca",
            "broker_account_id": "PA-1", "takeover_epoch": 4},
        "performance": {"ending_equity": "80", "cumulative_factor": "1"},
    })
    same_epoch_gap = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert same_epoch_gap["verdict"] == "NOT_VERIFIED"
    assert "VERIFICATION_GAP" in same_epoch_gap["reason_codes"]
    monkeypatch.setattr(trial, "_previous_verification", lambda *_: None)

    # Two capital movements are still two denominator crossings even if their
    # net amount is zero.  Netting must not manufacture a no-flow return.
    offsetting_flows = [
        {"flow_id": "operator-in", "amount": "25",
         "classification": "EXTERNAL", "detail": "deposit",
         "recorded_at": (NOW - timedelta(minutes=2)).isoformat()},
        {"flow_id": "operator-out", "amount": "-25",
         "classification": "EXTERNAL", "detail": "withdrawal",
         "recorded_at": (NOW - timedelta(minutes=1)).isoformat()},
    ]
    monkeypatch.setattr(
        trial, "_cash_rows",
        lambda *_: (offsetting_flows, Decimal("0"), Decimal("0")))
    offsetting_external = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert offsetting_external["verdict"] == "NOT_VERIFIED"
    assert "EXTERNAL_FLOW_UNWEIGHTED" in offsetting_external["reason_codes"]
    assert offsetting_external["performance"]["daily_return"] is None
    monkeypatch.setattr(
        trial, "_cash_rows",
        lambda *_: ([], Decimal("0"), Decimal("0")))

    # A transiently absent historical source is visible and can never inherit
    # the later live account values merely because they happen to be present.
    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence", lambda *_args, **_kwargs: None)
    missing_close = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert missing_close["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_NAV_EVIDENCE_MISSING" in missing_close["reason_codes"]
    assert missing_close["performance"]["ending_equity"] is None
    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence",
        lambda *_args, **_kwargs: close_evidence)

    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: None)
    missing_fills = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert missing_fills["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_FILL_INTERVAL_EVIDENCE_MISSING" in (
        missing_fills["reason_codes"])
    assert "CLOSE_BOOK_INTERVAL_UNPROVEN" in missing_fills["reason_codes"]
    assert missing_fills["nav_attribution"]["close_cash"] is None
    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: fill_evidence)

    future_fill = {
        **fill_evidence,
        "request_completed_at": (NOW + timedelta(minutes=1)).isoformat(),
    }
    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: future_fill)
    future_fills = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert future_fills["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_FILL_INTERVAL_EVIDENCE_FUTURE" in (
        future_fills["reason_codes"])
    monkeypatch.setattr(
        trial_fills, "load_fill_interval_evidence",
        lambda *_args, **_kwargs: fill_evidence)

    # A valid source row still cannot certify a verdict in its own future.
    future_valuation = BrokerCloseValuation(**{
        **close_valuation.__dict__,
        "request_started_at": NOW + timedelta(minutes=1),
        "request_completed_at": NOW + timedelta(minutes=1, seconds=1),
    })
    future_close = trial_close.build_close_nav_evidence(
        deployment=deployment, valuation=future_valuation)
    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence",
        lambda *_args, **_kwargs: future_close)
    future = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert future["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_NAV_EVIDENCE_FUTURE" in future["reason_codes"]
    assert future["nav_attribution"]["timestamp_aligned"] is False
    monkeypatch.setattr(
        trial_close, "load_close_nav_evidence",
        lambda *_args, **_kwargs: close_evidence)

    # A changed cumulative broker activity total cannot be assigned to the
    # official close because Alpaca supplies only a business date.
    account["cash_activity"]["balance_total"] = "1"
    changed_cash = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert changed_cash["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_CASH_UNPROVEN" in changed_cash["reason_codes"]
    assert changed_cash["nav_attribution"]["close_cash"] is None
    account["cash_activity"]["balance_total"] = "0"

    # Equal cumulative totals are not equal event sets. Offsetting non-zero
    # cash events advance the native activity identity and remain unassignable
    # when the broker exposes only their business date.
    account["cash_activity"]["last_activity_id"] = "cash-offsetting-later"
    offsetting_cash = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert offsetting_cash["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_CASH_UNPROVEN" in offsetting_cash["reason_codes"]
    account["cash_activity"]["last_activity_id"] = "cash-before-plan"

    legacy_baseline = broker_cash.PlanCashBaseline(
        plan_id=plan.plan_id, broker="alpaca", account_id="PA-1",
        decision_session=decision_session,
        processed_through=NOW - timedelta(hours=9),
        balance_total=Decimal("0"))
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: legacy_baseline)
    legacy_cash = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert legacy_cash["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_CASH_UNPROVEN" in legacy_cash["reason_codes"]
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: baseline)

    # A fill after the official boundary belongs to no certified closing book.
    command_rows = [(
        "client-late", "SEC-A", "BUY", Decimal("1"), "FILLED",
        "order-late", Decimal("1"), Decimal("5"), "late fill",
        official_close + timedelta(seconds=2))]
    fill_rows = [(
        "order-late", "fill-late", "client-late", Decimal("1"),
        Decimal("5"), official_close + timedelta(seconds=1))]
    late_fill = trial.build_cycle_verification(
        VerificationConnection(
            plan.plan_id, command_rows=command_rows, fill_rows=fill_rows),
        cycle_id=cycle.cycle_id, observation_id=17, now=NOW)
    assert late_fill["verdict"] == "NOT_VERIFIED"
    assert "CLOSE_BOOK_INTERVAL_UNPROVEN" in late_fill["reason_codes"]

    entitlement = {
        "security_id": "SEC-A", "ticker": "AAA",
        "accrued_session": effective_session.isoformat(), "shares": "10",
        "per_share": "0.5", "amount": "5.0",
        "settlement_lag_sessions": 1,
    }
    monkeypatch.setattr(
        trial, "_expected_effective_equity_dividends",
        lambda *_: [entitlement])
    limited = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)

    assert limited["verdict"] == "NOT_VERIFIED"
    assert "ALPACA_PAPER_DIVIDEND_UNSUPPORTED" in limited["reason_codes"]
    assert limited["paper_limitations"] == {
        "expected_dividends": [entitlement], "compensation_applied": False}
    assert limited["account_evidence"]["account"]["cash"] == "777"
    assert limited["performance"]["actual_cash"] == "0"

    bil_entitlement = {
        "security_id": "SENTINEL:BIL", "ticker": "BIL",
        "accrued_session": effective_session.isoformat(), "shares": "12",
        "per_share": "0.25", "amount": "3.00",
        "reported_per_share": "0.25", "source_row_ids": ["action-bil"],
        "source": "SHARADAR_ACTIONS", "settlement_lag_sessions": None,
    }
    monkeypatch.setattr(
        trial, "_expected_effective_equity_dividends", lambda *_: [])
    monkeypatch.setattr(
        trial, "_expected_defensive_dividends",
        lambda *_: [bil_entitlement])
    bil_limited = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert bil_limited["verdict"] == "NOT_VERIFIED"
    assert "ALPACA_PAPER_DIVIDEND_UNSUPPORTED" in \
        bil_limited["reason_codes"]
    assert bil_limited["paper_limitations"] == {
        "expected_dividends": [bil_entitlement],
        "compensation_applied": False,
    }

    def invalid_defensive(*_args):
        raise trial.TrialEvidenceRefused("missing BIL price basis")

    monkeypatch.setattr(
        trial, "_expected_defensive_dividends", invalid_defensive)
    invalid = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert "DIVIDEND_EVIDENCE_INVALID" in invalid["reason_codes"]
