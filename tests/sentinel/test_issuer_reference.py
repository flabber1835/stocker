"""Pure issuer-reference qualification: no account, provider or database access."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError

from sentinel.feed import issuer_reference as reference

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def row(ticker="GOOG", cik="0001652044", exchange="Nasdaq"):
    return {"cik": cik, "ticker": ticker, "exchange": exchange}


def snapshot(rows=None, **kwargs):
    return reference.IssuerReferenceSnapshot.create(
        observed_at_utc=NOW, associations=rows or [row()], **kwargs)


def corroboration(**changes):
    return reference.UnderlyingIssuerCorroboration.create(**{
        "cik": "0001119639", "symbols": ("PBR", "PBR-A"), "exchange": "NYSE",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1119639/000129281426002168/ex2-4.htm",
        "observed_at_utc": NOW, "expires_at_utc": NOW + timedelta(days=1),
        "statement": "Petrobras identifies both common and preferred ADSs as representing its shares.",
        **changes})


def resolve(source, symbol="GOOG", exchange="NASDAQ", kind="Common Stock",
            broad="Common Stock", now=NOW):
    return source.resolve(symbol, exchange, kind, broad, now=now)


def test_bundled_observed_pairs_resolve_to_same_cik_without_name_matching():
    source = reference.load_snapshot()
    assert source.provenance.source_method == "WEB_EXTRACTED_REPRESENTATION"
    assert source.provenance.raw_http_sha256 is None
    assert source.provenance.coverage == "PARTIAL"
    assert len(source.associations) == 10429
    for first, second, cik, exchange, kind, broad in (
        ("GOOG", "GOOGL", "0001652044", "NASDAQ", "Common Stock", "Common Stock"),
        ("BRK.A", "BRK.B", "0001067983", "NYSE", "Common Stock", "Common Stock"),
        ("FOX", "FOXA", "0001754301", "NASDAQ", "Common Stock", "Common Stock"),
        ("PBR", "PBR.A", "0001119639", "NYSE", "ADR", "Depositary Receipt"),
    ):
        identities = [resolve(source, symbol, exchange, kind, broad) for symbol in (first, second)]
        assert {identity.status for identity in identities} == {"VERIFIED"}
        assert {identity.issuer_id for identity in identities} == {f"SEC_CIK:{cik}"}
        assert all(identity.snapshot_digest == source.sha256 for identity in identities)
    assert source.resolve("MSFT", "NASDAQ", "Common Stock", "Common Stock", now=NOW).issuer_id != (
        source.resolve("AAPL", "NASDAQ", "Common Stock", "Common Stock", now=NOW).issuer_id)


def test_round_trip_retains_authenticated_frozen_snapshot_and_identity():
    source = snapshot()
    restored = reference.IssuerReferenceSnapshot.model_validate_json(source.model_dump_json())
    identity = resolve(restored)
    assert identity.status == "VERIFIED" and identity.cik == "0001652044"
    assert reference.IssuerIdentity.model_validate_json(identity.model_dump_json()) == identity
    with pytest.raises(ValidationError):
        restored.provenance.observed_at_utc = NOW + timedelta(days=1)


def test_only_unique_final_dot_hyphen_class_translation_is_allowed():
    source = snapshot([row("SAME-A"), row("SAME-B"), row("SAME-PA")])
    assert resolve(source, "SAME.A").reference_symbol == "SAME-A"
    assert resolve(source, "SAME.B").original_symbol == "SAME.B"
    assert resolve(source, "SAME").status == "UNRESOLVED"
    assert resolve(source, "SAME.PA").status == "UNRESOLVED"
    assert resolve(source, "SAME/A").status == "UNRESOLVED"
    assert resolve(source, "same.a").status == "UNRESOLVED"
    ambiguous = snapshot([row("SAME-A"), row("SAME.A")])
    assert resolve(ambiguous, "SAME.A").reason == "ambiguous_class_separator_association"


@pytest.mark.parametrize("rows", [
    [row(), row(cik="0000320193")],
    [row(), row(cik="0000320193", exchange="NYSE")],
    [row("SAME-A"), row("SAME.A", cik="0000320193")],
])
def test_conflicting_cik_never_resolves_even_if_one_exchange_matches(rows):
    symbol = "SAME.A" if rows[0]["ticker"] == "SAME-A" else "GOOG"
    assert resolve(snapshot(rows), symbol).reason == "conflicting_cik_associations"


@pytest.mark.parametrize("kind,broad", [
    ("Closed-End Fund", "Mutual Fund"), ("ETP", "Mutual Fund"),
    ("Unit", "Unit"), ("Equity WRT", "Warrant"), ("Preferred", "Preferred"),
    ("Unknown", None), (None, None), ("Common Stock", None), ("Common Stock", "Mutual Fund"),
])
def test_unsupported_and_fund_instruments_remain_unresolved(kind, broad):
    assert resolve(snapshot(), kind=kind, broad=broad).reason == "unsupported_security_type"


@pytest.mark.parametrize("exchange", [None, "", "OTC", "LSE", "NYSE", "US"])
def test_exchange_missing_or_wrong_has_no_identity(exchange):
    assert resolve(snapshot(), exchange=exchange).status == "UNRESOLVED"


def test_missing_symbol_is_unresolved_regardless_of_nearby_ticker_or_cik():
    assert resolve(snapshot(), "GOOGL").status == "UNRESOLVED"
    assert resolve(snapshot(), None).status == "UNRESOLVED"


def test_adr_needs_positive_underlying_issuer_proof_and_its_original_expiry():
    rows = [row("PBR", "0001119639", "NYSE"), row("PBR-A", "0001119639", "NYSE")]
    bare = snapshot(rows)
    assert resolve(bare, "PBR", "NYSE", "ADR", "Depositary Receipt").reason == (
        "underlying_issuer_not_corroborated")
    source = snapshot(rows, corroborations=[corroboration()])
    identity = resolve(source, "PBR.A", "NYSE", "ADR", "Depositary Receipt")
    assert identity.status == "VERIFIED" and len(identity.source_urls) == 2
    assert identity.expires_at_utc == NOW + timedelta(days=1)
    assert resolve(source, "PBR.A", "NYSE", "ADR", "Depositary Receipt",
                   NOW + timedelta(days=1)).status == "UNRESOLVED"
    mismatched = snapshot(rows, corroborations=[corroboration(cik="0000320193")])
    assert resolve(mismatched, "PBR", "NYSE", "ADR", "Depositary Receipt").status == "UNRESOLVED"


def test_incumbent_lookup_requires_typed_listing_instead_of_guessing_fund_identity():
    source = snapshot()
    assert source.resolve_symbol("GOOG", "NASDAQ", now=NOW).status == "UNRESOLVED"
    assert source.resolve_symbol("GOOG", "NASDAQ", security_type="Common Stock",
        security_type2="Common Stock", now=NOW).status == "VERIFIED"


def test_observation_is_current_evidence_and_never_a_historical_backfill():
    source = snapshot()
    for current in (NOW - timedelta(microseconds=1), NOW + timedelta(days=30)):
        assert resolve(source, now=current).reason == "reference_expired_or_not_yet_observed"
    assert resolve(source, now=NOW + timedelta(days=30, microseconds=-1)).status == "VERIFIED"
    with pytest.raises(ValueError, match="UTC"):
        resolve(source, now=NOW.replace(tzinfo=None))


def test_content_provenance_and_evidence_tampering_refuse():
    source = snapshot()
    changed = source.model_dump(mode="json")
    changed["associations"][0]["cik"] = "0000320193"
    with pytest.raises(ValidationError, match="digest"):
        reference.IssuerReferenceSnapshot.model_validate(changed)
    changed = source.model_dump(mode="json")
    changed["provenance"]["expires_at_utc"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        reference.IssuerReferenceSnapshot.model_validate(changed)
    identity = resolve(source).model_dump(mode="json")
    identity["issuer_id"] = "SEC_CIK:0000320193"
    with pytest.raises(ValidationError):
        reference.IssuerIdentity.model_validate(identity)


def test_web_extraction_cannot_claim_http_payload_hash_or_infer_a_name():
    with pytest.raises(ValidationError, match="HTTP body hash"):
        snapshot(raw_http_sha256="a" * 64)
    with pytest.raises(ValidationError):
        snapshot([{**row(), "name": "Same Company"}])
    with pytest.raises(ValidationError):
        snapshot([row(cik="1652044")])
    with pytest.raises(ValidationError):
        snapshot([row(cik="0000000000")])


def test_custom_cache_requires_its_independently_retained_digest(tmp_path):
    source = snapshot()
    path = tmp_path / "reference.json"
    path.write_text(source.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="trusted digest"):
        reference.load_snapshot(path)
    assert reference.load_snapshot(path, expected_digest=source.sha256) == source
    with pytest.raises(ValueError, match="trusted digest"):
        reference.load_snapshot(path, expected_digest="f" * 64)


def test_batch_evidence_binds_original_security_identity_and_rejects_duplicates():
    descriptor = {"security_id": "uuid-1", "ticker": "GOOG", "exchange": "NASDAQ",
                  "security_type": "Common Stock", "security_type2": "Common Stock"}
    identities = reference.evidence(snapshot(), [descriptor], now=NOW)
    assert identities["uuid-1"].status == "VERIFIED"
    with pytest.raises(ValueError, match="duplicate"):
        reference.evidence(snapshot(), [descriptor, descriptor], now=NOW)


def test_resolution_never_fetches_reference_or_broker_state(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("resolution attempted network access")
    monkeypatch.setattr(reference, "build_opener", forbidden)
    monkeypatch.setattr(reference, "refresh_snapshot", forbidden)
    assert resolve(snapshot()).status == "VERIFIED"


class Reply(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, raw=None, status=None):
        self.raw, self.status, self.calls = raw, status, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.status:
            raise HTTPError(reference.SEC_ENDPOINT, self.status, "provider-private-text", {}, None)
        return Reply(self.raw)


@pytest.mark.parametrize("status", [403, 429, 503])
def test_refresh_failure_is_one_request_and_never_renews_valid_cache(status):
    source = snapshot()
    opener = Opener(status=status)
    result = reference.refresh_snapshot(source, now=NOW, opener=opener)
    assert result.status == "CACHED_VALID" and result.snapshot == source
    assert result.reason == f"sec_http_{status}" and len(opener.calls) == 1
    assert result.retry_after_seconds >= 3600
    request, timeout = opener.calls[0]
    assert request.full_url == reference.SEC_ENDPOINT and request.get_method() == "GET"
    assert "github.com/flabber1835/stocker" in request.get_header("User-agent")
    assert timeout <= 30 and "provider-private-text" not in result.model_dump_json()


def test_expired_cache_is_not_reactivated_when_refresh_is_blocked():
    result = reference.refresh_snapshot(snapshot(), now=NOW + timedelta(days=30),
                                        opener=Opener(status=403))
    assert result.status == "UNAVAILABLE" and result.snapshot is None


def test_successful_bounded_refresh_records_real_body_hash_without_names_as_identity():
    raw = json.dumps({"fields": ["cik", "name", "ticker", "exchange"],
                      "data": [[1652044, "cosmetic only", "GOOG", "Nasdaq"]]}).encode()
    opener = Opener(raw)
    result = reference.refresh_snapshot(snapshot(), now=NOW, opener=opener)
    assert result.status == "REFRESHED" and len(opener.calls) == 1
    assert result.snapshot.provenance.raw_http_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.snapshot.provenance.source_method == "DIRECT_HTTP_BODY"
    assert "cosmetic only" not in result.snapshot.model_dump_json()


def test_changed_cik_refresh_requires_review_instead_of_accepting_ticker_reuse():
    raw = json.dumps({"fields": ["cik", "name", "ticker", "exchange"],
                      "data": [[320193, "irrelevant", "GOOG", "Nasdaq"]]}).encode()
    source = snapshot()
    result = reference.refresh_snapshot(source, now=NOW, opener=Opener(raw))
    assert result.reason == "changed_cik_requires_identity_review" and result.snapshot == source


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"fields":[],"data":[]}',
                                      b"x" * (reference.MAX_RESPONSE_BYTES + 1)])
def test_invalid_or_oversized_refresh_retains_original_expiry(raw):
    source = snapshot()
    result = reference.refresh_snapshot(source, now=NOW, opener=Opener(raw))
    assert result.status == "CACHED_VALID" and result.snapshot == source


def test_fund_guard_falsifier_detects_removed_supported_type_boundary(monkeypatch):
    source = snapshot()
    def assertion():
        assert resolve(source, kind="Closed-End Fund", broad="Mutual Fund").status == "UNRESOLVED"
    assertion()
    monkeypatch.setitem(reference._SUPPORTED_TYPES, "Closed-End Fund", "Mutual Fund")
    with pytest.raises(AssertionError):
        assertion()
