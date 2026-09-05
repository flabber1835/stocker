#!/usr/bin/env python3
"""Fail-closed, broker-read-only expected/observed PAPER ledger certificate.

The inputs are sanitized exports produced independently by Sentinel's durable
journal and the Alpaca PAPER observation path.  This tool performs no network
or broker operation.  It never promotes Alpaca P/L to strategy authority.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence

from sentinel.execution.states import CommandState


EXPECTED_SCHEMA = "sentinel.paper-ledger-expected/1"
OBSERVED_SCHEMA = "sentinel.paper-ledger-observed/1"
REPORT_SCHEMA = "sentinel.paper-ledger-certificate/1"
CASH_TOLERANCE = Decimal("0.01")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TOP_FIELDS = {
    "schema", "captured_at", "commit_sha", "account_subject_sha256",
    "plan_id_sha256", "decision_session", "effective_session", "cash",
    "equity", "positions", "orders", "fills", "corporate_actions",
    "completeness",
}
ORDER_FIELDS = {
    "client_key_sha256", "security_id_sha256", "side", "quantity",
    "filled_quantity", "filled_average_price", "state",
}
FILL_FIELDS = {
    "fill_sha256", "client_key_sha256", "security_id_sha256", "quantity",
    "price", "filled_at",
}
ACTION_FIELDS = {
    "action_sha256", "security_id_sha256", "kind", "effective_session",
    "quantity_multiplier", "cash_amount",
}


class PaperLedgerRefused(RuntimeError):
    """The supplied evidence cannot support a comparison."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise PaperLedgerRefused("ledger evidence is not canonical JSON") from exc


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decimal(value: object, *, label: str, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise PaperLedgerRefused(f"{label} must be a decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise PaperLedgerRefused(f"{label} is not a decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise PaperLedgerRefused(f"{label} is outside its financial domain")
    return parsed


def _timestamp(value: object, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PaperLedgerRefused(f"{label} is not an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperLedgerRefused(f"{label} is timezone-naive")
    return parsed.astimezone(timezone.utc)


def _hash_field(value: object, *, label: str) -> str:
    text = str(value or "")
    if HEX64.fullmatch(text) is None:
        raise PaperLedgerRefused(f"{label} is not a SHA-256 subject")
    return text


def _load(path: Path, *, schema: str) -> tuple[dict, str, datetime]:
    try:
        raw = path.read_bytes().rstrip(b"\r\n")
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperLedgerRefused(f"{schema} evidence is unreadable") from exc
    if (not isinstance(value, Mapping) or set(value) != TOP_FIELDS
            or value.get("schema") != schema or _canonical(value) != raw):
        raise PaperLedgerRefused(f"{schema} evidence has an unknown shape")
    if value.get("completeness") != "COMPLETE":
        raise PaperLedgerRefused(f"{schema} evidence is not COMPLETE")
    captured = _timestamp(value.get("captured_at"), label=f"{schema} captured_at")
    _hash_field(value.get("commit_sha"), label="commit_sha")
    _hash_field(value.get("account_subject_sha256"),
                label="account_subject_sha256")
    _hash_field(value.get("plan_id_sha256"), label="plan_id_sha256")
    try:
        decision = date.fromisoformat(str(value.get("decision_session")))
        effective = date.fromisoformat(str(value.get("effective_session")))
    except ValueError as exc:
        raise PaperLedgerRefused("ledger sessions are not ISO dates") from exc
    if effective <= decision:
        raise PaperLedgerRefused("effective_session must follow decision_session")
    if _decimal(value.get("cash"), label="cash") < 0:
        raise PaperLedgerRefused("cash cannot be negative in the cash-only mirror")
    if _decimal(value.get("equity"), label="equity", positive=True) <= 0:
        raise PaperLedgerRefused("equity must be positive")

    positions = value.get("positions")
    if not isinstance(positions, Mapping):
        raise PaperLedgerRefused("positions must be a subject-to-quantity map")
    for subject, quantity in positions.items():
        _hash_field(subject, label="position security subject")
        if _decimal(quantity, label="position quantity") < 0:
            raise PaperLedgerRefused("a cash-only long position cannot be negative")

    orders = value.get("orders")
    if not isinstance(orders, list):
        raise PaperLedgerRefused("orders must be a list")
    order_keys = set()
    orders_by_key = {}
    valid_states = {state.value for state in CommandState}
    for index, order in enumerate(orders):
        if not isinstance(order, Mapping) or set(order) != ORDER_FIELDS:
            raise PaperLedgerRefused(f"order {index} has an unknown shape")
        key = _hash_field(order.get("client_key_sha256"),
                          label=f"order {index} client key")
        _hash_field(order.get("security_id_sha256"),
                    label=f"order {index} security")
        if key in order_keys:
            raise PaperLedgerRefused("orders contain a duplicate client key")
        order_keys.add(key)
        if order.get("side") not in {"BUY", "SELL"}:
            raise PaperLedgerRefused(f"order {index} side is invalid")
        quantity = _decimal(
            order.get("quantity"), label=f"order {index} quantity", positive=True)
        filled = _decimal(
            order.get("filled_quantity"), label=f"order {index} filled")
        if filled < 0 or filled > quantity:
            raise PaperLedgerRefused(f"order {index} filled quantity is invalid")
        if order.get("state") not in valid_states:
            raise PaperLedgerRefused(f"order {index} state is invalid")
        if order.get("state") == CommandState.FILLED.value and filled != quantity:
            raise PaperLedgerRefused(
                f"order {index} is FILLED without its full quantity")
        average = order.get("filled_average_price")
        if ((filled == 0 and average is not None)
                or (filled > 0 and _decimal(
                    average, label=f"order {index} average fill",
                    positive=True) <= 0)):
            raise PaperLedgerRefused(
                f"order {index} average fill price is inconsistent")
        orders_by_key[key] = order

    fills = value.get("fills")
    if not isinstance(fills, list):
        raise PaperLedgerRefused("fills must be a list")
    fill_keys = set()
    filled_by_order: dict[str, Decimal] = {}
    for index, fill in enumerate(fills):
        if not isinstance(fill, Mapping) or set(fill) != FILL_FIELDS:
            raise PaperLedgerRefused(f"fill {index} has an unknown shape")
        fill_key = _hash_field(
            fill.get("fill_sha256"), label=f"fill {index} identity")
        client_key = _hash_field(
            fill.get("client_key_sha256"), label=f"fill {index} client key")
        security_id = _hash_field(
            fill.get("security_id_sha256"), label=f"fill {index} security")
        if fill_key in fill_keys:
            raise PaperLedgerRefused("fills contain a duplicate identity")
        fill_keys.add(fill_key)
        fill_quantity = _decimal(
            fill.get("quantity"), label=f"fill {index} quantity", positive=True)
        _decimal(fill.get("price"), label=f"fill {index} price", positive=True)
        _timestamp(fill.get("filled_at"), label=f"fill {index} filled_at")
        order = orders_by_key.get(client_key)
        if order is None or order["security_id_sha256"] != security_id:
            raise PaperLedgerRefused(
                f"fill {index} has no matching order/security origin")
        filled_by_order[client_key] = (
            filled_by_order.get(client_key, Decimal(0)) + fill_quantity)
    for key, order in orders_by_key.items():
        if filled_by_order.get(key, Decimal(0)) != Decimal(
                order["filled_quantity"]):
            raise PaperLedgerRefused(
                "complete fill ledger does not equal the order filled quantity")

    actions = value.get("corporate_actions")
    if not isinstance(actions, list):
        raise PaperLedgerRefused("corporate_actions must be a list")
    action_keys = set()
    valid_action_kinds = {
        "SPLIT", "DIVIDEND", "MERGER", "DELISTING", "TICKER_CHANGE",
    }
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping) or set(action) != ACTION_FIELDS:
            raise PaperLedgerRefused(
                f"corporate action {index} has an unknown shape")
        key = _hash_field(
            action.get("action_sha256"), label=f"action {index} identity")
        _hash_field(action.get("security_id_sha256"),
                    label=f"action {index} security")
        if key in action_keys:
            raise PaperLedgerRefused("corporate actions contain a duplicate")
        action_keys.add(key)
        if action.get("kind") not in valid_action_kinds:
            raise PaperLedgerRefused(f"corporate action {index} kind is invalid")
        try:
            date.fromisoformat(str(action.get("effective_session")))
        except ValueError as exc:
            raise PaperLedgerRefused(
                f"corporate action {index} session is invalid") from exc
        _decimal(action.get("quantity_multiplier"),
                 label=f"action {index} multiplier", positive=True)
        _decimal(action.get("cash_amount"),
                 label=f"action {index} cash amount")
    normalized = json.loads(_canonical(value))
    return normalized, hashlib.sha256(raw).hexdigest(), captured


def _by(records: list[dict], key: str) -> dict[str, dict]:
    return {record[key]: record for record in records}


def _differences(expected: dict, observed: dict) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    identity_fields = (
        "commit_sha", "account_subject_sha256", "plan_id_sha256",
        "decision_session", "effective_session",
    )
    changed = [name for name in identity_fields
               if expected[name] != observed[name]]
    if changed:
        mismatches.append({
            "component": "subject", "subject_sha256": _sha(expected),
            "fields": changed,
        })
    for money in ("cash", "equity"):
        if abs(Decimal(expected[money]) - Decimal(observed[money])) \
                <= CASH_TOLERANCE:
            continue
        mismatches.append({
            "component": money, "subject_sha256": _sha({
                "account": expected["account_subject_sha256"],
                "plan": expected["plan_id_sha256"],
            }), "fields": [money],
        })
    for component, key in (("positions", None),
                           ("orders", "client_key_sha256"),
                           ("fills", "fill_sha256"),
                           ("corporate_actions", "action_sha256")):
        left = expected[component]
        right = observed[component]
        if key is not None:
            left = _by(left, key)
            right = _by(right, key)
        if left != right:
            subjects = sorted(set(left) | set(right))
            mismatches.append({
                "component": component,
                "subject_sha256": _sha(subjects),
                "fields": [component],
            })
    return mismatches


def certify(*, expected_path: Path, observed_path: Path, output: Path) -> dict:
    expected, expected_sha, expected_at = _load(
        expected_path, schema=EXPECTED_SCHEMA)
    observed, observed_sha, observed_at = _load(
        observed_path, schema=OBSERVED_SCHEMA)
    if observed_at < expected_at:
        raise PaperLedgerRefused(
            "observed ledger predates the expected ledger checkpoint")
    mismatches = _differences(expected, observed)
    report = {
        "schema": REPORT_SCHEMA,
        "scope": "ALPACA_PAPER_EXPECTED_OBSERVED",
        "performance_authority": "CERTIFIED_SHADOW_ONLY",
        "broker_mutation_attempts": 0,
        "expected_sha256": expected_sha,
        "observed_sha256": observed_sha,
        "subject": {
            "commit_sha": expected["commit_sha"],
            "account_subject_sha256": expected["account_subject_sha256"],
            "plan_id_sha256": expected["plan_id_sha256"],
            "decision_session": expected["decision_session"],
            "effective_session": expected["effective_session"],
        },
        "expected_captured_at": expected["captured_at"],
        "observed_captured_at": observed["captured_at"],
        "cash_tolerance": str(CASH_TOLERANCE),
        "mismatches": mismatches,
        "mismatch_count": len(mismatches),
        "verdict": "MATCH" if not mismatches else "DIVERGED",
        "certification_passed": not mismatches,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(report) + b"\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = certify(
            expected_path=args.expected,
            observed_path=args.observed,
            output=args.output,
        )
    except PaperLedgerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "certification_passed": report["certification_passed"],
        "mismatch_count": report["mismatch_count"],
        "verdict": report["verdict"],
    }, sort_keys=True))
    return 0 if report["certification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
