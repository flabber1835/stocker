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
    from sentinel.execution.plan import ExecutionPlan
    from sentinel.execution.target_reprojection import TargetProjection


ACCOUNT_PREFIX = "trial-account:v2:"
VERIFICATION_PREFIX = "trial-verification:v3:"
ACCOUNT_KIND = "sentinel-trial-account/v2"
VERIFICATION_KIND = "sentinel-trial-verification/v3"
FINANCIAL_TOLERANCE = Decimal("1.00")
SHARE_TOLERANCE = Decimal("0.000001")
DIVIDEND_EVIDENCE_TOLERANCE = Decimal("0.000001")
MAXIMUM_CLOCK_SKEW_SECONDS = 5
LOCAL_TIMESTAMP_AUTHORITY = "LOCAL_RESPONSE_BRACKET_UNVERIFIED"


class TrialEvidenceRefused(RuntimeError):
    """Trial evidence is malformed, contradictory, or changed after writing."""


class _CloseCashUnproven(TrialEvidenceRefused):
    """The official-close cash boundary cannot be reconstructed exactly."""


class _CloseCashFinalityUnavailable(_CloseCashUnproven):
    """The cash source has not yet earned a fixed close-interval boundary."""


class _CloseBookIntervalUnproven(TrialEvidenceRefused):
    """Durable commands/fills do not prove the book through official close."""


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
        plan: "ExecutionPlan", target_projection: "TargetProjection",
        observation_post_projection_actions: Mapping[str, object],
        observation_started_at: datetime | None = None) -> dict:
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
    started = (_utc(observation_started_at,
                    where="account evidence observation_started_at")
               if observation_started_at is not None else None)
    if started is not None and started > stamp:
        raise TrialEvidenceRefused(
            "account evidence request begins after its response timestamp")
    reconciliation_started = (
        _utc(reconciliation.observation.started_at,
             where="reconciliation observation start")
        if reconciliation.observation.started_at is not None else None)
    reconciliation_observed = _utc(
        reconciliation.observation.observed_at,
        where="reconciliation observation completion")
    equity = _decimal(snapshot.equity, where="actual account equity", positive=True)
    cash = _decimal(snapshot.cash, where="actual account cash")
    from sentinel.execution import target_reprojection
    try:
        target_reprojection.assert_projection(
            conn, plan=plan, projection=target_projection,
            through_session=session)
    except target_reprojection.TargetProjectionRefused as exc:
        raise TrialEvidenceRefused(
            f"account evidence target projection is invalid: {exc}") from exc
    if target_projection.through_session != plan.effective_session:
        raise TrialEvidenceRefused(
            "account evidence target projection is not the plan's effective "
            "session projection")
    durable_target = _quantity_map(plan.target_basket, where="plan target")
    effective_target = _quantity_map(
        target_projection.target_basket, where="durable target projection")
    exact_target_actions = _quantity_map(
        target_projection.action_multipliers,
        where="target-projection corporate-action multiplier")
    exact_observation_target_actions = _quantity_map(
        observation_post_projection_actions,
        where="post-projection corporate-action multiplier")
    observation_target = _age_plan_target(
        effective_target, exact_observation_target_actions)
    projection_payload = target_projection.payload()
    activity = None
    if activity_state is not None:
        if (activity_state.broker != deployment.broker
                or activity_state.account_id != deployment.broker_account_id):
            raise TrialEvidenceRefused("cash activity cursor belongs to another account")
        activity = {
            "processed_through": activity_state.processed_through.isoformat(),
            "last_activity_id": activity_state.last_activity_id,
            "last_event_id": activity_state.last_event_id,
            "activity_identity_scheme": (
                activity_state.activity_identity_scheme),
            "balance_total": str(activity_state.balance_total),
        }
    evidence = {
        "kind": ACCOUNT_KIND,
        "session": session.isoformat(),
        "observation_id": observation_id,
        "observation_started_at": started.isoformat() if started else None,
        "observed_at": stamp.isoformat(),
        "reconciliation_started_at": (
            reconciliation_started.isoformat()
            if reconciliation_started is not None else None),
        "reconciliation_observed_at": reconciliation_observed.isoformat(),
        # Alpaca's account/positions payloads contain no broker-authenticated
        # valuation timestamp.  Local request bracketing is retained for
        # diagnostics but cannot promote itself to close authority.
        "valuation_timestamp_authority": LOCAL_TIMESTAMP_AUTHORITY,
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
            "target_projection": projection_payload,
            "target": {
                key: str(value) for key, value in sorted(effective_target.items())},
            "target_corporate_actions": {
                key: str(value) for key, value in
                sorted(exact_target_actions.items())},
            # Verification can be delayed beyond this plan's close. Retain a
            # second book aged only from the exact execution projection for
            # comparison with the later live reconciliation; the projected
            # close target above remains the only historical-close mark book.
            "observation_target": {
                key: str(value) for key, value in
                sorted(observation_target.items())},
            "observation_target_corporate_actions": {
                key: str(value) for key, value in
                sorted(exact_observation_target_actions.items())},
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


def _economic_book_equal(left: Mapping[str, Decimal],
                         right: Mapping[str, Decimal]) -> bool:
    """Compare books economically; an omitted key is an exact zero holding."""
    keys = set(left) | set(right)
    return all(
        abs(left.get(key, Decimal(0)) - right.get(key, Decimal(0)))
        <= SHARE_TOLERANCE
        for key in keys)


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


def _reverse_session_fills(
        closing_positions: Mapping[str, object], commands: object, *,
        where: str) -> dict[str, Decimal]:
    """Recover a session's pre-open actual shares from its closing book."""
    pre_open = _quantity_map(closing_positions, where=f"{where} positions")
    pre_open = dict(pre_open)
    if not isinstance(commands, list):
        raise TrialEvidenceRefused(f"{where} commands are not an array")
    seen_commands: set[str] = set()
    for index, raw in enumerate(commands):
        command = _mapping(raw, where=f"{where} command {index}")
        client_key = str(command.get("client_key") or "").strip()
        security_id = str(command.get("security_id") or "").strip()
        side = str(command.get("side") or "").upper()
        if (not client_key or client_key in seen_commands or not security_id
                or side not in {"BUY", "SELL"}):
            raise TrialEvidenceRefused(
                f"{where} command {index} has invalid identity or side")
        seen_commands.add(client_key)
        filled = _decimal(
            command.get("filled_quantity"),
            where=f"{where} command {index} filled quantity")
        if filled < 0:
            raise TrialEvidenceRefused(
                f"{where} command {index} has negative filled quantity")
        opening = pre_open.get(security_id, Decimal(0))
        pre_open[security_id] = (
            opening - filled if side == "BUY" else opening + filled)
    if any(quantity < 0 for quantity in pre_open.values()):
        raise TrialEvidenceRefused(
            "signed fills imply a negative pre-open paper holding")
    return pre_open


def _expected_effective_equity_dividends(
        conn, effective_session: date,
        closing_positions: Mapping[str, object], commands: object) -> list[dict]:
    """Read effective-session equity dividends from the published corpus.

    The state committed by the plan ends on the preceding decision session, so
    its ledger cannot witness a dividend that occurs during the interval being
    verified.  The newly published effective-session bar can: its dividend is
    already normalized onto raw/as-traded shares and remains publication-bound.
    """
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    from sentinel.core.terminal import DIVIDEND_ACTIONS
    from sentinel.feed import calendar, publication
    from stock_strategy_shared.wealth_core.sharadar_domains import (
        raw_dividend_per_share)

    wanted = effective_session.isoformat()
    pre_open = _reverse_session_fills(
        closing_positions, commands, where="effective-session")
    held = sorted(
        security_id for security_id, shares in pre_open.items()
        if shares > 0 and security_id != DEFENSIVE_SECURITY_ID)
    if not held:
        return []

    visible = publication.visible_predicate("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id,ticker,close_signal,close_unadjusted,"
            " dividend_per_share"
            " FROM sentinel_bars b WHERE session=%s"
            " AND security_id=ANY(%s) AND " + visible
            + " ORDER BY security_id", (wanted, held))
        bar_rows = cur.fetchall()
    found_security_ids = [str(row[0]) for row in bar_rows]
    if (set(found_security_ids) != set(held)
            or len(found_security_ids) != len(set(found_security_ids))):
        missing = sorted(set(held) - set(found_security_ids))
        raise TrialEvidenceRefused(
            "effective-session dividend evidence has missing or duplicate "
            "published bars for: " + ", ".join(missing or held))

    ticker_rows: dict[str, tuple[str, str, Decimal, Decimal, Decimal]] = {}
    for security_id, ticker, close_signal, close_unadjusted, amount in bar_rows:
        ticker_key = str(ticker or "").strip().upper()
        if not ticker_key or ticker_key in ticker_rows:
            raise TrialEvidenceRefused(
                "effective-session dividend evidence has an absent or "
                f"ambiguous ticker: {ticker!r}")
        signal = _decimal(
            close_signal, where=f"{ticker_key} close signal", positive=True)
        raw = _decimal(
            close_unadjusted, where=f"{ticker_key} raw close", positive=True)
        per_share = _decimal(
            amount,
            where=f"{ticker_key} effective-session dividend per-share")
        if per_share < 0:
            raise TrialEvidenceRefused(
                f"{ticker_key} effective-session dividend is negative")
        ticker_rows[ticker_key] = (
            str(security_id), str(ticker), signal, raw, per_share)

    raw_start, raw_end = calendar.action_date_window(wanted, wanted)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,action,ticker,value,source_row_id"
            " FROM sentinel_active_actions"
            " WHERE session BETWEEN %s AND %s"
            " ORDER BY session,ticker,source_row_id", (raw_start, raw_end))
        action_rows = [row for row in cur.fetchall()
                       if str(row[1] or "").lower() in DIVIDEND_ACTIONS
                       and calendar.session_on_or_after(str(row[0])) == wanted
                       and str(row[2] or "").strip().upper() in ticker_rows]
    sources: dict[str, list[str]] = {}
    reported: dict[str, Decimal] = {}
    seen_sources: set[str] = set()
    for raw_session, action, ticker, value, source_row_id in action_rows:
        ticker_key = str(ticker).strip().upper()
        identity = str(source_row_id or "").strip()
        if not identity or identity in seen_sources:
            raise TrialEvidenceRefused(
                "effective-session dividend source identities are absent or repeat")
        seen_sources.add(identity)
        amount = _decimal(
            value,
            where=f"{ticker_key} {action} {raw_session} amount",
            positive=True)
        reported[ticker_key] = reported.get(ticker_key, Decimal(0)) + amount
        sources.setdefault(ticker_key, []).append(identity)

    expected: list[dict] = []
    for ticker_key, row in sorted(ticker_rows.items()):
        security_id, ticker, close_signal, close_unadjusted, per_share = row
        source_ids = sources.get(ticker_key, [])
        reported_per_share = reported.get(ticker_key)
        if reported_per_share is None:
            if per_share == 0:
                continue
            raise TrialEvidenceRefused(
                f"{ticker} positive dividend lacks bound action evidence")
        converted = _decimal(
            raw_dividend_per_share(
                float(close_signal), float(close_unadjusted),
                float(reported_per_share)),
            where=f"{ticker} normalized dividend per-share")
        if abs(converted - per_share) > DIVIDEND_EVIDENCE_TOLERANCE:
            raise TrialEvidenceRefused(
                f"{ticker} dividend action aggregate does not match the "
                "published normalized bar")
        shares = pre_open[security_id]
        expected.append({
            "security_id": security_id,
            "ticker": ticker,
            "accrued_session": wanted,
            "shares": str(shares),
            "per_share": str(per_share),
            "amount": str(shares * per_share),
            "reported_per_share": str(reported_per_share),
            "source_row_ids": sorted(source_ids),
            "source": "PUBLISHED_NORMALISED_BAR_AND_SHARADAR_ACTIONS",
            "settlement_lag_sessions": None,
        })
    return expected


