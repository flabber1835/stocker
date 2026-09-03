#!/usr/bin/env python3
"""Candidate-only V4 recovery through SEC Form 8-A registration filings.

Form 8-A registers a specific class of securities under Exchange Act Section 12(b)
or 12(g). EFTS search results remain discovery-only. A candidate is emitted only
when the downloaded strict-prior filing itself contains exact historical ticker proof.
Canonical data is never mutated here.
"""
from __future__ import annotations

import re
import urllib.parse

from backtester import expand_historical_authority_v4 as base
from backtester.mine_historical_metadata_candidates_v3 import classify_window
from backtester.sec_http_transport_resilient_v4 import ResilientSecHttpTransport

SCHEMA = "backtester.historical-metadata-authority-expansion-v4.registration-safe/1"
REGISTRATION_FORMS = {"8-A12B", "8-A12B/A", "8-A12G", "8-A12G/A"}
EFTS_FORMS = "8-A12B,8-A12G"


def build_discovery_url(row, offset: int = 0) -> str:
    return base.EFTS + "?" + urllib.parse.urlencode({
        "q": f'"{str(row["ticker"]).upper()}"',
        "forms": EFTS_FORMS,
        "startdt": str(row["search_start"]),
        "enddt": str(row["search_end"]),
        "from": str(offset),
        "size": "100",
    })


def registration_symbol_match(visible: str, ticker: str):
    token = re.escape(str(ticker).upper())
    patterns = (
        re.compile(
            rf"\bunder\s+(?:the\s+)?(?:trading\s+)?symbol\s*[\"'“”]?{token}[\"'“”]?(?![A-Z0-9])",
            re.I,
        ),
        re.compile(
            rf"\b(?:listed|listing|trade|trading)\b.{{0,180}}?\bsymbol\s*[\"'“”]?{token}[\"'“”]?(?![A-Z0-9])",
            re.I,
        ),
    )
    for pattern in patterns:
        match = pattern.search(visible)
        if match:
            return match
    return None


def analyze_filing(
    row, cik: str, accession: str, data: bytes, source_url: str,
    discovery_url: str, discovery_sha256: str, source_member: str,
):
    raw = data.decode("utf-8", errors="replace")
    visible = base.visible_text(raw)
    form, filed, parsed_accession, sic = base.filing_metadata(raw, source_url)
    filed = filed or str(row.get("_hit_filed") or "")
    form = (form or str(row.get("_hit_form") or "")).upper()
    if form not in REGISTRATION_FORMS:
        return None
    if not filed or filed >= str(row["authority_before"]):
        return None

    ticker = str(row["ticker"]).upper()
    proofs = base.historical_ticker_proofs(raw, visible, ticker)
    registration_match = None
    if proofs:
        proof_kind, proof_excerpt = proofs[0]
    else:
        registration_match = registration_symbol_match(visible, ticker)
        if registration_match is None:
            return None
        proof_kind = "SEC_REGISTRATION_FORM_TRADING_SYMBOL"
        proof_excerpt = registration_match.group(0)

    classification, class_excerpt = base.class_candidate_near_ticker(visible, ticker)
    if classification == "unknown" and registration_match is not None:
        start = max(0, registration_match.start() - 1400)
        end = min(len(visible), registration_match.end() + 1400)
        window = visible[start:end]
        classification, evidence = classify_window(window)
        if classification != "unknown":
            class_excerpt = f"{evidence} | {window[:800]}"

    return {
        "security_id": row["security_id"],
        "ticker": ticker,
        "bucket": row.get("bucket", ""),
        "authority_before": row["authority_before"],
        "candidate_cik": cik,
        "accession": parsed_accession or accession,
        "form": form,
        "filed": filed,
        "identity_proof_kind": proof_kind,
        "identity_proof_excerpt": str(proof_excerpt)[:500],
        "classification": classification,
        "classification_excerpt": str(class_excerpt)[:800],
        "sic": sic,
        "form_authority": "REGISTRATION_AUTHORITY_FORM",
        "source_url": source_url,
        "source_sha256": base.sha256_bytes(data),
        "source_member": source_member,
        "discovery_url": discovery_url,
        "discovery_sha256": discovery_sha256,
        "admission_effect": "NONE_CANDIDATE_ONLY",
        "source_cik": str(cik),
        "issuer_cik_source": "SOURCE_URL_CIK_NON_OWNERSHIP",
        "issuer_cik_matches_source": "true",
    }


def main() -> int:
    base.SCHEMA = SCHEMA
    base.SecHttpTransport = ResilientSecHttpTransport
    base.build_discovery_url = build_discovery_url
    # The EFTS hit is only a locator. Form-specific discovery does not need current
    # display-name/ticker metadata; exact ticker identity is proven from raw filing bytes.
    base.display_name_matches_ticker = lambda _display_names, _ticker: True
    base.analyze_filing = analyze_filing
    for field in ("source_cik", "issuer_cik_source", "issuer_cik_matches_source"):
        if field not in base.EVIDENCE_FIELDS:
            base.EVIDENCE_FIELDS.append(field)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
