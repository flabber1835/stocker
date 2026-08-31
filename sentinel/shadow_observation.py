"""Broker-free, commitment-bearing forward observation of canonical state.

This module has one economic job: advance :class:`SessionState` through the
same :func:`sentinel.core.kernel.advance_session` function used by production,
after an XNYS session
has become a published corpus fact.  It deliberately has no broker seam.  The
pure/store-generic boundary can produce only ``CANDIDATE``/``NOT_DEPLOYABLE``.
Only :class:`PostgresShadowRuntime`, which owns the real publication pin and
reruns the complete corpus gates, may promote that exact result to
``SHADOW_GO``/``VERIFIED``.  Neither verdict can become order authority.

The durable record is an application-append-only hash chain.  Every row binds
the explicit research capital, strategy identity, initial canonical state,
published input, prior state and resulting canonical state.  A restart verifies
the whole retained chain before it advances.  Missing sessions, changed rows,
changed publication/input bytes and self-consistent-looking state under the
wrong session or strategy all refuse.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol, Sequence

from sentinel.controller.frozen_rule import ControllerConfig
from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session as advance_state
from sentinel.core.production import (
    DefensiveBar, PublishedSession, SessionState, load_published_session)
from sentinel.feed import calendar


SHADOW_GO = "SHADOW_GO"
VERIFIED = "VERIFIED"
CANDIDATE = "CANDIDATE"
NOT_DEPLOYABLE = "NOT_DEPLOYABLE"
FULLY_PUBLISHED = "FULLY_PUBLISHED"
BEFORE_NEXT_OPEN = "BEFORE_NEXT_OPEN"
# V3 assigns every effective-open entitlement of the prior-close Core book to
# the old scalar allocation: ex-date receivables plus exact cash/stock terminal
# consideration. V1 measured dividends only at the close; V2 corrected that
# distribution boundary but still measured terminal transformations after the
# allocation change. The commitment-bound name prevents either old lineage
# from silently resuming under the corrected ownership semantics.
SHADOW_EXECUTION_MODEL = "PROSPECTIVE_CONCORDANCE_SCALAR_CORE_BIL_V3"
SHADOW_CUTOFF_POLICY = "STRICT_BEFORE_OFFICIAL_NEXT_XNYS_OPEN_V1"
SHADOW_WARMUP_SESSIONS = 252

RECORD_SCHEMA = "sentinel.shadow-observation/1"
GENESIS_SCHEMA = "sentinel.shadow-observation-genesis/1"
PUBLICATION_SCHEMA = "sentinel.shadow-publication/1"
RUNTIME_AUTHORITY_SCHEMA = "sentinel.shadow-runtime-authority/1"
STRATEGY_ECONOMICS_SCHEMA = "sentinel.shadow-strategy-economics/1"
ECONOMIC_INPUT_SCHEMA = "sentinel.shadow-economic-input/1"
WARMUP_INPUT_SCHEMA = "sentinel.shadow-warmup-economic-input/1"
POSTGRES_CURSOR_PREFIX = "shadow-observation:v1:"

_OBSERVATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RECORD_FIELDS = frozenset({
    "schema", "observation_id", "session", "shadow_verdict",
    "verification", "spec_sha256", "starting_cash", "first_session",
    "strategy_identity", "runtime_identity", "activation_timing",
    "execution_model", "cutoff_policy", "controller", "initial_state_sha256",
    "initial_strategy_economics", "warmup_input_identity_sha256",
    "previous_record_sha256", "prior_state_sha256", "publication",
    "input_sha256", "economic_input_identity", "state", "state_sha256",
    "strategy_economics", "record_sha256",
})


class ShadowObservationRefused(RuntimeError):
    """The forward result cannot be labelled verified."""


class ShadowObservationStore(Protocol):
    """Small persistence seam; implementations append and return every row."""

    def genesis(self) -> Mapping[str, Any] | None: ...

    def append_genesis(self, genesis: Mapping[str, Any]) -> None: ...

    def records(self) -> Sequence[Mapping[str, Any]]: ...

    def append(self, record: Mapping[str, Any]) -> None: ...


class FullyPublishedSessionSource(Protocol):
    """Source seam whose only positive result is a completed publication."""

    def load_fully_published(
            self, session: str, *, known_feed_security_ids: Sequence[str] = ()
            ) -> "FullyPublishedSession | None": ...


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ShadowObservationRefused(
            f"shadow observation value is not canonical JSON: {exc}") from exc


def _canonical_value(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _cash_text(value: Decimal | str | int | float) -> str:
    if isinstance(value, bool):
        raise ShadowObservationRefused(
            "shadow starting cash must be an explicit positive decimal")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowObservationRefused(
            "shadow starting cash must be an explicit positive decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise ShadowObservationRefused(
            "shadow starting cash must be an explicit positive decimal")
    return format(amount.normalize(), "f")


def _observation_id(value: str) -> str:
    text = str(value)
    if not _OBSERVATION_ID.fullmatch(text):
        raise ShadowObservationRefused(
            "observation_id must be 1-64 ASCII letters, digits, dots or hyphens")
    return text


def _utc_instant(value: Any, *, where: str) -> datetime:
    if isinstance(value, datetime):
        instant = value
    elif isinstance(value, str):
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ShadowObservationRefused(
                f"{where} is not an ISO timestamp") from exc
    else:
        raise ShadowObservationRefused(f"{where} is not an ISO timestamp")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ShadowObservationRefused(f"{where} is not timezone-aware")
    return instant.astimezone(timezone.utc)


def _utc_text(value: Any, *, where: str) -> str:
    return _utc_instant(value, where=where).isoformat().replace("+00:00", "Z")


def _timing_proof(
        value: Mapping[str, Any], *, decision_session: str,
        committed: bool, where: str) -> dict:
    raw = _as_mapping(value, where=where)
    fields = {
        "schema", "decision_session", "execution_session", "observed_at",
        "execution_open_at", "status"}
    if committed:
        fields.add("candidate_committed_at")
    if set(raw) != fields:
        raise ShadowObservationRefused(f"{where} has an unknown shape")
    expected_execution = _next_session(decision_session)
    expected_open, _close = calendar.session_window(expected_execution)
    expected_open_text = _utc_text(
        expected_open, where=f"{where} expected execution open")
    observed = _utc_instant(raw.get("observed_at"), where=f"{where} observed_at")
    cutoff = _utc_instant(
        raw.get("execution_open_at"), where=f"{where} execution_open_at")
    if (raw.get("decision_session") != decision_session
            or raw.get("execution_session") != expected_execution
            or raw.get("execution_open_at") != expected_open_text
            or raw.get("status") != BEFORE_NEXT_OPEN
            or observed >= cutoff):
        raise ShadowObservationRefused(
            f"{where} does not prove commitment before the following XNYS open")
    if committed:
        committed_at = _utc_instant(
            raw.get("candidate_committed_at"),
            where=f"{where} candidate_committed_at")
        if committed_at < observed or committed_at >= cutoff:
            raise ShadowObservationRefused(
                f"{where} does not prove candidate commit before the following "
                "XNYS open")
    return _canonical_value(raw)


def _xnys_session(value: str, *, where: str) -> str:
    text = str(value)
    try:
        sessions = calendar.sessions_in_range(text, text)
    except Exception as exc:  # the calendar is authority; no fallback axis
        raise ShadowObservationRefused(
            f"{where} is not provably an XNYS session: {text!r}") from exc
    if sessions != [text]:
        raise ShadowObservationRefused(
            f"{where} is not an XNYS session: {text!r}")
    return text


def _next_session(session: str) -> str:
    try:
        return calendar.next_session(session)
    except Exception as exc:
        raise ShadowObservationRefused(
            f"next XNYS session after {session} is unavailable") from exc


def _as_mapping(value: Any, *, where: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ShadowObservationRefused(f"{where} is not JSON") from exc
    if not isinstance(value, Mapping):
        raise ShadowObservationRefused(f"{where} is not an object")
    return _canonical_value(dict(value))


def _positive_decimal(value: Any, *, where: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowObservationRefused(f"{where} is not a decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ShadowObservationRefused(
            f"{where} must be finite and positive")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _strategy_prices(
        value: Any, *, session: str, previous_value: Any = None) -> dict:
    if isinstance(value, DefensiveBar):
        raw = _canonical_value(asdict(value))
        if (raw.get("session") != session
                or raw.get("security_id") != "SENTINEL:BIL"
                or raw.get("ticker") != "BIL"):
            raise ShadowObservationRefused(
                f"defensive bar identity is incoherent at {session}")
        raw = {
            "bil_open_signal": raw["open_signal"],
            "bil_close_signal": raw["close_signal"],
            "bil_close_unadjusted": raw["close_unadjusted"],
            "bil_close_adjusted": raw["close_adjusted"],
        }
        if not isinstance(previous_value, DefensiveBar):
            raise ShadowObservationRefused(
                f"defensive bar lacks its same-publication predecessor at "
                f"{session}")
        previous = _canonical_value(asdict(previous_value))
        previous_session = previous.get("session")
        if (previous.get("security_id") != "SENTINEL:BIL"
                or previous.get("ticker") != "BIL"
                or not isinstance(previous_session, str)
                or _next_session(previous_session) != session):
            raise ShadowObservationRefused(
                f"defensive predecessor is not the adjacent XNYS row at "
                f"{session}")
        raw.update({
            "bil_previous_session": previous_session,
            "bil_previous_close_adjusted": previous.get("close_adjusted"),
        })
    else:
        raw = _as_mapping(value, where=f"Core+BIL prices for {session}")
    source_fields = {
        "bil_open_signal", "bil_close_signal", "bil_close_unadjusted",
        "bil_close_adjusted", "bil_previous_close_adjusted"}
    identity_fields = {"bil_previous_session"}
    expected = source_fields | identity_fields
    if set(raw) not in (expected, expected | {"bil_open_adjusted"}):
        raise ShadowObservationRefused(
            f"Core+BIL prices have an unknown shape at {session}")
    previous_session = raw.get("bil_previous_session")
    if (not isinstance(previous_session, str)
            or _next_session(previous_session) != session):
        raise ShadowObservationRefused(
            f"Core+BIL prices lack the adjacent current-publication "
            f"denominator at {session}")
    values = {
        key: _positive_decimal(raw[key], where=f"{key} at {session}")
        for key in source_fields}
    adjusted_open = (
        values["bil_open_signal"] * values["bil_close_adjusted"]
        / values["bil_close_signal"])
    if "bil_open_adjusted" in raw:
        claimed = _positive_decimal(
            raw["bil_open_adjusted"],
            where=f"bil_open_adjusted at {session}")
        if claimed != adjusted_open:
            raise ShadowObservationRefused(
                f"BIL adjusted open disagrees with published domains at {session}")
    return {
        **{key: _decimal_text(values[key]) for key in sorted(values)},
        "bil_previous_session": previous_session,
        "bil_open_adjusted": _decimal_text(adjusted_open),
    }


def _published_input_value(
        published: PublishedSession,
        strategy_prices: Mapping[str, Any] | None = None) -> dict:
    """Canonical, order-stable commitment to every engine input field."""
    if not isinstance(published, PublishedSession):
        raise ShadowObservationRefused(
            "fully published input is not a canonical PublishedSession")

    def row(value: Any) -> Any:
        return asdict(value) if is_dataclass(value) else value

    bars = sorted(
        (row(item) for item in published.bars),
        key=lambda item: (str(item.get("security_id")),
                          str(item.get("ticker"))))
    terminals = sorted(
        (row(item) for item in published.terminal_events),
        key=lambda item: (str(item.get("security_id")),
                          str(item.get("kind")), str(item.get("reference"))))
    anchors = {
        str(key): row(value)
        for key, value in sorted(published.feed_anchors.items())
    }
    return _canonical_value({
        "session": published.session,
        "data_version": published.data_version,
        "bars": bars,
        "meta": {
            str(key): row(value)
            for key, value in sorted(published.meta.items())
        },
        "sectors": {
            str(key): value for key, value in sorted(published.sectors.items())
        },
        "spy_closeadj": list(published.spy_closeadj),
        "spy_sessions": list(published.spy_sessions),
        "spy_expected_sessions": list(published.spy_expected_sessions),
        "terminal_events": terminals,
        "feed_anchors": anchors,
        "defensive_bar": (
            None if published.defensive_bar is None
            else row(published.defensive_bar)),
        "defensive_previous_bar": (
            None if published.defensive_previous_bar is None
            else row(published.defensive_previous_bar)),
        "strategy_prices": _strategy_prices(
            strategy_prices if strategy_prices is not None else
            published.defensive_bar, session=published.session,
            previous_value=(
                None if strategy_prices is not None else
                published.defensive_previous_bar)),
    })


def _finite_decimal(value: Any, *, where: str) -> Decimal:
    if isinstance(value, bool):
        raise ShadowObservationRefused(f"{where} is not a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowObservationRefused(
            f"{where} is not a finite decimal") from exc
    if not result.is_finite():
        raise ShadowObservationRefused(f"{where} is not a finite decimal")
    return result


def _optional_decimal_text(
        value: Any, *, where: str, positive: bool = False,
        nonnegative: bool = False) -> str | None:
    if value is None:
        return None
    result = _finite_decimal(value, where=where)
    if ((positive and result <= 0)
            or (nonnegative and result < 0)):
        raise ShadowObservationRefused(
            f"{where} is outside its economic price/quantity domain")
    return _decimal_text(result)


def _economic_input_identity(
        published: PublishedSession,
        strategy_prices: Mapping[str, Any] | None = None) -> dict:
    """Compact economic identity for cross-publication revision detection.

    The original full-input SHA remains the audit commitment.  This second
    identity has exactly two normalization exceptions that are economically
    invariant under Sharadar's routine total-return rebasing:

    * SPY's dated 41-session path is divided by its first positive close.
    * BIL compares exact raw domains plus overnight/intraday adjusted factors.

    SEP/Core prices, actions and session-effective identity remain exact.  The
    canonical raw-compatible volume is represented by raw-close dollar
    liquidity rather than by volume alone, because Sharadar's adjusted close
    and reported volume are inversely rescaled by later splits.
    """
    source = _published_input_value(published, strategy_prices)
    session = _xnys_session(
        published.session, where="economic-input session")

    bars: list[dict] = []
    for index, bar in enumerate(sorted(
            published.bars,
            key=lambda item: (str(item.security_id), str(item.ticker)))):
        raw_close_text = _optional_decimal_text(
            bar.raw_close, where=f"bar {index} raw close", positive=True)
        raw_open_text = _optional_decimal_text(
            bar.raw_open, where=f"bar {index} raw open", positive=True)
        volume = (None if bar.volume is None else _finite_decimal(
            bar.volume, where=f"bar {index} raw-compatible volume"))
        if volume is not None and volume < 0:
            raise ShadowObservationRefused(
                f"bar {index} raw-compatible volume is negative")
        liquidity = None
        if raw_close_text is not None and volume is not None:
            raw_close = Decimal(raw_close_text)
            if volume > 0:
                liquidity = _decimal_text(raw_close * volume)
        bars.append({
            "session": str(bar.session),
            "security_id": str(bar.security_id),
            "ticker": str(bar.ticker),
            "raw_close": raw_close_text,
            "raw_open": raw_open_text,
            "raw_dollar_liquidity": liquidity,
            "split_ratio": _decimal_text(_positive_decimal(
                bar.split_ratio, where=f"bar {index} split ratio")),
            "dividend_per_share": _optional_decimal_text(
                bar.dividend_per_share,
                where=f"bar {index} dividend per share", nonnegative=True),
            "tradeable": bool(bar.tradeable),
            "unresolved_corporate_action": bool(
                bar.unresolved_corporate_action),
        })

    spy_sessions = list(published.spy_sessions)
    spy_expected = list(published.spy_expected_sessions)
    if (not spy_sessions or len(spy_sessions) != len(published.spy_closeadj)
            or spy_sessions != spy_expected or spy_sessions[-1] != session):
        raise ShadowObservationRefused(
            f"SPY economic path is not the exact dated axis at {session}")
    spy_values = [
        _positive_decimal(value, where=f"SPY close {index} at {session}")
        for index, value in enumerate(published.spy_closeadj)
    ]
    spy_anchor = spy_values[0]
    spy_path = {
        "sessions": spy_sessions,
        "expected_sessions": spy_expected,
        "normalized_close_path": [
            _decimal_text(value / spy_anchor) for value in spy_values],
    }

    current = published.defensive_bar
    previous = published.defensive_previous_bar
    if not isinstance(current, DefensiveBar) or not isinstance(
            previous, DefensiveBar):
        raise ShadowObservationRefused(
            f"BIL economic path is incomplete at {session}")
    canonical_prices = _strategy_prices(
        current, session=session, previous_value=previous)
    supplied_prices = _strategy_prices(
        strategy_prices if strategy_prices is not None else canonical_prices,
        session=session)
    if supplied_prices != canonical_prices:
        raise ShadowObservationRefused(
            f"BIL strategy prices differ from published source rows at {session}")

    def raw_bar(value: DefensiveBar, *, where: str) -> dict:
        return {
            "session": value.session,
            "security_id": value.security_id,
            "ticker": value.ticker,
            "open_signal": _decimal_text(_positive_decimal(
                value.open_signal, where=f"{where} open signal")),
            "close_signal": _decimal_text(_positive_decimal(
                value.close_signal, where=f"{where} close signal")),
            "close_unadjusted": _decimal_text(_positive_decimal(
                value.close_unadjusted,
                where=f"{where} unadjusted close")),
        }

    bil_open = _positive_decimal(
        canonical_prices["bil_open_adjusted"],
        where=f"BIL adjusted open at {session}")
    bil_close = _positive_decimal(
        canonical_prices["bil_close_adjusted"],
        where=f"BIL adjusted close at {session}")
    bil_previous_close = _positive_decimal(
        canonical_prices["bil_previous_close_adjusted"],
        where=f"prior BIL adjusted close at {session}")
    identity = {
        "schema": ECONOMIC_INPUT_SCHEMA,
        "session": session,
        "bars_sha256": _sha256(bars),
        "meta_sha256": _sha256(source["meta"]),
        "sectors_sha256": _sha256(source["sectors"]),
        "terminal_events_sha256": _sha256(source["terminal_events"]),
        "feed_anchors_sha256": _sha256(source["feed_anchors"]),
        "spy_ratio_path_sha256": _sha256(spy_path),
        "bil": {
            "current_raw": raw_bar(current, where="current BIL"),
            "previous_raw": raw_bar(previous, where="previous BIL"),
            "overnight_factor": _decimal_text(
                bil_open / bil_previous_close),
            "intraday_factor": _decimal_text(bil_close / bil_open),
        },
    }
    identity["economic_input_sha256"] = _sha256(identity)
    return _canonical_value(identity)


def _validate_economic_input_identity(value: Any, *, session: str) -> dict:
    identity = _as_mapping(value, where=f"economic input at {session}")
    fields = {
        "schema", "session", "bars_sha256", "meta_sha256",
        "sectors_sha256", "terminal_events_sha256", "feed_anchors_sha256",
        "spy_ratio_path_sha256", "bil", "economic_input_sha256",
    }
    digest_fields = {
        "bars_sha256", "meta_sha256", "sectors_sha256",
        "terminal_events_sha256", "feed_anchors_sha256",
        "spy_ratio_path_sha256", "economic_input_sha256",
    }
    payload = {key: item for key, item in identity.items()
               if key != "economic_input_sha256"}
    bil = identity.get("bil")
    if (set(identity) != fields
            or identity.get("schema") != ECONOMIC_INPUT_SCHEMA
            or identity.get("session") != session
            or any(not isinstance(identity.get(key), str)
                   or not _SHA256.fullmatch(identity[key])
                   for key in digest_fields)
            or identity["economic_input_sha256"] != _sha256(payload)
            or not isinstance(bil, Mapping)
            or set(bil) != {
                "current_raw", "previous_raw", "overnight_factor",
                "intraday_factor"}):
        raise ShadowObservationRefused(
            f"economic input identity is incoherent at {session}")
    for name in ("current_raw", "previous_raw"):
        raw = bil.get(name)
        if (not isinstance(raw, Mapping)
                or set(raw) != {
                    "session", "security_id", "ticker", "open_signal",
                    "close_signal", "close_unadjusted"}):
            raise ShadowObservationRefused(
                f"BIL economic identity is incoherent at {session}")
    _positive_decimal(
        bil.get("overnight_factor"), where="BIL overnight factor")
    _positive_decimal(
        bil.get("intraday_factor"), where="BIL intraday factor")
    return identity


def _validate_warmup_input_identity(
        value: Any, *, first_session: str) -> dict:
    """Validate the compact commitment to the seed's causal input corpus."""
    identity = _as_mapping(value, where="shadow warm-up economic input")
    fields = {
        "schema", "first_warmup_session", "last_warmup_session",
        "session_count", "sessions_sha256", "bars_sha256",
        "metadata_mode", "metadata_sha256", "warmup_input_sha256",
    }
    digest_fields = {
        "sessions_sha256", "bars_sha256", "metadata_sha256",
        "warmup_input_sha256",
    }
    payload = {key: item for key, item in identity.items()
               if key != "warmup_input_sha256"}
    first_warmup = identity.get("first_warmup_session")
    last_warmup = identity.get("last_warmup_session")
    try:
        axis = calendar.sessions_in_range(
            str(first_warmup), str(last_warmup))
    except Exception as exc:
        raise ShadowObservationRefused(
            "shadow warm-up session axis is unavailable") from exc
    if (set(identity) != fields
            or identity.get("schema") != WARMUP_INPUT_SCHEMA
            or identity.get("session_count") != SHADOW_WARMUP_SESSIONS
            or identity.get("metadata_mode") not in {
                "CAUSAL_METADATA_TIMELINE",
                "PROSPECTIVE_STATIC_FEATURE_METADATA",
            }
            or len(axis) != SHADOW_WARMUP_SESSIONS
            or not axis
            or axis[0] != first_warmup
            or axis[-1] != last_warmup
            or _next_session(str(last_warmup)) != first_session
            or identity.get("sessions_sha256") != _sha256(axis)
            or any(not isinstance(identity.get(key), str)
                   or not _SHA256.fullmatch(identity[key])
                   for key in digest_fields)
            or identity.get("warmup_input_sha256") != _sha256(payload)):
        raise ShadowObservationRefused(
            "shadow warm-up economic input identity is incoherent")
    return identity


