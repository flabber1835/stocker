"""Generated execution-account economics, never provider acceptance or authority."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from pydantic import ValidationError

from sentinel.execution import account_event_accounting as account
from sentinel.execution import trade_rebooking as gross
from sentinel.execution.contract import Side
from sentinel.execution.native_activity import activity_evidence, canonical_json
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.trading_environment import TradingEnvironment


def uid(number):
    return str(UUID(int=number))


def publication(number):
    return f"01K{number:023d}"


ACCOUNT, A, B, C = uid(1), uid(3), uid(4), uid(5)
SUBJECT = ExecutionSubject(deployment_id="private-offline-candidate", account_id=ACCOUNT,
    takeover_epoch=1, environment=TradingEnvironment.PAPER,
    base_url="https://paper-api.alpaca.markets")
EXECUTED = datetime(2026, 10, 23, 13, 31, tzinfo=timezone.utc)


def evidence(native_id, *, subject=SUBJECT, activity_type="LOCAL_ACTION", **fields):
    return activity_evidence({"id": native_id, "account_id": subject.account_id,
        "activity_type": activity_type, **fields}, subject_sha256=subject.sha256)


def cash_leg(number, kind=account.CashKind.DEPOSIT, amount="1000", **changes):
    native_id = uid(1000 + number)
    native_kind = {account.CashKind.DEPOSIT: "CSD", account.CashKind.WITHDRAWAL: "CSW",
        account.CashKind.DIVIDEND: "DIV", account.CashKind.FEE: "FEE",
        account.CashKind.WITHHOLDING: "DIVNRA", account.CashKind.INTEREST: "INT"}.get(kind, "LOCAL_ACTION")
    return account.CashLeg(native_id=native_id, kind=kind, net_amount=Decimal(amount),
        evidence=evidence(native_id, activity_type=native_kind,
                          date="2026-10-23", net_amount=amount), **changes)


def security_leg(number, asset, quantity):
    native_id = uid(2000 + number)
    return account.SecurityLeg(native_id=native_id, asset_id=asset,
        quantity=Decimal(quantity), evidence=evidence(native_id))


def cash(number=0, kind=account.CashKind.DEPOSIT, amount="1000", **changes):
    leg = cash_leg(number, kind, amount)
    fields = dict(subject=SUBJECT, entry_id=leg.native_id,
        publication_id=publication(number), kind=account.EntryKind.CASH,
        cash_kind=kind, cash_legs=(leg,), expected_leg_ids=(leg.native_id,),
        native_evidence_json=leg.evidence.payload_json)
    return account.AccountEntry(**(fields | changes))


def trade(number=1, *, side=Side.BUY, quantity="10", price="50", asset=A,
          kind=gross.TradeKind.FILL, previous=None, subject=SUBJECT, **changes):
    native_id = uid(3000 + number)
    original = canonical_json({"id": native_id, "account_id": subject.account_id,
        "activity_type": "TRD", "raw": "generated, not a provider capture"})
    event = gross.TradeEvent(account_id=subject.account_id, event_id=publication(number),
        activity_id=native_id, broker_order_id=uid(4001), asset_id=asset,
        side=side, kind=kind, previous_activity_id=previous,
        executed_at=EXECUTED, native_evidence_json=original,
        quantity=None if kind is gross.TradeKind.BUST else Decimal(quantity),
        price=None if kind is gross.TradeKind.BUST else Decimal(price))
    return account.AccountEntry(subject=subject, entry_id=native_id,
        publication_id=event.event_id, kind=account.EntryKind.TRADE,
        native_evidence_json=original, trade=event, **changes)


def action(number=2, kind=account.ActionKind.STOCK_DIVIDEND,
           securities=None, cash_legs=(), source=A, **changes):
    if securities is None:
        securities = (security_leg(number, A, "2"),)
    native_id = uid(5000 + number)
    fields = dict(subject=SUBJECT, entry_id=native_id, publication_id=publication(number),
        kind=account.EntryKind.CORPORATE_ACTION, action_kind=kind,
        action_id=uid(6000 + number), source_asset_id=source,
        security_legs=securities, cash_legs=cash_legs,
        expected_leg_ids=tuple(leg.native_id for leg in (*cash_legs, *securities)),
        native_evidence_json=canonical_json({"group": native_id,
            "account_id": ACCOUNT, "raw": "generated complete local interpretation"}))
    return account.AccountEntry(**(fields | changes))


def run(*entries):
    return account.replay(entries, subject=SUBJECT)


def positions(projection):
    return {item.asset_id: item.quantity for item in projection.positions}


def test_explained_gross_and_nontrade_cash_are_not_double_booked():
    fee = cash(4, account.CashKind.FEE, "-0.50")
    linked = fee.cash_legs[0].model_copy(update={"related_trade_activity_id": trade().entry_id})
    fee = fee.model_copy(update={"cash_legs": (linked,)})
    result = run(cash(), trade(), cash(2, account.CashKind.DIVIDEND, "10"),
                 cash(3, account.CashKind.WITHHOLDING, "-1"), fee)
    assert positions(result) == {A: Decimal("10")}
    assert result.gross_trade_cash_delta == Decimal("-500")
    assert result.nontrade_cash_delta == Decimal("1008.50")
    assert result.explained_cash_delta == Decimal("508.50")
    assert result.spendable_cash == 0 and result.order_authority == "NONE"
    assert not any((result.provider_finality_proven, result.settlement_proven,
                    result.live_authority_granted, result.strategy_inputs_supplied))


@pytest.mark.parametrize("kind,amount", [
    (account.CashKind.DEPOSIT, "2"), (account.CashKind.WITHDRAWAL, "-2"),
    (account.CashKind.DIVIDEND, "2"), (account.CashKind.FEE, "-2"),
    (account.CashKind.WITHHOLDING, "-2"), (account.CashKind.INTEREST, "-2"),
    (account.CashKind.INTEREST, "2"),
])
def test_separate_cash_movements(kind, amount):
    assert run(cash(), cash(1, kind, amount)).explained_cash_delta == Decimal("1000") + Decimal(amount)


def test_stock_dividend_preserves_actual_shares_and_restricts_disposition():
    distribution = action()
    result = run(cash(), trade(), distribution)
    assert positions(result) == {A: Decimal("12")}
    assert result.explained_cash_delta == Decimal("500")
    assert result.positions[0].disposition == "RESTRICTED_PENDING_POLICY"
    assert result.positions[0].action_origins == (distribution.action_id,)


def test_stock_dividend_can_group_actual_cash_in_lieu_with_received_shares():
    distribution = action(securities=(security_leg(2, A, "2.25"),),
        cash_legs=(cash_leg(2, account.CashKind.CASH_IN_LIEU, "7.50"),))
    result = run(cash(), trade(), distribution)
    assert positions(result) == {A: Decimal("12.25")}
    assert result.explained_cash_delta == Decimal("507.50")
    assert result.positions[0].disposition == "RESTRICTED_PENDING_POLICY"
    assert not result.corporate_action_entitlements_proven


def test_spinoff_delivers_another_company_without_purchase_or_parent_disposal():
    distribution = action(kind=account.ActionKind.SPINOFF,
                          securities=(security_leg(2, B, "1.5"),))
    result = run(cash(), trade(), distribution)
    assert positions(result) == {A: Decimal("10"), B: Decimal("1.5")}
    assert result.explained_cash_delta == Decimal("500")
    assert result.gross_trade_cash_delta == Decimal("-500")
    assert result.positions[0].disposition == "TRADE_HISTORY_ONLY"
    assert result.positions[1].disposition == "RESTRICTED_PENDING_POLICY"
    assert result.positions[1].action_origins == (distribution.action_id,)


@pytest.mark.parametrize("before,after,delta", [("10", "20", "10"), ("10", "5", "-5")])
def test_split_and_reverse_split_bind_original_inventory(before, after, delta):
    split = action(kind=account.ActionKind.SPLIT, securities=(security_leg(2, A, delta),),
                   split_before=Decimal(before), split_after=Decimal(after))
    result = run(cash(), trade(), split)
    assert positions(result) == {A: Decimal(after)}
    assert result.explained_cash_delta == Decimal("500")
    assert result.positions[0].disposition == "RESTRICTED_PENDING_POLICY"


@pytest.mark.parametrize("mixed", [False, True])
def test_stock_and_mixed_cash_mergers_apply_complete_surrender_and_receipt(mixed):
    securities = (security_leg(2, A, "-10"), security_leg(3, B, "4.25"))
    cash_legs = (cash_leg(2, account.CashKind.MERGER_CASH, "25"),) if mixed else ()
    merger = action(kind=account.ActionKind.MIXED_MERGER if mixed else account.ActionKind.STOCK_MERGER,
                    securities=securities, cash_legs=cash_legs)
    result = run(cash(), trade(), merger)
    assert positions(result) == {B: Decimal("4.25")}
    assert result.explained_cash_delta == Decimal("525" if mixed else "500")
    assert result.positions[0].action_origins == (merger.action_id,)


def test_fractional_delivery_and_actual_cash_in_lieu_remain_separate_events():
    spinoff = action(kind=account.ActionKind.SPINOFF,
                     securities=(security_leg(2, B, "1.5"),))
    payout = action(3, kind=account.ActionKind.CASH_IN_LIEU, source=B,
        securities=(security_leg(3, B, "-0.5"),),
        cash_legs=(cash_leg(3, account.CashKind.CASH_IN_LIEU, "12.34"),))
    result = run(cash(), trade(), spinoff, payout)
    assert positions(result) == {A: Decimal("10"), B: Decimal("1")}
    assert result.explained_cash_delta == Decimal("512.34")
    assert set(result.positions[1].action_origins) == {spinoff.action_id, payout.action_id}


def test_cash_in_lieu_without_fractional_share_credit_does_not_invent_shares():
    payout = action(kind=account.ActionKind.CASH_IN_LIEU, source=B, securities=(),
        cash_legs=(cash_leg(2, account.CashKind.CASH_IN_LIEU, "7.11"),))
    result = run(cash(), trade(), payout)
    assert positions(result) == {A: Decimal("10")}
    assert result.explained_cash_delta == Decimal("507.11")


def test_action_correction_and_bust_reverse_exact_active_group():
    original = action(kind=account.ActionKind.SPINOFF, securities=(security_leg(2, B, "1.5"),))
    corrected = action(3, kind=account.ActionKind.SPINOFF, securities=(security_leg(3, B, "2.5"),),
        operation=account.Operation.CORRECTION, previous_entry_id=original.entry_id,
        action_id=original.action_id)
    assert positions(run(cash(), trade(), original, corrected)) == {A: Decimal("10"), B: Decimal("2.5")}
    bust = action(4, kind=account.ActionKind.SPINOFF, securities=(),
        operation=account.Operation.BUST, previous_entry_id=corrected.entry_id,
        action_id=original.action_id)
    result = run(cash(), trade(), original, corrected, bust)
    assert positions(result) == {A: Decimal("10")}
    assert result.explained_cash_delta == Decimal("500")
    assert result.active_entry_ids == tuple(sorted((cash().entry_id, trade().entry_id)))


def test_one_corporate_action_cannot_be_posted_twice_under_new_native_leg_ids():
    original = action()
    duplicate_action = action(3, action_id=original.action_id)
    with pytest.raises(account.AccountEventRefused, match="already owns an entry chain"):
        run(cash(), trade(), original, duplicate_action)
    bust = action(3, securities=(), operation=account.Operation.BUST,
                  previous_entry_id=original.entry_id, action_id=original.action_id)
    with pytest.raises(account.AccountEventRefused, match="already owns an entry chain"):
        run(cash(), trade(), original, bust, action(4, action_id=original.action_id))


def test_trade_revision_cannot_subtract_presplit_units_from_postsplit_position():
    original = trade()
    split = action(kind=account.ActionKind.SPLIT, securities=(security_leg(2, A, "10"),),
                   split_before=Decimal("10"), split_after=Decimal("20"))
    correction = trade(3, kind=gross.TradeKind.CORRECTION,
                       previous=original.entry_id, quantity="8")
    with pytest.raises(account.AccountEventRefused, match="dependent corporate action"):
        run(cash(), original, split, correction)


def test_stock_receipt_bust_cannot_reverse_presplit_quantity_after_later_split():
    receipt = action(kind=account.ActionKind.SPINOFF, securities=(security_leg(2, B, "2"),))
    split = action(3, kind=account.ActionKind.SPLIT, source=B,
        securities=(security_leg(3, B, "2"),), split_before=Decimal("2"), split_after=Decimal("4"))
    bust = action(4, kind=account.ActionKind.SPINOFF, securities=(),
        operation=account.Operation.BUST, previous_entry_id=receipt.entry_id,
        action_id=receipt.action_id)
    with pytest.raises(account.AccountEventRefused, match="dependent corporate action"):
        run(cash(), trade(), receipt, split, bust)


def test_unrelated_action_does_not_block_trade_revision_or_prove_entitlement():
    original = trade()
    # The parent need not still be held when a delayed record-date entitlement
    # posts. This records the supplied receipt without proving that entitlement.
    receipt = action(kind=account.ActionKind.SPINOFF, source=C,
                     securities=(security_leg(2, B, "1"),))
    correction = trade(3, kind=gross.TradeKind.CORRECTION, previous=original.entry_id, quantity="8")
    result = run(cash(), original, receipt, correction)
    assert positions(result) == {A: Decimal("8"), B: Decimal("1")}
    assert not result.corporate_action_entitlements_proven


def test_cash_correction_and_bust_do_not_synthesize_refund_for_another_fee():
    original = cash(2, account.CashKind.FEE, "-1")
    corrected = cash(3, account.CashKind.FEE, "-0.50", operation=account.Operation.CORRECTION,
                     previous_entry_id=original.entry_id)
    result = run(cash(), trade(), original, corrected, cash(4, account.CashKind.FEE, "-2"))
    assert result.explained_cash_delta == Decimal("497.50")
    bust = corrected.model_copy(update={"entry_id": uid(9000), "publication_id": publication(5),
        "operation": account.Operation.BUST, "previous_entry_id": corrected.entry_id,
        "cash_legs": (), "expected_leg_ids": ()})
    assert run(cash(), trade(), original, corrected, cash(4, account.CashKind.FEE, "-2"), bust).explained_cash_delta == 498


def test_replacement_is_atomic_even_if_standalone_reversal_would_be_negative():
    original = action()
    sale = trade(3, side=Side.SELL, quantity="11", price="60")
    corrected = action(4, securities=(security_leg(4, A, "1"),),
        operation=account.Operation.CORRECTION, previous_entry_id=original.entry_id,
        action_id=original.action_id)
    result = run(cash(), trade(), original, sale, corrected)
    assert result.positions == ()
    assert result.explained_cash_delta == Decimal("1160")


def test_trade_corrections_and_busts_reuse_gross_ledger_with_separate_fee():
    original = trade()
    correction = trade(3, kind=gross.TradeKind.CORRECTION, previous=original.entry_id,
                       quantity="8")
    fee = cash(2, account.CashKind.FEE, "-0.50")
    fee = fee.model_copy(update={"cash_legs": (fee.cash_legs[0].model_copy(
        update={"related_trade_activity_id": original.entry_id}),)})
    result = run(cash(), original, fee, correction)
    assert positions(result) == {A: Decimal("8")}
    assert result.explained_cash_delta == Decimal("599.50")
    bust = trade(4, kind=gross.TradeKind.BUST, previous=correction.entry_id)
    result = run(cash(), original, fee, correction, bust)
    assert result.positions == () and result.explained_cash_delta == Decimal("999.50")
    assert result.gross_trade_cash_delta == 0
    assert result.active_entry_ids == tuple(sorted((cash().entry_id, fee.entry_id)))


def test_duplicate_late_delivery_is_idempotent_after_revision_and_recovery():
    original = action()
    corrected = action(3, securities=(security_leg(3, A, "3.125"),),
        operation=account.Operation.CORRECTION, previous_entry_id=original.entry_id,
        action_id=original.action_id)
    once = (cash(), trade(), original, corrected)
    repeated = (*once, original, cash(), corrected)
    result = run(*repeated)
    assert result.replayed_entries == 3
    assert result.ledger_sha256 == run(*once).ledger_sha256
    envelope = account.seal(repeated, subject=SUBJECT)
    assert account.recover(envelope.envelope_json, expected_sha256=envelope.sha256, subject=SUBJECT) == result
    assert json.loads(envelope.envelope_json).keys() == {"schema", "subject", "entries", "entry_sha256"}


def test_exact_arithmetic_does_not_depend_on_decimal_context():
    with localcontext() as context:
        context.prec = 4
        result = run(cash(amount="123456789.000000001"),
            trade(quantity="1.000000001", price="123.123456789"),
            cash(2, account.CashKind.FEE, "-0.0000000001"),
            action(securities=(security_leg(2, A, "0.000000000123"),),
                   publication_id=publication(3)))
    assert result.explained_cash_delta == Decimal("123456665.876543088776543211")
    assert positions(result) == {A: Decimal("1.000000001123")}


def test_native_ordinary_cash_reuses_production_normalizer_without_enabling_it():
    payload = {"id": "20261023::native-dividend", "account_id": ACCOUNT,
        "activity_type": "DIV", "date": "2026-10-23", "net_amount": "12.34"}
    entry = account.cash_entry_from_native(payload, subject=SUBJECT, publication_id=publication(0))
    result = run(entry)
    assert result.explained_cash_delta == Decimal("12.34")
    assert entry.cash_legs[0].evidence == activity_evidence(payload, subject_sha256=SUBJECT.sha256)
    assert result.order_authority == "NONE" and not result.settlement_proven


def test_interpreted_ordinary_cash_cannot_disagree_with_retained_native_amount():
    payload = {"id": "20261023::native-dividend", "account_id": ACCOUNT,
        "activity_type": "DIV", "date": "2026-10-23", "net_amount": "12.34"}
    entry = account.cash_entry_from_native(payload, subject=SUBJECT, publication_id=publication(0))
    forged = entry.model_copy(update={"cash_legs": (entry.cash_legs[0].model_copy(
        update={"net_amount": Decimal("1234")}),)})
    with pytest.raises(account.AccountEventRefused, match="contradicts native evidence"):
        run(forged)


def test_interpreted_ordinary_cash_cannot_reclassify_retained_native_fee():
    original = cash(1, account.CashKind.FEE, "-1")
    forged = original.model_copy(update={"cash_kind": account.CashKind.WITHHOLDING,
        "cash_legs": (original.cash_legs[0].model_copy(
            update={"kind": account.CashKind.WITHHOLDING}),)})
    with pytest.raises(account.AccountEventRefused, match="contradicts native evidence"):
        run(cash(), forged)


@pytest.mark.parametrize("change", [
    {"activity_type": "SPLIT"}, {"previous_id": uid(8)},
    {"account_id": uid(9)}, {"activity_type": "FILL"},
    {"activity_type": "JNLC"}, {"currency": "EUR"},
    {"net_amount": "-10"},
])
def test_native_projection_does_not_bypass_existing_quarantine_or_guess_semantics(change):
    payload = {"id": "20261023::native-dividend", "account_id": ACCOUNT,
        "activity_type": "DIV", "date": "2026-10-23", "net_amount": "12.34"} | change
    with pytest.raises((ValueError, ValidationError)):
        account.cash_entry_from_native(payload, subject=SUBJECT, publication_id=publication(0))


def test_missing_group_leg_does_not_publish_partial_economics():
    entry = action(securities=(security_leg(2, A, "1"), security_leg(3, A, "2")))
    incomplete = entry.model_copy(update={"security_legs": entry.security_legs[:1]})
    with pytest.raises((ValueError, ValidationError)):
        run(cash(), trade(), incomplete)
    assert positions(run(cash(), trade())) == {A: Decimal("10")}


@pytest.mark.parametrize("change", [
    {"quantity": Decimal("3")}, {"asset_id": C},
    {"native_id": uid(999)},
])
def test_changed_entry_identity_and_changed_native_leg_refuse(change):
    original = action()
    changed = original.model_copy(update={"security_legs": (
        original.security_legs[0].model_copy(update=change),)})
    with pytest.raises((ValueError, ValidationError)):
        run(cash(), trade(), original, changed)


@pytest.mark.parametrize("field,value", [("takeover_epoch", 2),
    ("deployment_id", "another-deployment"), ("account_id", uid(99)),
    ("base_url", "https://api.alpaca.markets")])
def test_cross_subject_or_invalid_environment_refuses(field, value):
    changed_subject = SUBJECT.model_copy(update={field: value})
    forged = cash().model_copy(update={"subject": changed_subject})
    with pytest.raises((ValueError, ValidationError)):
        run(forged)


def test_publication_reuse_regression_and_changed_payload_refuse():
    for entries in ((cash(1), cash()),
                    (cash(), cash(1, publication_id=publication(0))),
                    (cash(), cash(amount="1001"))):
        with pytest.raises((ValueError, ValidationError)):
            run(*entries)


def test_duplicate_native_leg_cannot_be_booked_by_another_group():
    original = action()
    another = action(3, securities=original.security_legs)
    with pytest.raises(account.AccountEventRefused, match="another entry"):
        run(cash(), trade(), original, another)


def test_fill_principal_cannot_be_booked_as_generic_cash():
    entry = cash(2)
    leg = entry.cash_legs[0]
    principal = evidence(leg.native_id, activity_type="FILL", qty="10", price="50")
    forged = entry.model_copy(update={"cash_legs": (leg.model_copy(update={"evidence": principal}),)})
    with pytest.raises(account.AccountEventRefused, match="second account leg"):
        run(cash(), trade(), forged)


def test_missing_or_inactive_predecessor_and_action_identity_changes_refuse():
    original = action()
    correction = action(3, operation=account.Operation.CORRECTION,
        previous_entry_id=original.entry_id, action_id=original.action_id)
    with pytest.raises(account.AccountEventRefused, match="missing or inactive"):
        run(cash(), trade(), correction)
    with pytest.raises(account.AccountEventRefused, match="missing or inactive"):
        run(cash(), trade(), original, correction,
            action(4, operation=account.Operation.CORRECTION,
                   previous_entry_id=original.entry_id, action_id=original.action_id))
    for field, value in (("action_id", uid(99)), ("source_asset_id", B)):
        with pytest.raises((ValueError, ValidationError)):
            run(cash(), trade(), original, correction.model_copy(update={field: value}))


def test_corrected_merger_cannot_change_received_security_identity():
    original = action(kind=account.ActionKind.STOCK_MERGER,
        securities=(security_leg(2, A, "-10"), security_leg(3, B, "4")))
    changed = action(3, kind=account.ActionKind.STOCK_MERGER,
        securities=(security_leg(4, A, "-10"), security_leg(5, C, "4")),
        operation=account.Operation.CORRECTION, previous_entry_id=original.entry_id,
        action_id=original.action_id)
    with pytest.raises(account.AccountEventRefused, match="securities identity"):
        run(cash(), trade(), original, changed)


def test_unexplained_cash_inventory_and_split_basis_are_never_invented():
    with pytest.raises(account.AccountEventRefused, match="negative explained"):
        run(cash(kind=account.CashKind.WITHDRAWAL, amount="-10"))
    merger = action(kind=account.ActionKind.STOCK_MERGER,
        securities=(security_leg(2, A, "-10"), security_leg(3, B, "4")))
    with pytest.raises(account.AccountEventRefused, match="negative explained"):
        run(cash(), merger)
    split = action(kind=account.ActionKind.SPLIT, securities=(security_leg(2, A, "10"),),
        split_before=Decimal("11"), split_after=Decimal("21"))
    with pytest.raises(account.AccountEventRefused, match="opening inventory"):
        run(cash(), trade(), split)


def test_linked_fee_requires_known_exact_native_trade():
    fee = cash(2, account.CashKind.FEE, "-1")
    fee = fee.model_copy(update={"cash_legs": (fee.cash_legs[0].model_copy(
        update={"related_trade_activity_id": uid(99)}),)})
    with pytest.raises(account.AccountEventRefused, match="linked trade activity missing"):
        run(cash(), trade(), fee)


@pytest.mark.parametrize("change", [
    {"quantity": Decimal("NaN")}, {"quantity": 1.5},
    {"quantity": Decimal("1e65")}, {"quantity": Decimal("0")},
    {"asset_id": "SYMBOL"}, {"native_id": ""},
])
def test_security_numeric_and_identity_bounds(change):
    with pytest.raises((ValueError, ValidationError)):
        account.SecurityLeg.model_validate(security_leg(2, B, "1").model_dump() | change)


@pytest.mark.parametrize("kind,amount", [
    (account.CashKind.DEPOSIT, "-1"), (account.CashKind.WITHDRAWAL, "1"),
    (account.CashKind.FEE, "1"), (account.CashKind.WITHHOLDING, "1"),
    (account.CashKind.DIVIDEND, "-1"), (account.CashKind.DEPOSIT, "0"),
])
def test_cash_signs_are_not_guessed(kind, amount):
    with pytest.raises((ValueError, ValidationError)):
        cash(kind=kind, amount=amount)


@pytest.mark.parametrize("kind,securities,cash_legs", [
    (account.ActionKind.STOCK_DIVIDEND, (security_leg(2, B, "1"),), ()),
    (account.ActionKind.SPINOFF, (security_leg(2, A, "1"),), ()),
    (account.ActionKind.STOCK_MERGER, (security_leg(2, B, "1"),), ()),
    (account.ActionKind.MIXED_MERGER, (security_leg(2, A, "-10"), security_leg(3, B, "4")), ()),
    (account.ActionKind.CASH_IN_LIEU, (security_leg(2, A, "1"),),
        (cash_leg(2, account.CashKind.CASH_IN_LIEU, "2"),)),
])
def test_corporate_action_shapes_refuse_missing_or_contradictory_legs(kind, securities, cash_legs):
    with pytest.raises((ValueError, ValidationError)):
        action(kind=kind, securities=securities, cash_legs=cash_legs)


def test_frozen_copies_of_nested_fields_are_revalidated():
    entry = action()
    invalid = entry.model_copy(update={"security_legs": (
        entry.security_legs[0].model_copy(update={"quantity": Decimal("-999")}),)})
    with pytest.raises((ValueError, ValidationError)):
        run(cash(), trade(), invalid)
    with pytest.raises(ValidationError):
        entry.action_id = uid(9)


def test_evidence_mutation_is_detected_even_if_interpretation_did_not_change():
    entry = action()
    leg = entry.security_legs[0]
    forged_evidence = leg.evidence.model_copy(update={"payload_json": canonical_json({"changed": True})})
    forged = entry.model_copy(update={"security_legs": (leg.model_copy(update={"evidence": forged_evidence}),)})
    with pytest.raises((ValueError, ValidationError)):
        run(cash(), trade(), forged)


def test_envelope_and_per_entry_original_hashes_are_both_required():
    envelope = account.seal((cash(), trade(), action()), subject=SUBJECT)
    with pytest.raises(account.AccountEventRefused, match="byte identity"):
        account.recover(envelope.envelope_json + " ", expected_sha256=envelope.sha256, subject=SUBJECT)
    payload = json.loads(envelope.envelope_json)
    payload["entries"][0] += " "
    changed = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with pytest.raises(account.AccountEventRefused):
        account.recover(changed, expected_sha256=hashlib.sha256(changed.encode()).hexdigest(), subject=SUBJECT)
    with pytest.raises(account.AccountEventRefused):
        account.recover(envelope.envelope_json, expected_sha256=envelope.sha256,
            subject=SUBJECT.model_copy(update={"takeover_epoch": 2}))


def test_resource_bounds_cover_duplicates_groups_and_recovery(monkeypatch):
    envelope = account.seal((cash(),), subject=SUBJECT)
    monkeypatch.setattr(account, "MAX_ENTRIES", 1)
    with pytest.raises(account.AccountEventRefused, match="bounded entry"):
        run(cash(), cash())
    monkeypatch.setattr(account, "MAX_BYTES", 8)
    with pytest.raises(account.AccountEventRefused, match="byte limit"):
        run(cash())
    with pytest.raises(account.AccountEventRefused):
        account.recover(envelope.envelope_json, expected_sha256=envelope.sha256, subject=SUBJECT)


def test_complete_group_guard_removal_falsifies_missing_leg_test(monkeypatch):
    monkeypatch.setattr(account, "_complete_legs", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_missing_group_leg_does_not_publish_partial_economics()


def test_native_unique_guard_removal_falsifies_double_booking_test(monkeypatch):
    monkeypatch.setattr(account, "_require_unbooked", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_duplicate_native_leg_cannot_be_booked_by_another_group()


def test_nonnegative_guard_removal_falsifies_unexplained_balance_test(monkeypatch):
    monkeypatch.setattr(account, "_nonnegative", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_unexplained_cash_inventory_and_split_basis_are_never_invented()


def test_lineage_guard_removal_falsifies_action_identity_test(monkeypatch):
    original = action()
    changed = action(3, kind=account.ActionKind.SPINOFF,
        securities=(security_leg(3, B, "2"),), operation=account.Operation.CORRECTION,
        previous_entry_id=original.entry_id, action_id=original.action_id)
    def assertion():
        with pytest.raises(account.AccountEventRefused, match="identity changed"):
            run(cash(), trade(), original, changed)
    assertion()
    monkeypatch.setattr(account, "_same_lineage", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        assertion()


def test_subject_guard_removal_falsifies_cross_environment_ownership_test(monkeypatch):
    another = SUBJECT.model_copy(update={"deployment_id": "another-deployment"})
    entry = trade(subject=another)
    def assertion():
        with pytest.raises(account.AccountEventRefused, match="cross-subject"):
            run(cash(), entry)
    assertion()
    monkeypatch.setattr(account, "_require_subject", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        assertion()


def test_no_second_principal_guard_removal_falsifies_fill_cash_test(monkeypatch):
    monkeypatch.setattr(account, "_evidence", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_fill_principal_cannot_be_booked_as_generic_cash()


def test_action_chain_guard_removal_falsifies_duplicate_distribution_test(monkeypatch):
    monkeypatch.setattr(account, "_require_action_chain", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_one_corporate_action_cannot_be_posted_twice_under_new_native_leg_ids()


@pytest.mark.parametrize("assertion", [
    test_trade_revision_cannot_subtract_presplit_units_from_postsplit_position,
    test_stock_receipt_bust_cannot_reverse_presplit_quantity_after_later_split,
])
def test_action_dependency_guard_removal_falsifies_revision_tests(monkeypatch, assertion):
    monkeypatch.setattr(account, "_require_no_dependent_actions", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        assertion()


@pytest.mark.parametrize("assertion", [
    test_interpreted_ordinary_cash_cannot_disagree_with_retained_native_amount,
    test_interpreted_ordinary_cash_cannot_reclassify_retained_native_fee,
])
def test_native_cash_binding_guard_removal_falsifies_interpretation_tests(monkeypatch, assertion):
    monkeypatch.setattr(account, "_require_ordinary_cash", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        assertion()
