"""Alpaca transport mapped onto Sentinel's fail-closed execution contract.

Transport ambiguity is never an economic rejection.  A request timeout, rate
limit or server failure can mean that an order exists at Alpaca even when the
caller did not receive a usable acknowledgement, so those outcomes remain
UNKNOWN until the deterministic client key is resolved.  Conversely, broker
evidence that positively contradicts the durable order economics is malformed
and is never accepted.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional, Sequence
from urllib.parse import quote

from sentinel.execution.broker_cash import (
    BrokerCashActivity, BrokerCashActivityBatch, RECOGNIZED_ACTIVITY_TYPES)
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerCapabilities,
    BrokerCloseValuation, BrokerFill, BrokerInstrument, BrokerObservation,
    BrokerOrder, BrokerPosition, CommandOutcome, Completeness, ExecutionBroker,
    MalformedBrokerEvidence, Side)
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution import broker_cash, contract, journal
from sentinel.execution.identity import is_sentinel_key
from sentinel.execution.states import CommandState, CommandState as S, TERMINAL
from sentinel.feed import calendar

log = logging.getLogger(__name__)

PAGE_SIZE = 500
MAX_PAGES = 20
ACTIVITY_PAGE_SIZE = 100
MAX_ACTIVITY_PAGES = 20
PORTFOLIO_HISTORY_SOURCE = "alpaca_portfolio_history"
PORTFOLIO_HISTORY_QUARANTINE_SEMANTICS = "UNVALIDATED_1D_LEFT_LABEL"
ACCOUNT_LAST_EQUITY_SOURCE = "alpaca_trading_account_last_equity"
ACCOUNT_LAST_EQUITY_SEMANTICS = (
    "ALPACA_PREVIOUS_TRADING_DAY_1600_ET_LAST_EQUITY_T1_WINDOW_V1")
ACCOUNT_LAST_EQUITY_TIMESTAMP_UNIT = (
    "DERIVED_OFFICIAL_XNYS_CLOSE_EPOCH_SECONDS_NOT_A_WIRE_TIMESTAMP")
# Alpaca documents its beginning-of-day account synchronization as completing
# by 02:30 ET.  A half-hour margin makes the candidate's temporal interpretation
# explicit instead of racing the documented processing interval.
ACCOUNT_LAST_EQUITY_READY_ET = time(3, 0)

_STATUS = {
    "new": S.ACKNOWLEDGED,
    "accepted": S.ACKNOWLEDGED,
    "pending_new": S.ACKNOWLEDGED,
    "accepted_for_bidding": S.ACKNOWLEDGED,
    "held": S.ACKNOWLEDGED,
    "suspended": S.ACKNOWLEDGED,
    "stopped": S.ACKNOWLEDGED,
    "calculated": S.ACKNOWLEDGED,
    "done_for_day": S.ACKNOWLEDGED,
    "pending_replace": S.ACKNOWLEDGED,
    "replaced": S.ACKNOWLEDGED,
    "partially_filled": S.PARTIALLY_FILLED,
    "filled": S.FILLED,
    "canceled": S.CANCELLED,
    "cancelled": S.CANCELLED,
    "expired": S.CANCELLED,
    "pending_cancel": S.CANCEL_PENDING,
    "rejected": S.REJECTED,
}

ANOMALOUS_STATUSES = frozenset({"replaced", "pending_replace"})
_SIDES = {"buy": Side.BUY, "sell": Side.SELL}


class UnmappedBrokerStatus(RuntimeError):
    """Alpaca reported a lifecycle state without a certified mapping."""


class MalformedBrokerPayload(MalformedBrokerEvidence):
    """Broker evidence is contradictory or unreadable and cannot be trusted."""


class IncompleteBrokerPayload(MalformedBrokerPayload):
    """Broker evidence is missing fields needed to establish acknowledgement."""


class AlpacaCredentialsRefused(BrokerAuthorityRefused):
    """Alpaca rejected credentials/authority rather than order economics."""


@dataclass(frozen=True)
class RetryableCommandOutcome(CommandOutcome):
    """UNKNOWN submit outcome that explicitly permits a guarded same-key retry.

    This is deliberately structured state rather than a magic string in
    ``detail``.  The generic recovery layer may branch on the field while the
    human detail remains non-authoritative.
    """

    retry_after_seconds: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.state is not S.UNKNOWN:
            raise ValueError("retryable submit outcome must remain UNKNOWN")
        if (not isinstance(self.retry_after_seconds, Decimal)
                or not self.retry_after_seconds.is_finite()
                or self.retry_after_seconds < 0):
            raise ValueError("retry_after_seconds must be a finite non-negative Decimal")


def is_anomalous_status(raw: str) -> bool:
    return (raw or "").strip().lower() in ANOMALOUS_STATUSES


def map_status(raw: str) -> S:
    key = (raw or "").strip().lower()
    if key not in _STATUS:
        raise UnmappedBrokerStatus(
            f"Alpaca status {raw!r} has no certified mapping. Refusing to "
            "guess whether an order can still trade.")
    return _STATUS[key]


def _submit_outcome(order: BrokerOrder) -> CommandOutcome:
    """Translate the *returned* lifecycle, not merely HTTP 2xx, to authority."""
    raw_status = str(order.raw.get("status") or "").strip().lower()
    if order.state is S.REJECTED:
        return CommandOutcome(
            state=S.REJECTED, broker_order_id=order.broker_order_id,
            detail=f"broker rejected submitted order ({raw_status})")
    # A create response that is already cancelled, cancellation-pending,
    # stopped/suspended, or externally replaced is not acknowledgement that
    # the requested order remains under Sentinel's lifecycle.  UNKNOWN forces
    # exact-key recovery and stops the rest of the basket.
    acknowledged_statuses = frozenset({
        "new", "accepted", "pending_new", "accepted_for_bidding", "held",
        "partially_filled", "filled",
    })
    if order.external_replacement or raw_status not in acknowledged_statuses:
        return CommandOutcome(
            state=S.UNKNOWN, broker_order_id=order.broker_order_id,
            detail=("2xx submit returned a non-acknowledging lifecycle "
                    f"status {raw_status!r}; exact-key recovery required"))
    return CommandOutcome(
        state=S.ACKNOWLEDGED,
        broker_order_id=order.broker_order_id,
        detail="accepted; lifecycle reconciles separately")


def _side(raw, *, where: str) -> Side:
    key = str(raw).strip().lower() if raw is not None else ""
    if key not in _SIDES:
        raise MalformedBrokerPayload(
            f"{where}: side {raw!r} is neither 'buy' nor 'sell'")
    return _SIDES[key]


def _required_dec(value, *, where: str,
                  allow_negative: bool = False) -> Decimal:
    if value is None or value == "":
        raise MalformedBrokerPayload(
            f"{where}: missing; absence is not evidence of zero")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MalformedBrokerPayload(
            f"{where}: {value!r} is not a number") from None
    if not out.is_finite():
        raise MalformedBrokerPayload(f"{where}: {value!r} is not finite")
    if out < 0 and not allow_negative:
        raise MalformedBrokerPayload(
            f"{where}: {out} is negative in a non-negative quantity field")
    return out


def _required_bool(payload: dict, key: str, *, where: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise MalformedBrokerPayload(
            f"{where}: {key} must be an explicit boolean, got {value!r}")
    return value


def _dec(value, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _retry_after_seconds(resp) -> Decimal:
    raw = getattr(resp, "headers", {}).get("Retry-After")
    if raw in (None, ""):
        return Decimal("1")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Decimal("1")
    if not value.is_finite() or value < 0:
        return Decimal("1")
    return value


def _submit_error_detail(resp) -> str:
    """Return bounded Alpaca error evidence without trusting one wire shape."""
    text = str(getattr(resp, "text", "") or "").strip()
    try:
        payload = resp.json()
    except Exception:                                      # noqa: BLE001
        payload = None
    if isinstance(payload, dict):
        code = payload.get("code")
        message = str(payload.get("message") or "").strip()
        structured = " ".join(
            part for part in (
                f"code={code}" if code not in (None, "") else "",
                message,
            ) if part)
        if structured and structured not in text:
            text = f"{structured}; {text}" if text else structured
    return text[:500]


def _submit_error_outcome(resp) -> CommandOutcome:
    """Classify only documented create-order non-acceptance as REJECTED.

    HTTP's 4xx class is not an order lifecycle.  An undocumented status may be
    emitted by an intermediary or by a changed vendor contract after the order
    reached Alpaca, so exact-key recovery remains mandatory unless this
    endpoint's contract positively proves non-acceptance.
    """
    status = int(resp.status_code)
    detail = _submit_error_detail(resp)
    lowered = detail.lower()
    duplicate_key = (
        "duplicate" in lowered
        or (("client_order_id" in lowered or "client order id" in lowered)
            and any(token in lowered for token in (
                "unique", "already exists", "already been used"))))

    if status == 401:
        raise AlpacaCredentialsRefused(
            f"Alpaca submit credentials refused with HTTP 401: {detail}")
    if status == 429:
        retry_after = _retry_after_seconds(resp)
        return RetryableCommandOutcome(
            state=S.UNKNOWN,
            retry_after_seconds=retry_after,
            detail=("HTTP 429 rate limit; same-key retry eligible after "
                    f"{retry_after}s"))
    if status == 408:
        return CommandOutcome(
            state=S.UNKNOWN, detail="HTTP 408 transport ambiguity")
    if status == 422 and duplicate_key:
        return CommandOutcome(
            state=S.UNKNOWN,
            detail=f"duplicate key at broker: {detail}")
    if status in {403, 422}:
        headers = getattr(resp, "headers", {}) or {}
        request_id = str(
            headers.get("X-Request-ID")
            or headers.get("x-request-id") or "").strip()
        if not request_id:
            return CommandOutcome(
                state=S.UNKNOWN,
                detail=(f"HTTP {status} omitted Alpaca X-Request-ID; "
                        f"response origin/non-acceptance is unproven: {detail}"))
        return CommandOutcome(
            state=S.REJECTED,
            detail=(f"HTTP {status} documented Alpaca order refusal "
                    f"(request_id={request_id}): {detail}"))
    return CommandOutcome(
        state=S.UNKNOWN,
        detail=(f"HTTP {status} is not documented as definitive order "
                f"non-acceptance: {detail}"))


def parse_portfolio_history_close(
        payload, *, identity: BrokerAccountIdentity, requested_session: date,
        request_started_at: datetime, request_completed_at: datetime,
        query: Sequence[tuple[str, str]]) -> BrokerCloseValuation:
    """Strictly parse one *quarantined* Alpaca 1D history point.

    Alpaca documents the response timestamp as a left label and the equity as
    the value at the end of that window.  Retained examples do not establish a
    stable integer unit.  This parser consequently validates and preserves the
    integer but never converts it, maps it to ``requested_session``, or stamps a
    valuation time.  A real-account acceptance contract must do those things
    before the adapter can advertise close-valuation capability.
    """
    if not isinstance(payload, dict):
        raise MalformedBrokerPayload(
            "portfolio-history response must be an object")
    if type(requested_session) is not date:
        raise MalformedBrokerPayload(
            "portfolio-history requested session must be a date")
    if payload.get("timeframe") != "1D":
        raise MalformedBrokerPayload(
            "portfolio-history response timeframe must be exactly '1D'")
    timestamps = payload.get("timestamp")
    equities = payload.get("equity")
    if not isinstance(timestamps, list) or not isinstance(equities, list):
        raise MalformedBrokerPayload(
            "portfolio-history timestamp and equity must be arrays")
    if len(timestamps) != 1 or len(equities) != 1:
        raise MalformedBrokerPayload(
            "quarantined one-session portfolio-history query must return "
            "exactly one timestamp/equity point")
    source_timestamp = timestamps[0]
    if (isinstance(source_timestamp, bool)
            or not isinstance(source_timestamp, int)
            or source_timestamp < 1):
        raise MalformedBrokerPayload(
            "portfolio-history timestamp must be a positive opaque integer")
    equity = _required_dec(
        equities[0], where="portfolio-history close equity")
    if equity <= 0:
        raise MalformedBrokerPayload(
            "portfolio-history close equity must be positive")

    # Validate documented parallel numeric series when they are present, even
    # though Sentinel must never use Alpaca's P/L or percentage calculation as
    # its own performance arithmetic.
    for key in ("profit_loss", "profit_loss_pct"):
        if key not in payload:
            continue
        series = payload[key]
        if not isinstance(series, list) or len(series) != 1:
            raise MalformedBrokerPayload(
                f"portfolio-history {key} must parallel the one equity point")
        _required_dec(
            series[0], where=f"portfolio-history {key}",
            allow_negative=True)
    if "base_value" in payload and payload["base_value"] is not None:
        _required_dec(payload["base_value"], where="portfolio-history base_value")

    try:
        return BrokerCloseValuation(
            identity=identity, requested_session=requested_session,
            equity=equity, source_timestamp=source_timestamp,
            source_timeframe="1D", source=PORTFOLIO_HISTORY_SOURCE,
            semantics=PORTFOLIO_HISTORY_QUARANTINE_SEMANTICS,
            request_started_at=_required_aware_ts(
                request_started_at, where="portfolio-history request start"),
            request_completed_at=_required_aware_ts(
                request_completed_at,
                where="portfolio-history request completion"),
            query=tuple(query), source_timestamp_unit=None, valuation_at=None,
            raw=dict(payload))
    except (TypeError, ValueError) as exc:
        raise MalformedBrokerPayload(
            f"portfolio-history typed evidence is invalid: {exc}") from exc


@dataclass(frozen=True)
class AlpacaMarketClock:
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime


class AlpacaExecutionBroker(ExecutionBroker):
    """`ExecutionBroker` implemented over Alpaca's paper REST API."""

    capabilities = BrokerCapabilities(
        stable_client_key=True,
        single_order_cancel=True,
        complete_order_pagination=True,
        recent_fill_history=True,
        instrument_identity=True,
        pre_submit_instrument_revalidation=True,
        account_bound_observation=True,
        fractional_quantities=True,
        minimum_quantity_increment=Decimal("0.000000001"),
        market_on_open=False,
    )
    certification_name = "alpaca"
    # Method presence is deliberately not production authority.  These flags
    # let the NAS acceptance harness distinguish an implemented read-only
    # candidate from a capability that has actually passed the bound paper
    # account test and may cross the production guard.
    candidate_previous_session_close_valuation = True
    previous_session_close_nas_accepted = False

    def __init__(self, *, api_key: str, secret_key: str, base_url: str,
                 resolve_security_id=None, to_broker_symbol=None,
                 from_broker_symbol=None, http_provider=None,
                 clock_provider=None) -> None:
        from sentinel.config import assert_paper_url
        assert_paper_url(base_url)
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self._http_provider = http_provider
        self._clock_provider = (
            clock_provider or (lambda: datetime.now(timezone.utc)))
        self._resolve = resolve_security_id or (lambda symbol: symbol)
        self._to_symbol = to_broker_symbol or (lambda s: s.replace("-", "."))
        self._from_symbol = (from_broker_symbol
                             or (lambda s: s.replace(".", "-")))

    @property
    def _httpx(self):
        if self._http_provider is not None:
            return self._http_provider()
        import httpx  # noqa: PLC0415
        return httpx

    def _headers(self) -> dict:
        return {"APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key}

    def _now(self) -> datetime:
        return _required_aware_ts(
            self._clock_provider(), where="Alpaca observation clock")

    async def _get(self, path: str, params: Optional[dict] = None):
        async with self._httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self.base_url}{path}", headers=self._headers(),
                params=params or {})
            if resp.status_code in (401, 403):
                raise AlpacaCredentialsRefused(
                    f"Alpaca read authority refused with HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()

    async def identify_account(self) -> BrokerAccountIdentity:
        return self._account_identity(await self._get("/v2/account"))

    async def account_snapshot(self) -> BrokerAccountSnapshot:
        payload = await self._get("/v2/account")
        identity = self._account_identity(payload)
        return BrokerAccountSnapshot(
            identity=identity,
            equity=_required_dec(payload.get("equity"), where="account equity"),
            cash=_required_dec(payload.get("cash"), where="account cash",
                               allow_negative=True),
            buying_power=_required_dec(
                payload.get("buying_power"), where="account buying power",
                allow_negative=True),
            multiplier=_required_dec(
                payload.get("multiplier"), where="account multiplier"),
            status=str(payload.get("status") or ""),
            trading_blocked=_required_bool(
                payload, "trading_blocked", where="account"),
            account_blocked=_required_bool(
                payload, "account_blocked", where="account"),
            trade_suspended_by_user=_required_bool(
                payload, "trade_suspended_by_user", where="account"))

    async def account_close_valuation(
            self, *, session: date) -> BrokerCloseValuation:
        """Read the official previous-session close field as a NAS candidate.

        Alpaca defines ``/v2/account.last_equity`` as the previous trading
        day's equity at 16:00 ET.  That definition identifies one XNYS close
        only while ``session`` is the session immediately before the next XNYS
        session.  The read is therefore accepted only from 03:00 ET on that
        next session date (after the documented BOD synchronization window)
        until, but not including, that session's own official close.  Both
        account reads must preserve native identity and the exact field value.

        The account field carries no native timestamp.  ``source_timestamp``
        is consequently the explicitly labelled *derived* official XNYS close,
        never represented as an Alpaca wire label.  Capability remains false
        until this candidate passes the bound paper-account NAS acceptance.
        """
        if type(session) is not date:
            raise MalformedBrokerPayload(
                "last-equity requested session must be a date")
        from sentinel.feed import calendar  # noqa: PLC0415
        from zoneinfo import ZoneInfo       # noqa: PLC0415

        _opened, official_close = calendar.session_window(session)
        official_close_et = official_close.astimezone(
            ZoneInfo(calendar.EXCHANGE_TZ))
        if official_close_et.timetz().replace(tzinfo=None) != time(16, 0):
            raise MalformedBrokerPayload(
                "Alpaca documents last_equity at 16:00 ET, which does not "
                "establish the official close NAV for an XNYS half-day")
        next_session = date.fromisoformat(calendar.next_session(session))
        _next_open, next_close = calendar.session_window(next_session)
        ready_at = datetime.combine(
            next_session, ACCOUNT_LAST_EQUITY_READY_ET,
            tzinfo=ZoneInfo(calendar.EXCHANGE_TZ))

        def require_read_window(observed_at: datetime, *, where: str) -> None:
            observed = _required_aware_ts(observed_at, where=where)
            if observed < ready_at.astimezone(timezone.utc):
                raise MalformedBrokerPayload(
                    "Alpaca last_equity is not mature for the requested "
                    f"session until {ready_at.isoformat()}")
            if observed >= next_close.astimezone(timezone.utc):
                raise MalformedBrokerPayload(
                    "Alpaca last_equity no longer has an unambiguous T+1 "
                    "mapping to the requested session; read before the next "
                    f"XNYS close {next_close.isoformat()}")

        request_started_at = self._now()
        require_read_window(
            request_started_at, where="last-equity request start")
        before = await self._get("/v2/account")
        identity_before = self._account_identity(before)
        native_before = str(before.get("id") or "").strip()
        if not native_before:
            raise MalformedBrokerPayload(
                "Alpaca account payload has no native id for last-equity "
                "identity bracketing")
        equity_before = _required_dec(
            before.get("last_equity"), where="account last_equity")
        if equity_before <= 0:
            raise MalformedBrokerPayload(
                "account last_equity must be positive")

        after = await self._get("/v2/account")
        identity_after = self._account_identity(after)
        native_after = str(after.get("id") or "").strip()
        equity_after = _required_dec(
            after.get("last_equity"), where="account last_equity")
        request_completed_at = self._now()
        require_read_window(
            request_completed_at, where="last-equity request completion")
        if ((identity_before.broker, identity_before.account_id, native_before)
                != (identity_after.broker, identity_after.account_id,
                    native_after)):
            raise MalformedBrokerPayload(
                "Alpaca account identity changed around last-equity read")
        if equity_before != equity_after:
            raise MalformedBrokerPayload(
                "Alpaca last_equity changed inside the identity-stable read "
                f"bracket: {equity_before} -> {equity_after}")

        official_close_utc = official_close.astimezone(timezone.utc)
        query = (
            ("endpoint", "/v2/account"),
            ("field", "last_equity"),
            ("read_not_before", ready_at.isoformat()),
            ("read_before", next_close.isoformat()),
            ("source_session", session.isoformat()),
        )
        try:
            return BrokerCloseValuation(
                identity=identity_before,
                requested_session=session,
                equity=equity_before,
                source_timestamp=int(official_close_utc.timestamp()),
                source_timeframe="PREVIOUS_TRADING_DAY_1600_ET",
                source=ACCOUNT_LAST_EQUITY_SOURCE,
                semantics=ACCOUNT_LAST_EQUITY_SEMANTICS,
                request_started_at=request_started_at,
                request_completed_at=request_completed_at,
                query=query,
                source_timestamp_unit=ACCOUNT_LAST_EQUITY_TIMESTAMP_UNIT,
                valuation_at=official_close_utc,
                raw={
                    "before": dict(before),
                    "after": dict(after),
                    "native_source_timestamp": None,
                    "derived_valuation_at": official_close_utc.isoformat(),
                },
            )
        except (TypeError, ValueError) as exc:
            raise MalformedBrokerPayload(
                f"last-equity typed evidence is invalid: {exc}") from exc

    async def portfolio_history_close_probe(
            self, *, session: date) -> BrokerCloseValuation:
        """Retain the raw 1D REST fallback as a diagnostic-only probe.

        Its integer label remains intentionally opaque and the result has no
        accepted valuation time.  This endpoint is not silently substituted
        for ``last_equity`` when the explicit T+1 window is unavailable.
        """
        if type(session) is not date:
            raise MalformedBrokerPayload(
                "portfolio-history session must be a date")
        from sentinel.feed import calendar  # noqa: PLC0415

        opened, closed = calendar.session_window(session)
        params = {
            "start": opened.isoformat(),
            "end": closed.isoformat(),
            "timeframe": "1D",
            "intraday_reporting": "market_hours",
            "cashflow_types": "ALL",
        }
        query = tuple(sorted((key, str(value))
                             for key, value in params.items()))

        identity_before = await self.identify_account()
        request_started_at = self._now()
        payload = await self._get("/v2/account/portfolio/history", params)
        request_completed_at = self._now()
        identity_after = await self.identify_account()
        if ((identity_before.broker, identity_before.account_id)
                != (identity_after.broker, identity_after.account_id)):
            raise MalformedBrokerPayload(
                "Alpaca account identity changed around portfolio-history read: "
                f"{identity_before.broker}/{identity_before.account_id} -> "
                f"{identity_after.broker}/{identity_after.account_id}")
        return parse_portfolio_history_close(
            payload, identity=identity_before, requested_session=session,
            request_started_at=request_started_at,
            request_completed_at=request_completed_at, query=query)

    @staticmethod
    def _account_identity(payload: dict) -> BrokerAccountIdentity:
        if not isinstance(payload, dict):
            raise MalformedBrokerPayload("account payload must be an object")
        account_id = str(
            payload.get("account_number") or payload.get("id") or "")
        if not account_id:
            raise MalformedBrokerPayload(
                "account payload has no account_number or id")
        return BrokerAccountIdentity(
            broker="alpaca", account_id=account_id, raw=payload)

    async def resolve_instrument(self, *, security_id: str,
                                 symbol: str) -> BrokerInstrument:
        broker_symbol = self._to_symbol(symbol)
        payload = await self._get(
            f"/v2/assets/{quote(broker_symbol, safe='')}")
        if not isinstance(payload, dict):
            raise MalformedBrokerPayload(
                f"asset lookup for {symbol!r} must return an object")
        returned_symbol = str(payload.get("symbol") or "")
        asset_id = str(payload.get("id") or "")
        if not returned_symbol or not asset_id:
            raise MalformedBrokerPayload(
                f"asset lookup for {symbol!r} omitted symbol or stable asset id")
        if str(payload.get("status") or "").lower() != "active":
            raise MalformedBrokerPayload(
                f"asset {returned_symbol!r} is not active")
        if payload.get("tradable") is not True:
            raise MalformedBrokerPayload(
                f"asset {returned_symbol!r} is not tradable")
        instrument = self._instrument(returned_symbol, asset_id)
        if instrument.security_id != str(security_id):
            raise MalformedBrokerPayload(
                f"asset {returned_symbol!r}/{asset_id} resolves to permanent "
                f"security {instrument.security_id!r}, not requested "
                f"{security_id!r}")
        return instrument

    async def market_clock(self) -> AlpacaMarketClock:
        payload = await self._get("/v2/clock")
        if not isinstance(payload, dict):
            raise MalformedBrokerPayload(
                "market clock payload must be an object")
        return AlpacaMarketClock(
            timestamp=_required_aware_ts(
                payload.get("timestamp"), where="market clock timestamp"),
            is_open=_required_bool(payload, "is_open", where="market clock"),
            next_open=_required_aware_ts(
                payload.get("next_open"), where="market clock next_open"),
            next_close=_required_aware_ts(
                payload.get("next_close"), where="market clock next_close"))

    async def account_cash_activities(
            self, *, after: datetime,
            through: datetime) -> BrokerCashActivityBatch:
        floor = _required_aware_ts(after, where="cash activity lower boundary")
        upper = _required_aware_ts(
            through, where="cash activity upper boundary")
        if floor > upper:
            raise MalformedBrokerPayload(
                "cash activity lower boundary is later than upper boundary")
        activities: list[BrokerCashActivity] = []
        seen_ids: set[str] = set()
        page_token: Optional[str] = None
        last_id: Optional[str] = None
        for _page in range(MAX_ACTIVITY_PAGES):
            params = {
                "activity_types": ",".join(sorted(RECOGNIZED_ACTIVITY_TYPES)),
                "after": floor.isoformat(),
                "until": upper.isoformat(),
                "direction": "asc",
                "page_size": ACTIVITY_PAGE_SIZE,
            }
            if page_token:
                params["page_token"] = page_token
            page = await self._get("/v2/account/activities", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "account-activities response must be an array")
            if len(page) > ACTIVITY_PAGE_SIZE:
                raise MalformedBrokerPayload(
                    f"account-activities page contains {len(page)} rows for "
                    f"limit {ACTIVITY_PAGE_SIZE}")
            if not page:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=Completeness.COMPLETE,
                    last_activity_id=last_id)
            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "account-activities page contains a non-object row")
                activity_id = str(item.get("id") or "").strip()
                if not activity_id:
                    raise MalformedBrokerPayload(
                        "account activity row has no native activity id")
                if activity_id in seen_ids:
                    raise MalformedBrokerPayload(
                        "account-activities pagination repeated native id "
                        f"{activity_id}")
                activity_type = str(
                    item.get("activity_type") or "").upper()
                if activity_type not in RECOGNIZED_ACTIVITY_TYPES:
                    raise MalformedBrokerPayload(
                        f"account activity {activity_id} returned unexpected "
                        f"type {activity_type!r}")
                try:
                    activity_date = date.fromisoformat(
                        str(item.get("date") or "")[:10])
                except ValueError:
                    raise MalformedBrokerPayload(
                        f"account activity {activity_id} has invalid date "
                        f"{item.get('date')!r}") from None
                amount = _required_dec(
                    item.get("net_amount"),
                    where=f"account activity {activity_id} net_amount",
                    allow_negative=True)
                seen_ids.add(activity_id)
                page_ids.append(activity_id)
                last_id = activity_id
                activities.append(BrokerCashActivity(
                    activity_id=activity_id, activity_type=activity_type,
                    activity_date=activity_date, net_amount=amount, raw=item))
            if len(page) < ACTIVITY_PAGE_SIZE:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=Completeness.COMPLETE,
                    last_activity_id=last_id)
            next_token = page_ids[-1]
            if not next_token or next_token == page_token:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=Completeness.TRUNCATED,
                    last_activity_id=last_id)
            page_token = next_token
        log.warning(
            "sentinel: account-activity recovery hit the %d-page cap; "
            "reporting TRUNCATED", MAX_ACTIVITY_PAGES)
        return BrokerCashActivityBatch(
            activities=tuple(activities), processed_through=upper,
            completeness=Completeness.TRUNCATED,
            last_activity_id=last_id)

    async def observe(self) -> BrokerObservation:
        return await self._observe_snapshot()

    async def observe_with_terminal_recovery(
            self, *, submitted_after: datetime,
            processed_through: datetime) -> BrokerObservation:
        floor = _required_aware_ts(
            submitted_after, where="terminal recovery floor")
        checkpoint = _required_aware_ts(
            processed_through, where="processed terminal watermark")
        recovery_through = datetime.now(timezone.utc)
        if recovery_through < checkpoint:
            raise MalformedBrokerPayload(
                "terminal recovery clock is behind the durable processed "
                f"watermark ({recovery_through.isoformat()} < "
                f"{checkpoint.isoformat()}); refusing to skip broker history")
        return await self._observe_snapshot(
            terminal_floor=floor, recovery_through=recovery_through)

    async def _observe_snapshot(
            self, *, terminal_floor: Optional[datetime] = None,
            recovery_through: Optional[datetime] = None) -> BrokerObservation:
        # Account identity is part of the snapshot, not an adjacent fact. Check
        # it around each major phase so an A->B->A routing/credential flip is
        # detected before any observation can reach the journal.
        observation_started_at = datetime.now(timezone.utc)
        account_before = await self.identify_account()
        opened, complete_open_a = await self._list_open_orders()
        terminal_a: list[BrokerOrder] = []
        complete_terminal_a = True
        if terminal_floor is not None:
            terminal_a, complete_terminal_a = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        account_after_orders = await self.identify_account()
        positions_a = await self._list_positions()
        account_after_positions_a = await self.identify_account()
        reopened, complete_open_b = await self._list_open_orders()
        terminal_b: list[BrokerOrder] = []
        complete_terminal_b = True
        if terminal_floor is not None:
            terminal_b, complete_terminal_b = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        account_after_orders_b = await self.identify_account()
        # Alpaca's position view may lag a partial-fill update already visible
        # in both order reads.  Re-read positions after the stable order pair;
        # disagreement is an amber inconsistent snapshot, never unexplained
        # foreign activity or permission to mutate.
        positions_b = await self._list_positions()
        account_after_positions_b = await self.identify_account()
        accounts = (
            account_before, account_after_orders,
            account_after_positions_a, account_after_orders_b,
            account_after_positions_b)
        identity_keys = {(item.broker, item.account_id) for item in accounts}
        if len(identity_keys) != 1:
            raise MalformedBrokerPayload(
                "Alpaca account identity changed during one broker observation: "
                + ", ".join(f"{b}/{a}" for b, a in sorted(identity_keys)))
        orders, merged_a = _merge_order_sets(opened, terminal_a)
        recheck, merged_b = _merge_order_sets(reopened, terminal_b)
        completeness = Completeness.COMPLETE
        if not (complete_open_a and complete_open_b
                and complete_terminal_a and complete_terminal_b):
            completeness = Completeness.TRUNCATED
        elif (not merged_a or not merged_b
              or _fingerprint(recheck) != _fingerprint(orders)
              or _position_fingerprint(positions_b)
              != _position_fingerprint(positions_a)):
            completeness = Completeness.INCONSISTENT
        return BrokerObservation(
            observed_at=datetime.now(timezone.utc),
            started_at=observation_started_at, orders=tuple(recheck),
            positions=tuple(positions_b), completeness=completeness,
            terminal_recovery_through=recovery_through,
            account_identity=account_before)

    async def _list_open_orders(self):
        out: list[BrokerOrder] = []
        seen_ids: set[str] = set()
        before_order_id: Optional[str] = None
        for _page in range(MAX_PAGES):
            params = {"status": "open", "limit": PAGE_SIZE,
                      "direction": "desc"}
            if before_order_id:
                params["before_order_id"] = before_order_id
            page = await self._get("/v2/orders", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "open-order response must be an array")
            if len(page) > PAGE_SIZE:
                raise MalformedBrokerPayload(
                    f"open-order page contains {len(page)} rows for limit "
                    f"{PAGE_SIZE}")
            if not page:
                return out, True
            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "open-order page contains a non-object row")
                order_id = str(item.get("id") or "").strip()
                if not order_id:
                    raise MalformedBrokerPayload(
                        "open-order row has no broker order id")
                if order_id in seen_ids:
                    raise MalformedBrokerPayload(
                        f"open-order pagination repeated broker id {order_id}")
                seen_ids.add(order_id)
                page_ids.append(order_id)
                out.append(self._to_order(item))
            if len(page) < PAGE_SIZE:
                return out, True
            next_cursor = page_ids[-1]
            if not next_cursor or next_cursor == before_order_id:
                return out, False
            before_order_id = next_cursor
        log.warning(
            "sentinel: open order list hit the %d-page cap; reporting "
            "TRUNCATED rather than assuming completeness", MAX_PAGES)
        return out, False

    async def _list_closed_orders(self, *, floor: datetime,
                                  through: datetime):
        floor = _required_aware_ts(floor, where="terminal recovery floor")
        through = _required_aware_ts(
            through, where="terminal recovery upper boundary")
        if floor > through:
            raise MalformedBrokerPayload(
                "terminal recovery floor is later than its captured upper "
                "boundary")
        out: list[BrokerOrder] = []
        seen_ids: set[str] = set()
        before_order_id: Optional[str] = None
        previous_submitted: Optional[datetime] = None
        for _page in range(MAX_PAGES):
            params = {"status": "closed", "limit": PAGE_SIZE,
                      "direction": "desc"}
            if before_order_id:
                params["before_order_id"] = before_order_id
            page = await self._get("/v2/orders", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "closed-order response must be an array")
            if len(page) > PAGE_SIZE:
                raise MalformedBrokerPayload(
                    f"closed-order page contains {len(page)} rows for limit "
                    f"{PAGE_SIZE}")
            if not page:
                return out, True
            page_ids: list[str] = []
            oldest: Optional[datetime] = None
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "closed-order page contains a non-object row")
                order_id = str(item.get("id") or "").strip()
                if not order_id:
                    raise MalformedBrokerPayload(
                        "closed-order row has no broker order id")
                if order_id in seen_ids:
                    raise MalformedBrokerPayload(
                        "closed-order pagination repeated broker id "
                        f"{order_id}")
                seen_ids.add(order_id)
                page_ids.append(order_id)
                submitted = _required_aware_ts(
                    item.get("submitted_at"),
                    where=f"closed order {order_id} submitted_at")
                if (previous_submitted is not None
                        and submitted > previous_submitted):
                    raise MalformedBrokerPayload(
                        "closed-order pagination is not descending by "
                        f"submitted_at at broker order {order_id}")
                previous_submitted = submitted
                oldest = submitted
                if floor <= submitted <= through:
                    out.append(self._to_order(item))
            if len(page) < PAGE_SIZE:
                return out, True
            if oldest is not None and oldest < floor:
                return out, True
            next_cursor = page_ids[-1]
            if not next_cursor or next_cursor == before_order_id:
                return out, False
            before_order_id = next_cursor
        log.warning(
            "sentinel: closed-order recovery hit the %d-page cap before "
            "crossing %s; reporting TRUNCATED",
            MAX_PAGES, floor.isoformat())
        return out, False

    async def _list_positions(self):
        payload = await self._get("/v2/positions")
        if not isinstance(payload, list):
            raise MalformedBrokerPayload(
                "positions response must be an array")
        out: list[BrokerPosition] = []
        seen_security_ids: set[str] = set()
        for p in payload:
            if not isinstance(p, dict):
                raise MalformedBrokerPayload(
                    "positions response contains a non-object row")
            symbol = str(p.get("symbol") or "")
            qty = _required_dec(
                p.get("qty"), allow_negative=True,
                where=f"position {p.get('symbol')} qty")
            instrument = self._instrument(symbol, p.get("asset_id"))
            if instrument.security_id in seen_security_ids:
                raise MalformedBrokerPayload(
                    "positions response repeats permanent security "
                    f"{instrument.security_id}")
            seen_security_ids.add(instrument.security_id)
            out.append(BrokerPosition(instrument=instrument, quantity=qty))
        return out

    def _instrument(self, symbol: str, asset_id=None, *, as_of=None
                    ) -> BrokerInstrument:
        system_symbol = self._from_symbol(symbol)
        try:
            security_id = self._resolve(system_symbol, as_of)
        except TypeError:
            security_id = self._resolve(system_symbol)
        if security_id is None or not str(security_id).strip():
            raise MalformedBrokerPayload(
                f"instrument {symbol!r} has no permanent security identity")
        return BrokerInstrument(
            security_id=str(security_id), symbol=system_symbol,
            broker_id=str(asset_id) if asset_id else None)

    def _to_order(self, payload: dict) -> BrokerOrder:
        if not isinstance(payload, dict):
            raise MalformedBrokerPayload("order payload must be an object")
        symbol = str(payload.get("symbol") or "")
        raw_status = str(payload.get("status") or "")
        if is_anomalous_status(raw_status):
            log.warning(
                "sentinel: order %s reports %r; Sentinel never replaces "
                "orders, so external replacement remains blocking",
                payload.get("id"), raw_status)
        return BrokerOrder(
            broker_order_id=str(payload.get("id") or ""),
            client_key=payload.get("client_order_id") or None,
            instrument=self._instrument(
                symbol, payload.get("asset_id"),
                as_of=str(payload.get("submitted_at") or "")[:10] or None),
            side=_side(
                payload.get("side"), where=f"order {payload.get('id')} side"),
            state=map_status(raw_status),
            quantity=_required_dec(
                payload.get("qty"), where=f"order {payload.get('id')} qty"),
            filled_quantity=_required_dec(
                payload.get("filled_qty"),
                where=f"order {payload.get('id')} filled_qty"),
            filled_average_price=(
                _required_dec(
                    payload.get("filled_avg_price"),
                    where=f"order {payload.get('id')} filled_avg_price")
                if payload.get("filled_avg_price") not in (None, "") else None),
            submitted_at=_parse_ts(payload.get("submitted_at")),
            external_replacement=is_anomalous_status(raw_status),
            replaced_by=(str(payload["replaced_by"]).strip()
                         if payload.get("replaced_by") else None),
            replaces=(str(payload["replaces"]).strip()
                      if payload.get("replaces") else None),
            raw=payload)

    async def find_by_client_key(self, client_key: str) -> Optional[BrokerOrder]:
        try:
            payload = await self._get(
                "/v2/orders:by_client_order_id",
                {"client_order_id": client_key})
        except Exception as exc:  # noqa: BLE001
            if _is_not_found(exc):
                return None
            raise
        return self._to_order(payload) if payload else None

    def _validate_submit_response(
            self, payload, *, client_key: str,
            instrument: BrokerInstrument, side: Side,
            quantity: Decimal) -> BrokerOrder:
        """A 2xx may acknowledge only the exact economics Sentinel sent."""
        if not isinstance(payload, dict):
            raise IncompleteBrokerPayload(
                "successful submit response must be an order object")
        required = (
            "id", "client_order_id", "symbol", "side", "status", "qty",
            "filled_qty", "type", "time_in_force", "order_class",
            "extended_hours")
        missing = [
            key for key in required
            if key not in payload
            or payload[key] is None
            or (key != "extended_hours" and payload[key] == "")]
        if missing:
            raise IncompleteBrokerPayload(
                "successful submit response omitted acknowledgement fields: "
                + ", ".join(missing))
        order = self._to_order(payload)
        if not order.broker_order_id:
            raise IncompleteBrokerPayload(
                "successful submit response omitted broker order id")
        if order.client_key != client_key:
            raise MalformedBrokerPayload(
                f"successful submit returned client_order_id "
                f"{order.client_key!r}, expected {client_key!r}")
        if order.side is not side:
            raise MalformedBrokerPayload(
                f"successful submit returned side {order.side.value}, "
                f"expected {side.value}")
        if order.quantity != quantity:
            raise MalformedBrokerPayload(
                f"successful submit returned quantity {order.quantity}, "
                f"expected {quantity}")
        if order.instrument.security_id != instrument.security_id:
            raise MalformedBrokerPayload(
                "successful submit returned a different permanent security: "
                f"{order.instrument.security_id!r} != "
                f"{instrument.security_id!r}")
        if order.instrument.symbol != instrument.symbol:
            raise MalformedBrokerPayload(
                f"successful submit returned symbol {order.instrument.symbol!r}, "
                f"expected {instrument.symbol!r}")
        if (instrument.broker_id is not None
                and order.instrument.broker_id != instrument.broker_id):
            raise MalformedBrokerPayload(
                "successful submit returned stable asset id "
                f"{order.instrument.broker_id!r}, expected "
                f"{instrument.broker_id!r}")
        if str(payload.get("type") or "").lower() != "market":
            raise MalformedBrokerPayload(
                f"successful submit returned type {payload.get('type')!r}, "
                "expected 'market'")
        alias_type = payload.get("order_type")
        if alias_type is not None and str(alias_type).lower() != "market":
            raise MalformedBrokerPayload(
                f"successful submit returned order_type {alias_type!r}, "
                "expected 'market'")
        if str(payload.get("time_in_force") or "").lower() != "day":
            raise MalformedBrokerPayload(
                "successful submit did not confirm DAY time-in-force")
        if str(payload.get("order_class") or "").lower() != "simple":
            raise MalformedBrokerPayload(
                "successful submit did not confirm simple order class")
        if payload.get("extended_hours") is not False:
            raise MalformedBrokerPayload(
                "successful submit did not explicitly confirm "
                "extended_hours=false")
        return order

    async def submit(self, *, client_key: str, instrument: BrokerInstrument,
                     side: Side, quantity: Decimal) -> CommandOutcome:
        body = {
            "symbol": self._to_symbol(instrument.symbol),
            "qty": str(quantity),
            "side": "buy" if side is Side.BUY else "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_key,
            "order_class": "simple",
            "extended_hours": False,
        }
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(), json=body)
        except Exception as exc:  # noqa: BLE001
            return CommandOutcome(
                state=S.UNKNOWN, detail=f"{type(exc).__name__}: {exc}")

        if resp.status_code in (200, 201):
            try:
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                return CommandOutcome(
                    state=S.UNKNOWN,
                    detail=f"2xx response body unreadable: {type(exc).__name__}: {exc}")
            try:
                order = self._validate_submit_response(
                    payload, client_key=client_key, instrument=instrument,
                    side=side, quantity=quantity)
            except IncompleteBrokerPayload as exc:
                broker_order_id = (
                    str(payload.get("id") or "")
                    if isinstance(payload, dict) else "")
                return CommandOutcome(
                    state=S.UNKNOWN,
                    broker_order_id=broker_order_id or None,
                    detail=f"incomplete 2xx acknowledgement: {exc}")
            return _submit_outcome(order)
        return _submit_error_outcome(resp)

    async def cancel(self, broker_order_id: str) -> CommandOutcome:
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.delete(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            return CommandOutcome(
                state=S.UNKNOWN, detail=f"{type(exc).__name__}: {exc}")
        if resp.status_code in (200, 204):
            return CommandOutcome(
                state=S.ACKNOWLEDGED,
                broker_order_id=broker_order_id,
                detail="cancel accepted (unconfirmed)")
        if resp.status_code == 404:
            return CommandOutcome(state=S.REJECTED, detail="no such order")
        return CommandOutcome(
            state=S.UNKNOWN, detail=f"HTTP {resp.status_code}")

    async def recent_fills(self, since: datetime) -> Sequence[BrokerFill]:
        payload = await self._get(
            "/v2/account/activities/FILL", {"after": since.isoformat()})
        out = []
        for activity in payload or []:
            if not isinstance(activity, dict):
                continue
            out.append(BrokerFill(
                client_key=None,
                broker_order_id=str(activity.get("order_id") or ""),
                quantity=_required_dec(
                    activity.get("qty"),
                    where=f"activity {activity.get('id')} qty"),
                price=_required_dec(
                    activity.get("price"),
                    where=f"activity {activity.get('id')} price"),
                filled_at=_parse_ts(activity.get("transaction_time"))))
        return tuple(out)


def _fingerprint(orders) -> tuple:
    return tuple(sorted((
        order.broker_order_id, order.client_key or "",
        order.instrument.security_id, order.instrument.broker_id or "",
        order.side.value, str(order.quantity),
        order.state.value, str(order.filled_quantity),
        (str(order.filled_average_price)
         if order.filled_average_price is not None else ""),
        (order.submitted_at.isoformat()
         if order.submitted_at is not None else ""),
        order.external_replacement,
        order.replaced_by or "", order.replaces or "",
    ) for order in orders))


def _position_fingerprint(positions) -> tuple:
    return tuple(sorted((
        position.instrument.security_id,
        position.instrument.symbol,
        position.instrument.broker_id or "",
        str(position.quantity),
    ) for position in positions))


def _merge_order_sets(opened, closed) -> tuple[list, bool]:
    merged = {order.broker_order_id: order for order in opened}
    stable = True
    for order in closed:
        if order.broker_order_id in merged:
            stable = False
        merged[order.broker_order_id] = order
    return list(merged.values()), stable


def _is_not_found(exc) -> bool:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _required_aware_ts(value, *, where: str) -> datetime:
    parsed = value if isinstance(value, datetime) else _parse_ts(value)
    if parsed is None or parsed.tzinfo is None:
        raise MalformedBrokerPayload(
            f"{where} must be a parseable timezone-aware timestamp")
    return parsed.astimezone(timezone.utc)

_ACTIVITY_BUSINESS_TIME_FLOOR = datetime(1970, 1, 1, tzinfo=timezone.utc)
ACTIVITY_FILL_INTERVAL_SOURCE = "alpaca_trading_activity_sse_candidate"
ACTIVITY_FILL_INTERVAL_SEMANTICS = (
    "ALPACA_ACCOUNT_ACTIVITY_FIXED_EVENT_FRONTIER_UNACCEPTED_V1"
)
_OBSERVATION_PREFIX = "broker-observation:v3:"
_WITNESS_PREFIX = "terminal-recovery-witness:v3:"
_PROVENANCE_PREFIX = _OBSERVATION_PREFIX
_DB_INCARCERATION_CURSOR = "broker-recovery-db-incarnation:v1"
_DB_CURSOR = _DB_INCARCERATION_CURSOR

class ActivityCorrectionRequiresRecovery(RuntimeError):
    """A correction/bust needs reversal semantics before trading may continue."""

class RestoreGradeIncreaseDeferred(RuntimeError):
    """A database takeover has not yet made predecessor DAY orders harmless."""

def _loads_state(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"{where} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value

def _sse_events(text: str, *, malformed) -> tuple[dict, ...]:
    """Parse a bounded Alpaca SSE response; comments that signal loss refuse."""
    events: list[dict] = []
    data: list[str] = []

    def flush() -> None:
        if not data:
            return
        payload = "\n".join(data)
        data.clear()
        try:
            event = json.loads(payload)
        except Exception as exc:
            raise malformed("Activity SSE contained malformed JSON") from exc
        if not isinstance(event, dict):
            raise malformed("Activity SSE data event must be a JSON object")
        events.append(event)

    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith(":"):
            lowered = line.lower()
            if "dropped" in lowered or "internal server error" in lowered:
                raise malformed(
                    "Activity SSE reported message loss/server failure; "
                    "history is not complete")
            continue
        if line == "":
            flush()
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
            continue
        # event/id/retry fields are transport metadata. Unknown non-comment,
        # non-SSE fields are not ignored because doing so can hide corruption.
        if line.startswith(("event:", "id:", "retry:")):
            continue
        raise malformed(f"Activity SSE contained unknown line {line!r}")
    flush()
    return tuple(events)

def _json(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"{where} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value

@dataclass(frozen=True)
class AccountBoundObservation(contract.BrokerObservation):
    """Observation carrying the account identity that bracketed its reads."""

    account_identity: Optional[contract.BrokerAccountIdentity] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.account_identity is not None:
            if (not self.account_identity.broker
                    or not self.account_identity.account_id):
                raise ValueError("account-bound observation identity is incomplete")

@dataclass(frozen=True)
class NativeBrokerFill(contract.BrokerFill):
    """Fill whose broker-native activity id is the idempotency authority."""

    activity_id: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.activity_id is not None and not str(self.activity_id).strip():
            raise ValueError("native fill activity id must be non-empty")

OriginalAlpaca = AlpacaExecutionBroker

class HardenedAlpacaExecutionBroker(OriginalAlpaca):
    """Alpaca adapter with account, asset and activity evidence tightened."""

    def _validate_submit_response(
            self, payload, *, client_key: str,
            instrument: contract.BrokerInstrument,
            side: contract.Side, quantity: Decimal):
        # Alpaca represents a simple order as either "" or "simple".  PR
        # #184's validator accepted only the latter, turning a valid 2xx into
        # false uncertainty.  Normalize only this documented equivalence;
        # bracket/oco/oto values still fail closed in the original validator.
        if isinstance(payload, dict) and payload.get("order_class") == "":
            payload = dict(payload)
            payload["order_class"] = "simple"
        return super()._validate_submit_response(
            payload, client_key=client_key, instrument=instrument,
            side=side, quantity=quantity)

    async def account_cash_activities(
            self, *, after: datetime,
            through: datetime) -> BrokerCashActivityBatch:
        floor = _required_aware_ts(
            after, where="cash activity lower boundary")
        upper = _required_aware_ts(
            through, where="cash activity upper boundary")
        if floor > upper:
            raise MalformedBrokerPayload(
                "cash activity lower boundary is later than upper boundary")

        activities: list[BrokerCashActivity] = []
        seen_ids: set[str] = set()
        page_token: Optional[str] = None
        last_recognized_id: Optional[str] = None
        for _page in range(MAX_ACTIVITY_PAGES):
            # Category, not a fixed activity-type allowlist.  A vendor-added
            # non-zero cash type must reach Sentinel and become a refusal;
            # filtering it at the request would make the negative space
            # unknowable and could defeat cash authority.
            params = {
                "category": "non_trade_activity",
                "after": floor.isoformat(),
                "until": upper.isoformat(),
                "direction": "asc",
                "page_size": ACTIVITY_PAGE_SIZE,
            }
            if page_token:
                params["page_token"] = page_token
            page = await self._get("/v2/account/activities", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "account-activities response must be an array")
            if len(page) > ACTIVITY_PAGE_SIZE:
                raise MalformedBrokerPayload(
                    "account-activities page exceeds requested page size")
            if not page:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=contract.Completeness.COMPLETE,
                    last_activity_id=last_recognized_id)

            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "account-activities page contains a non-object row")
                activity_id = str(item.get("id") or "").strip()
                if not activity_id:
                    raise MalformedBrokerPayload(
                        "account activity row has no native activity id")
                if activity_id in seen_ids:
                    raise MalformedBrokerPayload(
                        "account-activities pagination repeated native id "
                        f"{activity_id}")
                seen_ids.add(activity_id)
                page_ids.append(activity_id)
                activity_type = str(
                    item.get("activity_type") or "").upper()
                amount = _required_dec(
                    item.get("net_amount"),
                    where=f"account activity {activity_id} net_amount",
                    allow_negative=True)
                if activity_type not in RECOGNIZED_ACTIVITY_TYPES:
                    if amount == 0:
                        # A non-cash corporate event is outside this cash
                        # ledger. Its native id still participates in page
                        # progress, but it does not pretend to be cash.
                        continue
                    raise MalformedBrokerPayload(
                        "unrecognized non-trade cash activity "
                        f"{activity_id}: type={activity_type!r}, "
                        f"net_amount={amount}")
                try:
                    activity_date = date.fromisoformat(
                        str(item.get("date") or "")[:10])
                except ValueError:
                    raise MalformedBrokerPayload(
                        f"account activity {activity_id} has invalid date "
                        f"{item.get('date')!r}") from None
                activities.append(BrokerCashActivity(
                    activity_id=activity_id,
                    activity_type=activity_type,
                    activity_date=activity_date,
                    net_amount=amount,
                    raw=item,
                ))
                last_recognized_id = activity_id

            if len(page) < ACTIVITY_PAGE_SIZE:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=contract.Completeness.COMPLETE,
                    last_activity_id=last_recognized_id)
            next_token = page_ids[-1]
            if not next_token or next_token == page_token:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=contract.Completeness.TRUNCATED,
                    last_activity_id=last_recognized_id)
            page_token = next_token

        return BrokerCashActivityBatch(
            activities=tuple(activities), processed_through=upper,
            completeness=contract.Completeness.TRUNCATED,
            last_activity_id=last_recognized_id)

    async def _recent_fills_bounded(
            self, since: datetime,
            through: Optional[datetime]) -> Sequence[contract.BrokerFill]:
        floor = _required_aware_ts(
            since, where="fill activity lower boundary")
        upper = (_required_aware_ts(
            through, where="fill activity upper boundary")
                 if through is not None else None)
        if upper is not None and floor > upper:
            raise MalformedBrokerPayload(
                "fill activity lower boundary is later than upper boundary")
        out: list[contract.BrokerFill] = []
        seen_ids: set[str] = set()
        page_token: Optional[str] = None
        for _page in range(MAX_ACTIVITY_PAGES):
            params = {
                "after": floor.isoformat(),
                "direction": "asc",
                "page_size": ACTIVITY_PAGE_SIZE,
            }
            if upper is not None:
                params["until"] = upper.isoformat()
            if page_token:
                params["page_token"] = page_token
            page = await self._get("/v2/account/activities/FILL", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "fill activities response must be an array")
            if len(page) > ACTIVITY_PAGE_SIZE:
                raise MalformedBrokerPayload(
                    "fill activities page exceeds requested page size")
            if not page:
                return tuple(out)
            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "fill activities page contains a non-object row")
                activity_id = str(item.get("id") or "").strip()
                if not activity_id:
                    raise MalformedBrokerPayload(
                        "fill activity has no broker-native id")
                if activity_id in seen_ids:
                    raise MalformedBrokerPayload(
                        "fill activity pagination repeated native id "
                        f"{activity_id}")
                seen_ids.add(activity_id)
                page_ids.append(activity_id)
                broker_order_id = str(item.get("order_id") or "").strip()
                if not broker_order_id:
                    raise MalformedBrokerPayload(
                        f"fill activity {activity_id} omitted order_id")
                out.append(NativeBrokerFill(
                    activity_id=activity_id,
                    client_key=None,
                    broker_order_id=broker_order_id,
                    quantity=_required_dec(
                        item.get("qty"),
                        where=f"activity {activity_id} qty"),
                    price=_required_dec(
                        item.get("price"),
                        where=f"activity {activity_id} price"),
                    filled_at=_parse_ts(
                        item.get("transaction_time")),
                ))
            if len(page) < ACTIVITY_PAGE_SIZE:
                return tuple(out)
            next_token = page_ids[-1]
            if not next_token or next_token == page_token:
                raise MalformedBrokerPayload(
                    "fill activity pagination cannot prove completeness")
            page_token = next_token
        raise MalformedBrokerPayload(
            "fill activity traversal hit its page cap; refusing to imply "
            "complete recovery history")

    async def recent_fills(
            self, since: datetime) -> Sequence[contract.BrokerFill]:
        return await self._recent_fills_bounded(since, None)

    async def _observe_snapshot(
            self, *, terminal_floor: Optional[datetime] = None,
            recovery_through: Optional[datetime] = None):
        # The base adapter already binds ordinary snapshots with identity
        # reads around every major phase.  This overlay needs an additional
        # outer fence only when it adds fill-activity recovery work.
        if terminal_floor is None:
            return await super()._observe_snapshot(
                terminal_floor=terminal_floor,
                recovery_through=recovery_through)
        account_before = await self.identify_account()
        observed = await super()._observe_snapshot(
            terminal_floor=terminal_floor,
            recovery_through=recovery_through)

        # A fill activity is keyed to when the economic event occurred, not
        # to the order's ancient submitted_at.  Join a newly reported fill
        # back to its exact order so a CANCELLED/FILLED command cannot age
        # out of closed-order pagination and then mutate silently (#127).
        orders = list(observed.orders)
        known_order_ids = {o.broker_order_id for o in orders}
        if terminal_floor is not None:
            fills = await self._recent_fills_bounded(
                terminal_floor, recovery_through)
            for fill in fills:
                if fill.broker_order_id in known_order_ids:
                    continue
                payload = await self._get(
                    f"/v2/orders/{quote(fill.broker_order_id, safe='')}")
                if not isinstance(payload, dict):
                    raise MalformedBrokerPayload(
                        "late-fill exact order lookup returned no order object")
                order = self._to_order(payload)
                if order.broker_order_id != fill.broker_order_id:
                    raise MalformedBrokerPayload(
                        "late-fill exact order lookup changed broker order id")
                orders.append(order)
                known_order_ids.add(order.broker_order_id)

        account_after = await self.identify_account()
        completeness = observed.completeness
        if (account_after.broker != account_before.broker
                or account_after.account_id != account_before.account_id):
            completeness = contract.Completeness.INCONSISTENT

        return AccountBoundObservation(
            observed_at=observed.observed_at,
            started_at=observed.started_at,
            orders=tuple(orders),
            positions=tuple(observed.positions),
            completeness=completeness,
            terminal_recovery_through=observed.terminal_recovery_through,
            account_identity=account_before,
        )

