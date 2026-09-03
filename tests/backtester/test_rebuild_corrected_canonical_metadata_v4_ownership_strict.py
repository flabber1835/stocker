from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).parents[2] / "backtester" / "run_rebuild_corrected_canonical_metadata_v4_ownership_strict.py"
    spec = importlib.util.spec_from_file_location("strictaudit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _base():
    guard={"security_id":"s","ticker":"ABC","first_session":"2007-01-03","last_session":"2007-12-31"}
    row={
        "security_id":"s","ticker":"ABC","first_session":"2007-01-03","last_session":"2007-12-31",
        "candidate_cik":"0000000002","source_cik":"0000000001",
        "issuer_cik_source":"OWNERSHIP_XML_ISSUER_CIK","issuer_cik_matches_source":"false",
        "candidate_kind":"IDENTITY_EXACT_TICKER","candidate_quality":"SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML",
        "form":"4","filed":"2007-06-01","source_url":"https://www.sec.gov/Archives/edgar/data/1/x.txt",
        "source_sha256":"a"*64,"admission_effect":"NONE_CANDIDATE_ONLY",
    }
    return row,guard


def test_exact_issuer_trading_symbol_xml_can_pass_validation() -> None:
    strict=_load(); row,guard=_base()
    assert strict.ownership_strict_validate(row,guard,guard,{"ABC":[guard]})==""


def test_generic_ownership_trading_symbol_label_fails_closed() -> None:
    strict=_load(); row,guard=_base()
    row["candidate_quality"]="SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
    assert strict.ownership_strict_validate(row,guard,guard,{"ABC":[guard]})=="ownership_identity_without_issuer_trading_symbol_xml"


def test_non_ownership_label_is_not_rejected_by_ownership_guard() -> None:
    strict=_load(); row,guard=_base()
    row.update({"form":"10-K","candidate_cik":"0000000001","issuer_cik_source":"SOURCE_URL_CIK_NON_OWNERSHIP","issuer_cik_matches_source":"true","candidate_quality":"SEC_EXPLICIT_TRADING_SYMBOL_LABEL"})
    assert strict.ownership_strict_validate(row,guard,guard,{"ABC":[guard]})==""
