from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from sentinel.execution.native_activity import (
    NativeActivityRefused, activity_evidence, canonical_json, decode_canonical_json,
    normalize_activity,
)


SUBJECT = "a" * 64
ACCOUNT = "11111111-1111-1111-1111-111111111111"
ORDER_ID = "22222222-2222-2222-2222-222222222222"
ASSET = "33333333-3333-3333-3333-333333333333"


def order():
    return {"id": ORDER_ID, "asset_id": ASSET, "side": "buy", "filled_qty": "2",
            "filled_avg_price": "10", "submitted_at": "2026-10-15T13:30:00Z",
            "filled_at": "2026-10-15T13:30:02Z", "account_id": ACCOUNT}


def fill():
    return {"id": "native-fill-1", "activity_type": "FILL", "order_id": ORDER_ID,
            "qty": "2", "price": "10", "transaction_time": "2026-10-15T13:30:01Z"}


def cash(kind="DIV", amount="1.25"):
    return {"id": "native-cash-1", "activity_type": kind, "date": "2026-10-14",
            "net_amount": amount}


def normalize(payload, **kwargs):
    return normalize_activity(payload, subject_sha256=SUBJECT, account_id=ACCOUNT, **kwargs)


def test_exact_order_enrichment_never_uses_symbol():
    payload = dict(fill(), symbol="IGNORED")
    result = normalize(payload, order=order())
    assert result.disposition == "ACCEPTED"
    assert result.fill.asset_id == ASSET
    assert result.fill.as_broker_fill().asset_id == ASSET
    assert normalize(payload).reason_code == "EXACT_ORDER_REQUIRED"


@pytest.mark.parametrize("change,expected", [
    ({"asset_id": "44444444-4444-4444-4444-444444444444"}, "FILL_ORDER_ASSET_MISMATCH"),
    ({"side": "sell"}, "FILL_ORDER_SIDE_MISMATCH"),
    ({"qty": "3"}, "FILL_EXCEEDS_ORDER_QUANTITY"),
    ({"notional": "19"}, "FILL_GROSS_MISMATCH"),
    ({"qty": 1.0}, "INVALID_NATIVE_DECIMAL"),
    ({"price": "NaN"}, "INVALID_NATIVE_DECIMAL"),
    ({"transaction_time": "2026-10-15T13:29:00Z"}, "FILL_PRECEDES_ORDER"),
    ({"transaction_time": "2026-10-15T13:31:00Z"}, "FILL_FOLLOWS_ORDER_FILL"),
    ({"account_id": "other"}, "CROSS_ACCOUNT_NATIVE_EVIDENCE"),
    ({"type": "unknown"}, "UNSUPPORTED_FILL_EXECUTION_TYPE"),
    ({"type": "fill", "execution_type": "partial_fill"}, "UNSUPPORTED_FILL_EXECUTION_TYPE"),
    ({"type": "trade_bust", "execution_type": "fill"}, "CORRECTION_REQUIRES_REBOOKING"),
    ({"qty": "1e999999999"}, "NATIVE_DECIMAL_BOUND_EXCEEDED"),
    ({"price": "1e-999999999"}, "NATIVE_DECIMAL_BOUND_EXCEEDED"),
])
def test_fill_identity_and_economic_falsifiers(change, expected):
    result = normalize(dict(fill(), **change), order=order())
    assert result.disposition == "QUARANTINED" and result.reason_code == expected


@pytest.mark.parametrize("kind,external", [("DIV", False), ("FEE", False), ("INT", False),
                                            ("WH", False), ("CSD", True), ("CSW", True)])
def test_cash_classification_reuses_execution_ledger_model(kind, external):
    result = normalize(cash(kind, "-1.25" if kind in {"FEE", "WH", "CSW"} else "1.25"))
    assert result.disposition == "ACCEPTED"
    assert (result.cash.classification == "EXTERNAL") is external
    assert isinstance(result.cash.net_amount, Decimal)


