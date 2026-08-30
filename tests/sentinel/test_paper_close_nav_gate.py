"""A succeeded cycle cannot be superseded without accepted close NAV."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import paper, trial, trial_close, trial_fills
from sentinel.paper import (
    cash as paper_cash,
    finalization as paper_finalization,
    preparation as paper_preparation,
)
from sentinel.execution import broker_cash, journal
from sentinel.execution.contract import MalformedBrokerEvidence
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerFillIntervalEvidence,
    BrokerObservation, Completeness)


SESSION = date(2026, 8, 20)
DECISION = date(2026, 8, 19)
BASELINE_AT = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
CLOSE = datetime(2026, 8, 20, 20, tzinfo=timezone.utc)
REQUIRED_THROUGH = CLOSE + timedelta(minutes=5)
PROCESSED_THROUGH = REQUIRED_THROUGH + timedelta(minutes=1)
DEPLOYMENT = SimpleNamespace(
    deployment_id="deploy", broker="alpaca",
    broker_account_id="PA-1", takeover_epoch=1)
PLAN = SimpleNamespace(
    plan_id="plan-fill-gate", broker="alpaca",
    broker_account_id="PA-1", decision_session=DECISION,
    effective_session=SESSION,
    target_basket={"SEC-A": Decimal(5)})
BASELINE = broker_cash.PlanCashBaseline(
    plan_id=PLAN.plan_id, broker="alpaca", account_id="PA-1",
    decision_session=DECISION, processed_through=BASELINE_AT,
    balance_total=Decimal(0), last_activity_id="cash-before-plan",
    activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)


class CloseBroker:
    def __init__(self, *, supported=True, result=None, error=None):
        self.supports_account_close_valuation = supported
        self.result = result or object()
        self.error = error
        self.calls = []

    async def account_close_valuation(self, *, session):
        self.calls.append(session)
        if self.error is not None:
            raise self.error
        return self.result


class FillBroker:
    def __init__(self, *, supported=True, result=None, error=None):
        self.supports_account_fill_interval_evidence = supported
        self.result = result or object()
        self.error = error
        self.calls = []

    async def account_fill_interval_evidence(
            self, *, session, interval_start):
        self.calls.append((session, interval_start))
        if self.error is not None:
            raise self.error
        return self.result


def fill_interval(*, interval_start=BASELINE_AT,
                  processed_through=PROCESSED_THROUGH):
    return BrokerFillIntervalEvidence(
        identity=BrokerAccountIdentity("alpaca", "PA-1"),
        requested_session=SESSION, interval_start=interval_start,
        processed_through=processed_through, fills=(),
        completeness=Completeness.COMPLETE,
        source="accepted_account_fill_ledger",
    semantics=trial_fills.FILL_INTERVAL_SEMANTICS,
    request_started_at=processed_through + timedelta(seconds=1),
        request_completed_at=processed_through + timedelta(seconds=2),
        query=(("after", interval_start.isoformat()),
               ("through", processed_through.isoformat())),
    raw={"complete": True, "fills": []})


@pytest.fixture(autouse=True)
def certified_observation_history(monkeypatch):
    """These unit tests isolate close evidence from the history gate."""
    monkeypatch.setattr(
        journal, "require_observation_integrity", lambda _conn: None)


def run(coro):
    return asyncio.run(coro)


def test_uncertified_source_refuses_before_transport(monkeypatch):
    broker = CloseBroker(supported=False)
    monkeypatch.setattr(
        trial_close, "record_close_nav_evidence",
        lambda *_args, **_kwargs: pytest.fail("uncertified point was recorded"))

    with pytest.raises(paper.PaperRetryableRefused, match="not a certified"):
        run(paper_finalization._record_due_close_nav_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, session=SESSION))

    assert broker.calls == []


def test_accepted_point_is_recorded_before_the_due_cycle_can_advance(
        monkeypatch):
    valuation = object()
    broker = CloseBroker(result=valuation)
    captured = []
    monkeypatch.setattr(
        trial_close, "record_close_nav_evidence",
        lambda conn, *, deployment, valuation: captured.append(
            (conn, deployment, valuation)) or {"evidence_sha256": "a" * 64})
    conn = object()

    result = run(paper_finalization._record_due_close_nav_or_refuse(  # noqa: SLF001
        conn, broker=broker, deployment=DEPLOYMENT, session=SESSION))

    assert result == {"evidence_sha256": "a" * 64}
    assert broker.calls == [SESSION]
    assert captured == [(conn, DEPLOYMENT, valuation)]


def test_transport_unavailability_is_retryable_and_records_nothing(monkeypatch):
    broker = CloseBroker(error=RuntimeError("history not mature"))
    monkeypatch.setattr(
        trial_close, "record_close_nav_evidence",
        lambda *_args, **_kwargs: pytest.fail("unavailable point was recorded"))

    with pytest.raises(
            paper.PaperRetryableRefused, match="temporarily unavailable"):
        run(paper_finalization._record_due_close_nav_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, session=SESSION))


def test_malformed_transport_evidence_is_not_retried_as_an_outage(monkeypatch):
    broker = CloseBroker(error=MalformedBrokerEvidence("bad history shape"))
    monkeypatch.setattr(
        trial_close, "record_close_nav_evidence",
        lambda *_args, **_kwargs: pytest.fail("malformed point was recorded"))

    with pytest.raises(
            paper.PaperActivationRefused, match="malformed or contradictory"):
        run(paper_finalization._record_due_close_nav_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, session=SESSION))


def test_malformed_or_revised_history_is_a_hard_refusal(monkeypatch):
    broker = CloseBroker()

    def refuse(*_args, **_kwargs):
        raise trial_close.TrialCloseNavHistoricalRevision("history changed")

    monkeypatch.setattr(trial_close, "record_close_nav_evidence", refuse)

    with pytest.raises(
            paper.PaperActivationRefused, match="acceptance contract"):
        run(paper_finalization._record_due_close_nav_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, session=SESSION))


def test_fill_interval_requires_certified_capability_before_baseline_or_transport(
        monkeypatch):
    broker = FillBroker(supported=False)
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: pytest.fail(
            "uncertified fill source read the plan baseline"))
    monkeypatch.setattr(
        trial_fills, "record_fill_interval_evidence",
        lambda *_args, **_kwargs: pytest.fail(
            "uncertified fill interval was recorded"))

    with pytest.raises(paper.PaperRetryableRefused, match="not a certified"):
        run(paper_finalization._record_due_fill_interval_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, plan=PLAN,
            session=SESSION, required_through=REQUIRED_THROUGH))

    assert broker.calls == []


def test_fill_interval_uses_exact_authoritative_plan_cash_boundary_and_records(
        monkeypatch):
    interval = fill_interval()
    broker = FillBroker(result=interval)
    conn = object()
    recorded = []
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda _conn, *, plan_id: BASELINE if plan_id == PLAN.plan_id else None)
    monkeypatch.setattr(
        trial_fills, "record_fill_interval_evidence",
        lambda conn, *, deployment, plan_id, interval: recorded.append(
            (conn, deployment, plan_id, interval))
        or {"evidence_sha256": "f" * 64})

    result = run(paper_finalization._record_due_fill_interval_or_refuse(  # noqa: SLF001
        conn, broker=broker, deployment=DEPLOYMENT, plan=PLAN,
        session=SESSION, required_through=REQUIRED_THROUGH))

    assert result == {"evidence_sha256": "f" * 64}
    assert broker.calls == [(SESSION, BASELINE_AT)]
    assert recorded == [(conn, DEPLOYMENT, PLAN.plan_id, interval)]


@pytest.mark.parametrize("baseline", [
    None,
    broker_cash.PlanCashBaseline(
        plan_id=PLAN.plan_id, broker="alpaca", account_id="PA-1",
        decision_session=DECISION, processed_through=BASELINE_AT,
        balance_total=Decimal(0), last_activity_id="cash-before-plan"),
], ids=["missing", "legacy-identity"])
def test_fill_interval_refuses_missing_or_non_authoritative_cash_baseline(
        monkeypatch, baseline):
    broker = FillBroker(result=fill_interval())
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: baseline)

    with pytest.raises(
            paper.PaperActivationRefused,
            match="authoritative plan cash baseline|not authoritative"):
        run(paper_finalization._record_due_fill_interval_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, plan=PLAN,
            session=SESSION, required_through=REQUIRED_THROUGH))

    assert broker.calls == []


@pytest.mark.parametrize(
    ("error", "refusal", "message"),
    [
        (RuntimeError("ledger not final"), paper.PaperRetryableRefused,
         "temporarily unavailable"),
        (MalformedBrokerEvidence("duplicate native id"),
         paper.PaperActivationRefused, "malformed or contradictory"),
    ],
)
def test_fill_interval_transport_vs_malformed_classification(
        monkeypatch, error, refusal, message):
    broker = FillBroker(error=error)
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: BASELINE)
    monkeypatch.setattr(
        trial_fills, "record_fill_interval_evidence",
        lambda *_args, **_kwargs: pytest.fail(
            "failed fill interval was recorded"))

    with pytest.raises(refusal, match=message):
        run(paper_finalization._record_due_fill_interval_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, plan=PLAN,
            session=SESSION, required_through=REQUIRED_THROUGH))


@pytest.mark.parametrize(
    ("interval", "message"),
    [
        (fill_interval(interval_start=BASELINE_AT + timedelta(seconds=1)),
         "does not begin"),
        (fill_interval(processed_through=REQUIRED_THROUGH - timedelta(seconds=1)),
         "does not cover"),
    ],
    ids=["shifted-lower-bound", "short-upper-bound"],
)
def test_fill_interval_rejects_shifted_or_short_accepted_payload_before_write(
        monkeypatch, interval, message):
    broker = FillBroker(result=interval)
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: BASELINE)
    monkeypatch.setattr(
        trial_fills, "record_fill_interval_evidence",
        lambda *_args, **_kwargs: pytest.fail(
            "invalid accepted fill interval poisoned durable history"))

    with pytest.raises(paper.PaperActivationRefused, match=message):
        run(paper_finalization._record_due_fill_interval_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, plan=PLAN,
            session=SESSION, required_through=REQUIRED_THROUGH))


def test_fill_interval_historical_revision_is_a_hard_refusal(monkeypatch):
    broker = FillBroker(result=fill_interval())
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: BASELINE)

    def refuse(*_args, **_kwargs):
        raise trial_fills.TrialFillIntervalHistoricalRevision(
            "historical fill set changed")

    monkeypatch.setattr(
        trial_fills, "record_fill_interval_evidence", refuse)

    with pytest.raises(
            paper.PaperActivationRefused, match="immutable acceptance contract"):
        run(paper_finalization._record_due_fill_interval_or_refuse(  # noqa: SLF001
            object(), broker=broker, deployment=DEPLOYMENT, plan=PLAN,
            session=SESSION, required_through=REQUIRED_THROUGH))


def test_offsetting_cash_activity_identity_blocks_immutable_plan(monkeypatch):
    now = datetime(2026, 8, 20, 21, tzinfo=timezone.utc)
    plan = SimpleNamespace(
        plan_id="plan-cash", broker="alpaca", broker_account_id="PA-1",
        decision_session=date(2026, 8, 19), account_cash=Decimal("100"))
    account = BrokerAccountSnapshot(
        identity=BrokerAccountIdentity("alpaca", "PA-1"),
        equity=Decimal("100"), cash=Decimal("100"), status="ACTIVE")
    observation = BrokerObservation(observed_at=now)
    activity = broker_cash.CashActivityState(
        broker="alpaca", account_id="PA-1", processed_through=now,
        last_activity_id="cash-after", last_event_id="event-after",
        balance_total=Decimal("0"),
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    baseline = broker_cash.PlanCashBaseline(
        plan_id=plan.plan_id, broker="alpaca", account_id="PA-1",
        decision_session=plan.decision_session, processed_through=now,
        balance_total=Decimal("0"), last_activity_id="cash-before",
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: baseline)

    with pytest.raises(paper.PaperActivationRefused, match="net=0"):
        paper_cash._cash_authority_or_refuse(  # noqa: SLF001
            object(), plan=plan, deployment=DEPLOYMENT, account=account,
            observation=observation, activity_state=activity)

    # Preparation may observe the changed set only to build a successor plan;
    # it never rewrites the current plan's immutable cash economics.
    paper_cash._cash_authority_or_refuse(  # noqa: SLF001
        object(), plan=plan, deployment=DEPLOYMENT, account=account,
        observation=observation, activity_state=activity,
        permit_new_activity=True)


def test_authoritative_cash_baseline_refuses_downgraded_current_provenance(
        monkeypatch):
    now = datetime(2026, 8, 20, 21, tzinfo=timezone.utc)
    plan = SimpleNamespace(
        plan_id="plan-cash-scheme", broker="alpaca",
        broker_account_id="PA-1", decision_session=DECISION,
        account_cash=Decimal("100"))
    account = BrokerAccountSnapshot(
        identity=BrokerAccountIdentity("alpaca", "PA-1"),
        equity=Decimal("100"), cash=Decimal("100"), status="ACTIVE")
    observation = BrokerObservation(observed_at=now)
    downgraded = broker_cash.CashActivityState(
        broker="alpaca", account_id="PA-1", processed_through=now,
        last_activity_id="cash-before", balance_total=Decimal(0),
        activity_identity_scheme=None)
    baseline = broker_cash.PlanCashBaseline(
        plan_id=plan.plan_id, broker="alpaca", account_id="PA-1",
        decision_session=DECISION, processed_through=now,
        balance_total=Decimal(0), last_activity_id="cash-before",
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: baseline)

    with pytest.raises(
            paper.PaperActivationRefused, match="activity identity scheme"):
        paper_cash._cash_authority_or_refuse(  # noqa: SLF001
            object(), plan=plan, deployment=DEPLOYMENT, account=account,
            observation=observation, activity_state=downgraded,
            permit_new_activity=True)


def test_due_cycle_finalization_uses_old_plan_effective_session_everywhere(
        monkeypatch):
    """A delayed caller cannot relabel prior-cycle evidence as today's date."""
    conn = object()
    reconciliation = SimpleNamespace(
        observation_id=73,
        observation=SimpleNamespace(observed_at=REQUIRED_THROUGH))
    observed_at = REQUIRED_THROUGH + timedelta(minutes=1)
    started_at = observed_at - timedelta(seconds=1)
    verified_at = observed_at + timedelta(minutes=2)
    calls = []

    def due(_conn, *, plan_id, effective_session):
        calls.append(("query", _conn, plan_id, effective_session))
        return "cycle-old"

    async def close(_conn, *, broker, deployment, session):
        calls.append(("close", _conn, broker, deployment, session))
        return {}

    async def fills(
            _conn, *, broker, deployment, plan, session, required_through):
        calls.append((
            "fills", _conn, broker, deployment, plan, session,
            required_through))
        return {}

    certified_target_actions = lambda security_id, since=None: (  # noqa: E731
        Decimal(2) if security_id == "SEC-A" else None)
    observation_target_actions = lambda security_id, since=None: (  # noqa: E731
        Decimal(2 if since == SESSION else 4)
        if security_id == "SEC-A" else None)
    target_projection = SimpleNamespace(
        action_multipliers={"SEC-A": Decimal(2)},
        target_basket={"SEC-A": Decimal(10)}, through_session=SESSION)

    def account_evidence(_conn, **kwargs):
        calls.append(("account", _conn, kwargs))
        return {}

    def verification(_conn, **kwargs):
        calls.append(("verification", _conn, kwargs))
        return {"status": "VERIFIED"}

    monkeypatch.setattr(trial, "due_succeeded_cycle_id", due)
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: BASELINE)
    monkeypatch.setattr(
        broker_cash.PlanCashBaseline,
        "close_cash_finality_authoritative", property(lambda _self: True))
    monkeypatch.setattr(paper_finalization, "_record_due_close_nav_or_refuse", close)
    monkeypatch.setattr(paper_finalization, "_record_due_fill_interval_or_refuse", fills)
    monkeypatch.setattr(
        paper_finalization.target_reprojection, "load_projection",
        lambda *_args, **_kwargs: target_projection)
    monkeypatch.setattr(
        paper_finalization.target_reprojection, "assert_projection",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(trial, "record_account_evidence", account_evidence)
    monkeypatch.setattr(trial, "record_cycle_verification", verification)
    broker = object()
    account = object()
    activity = object()

    result = run(paper_finalization._finalize_due_succeeded_cycle_or_refuse(  # noqa: SLF001
        conn, broker=broker, deployment=DEPLOYMENT, plan=PLAN,
        reconciliation=reconciliation, account=account,
        activity_state=activity, observation_started_at=started_at,
        observed_at=observed_at,
        target_actions=certified_target_actions,
        observation_target_actions=observation_target_actions,
        clock=lambda: verified_at))

    assert result == {"status": "VERIFIED"}
    assert calls[0] == ("query", conn, PLAN.plan_id, SESSION)
    assert calls[1] == ("close", conn, broker, DEPLOYMENT, SESSION)
    assert calls[2] == (
        "fills", conn, broker, DEPLOYMENT, PLAN, SESSION, observed_at)
    assert calls[3][0:2] == ("account", conn)
    assert calls[3][2]["session"] == SESSION
    assert calls[3][2]["target_projection"] is target_projection
    assert calls[3][2]["observation_post_projection_actions"] == {
        "SEC-A": Decimal(2)}
    assert calls[4] == (
        "verification", conn,
        {"cycle_id": "cycle-old", "observation_id": 73,
         "now": verified_at})


def test_due_cycle_without_close_cash_finality_stays_pending_before_writes(
        monkeypatch):
    reconciliation = SimpleNamespace(
        observation_id=73,
        observation=SimpleNamespace(observed_at=REQUIRED_THROUGH))
    monkeypatch.setattr(
        trial, "due_succeeded_cycle_id", lambda *_args, **_kwargs: "cycle-old")
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: BASELINE)
    monkeypatch.setattr(
        paper_finalization, "_record_due_close_nav_or_refuse",
        lambda *_args, **_kwargs: pytest.fail(
            "close source was written before cash finality existed"))
    monkeypatch.setattr(
        paper_finalization, "_record_due_fill_interval_or_refuse",
        lambda *_args, **_kwargs: pytest.fail(
            "fill source was written before cash finality existed"))
    monkeypatch.setattr(
        trial, "record_account_evidence",
        lambda *_args, **_kwargs: pytest.fail(
            "account evidence was frozen before cash finality existed"))
    monkeypatch.setattr(
        trial, "record_cycle_verification",
        lambda *_args, **_kwargs: pytest.fail(
            "verdict was frozen before cash finality existed"))

    with pytest.raises(
            paper.PaperRetryableRefused,
            match="cash source has no accepted close-interval finality"):
        run(paper_finalization._finalize_due_succeeded_cycle_or_refuse(  # noqa: SLF001
            object(), broker=object(), deployment=DEPLOYMENT, plan=PLAN,
            reconciliation=reconciliation, account=object(),
            activity_state=object(), observation_started_at=BASELINE_AT,
            observed_at=REQUIRED_THROUGH, target_actions=lambda _key: None,
            observation_target_actions=lambda _key: None,
            clock=lambda: PROCESSED_THROUGH))


