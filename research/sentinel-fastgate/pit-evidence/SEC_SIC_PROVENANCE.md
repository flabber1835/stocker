# Orion SEC SIC -> FF12 point-in-time evidence

This is a **research-only Orion evidence record**. It does not change production behavior and must not be merged to `main` as a strategy activation.

## Source authority

The economic source is the U.S. SEC Financial Statement Data Sets `submissions` table. The retained corrected PIT experiment used filings from **2009Q2 through 2026Q1**.

Direct retrieval of the SEC quarterly ZIPs from a GitHub-hosted runner returned HTTP 403 during the corrected reconstruction. A public DuckDB mirror of the same SEC table was therefore used as **transport only**:

- dataset: `erlenbusch/sec-edgar`
- database: `sec_edgar.duckdb`
- retained mirror SHA-256: `fdfd9c5807dac4725a1fb0b84b42a547be75f9a70d3568280a45930d1776a044`

The SEC remains the source authority; the mirror is not an independent classification source.

## Retained SIC tape fingerprint

The corrected experiment exported the as-filed SIC tape with these acceptance fingerprints:

- rows: **423,766**
- uncompressed CSV SHA-256: `cee14e068e0793bcaaf668ffe3bbbd09c5d2107699ecd08b71371641a3efd8b7`
- 2011Q2 validation fingerprint: exactly **1,695** unique `(filed, CIK, SIC)` observations
- fields: `filed,cik,sic,adsh,source_quarter`

`.github/workflows/orion-pit-sic-evidence.yml` recovers the exact still-retained corrected-research workflow artifact and refuses to archive it unless all three fingerprints match. It then stores a deterministic gzip copy under `generated/` together with a machine-readable provenance record and checksum.

## Causal rule

For a decision session `t`, the only admissible SIC is the most recent SEC SIC observation satisfying:

`filed < t`

Same-day filings are not assumed known. Later SIC observations are never backfilled into earlier sessions.

If no causal SIC is available for a security, Orion assigns that security a **singleton unknown peer**. There is **no fallback to current Sharadar sector**.

## FF12 mapping

SIC is mapped through the frozen Fama-French 12-industry definition retained in `ff12_sic_definition.txt`. The mapping is a causal replacement taxonomy for peer grouping; it is not a claim to reconstruct historical Sharadar sector labels byte-for-byte.

## Lineage

The authoritative corrected PIT A/B record is retained on branch `research/correct-pit-sector-ab-2026-08-23` under `research/correct-pit-metadata-ab/`.

Its sector evidence fingerprint is the same `cee14e068...` SIC tape used here. The relevant control proved that replacing current Sharadar sector with causal SEC SIC->FF12 changed damaged breadth on 1,480 sessions and the raw native FAST trigger on five sessions.