CurrentAlpaca = HardenedAlpacaExecutionBroker

class FinancialGradeAlpacaExecutionBroker(CurrentAlpaca):
    """Alpaca adapter using stable asset identity and unified Activity SSE."""

    # The generic flag historically implied more than Alpaca can prove from
    # open-order REST enumeration after a stale restore. Ordinary pagination
    # remains usable, but restore-grade safety is supplied by the independent
    # DB-incarnation/DAY-order fence below, not by this claim.
    capabilities = replace(
        CurrentAlpaca.capabilities,
        complete_order_pagination=False,
        recent_fill_history=False,
    )
    restore_grade_order_recovery = False
    account_snapshot_freshness = False
    # Candidate parser only. Alpaca's current changelog lists Activity SSE
    # for the Trading API, but method presence and documentation cannot
    # prove that this paper account's APCA credentials can reach the stream.
    # Keep every authority claim false until a real reachable account-bound
    # NAS integration passes acceptance; production guards cannot call it.
    financial_activity_sse = False
    candidate_financial_activity_sse = True
    candidate_account_fill_interval_evidence = True
    account_fill_interval_nas_accepted = False

    async def submit(
            self, *, client_key: str,
            instrument: contract.BrokerInstrument,
            side: contract.Side,
            quantity: Decimal) -> contract.CommandOutcome:
        if not instrument.broker_id:
            raise BrokerAuthorityRefused(
                "Alpaca submit requires the durable broker asset_id; "
                "ticker-only mutation is not certified")
        # Alpaca's create-order `symbol` parameter accepts an asset ID. Use
        # that stable handle directly so a symbol remap cannot retarget the
        # mutation between the final identity read and POST.
        body = {
            "symbol": str(instrument.broker_id),
            "qty": str(quantity),
            "side": "buy" if side is contract.Side.BUY else "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_key,
            "order_class": "simple",
            "extended_hours": False,
        }
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(), json=body)
        except Exception as exc:                          # noqa: BLE001
            return contract.CommandOutcome(
                state=CommandState.UNKNOWN,
                detail=f"{type(exc).__name__}: {exc}")

        if resp.status_code in (200, 201):
            try:
                payload = resp.json()
            except Exception as exc:                      # noqa: BLE001
                return contract.CommandOutcome(
                    state=CommandState.UNKNOWN,
                    detail=("2xx response body unreadable: "
                            f"{type(exc).__name__}: {exc}"))
            try:
                order = self._validate_submit_response(
                    payload, client_key=client_key,
                    instrument=instrument, side=side, quantity=quantity)
            except IncompleteBrokerPayload as exc:
                broker_order_id = (
                    str(payload.get("id") or "")
                    if isinstance(payload, dict) else "")
                return contract.CommandOutcome(
                    state=CommandState.UNKNOWN,
                    broker_order_id=broker_order_id or None,
                    detail=f"incomplete 2xx acknowledgement: {exc}")
            return _submit_outcome(order)
        return _submit_error_outcome(resp)

    async def _bounded_activity_events(
            self, *, after: datetime,
            through: datetime,
            since_event_id: Optional[str] = None,
            verify_fixed_frontier: bool = False) -> tuple[dict, ...]:
        floor = _required_aware_ts(
            after, where="Activity SSE lower boundary")
        upper = _required_aware_ts(
            through, where="Activity SSE upper boundary")
        if floor > upper:
            raise MalformedBrokerPayload(
                "Activity SSE lower boundary exceeds upper boundary")
        account = await self.identify_account()
        account_uuid = str(account.raw.get("id") or "").strip()
        if not account_uuid:
            raise MalformedBrokerPayload(
                "Alpaca account payload has no UUID for Activity SSE binding")
        headers = dict(self._headers())
        headers["Accept"] = "text/event-stream"

        async def request(params: Mapping[str, str]) -> tuple[dict, ...]:
            try:
                async with self._httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(
                        f"{self.base_url}/v2beta1/events/activities",
                        headers=headers, params=dict(params))
            except Exception as exc:                      # noqa: BLE001
                raise RuntimeError(
                    "Activity SSE transport failed: "
                    f"{type(exc).__name__}: {exc}") from exc
            if resp.status_code in (401, 403):
                raise AlpacaCredentialsRefused(
                    "Activity SSE authority refused with HTTP "
                    f"{resp.status_code}")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Activity SSE returned HTTP {resp.status_code}")
            events = tuple(_sse_events(
                resp.text, malformed=MalformedBrokerPayload))
            seen_event: set[str] = set()
            seen_ref: set[str] = set()
            prior_event = ""
            for event in events:
                event_id = str(event.get("event_id") or "").strip()
                ref_id = str(event.get("ref_id") or "").strip()
                event_account = str(event.get("account_id") or "").strip()
                if not event_id or not ref_id:
                    raise MalformedBrokerPayload(
                        "Activity SSE event omitted event_id/ref_id")
                if event_account != account_uuid:
                    raise MalformedBrokerPayload(
                        "Activity SSE event belongs to another account")
                # The cash and fill consumers below are USD ledgers and
                # accept only completed economic state changes.  Alpaca's
                # common envelope requires both fields; silently accepting
                # a missing/foreign currency would interpret local-currency
                # ``net_amount``/``price`` values as USD, while accepting a
                # non-final status could book economics before completion.
                currency = str(event.get("currency") or "").strip().upper()
                if currency != "USD":
                    raise MalformedBrokerPayload(
                        f"Activity SSE event {event_id} currency "
                        f"{currency or '<missing>'!r} is not USD")
                status = str(event.get("status") or "").strip().lower()
                if status != "executed":
                    raise MalformedBrokerPayload(
                        f"Activity SSE event {event_id} status "
                        f"{status or '<missing>'!r} is not executed")
                business_at = _required_aware_ts(
                    event.get("at"),
                    where=f"Activity SSE {event_id} business time")
                if not (floor <= business_at <= upper):
                    raise MalformedBrokerPayload(
                        f"Activity SSE event {event_id} business time lies "
                        "outside the requested bounded snapshot")
                _required_aware_ts(
                    event.get("executed_at"),
                    where=f"Activity SSE {event_id} execution time")
                settle_date = event.get("settle_date")
                try:
                    if not isinstance(settle_date, str):
                        raise TypeError
                    date.fromisoformat(settle_date)
                except (TypeError, ValueError) as exc:
                    raise MalformedBrokerPayload(
                        f"Activity SSE event {event_id} settle_date is "
                        "not an ISO date") from exc
                if event_id in seen_event:
                    raise MalformedBrokerPayload(
                        f"Activity SSE repeated event_id {event_id}")
                if ref_id in seen_ref:
                    raise MalformedBrokerPayload(
                        f"Activity SSE repeated ref_id {ref_id}")
                if prior_event and event_id <= prior_event:
                    raise MalformedBrokerPayload(
                        "Activity SSE event_id order is not strictly monotonic")
                seen_event.add(event_id)
                seen_ref.add(ref_id)
                prior_event = event_id
                if not isinstance(event.get("details"), dict):
                    raise MalformedBrokerPayload(
                        f"Activity SSE event {event_id} has no details object")
            return events

        # Timestamp filters establish only a *bounded snapshot*. They are
        # not a replay cursor because Alpaca filters business time (`at`),
        # while delayed/backfilled events append later in event_id order.
        snapshot = await request({
            "since": floor.isoformat(), "until": upper.isoformat()})
        if since_event_id is None:
            if verify_fixed_frontier:
                # Freeze the discovery response at its native publication
                # frontier, then demand a byte-for-byte equivalent replay.
                # For an empty account there is no event id to name, so the
                # exact bounded empty query is repeated instead.  Neither
                # case claims that a later backfill cannot append after the
                # captured frontier.
                if snapshot:
                    replay = await request({
                        "until_id": str(snapshot[-1]["event_id"])})
                else:
                    replay = await request({
                        "since": floor.isoformat(),
                        "until": upper.isoformat(),
                    })
                if replay != snapshot:
                    raise MalformedBrokerPayload(
                        "Activity SSE fixed-frontier replay disagreed with "
                        "its exhaustive discovery snapshot")
            return snapshot
        cursor = str(since_event_id).strip()
        if not cursor:
            raise MalformedBrokerPayload(
                "Activity SSE since_event_id must be non-empty")
        if not snapshot:
            # A retained cursor proves at least one event was previously
            # visible.  An empty exhaustive discovery snapshot contradicts
            # that retained source; treating it as "no changes" would hide
            # source truncation, account drift, or a vendor regression.
            raise MalformedBrokerPayload(
                "Activity SSE exhaustive discovery omitted the retained "
                "event cursor")
        upper_event_id = str(snapshot[-1]["event_id"])
        if upper_event_id < cursor:
            raise MalformedBrokerPayload(
                "Activity SSE bounded upper event_id regressed")
        if upper_event_id == cursor:
            return ()

        replay = await request({
            "since_id": cursor, "until_id": upper_event_id})
        if not replay or str(replay[-1]["event_id"]) != upper_event_id:
            raise MalformedBrokerPayload(
                "Activity SSE cursor replay did not reach its bounded upper id")
        if str(replay[0]["event_id"]) < cursor:
            raise MalformedBrokerPayload(
                "Activity SSE cursor replay crossed behind its durable id")
        return replay

    async def account_cash_activities(
            self, *, after: datetime,
            through: datetime,
            since_event_id: Optional[str] = None
            ) -> broker_cash.BrokerCashActivityBatch:
        requested_floor = _required_aware_ts(
            after, where="cash activity lower boundary")
        upper = _required_aware_ts(
            through, where="cash activity upper boundary")
        if requested_floor > upper:
            raise MalformedBrokerPayload(
                "cash activity lower boundary exceeds upper boundary")
        events = await self._bounded_activity_events(
            # Never use the caller's business-time baseline for discovery.
            # Publication-order replay begins only after this exhaustive
            # snapshot has captured the current upper event_id.
            after=_ACTIVITY_BUSINESS_TIME_FLOOR, through=through,
            since_event_id=since_event_id)
        activities: list[broker_cash.BrokerCashActivity] = []
        last_ref: Optional[str] = None
        for event in events:
            previous_id = str(event.get("previous_id") or "").strip()
            details = event["details"]
            execution_type = str(details.get("execution_type") or "").lower()
            if previous_id or execution_type in {"trade_correct", "trade_bust"}:
                # Correction/bust arithmetic must reverse the prior ref_id.
                # Until that reversal is represented in the durable ledger,
                # treating the new event as another positive fill is unsafe.
                raise ActivityCorrectionRequiresRecovery(
                    "Activity SSE reported a correction/bust; cash/fill "
                    "authority is fenced until the prior ref_id is reversed")
            activity_type = str(event.get("activity_type") or "").upper()
            activity_subtype = str(
                event.get("activity_subtype") or "").upper()
            if activity_type == "TRD":
                # Sentinel's exact durable fill ledger already applies
                # trade notional to plan cash. Adding the Activity-SSE TRD
                # net_amount here would book the same purchase/sale twice.
                # The enclosing batch still advances its event_id cursor;
                # corrections/busts were refused above.
                continue
            if activity_type in {"ACATS", "FOPT", "JNLS"}:
                # These move securities across the owned account boundary.
                # A cash-only ledger cannot value or time-weight that
                # external in-kind flow, so it must never be silently
                # treated as strategy performance.
                raise broker_cash.BrokerCashAuthorityRefused(
                    "Activity SSE reported an unweighted external "
                    f"securities transfer ({activity_type})")
            if activity_type not in broker_cash.RECOGNIZED_ACTIVITY_TYPES:
                # Missing net_amount is not evidence that a newly added
                # vendor activity type has no economic effect. Refuse the
                # unknown taxonomy before any field-based filtering.
                raise MalformedBrokerPayload(
                    "unrecognized Activity SSE cash/economic type "
                    f"{activity_type!r}")
            raw_amount = event.get("net_amount")
            if raw_amount is None:
                cash_amount_required = (
                    activity_type in (
                        broker_cash.EXTERNAL_ACTIVITY_TYPES
                        | frozenset({
                            "FEE", "CFEE", "INT", "INTNRA", "INTTW",
                            "WH", "CGD", "PTC", "PTR", "FIMAT",
                            "OPASN", "OPEXC", "OPTRD", "OPCSH",
                        }))
                    or (activity_type.startswith("DIV")
                        and activity_subtype != "SDIV")
                    or (activity_type == "MA"
                        and activity_subtype in {"CMA", "SCMA"})
                    or (activity_type == "OPCA"
                        and (activity_subtype.endswith("CMA")
                             or activity_subtype == "DIV.CDIV")))
                if cash_amount_required:
                    raise MalformedBrokerPayload(
                        "Activity SSE cash event "
                        f"{event.get('event_id')} ({activity_type}) "
                        "omitted net_amount")
                continue
            amount = _required_dec(
                raw_amount,
                where=f"Activity SSE {event.get('event_id')} net_amount",
                allow_negative=True)
            if amount == 0:
                continue
            # The common-envelope validator above has already established
            # that this is the broker's required exact settlement date.
            # Execution time is not a substitute: changing which session
            # owns an external flow changes time-weighted performance.
            activity_date = date.fromisoformat(event["settle_date"])
            ref_id = str(event["ref_id"])
            activities.append(broker_cash.BrokerCashActivity(
                activity_id=ref_id,
                activity_type=activity_type,
                activity_date=activity_date,
                net_amount=amount,
                raw=event,
            ))
            last_ref = ref_id
        return broker_cash.BrokerCashActivityBatch(
            activities=tuple(activities),
            processed_through=upper,
            completeness=contract.Completeness.COMPLETE,
            last_activity_id=last_ref,
            last_event_id=(str(events[-1]["event_id"])
                           if events else since_event_id),
        )

    async def account_fill_interval_evidence(
            self, *, session: date,
            interval_start: datetime
            ) -> contract.BrokerFillIntervalEvidence:
        """Return a fixed-frontier, account-wide NAS acceptance candidate.

        ``Completeness.COMPLETE`` describes the terminated, exhaustively
        replayed snapshot through the captured boundary.  It is not cash or
        late-publication finality: the deliberately non-certified semantics
        and false capability bit prevent trial persistence until the paper
        endpoint and its correction/finality behavior pass NAS acceptance.
        """
        if type(session) is not date:
            raise MalformedBrokerPayload(
                "fill interval requested session must be a date")
        requested_floor = _required_aware_ts(
            interval_start, where="fill interval lower boundary")
        from sentinel.feed import calendar  # noqa: PLC0415

        _opened, official_close = calendar.session_window(session)
        close_utc = official_close.astimezone(timezone.utc)
        if requested_floor > close_utc:
            raise MalformedBrokerPayload(
                "fill interval begins after the requested official XNYS "
                "close")

        request_started_at = self._now()
        processed_through = request_started_at
        if processed_through < close_utc:
            raise MalformedBrokerPayload(
                "fill interval cannot be observed before the requested "
                "official XNYS close")

        identity_before = await self.identify_account()
        native_before = str(
            identity_before.raw.get("id") or "").strip()
        if not native_before:
            raise MalformedBrokerPayload(
                "Alpaca account payload has no UUID for fill-interval "
                "identity bracketing")
        events = await self._bounded_activity_events(
            after=_ACTIVITY_BUSINESS_TIME_FLOOR,
            through=processed_through,
            verify_fixed_frontier=True)
        identity_after = await self.identify_account()
        native_after = str(identity_after.raw.get("id") or "").strip()
        request_completed_at = self._now()
        if request_completed_at < request_started_at:
            raise MalformedBrokerPayload(
                "Alpaca observation clock regressed during fill interval")
        if ((identity_before.broker, identity_before.account_id,
             native_before)
                != (identity_after.broker, identity_after.account_id,
                    native_after)):
            raise MalformedBrokerPayload(
                "Alpaca account identity changed around Activity SSE "
                "fill-interval read")

        fills: list[contract.BrokerAccountFill] = []
        for event in events:
            details = event["details"]
            previous_id = str(event.get("previous_id") or "").strip()
            execution_type = str(
                details.get("execution_type") or "").strip().lower()
            if (previous_id
                    or execution_type in {"trade_correct", "trade_bust"}):
                raise ActivityCorrectionRequiresRecovery(
                    "Activity SSE reported a correction/bust inside the "
                    "account history; append-only fill evidence is refused")
            if str(event.get("activity_type") or "").upper() != "TRD":
                continue
            if execution_type != "fill":
                raise MalformedBrokerPayload(
                    "TRD Activity SSE event has an unsupported or missing "
                    f"execution_type {execution_type or '<missing>'!r}")

            event_id = str(event["event_id"])
            ref_id = str(event["ref_id"])
            order_id = str(details.get("order_id") or "").strip()
            asset_id = str(details.get("asset_id") or "").strip()
            symbol = str(details.get("symbol") or "").strip()
            side = str(details.get("side") or "").strip().lower()
            if not order_id:
                raise MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} omitted details.order_id")
            if not asset_id or not symbol or side not in {"buy", "sell"}:
                raise MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} omitted native asset/"
                    "symbol/side identity")
            client_value = details.get("client_order_id")
            client_key = (None if client_value is None else
                          str(client_value).strip())
            if client_value is not None and not client_key:
                raise MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} has an empty "
                    "details.client_order_id")

            quantity = _required_dec(
                event.get("qty"), where=f"TRD {event_id} qty")
            price = _required_dec(
                event.get("price"), where=f"TRD {event_id} price")
            if quantity <= 0 or price <= 0:
                raise MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} quantity and price must "
                    "be positive")
            executed_at = _required_aware_ts(
                event.get("executed_at"),
                where=f"TRD {event_id} executed_at")
            if executed_at > processed_through:
                raise MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} executes after the "
                    "fixed processed-through boundary")
            if executed_at < requested_floor:
                continue
            fills.append(contract.BrokerAccountFill(
                activity_id=ref_id,
                broker_order_id=order_id,
                client_key=client_key,
                quantity=quantity,
                price=price,
                filled_at=executed_at,
                raw=dict(event),
            ))

        fills.sort(key=lambda fill: (fill.filled_at, fill.activity_id))
        upper_event_id = (
            str(events[-1]["event_id"]) if events else "<EMPTY>")
        return contract.BrokerFillIntervalEvidence(
            identity=identity_before,
            requested_session=session,
            interval_start=requested_floor,
            processed_through=processed_through,
            fills=tuple(fills),
            completeness=contract.Completeness.COMPLETE,
            source=ACTIVITY_FILL_INTERVAL_SOURCE,
            semantics=ACTIVITY_FILL_INTERVAL_SEMANTICS,
            request_started_at=request_started_at,
            request_completed_at=request_completed_at,
            query=(
                ("endpoint", "/v2beta1/events/activities"),
                ("since", _ACTIVITY_BUSINESS_TIME_FLOOR.isoformat()),
                ("until", processed_through.isoformat()),
                ("upper_event_id", upper_event_id),
            ),
            raw={
                "events": [dict(event) for event in events],
                "upper_event_id": upper_event_id,
                "fixed_frontier_replayed": True,
                "late_publication_finality": False,
                "nas_acceptance_required": True,
            },
        )

    async def candidate_fill_interval_evidence(
            self, *, session: date,
            interval_start: datetime
            ) -> contract.BrokerFillIntervalEvidence:
        """Explicit acceptance-harness spelling for the guarded method."""
        return await self.account_fill_interval_evidence(
            session=session, interval_start=interval_start)

    async def _recent_fills_bounded(
            self, since: datetime,
            through: Optional[datetime]) -> Sequence[contract.BrokerFill]:
        upper = through or datetime.now(timezone.utc)
        requested_floor = _required_aware_ts(
            since, where="fill activity lower boundary")
        if requested_floor > upper:
            raise MalformedBrokerPayload(
                "fill activity lower boundary exceeds upper boundary")
        # Terminal recovery cannot resume fill publication by business
        # timestamp: a fill may be backfilled after the durable terminal
        # watermark with an older ``at``/``executed_at``. Until fill
        # recovery owns its own durable event_id cursor, a bounded recovery
        # read deliberately traverses the complete Activity-SSE lifetime.
        # The unbounded diagnostic method retains its caller's time filter.
        event_floor = (
            _ACTIVITY_BUSINESS_TIME_FLOOR
            if through is not None else requested_floor)
        events = await self._bounded_activity_events(
            after=event_floor, through=upper)
        fills: list[contract.BrokerFill] = []
        for event in events:
            if str(event.get("activity_type") or "").upper() != "TRD":
                continue
            details = event["details"]
            execution_type = str(details.get("execution_type") or "fill").lower()
            if (event.get("previous_id")
                    or execution_type in {"trade_correct", "trade_bust"}):
                raise ActivityCorrectionRequiresRecovery(
                    "trade correction/bust cannot be flattened into an "
                    "append-only fill history")
            order_id = str(details.get("order_id") or "").strip()
            if not order_id:
                raise MalformedBrokerPayload(
                    "TRD Activity SSE event omitted details.order_id")
            fills.append(NativeBrokerFill(
                activity_id=str(event["ref_id"]),
                client_key=(str(details.get("client_order_id"))
                            if details.get("client_order_id") else None),
                broker_order_id=order_id,
                quantity=_required_dec(
                    event.get("qty"),
                    where=f"TRD {event.get('event_id')} qty"),
                price=_required_dec(
                    event.get("price"),
                    where=f"TRD {event.get('event_id')} price"),
                filled_at=_required_aware_ts(
                    event.get("executed_at"),
                    where=f"TRD {event.get('event_id')} executed_at"),
            ))
        return tuple(fills)

    async def recent_fills(
            self, since: datetime) -> Sequence[contract.BrokerFill]:
        # Method remains available for diagnostics/reconciliation, but the
        # capability flag is intentionally false because a correction/bust
        # produces an explicit refusal rather than a lossy accounting row.
        return await self._recent_fills_bounded(
            since, datetime.now(timezone.utc))

    async def legacy_rest_recent_fills_probe(
            self, since: datetime) -> Sequence[contract.BrokerFill]:
        """Raw Account Activities REST fallback, diagnostic only."""
        return await super().recent_fills(since)