def _validate_retained_publication(
        value: Any, *, session: str, data_version: int) -> dict:
    publication = _as_mapping(value, where="shadow publication commitment")
    fields = {
        "schema", "status", "session", "data_version", "published_through",
        "publication_sha256", "publication"}
    if set(publication) != fields:
        raise ShadowObservationRefused(
            f"publication commitment has an unknown shape at {session}")
    raw = _as_mapping(
        publication["publication"], where="retained corpus publication")
    if set(raw) != {
            "version", "previous_version", "run_id", "window", "evidence"}:
        raise ShadowObservationRefused(
            f"retained corpus publication has an unknown shape at {session}")
    window = raw["window"]
    version = raw["version"]
    previous = raw["previous_version"]
    run_id = raw["run_id"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ShadowObservationRefused(
            f"publication version is invalid at {session}")
    if (publication["schema"] != PUBLICATION_SCHEMA
            or publication["status"] != FULLY_PUBLISHED
            or publication["session"] != session
            or publication["data_version"] != data_version
            or version != data_version
            or not isinstance(window, list) or len(window) != 2
            or any(bound is not None and not isinstance(bound, str)
                   for bound in window)
            or not isinstance(publication["published_through"], str)
            or publication["published_through"] < session
            or publication["publication_sha256"] != _sha256(raw)
            or (version == 1 and previous is not None)
            or (version > 1 and (
                isinstance(previous, bool) or not isinstance(previous, int)
                or previous != version - 1))
            or (run_id is not None and (
                not isinstance(run_id, str) or not run_id.strip()))
            or not isinstance(raw["evidence"], Mapping)):
        raise ShadowObservationRefused(
            f"publication commitment is incoherent at {session}")
    return publication


@dataclass(frozen=True)
class FullyPublishedSession:
    """One canonical engine input named by an actual corpus publication.

    ``publication`` is the result of ``Publication.to_dict()`` (or the same
    mapping).  Sentinel writes that row only after ingest validation.  Requiring
    its covered window to reach this exact session prevents a merely current
    *version number* from being mistaken for publication of the next session.
    """

    published: PublishedSession
    publication: Mapping[str, Any]
    published_through: str | None = None
    strategy_prices: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        prices = (self.strategy_prices if self.strategy_prices is not None else
                  self.published.defensive_bar)
        if prices is None:
            raise ShadowObservationRefused(
                "fully published session lacks Core+BIL strategy prices")
        object.__setattr__(
            self, "strategy_prices",
            _strategy_prices(
                prices, session=self.published.session,
                previous_value=(
                    None if self.strategy_prices is not None else
                    self.published.defensive_previous_bar)))

    def commitment(self) -> dict:
        raw = _as_mapping(
            self.publication.to_dict()
            if hasattr(self.publication, "to_dict") else self.publication,
            where="corpus publication")
        required = {
            "version", "previous_version", "run_id", "window", "evidence"}
        if set(raw) != required:
            raise ShadowObservationRefused(
                "corpus publication has an unknown or incomplete identity shape")
        version = raw["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ShadowObservationRefused(
                "corpus publication version is not a positive integer")
        previous = raw["previous_version"]
        if ((version == 1 and previous is not None)
                or (version > 1 and (
                    isinstance(previous, bool)
                    or not isinstance(previous, int)
                    or previous != version - 1))):
            raise ShadowObservationRefused(
                "corpus publication predecessor does not form an exact chain")
        run_id = raw["run_id"]
        if run_id is not None and (
                not isinstance(run_id, str) or not run_id.strip()):
            raise ShadowObservationRefused(
                "corpus publication run identity is invalid")
        if self.published.data_version != version:
            raise ShadowObservationRefused(
                "published session data version differs from its publication")
        window = raw["window"]
        if not isinstance(window, list) or len(window) != 2:
            raise ShadowObservationRefused(
                "corpus publication window is not an exact two-value range")
        start, end = window
        if any(bound is not None and not isinstance(bound, str)
               for bound in (start, end)):
            raise ShadowObservationRefused(
                "corpus publication window identity is invalid")
        # The publication's own durable window is the authority.  A wrapper's
        # caller-supplied string must never manufacture positive coverage.
        if (self.published_through is not None
                and self.published_through != end):
            raise ShadowObservationRefused(
                f"session {self.published.session} is not fully published "
                "through the held publication window")
        through = end
        if not isinstance(through, str) or through < self.published.session:
            raise ShadowObservationRefused(
                f"session {self.published.session} is not fully published "
                f"through {through!r}")
        if not isinstance(raw["evidence"], Mapping):
            raise ShadowObservationRefused(
                "corpus publication evidence is not an object")
        publication_sha256 = _sha256(raw)
        return {
            "schema": PUBLICATION_SCHEMA,
            "status": FULLY_PUBLISHED,
            "session": self.published.session,
            "data_version": version,
            "published_through": through,
            "publication_sha256": publication_sha256,
            "publication": raw,
        }

    @property
    def input_sha256(self) -> str:
        return _sha256(_published_input_value(
            self.published, self.strategy_prices))


@dataclass(frozen=True)
class ShadowObservationResult:
    session: str
    state: SessionState
    record_sha256: str
    starting_cash: str
    strategy_nav: str
    strategy_cumulative_return: str
    parent_core_nav: str
    runtime_identity_sha256: str
    runtime_authority_sha256: str | None = None
    live_frontier: str | None = None
    sessions_lag: int = 0
    shadow_verdict: str = NOT_DEPLOYABLE
    verification: str = CANDIDATE
    appended: bool = True

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "shadow_verdict": self.shadow_verdict,
            "verification": self.verification,
            "starting_cash": self.starting_cash,
            "strategy_nav": self.strategy_nav,
            "strategy_cumulative_return": self.strategy_cumulative_return,
            "parent_core_nav": self.parent_core_nav,
            "runtime_identity_sha256": self.runtime_identity_sha256,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "live_frontier": self.live_frontier,
            "sessions_lag": self.sessions_lag,
            "state_sha256": self.state.state_hash,
            "record_sha256": self.record_sha256,
            "appended": self.appended,
        }


