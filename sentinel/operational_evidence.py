"""Append-only operational evidence for the Caesar's Palace projection.

These records describe the execution membrane and recoverability infrastructure.
They are never read by strategy or exposure-control code.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Mapping


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, default=str)


def record_account_snapshot(conn, snapshot) -> None:
    """Append one already-authorized typed broker account result."""
    flags = {
        "trading_blocked": bool(snapshot.trading_blocked),
        "account_blocked": bool(snapshot.account_blocked),
        "trade_suspended_by_user": bool(snapshot.trade_suspended_by_user),
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_broker_account_evidence"
            " (broker,broker_account_id,status,flags,equity,cash,"
            " buying_power,multiplier)"
            " VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
            (snapshot.identity.broker, snapshot.identity.account_id,
             str(snapshot.status or "UNKNOWN"), _json(flags),
             Decimal(snapshot.equity), Decimal(snapshot.cash),
             (None if snapshot.buying_power is None
              else Decimal(snapshot.buying_power)),
             (None if snapshot.multiplier is None
              else Decimal(snapshot.multiplier))))


def record_backup_proof(conn, *, kind: str, proof: Mapping[str, Any]) -> str:
    """Append one successful backup/restore observation and return its digest."""
    normalized_kind = str(kind).strip().upper()
    if normalized_kind not in {
            "BASE_BACKUP", "RUNTIME_CHAIN", "RESTORE_DRILL"}:
        raise ValueError("unknown backup evidence kind")
    payload = _json(proof)
    digest = hashlib.sha256(
        ("sentinel.backup-evidence/1\0" + normalized_kind + "\0" + payload)
        .encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_backup_evidence"
            " (kind,evidence_sha256,proof) VALUES (%s,%s,%s::jsonb)"
            " RETURNING kind,proof",
            (normalized_kind, digest, payload))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("backup evidence could not be read after insert")
    stored = row[1]
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except json.JSONDecodeError as exc:
            raise RuntimeError("backup evidence is not valid JSON") from exc
    if (str(row[0]) != normalized_kind or not isinstance(stored, Mapping)
            or dict(stored) != json.loads(payload)):
        raise RuntimeError("backup evidence identity was reused inconsistently")
    return digest


__all__ = ["record_account_snapshot", "record_backup_proof"]