# Public adapter identity. Existing importers continue to ask for
# AlpacaExecutionBroker and receive the complete final class directly.
AlpacaExecutionBroker = FinancialGradeAlpacaExecutionBroker

def database_incarnation(conn, *, initialize: bool = True):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (pg_control_system()).system_identifier::text,"
            " (pg_control_checkpoint()).timeline_id")
        system_identifier, timeline_id = cur.fetchone()
        cur.execute(
            "SELECT takeover_epoch,updated_at,broker,broker_account_id"
            " FROM sentinel_account_binding WHERE id=1")
        binding_row = cur.fetchone()
    if binding_row is None:
        raise RuntimeError("database incarnation check has no account binding")
    current = {
        "kind": "broker-recovery-db-incarnation/v1",
        "system_identifier": str(system_identifier),
        "timeline_id": int(timeline_id),
        "takeover_epoch": int(binding_row[0]),
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (_DB_INCARCERATION_CURSOR,),
        )
        row = cur.fetchone()
    if row is None:
        if not initialize:
            return None, current, binding_row
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,CURRENT_DATE,%s::jsonb)",
                (_DB_INCARCERATION_CURSOR,
                 json.dumps(current, sort_keys=True)),
            )
        conn.commit()
        return current, current, binding_row
    prior = _loads_state(row[0], where="database incarnation cursor")
    expected_keys = {"kind", "system_identifier", "timeline_id", "takeover_epoch"}
    if (set(prior) != expected_keys
            or prior.get("kind") != "broker-recovery-db-incarnation/v1"):
        raise RuntimeError("database incarnation cursor has unknown shape")
    return prior, current, binding_row

