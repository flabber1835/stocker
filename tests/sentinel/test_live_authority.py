"""Offline LIVE signatures, exact subjects and fresh revocation boundaries."""
from dataclasses import replace
from datetime import timedelta
import inspect
import json

import pytest

from sentinel.authority.canonical import canonical_json_bytes
from sentinel.authority.live import (
    AuthorityRefused, LiveAdapterAdmission, LiveAuthorityContext, LiveLimits,
    LiveTrustRoot, require_live_adapter_admission,
)
from tests.sentinel.live_authority_fixtures import live_fixture, signed_live


def verify(fixture, admission=None, **kwargs):
    return require_live_adapter_admission(
        fixture.admission if admission is None else admission,
        base_url="https://api.alpaca.markets", now=fixture.now, **kwargs)


def resigned(fixture, claims):
    return replace(fixture.admission, certificate=signed_live(claims, fixture.private_key, fixture.key_id))


def test_separately_enrolled_live_authority_is_exact_and_bounded():
    fixture = live_fixture()
    authority = verify(fixture, required_operation="SUBMIT")
    assert authority.subject == fixture.subject
    assert authority.claims.limits.max_capital == 10000
    assert authority.claims.limits.max_order_principal == 1000
    assert authority.certificate_sha256 == authority.sha256


def test_no_enrollment_and_disabled_root_refuse():
    fixture = live_fixture()
    for roots in ({}, {fixture.key_id: replace(fixture.roots[fixture.key_id], status="DISABLED")}):
        with pytest.raises(AuthorityRefused, match="enrolled"):
            verify(fixture, replace(fixture.admission, trust_roots=roots))


def test_paper_envelope_and_settlement_key_cannot_authorize_live_orders():
    fixture = live_fixture()
    paper = signed_live(fixture.claims, fixture.private_key, fixture.key_id,
                        schema="sentinel.paper_execution_certificate/1")
    with pytest.raises(AuthorityRefused, match="schema"):
        verify(fixture, replace(fixture.admission, certificate=paper))
    roots = {fixture.key_id: replace(fixture.roots[fixture.key_id], scope="LIVE_SETTLEMENT")}
    with pytest.raises(AuthorityRefused, match="enrolled"):
        verify(fixture, replace(fixture.admission, trust_roots=roots))


@pytest.mark.parametrize("changes", [
    {"account_id": "22222222-2222-2222-2222-222222222222"},
    {"deployment_id": "another-appliance"}, {"takeover_epoch": 2},
    {"environment": "ALPACA_PAPER", "base_url": "https://paper-api.alpaca.markets"},
])
def test_exact_account_environment_deployment_and_epoch_cannot_replay(changes):
    fixture = live_fixture()
    subject = fixture.subject.model_copy(update=changes)
    admission = replace(fixture.admission, context=LiveAuthorityContext(subject, fixture.bindings))
    with pytest.raises(AuthorityRefused):
        verify(fixture, admission)


def test_live_certificate_cannot_authorize_paper_or_an_unknown_operation():
    fixture = live_fixture()
    with pytest.raises(AuthorityRefused, match="PAPER"):
        require_live_adapter_admission(fixture.admission, base_url="https://paper-api.alpaca.markets", now=fixture.now)
    with pytest.raises(AuthorityRefused, match="unknown"):
        verify(fixture, required_operation="LIQUIDATE")
    fixture = live_fixture(operations=("READ",))
    with pytest.raises(AuthorityRefused, match="does not allow"):
        verify(fixture, required_operation="SUBMIT")


def test_manual_live_certificate_cannot_be_promoted_to_unattended_authority():
    fixture = live_fixture(operations=("READ", "SUBMIT", "CANCEL"))
    verify(fixture, required_operation="SUBMIT")
    with pytest.raises(AuthorityRefused, match="does not allow"):
        verify(fixture, required_operation="AUTOMATION")


