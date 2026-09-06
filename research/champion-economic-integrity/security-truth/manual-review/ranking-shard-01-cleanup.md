# Ranking/base security-truth review — shard 01 cleanup

Base: `0a4f08207f9f8c83a2c86cb56cd4fc78805563fa`

Branch: `research/champion-security-truth-ranking-01-cleanup`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

Scope is exactly the seven unresolved P3 ranking/base cases carried by the base review: `LB`, `SYCRF`, `NCV-PA`, `ACR-PC`, `BTTGY`, `VNTRQ`, and `CVOVQ`.

Fresh authoritative research was performed for each case. Security identity/CUSIP continuity is analyzed separately from factual legal security type. No return, price, rank, Champion selection, survival, profitability, future index membership, strategy outcome, replay result, or backtest result was used. Every record has `outcome_information_used=false`.

## Results

Counts: **5 common / 2 non_common / 0 split / 0 unresolved**.

| ticker | canonical interval | decision | legal security type |
|---|---|---|---|
| LB | 2024-12-27/2026-07-29 | common | Class A shares representing limited liability company interests (Class A common equity) |
| SYCRF | 2007-08-02/2007-11-21 | common | common shares |
| NCV-PA | 2024-12-20/2024-12-31 | non_common | 5.625% Series A Cumulative Preferred Shares |
| ACR-PC | 2025-01-07/2025-01-07 | non_common | 8.625% Fixed-to-Floating Series C Cumulative Redeemable Preferred Stock |
| BTTGY | 2008-01-04/2019-09-19 | common | American Depositary Shares evidenced by ADRs, representing BT Group ordinary shares |
| VNTRQ | 2018-02-07/2018-03-06 | common | ordinary shares |
| CVOVQ | 2007-08-08/2007-09-04 | common | common stock |

## LB — common

Canonical CUSIP: `514952100`.

SEC Schedule 13G evidence identifies the exact security as **Class A shares representing limited liability company interests**. A separate CUSIP-specific SEC filing describes the same security as **Class A common stock**. This is LandBridge Company LLC's publicly traded Class A common-equity class and fits the contract's common-equity category.

Evidence:

- https://www.sec.gov/Archives/edgar/data/1837343/000119312524176264/d101492dsc13g.htm
- https://www.sec.gov/Archives/edgar/data/1995807/000105682326000020/xslSCHEDULE_13G_X02/primary_doc.xml
- https://www.sec.gov/Archives/edgar/data/315066/000031506626002059/xslSCHEDULE_13G_X02/primary_doc.xml

Identity analysis: the canonical record has one CUSIP. No identity-chain uncertainty affects the classification.

Contradiction search: no authoritative evidence identified CUSIP `514952100` as preferred, a warrant/right, partnership unit, trust unit, depositary preferred, or another non-common instrument.

## SYCRF — common

CUSIPs: `G8649T109`, `G8018D107`.

Security Capital Assurance Ltd.'s SEC Form 10-K for 2007 identifies its publicly traded equity as **common shares** and separately discusses **Series A Preference Shares**. SEC proxy and issuer materials establish the later Security Capital Assurance-to-Syncora corporate name change while continuing the common-share security.

Evidence:

- https://www.sec.gov/Archives/edgar/data/1358164/000093041308001742/c52677_10k.htm
- https://www.sec.gov/Archives/edgar/data/1358164/000093041308002591/c52053_def14a.htm
- https://www.sec.gov/Archives/edgar/data/1358164/000093041308004574/c54399_ex99-1.htm

Identity analysis: `G8018D107` belongs to the Security Capital Assurance identity in the canonical era; `G8649T109` is associated with the later Syncora identity. The name/identifier transition is identity continuity. It does not establish a legal security-type transition during `2007-08-02/2007-11-21`.

Contradiction search: authoritative filings distinguish preference shares from the traded common shares. No evidence establishes that the decision-period security was a preference share or another non-common instrument.

## NCV-PA — non_common

CUSIPs: `018828707`, `92838X706`.

Virtus's authoritative fund-name-change table explicitly maps both identifiers to the same preferred class:

- `018828707`: AllianzGI Convertible & Income Fund **Series A Cumulative Preferred Shares**
- `92838X706`: Virtus AllianzGI Convertible & Income Fund **Series A Cumulative Preferred Shares**

The table gives NYSE symbol `NCV PR A`. Current issuer materials identify the class as **5.625% Series A Cumulative Preferred Shares**.

Evidence:

- https://www.virtus.com/assets/files/4ky/january-27-2021-allianzgi-closed-end-funds-provide-additional-information-on-fund-name-changes.pdf
- https://ir.virtus.com/news/news-details/2026/Virtus-Convertible--Income-Fund-Announces-Quarterly-Distribution-5-625-Series-A-Cumulative-Preferred-Shares/default.aspx

Identity analysis: the sponsor explicitly ties the two CUSIPs to the 2021 fund-name/CUSIP change. The legal instrument remains the same Series A cumulative preferred-share class.

Contradiction search: no authoritative source describes `NCV PR A` as common equity or another eligible common-share instrument.

## ACR-PC — non_common

CUSIPs: `30068N402`, `00489Q201`.

Issuer announcements identify the exact class throughout both corporate renames as **8.625% Fixed-to-Floating Series C Cumulative Redeemable Preferred Stock**. The 2018 Resource Capital-to-Exantas rename assigned preferred CUSIP `30068N402`. The 2021 Exantas-to-ACRES rename assigned preferred CUSIP `00489Q201` and ticker `ACR PrC`.

