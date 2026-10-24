"""Isolated accounting candidate; no broker, database, credentials or authority."""
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from sentinel.execution import trade_rebooking as ledger
from sentinel.execution.contract import Side
from sentinel.execution.native_activity import canonical_json, decode_canonical_json


ACCOUNT = "11111111-1111-1111-1111-111111111111"
ORDER = "22222222-2222-2222-2222-222222222222"
ASSET = "33333333-3333-3333-3333-333333333333"
OTHER = "44444444-4444-4444-4444-444444444444"
EXECUTED = datetime(2026, 10, 23, 13, 31, tzinfo=timezone.utc)
_REFS = tuple(f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 8))
_EVENTS = tuple(f"01K0000000000000000000000{index}" for index in range(1, 8))


def event(index=0, *, kind=ledger.TradeKind.FILL, previous=None, **changes):
    fields = {"account_id": ACCOUNT, "event_id": _EVENTS[index],
        "activity_id": _REFS[index], "broker_order_id": ORDER,
        "asset_id": ASSET, "side": Side.BUY, "kind": kind,
        "executed_at": EXECUTED,
        # This is intentionally not a native parser. Raw wire evidence and
        # the explicitly supplied interpretation are separate commitments.
        "native_evidence_json": canonical_json({"wire_ref": _REFS[index],
            "uninterpreted": {"qty": "provider-specific"}}),
        "previous_activity_id": previous,
        "quantity": None if kind is ledger.TradeKind.BUST else Decimal("2"),
        "price": None if kind is ledger.TradeKind.BUST else Decimal("10")}
    return ledger.TradeEvent(**(fields | changes))


def run(*events):
    return ledger.replay(events, account_id=ACCOUNT)


def quantities(projection):
    return {item.asset_id: item.quantity for item in projection.position_deltas}


def test_fill_and_independent_partial_fills_keep_native_identity():
    result = run(event(), event(1, quantity=Decimal("3"), price=Decimal("11")))
    assert quantities(result) == {ASSET: Decimal("5")}
    assert result.gross_trade_cash_delta == Decimal("-53")
    assert result.active_activity_ids == _REFS[:2]
    assert result.unique_events == 2 and result.replayed_events == 0
    assert not result.provider_finality_proven
    assert not result.settlement_proven and not result.live_authority_granted


@pytest.mark.parametrize("side,cash", [(Side.BUY, "-36"), (Side.SELL, "36")])
def test_correction_reverses_exact_original_then_applies_replacement(side, cash):
    original = event(side=side)
    correction = event(1, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0],
                       quantity=Decimal("3"), price=Decimal("12"), side=side)
    result = run(original, correction)
    assert quantities(result) == {ASSET: Decimal("3") * (1 if side is Side.BUY else -1)}
    assert result.gross_trade_cash_delta == Decimal(cash)
    assert result.active_activity_ids == (_REFS[1],)


def test_chained_correction_and_bust_do_not_reverse_another_partial_fill():
    events = (event(), event(1, quantity=Decimal("1"), price=Decimal("9")),
        event(2, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0], price=Decimal("11")),
        event(3, kind=ledger.TradeKind.CORRECTION, previous=_REFS[2], quantity=Decimal("3")),
        event(4, kind=ledger.TradeKind.BUST, previous=_REFS[3]))
    result = run(*events)
    assert quantities(result) == {ASSET: Decimal("1")}
    assert result.gross_trade_cash_delta == Decimal("-9")
    assert result.active_activity_ids == (_REFS[1],)
    assert run(events[0], event(1, kind=ledger.TradeKind.BUST, previous=_REFS[0])).position_deltas == ()


def test_late_business_time_obeys_publication_sequence():
    correction = event(1, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0],
        executed_at=datetime(2026, 10, 22, 13, 31, tzinfo=timezone.utc), price=Decimal("8"))
    assert run(event(), correction).gross_trade_cash_delta == Decimal("-16")


def test_exact_duplicate_replay_is_idempotent_even_behind_current_cursor():
    original = event()
    correction = event(1, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0], price=Decimal("8"))
    once, duplicate = run(original, correction), run(original, correction, original, correction)
    assert duplicate.replayed_events == 2
    assert duplicate.position_deltas == once.position_deltas
    assert duplicate.gross_trade_cash_delta == once.gross_trade_cash_delta
    assert duplicate.ledger_sha256 == once.ledger_sha256


