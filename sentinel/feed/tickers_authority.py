"""Structural publication authority for Sharadar ``table=SEP`` TICKERS.

A complete/stable traversal is not enough when its keys are ambiguous.  This
module validates the exact identity and listing-interval invariants before a
TICKERS observation can be fingerprinted, used as a resolver, or written.

The retained TICKERS snapshot is small enough to materialise (~22k SEP rows),
which the existing source membrane already does.  SEP history remains streaming;
this validator adds no history-sized state.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from sentinel.feed import universe

SCHEMA = "sentinel.tickers-structural-authority/1"
AUTHORITY_FIELDS = (
    "table", "permaticker", "ticker", "category", "relatedtickers",
    "firstpricedate", "lastpricedate", "sector", "isdelisted",
)
_MAX_EXAMPLES = 8
_MASK_256 = (1 << 256) - 1


@dataclass(frozen=True)
class TickersStructureEvidence:
    invariant: str
    source_rows: int
    source_digest: str
    keys: tuple[tuple[str, str], ...] = ()
    intervals: tuple[tuple[str, str | None, str | None], ...] = ()
    row_fingerprints: tuple[str, ...] = ()
    detail: str = ""
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "invariant": self.invariant,
            "source_observation": {
                "rows": int(self.source_rows),
                "sha256": self.source_digest,
            },
            "keys": [list(item) for item in self.keys[:_MAX_EXAMPLES]],
            "intervals": [list(item) for item in self.intervals[:_MAX_EXAMPLES]],
            "row_fingerprints": list(self.row_fingerprints[:_MAX_EXAMPLES]),
            "detail": self.detail[:1000],
        }


class TickersStructureInvalid(RuntimeError):
    """One stable TICKERS candidate cannot unambiguously define identity."""

    def __init__(self, evidence: TickersStructureEvidence):
        self.evidence = evidence
        encoded = json.dumps(
            evidence.to_dict(), sort_keys=True, separators=(",", ":"))
        super().__init__(f"Sharadar TICKERS structural authority refused: {encoded}")


class _Fingerprint:
    """Order-independent, multiplicity-sensitive bounded-memory commitment."""

    def __init__(self) -> None:
        self.rows = 0
        self._a = 0
        self._b = 0

    def add(self, payload: bytes) -> None:
        self.rows += 1
        self._a = (self._a + int.from_bytes(
            hashlib.sha256(b"\x00" + payload).digest(), "big")) & _MASK_256
        self._b = (self._b + int.from_bytes(
            hashlib.sha256(b"\x01" + payload).digest(), "big")) & _MASK_256

    def digest(self) -> str:
        witness = (
            self.rows.to_bytes(16, "big")
            + self._a.to_bytes(32, "big")
            + self._b.to_bytes(32, "big"))
        return hashlib.sha256(witness).hexdigest()


def _canonical_scalar(value):
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
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
    return str(value).strip()


def _strict_date(value, *, field: str, source_rows: int,
                 source_digest: str, key: tuple[str, str]) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise TickersStructureInvalid(TickersStructureEvidence(
            invariant="valid_listing_date",
            source_rows=source_rows,
            source_digest=source_digest,
            keys=(key,),
            detail=f"{field} is not a strict ISO calendar date: {text!r}",
        )) from exc
    if parsed.isoformat() != text:
        raise TickersStructureInvalid(TickersStructureEvidence(
            invariant="valid_listing_date",
            source_rows=source_rows,
            source_digest=source_digest,
            keys=(key,),
            detail=f"{field} is not canonical YYYY-MM-DD: {text!r}",
        ))
    return text


def _listing_state(value, *, source_rows: int, source_digest: str,
                   key: tuple[str, str]) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return "Y" if value else "N"
    if isinstance(value, str):
        token = value.strip().upper()
        if token in {"Y", "TRUE", "1"}:
            return "Y"
        if token in {"N", "FALSE", "0"}:
            return "N"
    raise TickersStructureInvalid(TickersStructureEvidence(
        invariant="supported_isdelisted_domain",
        source_rows=source_rows,
        source_digest=source_digest,
        keys=(key,),
        detail=f"isdelisted has unsupported value/type: {value!r}",
    ))


def _payload(row: Mapping) -> bytes:
    values = {}
    for field in AUTHORITY_FIELDS:
        if field == "relatedtickers":
            raw = row.get(field)
            values[field] = (None if raw is None else list(
                universe.parse_related_tickers(raw)))
        else:
            values[field] = _canonical_scalar(row.get(field))
    return json.dumps(values, sort_keys=True, separators=(",", ":")).encode(
        "utf-8")


def _observation(rows: Iterable[Mapping]) -> tuple[int, str]:
    fingerprint = _Fingerprint()
    for row in rows:
        fingerprint.add(_payload(row))
    return fingerprint.rows, fingerprint.digest()


def _refuse(*, invariant: str, source_rows: int, source_digest: str,
            keys=(), intervals=(), fingerprints=(), detail: str = "") -> None:
    raise TickersStructureInvalid(TickersStructureEvidence(
        invariant=invariant,
        source_rows=source_rows,
        source_digest=source_digest,
        keys=tuple(keys)[:_MAX_EXAMPLES],
        intervals=tuple(intervals)[:_MAX_EXAMPLES],
        row_fingerprints=tuple(fingerprints)[:_MAX_EXAMPLES],
        detail=detail,
    ))


def validate(rows: Iterable[Mapping]) -> list[dict]:
    """Return one deterministic canonical row per valid SEP identity pair.

    Non-SEP product rows are intentionally outside Sentinel's universe and are
    discarded exactly as the existing source membrane already does.  Within the
    SEP partition, no malformed row is filtered: one invalid key, interval,
    state, or conflicting duplicate refuses the complete candidate.
    """
    material = [dict(row) for row in rows]
    relevant = [row for row in material
                if str(row.get("table") or "").strip().upper() == "SEP"]
    source_rows, source_digest = _observation(relevant)
    if not relevant:
        _refuse(
            invariant="nonempty_sep_partition",
            source_rows=source_rows,
            source_digest=source_digest,
            detail="TICKERS exposed no explicit table=SEP rows")

    grouped: dict[tuple[str, str], dict[str, tuple[bytes, dict]]] = {}
    for row in relevant:
        permaticker = str(row.get("permaticker") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        key = (permaticker, ticker)
        if not permaticker or not ticker:
            _refuse(
                invariant="nonblank_canonical_identity_key",
                source_rows=source_rows,
                source_digest=source_digest,
                keys=(key,),
                detail="permaticker and ticker must both be nonblank")

        first = _strict_date(
            row.get("firstpricedate"), field="firstpricedate",
            source_rows=source_rows, source_digest=source_digest, key=key)
        last = _strict_date(
            row.get("lastpricedate"), field="lastpricedate",
            source_rows=source_rows, source_digest=source_digest, key=key)
        if first is not None and last is not None and first > last:
            _refuse(
                invariant="ordered_listing_interval",
                source_rows=source_rows,
                source_digest=source_digest,
                keys=(key,),
                intervals=((permaticker, first, last),),
                detail="firstpricedate is after lastpricedate")
        state = _listing_state(
            row.get("isdelisted"), source_rows=source_rows,
            source_digest=source_digest, key=key)

        canonical = dict(row)
        canonical.update({
            "table": "SEP",
            "permaticker": permaticker,
            "ticker": ticker,
            "firstpricedate": first,
            "lastpricedate": last,
            "isdelisted": state,
        })
        payload = _payload(canonical)
        digest = hashlib.sha256(payload).hexdigest()
        grouped.setdefault(key, {})[digest] = (payload, canonical)

    deduped: list[dict] = []
    for key in sorted(grouped):
        variants = grouped[key]
        if len(variants) != 1:
            _refuse(
                invariant="unique_canonical_identity_pair",
                source_rows=source_rows,
                source_digest=source_digest,
                keys=(key,),
                fingerprints=tuple(sorted(variants)),
                detail=(
                    "duplicate canonical (permaticker,ticker) rows differ in "
                    "authority-bearing content"))
        # Repeated byte-equivalent authority rows collapse explicitly to one.
        _payload_bytes, canonical = next(iter(variants.values()))
        deduped.append(canonical)

    by_ticker: dict[str, list[tuple[str, str | None, str | None, str]]] = {}
    for row in deduped:
        payload_digest = hashlib.sha256(_payload(row)).hexdigest()
        by_ticker.setdefault(str(row["ticker"]), []).append((
            str(row["permaticker"]), row.get("firstpricedate"),
            row.get("lastpricedate"), payload_digest))

    for ticker in sorted(by_ticker):
        intervals = sorted(
            by_ticker[ticker],
            key=lambda item: (item[1] is not None, item[1] or "", item[0]))
        active: tuple[str, str | None, str | None, str] | None = None
        for current in intervals:
            if active is None:
                active = current
                continue
            active_end = active[2]
            current_start = current[1]
            overlaps = active_end is None or current_start is None or (
                current_start <= active_end)
            if overlaps and current[0] != active[0]:
                _refuse(
                    invariant="nonoverlapping_ticker_reuse_intervals",
                    source_rows=source_rows,
                    source_digest=source_digest,
                    keys=((active[0], ticker), (current[0], ticker)),
                    intervals=(
                        (active[0], active[1], active[2]),
                        (current[0], current[1], current[2]),
                    ),
                    fingerprints=(active[3], current[3]),
                    detail=(
                        "inclusive listing intervals for one ticker overlap "
                        "across different permanent identities"))
            # Keep the interval with the furthest/open end as the overlap sweep.
            if active_end is None:
                continue
            if current[2] is None or current[2] > active_end:
                active = current

    return sorted(
        deduped,
        key=lambda row: (str(row["permaticker"]), str(row["ticker"])))


__all__ = [
    "AUTHORITY_FIELDS", "SCHEMA", "TickersStructureEvidence",
    "TickersStructureInvalid", "validate",
]
