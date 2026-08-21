"""Immutable financial evidence for the autonomous Alpaca paper trial.

The panel is a reader, never a verifier.  Guarded execution captures account
evidence beside a clean broker reconciliation; the persistent automation loop
then appends one versioned verdict after the cycle transition is durable.

Physical storage deliberately follows ``execution.broker_cash``: the strict
behavioural catalog already owns ``sentinel_processed_sessions`` as a typed,
namespaced JSON state store.  Adding an unreviewed runtime table would make
normal startup either mutate or reject the catalog.  See the design contract in
``docs/sentinel-trial-verification.md``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from sentinel.execution.broker_cash import CashActivityState
    from sentinel.execution.contract import BrokerAccountSnapshot
    from sentinel.execution.identity import DeploymentIdentity


ACCOUNT_PREFIX = "trial-account:v1:"
VERIFICATION_PREFIX = "trial-verification:v1:"
ACCOUNT_KIND = "sentinel-trial-account/v1"
VERIFICATION_KIND = "sentinel-trial-verification/v1"
FINANCIAL_TOLERANCE = Decimal("1.00")
SHARE_TOLERANCE = Decimal("0.000001")
DIVIDEND_EVIDENCE_TOLERANCE = Decimal("0.000001")
MAXIMUM_CLOCK_SKEW_SECONDS = 5


class TrialEvidenceRefused(RuntimeError):
    """Trial evidence is malformed, contradictory, or changed after writing."""


def _canonical(value: Mapping) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _sha(value: Mapping) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _utc(value, *, where: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise TrialEvidenceRefused(f"{where} is not a timestamp") from exc
    if parsed.tzinfo is None:
        raise TrialEvidenceRefused(f"{where} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _decimal(value, *, where: str, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise TrialEvidenceRefused(f"{where} is not a decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TrialEvidenceRefused(f"{where} is not a decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise TrialEvidenceRefused(f"{where} is not a usable decimal")
    return result


def _mapping(value, *, where: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise TrialEvidenceRefused(f"{where} is not JSON") from exc
    if not isinstance(value, Mapping):
        raise TrialEvidenceRefused(f"{where} is not an object")
    return dict(value)


def _stored(conn, name: str) -> tuple[date, dict] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (name,))
        row = cur.fetchone()
    if row is None:
        return None
    session = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
    return session, _mapping(row[1], where=name)


def _insert_immutable(conn, *, name: str, session: date,
                      state: Mapping) -> dict:
    candidate = dict(state)
    existing = _stored(conn, name)
    if existing is not None:
        if existing != (session, candidate):
            raise TrialEvidenceRefused(
                f"immutable trial evidence {name!r} changed: "
                f"stored={existing}, attempted={(session, candidate)}")
        return candidate
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
            (name, session.isoformat(), _canonical(candidate)))
    conn.commit()
    return candidate


def record_account_evidence(
        conn, *, session: date, observation_id: int,
        observed_at: datetime, snapshot: "BrokerAccountSnapshot",
        deployment: "DeploymentIdentity", reconciliation,
        activity_state: "CashActivityState | None",
        plan_target: Mapping[str, object],
        target_actions: Mapping[str, object]) -> dict:
    """Bind actual account equity/cash to one clean reconciliation row."""
    if observation_id < 1:
        raise TrialEvidenceRefused("reconciliation observation id is invalid")
    from sentinel.execution.states import RuntimeState
    if (reconciliation.runtime_state is not RuntimeState.RUNNING
            or not reconciliation.clean
            or reconciliation.observation is None
            or not reconciliation.observation.is_complete
            or reconciliation.observation_id != observation_id):
        raise TrialEvidenceRefused(
            "account evidence requires an exact COMPLETE RUNNING clean reconciliation")
    if not deployment.matches_account(snapshot.identity):
        raise TrialEvidenceRefused("account evidence belongs to another binding")
    stamp = _utc(observed_at, where="account evidence observed_at")
    equity = _decimal(snapshot.equity, where="actual account equity", positive=True)
    cash = _decimal(snapshot.cash, where="actual account cash")
    durable_target = _quantity_map(plan_target, where="plan target")
    exact_target_actions = _quantity_map(
        target_actions, where="target corporate-action multiplier")
    effective_target = _age_plan_target(durable_target, exact_target_actions)
    activity = None
    if activity_state is not None:
        if (activity_state.broker != deployment.broker
                or activity_state.account_id != deployment.broker_account_id):
            raise TrialEvidenceRefused("cash activity cursor belongs to another account")
        activity = {
            "processed_through": activity_state.processed_through.isoformat(),
            "last_activity_id": activity_state.last_activity_id,
            "last_event_id": activity_state.last_event_id,
            "balance_total": str(activity_state.balance_total),
        }
    evidence = {
        "kind": ACCOUNT_KIND,
        "session": session.isoformat(),
        "observation_id": observation_id,
        "observed_at": stamp.isoformat(),
        "deployment": {
            "deployment_id": deployment.deployment_id,
            "broker": deployment.broker,
            "broker_account_id": deployment.broker_account_id,
            "takeover_epoch": deployment.takeover_epoch,
        },
        "account": {
            "equity": str(equity), "cash": str(cash),
            "status": snapshot.status,
            "trading_blocked": snapshot.trading_blocked,
            "account_blocked": snapshot.account_blocked,
            "trade_suspended_by_user": snapshot.trade_suspended_by_user,
        },
        "reconciliation": {
            "runtime_state": reconciliation.runtime_state.value,
            "completeness": reconciliation.observation.completeness.value,
            "plan_target": {
                key: str(value) for key, value in sorted(durable_target.items())},
            "target": {
                key: str(value) for key, value in sorted(effective_target.items())},
            "target_corporate_actions": {
                key: str(value) for key, value in
                sorted(exact_target_actions.items())},
            "expected": {
                key: str(value) for key, value in
                sorted(reconciliation.expected.items())},
            "corporate_actions": {
                key: str(value) for key, value in
                sorted(reconciliation.corporate_actions.items())},
        },
        "cash_activity": activity,
    }
    evidence["evidence_sha256"] = _sha(evidence)
    return _insert_immutable(
        conn, name=f"{ACCOUNT_PREFIX}{observation_id}", session=session,
        state=evidence)


def load_account_evidence(conn, observation_id: int) -> dict | None:
    row = _stored(conn, f"{ACCOUNT_PREFIX}{observation_id}")
    if row is None:
        return None
    session, evidence = row
    digest = evidence.pop("evidence_sha256", None)
    if (evidence.get("kind") != ACCOUNT_KIND
            or evidence.get("session") != session.isoformat()
            or digest != _sha(evidence)):
        raise TrialEvidenceRefused("trial account evidence fingerprint is corrupt")
    evidence["evidence_sha256"] = digest
    return evidence


def _reason(reasons: list[str], condition: bool, code: str) -> bool:
    if not condition:
        reasons.append(code)
        return False
    return True


def _quantity_map(value, *, where: str) -> dict[str, Decimal]:
    raw = _mapping(value, where=where)
    return {
        str(key): _decimal(quantity, where=f"{where} {key}")
        for key, quantity in raw.items()
    }


def _age_plan_target(plan_target: Mapping[str, object],
                     corporate_actions: Mapping[str, object]
                     ) -> dict[str, Decimal]:
    """Age an immutable share basket through supported reconciliation actions."""
    target = _quantity_map(plan_target, where="plan target")
    actions = _quantity_map(
        corporate_actions, where="corporate-action multiplier")
    unknown = set(actions) - set(target)
    if unknown:
        raise TrialEvidenceRefused(
            f"corporate actions name securities outside plan target: {sorted(unknown)}")
    for security_id, multiplier in actions.items():
        if multiplier <= 0:
            raise TrialEvidenceRefused(
                f"corporate-action multiplier {security_id} is not positive")
        target[security_id] *= multiplier
    return target


def _expected_paper_dividends(
        state, decision_session: date, previous: Mapping | None) -> list[dict]:
    """Project causal Wealth Core dividend entitlements into trial evidence.

    Wealth Core's hashed ledger supplies the security and per-share source
    evidence, but its shares belong to the full shadow.  Recover the scaled
    paper entitlement by reversing the decision session's signed fills from
    the immediately preceding immutable closing paper position.

    This helper is evidence-only.  Its output is never added to broker cash,
    NAV, positions, fills, orders, or target sizing.
    """
    ledger = _mapping(getattr(state, "ledger", None),
                      where="canonical Wealth Core ledger")
    events = ledger.get("events")
    if not isinstance(events, list):
        raise TrialEvidenceRefused(
            "canonical Wealth Core ledger events are not an array")
    wanted = decision_session.isoformat()
    source: list[dict] = []
    for index, raw in enumerate(events):
        event = _mapping(raw, where=f"Wealth Core ledger event {index}")
        if (event.get("event_type") != "DIVIDEND_ACCRUED"
                or event.get("session") != wanted):
            continue
        security_id = str(event.get("security_id") or "").strip()
        ticker = str(event.get("ticker") or "").strip()
        if not security_id or not ticker:
            raise TrialEvidenceRefused(
                f"dividend entitlement {index} has no security identity")
        detail = _mapping(
            event.get("detail"), where=f"dividend entitlement {index} detail")
        shares = _decimal(
            detail.get("shares"), where=f"dividend entitlement {index} shares",
            positive=True)
        per_share = _decimal(
            event.get("price"), where=f"dividend entitlement {index} per-share",
            positive=True)
        amount = _decimal(
            detail.get("amount"), where=f"dividend entitlement {index} amount",
            positive=True)
        try:
            due_in = int(detail.get("due_in"))
        except (TypeError, ValueError) as exc:
            raise TrialEvidenceRefused(
                f"dividend entitlement {index} has invalid settlement lag") from exc
        if due_in < 0:
            raise TrialEvidenceRefused(
                f"dividend entitlement {index} has negative settlement lag")
        if abs(amount - shares * per_share) > DIVIDEND_EVIDENCE_TOLERANCE:
            raise TrialEvidenceRefused(
                f"dividend entitlement {index} amount disagrees with shares "
                "times per-share amount")
        source.append({
            "security_id": security_id,
            "ticker": ticker,
            "accrued_session": wanted,
            "shadow_shares": shares,
            "per_share": str(per_share),
            "shadow_amount": str(amount),
            "settlement_lag_sessions": due_in,
        })
    if not source:
        return []
    prior = _mapping(previous, where="preceding trial verification")
    if (prior.get("session") != wanted
            or prior.get("verdict") not in {"VERIFIED", "NOT_VERIFIED"}):
        raise TrialEvidenceRefused(
            "paper dividend entitlement lacks the preceding session evidence")
    allowed_prior_reasons = {
        "ALPACA_PAPER_DIVIDEND_UNSUPPORTED", "VERIFICATION_GAP"}
    if set(prior.get("reason_codes") or ()) - allowed_prior_reasons:
        raise TrialEvidenceRefused(
            "preceding paper book is not clean enough to prove dividend entitlement")
    reconciliation = _mapping(
        prior.get("reconciliation"), where="preceding reconciliation")
    positions = _quantity_map(
        reconciliation.get("positions") or {}, where="preceding positions")
    pre_open = dict(positions)
    commands = prior.get("commands")
    if not isinstance(commands, list):
        raise TrialEvidenceRefused("preceding commands are not an array")
    seen_commands: set[str] = set()
    for index, raw in enumerate(commands):
        command = _mapping(raw, where=f"preceding command {index}")
        client_key = str(command.get("client_key") or "").strip()
        security_id = str(command.get("security_id") or "").strip()
        side = str(command.get("side") or "").upper()
        if (not client_key or client_key in seen_commands or not security_id
                or side not in {"BUY", "SELL"}):
            raise TrialEvidenceRefused(
                f"preceding command {index} has invalid identity or side")
        seen_commands.add(client_key)
        filled = _decimal(
            command.get("filled_quantity"),
            where=f"preceding command {index} filled quantity")
        if filled < 0:
            raise TrialEvidenceRefused(
                f"preceding command {index} has negative filled quantity")
        opening = pre_open.get(security_id, Decimal(0))
        pre_open[security_id] = (
            opening - filled if side == "BUY" else opening + filled)
    if any(quantity < 0 for quantity in pre_open.values()):
        raise TrialEvidenceRefused(
            "signed fills imply a negative pre-open paper holding")

    expected: list[dict] = []
    for item in source:
        paper_shares = pre_open.get(item["security_id"], Decimal(0))
        if paper_shares == 0:
            continue
        per_share = _decimal(
            item["per_share"], where="paper dividend per-share", positive=True)
        expected.append({
            **item,
            "shadow_shares": str(item["shadow_shares"]),
            "shares": str(paper_shares),
            "amount": str(paper_shares * per_share),
        })
    return sorted(
        expected,
        key=lambda row: (
            row["security_id"], row["ticker"], row["amount"], row["shares"]))


def _performance_attribution(*, opening: Decimal | None,
                             ending: Decimal | None,
                             external: Decimal,
                             prior_cumulative_factor: Decimal = Decimal(1)
                             ) -> tuple[Decimal | None, Decimal | None,
                                        Decimal, Decimal | None]:
    """Return P&L and an exact no-flow TWR interval.

    P&L can remove external capital without knowing when it arrived.  A return
    cannot: without NAV marks at each flow boundary, assigning a denominator is
    an estimate.  The caller therefore refuses financial green and this helper
    emits no percentage whenever external capital crossed the account.
    """
    if opening is None or ending is None:
        return None, None, prior_cumulative_factor, None
    strategy_pl = ending - opening - external
    if external != 0:
        return strategy_pl, None, prior_cumulative_factor, None
    daily_return = ending / opening - Decimal(1)
    cumulative_factor = prior_cumulative_factor * (Decimal(1) + daily_return)
    return (strategy_pl, daily_return, cumulative_factor,
            cumulative_factor - Decimal(1))


def _read_state(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state,updated_at FROM sentinel_processed_sessions"
            " WHERE cursor_name='catchup'")
        row = cur.fetchone()
    if row is None or row[1] is None:
        return None, None, None
    from sentinel.core.production import SessionState
    return (SessionState.from_dict(_mapping(row[1], where="canonical state")),
            row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0])),
            _utc(row[2], where="canonical state updated_at"))


def _read_binding(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT deployment_id,broker,broker_account_id,takeover_epoch,"
            " ownership_state FROM sentinel_account_binding WHERE id=1")
        row = cur.fetchone()
    if row is None:
        return None
    return {"deployment_id": str(row[0]), "broker": str(row[1]),
            "broker_account_id": str(row[2]), "takeover_epoch": int(row[3]),
            "ownership_state": str(row[4])}


def _read_observation(conn, observation_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT observed_at,completeness,positions,orders,runtime_state"
            " FROM sentinel_observations WHERE seq=%s", (observation_id,))
        row = cur.fetchone()
    if row is None:
        return None
    positions = _mapping(row[2], where="broker positions")
    orders = row[3] if isinstance(row[3], list) else json.loads(row[3] or "[]")
    if not isinstance(orders, list):
        raise TrialEvidenceRefused("broker orders are not an array")
    return {"observed_at": _utc(row[0], where="broker observation"),
            "completeness": str(row[1]), "positions": positions,
            "orders": orders, "runtime_state": str(row[4] or "")}


def _read_readiness(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_id,computed_at,ready,checks_passed,checks_total,checks"
            " FROM sentinel_readiness_snapshots"
            " ORDER BY computed_at DESC,snapshot_id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    checks = row[5] if isinstance(row[5], list) else json.loads(row[5] or "[]")
    return {"snapshot_id": int(row[0]),
            "computed_at": _utc(row[1], where="readiness snapshot"),
            "ready": bool(row[2]), "checks_passed": int(row[3]),
            "checks_total": int(row[4]), "checks": checks}


def _publication_time(conn, version: int) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT published_at FROM sentinel_corpus_publications"
            " WHERE version=%s", (version,))
        row = cur.fetchone()
    return _utc(row[0], where="publication time") if row else None


def _cash_rows(conn, session: date) -> tuple[list[dict], Decimal, Decimal]:
    from sentinel.execution import broker_cash
    with conn.cursor() as cur:
        cur.execute(
            "SELECT flow_id,amount,detail,recorded_at FROM sentinel_cash_flows"
            " WHERE session=%s ORDER BY recorded_at,flow_id", (session,))
        rows = cur.fetchall()
    result, external, internal = [], Decimal(0), Decimal(0)
    for flow_id, amount, detail, recorded_at in rows:
        value = _decimal(amount, where=f"cash flow {flow_id}")
        is_external = broker_cash.broker_flow_is_external(str(flow_id), str(detail))
        external += value if is_external else Decimal(0)
        internal += value if not is_external else Decimal(0)
        result.append({"flow_id": str(flow_id), "amount": str(value),
                       "classification": "EXTERNAL" if is_external else "INTERNAL",
                       "detail": str(detail),
                       "recorded_at": (_utc(recorded_at, where="cash flow time").isoformat()
                                       if recorded_at is not None else None)})
    return result, external, internal


def _marks(conn, session: date, positions: Mapping[str, object]) -> tuple[dict, Decimal]:
    from sentinel.feed import publication
    wanted = sorted(key for key, value in positions.items()
                    if _decimal(value, where=f"position {key}") != 0)
    if not wanted:
        return {}, Decimal(0)
    visible = publication.visible_predicate("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id,ticker,close_unadjusted FROM sentinel_bars b"
            f" WHERE b.session=%s AND b.security_id=ANY(%s) AND {visible}",
            (session, wanted))
        rows = cur.fetchall()
    found: dict[str, dict] = {}
    value = Decimal(0)
    for security_id, ticker, close in rows:
        mark = _decimal(close, where=f"mark {security_id}", positive=True)
        quantity = _decimal(positions[str(security_id)], where=f"position {security_id}")
        found[str(security_id)] = {"ticker": str(ticker), "close": str(mark)}
        value += quantity * mark
    if set(found) != set(wanted):
        missing = sorted(set(wanted) - set(found))
        raise TrialEvidenceRefused(f"missing published close marks for {missing}")
    return found, value


def _previous_verification(conn, before: date) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s AND session < %s"
            " ORDER BY session DESC LIMIT 1",
            (f"{VERIFICATION_PREFIX}%", before))
        row = cur.fetchone()
    if row is None:
        return None
    session = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
    state = _mapping(row[1], where="previous trial verification")
    return _validate_verification(session, state)


def _terminal_failure(cycle, now: datetime) -> dict:
    reasons = [f"CYCLE_{cycle.state.value}"]
    if cycle.failure_code:
        reasons.append(str(cycle.failure_code))
    return {"kind": VERIFICATION_KIND,
            "session": cycle.effective_session.isoformat(),
            "decision_session": cycle.decision_session.isoformat(),
            "verified_at": now.isoformat(), "verdict": "NOT_VERIFIED",
            "reason_codes": sorted(set(reasons)),
            "cycle": {"cycle_id": cycle.cycle_id,
                      "state": cycle.state.value,
                      "failure_detail": cycle.failure_detail}}


def build_cycle_verification(conn, *, cycle_id: str,
                             observation_id: int | None = None,
                             now: datetime | None = None) -> dict:
    """Deterministically evaluate one already-terminal automation cycle."""
    now = _utc(now or datetime.now(timezone.utc), where="verification time")
    from sentinel.automation import store as automation_store
    from sentinel.automation.model import CycleState
    from sentinel import trial_evidence
    from sentinel.core.decision import publication_fingerprint
    from sentinel.execution import journal
    from sentinel.feed import calendar, publication
    from sentinel.feed import store as feed_store
    cycle = automation_store.load_cycle(conn, cycle_id)
    terminal = {CycleState.SUCCEEDED, CycleState.MISSED_STATE_ONLY,
                CycleState.SUPERSEDED, CycleState.BLOCKED}
    if cycle.state not in terminal:
        raise TrialEvidenceRefused("trial verification requires a terminal cycle")
    if cycle.state is not CycleState.SUCCEEDED:
        return _terminal_failure(cycle, now)

    reasons: list[str] = []
    latest_allowed = now + timedelta(seconds=MAXIMUM_CLOCK_SKEW_SECONDS)
    plan = journal.load_plan(conn, cycle.plan_id) if cycle.plan_id else None
    _reason(reasons, plan is not None, "PLAN_MISSING")
    binding = _read_binding(conn)
    _reason(reasons, binding is not None, "BINDING_MISSING")
    state, cursor, state_at = _read_state(conn)
    _reason(reasons, state is not None and cursor is not None, "STATE_MISSING")
    expected_paper_dividends: list[dict] = []
    previous = (_previous_verification(conn, cycle.effective_session)
                if plan is not None else None)
    strategy_evidence = None
    if plan is not None:
        try:
            strategy_evidence = trial_evidence.load_strategy_session(
                conn, plan.decision_session.isoformat())
        except trial_evidence.TrialEvidenceConflict:
            reasons.append("STRATEGY_EVIDENCE_CORRUPT")
    _reason(reasons, strategy_evidence is not None,
            "STRATEGY_EVIDENCE_MISSING")
    reconciliation_id = observation_id
    if reconciliation_id is None:
        try:
            reconciliation_id = int(cycle.last_clean_reconciliation_id or "")
        except ValueError:
            reasons.append("CLEAN_RECONCILIATION_MISSING")
    observation = (_read_observation(conn, reconciliation_id)
                   if reconciliation_id is not None else None)
    account = (load_account_evidence(conn, reconciliation_id)
               if reconciliation_id is not None else None)
    readiness = _read_readiness(conn)
    current_publication = publication.current(conn)
    frontier = feed_store.latest_visible_session(conn)

    if plan is not None:
        _reason(reasons, plan.plan_id == cycle.plan_id, "PLAN_ID_MISMATCH")
        _reason(reasons, plan.fingerprint() == cycle.plan_fingerprint,
                "PLAN_FINGERPRINT_MISMATCH")
        _reason(reasons, plan.decision_session == cycle.decision_session
                and plan.effective_session == cycle.effective_session,
                "PLAN_SESSION_MISMATCH")
        _reason(reasons, not plan.is_superseded, "PLAN_SUPERSEDED")
        _reason(reasons, not plan.unpriced_securities, "PLAN_UNPRICED")
        _reason(reasons, plan.rollout_mode == cycle.rollout_mode
                and plan.rollout_version == cycle.rollout_version
                and plan.rollout_certificate_sha256 == cycle.certificate_sha256,
                "ROLLOUT_MISMATCH")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT plan_id FROM sentinel_execution_plans"
                " WHERE superseded_by IS NULL ORDER BY plan_id")
            current_plan_ids = [str(row[0]) for row in cur.fetchall()]
        _reason(reasons, current_plan_ids == [plan.plan_id],
                "CURRENT_PLAN_SET_MISMATCH")
    if binding is not None:
        expected_binding = {
            "deployment_id": cycle.deployment_id, "broker": cycle.broker,
            "broker_account_id": cycle.broker_account_id,
            "takeover_epoch": cycle.takeover_epoch}
        _reason(reasons, binding.get("ownership_state") == "OWNED",
                "BINDING_NOT_OWNED")
        _reason(reasons, all(binding.get(k) == v for k, v in expected_binding.items()),
                "BINDING_MISMATCH")
    if state is not None and plan is not None:
        _reason(reasons, cursor == plan.decision_session
                and state.last_processed_session == plan.decision_session.isoformat(),
                "STATE_SESSION_MISMATCH")
        _reason(reasons, state.state_hash == plan.shadow_snapshot_hash
                and state.state_hash == cycle.state_fingerprint,
                "STATE_FINGERPRINT_MISMATCH")
        _reason(reasons, state.data_version == plan.data_version,
                "STATE_PUBLICATION_MISMATCH")
        strategy_sha = hashlib.sha256(_canonical(state.strategy_identity).encode("ascii")).hexdigest()
        _reason(reasons, strategy_sha == plan.strategy_fingerprint,
                "STRATEGY_FINGERPRINT_MISMATCH")
        wealth = _mapping(state.wealth_core, where="Wealth Core state")
        _reason(reasons, not (wealth.get("unresolved_terminals") or {}),
                "TERMINAL_UNRESOLVED")
        _reason(reasons, not (wealth.get("terminal_pending_terms") or {}),
                "TERMINAL_CARRIED")
        try:
            expected_paper_dividends = _expected_paper_dividends(
                state, plan.decision_session, previous)
        except TrialEvidenceRefused:
            reasons.append("DIVIDEND_EVIDENCE_INVALID")
        if expected_paper_dividends:
            reasons.append("ALPACA_PAPER_DIVIDEND_UNSUPPORTED")
        if strategy_evidence is not None:
            _reason(reasons,
                    strategy_evidence["state_sha256"] == state.state_hash,
                    "STRATEGY_EVIDENCE_STATE_MISMATCH")
            _reason(reasons,
                    strategy_evidence["data_version"] == plan.data_version,
                    "STRATEGY_EVIDENCE_PUBLICATION_MISMATCH")
            evidence_strategy_sha = hashlib.sha256(
                _canonical(strategy_evidence["strategy_identity"])
                .encode("ascii")).hexdigest()
            _reason(reasons,
                    evidence_strategy_sha == plan.strategy_fingerprint,
                    "STRATEGY_EVIDENCE_IDENTITY_MISMATCH")
            _reason(reasons,
                    strategy_evidence["decision"] == state.last_decision,
                    "STRATEGY_EVIDENCE_DECISION_MISMATCH")
            _reason(reasons,
                    strategy_evidence["evidence"] == state.last_evidence,
                    "STRATEGY_EVIDENCE_OBSERVATION_MISMATCH")
    close_valuation = observation_id is not None
    if current_publication is None or plan is None:
        reasons.append("PUBLICATION_MISSING")
    else:
        _reason(reasons, cycle.data_version == str(plan.data_version)
                and cycle.publication_fingerprint == plan.publication_fingerprint,
                "PUBLICATION_IDENTITY_MISMATCH")
        _reason(reasons, ((current_publication.version >= plan.data_version)
                         if close_valuation else
                         (current_publication.version == plan.data_version
                          and publication_fingerprint(current_publication)
                          == plan.publication_fingerprint)),
                "VALUATION_PUBLICATION_MISMATCH")
    expected_frontier = (cycle.effective_session if close_valuation
                         else cycle.decision_session)
    _reason(reasons, str(frontier or "") == expected_frontier.isoformat(),
            "FRONTIER_SESSION_MISMATCH")
    freshness = calendar.freshness(str(frontier) if frontier else None, now)
    _reason(reasons, freshness.evaluable and freshness.sessions_behind == 0
            and not freshness.ahead, "SESSIONS_BEHIND")

    published_at = (_publication_time(conn, current_publication.version)
                    if current_publication is not None else None)
    _reason(reasons, published_at is not None
            and published_at <= latest_allowed, "PUBLICATION_FUTURE")
    if state_at is not None:
        _reason(reasons, state_at <= latest_allowed, "STATE_FUTURE")
    if cycle.completed_at is not None:
        _reason(reasons, _utc(cycle.completed_at, where="cycle completion")
                <= latest_allowed, "CYCLE_COMPLETION_FUTURE")
    if readiness is None:
        reasons.append("READINESS_MISSING")
    else:
        _reason(reasons, readiness["ready"]
                and readiness["checks_passed"] == readiness["checks_total"]
                and readiness["checks_total"] > 0,
                "READINESS_FAILED")
        _reason(reasons, published_at is not None
                and readiness["computed_at"] >= published_at,
                "READINESS_WRONG_PUBLICATION")
        _reason(reasons, readiness["computed_at"] <= latest_allowed,
                "READINESS_FUTURE")

    if observation is None:
        reasons.append("OBSERVATION_MISSING")
    else:
        _reason(reasons, observation["completeness"] == "COMPLETE",
                "OBSERVATION_INCOMPLETE")
        _reason(reasons, observation["runtime_state"] == "RUNNING",
                "RECONCILIATION_NOT_RUNNING")
        _reason(reasons, observation["observed_at"] <= latest_allowed,
                "OBSERVATION_FUTURE")
    if account is None:
        reasons.append("ACCOUNT_EVIDENCE_MISSING")
    else:
        _reason(reasons, account["session"] == cycle.effective_session.isoformat()
                and account["observation_id"] == reconciliation_id,
                "ACCOUNT_EVIDENCE_MISMATCH")
        account_at = _utc(account["observed_at"], where="account evidence")
        _reason(reasons, account_at <= latest_allowed,
                "ACCOUNT_EVIDENCE_FUTURE")
        if observation is not None:
            _reason(reasons, account_at >= observation["observed_at"],
                    "ACCOUNT_OBSERVATION_ORDER_MISMATCH")
        account_status = account.get("account") or {}
        _reason(reasons,
                str(account_status.get("status") or "").upper() == "ACTIVE"
                and not account_status.get("trading_blocked")
                and not account_status.get("account_blocked")
                and not account_status.get("trade_suspended_by_user"),
                "ACCOUNT_NOT_TRADABLE")
        account_binding = account.get("deployment") or {}
        _reason(reasons, binding is not None and all(
            account_binding.get(k) == binding.get(k)
            for k in ("deployment_id", "broker", "broker_account_id",
                      "takeover_epoch")), "ACCOUNT_BINDING_MISMATCH")

    positions = observation["positions"] if observation is not None else {}
    plan_target = ({key: str(value) for key, value in plan.target_basket.items()}
                   if plan is not None else {})
    account_reconciliation = ((account or {}).get("reconciliation") or {})
    corporate_actions = (
        account_reconciliation.get("target_corporate_actions") or {})
    reconciled_expected = account_reconciliation.get("expected") or {}
    try:
        retained_plan_target = _quantity_map(
            account_reconciliation.get("plan_target") or {},
            where="account-evidence plan target")
        current_plan_target = _quantity_map(plan_target, where="plan target")
        _reason(reasons, retained_plan_target == current_plan_target,
                "ACCOUNT_PLAN_TARGET_MISMATCH")
        effective_target = _age_plan_target(plan_target, corporate_actions)
        retained_target = _quantity_map(
            account_reconciliation.get("target") or {},
            where="account-evidence effective target")
        _reason(reasons, retained_target == effective_target,
                "ACCOUNT_EFFECTIVE_TARGET_MISMATCH")
        target = {key: str(value) for key, value in effective_target.items()}
        expected = _quantity_map(
            reconciled_expected, where="reconciled expected book")
        _reason(reasons, set(expected) == set(effective_target)
                and all(abs(expected[key] - effective_target[key])
                        <= SHARE_TOLERANCE for key in effective_target),
                "RECONCILED_TARGET_MISMATCH")
    except TrialEvidenceRefused:
        target = plan_target
        reasons.append("CORPORATE_ACTION_EVIDENCE_INVALID")
    all_securities = set(positions) | set(target)
    deltas = {key: str(_decimal(positions.get(key, 0), where=f"position {key}")
                       - _decimal(target.get(key, 0), where=f"target {key}"))
              for key in sorted(all_securities)}
    _reason(reasons, all(abs(_decimal(v, where="position delta"))
                         <= SHARE_TOLERANCE
                         for v in deltas.values()), "POSITION_MISMATCH")
    working = []
    for raw in (observation or {}).get("orders", []):
        order = _mapping(raw, where="broker order")
        if str(order.get("state") or "").upper() in {
                "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN", "PARTIALLY_FILLED",
                "CANCEL_PENDING", "NEW", "ACCEPTED", "PENDING_NEW"}:
            working.append(order)
    _reason(reasons, not working, "WORKING_OR_FOREIGN_ORDER")

    commands, fills = [], []
    if plan is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT client_key,security_id,side,quantity,state,broker_order_id,"
                " filled_quantity,filled_average_price,detail,updated_at"
                " FROM sentinel_commands WHERE plan_id=%s ORDER BY client_key",
                (plan.plan_id,))
            command_rows = cur.fetchall()
        for row in command_rows:
            commands.append({"client_key": str(row[0]), "security_id": str(row[1]),
                             "side": str(row[2]), "quantity": str(row[3]),
                             "state": str(row[4]), "broker_order_id": row[5],
                             "filled_quantity": str(row[6]),
                             "filled_average_price": (str(row[7]) if row[7] is not None else None),
                             "detail": row[8],
                             "updated_at": _utc(row[9], where="command update").isoformat()})
        _reason(reasons, not any(
            _utc(row["updated_at"], where="command update") > latest_allowed
            for row in commands), "COMMAND_TIMESTAMP_FUTURE")
        bad_states = {"PLANNED", "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN",
                      "PARTIALLY_FILLED", "CANCEL_PENDING", "REJECTED", "CANCELLED"}
        _reason(reasons, not any(row["state"] in bad_states for row in commands),
                "COMMAND_JOURNAL_NOT_CLEAN")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT f.broker_order_id,f.fill_key,f.client_key,f.quantity,f.price,"
                " f.filled_at FROM sentinel_fills f JOIN sentinel_commands c"
                " ON c.client_key=f.client_key WHERE c.plan_id=%s"
                " ORDER BY f.filled_at,f.fill_key", (plan.plan_id,))
            fill_rows = cur.fetchall()
        fills = [{"broker_order_id": str(r[0]), "fill_key": str(r[1]),
                  "client_key": str(r[2]), "quantity": str(r[3]),
                  "price": str(r[4]),
                  "filled_at": (_utc(r[5], where="fill time").isoformat()
                                if r[5] is not None else None)} for r in fill_rows]
        _reason(reasons, not any(
            row["filled_at"] is not None
            and _utc(row["filled_at"], where="fill time") > latest_allowed
            for row in fills), "FILL_TIMESTAMP_FUTURE")

    cash_rows, external, internal = _cash_rows(conn, cycle.effective_session)
    _reason(reasons, not any(
        row["recorded_at"] is not None
        and _utc(row["recorded_at"], where="cash flow time") > latest_allowed
        for row in cash_rows), "CASH_TIMESTAMP_FUTURE")
    _reason(reasons, external == 0, "EXTERNAL_FLOW_UNWEIGHTED")
    marks, securities_value = ({}, Decimal(0))
    marked_nav = residual = None
    equity = cash = None
    if account is not None:
        equity = _decimal(account["account"]["equity"],
                          where="actual account equity", positive=True)
        cash = _decimal(account["account"]["cash"], where="actual account cash")
        try:
            marks, securities_value = _marks(
                conn, cycle.effective_session, positions)
            marked_nav = cash + securities_value
            residual = equity - marked_nav
            _reason(reasons, abs(residual) <= FINANCIAL_TOLERANCE,
                    "NAV_UNEXPLAINED")
        except TrialEvidenceRefused:
            reasons.append("MARKS_MISSING")
        activity = account.get("cash_activity")
        _reason(reasons, activity is not None, "CASH_ACTIVITY_CURSOR_MISSING")
        if activity is not None:
            processed = _utc(activity.get("processed_through"),
                             where="cash activity processed-through")
            _reason(reasons, processed >= _utc(
                account["observed_at"], where="account evidence time"),
                "CASH_ACTIVITY_INCOMPLETE")
            _reason(reasons, processed <= latest_allowed,
                    "CASH_CURSOR_FUTURE")

    previous_verified = (previous is not None
                         and previous.get("verdict") == "VERIFIED")
    if previous is not None and not previous_verified:
        reasons.append("VERIFICATION_GAP")
    opening = (_decimal(previous["performance"]["ending_equity"],
                        where="previous verified equity", positive=True)
               if previous_verified else
               (plan.account_nav if plan is not None else None))
    if previous_verified:
        previous_session = date.fromisoformat(previous["session"])
        _reason(reasons,
                calendar.next_session(previous_session.isoformat())
                == cycle.effective_session.isoformat(), "VERIFICATION_GAP")
    cumulative_factor = Decimal(1)
    if previous_verified:
        cumulative_factor = Decimal(str(
            previous["performance"]["cumulative_factor"]))
    strategy_pl, daily_return, cumulative_factor, total_return = (
        _performance_attribution(
            opening=opening, ending=equity, external=external,
            prior_cumulative_factor=cumulative_factor))

    verification = {
        "kind": VERIFICATION_KIND,
        "session": cycle.effective_session.isoformat(),
        "decision_session": cycle.decision_session.isoformat(),
        "verified_at": now.isoformat(),
        "verdict": "VERIFIED" if not reasons else "NOT_VERIFIED",
        "reason_codes": sorted(set(reasons)),
        "cycle": {"cycle_id": cycle.cycle_id, "state": cycle.state.value,
                  "plan_id": cycle.plan_id,
                  "last_clean_reconciliation_id": cycle.last_clean_reconciliation_id,
                  "completed_at": (cycle.completed_at.isoformat()
                                   if cycle.completed_at else None)},
        "publication": {
            "decision_version": plan.data_version if plan else None,
            "decision_fingerprint": plan.publication_fingerprint if plan else None,
            "valuation_version": current_publication.version if current_publication else None,
            "valuation_fingerprint": (publication_fingerprint(current_publication)
                                      if current_publication else None),
            "published_at": published_at.isoformat() if published_at else None,
            "frontier": str(frontier) if frontier else None,
            "readiness": ({**readiness,
                           "computed_at": readiness["computed_at"].isoformat()}
                          if readiness else None)},
        "state": {"cursor": cursor.isoformat() if cursor else None,
                  "state_hash": state.state_hash if state else None,
                  "updated_at": state_at.isoformat() if state_at else None,
                  "strategy_evidence": ({
                      **strategy_evidence,
                      "recorded_at": _utc(
                          strategy_evidence["recorded_at"],
                          where="strategy evidence recorded_at").isoformat(),
                  } if strategy_evidence else None),
                  "session_evidence": state.last_evidence if state else None,
                  "terminal_carry_audit": (
                      (state.wealth_core or {}).get("terminal_carry_audit", {})
                      if state else None)},
        "plan": plan.to_dict() if plan else None,
        "binding": binding,
        "account_evidence": account,
        "reconciliation": {
            "observation_id": reconciliation_id,
            "observed_at": (observation["observed_at"].isoformat()
                            if observation else None),
            "completeness": observation["completeness"] if observation else None,
            "runtime_state": observation["runtime_state"] if observation else None,
            "positions": positions, "plan_target": plan_target,
            "target": target, "deltas": deltas,
            "corporate_actions": corporate_actions,
            "orders": (observation or {}).get("orders", []),
            "working_orders": working},
        "commands": commands, "fills": fills,
        "cash": {"rows": cash_rows, "external": str(external),
                 "internal": str(internal)},
        "paper_limitations": {
            "expected_dividends": expected_paper_dividends,
            "compensation_applied": False,
        },
        "marks": marks,
        "nav_attribution": {
            "marked_nav": str(marked_nav) if marked_nav is not None else None,
            "securities_value": str(securities_value),
            "unexplained": str(residual) if residual is not None else None,
            "tolerance": str(FINANCIAL_TOLERANCE)},
        "performance": {
            "opening_equity": str(opening) if opening is not None else None,
            "ending_equity": str(equity) if equity is not None else None,
            "actual_cash": str(cash) if cash is not None else None,
            "strategy_pl": str(strategy_pl) if strategy_pl is not None else None,
            "daily_return": str(daily_return) if daily_return is not None else None,
            "cumulative_factor": str(cumulative_factor),
            "total_return": str(total_return) if total_return is not None else None,
        },
    }
    return verification


def _validate_verification(session: date, state: dict) -> dict:
    candidate = dict(state)
    digest = candidate.pop("evidence_sha256", None)
    if (candidate.get("kind") != VERIFICATION_KIND
            or candidate.get("session") != session.isoformat()
            or digest != _sha(candidate)):
        raise TrialEvidenceRefused(
            f"trial verification {session} fingerprint is corrupt")
    candidate["evidence_sha256"] = digest
    return candidate


def record_cycle_verification(conn, *, cycle_id: str,
                              observation_id: int | None = None,
                              now: datetime | None = None) -> dict:
    from sentinel.automation import store as automation_store
    cycle = automation_store.load_cycle(conn, cycle_id)
    name = f"{VERIFICATION_PREFIX}{cycle.effective_session.isoformat()}"
    existing = _stored(conn, name)
    if existing is not None:
        session, state = existing
        stored = _validate_verification(session, state)
        if (stored.get("cycle") or {}).get("cycle_id") != cycle_id:
            raise TrialEvidenceRefused(
                "effective session already has another immutable trial cycle")
        return stored
    result = build_cycle_verification(
        conn, cycle_id=cycle_id, observation_id=observation_id, now=now)
    result["evidence_sha256"] = _sha(result)
    return _insert_immutable(
        conn, name=name,
        session=date.fromisoformat(result["session"]), state=result)


def due_succeeded_cycle_id(
        conn, *, plan_id: str, effective_session: date) -> str | None:
    """Return the one autonomous success owed a post-close certificate."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cycle_id FROM sentinel_automation_cycles"
            " WHERE plan_id=%s AND effective_session=%s AND state='SUCCEEDED'"
            " ORDER BY completed_at DESC,created_at DESC", (plan_id, effective_session))
        rows = cur.fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise TrialEvidenceRefused(
            "multiple succeeded automation cycles name one plan/session")
    return str(rows[0][0])


def record_due_cycle_verification(
        conn, *, plan_id: str, effective_session: date,
        observation_id: int, now: datetime | None = None) -> dict | None:
    """Finalize the succeeded prior cycle once its close evidence is durable."""
    cycle_id = due_succeeded_cycle_id(
        conn, plan_id=plan_id, effective_session=effective_session)
    if cycle_id is None:
        return None
    return record_cycle_verification(
        conn, cycle_id=cycle_id, observation_id=observation_id, now=now)


def load_verifications(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY session", (f"{VERIFICATION_PREFIX}%",))
        rows = cur.fetchall()
    result = []
    for raw_session, raw_state in rows:
        session = (raw_session if isinstance(raw_session, date)
                   else date.fromisoformat(str(raw_session)))
        state = _mapping(raw_state, where="trial verification")
        result.append(_validate_verification(session, state))
    return result


__all__ = [
    "ACCOUNT_PREFIX", "FINANCIAL_TOLERANCE", "TrialEvidenceRefused",
    "VERIFICATION_PREFIX", "build_cycle_verification",
    "due_succeeded_cycle_id",
    "load_account_evidence", "load_verifications", "record_account_evidence",
    "record_cycle_verification", "record_due_cycle_verification",
]