@pytest.mark.parametrize("change", [{"quantity": Decimal("3")},
    {"price": Decimal("9")}, {"broker_order_id": OTHER}, {"asset_id": OTHER},
    {"event_id": _EVENTS[2]}, {"native_evidence_json": canonical_json({"changed": True})}])
def test_changed_native_activity_payload_is_never_replay(change):
    with pytest.raises(ledger.TradeRebookingRefused, match="identity changed"):
        run(event(), event(**change))


def test_event_identity_collision_and_publication_regression_refuse():
    with pytest.raises(ledger.TradeRebookingRefused, match="publication identity reused"):
        run(event(), event(1, event_id=_EVENTS[0]))
    with pytest.raises(ledger.TradeRebookingRefused, match="publication order regressed"):
        run(event(1), event())


@pytest.mark.parametrize("kind", [ledger.TradeKind.CORRECTION, ledger.TradeKind.BUST])
def test_missing_and_inactive_predecessors_refuse(kind):
    operation = event(1, kind=kind, previous=_REFS[0])
    with pytest.raises(ledger.TradeRebookingRefused, match="missing or inactive"):
        run(operation)
    replacement = event(2, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0])
    with pytest.raises(ledger.TradeRebookingRefused, match="missing or inactive"):
        run(event(), operation, replacement)


@pytest.mark.parametrize("change", [{"broker_order_id": OTHER}, {"asset_id": OTHER},
    {"side": Side.SELL}])
def test_predecessor_order_asset_and_side_must_agree(change):
    correction = event(1, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0], **change)
    with pytest.raises(ledger.TradeRebookingRefused, match="order/asset/side changed"):
        run(event(), correction)


def test_cross_account_is_rejected_before_any_economics():
    with pytest.raises(ledger.TradeRebookingRefused, match="cross-account"):
        run(event(account_id=OTHER))


@pytest.mark.parametrize("change", [
    {"account_id": "not-a-uuid"}, {"activity_id": "synthetic-symbol"},
    {"event_id": "01k00000000000000000000001"},
    {"event_id": "81K000000000000000000000001"},
    {"quantity": Decimal("0")}, {"quantity": Decimal("-1")},
    {"quantity": Decimal("NaN")}, {"price": Decimal("Infinity")},
    {"price": Decimal("1e31")}, {"price": Decimal("1e-65")},
    {"price": Decimal("1." + "1" * 64)}, {"quantity": 1.0},
    {"executed_at": EXECUTED.replace(tzinfo=None)},
    {"previous_activity_id": _REFS[0]},
    {"kind": "FILL"}, {"side": "BUY"},
    {"native_evidence_json": "{}"},
])
def test_typed_event_invalid_input_falsifiers(change):
    with pytest.raises((ValidationError, ledger.TradeRebookingRefused, ValueError)):
        event(**change)


def test_bust_is_explicit_interpretation_without_replacement_or_wire_parser():
    with pytest.raises(ValidationError, match="replacement economics"):
        event(1, kind=ledger.TradeKind.BUST, previous=_REFS[0], quantity=Decimal("2"))
    with pytest.raises(ValidationError, match="predecessor"):
        event(1, kind=ledger.TradeKind.CORRECTION)
    with pytest.raises(ValidationError):
        ledger.TradeEvent(**(event().model_dump() | {"commission": Decimal("1")}))
    bust = event(1, kind=ledger.TradeKind.BUST, previous=_REFS[0])
    assert run(event(), bust).gross_trade_cash_delta == 0
    assert decode_canonical_json(bust.native_evidence_json)["uninterpreted"] == {"qty": "provider-specific"}


def test_frozen_model_copy_cannot_bypass_accounting_boundary_validation():
    forged = event().model_copy(update={"quantity": Decimal("-1")})
    with pytest.raises(ValidationError, match="positive Decimal"):
        run(forged)
    with pytest.raises(ValidationError):
        event().price = Decimal("1")