def _base_restore_increase_fence_reason(conn, deployment, today: date) -> str:
    prior, current, binding_row = database_incarnation(conn)
    assert prior is not None
    bound_epoch = int(binding_row[0])
    updated_at = binding_row[1]
    if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
        return "durable account binding has no trustworthy takeover timestamp"
    if (str(binding_row[2]) != deployment.broker
            or str(binding_row[3]) != deployment.broker_account_id
            or bound_epoch != deployment.takeover_epoch):
        return "execution deployment does not match the durable account binding"

    changed = (
        prior["system_identifier"] != current["system_identifier"]
        or int(prior["timeline_id"]) != int(current["timeline_id"])
    )
    if changed:
        if bound_epoch <= int(prior["takeover_epoch"]):
            return (
                "PostgreSQL incarnation/timeline changed since the last "
                "broker-recovery anchor. An explicit adopt-restored-account "
                "takeover is required before any exposure increase")
        # The operator acknowledged this new physical DB incarnation by
        # advancing the takeover epoch. Bind the new anchor to that epoch.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_processed_sessions SET session=CURRENT_DATE,"
                " state=%s::jsonb,updated_at=NOW() WHERE cursor_name=%s",
                (json.dumps(current, sort_keys=True),
                 _DB_INCARCERATION_CURSOR),
            )
        conn.commit()

    # The predecessor can still have an omitted working order after an
    # acknowledged takeover. Sentinel submits DAY orders only. Refuse BUYs
    # through the adoption calendar date; the next XNYS session is therefore
    # after every predecessor DAY order's contractual expiry boundary.
    if bound_epoch > 1 and today <= updated_at.date():
        return (
            "restored-account takeover occurred on "
            f"{updated_at.date().isoformat()}; exposure increases wait "
            "until a later session so predecessor DAY orders cannot remain "
            "executable even if Alpaca open-order enumeration omitted one")
    return ""

