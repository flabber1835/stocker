# Durable shard 07 cleanup — factual security type

Base: `a852f1bb7c424e3dcc720a0b84e52f9863464f53`

Branch: `research/champion-security-truth-durable-07-cleanup`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

## Scope

Exactly three previously unresolved durable-shard-07 cases were reviewed:

| security_id | ticker | canonical interval |
|---:|---|---|
| 64207844585346273 | ROSEQ | 2010-11-10 / 2015-06-12 |
| 517535898370665174 | ZNB | 2009-07-30 / 2025-10-15 |
| 1082808592473316903 | NIKI | 2024-03-06 / 2025-08-25 |

No replay or backtest was run. `outcome_information_used=false` for every case.

## Decisions

| ticker | decision | factual legal type | identity/CUSIP conclusion |
|---|---|---|---|
| ROSEQ | **common** | Rosetta Resources Inc. common stock | Retained CUSIPs belong to the later KLR/Rosehill chain; canonical ROSE identity is Rosetta Resources, CUSIP 777779307. |
| ZNB | **common** | Common stock, later ordinary/Class A ordinary shares | Corporate-action chain remains eligible common/ordinary equity. Retained chain contains identity noise, including post-canonical CUSIP G2287A142. |
| NIKI | **common** | Aptorum Group Class A Ordinary Shares | All three retained CUSIPs bind to Aptorum Class A ordinary equity; terminal NIKI label is later identity metadata. |

Counts: **3 common, 0 non_common, 0 split, 0 unresolved**.

## ROSEQ — 64207844585346273

**Canonical interval:** 2010-11-10 through 2015-06-12  
**Recorded CUSIPs:** `777385105`, `49877M108`, `49877M207`, `777385204`  
**Decision:** `common`  
**Legal type:** common stock

### Primary-source evidence

- SEC Form 13F information tables identify **Rosetta Resources Inc.** as common stock under CUSIP **777779307** during the canonical era:
  - https://www.sec.gov/Archives/edgar/data/80255/000008025513000607/xslForm13F_X01/infotable.xml
  - https://www.sec.gov/Archives/edgar/data/887793/000093041315002304/xslForm13F_X01/infotable.xml
- KLR Energy Acquisition Corp. SEC Schedule 13G identifies CUSIP **49877M207** as **units**, each containing one Class A common share and one warrant:
  - https://www.sec.gov/Archives/edgar/data/1659122/000119312516509490/d165652dsc13g.htm
- Later Rosehill Resources SEC filings identify CUSIPs **777385105** and **49877M108** as Class A common stock:
  - https://www.sec.gov/Archives/edgar/data/1659122/000106299317003396/sched13d.htm
  - https://www.sec.gov/Archives/edgar/data/1300714/000090514818000787/efc18-580_sc13da.htm

### Identity analysis

The canonical 2010-2015 ROSE episode is **Rosetta Resources Inc., CUSIP 777779307**. The recorded ROSEQ CUSIPs are from the later KLR Energy Acquisition Corp./Rosehill Resources episode. KLR's unit CUSIP and Rosehill's later Class A common-stock CUSIPs therefore describe a separate, post-canonical identity chain.

This is an identity/CUSIP-chain defect. It is not a factual security-type ambiguity for the canonical episode. Rosetta Resources is directly identified by SEC records as common stock.

### Contradiction search

The search found affirmative non-common evidence for **KLR CUSIP 49877M207**, which was a unit containing a common share and warrant. That evidence confirms the retained CUSIP contamination. No preferred, partnership unit, trust unit, warrant, right, fund or other non-common class was found bound to the actual Rosetta Resources ticker ROSE episode.

`outcome_information_used=false`

## ZNB — 517535898370665174

**Canonical interval:** 2009-07-30 through 2025-10-15  
**Recorded CUSIPs:** `G2287A100`, `G2287A209`, `169365202`, `G2287A126`, `G2287A134`, `G21225100`, `169365103`, `G4645B101`, `G2287A142`  
**Decision:** `common`  
**Legal type:** common stock, later ordinary/Class A ordinary shares

### Primary-source evidence

- China Advanced Construction Materials Group's SEC-filed issuer announcement states that its **common stock** underwent a 1-for-12 reverse split in 2013 and continued as common stock under new CUSIP **169365202**:
  - https://www.sec.gov/Archives/edgar/data/1392363/000106299313003733/exhibit99-1.htm
- Huitao Technology Form 6-K documents the China Advanced Construction Materials/Huitao identity transition:
  - https://www.sec.gov/Archives/edgar/data/1747661/000121390019012968/f6k071719_huitaotechnology.htm