def test_exact_arithmetic_is_independent_of_ambient_decimal_precision():
    original = event(quantity=Decimal("1.000000001"), price=Decimal("123.123456789"))
    corrected = event(1, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0],
                     quantity=Decimal("2.000000003"), price=Decimal("99.123456789"))
    with localcontext() as context:
        context.prec = 5
        result = run(original, corrected)
    assert quantities(result) == {ASSET: Decimal("2.000000003")}
    assert result.gross_trade_cash_delta == Decimal("-198.246913875370370367")


def test_envelope_recovery_replays_original_bytes_and_keeps_source_evidence():
    original = event()
    correction = event(1, kind=ledger.TradeKind.CORRECTION, previous=_REFS[0], price=Decimal("7"))
    rows = (original, correction, original)
    sealed = ledger.seal(rows, account_id=ACCOUNT)
    recovered = ledger.recover(sealed.envelope_json, expected_sha256=sealed.sha256, account_id=ACCOUNT)
    assert recovered == run(*rows)
    envelope = decode_canonical_json(sealed.envelope_json)
    assert set(envelope) == {"schema", "account_id", "events", "event_sha256"}
    assert decode_canonical_json(envelope["events"][0])["native_evidence_json"] == original.native_evidence_json
    assert "gross_trade_cash_delta" not in envelope


def test_seal_revalidates_copied_models_before_committing_canonical_bytes():
    supplied = event().model_copy(update={"executed_at": EXECUTED.astimezone(
        timezone(timedelta(hours=-7)))})
    sealed = ledger.seal((supplied,), account_id=ACCOUNT)
    assert ledger.recover(sealed.envelope_json, expected_sha256=sealed.sha256,
                          account_id=ACCOUNT) == run(supplied)


def _reseal_payload(payload):
    encoded = canonical_json(payload)
    return encoded, hashlib.sha256(encoded.encode()).hexdigest()


def test_changed_envelope_cannot_retain_the_original_external_digest():
    sealed = ledger.seal((event(),), account_id=ACCOUNT)
    payload = decode_canonical_json(sealed.envelope_json)
    row = decode_canonical_json(payload["events"][0])
    row["price"] = Decimal("999")
    payload["events"][0] = canonical_json(row)
    payload["event_sha256"][0] = hashlib.sha256(payload["events"][0].encode()).hexdigest()
    changed, _ = _reseal_payload(payload)
    with pytest.raises(ledger.TradeRebookingRefused, match="original envelope byte identity"):
        ledger.recover(changed, expected_sha256=sealed.sha256, account_id=ACCOUNT)


@pytest.mark.parametrize("change,reason", [
    ({"schema": "unknown"}, "subject/schema"),
    ({"account_id": OTHER}, "subject/schema"),
    ({"derived_cash": Decimal("0")}, "subject/schema"),
    ({"event_sha256": []}, "bounded event envelope"),
    ({"event_sha256": ["0" * 64]}, "original event byte identity"),
])
def test_recovery_revalidates_contents_even_with_matching_outer_digest(change, reason):
    sealed = ledger.seal((event(),), account_id=ACCOUNT)
    payload = decode_canonical_json(sealed.envelope_json) | change
    encoded, digest = _reseal_payload(payload)
    with pytest.raises(ledger.TradeRebookingRefused, match=reason):
        ledger.recover(encoded, expected_sha256=digest, account_id=ACCOUNT)


def test_recovery_revalidates_typed_economics_and_chain_not_saved_totals():
    sealed = ledger.seal((event(),), account_id=ACCOUNT)
    payload = decode_canonical_json(sealed.envelope_json)
    row = decode_canonical_json(payload["events"][0])
    row.update(kind="CORRECTION", previous_activity_id=_REFS[6])
    payload["events"][0] = canonical_json(row)
    payload["event_sha256"][0] = hashlib.sha256(payload["events"][0].encode()).hexdigest()
    encoded, digest = _reseal_payload(payload)
    with pytest.raises(ledger.TradeRebookingRefused, match="missing or inactive"):
        ledger.recover(encoded, expected_sha256=digest, account_id=ACCOUNT)