def upgrade_restore_reason(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (_DB_CURSOR,),
        )
        anchor = cur.fetchone()
        cur.execute(
            "SELECT takeover_epoch FROM sentinel_account_binding WHERE id=1")
        bound = cur.fetchone()
        cur.execute(
            "SELECT to_regclass('public.sentinel_backup_recovery_markers')")
        marker_relation = cur.fetchone()[0]
        marker_count = 0
        if marker_relation is not None:
            cur.execute("SELECT COUNT(*) FROM sentinel_backup_recovery_markers")
            marker_count = int(cur.fetchone()[0])
    if bound is None:
        return "restore-grade recovery has no durable account binding"
    if anchor is None and marker_count > 0 and int(bound[0]) <= 1:
        return (
            "backup-capable behavioral database predates the physical "
            "incarnation anchor. One explicit adopt-restored-account "
            "takeover is required before exposure increases; this prevents "
            "an already-restored database from silently self-certifying")
    return ""

def postmaster_day_order_fence_reason(
        conn, today, *, recovery_generation=None) -> str:
    try:
        opened, closed = calendar.session_window(today)
    except calendar.NonSessionDate:
        # Non-session dates are already non-executable at the paper gateway;
        # this fence does not manufacture a calendar answer.
        return ""
    except Exception as exc:                                  # noqa: BLE001
        requested = getattr(today, "isoformat", lambda: str(today))()
        return (
            "restore-grade DAY-order recovery cannot evaluate its XNYS "
            "calendar fence; exposure increases are blocked: "
            f"calendar={calendar.calendar_version()}, session={requested}, "
            f"recovery_generation={recovery_generation}, "
            f"error={type(exc).__module__}.{type(exc).__qualname__}: {exc}")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_postmaster_start_time()")
        row = cur.fetchone()
    if row is None or row[0] is None:
        return (
            "PostgreSQL start time is unavailable; restore-grade unknown "
            "DAY-order recovery cannot authorize exposure increases")
    started = row[0]
    if started.tzinfo is None:
        return (
            "PostgreSQL start time is timezone-naive; restore-grade unknown "
            "DAY-order recovery cannot authorize exposure increases")
    started = started.astimezone(opened.tzinfo)
    if opened <= started < closed:
        return (
            "PostgreSQL restarted during XNYS session "
            f"{today.isoformat()} at {started.isoformat()}. Exposure "
            "increases wait for a later session so any broker DAY order "
            "missing from a restored journal must have expired")
    return ""

