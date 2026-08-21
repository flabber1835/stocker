"""Issue #211 — financial green is an earned, immutable session fact."""
from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import trial
from sentinel.automation.model import CycleState
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
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
        self.result = None
        self.pending = None

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split()).lower()
        if normalized.startswith("select session,state from sentinel_processed_sessions"):
            self.result = self.rows.get(params[0])
            return
        if normalized.startswith("insert into sentinel_processed_sessions"):
            name, session, raw = params
            self.pending = (name, date.fromisoformat(str(session)), json.loads(raw))
            return
        raise AssertionError(f"unexpected trial SQL: {statement}")

    def fetchone(self):
        return self.result

    def commit(self):
        if self.pending is not None:
            name, session, state = self.pending
            self.rows[name] = (session, state)
            self.pending = None


class VerificationConnection:
    def __init__(self, plan_id):
        self.plan_id = plan_id
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
        elif (normalized.startswith("select client_key,security_id")
              or normalized.startswith("select f.broker_order_id")):
            self.result = []
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
        balance_total=Decimal("125.00"))
    return deployment, reconciliation, snapshot, activity


def test_account_evidence_is_observation_bound_and_immutable():
    conn = JsonStateConnection()
    deployment, reconciliation, snapshot, activity = _clean_account_evidence()

    first = trial.record_account_evidence(
        conn, session=date(2026, 8, 20), observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=reconciliation, activity_state=activity,
        plan_target={"SEC-A": Decimal("10")},
        target_actions={"SEC-A": Decimal("2")})
    again = trial.record_account_evidence(
        conn, session=date(2026, 8, 20), observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=reconciliation, activity_state=activity,
        plan_target={"SEC-A": Decimal("10")},
        target_actions={"SEC-A": Decimal("2")})

    assert first == again
    assert first["account"] == {
        "equity": "100123.45", "cash": "20123.45", "status": "ACTIVE",
        "trading_blocked": False, "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    assert first["reconciliation"]["expected"] == {"SEC-A": "20"}
    assert first["reconciliation"]["corporate_actions"] == {"SEC-A": "2"}
    assert first["reconciliation"]["plan_target"] == {"SEC-A": "10"}
    assert first["reconciliation"]["target"] == {"SEC-A": "20"}
    assert first["reconciliation"]["target_corporate_actions"] == {
        "SEC-A": "2"}
    changed = BrokerAccountSnapshot(
        **{**snapshot.__dict__, "equity": Decimal("100123.46")})
    with pytest.raises(trial.TrialEvidenceRefused, match="immutable"):
        trial.record_account_evidence(
            conn, session=date(2026, 8, 20), observation_id=17,
            observation_started_at=NOW, observed_at=NOW,
            snapshot=changed, deployment=deployment,
            reconciliation=reconciliation, activity_state=activity,
            plan_target={"SEC-A": Decimal("10")},
            target_actions={"SEC-A": Decimal("2")})


def test_account_evidence_fingerprint_corruption_is_not_read_as_truth():
    conn = JsonStateConnection()
    deployment, reconciliation, snapshot, activity = _clean_account_evidence()
    trial.record_account_evidence(
        conn, session=date(2026, 8, 20), observation_id=17,
        observation_started_at=NOW, observed_at=NOW,
        snapshot=snapshot, deployment=deployment,
        reconciliation=reconciliation, activity_state=activity,
        plan_target={"SEC-A": Decimal("10")},
        target_actions={"SEC-A": Decimal("2")})
    conn.rows[f"{trial.ACCOUNT_PREFIX}17"][1]["account"]["cash"] = "999999"

    with pytest.raises(trial.TrialEvidenceRefused, match="fingerprint"):
        trial.load_account_evidence(conn, 17)


def test_legacy_v1_verification_cannot_enter_the_corrected_v2_chain():
    session = date(2026, 8, 20)
    legacy = {
        "kind": "sentinel-trial-verification/v1",
        "session": session.isoformat(),
        "verdict": "VERIFIED",
    }
    legacy["evidence_sha256"] = trial._sha(legacy)  # noqa: SLF001

    assert trial.VERIFICATION_PREFIX == "trial-verification:v2:"
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


def test_external_flow_has_pl_but_never_an_assumed_twr():
    result = trial._performance_attribution(  # noqa: SLF001
        opening=Decimal("100"), ending=Decimal("165"),
        external=Decimal("50"), prior_cumulative_factor=Decimal("1.10"))

    assert result == (Decimal("15"), None, Decimal("1.10"), None)


def test_no_flow_return_extends_the_exact_verified_chain():
    result = trial._performance_attribution(  # noqa: SLF001
        opening=Decimal("100"), ending=Decimal("105"), external=Decimal("0"),
        prior_cumulative_factor=Decimal("1.10"))

    assert result == (
        Decimal("5"), Decimal("0.05"), Decimal("1.1550"),
        Decimal("0.1550"))


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
    from sentinel.execution import journal

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
        "account": {"equity": "100", "cash": "0", "status": "ACTIVE",
                    "trading_blocked": False, "account_blocked": False,
                    "trade_suspended_by_user": False},
        "reconciliation": {
            "plan_target": {"SEC-A": "10"}, "target": {"SEC-A": "20"},
            "target_corporate_actions": {"SEC-A": "2"},
            "expected": {"SEC-A": "20"},
            "corporate_actions": {"SEC-A": "2"}},
        "cash_activity": {"processed_through": NOW.isoformat()}}
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

    monkeypatch.setattr(automation_store, "load_cycle", lambda *_: cycle)
    monkeypatch.setattr(journal, "load_plan", lambda *_: plan)
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
    defensive_calls = []

    def no_defensive_dividend(_conn, session, positions, commands):
        defensive_calls.append((session, positions, commands))
        return []

    monkeypatch.setattr(
        trial, "_expected_effective_equity_dividends", lambda *_: [])
    monkeypatch.setattr(
        trial, "_expected_defensive_dividends", no_defensive_dividend)

    result = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)

    # Numerically equal live equity and official-close marked NAV are not the
    # same valuation fact when the account read happened at a later instant.
    assert result["nav_attribution"]["unexplained"] == "0"
    assert result["verdict"] == "NOT_VERIFIED"
    assert "VALUATION_TIMESTAMP_UNALIGNED" in result["reason_codes"]
    assert defensive_calls[-1] == (
        effective_session, {"SEC-A": "20"}, [])

    # Evidence written before request-bracket fields were introduced is never
    # upgraded by inference.  It remains readable but financially unverified.
    reconciliation_observed_at = account.pop("reconciliation_observed_at")
    legacy = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)
    assert legacy["verdict"] == "NOT_VERIFIED"
    assert "VALUATION_TIMESTAMP_UNALIGNED" in legacy["reason_codes"]
    account["reconciliation_observed_at"] = reconciliation_observed_at

    monkeypatch.setattr(
        trial, "_valuation_timestamp_aligned", lambda *_: True)
    result = trial.build_cycle_verification(
        VerificationConnection(plan.plan_id), cycle_id=cycle.cycle_id,
        observation_id=17, now=NOW)

    assert result["verdict"] == "VERIFIED", result["reason_codes"]
    assert result["reconciliation"]["plan_target"] == {"SEC-A": "10"}
    assert result["reconciliation"]["target"] == {"SEC-A": "20"}
    assert result["reconciliation"]["deltas"] == {"SEC-A": "0"}
    assert result["state"]["strategy_evidence"]["payload_sha256"] == "evidence-sha"
    assert result["paper_limitations"] == {
        "expected_dividends": [], "compensation_applied": False}

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
    assert limited["account_evidence"]["account"]["cash"] == "0"

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