def _expected_defensive_dividends(
        conn, effective_session: date, closing_positions: Mapping[str, object],
        commands: object) -> list[dict]:
    """Project published BIL ACTIONS onto raw paper shares, evidence-only."""
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    from sentinel.core.terminal import DIVIDEND_ACTIONS
    from sentinel.feed import calendar, publication
    from stock_strategy_shared.wealth_core.sharadar_domains import (
        raw_dividend_per_share)

    wanted = effective_session.isoformat()
    raw_start, raw_end = calendar.action_date_window(wanted, wanted)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,action,value,source_row_id"
            " FROM sentinel_active_actions"
            " WHERE UPPER(ticker)='BIL' AND session BETWEEN %s AND %s"
            " ORDER BY session,source_row_id", (raw_start, raw_end))
        rows = [row for row in cur.fetchall()
                if str(row[1] or "").lower() in DIVIDEND_ACTIONS
                and calendar.session_on_or_after(str(row[0])) == wanted]
    if not rows:
        return []

    pre_open = _reverse_session_fills(
        closing_positions, commands, where="effective-session")
    shares = pre_open.get(DEFENSIVE_SECURITY_ID, Decimal(0))
    if shares == 0:
        return []

    reported = Decimal(0)
    source_rows: list[str] = []
    for raw_session, action, value, source_row_id in rows:
        reported += _decimal(
            value, where=f"BIL {action} {raw_session} amount", positive=True)
        identity = str(source_row_id or "").strip()
        if not identity:
            raise TrialEvidenceRefused(
                "BIL distribution lacks a source-row identity")
        source_rows.append(identity)
    if len(set(source_rows)) != len(source_rows):
        raise TrialEvidenceRefused("BIL distribution source identities repeat")

    visible = publication.visible_predicate("d")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close_signal,close_unadjusted"
            " FROM sentinel_defensive_bars d WHERE session=%s"
            " AND security_id=%s AND ticker='BIL' AND " + visible,
            (wanted, DEFENSIVE_SECURITY_ID))
        mark_row = cur.fetchone()
    if mark_row is None:
        raise TrialEvidenceRefused(
            "BIL distribution lacks published price-domain evidence")
    close_signal = _decimal(
        mark_row[0], where="BIL close signal", positive=True)
    close_unadjusted = _decimal(
        mark_row[1], where="BIL raw close", positive=True)
    converted = raw_dividend_per_share(
        close_signal, close_unadjusted, reported)
    per_share = _decimal(
        converted, where="BIL raw dividend per-share", positive=True)
    return [{
        "security_id": DEFENSIVE_SECURITY_ID,
        "ticker": "BIL",
        "accrued_session": wanted,
        "shares": str(shares),
        "per_share": str(per_share),
        "amount": str(shares * per_share),
        "reported_per_share": str(reported),
        "source_row_ids": sorted(source_rows),
        "source": "SHARADAR_ACTIONS",
        "settlement_lag_sessions": None,
    }]


