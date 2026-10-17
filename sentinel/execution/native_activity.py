from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sentinel.execution.broker_cash import BrokerCashActivity
from sentinel.execution.contract import Side


class NativeActivityRefused(ValueError):
    pass


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, arbitrary_types_allowed=True)


class NativeActivityEvidence(_Record):
    subject_sha256: str
    native_id: str | None
    payload_json: str
    payload_sha256: str
    source_sha256: str
    order_identity_sha256: str | None = None


class NativeFill(_Record):
    activity_id: str
    broker_order_id: str
    asset_id: str
    side: Side
    quantity: Decimal
    price: Decimal
    executed_at: datetime
    client_key: str | None = None

    def as_broker_fill(self):
        from sentinel.execution.alpaca import NativeBrokerFill
        return NativeBrokerFill(
            activity_id=self.activity_id, broker_order_id=self.broker_order_id,
            asset_id=self.asset_id, side=self.side, quantity=self.quantity,
            price=self.price, filled_at=self.executed_at, client_key=self.client_key)


class NativeActivityResult(_Record):
    disposition: Literal["ACCEPTED", "REPLAY", "QUARANTINED"]
    evidence: NativeActivityEvidence
    reason_code: str | None = None
    fill: NativeFill | None = None
    cash: BrokerCashActivity | None = None


_CASH_TYPES = frozenset({
    "CSD", "CSW", "ACATC", "JNLC",
    "DIV", "DIVNRA", "DIVCGL", "DIVCGS", "DIVFEE", "DIVFT", "DIVROC",
    "DIVTW", "DIVTXEX", "FEE", "CFEE", "INT", "INTNRA", "INTTW", "WH",
    "CGD", "PTC", "PTR",
})
_SECURITIES_TYPES = frozenset({"ACATS", "FOPT", "JNLS", "SPLIT", "SPIN", "MA", "NC", "REORG", "OPCA"})