Evidence:

- https://www.acresreit.com/2018-05-03-Resource-Capital-Corp-Reports-Results-for-Three-Months-Ended-March-31-2018-and-Announces-Name-Change
- https://www.acresreit.com/2021-02-16-Exantas-Capital-Corp-Changes-Name-to-ACRES-Commercial-Realty-Corp-and-Begins-Trading-Under-Ticker-Symbol-ACR

Identity analysis: both CUSIPs are issuer-linked identities of the same Series C preferred class. The corporate-name/CUSIP changes do not alter legal type.

Contradiction search: issuer materials separately identify common stock and the Series C cumulative redeemable preferred stock. No common-stock treatment of the Series C security was found.

## BTTGY — common

CUSIPs: `05577E101`, `111021200`, `111021408`.

BT's issuer listing history states that BT ordinary shares were also listed on the NYSE in the form of **American Depositary Shares** through September 2019. SEC materials identify ISIN `US05577E1010` as American Depositary Shares and state that one ADS represented five BT Group ordinary shares. Citibank's predecessor British Telecommunications ADR record for CUSIP `111021408` documents the successor BT Group NYSE CUSIP `05577E101`.

Evidence:

- https://www.bt.com/about/investors/financial-reporting-and-news/annual-reports/listing-history
- https://www.sec.gov/Archives/edgar/data/756620/000165495419012313/batchfiling-04112019.htm
- https://www.sec.gov/Archives/edgar/data/756620/000119312520147926/d873656d20f.htm
- https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=111021408&pageId=16&subpageID=104&typeDisplay=A

Identity analysis: `05577E101` is the decision-period BT Group ADS/ADR security. `111021408` is a predecessor British Telecommunications ADR identifier terminated years before the canonical interval and linked by the depositary to `05577E101`. `111021200` remains legacy identity metadata that is not needed to determine the decision-period security's factual legal type. No type transition is established within `2008-01-04/2019-09-19`.

Contradiction search: issuer, SEC, and depositary evidence consistently describes the decision-period U.S. security as ADS/ADR interests in ordinary shares. No preferred or other non-common legal class was found.

## VNTRQ — common

CUSIPs: `G9329Z100`, `G9329Z118`.

Venator's 2017 Form 10-K, filed during the canonical period, states that its publicly traded equity consisted of **ordinary shares**. A CUSIP-specific SEC filing identifies `G9329Z100` as **Ordinary Shares, par value $0.001**. A later SEC filing identifies post-reorganization `G9329Z118` as common stock.

Evidence:

- https://www.sec.gov/Archives/edgar/data/1705682/000155837018001041/vntr-20171231x10k.htm
- https://www.sec.gov/Archives/edgar/data/1307954/000110465921009525/tm214454d1_sc13ga.htm
- https://www.sec.gov/Archives/edgar/data/312069/000031206925000143/xslSCHEDULE_13G_X01/primary_doc.xml

Identity analysis: `G9329Z100` is the canonical 2018 ordinary-share identifier. `G9329Z118` is a later post-reorganization common-equity identifier. The later identity episode does not create a type transition inside the 2018 canonical interval.

Contradiction search: no authoritative filing identifies canonical CUSIP `G9329Z100` as preferred, a warrant/right, partnership/trust unit, or another non-common instrument.

## CVOVQ — common

CUSIPs: `15670S105`, `15670S402`, `560321200`.

SEC records identify Cenveo ticker `CVO` with CUSIP `15670S105` in the 2007 issuer period. CUSIP-specific SEC holdings filings identify `15670S105` as **common stock**. The later CUSIP `15670S402` is likewise identified as common equity shares/common stock. SEC issuer history confirms Cenveo's predecessor name Mail-Well Inc.

Evidence:

- https://www.sec.gov/Archives/edgar/data/895429/000118811208002863/t63733m_n-px.htm
- https://www.sec.gov/Archives/edgar/data/883422/000114036114040298/xslForm13F_X01/form13fInfoTable.xml
- https://www.sec.gov/Archives/edgar/data/93751/000162828016018963/xslForm13F_X01/copy2ofcopyof13fworkbook.xml
- https://www.sec.gov/edgar/browse/?CIK=920321

Identity analysis: `15670S105` is the canonical-era Cenveo security and is authoritatively typed as common stock. `15670S402` is a later common-equity identifier. `560321200` is legacy predecessor identity history from the Mail-Well lineage; incomplete binding of that pre-canonical identifier does not create legal-type ambiguity for the 2007 decision-period security. No common-to-non-common transition is established during the canonical interval.

Contradiction search: no SEC evidence identifies the decision-period Cenveo security as preferred, warrant/right, unit, trust interest, or another non-common instrument.

## Changes from base

| ticker | base | cleanup |
|---|---|---|
| LB | unresolved | common |
| SYCRF | unresolved | common |
| NCV-PA | unresolved | non_common |
| ACR-PC | unresolved | non_common |
| BTTGY | unresolved | common |
| VNTRQ | unresolved | common |
| CVOVQ | unresolved | common |

## Remaining unresolved

**None.**

## Validation

- exactly seven requested P3 cases reviewed
- zero other securities reviewed or modified
- fresh authoritative external evidence recorded for every case
- multi-CUSIP identity continuity treated separately from factual legal security type
- `outcome_information_used=false` for every case
- no replay or backtest run
- only the requested cleanup JSON and Markdown files created
