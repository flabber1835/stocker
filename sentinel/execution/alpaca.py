"""Alpaca transport mapped onto Sentinel's fail-closed execution contract.

Transport ambiguity is never an economic rejection.  A request timeout, rate
limit or server failure can mean that an order exists at Alpaca even when the
caller did not receive a usable acknowledgement, so those outcomes remain
UNKNOWN until the deterministic client key is resolved.  Conversely, broker
evidence that positively contradicts the durable order economics is malformed
and is never accepted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence
from urllib.parse import quote

from sentinel.execution.broker_cash import (
    BrokerCashActivity, BrokerCashActivityBatch, RECOGNIZED_ACTIVITY_TYPES)
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerCapabilities,
    BrokerCloseValuation, BrokerFill, BrokerInstrument, BrokerObservation,
    BrokerOrder, BrokerPosition, CommandOutcome, Completeness, ExecutionBroker,
    MalformedBrokerEvidence, Side)
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.states import CommandState as S

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
        return CommandOutcome(
            state=S.REJECTED,
            detail=f"HTTP {status} documented order refusal: {detail}")
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
        account_bound_observation=True,
        fractional_quantities=True,
        minimum_quantity_increment=Decimal("0.000000001"),
        market_on_open=False,
    )
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
        order.instrument.security_id, order.side.value, str(order.quantity),
        order.state.value, str(order.filled_quantity),
        (str(order.filled_average_price)
         if order.filled_average_price is not None else ""),
        (order.submitted_at.isoformat()
         if order.submitted_at is not None else ""),
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