def test_resource_bounds_apply_to_replays_evidence_and_recovery(monkeypatch):
    with pytest.raises(ledger.TradeRebookingRefused, match="bounded event tuple"):
        ledger.replay([event()], account_id=ACCOUNT)
    with pytest.raises(ledger.TradeRebookingRefused, match="bounded event tuple"):
        ledger.replay((event(),) * (ledger.MAX_EVENTS + 1), account_id=ACCOUNT)
    monkeypatch.setattr(ledger, "MAX_EVENTS", 1)
    with pytest.raises(ledger.TradeRebookingRefused, match="bounded event tuple"):
        run(event(), event())
    monkeypatch.setattr(ledger, "MAX_EVENT_BYTES", 8)
    with pytest.raises(ValidationError, match="evidence byte limit"):
        event()
    monkeypatch.setattr(ledger, "MAX_EVENT_BYTES", 64 * 1024)
    monkeypatch.setattr(ledger, "MAX_ENVELOPE_BYTES", 8)
    with pytest.raises(ledger.TradeRebookingRefused, match="ledger byte limit"):
        run(event())
    with pytest.raises(ledger.TradeRebookingRefused, match="envelope byte identity"):
        ledger.recover("x" * 9, expected_sha256="a" * 64, account_id=ACCOUNT)


def _nested_canonical(depth):
    # Construct valid canonical JSON without depending on the interpreter's
    # recursive encoder to build the hostile input itself.
    return '["list",[' * depth + '["null"]' + ']]' * depth


def test_small_valid_nested_native_evidence_remains_accepted_and_recoverable():
    original = event(native_evidence_json=_nested_canonical(20))
    sealed = ledger.seal((original,), account_id=ACCOUNT)
    assert ledger.recover(sealed.envelope_json, expected_sha256=sealed.sha256,
                          account_id=ACCOUNT) == run(original)


def test_excessively_nested_native_evidence_is_a_typed_refusal():
    encoded = _nested_canonical(3000)
    assert len(encoded.encode()) < ledger.MAX_EVENT_BYTES
    with pytest.raises(ValidationError, match="excessively nested canonical evidence"):
        event(native_evidence_json=encoded)


@pytest.mark.parametrize("encoded", [_nested_canonical(3000), 'not-canonical-json'])
def test_corrupt_or_deep_envelope_is_a_typed_refusal(encoded):
    assert len(encoded.encode()) < ledger.MAX_ENVELOPE_BYTES
    with pytest.raises(ledger.TradeRebookingRefused, match="canonical evidence"):
        ledger.recover(encoded, expected_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                       account_id=ACCOUNT)


@pytest.mark.parametrize("row", [_nested_canonical(3000), 'not-canonical-json'])
def test_corrupt_or_deep_original_event_is_a_typed_refusal(row):
    sealed = ledger.seal((event(),), account_id=ACCOUNT)
    payload = decode_canonical_json(sealed.envelope_json)
    payload.update(events=[row], event_sha256=[hashlib.sha256(row.encode()).hexdigest()])
    encoded, digest = _reseal_payload(payload)
    with pytest.raises(ledger.TradeRebookingRefused, match="canonical evidence"):
        ledger.recover(encoded, expected_sha256=digest, account_id=ACCOUNT)


def test_recursion_translation_guard_removal_falsifies_the_native_evidence_test(monkeypatch):
    monkeypatch.setattr(ledger, "_decode", ledger.decode_canonical_json)
    with pytest.raises(RecursionError):
        test_excessively_nested_native_evidence_is_a_typed_refusal()


def test_account_guard_removal_falsifies_the_cross_account_test(monkeypatch):
    def assert_refused():
        with pytest.raises(ledger.TradeRebookingRefused, match="cross-account"):
            run(event(account_id=OTHER))
    assert_refused()
    monkeypatch.setattr(ledger, "_require_account", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        assert_refused()


def test_predecessor_identity_guard_removal_falsifies_the_mismatch_test(monkeypatch):
    def assert_refused():
        with pytest.raises(ledger.TradeRebookingRefused, match="order/asset/side changed"):
            run(event(), event(1, kind=ledger.TradeKind.CORRECTION,
                previous=_REFS[0], broker_order_id=OTHER))
    assert_refused()
    monkeypatch.setattr(ledger, "_require_same_trade", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        assert_refused()
