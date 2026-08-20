"""Canonical identity for the bt-data Sharadar ACTIONS source boundary.

This intentionally matches :mod:`sentinel.feed.action_source`. bt-data is a
self-contained image on the separate backtest machine, so it cannot import the
Sentinel runtime package; parity is guarded by tests instead of introducing a
runtime dependency across those deployment boundaries.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Mapping

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
    """Return the complete received source row in canonical JSON-safe form."""
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


__all__ = ["SOURCE_FIELDS", "canonical_payload", "payload_bytes", "source_row_id"]
