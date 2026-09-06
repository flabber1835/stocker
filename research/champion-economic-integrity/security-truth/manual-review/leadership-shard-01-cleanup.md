# Leadership security-truth review — shard 01 cleanup

Date: 2026-09-06

Base commit: `08b793ef0bd19c7360d591e25725bbedff43e447`

Branch: `research/champion-security-truth-leadership-01-cleanup`

## Scope

Reviewed exactly these 22 previously unresolved P2 leadership cases:

`GRCE`, `AKAN`, `MKDTY`, `CXRXF`, `AT1`, `FREHY`, `OCNF`, `DSY`, `NRTLQ`, `ORANY`, `GVHGF`, `HYFT`, `PBM`, `AEHL`, `CORZQ`, `BETSF`, `MDVLQ`, `CNL1`, `GSF1`, `CBKCQ`, `ATAC1`, `SKIL2`.

No other security was reviewed in this cleanup.

## Contract and method

Applied `PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md` as a historical truth-oracle classification exercise. Later authoritative evidence was accepted where it establishes the factual legal type during the canonical decision interval.

Fresh authoritative external research used SEC issuer filings, SEC ownership/security filings, and the authoritative depositary program record for SkillSoft. Legal security type was adjudicated independently from incomplete CUSIP/reorganization chains. Identifier anomalies are retained in the JSON case records.

No returns, prices, ranks, portfolio/strategy outcomes, survival, profitability, or future index membership were used. `outcome_information_used=false` for every case.

## Result

- common: 22
- non_common: 0
- split: 0
- unresolved: 0

Every scoped case resolves to ordinary/common corporate equity or an ADR/ADS representing ordinary/common equity under the contract.

## Case results

| Ticker | Decision | Factual legal type | Identity note |
|---|---|---|---|
| GRCE | common | common shares | reverse-split/continuance/name-chain anomalies retained separately |
| AKAN | common | common shares | successive reverse-split CUSIPs |
| MKDTY | common | ADS representing Class A ordinary shares | ADS ratio/CUSIP changes |
| CXRXF | common | common shares | Concordia reorganization/successor identifiers retained separately |
| AT1 | common | common stock | ALLTEL common-stock type established; extra chain identifier retained separately |
| FREHY | common | ADS representing Class A ordinary shares | AnPac/Fresh2 ADS-ratio/name changes; separate preference shares were a distinct instrument |
| OCNF | common | common shares | separate subordinated-share class had converted before the canonical interval |
| DSY | common | Class A ordinary shares | 2026 consolidation/dual-class CUSIP change |
| NRTLQ | common | common shares | NNC common shares distinguished from NNL preferred shares |
| ORANY | common | ADR representing ordinary shares | France Telecom/Orange name and depositary identifiers |
| GVHGF | common | common stock | pre/post-adjustment common-stock CUSIPs |
| HYFT | common | common shares | ImmunoPrecise/MindWalk name and identity chain |
| PBM | common | common shares | predecessor/reorganization and consolidation CUSIPs |
| AEHL | common | Class A ordinary shares | predecessor names and reverse-split CUSIPs |
| CORZQ | common | common stock | predecessor de-SPAC identity; warrants were a separate ticker/class |
| BETSF | common | Class A ordinary shares | predecessor/recapitalization/reverse-split identifiers |
| MDVLQ | common | common stock | predecessor/reorganization/reverse-split identifiers |
| CNL1 | common | common stock | Cleco common-stock type established; related identifiers retained separately |
| GSF1 | common | ordinary shares | GlobalSantaFe-to-Transocean merger identity transition |
| CBKCQ | common | common stock | Christopher & Banks common-stock type established; related identifier retained separately |
| ATAC1 | common | common stock | Aftermarket Technology/ATC Technology rename/CUSIP lineage |
| SKIL2 | common | ADR/ADS representing ordinary shares | SmartForce/SkillSoft depositary-program and name history |

## Authoritative evidence

The detailed JSON records preserve the URLs, source-document types, canonical intervals, CUSIPs, legal-type findings, identity analysis, contradiction searches, and outcome-information controls for every case.

Representative direct evidence includes:

- AKAN: SEC issuer filing states AKAN common shares and the April 2026 reverse-split CUSIP `00971M700`.
- MKDTY: SEC filing states the ADSs represent Class A ordinary shares.
- OCNF: SEC issuer filing identifies Nasdaq-traded OCNF as common shares and separately discusses subordinated shares.
- DSY: SEC issuer filing identifies DSY as Class A Ordinary Shares under CUSIP `G1263B132` during 2026.
- PBM: SEC issuer filing identifies PBM common shares and the January 2026 consolidation CUSIP `74449F407`.
- AEHL: SEC issuer filing identifies AEHL Class A ordinary shares and the March 2026 reverse-split CUSIP `G041JN148`.
- CORZQ: SEC issuer filing identifies CORZQ as common stock and CRZWQ as separate warrants.
- SKIL2: SEC issuer evidence and Citi's depositary record establish the listed SkillSoft security as an ADR/ADS on ordinary shares.

## Remaining unresolved

`[]`

## Validation

- exact requested scope count = 22: PASS
- every requested ticker reviewed exactly once: PASS
- out-of-scope cases reviewed = 0: PASS
- fresh authoritative external research recorded: PASS
- legal type separated from identifier/reorganization anomalies: PASS
- `outcome_information_used=false` for every case: PASS
- remaining unresolved = 0: PASS
- replay/backtest run = false: PASS

No replay or backtest was run.
