#!/usr/bin/env python3
"""Run the ownership-strict V4 corrected canonical observation audit."""
from __future__ import annotations

from backtester import historical_metadata_reconstruction_v2 as v2
from backtester import mine_historical_metadata_candidates_v4_issuer_safe as issuer_safe
from backtester import mine_historical_metadata_candidates_v4_ownership_strict as ownership_strict

v2.verify_package = v2.verify_checksums
issuer_safe.MERGE_SCHEMA = ownership_strict.MERGE_SCHEMA

from backtester import rebuild_corrected_canonical_metadata_v4 as audit

_ORIGINAL_VALIDATE = audit._validate_safe_candidate


def ownership_strict_validate(row, unresolved, guard, by_ticker):
    reason = _ORIGINAL_VALIDATE(row, unresolved, guard, by_ticker)
    if reason:
        return reason
    form = str(row.get("form") or "").upper()
    if (
        form in issuer_safe.v3.OWNERSHIP_FORMS
        and row.get("candidate_kind") == "IDENTITY_EXACT_TICKER"
        and row.get("candidate_quality") != "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML"
    ):
        return "ownership_identity_without_issuer_trading_symbol_xml"
    return ""


audit._validate_safe_candidate = ownership_strict_validate


if __name__ == "__main__":
    raise SystemExit(audit.main())
