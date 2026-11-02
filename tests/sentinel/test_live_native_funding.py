"""Unattended accepted-source consumer using generated contracts and native shapes."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import inspect

import pytest

from sentinel.execution import live_native_funding as native
from sentinel.execution.live_context import FUNDING_CERTIFICATE_PATH_ENV, load_live_funding_admission
from sentinel.authority.live_runtime import TRUST_ROOTS_PATH_ENV
from sentinel.execution.live_order_policy import LiveOrderDeferred, LiveOrderRefused
from tests.sentinel.live_native_funding_fixtures import native_fixture, resigned_native
from tests.sentinel.live_order_fixtures import NOW, order_fixture
from tests.sentinel.test_live_context import write_enrollment
from tests.sentinel.test_live_order_policy import assess


def test_accepted_source_contract_collects_current_typed_funds_without_perorder_signing():
    fixture, source = native_fixture()
    first = assess(fixture, receipt=source.admission)
    assert first.remaining_settled_cash == 699
    assert first.valid_until == NOW + timedelta(seconds=30)
    # The same independent source contract consumes a later actual-shaped
    # observation; no observation certificate or private key is requested.
    facts = replace(fixture.account.native_funding, observed_at=NOW+timedelta(seconds=31))
    later = replace(fixture.account, native_funding=facts)
    second = assess(fixture, receipt=source.admission, now=NOW+timedelta(seconds=31),
                    account=later, account_observed_at=NOW+timedelta(seconds=31))
    assert second.remaining_settled_cash == first.remaining_settled_cash
    assert second.funding_receipt_sha256 != first.funding_receipt_sha256


def test_native_field_presence_and_semantic_labels_do_not_qualify_themselves():
    fixture, source = native_fixture()
    with pytest.raises(LiveOrderDeferred, match="NOT_QUALIFIED"):
        assess(fixture, receipt=None)
    with pytest.raises(LiveOrderRefused, match="SOURCE_CONTRACT"):
        assess(fixture, receipt=replace(source.admission, trust_roots={}))
    # An execution issuer is not settlement enrollment even for valid bytes.
    roots = {source.key_id: replace(source.root, scope="LIVE_EXECUTION")}
    with pytest.raises(LiveOrderRefused, match="SOURCE_CONTRACT"):
        assess(fixture, receipt=replace(source.admission, trust_roots=roots))


@pytest.mark.parametrize("field", ["settled_cash_field", "spendable_cash_field"])
def test_only_explicit_allowlisted_native_fields_are_accepted(field):
    fixture, source = native_fixture()
    for value in ("equity", "settled_cash", "custom.balance", "../cash"):
        with pytest.raises(LiveOrderRefused, match="SOURCE_CONTRACT"):
            assess(fixture, receipt=resigned_native(source, **{field: value}))


def test_accepted_mapping_is_consumed_exactly_without_relabelling_another_field():
    fixture, source = native_fixture(non_marginable_buying_power="50")
    with pytest.raises(LiveOrderDeferred, match="SETTLED_UNRESERVED"):
        assess(fixture, receipt=source.admission)
    # Cash and buying power remain 1000; those ordinary fields cannot replace
    # the separately accepted field whose current value is only 50.
    assert fixture.account.cash == fixture.account.buying_power == 1000


@pytest.mark.parametrize("changes,code", [
    ({"endpoint_path": "/v2/account/activities"}, "SOURCE_CONTRACT"),
    ({"source_profile": "GENERIC_CALLER_NATIVE"}, "SOURCE_CONTRACT"),
    ({"currency": "EUR"}, "SOURCE_CONTRACT"),
    ({"reservation_contract": "ASSUME_NONE"}, "SOURCE_CONTRACT"),
    ({"max_observation_age_seconds": 31}, "SOURCE_CONTRACT"),
    ({"expires_at": (NOW+timedelta(days=31)).isoformat()}, "SOURCE_CONTRACT"),
    ({"expires_at": NOW.isoformat()}, "NOT_CURRENT"),
    ({"not_before": (NOW+timedelta(seconds=1)).isoformat()}, "NOT_CURRENT"),
])
def test_even_signed_native_source_contracts_have_fixed_semantics_and_validity(changes, code):
    fixture, source = native_fixture()
    with pytest.raises(LiveOrderRefused, match=code):
        assess(fixture, receipt=resigned_native(source, **changes))


def test_native_source_subject_and_independent_qualification_must_match():
    fixture, source = native_fixture()
    other = {**source.claims["subject"], "account_id": "22222222-2222-2222-2222-222222222222"}
    with pytest.raises(LiveOrderRefused, match="SUBJECT_MISMATCH"):
        assess(fixture, receipt=resigned_native(source, subject=other))
    refs = {**source.claims["qualification_receipts"], "native_settlement": "0"*64}
    with pytest.raises(LiveOrderRefused, match="QUALIFICATION_MISMATCH"):
        assess(fixture, receipt=resigned_native(source, qualification_receipts=refs))


@pytest.mark.parametrize("change", ["absent", "old", "future", "wrong_account", "wrong_digest"])
def test_native_funding_facts_must_be_current_typed_and_bound_to_account(change):
    fixture, source = native_fixture()
    facts = fixture.account.native_funding
    if change == "absent":
        facts = None
    elif change == "old":
        facts = replace(facts, observed_at=NOW-timedelta(seconds=31))
    elif change == "future":
        facts = replace(facts, observed_at=NOW+timedelta(microseconds=1))
    elif change == "wrong_account":
        facts = replace(facts, account_id="another-account")
    else:
        facts = replace(facts, account_snapshot_sha256="0"*64)
    with pytest.raises(LiveOrderRefused):
        assess(fixture, receipt=source.admission, account=replace(fixture.account, native_funding=facts))


def test_bypassed_frozen_fact_construction_and_missing_accepted_field_refuse():
    fixture, source = native_fixture()
    facts = fixture.account.native_funding
    object.__setattr__(facts, "amounts", (("invented", Decimal(1000)),))
    with pytest.raises(LiveOrderRefused, match="FACTS_REFUSED"):
        assess(fixture, receipt=source.admission)
    fixture, source = native_fixture()
    facts = replace(fixture.account.native_funding,
        amounts=tuple(pair for pair in fixture.account.native_funding.amounts if pair[0] != "non_marginable_buying_power"))
    with pytest.raises(LiveOrderDeferred, match="FIELD_UNAVAILABLE"):
        assess(fixture, receipt=source.admission, account=replace(fixture.account, native_funding=facts))


def test_account_value_contradictions_and_shorts_cannot_lower_capital_charge():
    for changes in ({"long_market_value": "1"}, {"short_market_value": "-1"}, {"short_market_value": "1"}):
        fixture, source = native_fixture(**changes)
        with pytest.raises(LiveOrderRefused):
            assess(fixture, receipt=source.admission)


def test_parser_has_no_missing_field_settlement_fallback_or_binary_float_conversion():
    fixture = order_fixture()
    payload = {"id": fixture.subject.account_id, "currency": "USD", "cash": "1000", "buying_power": "1000"}
    assert native.parse_alpaca_funding_facts(payload, account=fixture.account,
        base_url=fixture.subject.base_url, observed_at=NOW) is None
    payload.update(long_market_value="0", short_market_value="0")
    for value in (1.1, True, "NaN", "1E+1000000000"):
        with pytest.raises(native.LiveFundingRefused, match="AMOUNT_REFUSED"):
            native.parse_alpaca_funding_facts({**payload, "cash": value}, account=fixture.account,
                base_url=fixture.subject.base_url, observed_at=NOW)
    with pytest.raises(native.LiveFundingRefused, match="CANNOT_AUTHORIZE_PAPER"):
        native.parse_alpaca_funding_facts(payload, account=fixture.account,
            base_url="https://paper-api.alpaca.markets", observed_at=NOW)


def test_same_public_funding_path_loads_long_native_contract_and_fresh_revocation(tmp_path):
    fixture, source = native_fixture()
    path = tmp_path / "native-contract.json"
    roots = tmp_path / "public-enrollment.json"
    path.write_bytes(source.admission.certificate)
    write_enrollment(roots, source)
    admission = load_live_funding_admission(env={FUNDING_CERTIFICATE_PATH_ENV: str(path), TRUST_ROOTS_PATH_ENV: str(roots)})
    assert type(admission) is native.NativeFundingContractAdmission
    assert assess(fixture, receipt=admission).allowed
    import hashlib
    write_enrollment(roots, source, revoked=(hashlib.sha256(source.admission.certificate).hexdigest(),))
    with pytest.raises(LiveOrderRefused, match="SOURCE_CONTRACT"):
        assess(fixture, receipt=admission)


def test_accepted_settlement_field_guard_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(native.require_native_live_funding)
    needle = "min(values[contract.settled_cash_field], values[contract.spendable_cash_field])"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'values["cash"]'), "native-field-falsifier", "exec"),
         native.__dict__, namespace)
    monkeypatch.setattr(native, "require_native_live_funding", namespace["require_native_live_funding"])
    with pytest.raises(pytest.fail.Exception):
        test_accepted_mapping_is_consumed_exactly_without_relabelling_another_field()


@pytest.mark.parametrize("needle,case", [
    ("if contract.qualification_receipts != expected:", "qualification"),
    ("if not facts.observed_at <= now < facts.observed_at + age:", "freshness"),
])
def test_removed_native_acceptance_guards_are_detected(monkeypatch, needle, case):
    source = inspect.getsource(native.require_native_live_funding)
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "native-acceptance-falsifier", "exec"),
         native.__dict__, namespace)
    monkeypatch.setattr(native, "require_native_live_funding", namespace["require_native_live_funding"])
    with pytest.raises(pytest.fail.Exception):
        if case == "qualification":
            test_native_source_subject_and_independent_qualification_must_match()
        else:
            test_native_funding_facts_must_be_current_typed_and_bound_to_account("old")


def test_native_source_lifetime_guard_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(native.NativeFundingContract)
    needle = "or self.expires_at - self.issued_at > timedelta(days=31)"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "or False"), "native-contract-lifetime-falsifier", "exec"),
         native.__dict__, namespace)
    monkeypatch.setattr(native, "NativeFundingContract", namespace["NativeFundingContract"])
    with pytest.raises(pytest.fail.Exception):
        test_even_signed_native_source_contracts_have_fixed_semantics_and_validity(
            {"expires_at": (NOW+timedelta(days=31)).isoformat()}, "SOURCE_CONTRACT")