class PostgresShadowObservationStore:
    """Append-only adapter over the existing namespaced JSON cursor table.

    There is one immutable row per observation session.  The adapter performs
    no ``UPDATE`` or ``DELETE`` and never uses the paper catch-up cursor.  It
    commits the one-time genesis immediately, so a changed corpus after a failed
    first run cannot force reconstruction of a different warmed seed.  Session
    appends do not commit: the runtime owns their publication-read transaction.
    """

    def __init__(self, conn, *, observation_id: str) -> None:
        self.conn = conn
        self.observation_id = _observation_id(observation_id)
        self.prefix = f"{POSTGRES_CURSOR_PREFIX}{self.observation_id}:"

    def _name(self, session: str) -> str:
        return f"{self.prefix}session:{session}"

    def _authority_name(self, session: str) -> str:
        return f"{self.prefix}authority:{session}"

    @property
    def _genesis_name(self) -> str:
        return f"{self.prefix}genesis"

    def genesis(self) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT session,state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s", (self._genesis_name,))
            row = cur.fetchone()
        if row is None:
            return None
        genesis = _as_mapping(
            row[1], where=f"shadow observation row {self._genesis_name}")
        if str(row[0]) != genesis.get("first_session"):
            raise ShadowObservationRefused(
                "shadow observation genesis row/session is incoherent")
        return genesis

    def append_genesis(self, genesis: Mapping[str, Any]) -> None:
        candidate = _as_mapping(genesis, where="shadow observation genesis")
        if candidate.get("observation_id") != self.observation_id:
            raise ShadowObservationRefused(
                "shadow observation store cannot seed another observation id")
        session = _xnys_session(
            candidate.get("first_session"), where="shadow first session")
        encoded = _canonical_json(candidate)
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_processed_sessions"
                    " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                    " ON CONFLICT (cursor_name) DO NOTHING",
                    (self._genesis_name, session, encoded))
                cur.execute(
                    "SELECT session,state FROM sentinel_processed_sessions"
                    " WHERE cursor_name=%s", (self._genesis_name,))
                row = cur.fetchone()
            if row is None:
                raise ShadowObservationRefused(
                    "shadow observation genesis did not become durable")
            stored = _as_mapping(
                row[1], where=f"shadow observation row {self._genesis_name}")
            if str(row[0]) != session or stored != candidate:
                raise ShadowObservationRefused(
                    "shadow observation genesis was already committed with "
                    "different evidence")
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def records(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT cursor_name,session,state"
                " FROM sentinel_processed_sessions"
                " WHERE cursor_name LIKE %s"
                " ORDER BY session,cursor_name",
                (self.prefix + "session:%",))
            rows = cur.fetchall()
        out: list[dict] = []
        for cursor_name, stored_session, state in rows:
            record = _as_mapping(
                state, where=f"shadow observation row {cursor_name}")
            session = record.get("session")
            if (str(cursor_name) != self._name(str(session))
                    or str(stored_session) != str(session)):
                raise ShadowObservationRefused(
                    "shadow observation row key/session is incoherent")
            out.append(record)
        return out

    def append(self, record: Mapping[str, Any]) -> None:
        candidate = _as_mapping(record, where="shadow observation append")
        if candidate.get("observation_id") != self.observation_id:
            raise ShadowObservationRefused(
                "shadow observation store cannot append another observation id")
        session = _xnys_session(
            candidate.get("session"), where="shadow observation append session")
        name = self._name(session)
        encoded = _canonical_json(candidate)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (name, session, encoded))
            cur.execute(
                "SELECT session,state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s", (name,))
            row = cur.fetchone()
        if row is None:
            raise ShadowObservationRefused(
                "shadow observation append did not become durable")
        stored = _as_mapping(row[1], where=f"shadow observation row {name}")
        if str(row[0]) != session or stored != candidate:
            raise ShadowObservationRefused(
                f"shadow observation session {session} was already committed "
                "with different evidence")

    def authorities(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT cursor_name,session,state"
                " FROM sentinel_processed_sessions"
                " WHERE cursor_name LIKE %s"
                " ORDER BY session,cursor_name",
                (self.prefix + "authority:%",))
            rows = cur.fetchall()
        out: list[dict] = []
        for cursor_name, stored_session, state in rows:
            authority = _as_mapping(
                state, where=f"shadow runtime authority {cursor_name}")
            session = authority.get("session")
            if (str(cursor_name) != self._authority_name(str(session))
                    or str(stored_session) != str(session)):
                raise ShadowObservationRefused(
                    "shadow runtime authority row key/session is incoherent")
            out.append(authority)
        return out

    def append_authority(self, authority: Mapping[str, Any]) -> None:
        candidate = _as_mapping(authority, where="shadow runtime authority")
        if candidate.get("observation_id") != self.observation_id:
            raise ShadowObservationRefused(
                "shadow store cannot attest another observation id")
        session = _xnys_session(
            candidate.get("session"), where="shadow runtime authority session")
        name = self._authority_name(session)
        encoded = _canonical_json(candidate)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (name, session, encoded))
            cur.execute(
                "SELECT session,state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s", (name,))
            row = cur.fetchone()
        if row is None:
            raise ShadowObservationRefused(
                "shadow runtime authority append did not become durable")
        stored = _as_mapping(row[1], where=f"shadow runtime authority {name}")
        if str(row[0]) != session or stored != candidate:
            raise ShadowObservationRefused(
                f"shadow runtime authority for {session} was already committed "
                "with different evidence")