def test_manual_delayed_preparation_cannot_bypass_due_cycle_gate(monkeypatch):
    """No PREPARE automation grant is needed to owe the old cycle verdict."""
    import sentinel.handover as handover

    through = date(2026, 8, 21)
    now = datetime(2026, 8, 21, 21, tzinfo=timezone.utc)
    conn = object()
    binding = SimpleNamespace(identity=DEPLOYMENT)
    observation = BrokerObservation(observed_at=now)
    rec = SimpleNamespace(observation=observation, observation_id=81)
    account = object()
    broker = SimpleNamespace()
    aged_actions = object()
    target_actions = lambda _security_id: Decimal(2)  # noqa: E731
    reconciled_actions = []

    async def account_snapshot():
        return account

    async def reconcile(**kwargs):
        reconciled_actions.append(kwargs["actions"])
        return rec

    reached = []

    async def finalize(_conn, **kwargs):
        reached.append((_conn, kwargs))
        raise paper.PaperActivationRefused("due-cycle gate reached")

    broker.account_snapshot = account_snapshot
    monkeypatch.setattr(paper_preparation, "assert_paper_url", lambda _url: None)
    monkeypatch.setattr(
        paper_preparation, "_require_certified_paper_broker", lambda _broker: None)
    monkeypatch.setattr(
        paper_preparation.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(
        paper_preparation.journal, "writer_lock", lambda _conn: nullcontext())
    monkeypatch.setattr(
        handover, "assert_no_legacy_path", lambda _conn: binding)
    monkeypatch.setattr(
        paper_preparation, "load_rollout_state",
        lambda _conn: SimpleNamespace(
            mode=paper_preparation.RolloutMode.PINNED_1_00, version=1,
            certificate_sha256=None))
    monkeypatch.setattr(
        paper_preparation.publication, "pinned",
        lambda _conn, commit=False: nullcontext(SimpleNamespace(version=7)))
    monkeypatch.setattr(
        paper_preparation, "_readiness_or_refuse", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        paper_preparation.calendar, "latest_closed_session",
        lambda _now: through.isoformat())
    monkeypatch.setattr(
        paper_preparation.feed_store, "latest_visible_session",
        lambda _conn: through.isoformat())
    monkeypatch.setattr(
        paper_preparation, "require_current_authority",
        lambda *_args, **_kwargs: SimpleNamespace(
            certificate_sha256=None,
            authorization_mode="PAPER_OBSERVATION_ONLY"))
    monkeypatch.setattr(
        paper_preparation, "_guard_broker", lambda **_kwargs: broker)
    monkeypatch.setattr(paper_preparation.catchup, "resume_state", lambda _conn: None)
    monkeypatch.setattr(
        paper_preparation.catchup, "last_processed_session", lambda _conn: None)
    monkeypatch.setattr(
        paper_preparation.journal, "latest_plan", lambda _conn: PLAN)
    monkeypatch.setattr(
        paper_preparation.trial, "due_succeeded_cycle_id", lambda *_args, **_kwargs: "old")
    monkeypatch.setattr(
        paper_preparation, "_assert_deterministic_plan_id", lambda _plan: None)
    monkeypatch.setattr(
        paper_preparation, "_target_action_lookup",
        lambda *_args, **_kwargs: target_actions)
    monkeypatch.setattr(
        paper_preparation.journal, "load_commands", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        paper_preparation, "_preopen_views_or_none",
        lambda _conn, **kwargs: (
            object(), aged_actions, kwargs["target_actions"]))
    monkeypatch.setattr(
        paper_preparation.preopen_authority, "overlay_actions",
        lambda actions, _authority: actions)
    monkeypatch.setattr(
        paper_preparation, "_revalidate_preopen_authority_or_refuse",
        lambda **_kwargs: None)
    monkeypatch.setattr(paper.reconciliation, "reconcile", reconcile)
    monkeypatch.setattr(
        paper_preparation, "_clean_or_refuse", lambda _result, **_kwargs: observation)
    monkeypatch.setattr(
        paper_preparation, "_account_or_refuse", lambda *_args, **_kwargs: None)

    async def cash_state(*_args, **_kwargs):
        return None

    monkeypatch.setattr(paper_preparation, "_broker_cash_state_or_refuse", cash_state)
    monkeypatch.setattr(
        paper_preparation, "_cash_authority_or_refuse", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        paper_preparation, "_finalize_due_succeeded_cycle_or_refuse", finalize)

    with pytest.raises(
            paper.PaperActivationRefused, match="due-cycle gate reached"):
        run(paper.prepare_paper_plan(
            conn=conn, broker=broker, base_url="paper-test",
            through=through, expected_account="PA-1",
            controller_config=object(), strategy_identity={"strategy": "test"},
            now_et=now, automation_grant=None))

    assert len(reached) == 1
    assert reconciled_actions == [aged_actions]
    assert reached[0][0] is conn
    assert reached[0][1]["plan"] is PLAN
    assert reached[0][1]["target_actions"] is target_actions
    assert reached[0][1]["observation_target_actions"] is target_actions
    assert PLAN.effective_session == SESSION
    assert through != PLAN.effective_session


def test_missing_plan_cash_baseline_is_never_backfilled_from_current_state(
        monkeypatch):
    now = datetime(2026, 8, 20, 21, tzinfo=timezone.utc)
    plan = SimpleNamespace(
        plan_id="legacy-plan-without-boundary", broker="alpaca",
        broker_account_id="PA-1", decision_session=DECISION,
        account_cash=Decimal("100"))
    account = BrokerAccountSnapshot(
        identity=BrokerAccountIdentity("alpaca", "PA-1"),
        equity=Decimal("100"), cash=Decimal("100"), status="ACTIVE")
    observation = BrokerObservation(observed_at=now)
    current = broker_cash.CashActivityState(
        broker="alpaca", account_id="PA-1", processed_through=now,
        # This can be the last of offsetting post-plan events even though the
        # cash total and live cash returned to their old values.
        last_activity_id="offsetting-event-after-plan",
        last_event_id="event-after-plan", balance_total=Decimal(0),
        activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        broker_cash, "load_plan_baseline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        broker_cash, "record_plan_baseline",
        lambda *_args, **_kwargs: pytest.fail(
            "current activity was stamped retroactively onto an old plan"))

    with pytest.raises(
            paper.PaperActivationRefused, match="cannot be backfilled"):
        paper_cash._cash_authority_or_refuse(  # noqa: SLF001
            object(), plan=plan, deployment=DEPLOYMENT, account=account,
            observation=observation, activity_state=current,
            permit_new_activity=True)
