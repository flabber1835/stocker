# Held/pending security-truth shard 1

Date: 2026-09-06

Parent branch: `research/champion-certification-economic-integrity`

Parent head inspected before branching: `428721fd4a7494df477c2c9cd3d94ded1c1f5d37`

Shard branch: `research/champion-security-truth-shard-1`

## Scope and result

Assigned securities: **15**

- `common`: **13**
- `non_common`: **0**
- `interval_split`: **0**
- `unresolved`: **2**

Resolved common: `CVSA`, `MIR2`, `DTGF`, `CHAP1`, `CMCSK`, `WGHTQ`, `GOLD1`, `QIHU`, `IAG`, `ENDPQ`, `GEN1`, `SAIL1`, `SHOP`.

Unresolved: `FMX`, `HCR1`.

No resolved security in this shard requires a security-type change from the existing `common` hypothesis. No within-interval security-type transition was established.

## Unresolved worklist

### FMX

Security ID: `63371714929571534`  
Canonical interval: `2006-07-05` through `2026-07-31`  
CUSIP: `344419106`

Primary filings establish that the U.S. ADS represents a **BD Unit**, and each BD Unit bundles Series B, Series D-B and Series D-L Mexican shares. The supplied classification policy does not explicitly classify this bundled multi-series depositary unit. This is therefore retained as `unresolved` and is not promoted to `common`.

Evidence:
- FEMSA Schedule 13D/A (2006): https://www.sec.gov/Archives/edgar/data/1061736/000090342306000386/femsa13da6_0410.htm
- FEMSA Schedule 13D (2010): https://www.sec.gov/Archives/edgar/data/1052192/000110465910022157/a10-8819_1sc13d.htm

Required closure: explicit policy adjudication or authoritative legal analysis establishing that this bundled BD Unit falls within the existing ADR/ADS-on-ordinary/common-equity rule.

### HCR1

Security ID: `718098875444344211`  
Canonical interval: `2006-07-05` through `2007-12-21`  
CUSIPs: `564055101`, `404134108`, `421937103`

CUSIPs `564055101` and `404134108` are independently evidenced as Manor Care / HCR Manor Care common stock. The third CUSIP, `421937103`, was not independently authenticated strongly enough to establish the complete three-CUSIP identity chain. The case remains `unresolved` for full-interval certification.

Evidence:
- SEC Form N-PX covering Manor Care (2007): https://www.sec.gov/Archives/edgar/data/862502/000119312507193595/dnpx.htm
- SEC-filed historical HCR Manor Care holdings table (1999): https://investor.bankofamerica.com/regulatory-and-other-filings/all-sec-filings/content/0000065100-99-000015/0000065100-99-000015.pdf

Required closure: primary or strong secondary identity evidence binding CUSIP `421937103` to the same canonical security episode, with its legal security class and effective dates.

## Multi-CUSIP findings

- `CVSA`: DeVry CUSIP `251893103` to Adtalem CUSIP `00737L103`; common stock on both sides.
- `WGHTQ`: CUSIP `948626106` to `98262P101`; common stock on both sides.
- `ENDPQ`: Endo Health Solutions CUSIP `29264F205` to Endo International CUSIP `G30401106`; common equity on both sides.
- `GEN1`: Reliant Energy `75952B105` to RRI Energy `74971X107` to GenOn Energy `37244E107`; common stock throughout.
- `HCR1`: incomplete identity chain because CUSIP `421937103` remains insufficiently authenticated.

No genuine security-class transition was established in the resolved multi-CUSIP cases.

## Validation

The machine-readable ledger is `held-pending-shard-1.json`.

Validation assertions:

- assigned ticker count: **15**
- case count: **15**
- unique ticker count: **15**
- missing assigned tickers: **none**
- unassigned tickers present: **none**
- duplicate assigned tickers: **none**
- resolved cases with evidence URLs: **13/13**
- `outcome_information_used=false`: **15/15**
- economic replay executed: **no**

JSON SHA-256 (exact repository bytes, no trailing newline):

`fe53dc6bc36928e2590f0dfd5ba1f3a64d15c5ea9f70278e77823456610ff408`

## Classification basis

Only factual security identity, legal form, share/unit class, issuer/security documents, identifier history and corporate-identity transitions were used. Future returns, future price performance, future rank, later strategy outcome, later survival and later index membership were not used.
