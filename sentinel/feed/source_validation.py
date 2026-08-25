"""Exact source-envelope and source-key validation for Sharadar ingress.

Transport success and a stable content fingerprint do not prove that the rows
belong to the request that earned the fingerprint.  This module is the common
membrane used before fingerprinting, staging, normalization, or watermark
advancement.

SEP/SFP duplicate detection is disk-backed.  A historical year can contain
millions of rows; exact key authority must not turn that year into another
whole-table Python object graph merely to prove uniqueness.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable, Iterator, Mapping

from sentinel.feed import calendar


class SourceEnvelopeRefused(RuntimeError):
    """A returned row does not belong to the authority envelope requested."""


class ConflictingSourceDuplicate(SourceEnvelopeRefused):
    """One canonical source key was returned with conflicting row content."""


class TickerIdentityModelInvalid(SourceEnvelopeRefused):
    """The stable TICKERS snapshot cannot define an unambiguous identity model."""


def _strict_date(value, *, label: str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise SourceEnvelopeRefused(f"{label} must be an ISO date, not a timestamp")
    if isinstance(value, dt.date):
        return value
    text = str(value or "").strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise SourceEnvelopeRefused(f"{label} is not an ISO date: {value!r}") from exc
    if text != parsed.isoformat():
        raise SourceEnvelopeRefused(f"{label} is not a canonical ISO date: {value!r}")
    return parsed


def _optional_date(value, *, label: str) -> dt.date | None:
    if value is None or not str(value).strip():
        return None
    return _strict_date(value, label=label)


def _canonical(value):
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not number.is_finite():
            return str(value)
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return str(value)


def canonical_row_bytes(row: Mapping) -> bytes:
    return json.dumps(
        {str(key): _canonical(value) for key, value in sorted(row.items())},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _requested_date_bounds(params: Mapping | None) -> tuple[dt.date | None, dt.date | None]:
    params = params or {}
    lo_raw = params.get("date.gte")
    hi_raw = params.get("date.lte")
    lo = _strict_date(lo_raw, label="requested date.gte") if lo_raw else None
    hi = _strict_date(hi_raw, label="requested date.lte") if hi_raw else None
    if (lo is None) != (hi is None):
        raise SourceEnvelopeRefused(
            "market source request must supply date.gte and date.lte together")
    if lo is not None and lo > hi:
        raise SourceEnvelopeRefused(f"reversed market source interval: {lo} > {hi}")
    return lo, hi


def _requested_update_bounds(params: Mapping | None) -> tuple[dt.date | None, dt.date | None]:
    params = params or {}
    lo_raw = params.get("lastupdated.gte")
    hi_raw = params.get("lastupdated.lte")
    lo = (_strict_date(lo_raw, label="requested lastupdated.gte")
          if lo_raw else None)
    hi = (_strict_date(hi_raw, label="requested lastupdated.lte")
          if hi_raw else None)
    if (lo is None) != (hi is None):
        raise SourceEnvelopeRefused(
            "CDC source request must supply lastupdated.gte and lastupdated.lte together")
    if lo is not None and lo > hi:
        raise SourceEnvelopeRefused(f"reversed lastupdated interval: {lo} > {hi}")
    return lo, hi


def validated_market_rows(
    table: str,
    rows: Iterable[Mapping],
    params: Mapping | None = None,
    *,
    observation_through: str | dt.date | None = None,
) -> Iterator[Mapping]:
    """Validate and de-duplicate SEP/SFP before downstream observation.

    Exact semantic repeats collapse in first-observed order.  A conflicting
    duplicate is a refusal.  Every source row is proved to be a valid XNYS
    session and, when the request named a market interval, to lie inside that
    exact inclusive interval.  CDC bounds and seed watermark bounds are checked
    on SEP before the row can affect a fingerprint or cursor.
    """
    source = str(table).strip().upper()
    if source not in {"SEP", "SFP"}:
        raise ValueError(f"market-row validation does not support {table!r}")
    date_lo, date_hi = _requested_date_bounds(params)
    update_lo, update_hi = _requested_update_bounds(params)
    through = (_strict_date(observation_through, label="observation through")
               if observation_through is not None else None)
    requested_sessions = None
    if date_lo is not None:
        requested_sessions = set(calendar.sessions_in_range(
            date_lo.isoformat(), date_hi.isoformat()))

    with tempfile.TemporaryDirectory(prefix="sentinel-source-keys-") as directory:
        db_path = Path(directory) / "keys.sqlite3"
        seen = sqlite3.connect(str(db_path))
        try:
            seen.execute("PRAGMA journal_mode=OFF")
            seen.execute("PRAGMA synchronous=OFF")
            seen.execute("PRAGMA temp_store=FILE")
            seen.execute(
                "CREATE TABLE source_keys (source_key TEXT PRIMARY KEY, payload BLOB NOT NULL)"
            )
            pending = 0
            for raw in rows:
                row = dict(raw)
                ticker = str(row.get("ticker") or "").strip().upper()
                if not ticker:
                    raise SourceEnvelopeRefused(f"Sharadar {source} row has no ticker")
                session = _strict_date(
                    row.get("date"), label=f"Sharadar {source} {ticker} date")
                session_text = session.isoformat()
                if date_lo is not None and not date_lo <= session <= date_hi:
                    raise SourceEnvelopeRefused(
                        f"Sharadar {source} row {ticker}/{session_text} lies outside "
                        f"requested interval {date_lo}..{date_hi}")
                if requested_sessions is not None:
                    if session_text not in requested_sessions:
                        raise SourceEnvelopeRefused(
                            f"Sharadar {source} row {ticker}/{session_text} is not an "
                            "XNYS session in the requested market interval")
                else:
                    try:
                        calendar.session_window(session_text)
                    except Exception as exc:
                        raise SourceEnvelopeRefused(
                            f"Sharadar {source} row {ticker}/{session_text} is not an "
                            "XNYS session") from exc

                if source == "SEP":
                    updated_raw = row.get("lastupdated")
                    updated = None
                    if updated_raw is not None and str(updated_raw).strip():
                        updated = _strict_date(
                            updated_raw,
                            label=f"Sharadar SEP {ticker}/{session_text} lastupdated")
                    if update_lo is not None:
                        if updated is None or not update_lo <= updated <= update_hi:
                            raise SourceEnvelopeRefused(
                                f"Sharadar SEP row {ticker}/{session_text} has "
                                f"lastupdated={updated_raw!r} outside requested "
                                f"interval {update_lo}..{update_hi}")
                    if through is not None and updated is not None and updated > through:
                        raise SourceEnvelopeRefused(
                            f"Sharadar SEP row {ticker}/{session_text} has future "
                            f"lastupdated {updated} beyond observation boundary {through}")

                key = f"{ticker}\x00{session_text}"
                payload = canonical_row_bytes(row)
                cursor = seen.execute(
                    "INSERT OR IGNORE INTO source_keys(source_key,payload) VALUES (?,?)",
                    (key, payload))
                if cursor.rowcount == 0:
                    prior = seen.execute(
                        "SELECT payload FROM source_keys WHERE source_key=?", (key,)
                    ).fetchone()
                    if prior is None or bytes(prior[0]) != payload:
                        raise ConflictingSourceDuplicate(
                            f"Sharadar {source} returned conflicting duplicate source "
                            f"key ({ticker}, {session_text})")
                    continue
                pending += 1
                if pending >= 10_000:
                    seen.commit()
                    pending = 0
                yield row
            seen.commit()
        finally:
            seen.close()


def validate_tickers(rows: Iterable[Mapping]) -> list[Mapping]:
    """Validate one complete table=SEP TICKERS identity generation.

    TICKERS is small enough to retain once, but authority is still canonical:
    exact repeats collapse, conflicting repeats refuse, listing intervals must
    be valid, listing state must be from the reviewed domain, and ticker reuse
    may not overlap across permanent identities.
    """
    retained: list[Mapping] = []
    by_key: dict[tuple[str, str], bytes] = {}
    by_ticker: dict[str, list[tuple[dt.date, dt.date, str]]] = {}
    for raw in rows:
        row = dict(raw)
        permaticker = str(row.get("permaticker") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        if not permaticker or not ticker:
            raise TickerIdentityModelInvalid(
                "table=SEP TICKERS row lacks permaticker or ticker")
        key = (permaticker, ticker)
        payload = canonical_row_bytes(row)
        prior = by_key.get(key)
        if prior is not None:
            if prior != payload:
                raise ConflictingSourceDuplicate(
                    f"Sharadar TICKERS returned conflicting duplicate source key {key}")
            continue
        by_key[key] = payload

        first = _optional_date(
            row.get("firstpricedate") or row.get("first_price_date"),
            label=f"TICKERS {permaticker}/{ticker} firstpricedate")
        last = _optional_date(
            row.get("lastpricedate") or row.get("last_price_date"),
            label=f"TICKERS {permaticker}/{ticker} lastpricedate")
        if first is not None and last is not None and first > last:
            raise TickerIdentityModelInvalid(
                f"TICKERS {permaticker}/{ticker} has reversed listing interval "
                f"{first}..{last}")

        state = row.get("isdelisted")
        if state is None and "is_delisted" in row:
            state = row.get("is_delisted")
        if isinstance(state, bool):
            pass
        elif str(state or "").strip().upper() not in {
                "Y", "N", "TRUE", "FALSE", "1", "0"}:
            raise TickerIdentityModelInvalid(
                f"TICKERS {permaticker}/{ticker} has invalid isdelisted state {state!r}")

        lo = first or dt.date.min
        hi = last or dt.date.max
        by_ticker.setdefault(ticker, []).append((lo, hi, permaticker))
        retained.append(row)

    for ticker, intervals in by_ticker.items():
        intervals.sort(key=lambda item: (item[0], item[1], item[2]))
        prior_lo, prior_hi, prior_identity = intervals[0]
        for lo, hi, identity in intervals[1:]:
            if identity != prior_identity and lo <= prior_hi:
                raise TickerIdentityModelInvalid(
                    f"TICKERS assigns {ticker} to permanent identities "
                    f"{prior_identity} and {identity} on overlapping intervals "
                    f"{prior_lo}..{prior_hi} / {lo}..{hi}")
            if hi > prior_hi:
                prior_lo, prior_hi, prior_identity = lo, hi, identity
    return retained


__all__ = [
    "ConflictingSourceDuplicate", "SourceEnvelopeRefused",
    "TickerIdentityModelInvalid", "canonical_row_bytes",
    "validate_tickers", "validated_market_rows",
]
