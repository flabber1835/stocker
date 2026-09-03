from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).parents[2] / "backtester" / "mine_historical_metadata_candidates_v4_issuer_safe.py"
    spec = importlib.util.spec_from_file_location("v4safe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_form4_reporting_owner_url_uses_filing_issuer_cik() -> None:
    v4 = _load()
    raw = """
    <ownershipDocument>
      <issuer><issuerCik>0000827054</issuerCik><issuerTradingSymbol>MCHP</issuerTradingSymbol></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerCik>0001181945</rptOwnerCik></reportingOwnerId></reportingOwner>
    </ownershipDocument>
    """
    cik, source = v4.issuer_cik_for_filing(form="4", raw_text=raw, source_cik="0001181945")
    assert cik == "0000827054"
    assert source == "OWNERSHIP_XML_ISSUER_CIK"
    assert cik != "0001181945"


def test_form4_issuer_url_still_requires_and_uses_issuer_cik() -> None:
    v4 = _load()
    raw = "<issuer><issuerCik>1297989</issuerCik><issuerTradingSymbol>ABC</issuerTradingSymbol></issuer>"
    cik, source = v4.issuer_cik_for_filing(form="4", raw_text=raw, source_cik="0001297989")
    assert cik == "0001297989"
    assert source == "OWNERSHIP_XML_ISSUER_CIK"


def test_ownership_form_without_issuer_cik_fails_closed() -> None:
    v4 = _load()
    raw = "<ownershipDocument><issuer><issuerTradingSymbol>ABC</issuerTradingSymbol></issuer></ownershipDocument>"
    cik, source = v4.issuer_cik_for_filing(form="4", raw_text=raw, source_cik="0001181945")
    assert cik == ""
    assert source == "OWNERSHIP_XML_ISSUER_CIK_MISSING"


def test_non_ownership_form_uses_source_cik() -> None:
    v4 = _load()
    cik, source = v4.issuer_cik_for_filing(form="10-K", raw_text="", source_cik="827054")
    assert cik == "0000827054"
    assert source == "SOURCE_URL_CIK_NON_OWNERSHIP"


def test_corrected_issuer_not_in_causal_set_remains_discovery_only() -> None:
    v4 = _load()
    episode = {"_causal_ciks": {"0001181945"}}
    assert v4.candidate_authority("0000827054", episode) == "DISCOVERY_ONLY_HINT"
    assert v4.candidate_authority("0001181945", episode) == "CAUSALLY_ESTABLISHED"
