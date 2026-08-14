"""Canonical identity and cardinality diagnostics for Sharadar ACTIONS rows.

Sharadar's source row grain is the complete seven-column row delivered by the
datatable, not ``(ticker, date, action)``.  Several rows may legitimately share
that economic-event key (relationship rows are the production example).  This
module gives the received content a stable identity without consulting row
order, and therefore lets ingestion distinguish an exact repeat from a sibling
row or a vendor restatement.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Iterable, Mapping

SOURCE_FIELDS = (
    "date", "action", "ticker", "name", "value", "contraticker", "contraname",
)


def _text(value):
    return None if value is None else str(value)


def _number(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"ACTIONS value is not a finite number: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"ACTIONS value is not a finite number: {value!r}")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def canonical_payload(row: Mapping) -> dict:
    """Return the complete received source row in a canonical JSON-safe form.

    Numeric spelling is semantic: ``1``, ``1.0`` and ``Decimal('1.00')`` are
    the same vendor value.  NULL remains distinct from an empty string.
    """
    return {
        "date": _text(row.get("date")),
        "action": _text(row.get("action")),
        "ticker": _text(row.get("ticker")),
        "name": _text(row.get("name")),
        "value": _number(row.get("value")),
        "contraticker": _text(row.get("contraticker")),
        "contraname": _text(row.get("contraname")),
    }


def payload_bytes(payload: Mapping) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def source_row_id(row: Mapping) -> str:
    return hashlib.sha256(payload_bytes(canonical_payload(row))).hexdigest()


def distinct_rows(rows: Iterable[Mapping]) -> list[tuple[str, dict, Mapping]]:
    """Deduplicate exact semantic repeats and retain every distinct source row."""
    found: dict[str, tuple[dict, Mapping]] = {}
    for row in rows:
        payload = canonical_payload(row)
        identity = hashlib.sha256(payload_bytes(payload)).hexdigest()
        prior = found.get(identity)
        if prior is not None and prior[0] != payload:
            raise ValueError("ACTIONS source identity collision")
        found.setdefault(identity, (payload, row))
    return [(identity, *found[identity]) for identity in sorted(found)]


def multiplicity_profile(rows: Iterable[Mapping]) -> dict:
    """Sanitized source-cardinality profile grouped by action type.

    The result contains counts only.  It never contains credentials, request
    URLs, company names, or complete source rows.
    """
    material = list(rows)
    distinct = distinct_rows(material)
    groups: dict[tuple[str, str, str], set[str]] = {}
    by_action: dict[str, dict[str, int]] = {}
    for identity, payload, _row in distinct:
        action = (payload["action"] or "").lower()
        key = (payload["ticker"] or "", payload["date"] or "", action)
        groups.setdefault(key, set()).add(identity)
    raw_by_id: dict[str, int] = {}
    for row in material:
        identity = source_row_id(row)
        raw_by_id[identity] = raw_by_id.get(identity, 0) + 1
    for key, identities in groups.items():
        action = key[2]
        item = by_action.setdefault(action, {
            "source_rows": 0, "distinct_rows": 0, "economic_keys": 0,
            "multiplicity_keys": 0, "exact_repeat_rows": 0,
        })
        item["economic_keys"] += 1
        item["distinct_rows"] += len(identities)
        item["source_rows"] += sum(raw_by_id[i] for i in identities)
        item["exact_repeat_rows"] += sum(raw_by_id[i] - 1 for i in identities)
        if len(identities) > 1:
            item["multiplicity_keys"] += 1
    return {"source_rows": len(material), "distinct_rows": len(distinct),
            "exact_repeat_rows": len(material) - len(distinct),
            "by_action": {key: by_action[key] for key in sorted(by_action)}}


__all__ = ["SOURCE_FIELDS", "canonical_payload", "distinct_rows",
           "multiplicity_profile", "payload_bytes", "source_row_id"]
