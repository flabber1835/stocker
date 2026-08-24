# Provenance

## SEC issuer identity

Session-effective issuer identity uses the retained PR #208 Form 3/4/5 observation corpus. A filing is usable only when `filing_date < decision_session`; same-day filings are not assumed known. Missing/ambiguous evidence falls back to permanent security identity.

Retained Form 3/4/5 observations SHA-256:

`61287dcab9185136deedfb8f5f64c391751980a761b748e6bde848366ce65cd0`

## SEC SIC tape

Upstream data are the U.S. SEC Financial Statement Data Sets `submissions` table for 2009Q2 through 2026Q1. Direct SEC ZIP retrieval returned HTTP 403 from GitHub-hosted runners, so a public DuckDB mirror of the same SEC table was used as transport:

`erlenbusch/sec-edgar` / `sec_edgar.duckdb`

The mirror file was identified in the reconstruction workflow as SHA-256:

`fdfd9c5807dac4725a1fb0b84b42a547be75f9a70d3568280a45930d1776a044`

Exported as-filed SIC tape:

- rows: 423,766
- SHA-256: `cee14e068e0793bcaaf668ffe3bbbd09c5d2107699ecd08b71371641a3efd8b7`
- causal rule: latest SIC evidence with `filed < decision_session`
- validation fingerprint: 2011Q2 contains exactly 1,695 unique `(filed, CIK, SIC)` observations, matching the prior direct-SEC reconstruction.

## Sector definition

SIC is mapped to the frozen Fama-French 12-industry classification. This is a causal replacement taxonomy, not a claim to reproduce historical Sharadar sector labels byte-for-byte. When no causal SIC is available, the security is assigned a singleton unknown peer so missing evidence cannot create peer contagion.