def canonical_json(value: Any) -> str:
    def encode(item):
        if item is None:
            return ["null"]
        if type(item) is bool:
            return ["bool", item]
        if type(item) is str:
            return ["str", item]
        if type(item) is int:
            return ["int", str(item)]
        if isinstance(item, Decimal) and item.is_finite():
            return ["decimal", str(item)]
        if type(item) is float and math.isfinite(item):
            return ["float", repr(item)]
        if isinstance(item, (list, tuple)):
            return ["list", [encode(value) for value in item]]
        if isinstance(item, dict) and all(type(key) is str for key in item):
            return ["map", [[key, encode(item[key])] for key in sorted(item)]]
        raise NativeActivityRefused("NON_JSON_NATIVE_EVIDENCE")
    try:
        return json.dumps(encode(value), separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise NativeActivityRefused("NON_JSON_NATIVE_EVIDENCE") from exc


def decode_canonical_json(encoded: str) -> Any:
    def decode(item):
        if not isinstance(item, list) or not item or type(item[0]) is not str:
            raise NativeActivityRefused("INVALID_CANONICAL_NATIVE_EVIDENCE")
        kind = item[0]
        if kind == "null" and len(item) == 1:
            return None
        if len(item) != 2:
            raise NativeActivityRefused("INVALID_CANONICAL_NATIVE_EVIDENCE")
        value = item[1]
        if kind == "str" and type(value) is str:
            return value
        if kind == "bool" and type(value) is bool:
            return value
        if kind == "int" and type(value) is str:
            return int(value)
        if kind == "decimal" and type(value) is str:
            return Decimal(value)
        if kind == "float" and type(value) is str:
            return float(value)
        if kind == "list" and isinstance(value, list):
            return [decode(entry) for entry in value]
        if kind == "map" and isinstance(value, list):
            result = {}
            for pair in value:
                if (not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not str
                        or pair[0] in result):
                    raise NativeActivityRefused("INVALID_CANONICAL_NATIVE_EVIDENCE")
                result[pair[0]] = decode(pair[1])
            return result
        raise NativeActivityRefused("INVALID_CANONICAL_NATIVE_EVIDENCE")
    try:
        result = decode(json.loads(encoded))
        if canonical_json(result) != encoded:
            raise NativeActivityRefused("INVALID_CANONICAL_NATIVE_EVIDENCE")
        return result
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise NativeActivityRefused("INVALID_CANONICAL_NATIVE_EVIDENCE") from exc


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def activity_evidence(payload: Any, *, subject_sha256: str,
                      order_identity_sha256: str | None = None) -> NativeActivityEvidence:
    if (not isinstance(subject_sha256, str) or len(subject_sha256) != 64
            or any(c not in "0123456789abcdef" for c in subject_sha256)):
        raise NativeActivityRefused("INVALID_SUBJECT_HASH")
    if order_identity_sha256 is not None and (
            not isinstance(order_identity_sha256, str) or len(order_identity_sha256) != 64
            or any(c not in "0123456789abcdef" for c in order_identity_sha256)):
        raise NativeActivityRefused("INVALID_ORDER_IDENTITY_HASH")
    encoded = canonical_json(payload)
    native_id = payload.get("id") if isinstance(payload, dict) else None
    native_id = native_id if isinstance(native_id, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", native_id) else None
    digest = _sha(encoded)
    return NativeActivityEvidence(subject_sha256=subject_sha256, native_id=native_id,
        payload_json=encoded, payload_sha256=digest,
        order_identity_sha256=order_identity_sha256,
        source_sha256=_sha(canonical_json({"subject_sha256": subject_sha256,
            "payload_sha256": digest, "order_identity_sha256": order_identity_sha256})))


def validate_evidence(evidence: NativeActivityEvidence, *, subject_sha256: str) -> None:
    if not isinstance(evidence, NativeActivityEvidence) or evidence.subject_sha256 != subject_sha256:
        raise NativeActivityRefused("CROSS_SUBJECT_EVIDENCE")
    actual = activity_evidence(decode_canonical_json(evidence.payload_json),
        subject_sha256=subject_sha256, order_identity_sha256=evidence.order_identity_sha256)
    if actual != evidence:
        raise NativeActivityRefused("CHANGED_SOURCE_EVIDENCE")


def aware_time(value: Any) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise NativeActivityRefused("INVALID_NATIVE_TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    except ValueError as exc:
        raise NativeActivityRefused("INVALID_NATIVE_TIME") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NativeActivityRefused("INVALID_NATIVE_TIME")
    return parsed.astimezone(timezone.utc)


def _text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise NativeActivityRefused(code)
    return value


def _uuid(value: Any, code: str) -> str:
    text = _text(value, code)
    try:
        parsed = str(UUID(text))
    except ValueError as exc:
        raise NativeActivityRefused(code) from exc
    if parsed != text.lower():
        raise NativeActivityRefused(code)
    return parsed


def _decimal(value: Any, *, positive: bool = False) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise NativeActivityRefused("INVALID_NATIVE_DECIMAL")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise NativeActivityRefused("INVALID_NATIVE_DECIMAL") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise NativeActivityRefused("INVALID_NATIVE_DECIMAL")
    if (len(number.as_tuple().digits) > 64 or abs(number.as_tuple().exponent) > 64
            or (number != 0 and abs(number.adjusted()) > 30)):
        raise NativeActivityRefused("NATIVE_DECIMAL_BOUND_EXCEEDED")
    return number


def _account(payload: Mapping, account_id: str) -> None:
    if "account_id" in payload and payload["account_id"] != account_id:
        raise NativeActivityRefused("CROSS_ACCOUNT_NATIVE_EVIDENCE")


def _fill(payload: dict, order: Mapping | None, account_id: str) -> NativeFill:
    order_id = _uuid(payload.get("order_id"), "INVALID_NATIVE_ORDER_ID")
    if not isinstance(order, Mapping) or _uuid(order.get("id"), "INVALID_EXACT_ORDER") != order_id:
        raise NativeActivityRefused("EXACT_ORDER_REQUIRED")
    _account(order, account_id)
    asset_id = _uuid(order.get("asset_id"), "INVALID_NATIVE_ASSET_ID")
    if payload.get("asset_id") is not None and _uuid(payload["asset_id"], "INVALID_NATIVE_ASSET_ID") != asset_id:
        raise NativeActivityRefused("FILL_ORDER_ASSET_MISMATCH")
    side = _text(order.get("side"), "INVALID_NATIVE_SIDE")
    if side not in {"buy", "sell"} or (payload.get("side") is not None and payload["side"] != side):
        raise NativeActivityRefused("FILL_ORDER_SIDE_MISMATCH")
    quantity, price = _decimal(payload.get("qty"), positive=True), _decimal(payload.get("price"), positive=True)
    for key in ("gross_amount", "notional"):
        if key in payload and Fraction(_decimal(payload[key], positive=True)) != Fraction(quantity) * Fraction(price):
            raise NativeActivityRefused("FILL_GROSS_MISMATCH")
    filled = _decimal(order.get("filled_qty"), positive=True)
    if quantity > filled:
        raise NativeActivityRefused("FILL_EXCEEDS_ORDER_QUANTITY")
    executed = aware_time(payload.get("transaction_time"))
    if executed < aware_time(order.get("submitted_at")):
        raise NativeActivityRefused("FILL_PRECEDES_ORDER")
    if order.get("filled_at") is not None and executed > aware_time(order["filled_at"]):
        raise NativeActivityRefused("FILL_FOLLOWS_ORDER_FILL")
    key = order.get("client_order_id")
    if key is not None:
        key = _text(key, "INVALID_CLIENT_ORDER_ID")
    if payload.get("client_order_id") is not None and payload["client_order_id"] != key:
        raise NativeActivityRefused("FILL_ORDER_CLIENT_KEY_MISMATCH")
    return NativeFill(activity_id=payload["id"], broker_order_id=order_id,
        asset_id=asset_id, side=Side.BUY if side == "buy" else Side.SELL,
        quantity=quantity, price=price, executed_at=executed, client_key=key)


def normalize_activity(payload: Any, *, subject_sha256: str, account_id: str,
                       order: Mapping | None = None,
                       prior_evidence: tuple[NativeActivityEvidence, ...] = ()) -> NativeActivityResult:
    evidence = activity_evidence(payload, subject_sha256=subject_sha256)
    try:
        for prior in prior_evidence:
            validate_evidence(prior, subject_sha256=subject_sha256)
        if not isinstance(payload, dict) or evidence.native_id is None:
            raise NativeActivityRefused("INVALID_NATIVE_ACTIVITY_ID")
        same_id = [item for item in prior_evidence if item.native_id == evidence.native_id]
        if any(item.payload_sha256 != evidence.payload_sha256 for item in same_id):
            raise NativeActivityRefused("CHANGED_NATIVE_ACTIVITY_ID")
        _account(payload, account_id)
        if payload.get("currency", "USD") != "USD":
            raise NativeActivityRefused("UNSUPPORTED_NATIVE_CURRENCY")
        if payload.get("status", "executed") != "executed":
            raise NativeActivityRefused("UNEXECUTED_NATIVE_ACTIVITY")
        executions = [str(payload[key]).lower() for key in ("execution_type", "type") if key in payload]
        if any(payload.get(key) for key in ("previous_id", "correction_id", "replaces", "replaced_by")) or any(value in {"trade_correct", "trade_bust", "correction", "bust"} for value in executions):
            raise NativeActivityRefused("CORRECTION_REQUIRES_REBOOKING")
        kind = _text(payload.get("activity_type"), "INVALID_ACTIVITY_TYPE")
        if kind == "FILL":
            if any(value not in {"fill", "partial_fill"} for value in executions) or len(set(executions)) > 1:
                raise NativeActivityRefused("UNSUPPORTED_FILL_EXECUTION_TYPE")
            fill, cash = _fill(payload, order, account_id), None
            order_identity = _sha(canonical_json({"order_id": fill.broker_order_id,
                "asset_id": fill.asset_id, "side": fill.side.value,
                "client_key": fill.client_key,
                "submitted_at": aware_time(order["submitted_at"]).isoformat()}))
            evidence = activity_evidence(payload, subject_sha256=subject_sha256,
                order_identity_sha256=order_identity)
            if any(item.order_identity_sha256 != order_identity for item in same_id):
                raise NativeActivityRefused("CHANGED_NATIVE_ORDER_IDENTITY")
        elif kind in _SECURITIES_TYPES or str(payload.get("activity_subtype", "")).upper() == "SDIV":
            raise NativeActivityRefused("UNSUPPORTED_SECURITIES_ACTIVITY")
        elif kind in _CASH_TYPES:
            try:
                day = date.fromisoformat(_text(payload.get("date"), "INVALID_CASH_DATE"))
            except ValueError as exc:
                raise NativeActivityRefused("INVALID_CASH_DATE") from exc
            fill = None
            amount = _decimal(payload.get("net_amount"))
            if (kind == "CSD" and amount <= 0) or (kind == "CSW" and amount >= 0):
                raise NativeActivityRefused("CASH_TRANSFER_SIGN_MISMATCH")
            cash = BrokerCashActivity(activity_id=evidence.native_id, activity_type=kind,
                activity_date=day, net_amount=amount, raw=dict(payload))
        else:
            raise NativeActivityRefused("UNSUPPORTED_NATIVE_ACTIVITY")
        return NativeActivityResult(disposition="REPLAY" if same_id else "ACCEPTED",
            evidence=evidence, fill=fill, cash=cash)
    except NativeActivityRefused as exc:
        return NativeActivityResult(disposition="QUARANTINED", evidence=evidence, reason_code=str(exc))