@pytest.mark.parametrize("payload,code", [
    (cash("NEW_ACTION", "0"), "UNSUPPORTED_NATIVE_ACTIVITY"),
    (cash("ACATS", "0"), "UNSUPPORTED_SECURITIES_ACTIVITY"),
    (cash("JNL", "0"), "UNSUPPORTED_NATIVE_ACTIVITY"),
    (cash("MEM", "0"), "UNSUPPORTED_NATIVE_ACTIVITY"),
    (cash("SSP", "0"), "UNSUPPORTED_NATIVE_ACTIVITY"),
    (cash("SSO", "0"), "UNSUPPORTED_NATIVE_ACTIVITY"),
    (cash("SC", "0"), "UNSUPPORTED_NATIVE_ACTIVITY"),
    (cash("CSD", "-1"), "CASH_TRANSFER_SIGN_MISMATCH"),
    (cash("CSD", "0"), "CASH_TRANSFER_SIGN_MISMATCH"),
    (cash("CSW", "1"), "CASH_TRANSFER_SIGN_MISMATCH"),
    (cash("CSW", "0"), "CASH_TRANSFER_SIGN_MISMATCH"),
    (dict(cash(), activity_subtype="SDIV"), "UNSUPPORTED_SECURITIES_ACTIVITY"),
    (dict(cash(), previous_id="earlier"), "CORRECTION_REQUIRES_REBOOKING"),
    (dict(fill(), type="trade_bust"), "CORRECTION_REQUIRES_REBOOKING"),
    (dict(cash(), currency="EUR"), "UNSUPPORTED_NATIVE_CURRENCY"),
    (dict(cash(), status="pending"), "UNEXECUTED_NATIVE_ACTIVITY"),
    (dict(cash(), net_amount=None), "INVALID_NATIVE_DECIMAL"),
])
def test_unsupported_and_correction_evidence_is_retained(payload, code):
    result = normalize(payload, order=order())
    assert result.disposition == "QUARANTINED" and result.reason_code == code
    assert result.evidence.payload_json and result.fill is None and result.cash is None


def test_restart_replay_is_explicit_and_changed_native_id_quarantines():
    first = normalize(cash())
    assert normalize(deepcopy(cash()), prior_evidence=(first.evidence,)).disposition == "REPLAY"
    changed = normalize(cash(amount="2.50"), prior_evidence=(first.evidence,))
    assert changed.reason_code == "CHANGED_NATIVE_ACTIVITY_ID"
    assert changed.evidence.source_sha256 != first.evidence.source_sha256
    wrong_subject = activity_evidence(cash(), subject_sha256="b" * 64)
    assert normalize(cash(), prior_evidence=(wrong_subject,)).reason_code == "CROSS_SUBJECT_EVIDENCE"


def test_exact_gross_does_not_depend_on_ambient_decimal_context():
    payload = dict(fill(), qty="1.000000001", price="123.123456789", notional="123.123456912123456789")
    exact_order = dict(order(), filled_qty=payload["qty"])
    with localcontext() as ctx:
        ctx.prec = 6
        assert normalize(payload, order=exact_order).disposition == "ACCEPTED"


def test_evidence_hash_is_bound_to_subject_and_canonical_payload():
    first = activity_evidence(cash(), subject_sha256=SUBJECT)
    assert first == activity_evidence(dict(reversed(list(cash().items()))), subject_sha256=SUBJECT)
    assert first.source_sha256 != activity_evidence(cash(), subject_sha256="b" * 64).source_sha256
    with pytest.raises(NativeActivityRefused):
        activity_evidence({"x": float("nan")}, subject_sha256=SUBJECT)


def test_decimal_evidence_roundtrips_exactly_without_tag_or_string_collisions():
    value = {"amount": Decimal("123.000000000000000000001"),
             "nested": [Decimal("1.00"), "1.00", 1, 1.0, True, None]}
    encoded = canonical_json(value)
    restored = decode_canonical_json(encoded)
    assert restored == value and isinstance(restored["amount"], Decimal)
    assert str(restored["nested"][0]) == "1.00"
    assert canonical_json(Decimal("1")) != canonical_json("1") != canonical_json(1)
    assert canonical_json(Decimal("1")) != canonical_json({"decimal": "1"})
    payload = dict(cash(), net_amount=Decimal("1.25"))
    first = normalize(payload)
    assert first.disposition == "ACCEPTED"
    assert normalize(payload, prior_evidence=(first.evidence,)).disposition == "REPLAY"


@pytest.mark.parametrize("encoded", ['["int","01"]', '["decimal","NaN"]',
    '["map",[["a",["null"]],["a",["null"]]]]', '["other",1]'])
def test_noncanonical_evidence_refuses(encoded):
    with pytest.raises(NativeActivityRefused):
        decode_canonical_json(encoded)


@pytest.mark.parametrize("native_id", ["has\ncontrol", "a" * 257, "", "trailing "])
def test_native_id_is_a_bounded_opaque_cursor(native_id):
    result = normalize(dict(cash(), id=native_id))
    assert result.reason_code == "INVALID_NATIVE_ACTIVITY_ID"
    assert result.evidence.payload_json


def test_decimal_resource_bound_precedes_fraction_arithmetic():
    assert normalize(cash(amount="1e31")).reason_code == "NATIVE_DECIMAL_BOUND_EXCEEDED"


def test_native_id_length_guard():
    assert normalize(dict(cash(), id="a" * 257)).reason_code == "INVALID_NATIVE_ACTIVITY_ID"
