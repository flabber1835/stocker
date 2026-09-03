#!/usr/bin/env python3
"""Ownership-strict V4 miner.

Forms 3/4/5 may contain a reporting owner's ticker or other trading-symbol text.
For those forms, issuer identity is accepted as a candidate only when the filing
contains an exact <issuerTradingSymbol> XML match. Generic trading-symbol labels
remain usable for non-ownership forms. Output remains candidate-only.
"""
from __future__ import annotations

from backtester import mine_historical_metadata_candidates_v4_issuer_safe as safe

MINE_SCHEMA = "backtester.historical-metadata-reconstruction-v4.ownership-strict-candidate-mine/1"
MERGE_SCHEMA = "backtester.historical-metadata-reconstruction-v4.ownership-strict-candidate-merge/1"
_ORIGINAL_PROOFS = safe.v3.explicit_ticker_proofs


def ownership_strict_ticker_proofs(raw_text: str, visible: str, ticker: str):
    proofs = _ORIGINAL_PROOFS(raw_text, visible, ticker)
    form, _filed, _accession, _sic = safe.v3.filing_metadata(raw_text, "")
    if form in safe.v3.OWNERSHIP_FORMS:
        return [proof for proof in proofs if proof[0] == "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML"]
    return proofs


def main() -> int:
    safe.SCHEMA = MINE_SCHEMA
    safe.MERGE_SCHEMA = MERGE_SCHEMA
    safe.v3.explicit_ticker_proofs = ownership_strict_ticker_proofs
    return safe.main()


if __name__ == "__main__":
    raise SystemExit(main())