class PostgresFullyPublishedSessionSource:
    """Read one exact visible session while holding the corpus publication pin.

    Canonical readiness remains the service's wider precondition.  This adapter
    independently refuses incoherent/unpublished rows and returns ``None`` when
    the current completed publication window has not yet reached the requested
    next session.
    """

    def __init__(
            self, conn, *, load_published=load_published_session) -> None:
        self.conn = conn
        self.load_published = load_published

    def load_fully_published(
            self, session: str, *, known_feed_security_ids: Sequence[str] = ()
            ) -> FullyPublishedSession | None:
        from sentinel.feed import publication as publication_store

        expected = _xnys_session(session, where="requested shadow session")
        with publication_store.pinned(self.conn, commit=False) as publication:
            publication_store.assert_coherent(self.conn)
            published = self.load_published(
                self.conn, expected,
                known_feed_security_ids=tuple(known_feed_security_ids))
            if (not isinstance(published, PublishedSession)
                    or published.session != expected
                    or published.data_version != publication.version):
                raise ShadowObservationRefused(
                    "loaded shadow input differs from its held publication")
            return FullyPublishedSession(
                published, publication.to_dict(),
                published_through=publication.window_end)


class ShadowObserver:
    """Advance an isolated canonical state by exactly one published session."""

    def __init__(
            self, *, store: ShadowObservationStore, observation_id: str,
            starting_cash: Decimal | str | int | float, first_session: str,
            initial_state: SessionState | Mapping[str, Any],
            controller_config: ControllerConfig,
            strategy_identity: Mapping[str, Any],
            runtime_identity: Mapping[str, Any],
            activation_timing: Mapping[str, Any],
            warmup_input_identity: Mapping[str, Any]) -> None:
        self.store = store
        self.observation_id = _observation_id(observation_id)
        self.starting_cash = _cash_text(starting_cash)
        self.first_session = _xnys_session(first_session, where="first session")
        self.controller_config = controller_config
        self.strategy_identity = _as_mapping(
            strategy_identity, where="strategy identity")
        self.runtime_identity = _as_mapping(
            runtime_identity, where="shadow runtime identity")
        if not self.runtime_identity:
            raise ShadowObservationRefused(
                "shadow runtime identity cannot be empty")
        self.runtime_identity_sha256 = _sha256(self.runtime_identity)
        self.activation_timing = _timing_proof(
            activation_timing, decision_session=self.first_session,
            committed=False, where="shadow activation timing")
        self.warmup_input_identity = _validate_warmup_input_identity(
            warmup_input_identity, first_session=self.first_session)
        self.warmup_input_identity_sha256 = self.warmup_input_identity[
            "warmup_input_sha256"]
        try:
            state_value = (initial_state.to_dict()
                           if isinstance(initial_state, SessionState)
                           else initial_state)
            self.initial_state = SessionState.from_dict(state_value)
        except (TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                "initial shadow state is not a canonical SessionState") from exc
        self._assert_seed()
        self.initial_state_sha256 = self.initial_state.state_hash
        self.initial_strategy_economics = {
            "schema": STRATEGY_ECONOMICS_SCHEMA,
            "starting_cash": self.starting_cash,
            "last_session": None,
            "strategy_nav": self.starting_cash,
            "held_allocation": None,
            "pending_allocation": None,
            "parent_core_close_equity": None,
            "bil_close_adjusted": None,
        }
        self.spec = {
            "schema": RECORD_SCHEMA,
            "observation_id": self.observation_id,
            "starting_cash": self.starting_cash,
            "first_session": self.first_session,
            "strategy_identity": self.strategy_identity,
            "runtime_identity": self.runtime_identity,
            "activation_timing": self.activation_timing,
            "execution_model": SHADOW_EXECUTION_MODEL,
            "cutoff_policy": SHADOW_CUTOFF_POLICY,
            "controller": _canonical_value(controller_config.to_dict()),
            "initial_state_sha256": self.initial_state_sha256,
            "initial_strategy_economics": self.initial_strategy_economics,
            "warmup_input_identity_sha256": (
                self.warmup_input_identity_sha256),
        }
        self.spec_sha256 = _sha256(self.spec)
        genesis = {
            "schema": GENESIS_SCHEMA,
            **{key: value for key, value in self.spec.items()
               if key != "schema"},
            "spec_sha256": self.spec_sha256,
            "initial_state": self.initial_state.to_dict(),
            "warmup_input_identity": self.warmup_input_identity,
        }
        genesis["genesis_sha256"] = _sha256(genesis)
        self.genesis_record = genesis
        self.genesis_sha256 = genesis["genesis_sha256"]
        self._persist_and_verify_genesis()

    @classmethod
    def resume(
            cls, *, store: ShadowObservationStore, observation_id: str,
            starting_cash: Decimal | str | int | float, first_session: str,
            controller_config: ControllerConfig,
            strategy_identity: Mapping[str, Any],
            runtime_identity: Mapping[str, Any]) -> "ShadowObserver":
        """Reconstruct exactly from environment-bound spec plus durable rows."""
        try:
            genesis = store.genesis()
        except ShadowObservationRefused:
            raise
        except Exception as exc:
            raise ShadowObservationRefused(
                "shadow observation genesis is unreadable") from exc
        if genesis is None:
            raise ShadowObservationRefused(
                "shadow observation has no immutable genesis state")
        raw = _as_mapping(genesis, where="shadow observation genesis")
        initial = raw.get("initial_state")
        if not isinstance(initial, Mapping):
            raise ShadowObservationRefused(
                "shadow observation genesis lacks its canonical initial state")
        activation = raw.get("activation_timing")
        if not isinstance(activation, Mapping):
            raise ShadowObservationRefused(
                "shadow observation genesis lacks its activation timing proof")
        warmup_input = raw.get("warmup_input_identity")
        if not isinstance(warmup_input, Mapping):
            raise ShadowObservationRefused(
                "shadow observation genesis lacks its warm-up input identity")
        return cls(
            store=store, observation_id=observation_id,
            starting_cash=starting_cash, first_session=first_session,
            initial_state=initial, controller_config=controller_config,
            strategy_identity=strategy_identity,
            runtime_identity=runtime_identity,
            activation_timing=activation,
            warmup_input_identity=warmup_input)

    def _persist_and_verify_genesis(self) -> None:
        try:
            existing = self.store.genesis()
            if existing is None:
                self.store.append_genesis(self.genesis_record)
                existing = self.store.genesis()
        except ShadowObservationRefused:
            raise
        except Exception as exc:
            raise ShadowObservationRefused(
                "shadow observation genesis could not be persisted") from exc
        if _as_mapping(existing, where="shadow observation genesis") \
                != self.genesis_record:
            raise ShadowObservationRefused(
                "shadow observation genesis changed after commitment")
        payload = {key: value for key, value in self.genesis_record.items()
                   if key != "genesis_sha256"}
        if (_sha256(payload) != self.genesis_sha256
                or self._genesis_state_hash() != self.initial_state_sha256):
            raise ShadowObservationRefused(
                "shadow observation genesis commitment is incoherent")

    def _genesis_state_hash(self) -> str:
        try:
            return SessionState.from_dict(
                self.genesis_record["initial_state"]).state_hash
        except (TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                "shadow observation genesis state is incoherent") from exc

    def _assert_seed(self) -> None:
        state = self.initial_state
        if state.strategy_identity != self.strategy_identity:
            raise ShadowObservationRefused(
                "initial shadow state differs from explicit strategy identity")
        if (self.strategy_identity.get("strategy")
                != self.controller_config.strategy_id
                or self.strategy_identity.get("controller_rule_sha256")
                != self.controller_config.digest):
            raise ShadowObservationRefused(
                "explicit strategy identity differs from controller configuration")
        if state.last_processed_session is not None:
            raise ShadowObservationRefused(
                "initial shadow state has already processed an economic session")
        baseline = SessionState.fresh(
            starting_cash=float(Decimal(self.starting_cash)),
            controller=Controller(self.controller_config),
            strategy_identity=self.strategy_identity)
        if state.controller != baseline.controller:
            raise ShadowObservationRefused(
                "initial shadow controller is not at its isolated cold state")
        wealth = state.wealth_core
        try:
            seed_cash = Decimal(str(wealth["cash"]))
            peak = Decimal(str(state.shadow_peak_nav))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                "initial shadow state lacks explicit research capital") from exc
        expected = Decimal(self.starting_cash)
        if seed_cash != expected or peak != expected:
            raise ShadowObservationRefused(
                "initial shadow state cash/peak differs from explicit starting cash")
        if state.wealth_core != baseline.wealth_core:
            raise ShadowObservationRefused(
                "initial shadow Wealth Core book is not the exact cold seed")
        ledger = state.ledger
        dirty = (
            bool(wealth.get("initialized"))
            or bool(wealth.get("episodes"))
            or bool(wealth.get("security_cooldowns"))
            or bool(wealth.get("unresolved_terminals"))
            or bool(wealth.get("sessions_since_valid_mark"))
            or bool(wealth.get("terminal_pending_sessions"))
            or bool(wealth.get("terminal_pending_terms"))
            or any(
                slot.get("occupied_by") is not None
                or slot.get("reserved_for") is not None
                or slot.get("cooldown_sessions_elapsed") is not None
                for slot in (wealth.get("slots") or {}).values())
            or bool(state.pending)
            or bool(ledger.get("events"))
            or bool(ledger.get("receivables"))
            or bool(state.shadow_nav_history)
            or bool(state.trailing_stop_sessions)
            or bool(state.controller_session_history)
            or bool(state.breadth_history)
            or bool(state.last_known)
            or state.last_decision is not None
            or state.last_evidence is not None
        )
        if dirty:
            raise ShadowObservationRefused(
                "initial shadow state is not an isolated broker-free seed")
        seen = state.feed.get("seen_sessions") or {}
        if seen:
            last_warm = max(seen, key=lambda item: int(seen[item]))
            if _next_session(str(last_warm)) != self.first_session:
                raise ShadowObservationRefused(
                    "first shadow session is not adjacent to the warm-up frontier")

    def _parent_economics(self, state: SessionState) -> tuple[Decimal, Decimal]:
        if not state.shadow_nav_history:
            raise ShadowObservationRefused(
                "shadow state has no canonical parent Core NAV observation")
        try:
            nav = Decimal(str(state.shadow_nav_history[-1]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                "parent Core NAV is not a decimal") from exc
        if not nav.is_finite() or nav <= 0:
            raise ShadowObservationRefused(
                "parent Core NAV must be finite and positive")
        evidence = state.last_evidence or {}
        plan = evidence.get("wealth_core")
        if (not isinstance(plan, Mapping)
                or plan.get("session") != state.last_processed_session):
            raise ShadowObservationRefused(
                "shadow state lacks its current parent Core valuation")
        if (plan.get("blocked") is not False
                or plan.get("resolved_equity") is None
                or plan.get("resolved_open_equity") is None
                or plan.get("open_unresolved_security_ids") not in ([], ())):
            # ``advance_state`` deliberately retains an estimated equity while
            # a holding has no trustworthy current mark or terminal terms are
            # unresolved.  That estimate is useful diagnostic state, but it is
            # not a valuation from which performance may be reported.
            raise ShadowObservationRefused(
                "unresolved or blocked Wealth Core equity cannot feed verified "
                "Core+BIL strategy performance")
        try:
            resolved_nav = Decimal(str(plan["resolved_equity"]))
            resolved_open = Decimal(str(plan["resolved_open_equity"]))
            estimated_nav = Decimal(str(plan["estimated_equity"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                "parent Core valuation is not a decimal") from exc
        if (not resolved_nav.is_finite() or resolved_nav <= 0
                or not resolved_open.is_finite() or resolved_open <= 0
                or not estimated_nav.is_finite()
                or estimated_nav != resolved_nav):
            raise ShadowObservationRefused(
                "parent Core valuation is not fully resolved")
        # LiveSessionPlan retains valuation evidence to cents while the
        # observation envelope retains the canonical float.  Half a cent is
        # therefore the largest honest representation difference.
        if abs(nav - resolved_nav) > Decimal("0.0050000001"):
            raise ShadowObservationRefused(
                "parent Core NAV differs from resolved Wealth Core equity")
        observation = evidence.get("observation") or {}
        try:
            observed_nav = Decimal(str(observation.get("shadow_nav")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                "parent Core evidence lacks its NAV") from exc
        if observed_nav != nav:
            raise ShadowObservationRefused(
                "parent Core state and observation NAV disagree")
        # The close evidence is intentionally rendered to cents, while the
        # canonical SessionState NAV retains the plan's full float precision.
        # Use the latter after the half-cent coherence check so a multi-month
        # scalar series does not accumulate representation rounding drift.
        return resolved_open, nav

    @staticmethod
    def _allocation(value: Any, *, where: str) -> Decimal:
        try:
            allocation = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                f"{where} is not a decimal allocation") from exc
        if (not allocation.is_finite()
                or allocation < 0 or allocation > 1):
            raise ShadowObservationRefused(
                f"{where} is outside the unlevered [0,1] envelope")
        return allocation

    def _advance_strategy_economics(
            self, *, previous: Mapping[str, Any], state: SessionState,
            strategy_prices: Mapping[str, Any]) -> dict:
        session = str(state.last_processed_session)
        prior = _as_mapping(previous, where="prior strategy economics")
        parent_open, parent_close = self._parent_economics(state)
        prices = _strategy_prices(strategy_prices, session=session)
        bil_open = _positive_decimal(
            prices["bil_open_adjusted"], where="BIL adjusted open")
        bil_close = _positive_decimal(
            prices["bil_close_adjusted"], where="BIL adjusted close")
        bil_previous_close = _positive_decimal(
            prices["bil_previous_close_adjusted"],
            where="same-publication prior BIL adjusted close")
        decision = state.last_decision or {}
        pending = self._allocation(
            decision.get("target_core_exposure"),
            where=f"pending Core allocation at {session}")
        prior_nav = _positive_decimal(
            prior.get("strategy_nav"), where="prior strategy NAV")
        previous_session = prior.get("last_session")
        if (previous_session is not None
                and prices["bil_previous_session"] != previous_session):
            raise ShadowObservationRefused(
                f"same-publication prior BIL row is not the prior shadow "
                f"session at {session}")
        previous_pending = prior.get("pending_allocation")
        previous_held = prior.get("held_allocation")
        initial_deployment = previous_session is not None and previous_held is None
        held: Decimal | None
        core_overnight = bil_overnight = None
        core_intraday = parent_close / parent_open - Decimal(1)
        bil_intraday = bil_close / bil_open - Decimal(1)
        turnover = Decimal(0)
        cost_factor = Decimal(1)
        gross_factor = Decimal(1)
        if previous_session is None:
            # The first close creates only a future allocation commitment. It
            # cannot earn that already-finished session's return.
            held = None
            net_factor = Decimal(1)
        else:
            if previous_pending is None:
                raise ShadowObservationRefused(
                    "prior strategy close lacks its pending allocation")
            new_allocation = self._allocation(
                previous_pending, where="prior pending Core allocation")
            held = new_allocation
            if initial_deployment:
                # The Core leg's actual stock-entry costs already live in the
                # canonical parent open-to-close factor.  Only the newly bought
                # BIL sleeve needs the scalar overlay's 10bp transition cost.
                turnover = Decimal(1) - new_allocation
                cost_factor = Decimal(1) - Decimal("0.001") * turnover
                gross_factor = (
                    Decimal(1) + new_allocation * core_intraday
                    + (Decimal(1) - new_allocation) * bil_intraday)
            else:
                old_allocation = self._allocation(
                    previous_held, where="prior held Core allocation")
                previous_core_close = _positive_decimal(
                    prior.get("parent_core_close_equity"),
                    where="prior parent Core close")
                core_overnight = parent_open / previous_core_close - Decimal(1)
                bil_overnight = bil_open / bil_previous_close - Decimal(1)
                if new_allocation == old_allocation:
                    gross_factor = (
                        new_allocation * parent_close / previous_core_close
                        + (Decimal(1) - new_allocation)
                        * bil_close / bil_previous_close)
                else:
                    turnover = abs(new_allocation - old_allocation)
                    cost_factor = Decimal(1) - Decimal("0.001") * turnover
                    gross_factor = (
                        Decimal(1) + old_allocation * core_overnight
                        + (Decimal(1) - old_allocation) * bil_overnight)
                    gross_factor *= (
                        Decimal(1) + new_allocation * core_intraday
                        + (Decimal(1) - new_allocation) * bil_intraday)
            net_factor = cost_factor * gross_factor
        strategy_nav = prior_nav * net_factor
        if (not strategy_nav.is_finite() or strategy_nav <= 0
                or not net_factor.is_finite() or net_factor <= 0):
            raise ShadowObservationRefused(
                "combined Core+BIL strategy economics are nonpositive/nonfinite")
        cumulative = strategy_nav / Decimal(self.starting_cash) - Decimal(1)
        return {
            "schema": STRATEGY_ECONOMICS_SCHEMA,
            "starting_cash": self.starting_cash,
            "last_session": session,
            "previous_strategy_nav": _decimal_text(prior_nav),
            "strategy_nav": _decimal_text(strategy_nav),
            "strategy_cumulative_return": _decimal_text(cumulative),
            "held_allocation": (
                None if held is None else _decimal_text(held)),
            "pending_allocation": _decimal_text(pending),
            "initial_deployment": initial_deployment,
            "turnover": _decimal_text(turnover),
            "transaction_cost_factor": _decimal_text(cost_factor),
            "gross_factor": _decimal_text(gross_factor),
            "net_factor": _decimal_text(net_factor),
            "parent_core_open_equity": _decimal_text(parent_open),
            "parent_core_close_equity": _decimal_text(parent_close),
            "bil_open_adjusted": _decimal_text(bil_open),
            "bil_close_adjusted": _decimal_text(bil_close),
            "bil_previous_session": prices["bil_previous_session"],
            "bil_previous_close_adjusted_current_publication": (
                _decimal_text(bil_previous_close)),
            "core_overnight_return": (
                None if core_overnight is None
                else _decimal_text(core_overnight)),
            "bil_overnight_return": (
                None if bil_overnight is None
                else _decimal_text(bil_overnight)),
            "core_intraday_return": _decimal_text(core_intraday),
            "bil_intraday_return": _decimal_text(bil_intraday),
            "strategy_prices": prices,
            "strategy_prices_sha256": _sha256(prices),
        }

    def _result(self, *, session: str, state: SessionState,
                strategy_economics: Mapping[str, Any],
                record_sha256: str, appended: bool) -> ShadowObservationResult:
        economics = _as_mapping(
            strategy_economics, where="strategy economics result")
        _open, parent_close = self._parent_economics(state)
        return ShadowObservationResult(
            session=session, state=state, record_sha256=record_sha256,
            starting_cash=self.starting_cash,
            strategy_nav=str(economics["strategy_nav"]),
            strategy_cumulative_return=str(
                economics["strategy_cumulative_return"]),
            parent_core_nav=_decimal_text(parent_close),
            runtime_identity_sha256=self.runtime_identity_sha256,
            appended=appended)

    def _record_state(self, raw: Mapping[str, Any], *, expected_session: str,
                      prior_state_sha256: str) -> SessionState:
        state_raw = raw.get("state")
        try:
            state = SessionState.from_dict(state_raw)
        except (TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                f"shadow state for {expected_session} is incoherent") from exc
        if state.state_hash != raw.get("state_sha256"):
            raise ShadowObservationRefused(
                f"shadow state commitment changed at {expected_session}")
        if raw.get("prior_state_sha256") != prior_state_sha256:
            raise ShadowObservationRefused(
                f"shadow prior-state chain changed at {expected_session}")
        if (state.last_processed_session != expected_session
                or state.strategy_identity != self.strategy_identity
                or state.controller.get("last_session") != expected_session
                or not isinstance(state.last_decision, Mapping)
                or state.last_decision.get("session") != expected_session
                or not isinstance(state.last_evidence, Mapping)
                or not isinstance(state.last_evidence.get("observation"), Mapping)
                or state.last_evidence["observation"].get("session")
                != expected_session):
            raise ShadowObservationRefused(
                f"shadow state/session identity is incoherent at {expected_session}")
        self._parent_economics(state)
        _validate_retained_publication(
            raw.get("publication"), session=expected_session,
            data_version=state.data_version)
        return state

    def _history(self) -> tuple[list[dict], SessionState]:
        self._persist_and_verify_genesis()
        try:
            rows = list(self.store.records())
        except ShadowObservationRefused:
            raise
        except Exception as exc:
            raise ShadowObservationRefused(
                "shadow observation history is unreadable") from exc
        previous_record_sha256 = self.genesis_sha256
        prior_state_sha256 = self.initial_state_sha256
        state = self.initial_state
        prior_data_version = self.initial_state.data_version
        prior_strategy_economics = self.initial_strategy_economics
        expected_session = self.first_session
        validated: list[dict] = []
        for index, value in enumerate(rows):
            raw = _as_mapping(value, where=f"shadow observation row {index}")
            if set(raw) != _RECORD_FIELDS:
                raise ShadowObservationRefused(
                    f"shadow observation row {index} has an unknown state shape")
            if any(raw.get(key) != expected for key, expected in (
                    ("schema", RECORD_SCHEMA),
                    ("observation_id", self.observation_id),
                    ("session", expected_session),
                    ("shadow_verdict", NOT_DEPLOYABLE),
                    ("verification", CANDIDATE),
                    ("spec_sha256", self.spec_sha256),
                    ("starting_cash", self.starting_cash),
                    ("first_session", self.first_session),
                    ("strategy_identity", self.strategy_identity),
                    ("runtime_identity", self.runtime_identity),
                    ("activation_timing", self.activation_timing),
                    ("execution_model", SHADOW_EXECUTION_MODEL),
                    ("cutoff_policy", SHADOW_CUTOFF_POLICY),
                    ("controller", self.spec["controller"]),
                    ("initial_strategy_economics",
                     self.initial_strategy_economics),
                    ("warmup_input_identity_sha256",
                     self.warmup_input_identity_sha256),
                    ("initial_state_sha256", self.initial_state_sha256),
                    ("previous_record_sha256", previous_record_sha256),
            )):
                raise ShadowObservationRefused(
                    f"shadow observation chain/config changed at {expected_session}")
            if not isinstance(raw.get("input_sha256"), str) or not _SHA256.fullmatch(
                    raw["input_sha256"]):
                raise ShadowObservationRefused(
                    f"published input commitment is invalid at {expected_session}")
            _validate_economic_input_identity(
                raw.get("economic_input_identity"), session=expected_session)
            claimed_record = raw.get("record_sha256")
            payload = {key: item for key, item in raw.items()
                       if key != "record_sha256"}
            if (not isinstance(claimed_record, str)
                    or _sha256(payload) != claimed_record):
                raise ShadowObservationRefused(
                    f"shadow observation record changed at {expected_session}")
            state = self._record_state(
                raw, expected_session=expected_session,
                prior_state_sha256=prior_state_sha256)
            strategy_economics = _as_mapping(
                raw.get("strategy_economics"),
                where=f"strategy economics at {expected_session}")
            expected_economics = self._advance_strategy_economics(
                previous=prior_strategy_economics, state=state,
                strategy_prices=strategy_economics.get("strategy_prices"))
            if strategy_economics != expected_economics:
                raise ShadowObservationRefused(
                    f"combined Core+BIL economics changed at {expected_session}")
            if (prior_data_version is not None
                    and state.data_version < prior_data_version):
                raise ShadowObservationRefused(
                    f"shadow publication version regressed at {expected_session}")
            previous_record_sha256 = claimed_record
            prior_state_sha256 = state.state_hash
            prior_data_version = state.data_version
            prior_strategy_economics = strategy_economics
            validated.append(raw)
            expected_session = _next_session(expected_session)
        return validated, state

    def next_session(self) -> str:
        rows, _state = self._history()
        return (self.first_session if not rows
                else _next_session(rows[-1]["session"]))

    def advance_next(
            self, source: FullyPublishedSessionSource) -> ShadowObservationResult:
        rows, prior = self._history()
        expected = (self.first_session if not rows
                    else _next_session(rows[-1]["session"]))
        try:
            published = source.load_fully_published(
                expected,
                known_feed_security_ids=tuple(
                    (prior.feed.get("series") or {}).keys()))
        except Exception as exc:
            raise ShadowObservationRefused(
                f"fully published session {expected} is unavailable") from exc
        return self.observe(published)

    def observe(
            self, published: FullyPublishedSession | None
            ) -> ShadowObservationResult:
        rows, prior = self._history()
        expected = (self.first_session if not rows
                    else _next_session(rows[-1]["session"]))
        if published is None:
            raise ShadowObservationRefused(
                f"next session {expected} is not fully published")
        commitment = published.commitment()
        session = _xnys_session(
            published.published.session, where="published shadow session")
        input_sha256 = published.input_sha256
        economic_input_identity = _economic_input_identity(
            published.published, published.strategy_prices)

        # A retry after an uncertain append may present the just-committed
        # session again.  It is idempotent only when both publication and full
        # canonical input commitments are byte-identical.
        if rows and session == rows[-1]["session"]:
            latest = rows[-1]
            if (latest["publication"] != commitment
                    or latest["input_sha256"] != input_sha256
                    or latest["economic_input_identity"]
                    != economic_input_identity):
                raise ShadowObservationRefused(
                    f"published input for {session} was rewritten")
            return self._result(
                session=session, state=prior,
                strategy_economics=latest["strategy_economics"],
                record_sha256=latest["record_sha256"], appended=False)
        if session != expected:
            raise ShadowObservationRefused(
                f"shadow session gap: expected {expected}, got {session}")
        if commitment["session"] != expected:
            raise ShadowObservationRefused(
                "publication and canonical input name different sessions")

        prior_value = prior.to_dict()
        # ``advance_state`` is canonical, but its feed restoration currently
        # borrows nested observation arrays.  Give it an isolated canonical
        # round trip so even an internal alias cannot rewrite the committed
        # predecessor while advancing the next session.
        transition_prior = SessionState.from_dict(prior_value)
        try:
            advanced = advance_state(
                transition_prior, published.published,
                controller_config=self.controller_config,
                strategy_identity=self.strategy_identity)
        except Exception as exc:
            raise ShadowObservationRefused(
                f"canonical shadow transition refused {expected}: {exc}") from exc
        if prior.to_dict() != prior_value:
            raise ShadowObservationRefused(
                f"canonical shadow transition mutated prior state at {expected}")
        if not isinstance(advanced, SessionState):
            raise ShadowObservationRefused(
                "canonical shadow transition did not return SessionState")
        try:
            advanced = SessionState.from_dict(advanced.to_dict())
        except (TypeError, ValueError) as exc:
            raise ShadowObservationRefused(
                f"canonical shadow transition returned incoherent state at "
                f"{expected}") from exc
        prior_record_sha256 = (
            rows[-1]["record_sha256"] if rows else self.genesis_sha256)
        prior_strategy_economics = (
            rows[-1]["strategy_economics"] if rows
            else self.initial_strategy_economics)
        strategy_economics = self._advance_strategy_economics(
            previous=prior_strategy_economics, state=advanced,
            strategy_prices=published.strategy_prices)
        record = {
            **self.spec,
            "session": expected,
            "shadow_verdict": NOT_DEPLOYABLE,
            "verification": CANDIDATE,
            "spec_sha256": self.spec_sha256,
            "previous_record_sha256": prior_record_sha256,
            "prior_state_sha256": prior.state_hash,
            "publication": commitment,
            "input_sha256": input_sha256,
            "economic_input_identity": economic_input_identity,
            "state": advanced.to_dict(),
            "state_sha256": advanced.state_hash,
            "strategy_economics": strategy_economics,
        }
        # Apply the same semantic checks to a candidate before persistence.
        self._record_state(
            record, expected_session=expected,
            prior_state_sha256=prior.state_hash)
        record["record_sha256"] = _sha256(record)
        try:
            self.store.append(record)
        except ShadowObservationRefused:
            raise
        except Exception as exc:
            raise ShadowObservationRefused(
                f"shadow observation append failed at {expected}") from exc

        retained, retained_state = self._history()
        if (len(retained) != len(rows) + 1
                or retained[-1] != _canonical_value(record)
                or retained_state.state_hash != advanced.state_hash):
            raise ShadowObservationRefused(
                f"shadow observation append was not retained exactly at {expected}")
        return self._result(
            session=expected, state=retained_state,
            strategy_economics=retained[-1]["strategy_economics"],
            record_sha256=record["record_sha256"], appended=True)

    def verify_history(self) -> ShadowObservationResult:
        rows, state = self._history()
        if not rows:
            raise ShadowObservationRefused(
                "shadow observation has no verified published session")
        latest = rows[-1]
        return self._result(
            session=latest["session"], state=state,
            strategy_economics=latest["strategy_economics"],
            record_sha256=latest["record_sha256"], appended=False)


class PostgresShadowRuntime:
    """The sole promotion path from a candidate to SHADOW_GO/VERIFIED.

    Promotion is earned inside a real corpus pin after the complete readiness
    contract, corpus coherence, publication-chain continuity and canonical DB
    loader all agree.  A generic/memory store cannot instantiate this boundary.
    The transaction commits the candidate record and a separate immutable
    runtime-authority row.  GO language never enters the generic durable state,
    and a later status read must reproduce the latest input under the live
    PostgreSQL authority before it can surface that GO again.
    """

    def __init__(
            self, conn, *, observer: ShadowObserver, clock=None,
            warmup_input_loader=None) -> None:
        if (not isinstance(observer.store, PostgresShadowObservationStore)
                or observer.store.conn is not conn):
            raise ShadowObservationRefused(
                "SHADOW_GO requires the observer's bound PostgreSQL store")
        self.conn = conn
        self.observer = observer
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if not callable(warmup_input_loader):
            raise ShadowObservationRefused(
                "SHADOW_GO requires a canonical warm-up input loader")
        self.warmup_input_loader = warmup_input_loader

    def _now(self) -> datetime:
        return _utc_instant(self.clock(), where="shadow runtime clock")

    def _require_current_warmup_input(self) -> str:
        """Reproduce all 252 seed sessions under the held publication pin."""
        try:
            current = _validate_warmup_input_identity(
                self.warmup_input_loader(),
                first_session=self.observer.first_session)
        except ShadowObservationRefused:
            raise
        except Exception as exc:
            raise ShadowObservationRefused(
                "current corpus cannot reproduce the shadow warm-up input"
            ) from exc
        if current != self.observer.warmup_input_identity:
            raise ShadowObservationRefused(
                "current publication economically revised the 252-session "
                "shadow warm-up; VERIFIED performance withdrawn")
        return current["warmup_input_sha256"]

    def _preopen_timing(self, session: str) -> tuple[str, datetime, datetime]:
        execution = _next_session(session)
        opened, _closed = calendar.session_window(execution)
        cutoff = _utc_instant(opened, where="following XNYS open")
        observed = self._now()
        if observed >= cutoff:
            raise ShadowObservationRefused(
                f"shadow session {session} was observed after its following "
                f"XNYS open {cutoff.isoformat()}; retrospective fill refused")
        return execution, observed, cutoff

    def _attested_history(self) -> tuple[list[dict], SessionState]:
        rows, state = self.observer._history()
        authorities = self.observer.store.authorities()
        if len(authorities) != len(rows):
            raise ShadowObservationRefused(
                "PostgreSQL shadow candidate history lacks exact runtime "
                "authority; SHADOW_GO refused")
        self._validate_authorities(rows, authorities)
        return rows, state

    def _candidate_history(
            self) -> tuple[list[dict], SessionState, list[dict]]:
        """Allow only one exact trailing candidate for pre-open recovery."""
        rows, state = self.observer._history()
        authorities = self.observer.store.authorities()
        if (len(authorities) > len(rows)
                or len(rows) - len(authorities) > 1):
            raise ShadowObservationRefused(
                "PostgreSQL shadow history has an incoherent authority count")
        self._validate_authorities(rows[:len(authorities)], authorities)
        return rows, state, authorities

    def _validate_authorities(
            self, rows: Sequence[Mapping[str, Any]],
            authorities: Sequence[Mapping[str, Any]]) -> None:
        fields = {
            "schema", "observation_id", "session", "record_sha256",
            "state_sha256", "input_sha256", "publication_sha256",
            "readiness_sha256", "runtime_identity_sha256",
            "strategy_economics_sha256", "economic_input_identity_sha256",
            "warmup_input_identity_sha256",
            "execution_model", "cutoff_policy", "execution_session",
            "observed_at", "candidate_committed_at", "execution_open_at",
            "timing_status", "publication_chain_gaps", "shadow_verdict",
            "verification", "authority_sha256"}
        for record, authority_value in zip(rows, authorities):
            authority = _as_mapping(
                authority_value, where="shadow runtime authority")
            payload = {key: value for key, value in authority.items()
                       if key != "authority_sha256"}
            if (set(authority) != fields
                    or authority.get("schema") != RUNTIME_AUTHORITY_SCHEMA
                    or authority.get("observation_id")
                    != self.observer.observation_id
                    or authority.get("session") != record["session"]
                    or authority.get("record_sha256")
                    != record["record_sha256"]
                    or authority.get("state_sha256") != record["state_sha256"]
                    or authority.get("input_sha256") != record["input_sha256"]
                    or authority.get("publication_sha256")
                    != record["publication"]["publication_sha256"]
                    or authority.get("runtime_identity_sha256")
                    != self.observer.runtime_identity_sha256
                    or authority.get("strategy_economics_sha256")
                    != _sha256(record["strategy_economics"])
                    or authority.get("economic_input_identity_sha256")
                    != record["economic_input_identity"][
                        "economic_input_sha256"]
                    or authority.get("warmup_input_identity_sha256")
                    != self.observer.warmup_input_identity_sha256
                    or authority.get("execution_model")
                    != SHADOW_EXECUTION_MODEL
                    or authority.get("cutoff_policy") != SHADOW_CUTOFF_POLICY
                    or authority.get("publication_chain_gaps") != 0
                    or authority.get("shadow_verdict") != SHADOW_GO
                    or authority.get("verification") != VERIFIED
                    or not isinstance(authority.get("readiness_sha256"), str)
                    or not _SHA256.fullmatch(authority["readiness_sha256"])
                    or authority.get("authority_sha256") != _sha256(payload)):
                raise ShadowObservationRefused(
                    f"shadow runtime authority is incoherent at "
                    f"{record['session']}")
            _timing_proof({
                "schema": "sentinel.shadow-session-timing/1",
                "decision_session": authority["session"],
                "execution_session": authority["execution_session"],
                "observed_at": authority["observed_at"],
                "candidate_committed_at": authority[
                    "candidate_committed_at"],
                "execution_open_at": authority["execution_open_at"],
                "status": authority["timing_status"],
            }, decision_session=record["session"], committed=True,
                where=f"shadow runtime timing at {record['session']}")

    @staticmethod
    def _readiness_identity(readiness_result) -> list[dict[str, str]]:
        return [{
            "name": str(check.name), "status": str(check.status),
        } for check in readiness_result.checks]

    @staticmethod
    def _require_ready(readiness_result) -> list[dict[str, str]]:
        if not readiness_result.ready:
            failures = [
                str(check.name) for check in readiness_result.failures]
            raise ShadowObservationRefused(
                "canonical data readiness failed: "
                + ", ".join(failures[:10]))
        return PostgresShadowRuntime._readiness_identity(readiness_result)

    def _require_exact_live_frontier(self, publication, session: str) -> None:
        from sentinel.feed import store as feed_store

        if (not isinstance(publication.window_end, str)
                or publication.window_end < session):
            raise ShadowObservationRefused(
                f"held publication does not cover shadow session {session}")
        visible = feed_store.latest_visible_session(self.conn)
        if visible != session:
            raise ShadowObservationRefused(
                "shadow session is not the exact live published frontier: "
                f"expected={session!r}, visible={visible!r}")

    def _require_committed_economic_inputs(
            self, rows: Sequence[Mapping[str, Any]], publication) -> None:
        """Recheck every committed session against the held current corpus.

        Publications are detectable but not reconstructable: the corpus keeps
        only its latest corrected rows.  The immutable record therefore retains
        a compact economic identity for each session.  A new publication may
        differ byte-for-byte only when its normalized identity is unchanged
        (uniform SPY/BIL total-return rebasing).  Any other revision withdraws
        current VERIFIED status without rewriting the historical authority.
        """
        prior = self.observer.initial_state
        for record in rows:
            session = str(record["session"])
            published = load_published_session(
                self.conn, session,
                known_feed_security_ids=tuple(
                    (prior.feed.get("series") or {}).keys()))
            if (not isinstance(published, PublishedSession)
                    or published.session != session
                    or published.data_version != publication.version):
                raise ShadowObservationRefused(
                    f"current corpus cannot reproduce committed shadow input "
                    f"at {session}")
            current = FullyPublishedSession(
                published, publication.to_dict(),
                published_through=publication.window_end)
            retained_identity = _validate_economic_input_identity(
                record.get("economic_input_identity"), session=session)
            if (current.input_sha256 != record["input_sha256"]
                    and _economic_input_identity(
                        published, current.strategy_prices)
                    != retained_identity):
                raise ShadowObservationRefused(
                    f"current publication economically revised committed "
                    f"shadow session {session}; VERIFIED performance withdrawn")
            prior = SessionState.from_dict(record["state"])

    @staticmethod
    def _promoted_result(
            candidate: ShadowObservationResult, *, authority_sha256: str,
            appended: bool | None = None, live_frontier: str | None = None,
            sessions_lag: int = 0) -> ShadowObservationResult:
        return ShadowObservationResult(
            session=candidate.session, state=candidate.state,
            record_sha256=candidate.record_sha256,
            starting_cash=candidate.starting_cash,
            strategy_nav=candidate.strategy_nav,
            strategy_cumulative_return=(
                candidate.strategy_cumulative_return),
            parent_core_nav=candidate.parent_core_nav,
            runtime_identity_sha256=candidate.runtime_identity_sha256,
            runtime_authority_sha256=authority_sha256,
            live_frontier=live_frontier or candidate.session,
            sessions_lag=sessions_lag,
            shadow_verdict=SHADOW_GO, verification=VERIFIED,
            appended=(candidate.appended if appended is None else appended))

    def advance_next(self) -> ShadowObservationResult:
        from sentinel.feed import publication as publication_store
        from sentinel.feed import readiness

        rows, prior = self._attested_history()
        expected = (self.observer.first_session if not rows
                    else _next_session(rows[-1]["session"]))
        try:
            with publication_store.pinned(self.conn, commit=False) as publication:
                publication_store.assert_coherent(self.conn)
                gaps = publication_store.chain_gaps(self.conn)
                if gaps:
                    raise ShadowObservationRefused(
                        "corpus publication chain has gaps; SHADOW_GO refused")
                self._require_exact_live_frontier(publication, expected)
                readiness_result = readiness.check_readiness(self.conn)
                readiness_identity = self._require_ready(readiness_result)
                warmup_input_sha256 = self._require_current_warmup_input()
                self._require_committed_economic_inputs(rows, publication)
                execution_session, observed_at, execution_open = \
                    self._preopen_timing(expected)
                published = load_published_session(
                    self.conn, expected,
                    known_feed_security_ids=tuple(
                        (prior.feed.get("series") or {}).keys()))
                if (published.session != expected
                        or published.data_version != publication.version):
                    raise ShadowObservationRefused(
                        "canonical DB input differs from the held publication")
                authoritative_input = FullyPublishedSession(
                    published, publication.to_dict(),
                    published_through=publication.window_end)
                candidate = self.observer.observe(authoritative_input)
                candidate_record = self.observer.store.records()[-1]
                # First make the candidate durable while the corpus remains
                # pinned.  Only a clock sampled after this commit can prove the
                # decision existed before its following open.  A crash here is
                # recoverable only while that same cutoff is still future.
                self.conn.commit()
                candidate_committed_at = self._now()
                if candidate_committed_at >= execution_open:
                    raise ShadowObservationRefused(
                        f"shadow candidate {expected} did not commit before "
                        f"following XNYS open {execution_open.isoformat()}")
                authority = {
                    "schema": RUNTIME_AUTHORITY_SCHEMA,
                    "observation_id": self.observer.observation_id,
                    "session": expected,
                    "record_sha256": candidate.record_sha256,
                    "state_sha256": candidate.state.state_hash,
                    "input_sha256": authoritative_input.input_sha256,
                    "publication_sha256": authoritative_input.commitment()[
                        "publication_sha256"],
                    "readiness_sha256": _sha256(readiness_identity),
                    "runtime_identity_sha256": (
                        self.observer.runtime_identity_sha256),
                    "strategy_economics_sha256": _sha256(
                        candidate_record["strategy_economics"]),
                    "economic_input_identity_sha256": candidate_record[
                        "economic_input_identity"]["economic_input_sha256"],
                    "warmup_input_identity_sha256": warmup_input_sha256,
                    "execution_model": SHADOW_EXECUTION_MODEL,
                    "cutoff_policy": SHADOW_CUTOFF_POLICY,
                    "execution_session": execution_session,
                    "observed_at": _utc_text(
                        observed_at, where="shadow observation time"),
                    "candidate_committed_at": _utc_text(
                        candidate_committed_at,
                        where="shadow candidate commit time"),
                    "execution_open_at": _utc_text(
                        execution_open, where="following XNYS open"),
                    "timing_status": BEFORE_NEXT_OPEN,
                    "publication_chain_gaps": 0,
                    "shadow_verdict": SHADOW_GO,
                    "verification": VERIFIED,
                }
                authority["authority_sha256"] = _sha256(authority)
                self.observer.store.append_authority(authority)
                retained_authorities = self.observer.store.authorities()
                if (len(retained_authorities) != len(rows) + 1
                        or retained_authorities[-1]
                        != _canonical_value(authority)):
                    raise ShadowObservationRefused(
                        f"runtime authority was not retained exactly at {expected}")
                self.conn.commit()
        except ShadowObservationRefused:
            self.conn.rollback()
            raise
        except Exception as exc:
            self.conn.rollback()
            raise ShadowObservationRefused(
                f"PostgreSQL shadow runtime refused {expected}: {exc}") from exc
        return self._promoted_result(
            candidate, authority_sha256=authority["authority_sha256"])

    def recover_trailing_candidate(self) -> ShadowObservationResult:
        """Attest one durable crash remnant, but only before its next open."""
        from sentinel.feed import publication as publication_store
        from sentinel.feed import readiness

        rows, state, authorities = self._candidate_history()
        if not rows or len(rows) != len(authorities) + 1:
            raise ShadowObservationRefused(
                "shadow history has no single trailing candidate to recover")
        record = rows[-1]
        session = record["session"]
        prior = (self.observer.initial_state if len(rows) == 1 else
                 SessionState.from_dict(rows[-2]["state"]))
        try:
            with publication_store.pinned(self.conn, commit=False) as publication:
                publication_store.assert_coherent(self.conn)
                if publication_store.chain_gaps(self.conn):
                    raise ShadowObservationRefused(
                        "corpus publication chain has gaps; SHADOW_GO refused")
                self._require_exact_live_frontier(publication, session)
                readiness_identity = self._require_ready(
                    readiness.check_readiness(self.conn))
                warmup_input_sha256 = self._require_current_warmup_input()
                self._require_committed_economic_inputs(rows, publication)
                execution_session, recovered_at, execution_open = \
                    self._preopen_timing(session)
                published = load_published_session(
                    self.conn, session,
                    known_feed_security_ids=tuple(
                        (prior.feed.get("series") or {}).keys()))
                if (published.session != session
                        or published.data_version != publication.version):
                    raise ShadowObservationRefused(
                        "canonical DB input differs from the held publication")
                authoritative_input = FullyPublishedSession(
                    published, publication.to_dict(),
                    published_through=publication.window_end)
                commitment = authoritative_input.commitment()
                if (authoritative_input.input_sha256 != record["input_sha256"]
                        or commitment != record["publication"]):
                    raise ShadowObservationRefused(
                        f"trailing shadow candidate was rewritten at {session}")
                recomputed = advance_state(
                    SessionState.from_dict(prior.to_dict()), published,
                    controller_config=self.observer.controller_config,
                    strategy_identity=self.observer.strategy_identity)
                if recomputed.state_hash != state.state_hash:
                    raise ShadowObservationRefused(
                        f"trailing shadow candidate does not equal the canonical "
                        f"transition at {session}")
                candidate = self.observer._result(
                    session=session, state=state,
                    strategy_economics=record["strategy_economics"],
                    record_sha256=record["record_sha256"], appended=False)
                timestamp = _utc_text(
                    recovered_at, where="trailing candidate recovery time")
                authority = {
                    "schema": RUNTIME_AUTHORITY_SCHEMA,
                    "observation_id": self.observer.observation_id,
                    "session": session,
                    "record_sha256": candidate.record_sha256,
                    "state_sha256": candidate.state.state_hash,
                    "input_sha256": authoritative_input.input_sha256,
                    "publication_sha256": commitment["publication_sha256"],
                    "readiness_sha256": _sha256(readiness_identity),
                    "runtime_identity_sha256": (
                        self.observer.runtime_identity_sha256),
                    "strategy_economics_sha256": _sha256(
                        record["strategy_economics"]),
                    "economic_input_identity_sha256": record[
                        "economic_input_identity"]["economic_input_sha256"],
                    "warmup_input_identity_sha256": warmup_input_sha256,
                    "execution_model": SHADOW_EXECUTION_MODEL,
                    "cutoff_policy": SHADOW_CUTOFF_POLICY,
                    "execution_session": execution_session,
                    # The row was already durable when this recovery observed
                    # it, so this instant is both an observation and a valid
                    # conservative upper bound on its commit time.
                    "observed_at": timestamp,
                    "candidate_committed_at": timestamp,
                    "execution_open_at": _utc_text(
                        execution_open, where="following XNYS open"),
                    "timing_status": BEFORE_NEXT_OPEN,
                    "publication_chain_gaps": 0,
                    "shadow_verdict": SHADOW_GO,
                    "verification": VERIFIED,
                }
                authority["authority_sha256"] = _sha256(authority)
                self.observer.store.append_authority(authority)
                retained = self.observer.store.authorities()
                if (len(retained) != len(rows)
                        or retained[-1] != _canonical_value(authority)):
                    raise ShadowObservationRefused(
                        f"recovered runtime authority was not retained exactly "
                        f"at {session}")
                self.conn.commit()
        except ShadowObservationRefused:
            self.conn.rollback()
            raise
        except Exception as exc:
            self.conn.rollback()
            raise ShadowObservationRefused(
                f"PostgreSQL trailing shadow recovery refused {session}: "
                f"{exc}") from exc
        return self._promoted_result(
            candidate, authority_sha256=authority["authority_sha256"],
            appended=False, live_frontier=session)

    def revalidate_latest(self) -> ShadowObservationResult:
        """Re-earn the latest durable GO under the current PostgreSQL pin.

        This is the idempotent same-session/status path.  Merely finding a
        candidate row or even an old authority row is insufficient: the exact
        already-attested publication must still be the live frontier and pass
        coherence, continuity and the same readiness identity.
        """
        from sentinel.feed import publication as publication_store
        from sentinel.feed import readiness

        rows, state = self._attested_history()
        if not rows:
            raise ShadowObservationRefused(
                "shadow observation has no runtime-attested published session")
        latest = rows[-1]
        authorities = self.observer.store.authorities()
        authority = authorities[-1]
        session = latest["session"]
        try:
            with publication_store.pinned(self.conn, commit=False) as publication:
                publication_store.assert_coherent(self.conn)
                gaps = publication_store.chain_gaps(self.conn)
                if gaps:
                    raise ShadowObservationRefused(
                        "corpus publication chain has gaps; SHADOW_GO refused")
                self._require_exact_live_frontier(publication, session)
                readiness_result = readiness.check_readiness(self.conn)
                readiness_identity = self._require_ready(readiness_result)
                # This exact publication already earned the immutable latest
                # authority, including the complete warm-up/history scan. A
                # newer publication is handled by ``durable_status`` before it
                # can enter this same-publication idempotent path.
                if (_sha256(readiness_identity)
                        != authority["readiness_sha256"]):
                    raise ShadowObservationRefused(
                        f"latest shadow readiness identity changed at {session}")
            self.conn.commit()
        except ShadowObservationRefused:
            self.conn.rollback()
            raise
        except Exception as exc:
            self.conn.rollback()
            raise ShadowObservationRefused(
                f"PostgreSQL shadow runtime could not revalidate {session}: "
                f"{exc}") from exc
        candidate = self.observer._result(
            session=session, state=state,
            strategy_economics=latest["strategy_economics"],
            record_sha256=latest["record_sha256"], appended=False)
        return self._promoted_result(
            candidate, authority_sha256=authority["authority_sha256"],
            appended=False, live_frontier=session)

    def durable_status(self) -> ShadowObservationResult:
        """Return the latest fully attested result and name any live lag.

        A newer publication never rewrites a previously earned authority. It
        does, however, withdraw current VERIFIED status unless every warm-up and
        observed economic input is equivalent under the narrow SPY/BIL scale
        normalization. When the corpus has moved ahead, the result reports the
        exact XNYS-session lag only after that all-history check succeeds.
        """
        from sentinel.feed import publication as publication_store
        from sentinel.feed import readiness
        from sentinel.feed import store as feed_store

        rows, state = self._attested_history()
        if not rows:
            raise ShadowObservationRefused(
                "shadow observation has no runtime-attested published session")
        latest = rows[-1]
        session = latest["session"]
        authority = self.observer.store.authorities()[-1]
        live_publication_sha256 = None
        try:
            with publication_store.pinned(self.conn, commit=False) as publication:
                publication_store.assert_coherent(self.conn)
                if publication_store.chain_gaps(self.conn):
                    raise ShadowObservationRefused(
                        "corpus publication chain has gaps; SHADOW_GO refused")
                self._require_ready(readiness.check_readiness(self.conn))
                visible = feed_store.latest_visible_session(self.conn)
                if not isinstance(visible, str):
                    raise ShadowObservationRefused(
                        "live published frontier is unavailable")
                if visible < session:
                    raise ShadowObservationRefused(
                        "live published frontier regressed behind the durable "
                        "shadow session")
                if (not isinstance(publication.window_end, str)
                        or publication.window_end < visible):
                    raise ShadowObservationRefused(
                        "held publication does not cover the live frontier")
                live_publication_sha256 = _sha256(publication.to_dict())
                if (live_publication_sha256
                        != authority["publication_sha256"]):
                    # One O(252+N) scan per new publication. The authority row
                    # proves the scan for repeated status polls under the exact
                    # publication that originally earned it.
                    self._require_current_warmup_input()
                    self._require_committed_economic_inputs(rows, publication)
            self.conn.commit()
        except ShadowObservationRefused:
            self.conn.rollback()
            raise
        except Exception as exc:
            self.conn.rollback()
            raise ShadowObservationRefused(
                f"PostgreSQL shadow status refused {session}: {exc}") from exc
        if (visible == session
                and live_publication_sha256
                == latest["publication"]["publication_sha256"]):
            return self.revalidate_latest()
        if visible == session:
            # The all-history scan above proved this later publication differs
            # only by permitted economic-invariant normalization. Preserve the
            # exact prospective record; never rewrite it with today's bytes.
            candidate = self.observer._result(
                session=session, state=state,
                strategy_economics=latest["strategy_economics"],
                record_sha256=latest["record_sha256"], appended=False)
            return self._promoted_result(
                candidate, authority_sha256=authority["authority_sha256"],
                appended=False, live_frontier=visible, sessions_lag=0)
        lag_sessions = calendar.sessions_in_range(
            _next_session(session), visible)
        if not lag_sessions or lag_sessions[-1] != visible:
            raise ShadowObservationRefused(
                "live shadow lag does not form an exact XNYS session range")
        candidate = self.observer._result(
            session=session, state=state,
            strategy_economics=latest["strategy_economics"],
            record_sha256=latest["record_sha256"], appended=False)
        return self._promoted_result(
            candidate, authority_sha256=authority["authority_sha256"],
            appended=False, live_frontier=visible,
            sessions_lag=len(lag_sessions))

    def advance_through(self, session: str) -> ShadowObservationResult:
        """Advance exactly next, or revalidate an exact latest-session retry."""
        requested = _xnys_session(session, where="requested shadow session")
        rows, _state, authorities = self._candidate_history()
        latest = rows[-1]["session"] if rows else None
        if len(rows) == len(authorities) + 1:
            if requested == latest:
                return self.recover_trailing_candidate()
            raise ShadowObservationRefused(
                f"unattested trailing candidate {latest} must be resolved "
                "before any later shadow session")
        expected = (self.observer.first_session if not rows
                    else _next_session(latest))
        if requested == latest:
            return self.revalidate_latest()
        if requested == expected:
            return self.advance_next()
        raise ShadowObservationRefused(
            f"shadow publication gap/regression: latest={latest!r}, "
            f"expected={expected!r}, requested={requested!r}")


__all__ = [
    "BEFORE_NEXT_OPEN", "CANDIDATE", "FULLY_PUBLISHED",
    "FullyPublishedSession", "GENESIS_SCHEMA", "FullyPublishedSessionSource",
    "POSTGRES_CURSOR_PREFIX",
    "PostgresFullyPublishedSessionSource", "PostgresShadowObservationStore",
    "PostgresShadowRuntime", "RECORD_SCHEMA", "SHADOW_CUTOFF_POLICY",
    "SHADOW_EXECUTION_MODEL", "SHADOW_GO", "NOT_DEPLOYABLE",
    "RUNTIME_AUTHORITY_SCHEMA", "STRATEGY_ECONOMICS_SCHEMA",
    "ShadowObservationRefused", "ShadowObservationResult",
    "ShadowObservationStore", "ShadowObserver", "VERIFIED",
]