def provenance_name(seq: int) -> str:
    return f"{_PROVENANCE_PREFIX}{int(seq)}"

def witness_name(broker_name: str, account_id: str) -> str:
    return f"{_WITNESS_PREFIX}{broker_name}:{account_id}"

def load_provenance(conn, seq: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (provenance_name(seq),),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"broker observation {seq} has no account/asset provenance")
    state = _json(row[0], where=f"broker observation {seq} provenance")
    if (state.get("kind") != "broker-observation/v3"
            or state.get("observation_seq") != int(seq)):
        raise RuntimeError(
            f"broker observation {seq} provenance shape is invalid")
    return state

def durable_covers_observed(*, command_row, observed_order: dict) -> bool:
    state = CommandState(str(command_row[5]))
    observed_state = CommandState(str(observed_order.get("state")))
    durable_filled = Decimal(str(command_row[7]))
    observed_filled = Decimal(
        str(observed_order.get("filled_quantity") or "0"))
    if durable_filled < observed_filled:
        return False
    # Terminal broker evidence must have been synchronized exactly. A
    # terminal command cannot legitimately move again later, so this check
    # remains stable forever.
    if observed_state in TERMINAL and state is not observed_state:
        return False
    # Nonterminal positive broker evidence cannot still be represented as a
    # local pre-transport state. Any later broker-facing/UNKNOWN state is a
    # processed state and may legitimately progress after this witness.
    if state in {CommandState.PLANNED, CommandState.SEND_PENDING}:
        return False
    return True