def _performance_attribution(*, opening: Decimal | None,
                             ending: Decimal | None,
                             external: Decimal,
                             external_event_count: int = 0,
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
    if external != 0 or external_event_count:
        return strategy_pl, None, prior_cumulative_factor, None
    daily_return = ending / opening - Decimal(1)
    cumulative_factor = prior_cumulative_factor * (Decimal(1) + daily_return)
    return (strategy_pl, daily_return, cumulative_factor,
            cumulative_factor - Decimal(1))


def _reconstruct_close_cash(
        conn, *, plan, commands: list[dict], activity: Mapping | None,
        close_at: datetime, fill_interval_evidence: Mapping | None,
        required_fill_through: datetime | None) -> tuple[Decimal, list[dict]]:
    """Reconstruct official-close cash without reading a later live balance.

    The immutable plan cash is the pre-execution baseline. Exact fill rows move
    that balance. Broker cash activity may be included only when both its
    economic total and append-only native activity identity are unchanged from
    the plan's own baseline.  The identity comparison matters even when
    offsetting events net to zero. Alpaca supplies a business date rather than
    an intraday timestamp, so any post-baseline non-zero cash event is
    unassignable to the official-close boundary.
    """
    from sentinel.execution import broker_cash

    if activity is None:
        raise _CloseCashUnproven(
            "close cash has no broker activity cursor")
    try:
        baseline = broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise _CloseCashUnproven(str(exc)) from exc
    if baseline is None:
        raise _CloseCashUnproven(
            "close cash has no immutable plan baseline")
    if (baseline.broker != plan.broker
            or baseline.account_id != plan.broker_account_id
            or baseline.decision_session != plan.decision_session):
        raise _CloseCashUnproven(
            "close cash baseline belongs to another plan/account/session")
    if not baseline.activity_identity_authoritative:
        raise _CloseCashUnproven(
            "legacy close cash baseline has no append-only activity identity")
    if not baseline.close_cash_finality_authoritative:
        raise _CloseCashFinalityUnavailable(
            "close cash activity source has no accepted fixed-interval "
            "finality or publication watermark")
    if (activity.get("activity_identity_scheme")
            != broker_cash.ACTIVITY_IDENTITY_SCHEME):
        raise _CloseCashUnproven(
            "current close cash cursor has no accepted append-only activity "
            "identity scheme")
    try:
        activity_total = _decimal(
            activity.get("balance_total"), where="close cash activity total")
    except TrialEvidenceRefused as exc:
        raise _CloseCashUnproven(str(exc)) from exc
    if activity_total != baseline.balance_total:
        raise _CloseCashUnproven(
            "broker cash activity changed after the plan baseline and has no "
            "intraday close-boundary timestamp")
    if "last_activity_id" not in activity:
        raise _CloseCashUnproven(
            "close cash activity cursor has no native activity identity")
    activity_id = activity.get("last_activity_id")
    if (activity_id is not None
            and (not isinstance(activity_id, str) or not activity_id.strip())):
        raise _CloseCashUnproven(
            "close cash activity cursor has an invalid native activity identity")
    if activity_id != baseline.last_activity_id:
        raise _CloseCashUnproven(
            "broker cash activity identity changed after the plan baseline; "
            "offsetting events cannot be inferred away")

    if fill_interval_evidence is None:
        raise _CloseBookIntervalUnproven(
            "close cash has no complete account-wide fill interval evidence")
    try:
        evidence_start = _utc(
            fill_interval_evidence.get("interval_start"),
            where="account fill interval start")
        processed_through = _utc(
            fill_interval_evidence.get("processed_through"),
            where="account fill interval processed-through")
        close = _utc(close_at, where="official close")
        required_through = _utc(
            required_fill_through, where="required account fill boundary")
    except TrialEvidenceRefused as exc:
        raise _CloseBookIntervalUnproven(str(exc)) from exc
    if evidence_start != _utc(
            baseline.processed_through, where="plan cash baseline boundary"):
        raise _CloseBookIntervalUnproven(
            "account fill interval does not begin at the immutable plan "
            "cash baseline")
    if processed_through < max(close, required_through):
        raise _CloseBookIntervalUnproven(
            "account fill interval does not cover the close and later account "
            "observation")

    command_by_key = {}
    for command in commands:
        key = str(command.get("client_key") or "").strip()
        if not key or key in command_by_key:
            raise _CloseBookIntervalUnproven(
                "close cash command identity is absent or repeated")
        command_by_key[key] = command

    fill_quantity: dict[str, Decimal] = {}
    fill_notional: dict[str, Decimal] = {}
    authoritative_fills: list[dict] = []
    authoritative_economics: set[tuple[str, str, str, Decimal, Decimal,
                                       datetime]] = set()
    seen_fills: set[str] = set()
    raw_fills = fill_interval_evidence.get("fills")
    if not isinstance(raw_fills, list):
        raise _CloseBookIntervalUnproven(
            "account fill interval rows are not an array")
    for raw in raw_fills:
        if not isinstance(raw, Mapping):
            raise _CloseBookIntervalUnproven(
                "account fill interval contains a malformed row")
        fill_key = str(raw.get("activity_id") or "").strip()
        client_key = str(raw.get("client_key") or "").strip()
        if (not fill_key or fill_key in seen_fills
                or client_key not in command_by_key):
            raise _CloseBookIntervalUnproven(
                "account fill identity is absent, repeated, foreign, or "
                "off-plan")
        seen_fills.add(fill_key)
        broker_order_id = str(raw.get("broker_order_id") or "").strip()
        command_order_id = str(
            command_by_key[client_key].get("broker_order_id") or "").strip()
        if (not broker_order_id or not command_order_id
                or broker_order_id != command_order_id):
            raise _CloseBookIntervalUnproven(
                f"fill {fill_key} broker order identity does not bind to "
                f"command {client_key}")
        filled_at = raw.get("filled_at")
        if filled_at is None:
            raise _CloseBookIntervalUnproven(
                f"fill {fill_key} is not proven at or before official close")
        try:
            fill_time = _utc(filled_at, where=f"fill {fill_key} time")
        except TrialEvidenceRefused as exc:
            raise _CloseBookIntervalUnproven(str(exc)) from exc
        if (fill_time < evidence_start or fill_time > processed_through
                or fill_time > close):
            raise _CloseBookIntervalUnproven(
                f"fill {fill_key} is outside the plan-to-close book interval")
        try:
            quantity = _decimal(
                raw.get("quantity"), where=f"fill {fill_key} quantity")
            price = _decimal(
                raw.get("price"), where=f"fill {fill_key} price", positive=True)
        except TrialEvidenceRefused as exc:
            raise _CloseBookIntervalUnproven(str(exc)) from exc
        if quantity <= 0:
            raise _CloseBookIntervalUnproven(
                f"fill {fill_key} quantity must be positive")
        fill_quantity[client_key] = fill_quantity.get(
            client_key, Decimal(0)) + quantity
        fill_notional[client_key] = fill_notional.get(
            client_key, Decimal(0)) + quantity * price
        # Alpaca recovery persists the broker-native ref_id as a canonical
        # hashed fill key.  Matching only order/key/economics would allow a
        # different native event with identical quantity, price and timestamp
        # to masquerade as the retained row, defeating the identity proof.
        durable_fill_key = hashlib.sha256(json.dumps(
            {"kind": "broker-native-fill/v1", "activity_id": fill_key},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        authoritative_economics.add((
            broker_order_id, durable_fill_key, client_key,
            quantity, price, fill_time))
        authoritative_fills.append({
            "broker_order_id": broker_order_id,
            "fill_key": fill_key,
            "client_key": client_key,
            "quantity": str(quantity),
            "price": str(price),
            "filled_at": fill_time.isoformat(),
        })

    # The legacy fill cache is not completeness authority, but every retained
    # row in the economic interval must agree with the complete broker-native
    # publication.  Reading account-wide (without a current-plan JOIN) makes a
    # foreign, off-plan, post-close, null-time, stale or mislinked row blocking
    # instead of silently filtering it out.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT broker_order_id,fill_key,client_key,quantity,price,filled_at"
            " FROM sentinel_fills WHERE filled_at IS NULL OR filled_at >= %s"
            " ORDER BY filled_at NULLS FIRST,broker_order_id,fill_key",
            (evidence_start,))
        durable_rows = cur.fetchall()
    seen_durable: set[tuple[str, str]] = set()
    for row in durable_rows:
        broker_order_id = str(row[0] or "").strip()
        fill_key = str(row[1] or "").strip()
        client_key = str(row[2] or "").strip()
        durable_identity = (broker_order_id, fill_key)
        if (not broker_order_id or not fill_key
                or durable_identity in seen_durable
                or client_key not in command_by_key):
            raise _CloseBookIntervalUnproven(
                "durable fill is repeated, foreign, or off-plan")
        seen_durable.add(durable_identity)
        command_order_id = str(
            command_by_key[client_key].get("broker_order_id") or "").strip()
        if broker_order_id != command_order_id:
            raise _CloseBookIntervalUnproven(
                "durable fill broker order identity is stale or mislinked")
        if row[5] is None:
            raise _CloseBookIntervalUnproven(
                "durable fill has no broker timestamp")
        try:
            quantity = _decimal(
                row[3], where=f"durable fill {fill_key} quantity")
            price = _decimal(
                row[4], where=f"durable fill {fill_key} price", positive=True)
            fill_time = _utc(
                row[5], where=f"durable fill {fill_key} time")
        except TrialEvidenceRefused as exc:
            raise _CloseBookIntervalUnproven(str(exc)) from exc
        if quantity <= 0 or fill_time > close:
            raise _CloseBookIntervalUnproven(
                "durable fill is non-positive or after official close")
        if ((broker_order_id, fill_key, client_key,
             quantity, price, fill_time)
                not in authoritative_economics):
            raise _CloseBookIntervalUnproven(
                "durable fill is absent or economically different in the "
                "complete account interval")

    try:
        result = _decimal(plan.account_cash, where="plan account cash")
    except TrialEvidenceRefused as exc:
        raise _CloseCashUnproven(str(exc)) from exc
    for key, command in command_by_key.items():
        try:
            quantity = _decimal(
                command.get("filled_quantity"),
                where=f"command {key} filled quantity")
        except TrialEvidenceRefused as exc:
            raise _CloseBookIntervalUnproven(str(exc)) from exc
        if quantity < 0 or fill_quantity.get(key, Decimal(0)) != quantity:
            raise _CloseBookIntervalUnproven(
                f"command {key} fill rows do not prove its filled quantity")
        side = str(command.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise _CloseBookIntervalUnproven(
                f"command {key} has invalid side")
        notional = fill_notional.get(key, Decimal(0))
        result += notional if side == "SELL" else -notional
    return result, authoritative_fills


def _cash_baseline_reference(baseline) -> dict:
    """Canonical immutable plan-cash source embedded in a v3 certificate."""
    return {
        "kind": "plan-cash-baseline-reference/v1",
        "plan_id": baseline.plan_id,
        "broker": baseline.broker,
        "account_id": baseline.account_id,
        "decision_session": baseline.decision_session.isoformat(),
        "processed_through": baseline.processed_through.isoformat(),
        "balance_total": str(baseline.balance_total),
        "last_activity_id": baseline.last_activity_id,
        "activity_identity_scheme": baseline.activity_identity_scheme,
        "close_cash_finality_authoritative": (
            baseline.close_cash_finality_authoritative),
    }


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
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    wanted = sorted(key for key, value in positions.items()
                    if _decimal(value, where=f"position {key}") != 0)
    if not wanted:
        return {}, Decimal(0)
    visible = publication.visible_predicate("b")
    equity_wanted = [key for key in wanted if key != DEFENSIVE_SECURITY_ID]
    with conn.cursor() as cur:
        rows = []
        if equity_wanted:
            cur.execute(
                "SELECT security_id,ticker,close_unadjusted FROM sentinel_bars b"
                f" WHERE b.session=%s AND b.security_id=ANY(%s) AND {visible}",
                (session, equity_wanted))
            rows.extend(cur.fetchall())
        if DEFENSIVE_SECURITY_ID in wanted:
            defensive_visible = publication.visible_predicate("d")
            cur.execute(
                "SELECT security_id,ticker,close_unadjusted"
                " FROM sentinel_defensive_bars d WHERE d.session=%s"
                " AND d.security_id=%s AND d.ticker='BIL' AND "
                + defensive_visible,
                (session, DEFENSIVE_SECURITY_ID))
            rows.extend(cur.fetchall())
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
            " ORDER BY session",
            (f"{VERIFICATION_PREFIX}%", before))
        rows = cur.fetchall()
    if not rows:
        return None
    previous = None
    # Revalidate the whole retained chain, not just its newest link. A cash
    # backfill into an older certified session invalidates every cumulative
    # return descended from it even if the newest certificate is unchanged.
    for row in rows:
        session = (row[0] if isinstance(row[0], date)
                   else date.fromisoformat(str(row[0])))
        state = _mapping(row[1], where="previous trial verification")
        verified = _validate_verification(session, state)
        _validate_close_reference(conn, verified)
        _validate_fill_reference(conn, verified)
        _validate_cash_reference(conn, verified)
        _validate_cash_finality_reference(conn, verified)
        previous = verified
    return previous


def _terminal_verification_debt(conn, cycle) -> tuple[dict, ...]:
    """Find every earlier automation obligation missing its exact v3 row.

    The automation state transition and terminal callback are separate crash
    boundaries.  A durable terminal cycle must therefore remain visible to the
    financial chain even if the process dies before its callback writes the
    verification row.  Nonterminal older cycles are debt too: a later success
    cannot silently leapfrog unresolved economics.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cycle_id,effective_session,state"
            " FROM sentinel_automation_cycles"
            " WHERE deployment_id=%s AND broker=%s"
            " AND broker_account_id=%s"
            " AND effective_session < %s"
            " ORDER BY effective_session,created_at,cycle_id",
            (cycle.deployment_id, cycle.broker, cycle.broker_account_id,
             cycle.effective_session))
        rows = cur.fetchall()
    terminal = {"SUCCEEDED", "MISSED_STATE_ONLY", "SUPERSEDED", "BLOCKED"}
    debt = []
    for raw_cycle_id, raw_session, raw_state in rows:
        cycle_id = str(raw_cycle_id)
        session = (raw_session if isinstance(raw_session, date)
                   else date.fromisoformat(str(raw_session)))
        state = str(raw_state)
        if state not in terminal:
            debt.append({
                "cycle_id": cycle_id, "session": session.isoformat(),
                "state": state, "reason": "OLDER_CYCLE_NONTERMINAL"})
            continue
        stored = _stored(conn, f"{VERIFICATION_PREFIX}{session.isoformat()}")
        if stored is None:
            # v1/v2 verdicts cannot contribute an opening NAV or cumulative
            # factor to the corrected v3 series, but an exact, immutable
            # terminal row is still proof that an upgrade did not simply lose
            # the automation callback.  It is a chain boundary, not debt.
            legacy_found = False
            for version in (2, 1):
                legacy = _stored(
                    conn,
                    f"trial-verification:v{version}:{session.isoformat()}")
                if legacy is None:
                    continue
                legacy_session, raw_legacy = legacy
                candidate = dict(raw_legacy)
                digest = candidate.pop("evidence_sha256", None)
                if (candidate.get("kind")
                        != f"sentinel-trial-verification/v{version}"
                        or legacy_session != session
                        or candidate.get("session") != session.isoformat()
                        or digest != _sha(candidate)):
                    raise TrialEvidenceRefused(
                        f"legacy trial verification {session} fingerprint "
                        "is corrupt")
                embedded_cycle = candidate.get("cycle")
                if (not isinstance(embedded_cycle, Mapping)
                        or embedded_cycle.get("cycle_id") != cycle_id
                        or embedded_cycle.get("state") != state):
                    raise TrialEvidenceRefused(
                        "legacy terminal automation cycle disagrees with its "
                        f"verification: cycle_id={cycle_id}, "
                        f"session={session}, state={state}")
                legacy_found = True
                break
            if legacy_found:
                continue
            debt.append({
                "cycle_id": cycle_id, "session": session.isoformat(),
                "state": state, "reason": "TERMINAL_V3_MISSING"})
            continue
        stored_session, raw_verification = stored
        verification = _validate_verification(
            stored_session, raw_verification)
        embedded_cycle = verification.get("cycle")
        if (not isinstance(embedded_cycle, Mapping)
                or embedded_cycle.get("cycle_id") != cycle_id
                or embedded_cycle.get("state") != state):
            raise TrialEvidenceRefused(
                "terminal automation cycle disagrees with its v3 verification: "
                f"cycle_id={cycle_id}, session={session}, state={state}")
    return tuple(debt)


def _performance_chain_id(*, deployment_id: object, broker: object,
                          broker_account_id: object,
                          takeover_epoch: object) -> str | None:
    identity = {
        "deployment_id": deployment_id, "broker": broker,
        "broker_account_id": broker_account_id,
        "takeover_epoch": takeover_epoch,
    }
    if (any(value in (None, "") for value in identity.values())
            or isinstance(takeover_epoch, bool)
            or not isinstance(takeover_epoch, int)
            or takeover_epoch < 1):
        return None
    return hashlib.sha256(_canonical(identity).encode("ascii")).hexdigest()


def _terminal_failure(cycle, now: datetime) -> dict:
    reasons = [f"CYCLE_{cycle.state.value}"]
    if cycle.failure_code:
        reasons.append(str(cycle.failure_code))
    chain_id = _performance_chain_id(
        deployment_id=getattr(cycle, "deployment_id", None),
        broker=getattr(cycle, "broker", None),
        broker_account_id=getattr(cycle, "broker_account_id", None),
        takeover_epoch=getattr(cycle, "takeover_epoch", None))
    return {"kind": VERIFICATION_KIND,
            "session": cycle.effective_session.isoformat(),
            "decision_session": cycle.decision_session.isoformat(),
            "verified_at": now.isoformat(), "verdict": "NOT_VERIFIED",
            "reason_codes": sorted(set(reasons)),
            "cycle": {"cycle_id": cycle.cycle_id,
                      "state": cycle.state.value,
                      "failure_detail": cycle.failure_detail},
            "binding": {
                "deployment_id": getattr(cycle, "deployment_id", None),
                "broker": getattr(cycle, "broker", None),
                "broker_account_id": getattr(
                    cycle, "broker_account_id", None),
                "takeover_epoch": getattr(cycle, "takeover_epoch", None),
            },
            "performance": {
                "opening_equity": None, "ending_equity": None,
                "actual_cash": None, "strategy_pl": None,
                "daily_return": None, "cumulative_factor": "1",
                "total_return": None,
                "chain": {
                    "chain_id": chain_id, "predecessor_session": None,
                    "continuous": False,
                    "reset_reason": "TERMINAL_NOT_VERIFIED",
                },
            }}


def build_cycle_verification(conn, *, cycle_id: str,
                             observation_id: int | None = None,
                             now: datetime | None = None) -> dict:
    """Deterministically evaluate one already-terminal automation cycle."""
    now = _utc(now or datetime.now(timezone.utc), where="verification time")
    from sentinel.automation import store as automation_store
    from sentinel.automation.model import CycleState
    from sentinel import trial_close, trial_evidence, trial_fills
    from sentinel.core.decision import publication_fingerprint
    from sentinel.execution import broker_cash, journal, target_reprojection
    from sentinel.execution.identity import DeploymentIdentity
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
    target_projection = None
    if plan is not None:
        try:
            target_projection = target_reprojection.load_projection(
                conn, plan_id=plan.plan_id)
        except target_reprojection.TargetProjectionRefused:
            reasons.append("TARGET_PROJECTION_INVALID")
        if target_projection is None:
            reasons.append("TARGET_PROJECTION_MISSING")
        else:
            _reason(
                reasons,
                target_projection.plan_fingerprint == plan.fingerprint()
                and target_projection.through_session
                == plan.effective_session,
                "TARGET_PROJECTION_PLAN_MISMATCH")
    binding = _read_binding(conn)
    _reason(reasons, binding is not None, "BINDING_MISSING")
    state, cursor, state_at = _read_state(conn)
    _reason(reasons, state is not None and cursor is not None, "STATE_MISSING")
    expected_paper_dividends: list[dict] = []
    terminal_verification_debt = _terminal_verification_debt(conn, cycle)
    if terminal_verification_debt:
        reasons.append("VERIFICATION_GAP")
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
    deployment = DeploymentIdentity(
        deployment_id=cycle.deployment_id,
        broker=cycle.broker,
        broker_account_id=cycle.broker_account_id,
        takeover_epoch=cycle.takeover_epoch,
    )
    try:
        close_nav_evidence = trial_close.load_close_nav_evidence(
            conn, session=cycle.effective_session, deployment=deployment)
    except trial_close.TrialCloseNavRefused as exc:
        # Corrupt, revised, or cross-account historical evidence is an
        # integrity refusal.  It must not be flattened into an ordinary red
        # verdict that a later retry might appear to repair.
        raise TrialEvidenceRefused(
            f"historical close-NAV evidence is invalid: {exc}") from exc
    _reason(reasons, close_nav_evidence is not None,
            "CLOSE_NAV_EVIDENCE_MISSING")
    close_timestamp_aligned = False
    if close_nav_evidence is not None:
        close_request_completed = _utc(
            close_nav_evidence.get("request_completed_at"),
            where="historical close-NAV request completion")
        close_timestamp_aligned = close_request_completed <= latest_allowed
        _reason(reasons, close_timestamp_aligned,
                "CLOSE_NAV_EVIDENCE_FUTURE")
    fill_interval_evidence = None
    if plan is not None:
        try:
            fill_interval_evidence = trial_fills.load_fill_interval_evidence(
                conn, session=cycle.effective_session,
                deployment=deployment, plan_id=plan.plan_id)
        except trial_fills.TrialFillIntervalRefused as exc:
            raise TrialEvidenceRefused(
                f"historical account-fill interval evidence is invalid: "
                f"{exc}") from exc
        if fill_interval_evidence is None:
            reasons.extend((
                "CLOSE_FILL_INTERVAL_EVIDENCE_MISSING",
                "CLOSE_BOOK_INTERVAL_UNPROVEN",
            ))
        if fill_interval_evidence is not None:
            fill_interval_future = (
                _utc(
                    fill_interval_evidence.get("request_completed_at"),
                    where="account fill interval request completion")
                > latest_allowed)
            if fill_interval_future:
                reasons.extend((
                    "CLOSE_FILL_INTERVAL_EVIDENCE_FUTURE",
                    "CLOSE_BOOK_INTERVAL_UNPROVEN",
                ))
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
    try:
        frontier_session = date.fromisoformat(str(frontier))
    except (TypeError, ValueError):
        frontier_session = None
    frontier_aligned = (
        frontier_session is not None
        and ((frontier_session >= cycle.effective_session)
             if close_valuation
             else (frontier_session == cycle.decision_session)))
    _reason(reasons, frontier_aligned, "FRONTIER_SESSION_MISMATCH")
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
        try:
            reconciliation_time_matches = (
                observation is not None
                and _utc(account.get("reconciliation_observed_at"),
                         where="bound reconciliation completion")
                == observation["observed_at"])
        except (TrialEvidenceRefused, TypeError, ValueError):
            reconciliation_time_matches = False
        _reason(reasons, reconciliation_time_matches,
                "ACCOUNT_RECONCILIATION_TIME_MISMATCH")
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
    close_corporate_actions = (
        account_reconciliation.get("target_corporate_actions") or {})
    observation_corporate_actions = (
        account_reconciliation.get(
            "observation_target_corporate_actions") or {})
    reconciled_expected = account_reconciliation.get("expected") or {}
    try:
        retained_plan_target = _quantity_map(
            account_reconciliation.get("plan_target") or {},
            where="account-evidence plan target")
        current_plan_target = _quantity_map(plan_target, where="plan target")
        _reason(reasons, retained_plan_target == current_plan_target,
                "ACCOUNT_PLAN_TARGET_MISMATCH")
        if target_projection is None:
            raise TrialEvidenceRefused(
                "durable target projection is unavailable")
        retained_projection = _mapping(
            account_reconciliation.get("target_projection"),
            where="account-evidence target projection")
        _reason(
            reasons, retained_projection == target_projection.payload(),
            "ACCOUNT_TARGET_PROJECTION_MISMATCH")
        effective_target = _quantity_map(
            target_projection.target_basket,
            where="durable target projection")
        retained_close_actions = _quantity_map(
            close_corporate_actions,
            where="account-evidence target-projection actions")
        _reason(
            reasons,
            retained_close_actions == dict(
                target_projection.action_multipliers),
            "ACCOUNT_TARGET_ACTION_MISMATCH")
        retained_target = _quantity_map(
            account_reconciliation.get("target") or {},
            where="account-evidence effective target")
        _reason(reasons, retained_target == effective_target,
                "ACCOUNT_EFFECTIVE_TARGET_MISMATCH")
        target = {key: str(value) for key, value in effective_target.items()}
        observation_target = _age_plan_target(
            effective_target, observation_corporate_actions)
        retained_observation_target = _quantity_map(
            account_reconciliation.get("observation_target") or {},
            where="account-evidence observation target")
        _reason(
            reasons, retained_observation_target == observation_target,
            "ACCOUNT_OBSERVATION_TARGET_MISMATCH")
        expected = _quantity_map(
            reconciled_expected, where="reconciled expected book")
        # Command-derived reconciliation intentionally omits zero-net keys,
        # while production sizing retains an explicit zero defensive sleeve.
        # Those are the same economic book; compare the union with missing
        # quantities interpreted as exact zero.
        _reason(reasons, _economic_book_equal(expected, observation_target),
                "RECONCILED_TARGET_MISMATCH")
        comparison_target = {
            key: str(value) for key, value in observation_target.items()}
    except TrialEvidenceRefused:
        target = plan_target
        comparison_target = plan_target
        reasons.append("CORPORATE_ACTION_EVIDENCE_INVALID")
    all_securities = set(positions) | set(comparison_target)
    deltas = {key: str(_decimal(positions.get(key, 0), where=f"position {key}")
                       - _decimal(
                           comparison_target.get(key, 0),
                           where=f"observation target {key}"))
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

    if plan is not None and observation is not None:
        try:
            expected_paper_dividends.extend(
                _expected_effective_equity_dividends(
                    conn, cycle.effective_session, positions, commands))
        except TrialEvidenceRefused:
            reasons.append("DIVIDEND_EVIDENCE_INVALID")
        try:
            expected_paper_dividends.extend(
                _expected_defensive_dividends(
                    conn, cycle.effective_session, positions, commands))
        except TrialEvidenceRefused:
            reasons.append("DIVIDEND_EVIDENCE_INVALID")
    expected_paper_dividends.sort(
        key=lambda row: (
            row["security_id"], row["ticker"], row["amount"], row["shares"]))
    if expected_paper_dividends:
        reasons.append("ALPACA_PAPER_DIVIDEND_UNSUPPORTED")

    cash_rows, external, internal = _cash_rows(conn, cycle.effective_session)
    external_event_count = sum(
        1 for row in cash_rows
        if (row.get("classification") == "EXTERNAL"
            and _decimal(row.get("amount"), where="external cash event") != 0))
    _reason(reasons, not any(
        row["recorded_at"] is not None
        and _utc(row["recorded_at"], where="cash flow time") > latest_allowed
        for row in cash_rows), "CASH_TIMESTAMP_FUTURE")
    _reason(reasons, external_event_count == 0, "EXTERNAL_FLOW_UNWEIGHTED")
    marks, securities_value = ({}, Decimal(0))
    independent_close_nav = residual = close_cash = None
    historical_equity = None
    live_account_equity = live_account_cash = None
    if close_nav_evidence is not None:
        historical_equity = _decimal(
            close_nav_evidence["equity"],
            where="historical official-close equity", positive=True)

    activity = None
    if account is not None:
        live_account_equity = _decimal(
            account["account"]["equity"],
            where="live account equity", positive=True)
        live_account_cash = _decimal(
            account["account"]["cash"], where="live account cash")
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

    cash_baseline_evidence = None
    if plan is not None:
        try:
            baseline = broker_cash.load_plan_baseline(
                conn, plan_id=plan.plan_id)
        except broker_cash.BrokerCashAuthorityRefused:
            baseline = None
        if baseline is not None:
            cash_baseline_evidence = _cash_baseline_reference(baseline)
        try:
            _opened, official_close = calendar.session_window(
                cycle.effective_session)
            required_fill_through = max(
                _utc(account.get("observed_at"),
                     where="account evidence time"),
                _utc(account.get("reconciliation_observed_at"),
                     where="reconciliation evidence time"),
            ) if account is not None else None
            close_cash, fills = _reconstruct_close_cash(
                conn, plan=plan, commands=commands, activity=activity,
                close_at=official_close,
                fill_interval_evidence=fill_interval_evidence,
                required_fill_through=required_fill_through)
        except _CloseCashFinalityUnavailable:
            reasons.append("CLOSE_CASH_FINALITY_UNAVAILABLE")
        except _CloseCashUnproven:
            reasons.append("CLOSE_CASH_UNPROVEN")
        except _CloseBookIntervalUnproven:
            reasons.append("CLOSE_BOOK_INTERVAL_UNPROVEN")

    try:
        # The action-aged immutable target/command book is the close book.
        # The later live positions are an independent equality check above,
        # never the valuation input itself.
        marks, securities_value = _marks(
            conn, cycle.effective_session, target)
    except TrialEvidenceRefused:
        reasons.append("MARKS_MISSING")

    if close_cash is not None:
        independent_close_nav = close_cash + securities_value
    if historical_equity is not None and independent_close_nav is not None:
        residual = historical_equity - independent_close_nav
        _reason(reasons, abs(residual) <= FINANCIAL_TOLERANCE,
                "CLOSE_NAV_UNEXPLAINED")

    previous_verified = (previous is not None
                         and previous.get("verdict") == "VERIFIED")
    predecessor_identity_equal = False
    predecessor_adjacent = False
    predecessor_same_epoch = False
    predecessor_reset_reason = (
        "INITIAL_V3_ANCHOR" if previous is None else None)
    if previous is not None:
        prior_binding = previous.get("binding")
        identity_keys = ("deployment_id", "broker", "broker_account_id")
        prior_binding_complete = (
            isinstance(prior_binding, Mapping)
            and all(prior_binding.get(key) not in (None, "")
                    for key in (*identity_keys, "takeover_epoch")))
        predecessor_identity_equal = (
            prior_binding_complete
            and isinstance(binding, Mapping)
            and all(prior_binding.get(key) == binding.get(key)
                    for key in identity_keys))
        predecessor_same_epoch = bool(
            predecessor_identity_equal
            and prior_binding.get("takeover_epoch")
            == binding.get("takeover_epoch"))
        if not prior_binding_complete:
            reasons.append("VERIFICATION_GAP")
        elif not predecessor_identity_equal:
            predecessor_reset_reason = "DEPLOYMENT_OR_ACCOUNT_CHANGED"
        elif not predecessor_same_epoch:
            predecessor_reset_reason = "TAKEOVER_EPOCH_CHANGED"
        else:
            previous_session = date.fromisoformat(previous["session"])
            predecessor_adjacent = (
                calendar.next_session(previous_session.isoformat())
                == cycle.effective_session.isoformat())
            if not previous_verified or not predecessor_adjacent:
                reasons.append("VERIFICATION_GAP")
    predecessor_continuous = (
        previous_verified and predecessor_identity_equal
        and predecessor_same_epoch and predecessor_adjacent)
    performance_chain_id = _performance_chain_id(
        deployment_id=cycle.deployment_id, broker=cycle.broker,
        broker_account_id=cycle.broker_account_id,
        takeover_epoch=cycle.takeover_epoch)
    # A plan's sizing NAV is a later live observation, not an official-close
    # mark and not a valid opening boundary for historical performance.  The
    # first successful v3 certificate therefore anchors the chain at its
    # independently accepted closing equity without emitting P/L or a return.
    # Only an adjacent prior VERIFIED close can open a return interval.
    opening = (_decimal(previous["performance"]["ending_equity"],
                        where="previous verified equity", positive=True)
               if predecessor_continuous else None)
    cumulative_factor = Decimal(1)
    if predecessor_continuous:
        cumulative_factor = Decimal(str(
            previous["performance"]["cumulative_factor"]))
    strategy_pl, daily_return, cumulative_factor, total_return = (
        _performance_attribution(
            opening=opening, ending=historical_equity, external=external,
            external_event_count=external_event_count,
            prior_cumulative_factor=cumulative_factor))

    verification = {
        "kind": VERIFICATION_KIND,
        "session": cycle.effective_session.isoformat(),
        "decision_session": cycle.decision_session.isoformat(),
        "verified_at": now.isoformat(),
        "verdict": "VERIFIED" if not reasons else "NOT_VERIFIED",
        "reason_codes": sorted(set(reasons)),
        "terminal_verification_debt": list(terminal_verification_debt),
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
        "close_nav_evidence": close_nav_evidence,
        "fill_interval_evidence": fill_interval_evidence,
        "cash_baseline_evidence": cash_baseline_evidence,
        "reconciliation": {
            "observation_id": reconciliation_id,
            "observed_at": (observation["observed_at"].isoformat()
                            if observation else None),
            "completeness": observation["completeness"] if observation else None,
            "runtime_state": observation["runtime_state"] if observation else None,
            "positions": positions, "plan_target": plan_target,
            "target": target,
            "observation_target": comparison_target,
            "deltas": deltas,
            "corporate_actions": close_corporate_actions,
            "observation_corporate_actions": (
                observation_corporate_actions),
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
            # ``marked_nav`` is retained as the panel's display key, but in v3
            # it is the independently reconstructed official-close NAV, not a
            # later live cash balance plus marks.
            "marked_nav": (str(independent_close_nav)
                           if independent_close_nav is not None else None),
            "independent_close_nav": (
                str(independent_close_nav)
                if independent_close_nav is not None else None),
            "close_cash": str(close_cash) if close_cash is not None else None,
            "securities_value": str(securities_value),
            "unexplained": str(residual) if residual is not None else None,
            "account_observed_at": (
                account.get("observed_at") if account is not None else None),
            "account_observation_started_at": (
                account.get("observation_started_at")
                if account is not None else None),
            "reconciliation_observed_at": (
                account.get("reconciliation_observed_at")
                if account is not None else None),
            "reconciliation_started_at": (
                account.get("reconciliation_started_at")
                if account is not None else None),
            "marks_session": cycle.effective_session.isoformat(),
            "timestamp_aligned": close_timestamp_aligned,
            "timestamp_authority": (
                "IMMUTABLE_BROKER_HISTORICAL_CLOSE"
                if close_nav_evidence is not None else None),
            "close_evidence_sha256": (
                close_nav_evidence.get("evidence_sha256")
                if close_nav_evidence is not None else None),
            "fill_interval_evidence_sha256": (
                fill_interval_evidence.get("evidence_sha256")
                if fill_interval_evidence is not None else None),
            "live_account_equity": (
                str(live_account_equity)
                if live_account_equity is not None else None),
            "live_account_cash": (
                str(live_account_cash)
                if live_account_cash is not None else None),
            "tolerance": str(FINANCIAL_TOLERANCE)},
        "performance": {
            "opening_equity": str(opening) if opening is not None else None,
            "ending_equity": (str(historical_equity)
                              if historical_equity is not None else None),
            "actual_cash": str(close_cash) if close_cash is not None else None,
            "strategy_pl": str(strategy_pl) if strategy_pl is not None else None,
            "daily_return": str(daily_return) if daily_return is not None else None,
            "cumulative_factor": str(cumulative_factor),
            "total_return": str(total_return) if total_return is not None else None,
            "chain": {
                "chain_id": performance_chain_id,
                "predecessor_session": (
                    previous.get("session") if previous is not None else None),
                "continuous": predecessor_continuous,
                "reset_reason": predecessor_reset_reason,
            },
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


def _validate_close_reference(conn, verification: Mapping) -> None:
    """Re-bind a retained successful v3 row to its immutable close source.

    The verification hash proves what was frozen, not that its separately
    namespaced source row still exists unchanged.  Every read which can return
    or chain from a successful certificate therefore revalidates the current
    close row and requires exact equality with the embedded evidence.
    """
    cycle = verification.get("cycle")
    if not isinstance(cycle, Mapping) or cycle.get("state") != "SUCCEEDED":
        return
    embedded = verification.get("close_nav_evidence")
    if not isinstance(embedded, Mapping):
        raise TrialEvidenceRefused(
            "successful v3 verification has no embedded close-NAV evidence")
    binding = embedded.get("deployment")
    required = {
        "deployment_id", "broker", "broker_account_id", "takeover_epoch"}
    if not isinstance(binding, Mapping) or set(binding) != required:
        raise TrialEvidenceRefused(
            "successful v3 close-NAV deployment binding is malformed")
    epoch = binding.get("takeover_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise TrialEvidenceRefused(
            "successful v3 close-NAV takeover epoch is malformed")
    try:
        from sentinel import trial_close
        from sentinel.execution.identity import DeploymentIdentity

        deployment = DeploymentIdentity(
            deployment_id=binding["deployment_id"],
            broker=binding["broker"],
            broker_account_id=binding["broker_account_id"],
            takeover_epoch=epoch,
        )
        current = trial_close.load_close_nav_evidence(
            conn, session=str(verification.get("session") or ""),
            deployment=deployment)
    except (trial_close.TrialCloseNavRefused, TypeError, ValueError) as exc:
        raise TrialEvidenceRefused(
            f"successful v3 close-NAV reference is invalid: {exc}") from exc
    if current is None:
        raise TrialEvidenceRefused(
            "successful v3 close-NAV source row is missing")
    if dict(current) != dict(embedded):
        raise TrialEvidenceRefused(
            "successful v3 close-NAV source row changed after verification")


def _validate_fill_reference(conn, verification: Mapping) -> None:
    """Re-bind a successful v3 row to its account-wide fill publication."""
    cycle = verification.get("cycle")
    if not isinstance(cycle, Mapping) or cycle.get("state") != "SUCCEEDED":
        return
    embedded = verification.get("fill_interval_evidence")
    if not isinstance(embedded, Mapping):
        raise TrialEvidenceRefused(
            "successful v3 verification has no embedded fill interval")
    binding = embedded.get("deployment")
    required = {
        "deployment_id", "broker", "broker_account_id", "takeover_epoch"}
    if not isinstance(binding, Mapping) or set(binding) != required:
        raise TrialEvidenceRefused(
            "successful v3 fill-interval deployment binding is malformed")
    plan_id = embedded.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise TrialEvidenceRefused(
            "successful v3 fill-interval plan binding is malformed")
    epoch = binding.get("takeover_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise TrialEvidenceRefused(
            "successful v3 fill-interval takeover epoch is malformed")
    try:
        from sentinel import trial_fills
        from sentinel.execution.identity import DeploymentIdentity

        deployment = DeploymentIdentity(
            deployment_id=binding["deployment_id"], broker=binding["broker"],
            broker_account_id=binding["broker_account_id"],
            takeover_epoch=epoch)
        current = trial_fills.load_fill_interval_evidence(
            conn, session=str(verification.get("session") or ""),
            deployment=deployment, plan_id=plan_id)
    except (trial_fills.TrialFillIntervalRefused,
            TypeError, ValueError) as exc:
        raise TrialEvidenceRefused(
            f"successful v3 fill-interval reference is invalid: {exc}") from exc
    if current is None:
        raise TrialEvidenceRefused(
            "successful v3 fill-interval source row is missing")
    if dict(current) != dict(embedded):
        raise TrialEvidenceRefused(
            "successful v3 fill-interval source row changed after verification")


def _validate_cash_reference(conn, verification: Mapping) -> None:
    """Re-bind a succeeded v3 row to its session cash-flow ledger slice."""
    cycle = verification.get("cycle")
    if not isinstance(cycle, Mapping) or cycle.get("state") != "SUCCEEDED":
        return
    embedded = verification.get("cash")
    if not isinstance(embedded, Mapping) or set(embedded) != {
            "rows", "external", "internal"}:
        raise TrialEvidenceRefused(
            "successful v3 verification has malformed embedded cash evidence")
    try:
        session = date.fromisoformat(str(verification.get("session") or ""))
        rows, external, internal = _cash_rows(conn, session)
    except (TypeError, ValueError) as exc:
        raise TrialEvidenceRefused(
            f"successful v3 cash reference is invalid: {exc}") from exc
    current = {
        "rows": rows, "external": str(external), "internal": str(internal)}
    if dict(embedded) != current:
        raise TrialEvidenceRefused(
            "successful v3 cash-flow source rows changed after verification")


def _validate_cash_finality_reference(conn, verification: Mapping) -> None:
    """Re-bind retained VERIFIED output to current close-cash authority."""
    cycle = verification.get("cycle")
    if (not isinstance(cycle, Mapping)
            or cycle.get("state") != "SUCCEEDED"
            or verification.get("verdict") != "VERIFIED"):
        return
    embedded = verification.get("cash_baseline_evidence")
    if not isinstance(embedded, Mapping):
        raise TrialEvidenceRefused(
            "successful v3 verification has no embedded plan cash baseline")
    expected_keys = {
        "kind", "plan_id", "broker", "account_id", "decision_session",
        "processed_through", "balance_total", "last_activity_id",
        "activity_identity_scheme", "close_cash_finality_authoritative",
    }
    if (set(embedded) != expected_keys
            or embedded.get("kind") != "plan-cash-baseline-reference/v1"):
        raise TrialEvidenceRefused(
            "successful v3 plan cash baseline reference is malformed")
    plan = verification.get("plan")
    deployment = plan.get("deployment") if isinstance(plan, Mapping) else None
    if (not isinstance(plan, Mapping)
            or not isinstance(deployment, Mapping)
            or embedded.get("plan_id") != plan.get("plan_id")
            or embedded.get("decision_session") != plan.get("decision_session")
            or embedded.get("broker") != deployment.get("broker")
            or embedded.get("account_id")
            != deployment.get("broker_account_id")):
        raise TrialEvidenceRefused(
            "successful v3 plan cash baseline names another plan/account/session")
    try:
        from sentinel.execution import broker_cash

        current = broker_cash.load_plan_baseline(
            conn, plan_id=str(embedded["plan_id"]))
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise TrialEvidenceRefused(
            f"successful v3 plan cash baseline is invalid: {exc}") from exc
    if current is None:
        raise TrialEvidenceRefused(
            "successful v3 plan cash baseline source row is missing")
    current_reference = _cash_baseline_reference(current)
    if dict(embedded) != current_reference:
        raise TrialEvidenceRefused(
            "successful v3 plan cash baseline or finality authority changed "
            "after verification")
    if not current.close_cash_finality_authoritative:
        raise TrialEvidenceRefused(
            "successful v3 close-cash finality authority is no longer accepted")


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
        _validate_close_reference(conn, stored)
        _validate_fill_reference(conn, stored)
        _validate_cash_reference(conn, stored)
        _validate_cash_finality_reference(conn, stored)
        return stored
    result = build_cycle_verification(
        conn, cycle_id=cycle_id, observation_id=observation_id, now=now)
    pending_source_reasons = {
        "CLOSE_NAV_EVIDENCE_MISSING",
        "CLOSE_NAV_EVIDENCE_FUTURE",
        "CLOSE_FILL_INTERVAL_EVIDENCE_MISSING",
        "CLOSE_FILL_INTERVAL_EVIDENCE_FUTURE",
        "CLOSE_CASH_FINALITY_UNAVAILABLE",
    }
    pending = pending_source_reasons.intersection(
        result.get("reason_codes", ()))
    if ((result.get("cycle") or {}).get("state") == "SUCCEEDED" and pending):
        raise TrialEvidenceRefused(
            "a succeeded cycle cannot freeze a v3 verdict while immutable "
            "close/fill/cash evidence is pending: "
            + ",".join(sorted(pending)))
    _validate_close_reference(conn, result)
    _validate_fill_reference(conn, result)
    _validate_cash_reference(conn, result)
    _validate_cash_finality_reference(conn, result)
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
        verified = _validate_verification(session, state)
        _validate_close_reference(conn, verified)
        _validate_fill_reference(conn, verified)
        _validate_cash_reference(conn, verified)
        _validate_cash_finality_reference(conn, verified)
        result.append(verified)
    return result


__all__ = [
    "ACCOUNT_PREFIX", "FINANCIAL_TOLERANCE", "TrialEvidenceRefused",
    "VERIFICATION_PREFIX", "build_cycle_verification",
    "due_succeeded_cycle_id",
    "load_account_evidence", "load_verifications", "record_account_evidence",
    "record_cycle_verification", "record_due_cycle_verification",
]
