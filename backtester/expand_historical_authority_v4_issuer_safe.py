#!/usr/bin/env python3
"""Issuer-safe wrapper for bounded V4 external SEC authority expansion.

For Forms 3/4/5 the EDGAR archive URL CIK may belong to a reporting owner.
This wrapper preserves the existing strict-prior discovery/harvest contract but
binds candidate issuer identity to the filing's <issuerCik>. It remains
candidate-only and does not mutate canonical PIT data.
"""
from __future__ import annotations

from backtester import expand_historical_authority_v4 as base
from backtester.mine_historical_metadata_candidates_v4_issuer_safe import issuer_cik_for_filing
from backtester.sec_http_transport_resilient_v4 import ResilientSecHttpTransport

SCHEMA = "backtester.historical-metadata-authority-expansion-v4.issuer-safe/1"
_ORIGINAL_ANALYZE = base.analyze_filing


def analyze_filing(row, cik, accession, data, source_url, discovery_url, discovery_sha256, source_member):
    raw = data.decode("utf-8", errors="replace")
    form, _filed, _parsed_accession, _sic = base.filing_metadata(raw, source_url)
    issuer_cik, issuer_cik_source = issuer_cik_for_filing(
        form=form, raw_text=raw, source_cik=cik
    )
    if not issuer_cik:
        return None
    result = _ORIGINAL_ANALYZE(
        row, issuer_cik, accession, data, source_url,
        discovery_url, discovery_sha256, source_member,
    )
    if result is None:
        return None
    result["source_cik"] = str(cik)
    result["issuer_cik_source"] = issuer_cik_source
    result["issuer_cik_matches_source"] = str(issuer_cik == str(cik)).lower()
    return result


def main() -> int:
    base.SCHEMA = SCHEMA
    base.SecHttpTransport = ResilientSecHttpTransport
    base.analyze_filing = analyze_filing
    for field in ("source_cik", "issuer_cik_source", "issuer_cik_matches_source"):
        if field not in base.EVIDENCE_FIELDS:
            base.EVIDENCE_FIELDS.append(field)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