def completion_proof(conn, through: datetime):
    through = journal._aware_utc(through, "terminal recovery witness")
    broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seq,observed_at FROM sentinel_observations"
            " WHERE terminal_recovery_through=%s AND completeness='COMPLETE'"
            " ORDER BY seq DESC",
            (through,),
        )
        candidates = cur.fetchall()

    for seq_raw, observed_at in candidates:
        seq = int(seq_raw)
        try:
            provenance = load_provenance(conn, seq)
        except RuntimeError:
            continue
        if (provenance.get("broker") != broker_name
                or provenance.get("account_id") != account_id
                or provenance.get("terminal_recovery_through")
                != through.isoformat()
                or provenance.get("completeness") != "COMPLETE"):
            continue

        immutable_commands = []
        complete = True
        for order in provenance.get("orders", []):
            key = order.get("client_key")
            if not is_sentinel_key(key):
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT security_id,symbol,broker_instrument_id,side,"
                    " quantity,state,broker_order_id,filled_quantity,"
                    " filled_average_price FROM sentinel_commands"
                    " WHERE client_key=%s",
                    (key,),
                )
                command = cur.fetchone()
            if command is None:
                complete = False
                break
            immutable = {
                "client_key": str(key),
                "security_id": str(command[0]),
                "symbol": str(command[1]),
                "broker_id": None if command[2] is None else str(command[2]),
                "side": str(command[3]),
                "quantity": str(command[4]),
                "broker_order_id": (
                    None if command[6] is None else str(command[6])),
            }
            observed_immutable = {
                "client_key": str(key),
                "security_id": str(order.get("security_id")),
                "symbol": str(order.get("symbol")),
                "broker_id": order.get("broker_id"),
                "side": str(order.get("side")),
                "quantity": str(order.get("quantity")),
                "broker_order_id": str(order.get("broker_order_id")),
            }
            if immutable != observed_immutable:
                complete = False
                break
            if not durable_covers_observed(
                    command_row=command, observed_order=order):
                complete = False
                break
            immutable_commands.append(immutable)
        if not complete:
            continue

        evidence = {
            "kind": "terminal-recovery-completion/v3",
            "observation_seq": seq,
            "observed_at": journal._aware_utc(
                observed_at, "broker observation").isoformat(),
            "processed_through": through.isoformat(),
            "provenance": provenance,
            "immutable_commands": sorted(
                immutable_commands, key=lambda item: item["client_key"]),
        }
        digest = hashlib.sha256(json.dumps(
            evidence, sort_keys=True, separators=(",", ":"),
            default=str).encode("utf-8")).hexdigest()
        return seq, digest
    return None

