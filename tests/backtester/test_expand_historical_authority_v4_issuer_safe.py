from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).parents[2] / "backtester" / "expand_historical_authority_v4_issuer_safe.py"
    spec = importlib.util.spec_from_file_location("v4extsafe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _row():
    return {
        "security_id": "sid",
        "ticker": "MCHP",
        "bucket": "TYPE_AND_SECTOR",
        "authority_before": "2003-01-02",
    }


def test_external_form4_uses_issuer_cik_not_reporting_owner_cik() -> None:
    safe = _load()
    raw = b"""
ACCESSION NUMBER: 0001181945-02-000001
CONFORMED SUBMISSION TYPE: 4
FILED AS OF DATE: 20020101
<ownershipDocument>
<issuer><issuerCik>0000827054</issuerCik><issuerTradingSymbol>MCHP</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0001181945</rptOwnerCik></reportingOwnerId></reportingOwner>
</ownershipDocument>
"""
    result = safe.analyze_filing(
        _row(), "0001181945", "0001181945-02-000001", raw,
        "https://www.sec.gov/Archives/edgar/data/1181945/x.txt",
        "https://efts.sec.gov/example", "abc", "sources/x.bin",
    )
    assert result is not None
    assert result["candidate_cik"] == "0000827054"
    assert result["source_cik"] == "0001181945"
    assert result["issuer_cik_source"] == "OWNERSHIP_XML_ISSUER_CIK"
    assert result["issuer_cik_matches_source"] == "false"
    assert result["admission_effect"] == "NONE_CANDIDATE_ONLY"


def test_external_ownership_form_missing_issuer_cik_is_rejected() -> None:
    safe = _load()
    raw = b"""
CONFORMED SUBMISSION TYPE: 4
FILED AS OF DATE: 20020101
<ownershipDocument><issuer><issuerTradingSymbol>MCHP</issuerTradingSymbol></issuer></ownershipDocument>
"""
    result = safe.analyze_filing(
        _row(), "0001181945", "x", raw,
        "https://www.sec.gov/Archives/edgar/data/1181945/x.txt",
        "https://efts.sec.gov/example", "abc", "sources/x.bin",
    )
    assert result is None


def test_external_non_ownership_keeps_source_cik() -> None:
    safe = _load()
    raw = b"""
ACCESSION NUMBER: 0000827054-02-000001
CONFORMED SUBMISSION TYPE: 10-K
FILED AS OF DATE: 20020101
TRADING SYMBOL: MCHP
"""
    result = safe.analyze_filing(
        _row(), "0000827054", "0000827054-02-000001", raw,
        "https://www.sec.gov/Archives/edgar/data/827054/x.txt",
        "https://efts.sec.gov/example", "abc", "sources/x.bin",
    )
    assert result is not None
    assert result["candidate_cik"] == "0000827054"
    assert result["source_cik"] == "0000827054"
    assert result["issuer_cik_matches_source"] == "true"
