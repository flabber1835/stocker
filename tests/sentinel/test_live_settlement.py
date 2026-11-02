"""Synthetic signed funding acceptance; never native provider qualification."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import hashlib
import inspect
import json

import pytest

from sentinel.authority.canonical import canonical_json_bytes
from sentinel.execution import live_settlement as settlement
from sentinel.execution.contract import BrokerPosition
from tests.sentinel.live_authority_fixtures import signed_live
from tests.sentinel.live_order_fixtures import DAY, NOW, funding, order_fixture
from tests.sentinel.test_live_order_policy import assess


def signed_changed(generated, **changes):
    claims = {**generated.claims, **changes}
    return replace(generated.admission, certificate=signed_live(claims,
        generated.private_key, generated.key_id, schema=settlement.FUNDING_SCHEMA))


@pytest.mark.parametrize("change", ["missing", "disabled", "wrong_scope", "wrong_key", "revoked"])
def test_only_separately_enrolled_current_settlement_issuer_can_attest(change):
    fixture = order_fixture()
    generated = funding(fixture)
    roots = dict(generated.admission.trust_roots)
    revoked = ()
    if change == "missing":
        roots = {}
    elif change == "disabled":
        roots[generated.key_id] = replace(generated.root, status="DISABLED")
    elif change == "wrong_scope":
        roots[generated.key_id] = replace(generated.root, scope="LIVE_EXECUTION")
    elif change == "wrong_key":
        roots[generated.key_id] = replace(generated.root, public_key=b"x" * 32)
    else:
        revoked = (hashlib.sha256(generated.admission.certificate).hexdigest(),)
    admission = replace(generated.admission, trust_roots=roots, revoked_certificate_sha256=revoked)
    with pytest.raises(Exception, match="FUNDING_SIGNATURE"):
        assess(fixture, receipt=admission)


@pytest.mark.parametrize("changes,code", [
    ({"settled_cash": "NaN"}, "SIGNATURE_OR_CLAIMS"),
    ({"settled_cash": 1000}, "SIGNATURE_OR_CLAIMS"),
    ({"settled_cash": "-1"}, "SIGNATURE_OR_CLAIMS"),
    ({"expires_at": (NOW+timedelta(seconds=31)).isoformat()}, "SIGNATURE_OR_CLAIMS"),
    ({"observed_at": (NOW+timedelta(seconds=1)).isoformat()}, "NOT_CURRENT"),
    ({"observed_at": (NOW-timedelta(seconds=30)).isoformat(), "expires_at": NOW.isoformat()}, "NOT_CURRENT"),
    ({"short_market_value": "1"}, "SHORT_EXPOSURE"),
    ({"effective_session": (DAY+timedelta(days=1)).isoformat()}, "SUBJECT_MISMATCH"),
    ({"account_sha256": "b" * 64}, "OBSERVATION_CHANGED"),
    ({"positions_sha256": "b" * 64}, "OBSERVATION_CHANGED"),
])
def test_even_signed_claims_must_obey_native_funding_contract(changes, code):
    fixture = order_fixture()
    generated = funding(fixture)
    with pytest.raises(Exception, match=code):
        assess(fixture, receipt=signed_changed(generated, **changes))


def test_subject_and_contract_cannot_be_transplanted_from_another_account():
    fixture = order_fixture()
    generated = funding(fixture)
    subject = {**generated.claims["subject"], "account_id": "22222222-2222-2222-2222-222222222222"}
    with pytest.raises(Exception, match="SUBJECT_MISMATCH"):
        assess(fixture, receipt=signed_changed(generated, subject=subject))
    refs = {**generated.claims["qualification_receipts"], "native_settlement": "0" * 64}
    with pytest.raises(Exception, match="CONTRACT_MISMATCH"):
        assess(fixture, receipt=signed_changed(generated, qualification_receipts=refs))


def test_native_observation_cannot_be_reused_after_cash_or_positions_changed():
    fixture = order_fixture()
    generated = funding(fixture)
    with pytest.raises(Exception, match="OBSERVATION_CHANGED"):
        assess(fixture, receipt=generated.admission, account=replace(fixture.account, cash=Decimal(999)))
    position = BrokerPosition(fixture.request.instrument, Decimal(1))
    with pytest.raises(Exception, match="OBSERVATION_CHANGED"):
        assess(fixture, receipt=generated.admission, positions=(position,))


def test_unsigned_tampering_and_noncanonical_bytes_refuse():
    fixture = order_fixture()
    generated = funding(fixture)
    parsed = json.loads(generated.admission.certificate)
    parsed["claims"]["settled_cash"] = "1000000"
    for encoded in (canonical_json_bytes(parsed), json.dumps(parsed, indent=2).encode()):
        with pytest.raises(Exception, match="SIGNATURE_OR_CLAIMS"):
            assess(fixture, receipt=replace(generated.admission, certificate=encoded))


def test_funding_revocation_is_rechecked_between_assessments():
    fixture = order_fixture()
    generated = funding(fixture)
    revoked = set()
    receipt = replace(generated.admission, revoked_certificate_sha256=lambda: revoked)
    assert assess(fixture, receipt=receipt).allowed
    revoked.add(hashlib.sha256(generated.admission.certificate).hexdigest())
    with pytest.raises(Exception, match="SIGNATURE_OR_CLAIMS"):
        assess(fixture, receipt=receipt)


def test_funding_digest_ignores_audit_raw_but_binds_each_typed_economic_fact():
    fixture = order_fixture()
    original = settlement.account_snapshot_sha256(fixture.account)
    raw = replace(fixture.account, identity=replace(fixture.account.identity, raw={"audit": "ignored"}))
    assert settlement.account_snapshot_sha256(raw) == original
    assert settlement.account_snapshot_sha256(replace(fixture.account, equity=Decimal(999))) != original


def test_contract_match_guard_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(settlement.require_live_funding)
    needle = "if claims.qualification_receipts != expected:"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "live-contract-falsifier", "exec"),
         settlement.__dict__, namespace)
    monkeypatch.setattr(settlement, "require_live_funding", namespace["require_live_funding"])
    from sentinel.execution import live_order_policy
    monkeypatch.setattr(live_order_policy, "require_live_funding", namespace["require_live_funding"])
    with pytest.raises(pytest.fail.Exception):
        test_subject_and_contract_cannot_be_transplanted_from_another_account()
