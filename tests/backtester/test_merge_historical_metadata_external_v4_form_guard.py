from backtester.merge_historical_metadata_external_v4 import (
    _normalized_identity_quality,
    _type_quality,
)


def test_unreviewed_reporting_person_form_cannot_establish_identity():
    assert _normalized_identity_quality("SC 13D", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL") == ""
    assert _normalized_identity_quality("SC 13D/A", "SEC_EXCHANGE_QUALIFIED_TICKER") == ""


def test_reviewed_issuer_filed_form_can_establish_identity():
    assert _normalized_identity_quality("6-K", "SEC_EXCHANGE_QUALIFIED_TICKER") == "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
    assert _normalized_identity_quality("10-K", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL") == "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"


def test_ownership_form_requires_issuer_trading_symbol_xml():
    assert _normalized_identity_quality("4", "SEC_EXPLICIT_TRADING_SYMBOL_LABEL") == ""
    assert _normalized_identity_quality("4", "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML") == "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML"


def test_form_8a_registration_proof_maps_to_existing_exact_ticker_quality():
    assert _normalized_identity_quality("8-A12B", "SEC_REGISTRATION_FORM_TRADING_SYMBOL") == "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
    assert _type_quality("8-A12B") == "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