- Color Star Technology Schedule 13G identifies CUSIP **G2287A100** as **Ordinary Shares**:
  - https://www.sec.gov/Archives/edgar/data/1747661/000121390020023211/ea125897-sc13gjie_colorstar.htm
- Color Star's SEC Form 6-K documents a reverse split of its **ordinary shares**, continuing under CUSIP **G2287A209**, and states that no preference shares were then issued and outstanding:
  - https://www.sec.gov/Archives/edgar/data/1747661/000121390022058149/ea166147-6k_colorstar.htm
- SEC Schedules 13G identify CUSIP **G2287A126** as **Class A Ordinary Shares**:
  - https://www.sec.gov/Archives/edgar/data/1747661/000121390025006702/xslSCHEDULE_13G_X01/primary_doc.xml
  - https://www.sec.gov/Archives/edgar/data/1747661/000161052025000059/xslSCHEDULE_13G_X01/primary_doc.xml
- Nasdaq Trader documents the August 2025 Color Star-to-Zeta Network Group name/symbol change and the Class A ordinary-share transition to CUSIP **G2287A134**:
  - https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-452
- An SEC Schedule 13G within the canonical interval identifies **Zeta Network Group Class A Ordinary Shares**, CUSIP **G2287A134**:
  - https://www.sec.gov/Archives/edgar/data/1491072/000119312525282316/xslSCHEDULE_13G_X01/primary_doc.xml
- A later SEC Schedule 13G identifies **G2287A142** as Zeta Class A Ordinary Shares, with a 2026 event date:
  - https://www.sec.gov/Archives/edgar/data/1747661/000107997326000321/xslSCHEDULE_13G_X02/primary_doc.xml

### Identity analysis

The record spans reincorporations, issuer/name changes, reverse splits and CUSIP changes from China Advanced Construction Materials through Huitao/Color Star to Zeta Network Group. The authoritative class evidence remains common stock, ordinary shares, or Class A ordinary shares throughout the canonical decision interval. All are `common` under the classification policy.

The retained nine-CUSIP chain has data-quality defects. **G2287A142 is post-canonical**, because SEC evidence dates that CUSIP to 2026 after the 2025-10-15 canonical endpoint. **G21225100** was not independently tied to a standalone primary-source class description in this cleanup. Those identifier defects do not change the factual legal type established by the issuer-transition and class evidence.

### Contradiction search

Searches tested for preferred shares, units, warrants, rights, trust/partnership interests and other non-common instruments. Color Star's 2022 SEC filing expressly describes the listed security as ordinary shares and says that no preference shares were then issued and outstanding. No authoritative source binds a non-common instrument to the canonical listed-equity episode.

`outcome_information_used=false`

## NIKI — 1082808592473316903

**Canonical interval:** 2024-03-06 through 2025-08-25  
**Recorded CUSIPs:** `G6096M106`, `G6096M122`, `G6096M114`  
**Decision:** `common`  
**Legal type:** Class A Ordinary Shares

### Primary-source evidence

- Aptorum Group SEC Schedule 13G/A identifies CUSIP **G6096M114** as **Class A Ordinary Shares**:
  - https://www.sec.gov/Archives/edgar/data/1393825/000139382524000013/apm13ga.htm
- Aptorum Group SEC Schedule 13G/A identifies CUSIP **G6096M106** as **Class A Ordinary Shares**:
  - https://www.sec.gov/Archives/edgar/data/1702202/000107997325000854/xslSCHEDULE_13G_X01/primary_doc.xml
- SEC Form 13F data identifies Aptorum Group equity under CUSIP **G6096M122** as common/Class A equity:
  - https://www.sec.gov/Archives/edgar/data/1851815/000185181526000001/xslForm13F_X02/13F-HR.xml
- Aptorum's issuer-hosted SEC Schedule 13G/A independently identifies CUSIP **G6096M106** as Class A Ordinary Shares:
  - https://ir.aptorumgroup.com/static-files/de160593-f672-4fad-a74a-3d774c32aa11

### Identity analysis

All three retained CUSIPs bind to Aptorum Group's Class A ordinary-share episode across CUSIP/reverse-split changes. The terminal `NIKI` label reflects a later issuer/name transition and is an identity-label artifact for the canonical 2024-2025 interval. It does not alter the legal type of the historical Aptorum security.

### Contradiction search

Aptorum filings mention warrants issued in financings, but they expressly distinguish those warrants from the Class A Ordinary Shares and describe the warrants as exercisable into that share class. No preferred share, unit, trust/partnership interest, right, fund or other non-common class was found bound to the reviewed CUSIPs.

`outcome_information_used=false`

## Closure

All three durable-shard-07 cleanup cases are resolved:

- `ROSEQ` → `common`
- `ZNB` → `common`
- `NIKI` → `common`

Remaining unresolved names: **none**.