def test_current_runtime_must_be_observed_independently():
    fixture = live_fixture()
    bindings = {**fixture.bindings, "sentinel_source_sha256": "1" * 64}
    with pytest.raises(AuthorityRefused, match="current runtime"):
        verify(fixture, replace(fixture.admission, context=LiveAuthorityContext(fixture.subject, bindings)))


def test_fresh_key_and_certificate_revocation_rechecks_after_success():
    fixture = live_fixture()
    revoked = set()
    admission = replace(fixture.admission, trust_roots=lambda: fixture.roots,
                        revoked_certificate_sha256=lambda: revoked)
    verified = verify(fixture, admission)
    revoked.add(verified.sha256)
    with pytest.raises(AuthorityRefused, match="revoked"):
        verify(fixture, admission)
    revoked.clear()
    fixture.roots[fixture.key_id] = replace(fixture.roots[fixture.key_id], status="REVOKED")
    with pytest.raises(AuthorityRefused, match="enrolled"):
        verify(fixture, admission)


@pytest.mark.parametrize("change", ["expired", "future", "too_long", "missing_qualification", "paper_subject"])
def test_signed_but_unqualified_claims_refuse(change):
    fixture = live_fixture()
    claims = json.loads(json.dumps(fixture.claims))
    if change == "expired":
        claims["issued_at"] = (fixture.now - timedelta(hours=2)).isoformat()
        claims["not_before"] = claims["issued_at"]
        claims["expires_at"] = fixture.now.isoformat()
    elif change == "future":
        claims["not_before"] = (fixture.now + timedelta(seconds=1)).isoformat()
    elif change == "too_long":
        claims["expires_at"] = (fixture.now + timedelta(days=2)).isoformat()
    elif change == "missing_qualification":
        del claims["qualification_receipts"]["recovery"]
    else:
        claims["subject"].update(environment="ALPACA_PAPER", base_url="https://paper-api.alpaca.markets")
    with pytest.raises(AuthorityRefused):
        verify(fixture, resigned(fixture, claims))


def test_tampering_noncanonical_bytes_and_extra_fields_refuse():
    fixture = live_fixture()
    raw = json.loads(fixture.admission.certificate)
    raw["claims"]["limits"]["max_capital"] = "1000000"
    with pytest.raises(AuthorityRefused, match="signature"):
        verify(fixture, replace(fixture.admission, certificate=canonical_json_bytes(raw)))
    raw = json.loads(fixture.admission.certificate)
    with pytest.raises(AuthorityRefused, match="canonical"):
        verify(fixture, replace(fixture.admission, certificate=json.dumps(raw, indent=2).encode()))
    raw["scope"] = "ALPACA_LIVE"
    with pytest.raises(AuthorityRefused, match="schema"):
        verify(fixture, replace(fixture.admission, certificate=canonical_json_bytes(raw)))


@pytest.mark.parametrize("value", [1.5, True, "NaN", "Infinity", "0", "-1", "1e1000000"])
def test_limits_have_no_lossy_unbounded_or_permissive_values(value):
    with pytest.raises(ValueError):
        LiveLimits(max_capital=value, max_order_principal="100", max_daily_buy_commitment="100", max_buy_premium_bps=100)


def test_subject_guard_has_a_behavioral_falsifier():
    fixture = live_fixture()
    subject = fixture.subject.model_copy(update={"takeover_epoch": 2})
    admission = replace(fixture.admission, context=LiveAuthorityContext(subject, fixture.bindings))

    def subject_refuses(validator):
        try:
            validator(admission, base_url="https://api.alpaca.markets", now=fixture.now)
        except AuthorityRefused:
            return True
        return False

    assert subject_refuses(require_live_adapter_admission)
    source = inspect.getsource(require_live_adapter_admission)
    needle = "if claims.subject != subject or subject.base_url != endpoint.base_url:"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "live-subject-falsifier", "exec"),
         require_live_adapter_admission.__globals__, namespace)
    assert not subject_refuses(namespace["require_live_adapter_admission"])
