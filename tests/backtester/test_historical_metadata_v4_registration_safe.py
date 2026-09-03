from __future__ import annotations

from backtester.expand_historical_authority_v4_registration_safe import (
    analyze_filing,
    build_discovery_url,
    registration_class_candidate,
    registration_symbol_match,
)


def _row():
    return {
        "security_id": "123",
        "ticker": "AX",
        "bucket": "TYPE_AND_SECTOR",
        "authority_before": "2006-01-03",
        "search_start": "2001-01-01",
        "search_end": "2006-01-02",
    }


def _filing(form: str = "8-A12B", filed: str = "20051220") -> bytes:
    return f"""
<SEC-HEADER>
CONFORMED SUBMISSION TYPE: {form}
FILED AS OF DATE: {filed}
ACCESSION NUMBER: 0000123456-05-000001
STANDARD INDUSTRIAL CLASSIFICATION: SERVICES-COMPUTER PROGRAMMING [7372]
</SEC-HEADER>
FORM 8-A
Securities to be registered pursuant to Section 12(b) of the Act:
Title of each class to be so registered: Common Stock, $0.01 par value per share
Name of each exchange on which each class is to be registered: The Nasdaq Stock Market LLC
We expect the listing and trading of the Common Stock to commence under the symbol “AX”.
""".encode()


def test_registration_discovery_is_form_scoped():
    url = build_discovery_url(_row())
    assert "forms=8-A12B%2C8-A12G" in url
    assert "size=100" in url
    assert "AX" in url


def test_registration_symbol_phrase_is_exact():
    assert registration_symbol_match("trading will commence under the symbol AX.", "AX") is not None
    assert registration_symbol_match("trading will commence under the symbol AXX.", "AX") is None


def test_registered_class_table_can_classify_far_from_symbol():
    visible = (
        "Title of each class to be registered Common Shares "
        "Name of each exchange on which each class is to be registered NYSE "
        + ("other disclosure " * 300)
        + "trading under the symbol AX"
    )
    classification, excerpt = registration_class_candidate(visible)
    assert classification == "common"
    assert "FORM_8A_REGISTERED_CLASS" in excerpt


def test_registered_class_table_fails_closed_on_mixed_classes():
    visible = (
        "Title of each class to be registered Common Stock and Series A Preferred Stock "
        "Name of each exchange on which each class is to be registered NYSE"
    )
    classification, excerpt = registration_class_candidate(visible)
    assert classification == "unknown"
    assert excerpt == ""


def test_form_8a_candidate_proves_identity_type_and_sic():
    candidate = analyze_filing(
        _row(),
        "0000123456",
        "0000123456-05-000001",
        _filing(),
        "https://www.sec.gov/Archives/edgar/data/123456/000012345605000001/0000123456-05-000001.txt",
        "https://efts.sec.gov/example",
        "a" * 64,
        "sources/filings/source.bin",
    )
    assert candidate is not None
    assert candidate["form"] == "8-A12B"
    assert candidate["identity_proof_kind"] == "SEC_REGISTRATION_FORM_TRADING_SYMBOL"
    assert candidate["classification"] == "common"
    assert candidate["sic"] == "7372"
    assert candidate["candidate_cik"] == "0000123456"
    assert candidate["issuer_cik_source"] == "SOURCE_URL_CIK_NON_OWNERSHIP"
    assert candidate["form_authority"] == "REGISTRATION_AUTHORITY_FORM"
    assert candidate["admission_effect"] == "NONE_CANDIDATE_ONLY"


def test_registration_candidate_is_strict_prior():
    assert analyze_filing(
        _row(), "0000123456", "x", _filing(filed="20060103"),
        "https://www.sec.gov/Archives/edgar/data/123456/x.txt",
        "https://efts.sec.gov/example", "a" * 64, "sources/x.bin",
    ) is None


def test_non_registration_form_cannot_use_registration_symbol_rule():
    assert analyze_filing(
        _row(), "0000123456", "x", _filing(form="10-K"),
        "https://www.sec.gov/Archives/edgar/data/123456/x.txt",
        "https://efts.sec.gov/example", "a" * 64, "sources/x.bin",
    ) is None
