from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).parents[2] / "backtester" / "rebuild_corrected_canonical_metadata_v4.py"
    spec = importlib.util.spec_from_file_location("v4audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_strict_prior_excludes_same_day_evidence() -> None:
    audit = _load()
    dates = {"s": ["2007-02-08"]}
    values = {"s": ["common"]}
    assert audit._prior(dates, values, "s", "2007-02-08") == ""
    assert audit._prior(dates, values, "s", "2007-02-09") == "common"


def test_ownership_candidate_requires_filing_issuer_cik_binding() -> None:
    audit = _load()
    guard = {
        "security_id": "sid", "ticker": "ABC",
        "first_session": "2007-01-03", "last_session": "2007-12-31",
    }
    unresolved = dict(guard)
    row = {
        "security_id": "sid", "ticker": "ABC",
        "first_session": "2007-01-03", "last_session": "2007-12-31",
        "candidate_cik": "0000000002", "source_cik": "0000000001",
        "issuer_cik_source": "OWNERSHIP_XML_ISSUER_CIK",
        "issuer_cik_matches_source": "false",
        "candidate_kind": "IDENTITY_EXACT_TICKER",
        "candidate_quality": "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML",
        "form": "4", "filed": "2007-06-01",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/x.txt",
        "source_sha256": "a" * 64,
        "admission_effect": "NONE_CANDIDATE_ONLY",
    }
    assert audit._validate_safe_candidate(row, unresolved, guard, {"ABC": [guard]}) == ""
    bad = dict(row)
    bad["issuer_cik_source"] = "SOURCE_URL_CIK_NON_OWNERSHIP"
    assert audit._validate_safe_candidate(bad, unresolved, guard, {"ABC": [guard]}) == "ownership_issuer_cik_not_filing_bound"


def test_non_ownership_candidate_cik_must_match_source_cik() -> None:
    audit = _load()
    guard = {
        "security_id": "sid", "ticker": "ABC",
        "first_session": "2007-01-03", "last_session": "2007-12-31",
    }
    row = {
        "security_id": "sid", "ticker": "ABC",
        "first_session": "2007-01-03", "last_session": "2007-12-31",
        "candidate_cik": "0000000002", "source_cik": "0000000001",
        "issuer_cik_source": "SOURCE_URL_CIK_NON_OWNERSHIP",
        "issuer_cik_matches_source": "false",
        "form": "10-K", "filed": "2007-06-01",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/x.txt",
        "source_sha256": "b" * 64,
        "admission_effect": "NONE_CANDIDATE_ONLY",
    }
    assert audit._validate_safe_candidate(row, guard, guard, {"ABC": [guard]}) == "non_ownership_candidate_cik_not_source_bound"


def test_cik_evidence_does_not_define_security_episode_boundary() -> None:
    audit = _load()
    # A filing inside an already-defined corrected episode is allocatable evidence;
    # this helper has no path that creates or changes a security episode.
    guard = {
        "security_id": "same-security", "ticker": "MLS",
        "first_session": "2007-01-03", "last_session": "2007-03-30",
    }
    row = {"ticker": "MLS", "filed": "2007-02-08"}
    assert audit._candidate_date_allowed(row, guard, {"MLS": [guard]}) is True
    assert guard["security_id"] == "same-security"