def strict_checkpoint(conn) -> datetime:
    broker_name, account_id, established_at = (
        journal._terminal_recovery_binding(conn))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT broker,broker_account_id,processed_through"
            " FROM sentinel_terminal_recovery_watermark WHERE id=1")
        row = cur.fetchone()
    if row is None:
        return established_at
    if str(row[0]) != broker_name or str(row[1]) != account_id:
        raise RuntimeError(
            "terminal recovery watermark belongs to another account")
    processed = journal._aware_utc(
        row[2], "terminal recovery checkpoint")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (witness_name(broker_name, account_id),),
        )
        witness_row = cur.fetchone()
    if witness_row is None:
        # v1/v2/naked timestamps are not completion authority. Replay from
        # binding establishment once and earn a v3 witness.
        return established_at
    state = _json(
        witness_row[0], where="terminal recovery completion witness")
    proof = completion_proof(conn, processed)
    if proof is None:
        raise RuntimeError(
            "terminal recovery witness has no completed broker observation")
    seq, digest = proof
    expected = {
        "kind": "terminal-recovery-witness/v3",
        "broker": broker_name,
        "account_id": account_id,
        "processed_through": processed.isoformat(),
        "observation_seq": seq,
        "completion_sha256": digest,
    }
    if state != expected:
        raise RuntimeError(
            "terminal recovery watermark/completion witness disagree")
    return processed

def strict_floor(conn) -> datetime:
    return strict_checkpoint(conn) - journal.TERMINAL_RECOVERY_OVERLAP

def strict_advance(conn, through: datetime) -> datetime:
    candidate = journal._aware_utc(
        through, "terminal recovery upper boundary")
    current = strict_checkpoint(conn)
    processed = max(current, candidate)
    broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
    proof = completion_proof(conn, processed)
    if proof is None:
        raise RuntimeError(
            "terminal recovery cannot advance: every Sentinel order in "
            "the exact COMPLETE observation is not yet durably reconciled")
    seq, digest = proof
    state = {
        "kind": "terminal-recovery-witness/v3",
        "broker": broker_name,
        "account_id": account_id,
        "processed_through": processed.isoformat(),
        "observation_seq": seq,
        "completion_sha256": digest,
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_terminal_recovery_watermark"
            " (id,broker,broker_account_id,processed_through)"
            " VALUES (1,%s,%s,%s)"
            " ON CONFLICT (id) DO UPDATE SET"
            " broker=EXCLUDED.broker,broker_account_id=EXCLUDED.broker_account_id,"
            " processed_through=EXCLUDED.processed_through,updated_at=NOW()",
            (broker_name, account_id, processed),
        )
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO UPDATE SET"
            " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
            (witness_name(broker_name, account_id),
             processed.date().isoformat(),
             json.dumps(state, sort_keys=True)),
        )
    conn.commit()
    return processed

def execution_increase_fence_reason(*, conn, deployment, today) -> str:
    """Return the first Alpaca increase fence in certified execution order."""
    if deployment.broker != "alpaca":
        return ""
    return (
        _base_restore_increase_fence_reason(conn, deployment, today)
        or upgrade_restore_reason(conn)
        or postmaster_day_order_fence_reason(
            conn, today, recovery_generation=deployment.takeover_epoch)
    )


def restore_increase_fence_reason(conn, deployment, today) -> str:
    """Operator diagnostic preserving the prior public precedence."""
    return (
        postmaster_day_order_fence_reason(
            conn, today, recovery_generation=deployment.takeover_epoch)
        or upgrade_restore_reason(conn)
        or _base_restore_increase_fence_reason(conn, deployment, today)
    )

__all__ = [
    "AccountBoundObservation",
    "ActivityCorrectionRequiresRecovery",
    "AlpacaExecutionBroker",
    "FinancialGradeAlpacaExecutionBroker",
    "NativeBrokerFill",
    "RestoreGradeIncreaseDeferred",
    "database_incarnation",
    "execution_increase_fence_reason",
    "postmaster_day_order_fence_reason",
    "restore_increase_fence_reason",
    "strict_advance",
    "strict_checkpoint",
    "strict_floor",
]
