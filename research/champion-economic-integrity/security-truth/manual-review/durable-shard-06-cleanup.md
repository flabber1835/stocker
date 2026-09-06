# Durable shard 06 security-type cleanup

Date: 2026-09-06  
Base: `f627124da1eab25ff56dc521a093d504572c89a9`  
Branch: `research/champion-security-truth-durable-06-cleanup`

## Scope and contract

Reviewed exactly these eight unresolved cases from durable shard 06: `HOKUQ`, `FLNA`, `TT2`, `PSIG`, `OSI2`, `MITI1`, `WEST2`, `NEUP`.

Applied `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`. The review determines factual historical legal security type for each canonical decision interval. Later authoritative evidence may establish an earlier factual type. No return, price, rank, Champion-selection, survival, profitability, strategy-outcome, or future-index-membership information was used. `outcome_information_used=false` for every case.

The identity rule was applied explicitly: stale or misbound CUSIPs and issuer/name transitions were retained as identity-chain anomalies when authoritative evidence independently established the decision-period legal type.

## Results

| Ticker | Security ID | Canonical interval | CUSIPs | Final decision | Legal security type |
|---|---:|---|---|---|---|
| HOKUQ | 210189795761413012 | 2007-01-23 — 2008-01-31 | 434711107, 434712105 | common | COMMON_STOCK |
| FLNA | 280302887364922861 | 2019-12-27 — 2025-10-20 | 14817C107, 69562K100, 69562K506 | common | COMMON_STOCK |
| TT2 | 487869582447266471 | 2006-07-05 — 2008-06-05 | 892893108, 029712106 | common | COMMON_STOCK |
| PSIG | 597464188108207633 | 2024-08-12 — 2026-06-29 | G0R45S109, G7308J105, G7308J113 | common | ORDINARY_SHARES |
| OSI2 | 694575590377385878 | 2006-07-05 — 2007-06-13 | 689899102, 67104A101 | common | COMMON_STOCK |
| MITI1 | 884241433752390727 | 2012-01-26 — 2012-03-07 | 59509C105, 13738Y107 | common | COMMON_STOCK |
| WEST2 | 910334444152931164 | 2008-01-03 — 2008-02-06 | 009720103, 96040V101, 033355108 | common | COMMON_STOCK |
| NEUP | 942564779172582485 | 2023-09-28 — 2025-10-27 | 64136E102, 09063M205, Q1521J108 | common | ADS_ON_ORDINARY_SHARES_THEN_COMMON_STOCK |

## Case findings

### HOKUQ

**Evidence URLs**
- https://www.dtcc.com/globals/pdfs/2010/march/25/otc057
- https://investor.bankofamerica.com/regulatory-and-other-filings/all-sec-filings/content/0000728612-08-000104/0000728612-08-000104.pdf

The decision-period Hoku Scientific security, CUSIP `434712105`, is identified as common stock. DTCC later records a 2010 reorganization deleting that identifier and adding Hoku Corporation CUSIP `434711107` as common stock. The later CUSIP is outside the canonical interval and is an identity-timing anomaly, not legal-class uncertainty.

Contradiction search covered preferred/preference, warrant, right, unit, trust, and partnership terms for the issuer and both CUSIPs. No authoritative contrary class was found. `outcome_information_used=false`. Unresolved reason: none.

### FLNA

**Evidence URLs**
- https://www.sec.gov/Archives/edgar/data/1965621/000196562124000001/xslSCHEDULE_13G_X01/primary_doc.xml
- https://www.sec.gov/Archives/edgar/data/1069530/000106953020000009/sava-20191231x10k.htm
- https://www.sec.gov/Archives/edgar/data/1069530/000119312508031707/dsc13ga.htm

SEC evidence identifies Cassava Sciences CUSIP `14817C107` as common stock and establishes that Pain Therapeutics changed its corporate name to Cassava Sciences on March 26, 2019, before the canonical interval. Earlier SEC evidence identifies Pain Therapeutics CUSIP `69562K100` as common stock. The `69562K` identifiers are predecessor-history entries; the 2019-2025 decision-period issuer is Cassava Sciences.

Contradiction search covered preferred/preference, warrant, right, unit, trust, and partnership classes. No authoritative non-common tracked class was found. `outcome_information_used=false`. Unresolved reason: none.

### TT2

**Evidence URLs**
- https://www.sec.gov/Archives/edgar/data/836102/000119312507190610/ddef14a.htm
- https://www.sec.gov/Archives/edgar/data/919859/000091985904000002/filedec.pdf
- https://www.sec.gov/Archives/edgar/data/1358253/000135825308000006/tigadvisors.pdf

SEC filings identify American Standard Companies CUSIP `029712106` as common stock. The company's 2007 proxy documents the certificate amendment changing its name from American Standard Companies Inc. to Trane Inc. SEC filings identify Trane CUSIP `892893108` as common stock. The name/CUSIP transition preserves common-stock legal type across the canonical interval.

Contradiction search found no preferred, warrant, right, unit, trust, or partnership class for the tracked security. `outcome_information_used=false`. Unresolved reason: none.

### PSIG

**Evidence URLs**
- https://www.sec.gov/Archives/edgar/data/1882963/000121390022004464/ea154663-13daib_aibacquisit.htm
- https://nasdaqtrader.com/TraderNews.aspx?id=ECA2025-554
- https://www.sec.gov/Archives/edgar/data/1997201/000121390026041310/xslSCHEDULE_13G_X02/primary_doc.xml

SEC evidence identifies predecessor AIB Acquisition Corp. CUSIP `G0R45S109` as Class A Ordinary Shares. Nasdaq identifies PS International Group's PSIG security as Ordinary Shares and documents the October 13, 2025 reverse split/par-value change that changed the CUSIP to `G7308J113`. SEC Schedule 13G evidence identifies `G7308J113` as PS International Group Ordinary Shares. The `G7308J105` to `G7308J113` sequence is an ordinary-share episode; `G0R45S109` is predecessor identity history.

Contradiction searches included preferred/preference shares, warrants, rights, units, trusts, and partnership interests. SPAC-related instruments existed generally, but no non-common class was tied to the canonical PSIG tracked security. `outcome_information_used=false`. Unresolved reason: none.

### OSI2

**Evidence URLs**
- https://www.sec.gov/Archives/edgar/data/19617/000001961706000185/outb1230b.htm
- https://investor.bankofamerica.com/regulatory-and-other-filings/all-sec-filings/content/0000070858-06-000192/0000070858-06-000192.pdf

SEC evidence identifies Outback Steakhouse CUSIP `689899102` as common stock. SEC-filed holdings evidence identifies OSI Restaurant Partners CUSIP `67104A101` as common stock. The queue carries identifiers from the corporate identity sequence, while both authoritative class descriptions establish ordinary corporate common equity.

Contradiction search found no authoritative preferred, warrant, right, unit, trust, or partnership class for the tracked security. `outcome_information_used=false`. Unresolved reason: none.

### MITI1

**Evidence URLs**
- https://www.sec.gov/Archives/edgar/data/1131907/000119312512035384/d290549dsc14d9.htm
- https://www.sec.gov/Archives/edgar/data/1131907/000119312510040932/dsc13da.htm

SEC evidence ties both CUSIP `59509C105` and predecessor CUSIP `13738Y107` to Micromet, Inc. Common Stock, $0.00004 par value. The CUSIP transition did not change legal type.

Contradiction search found no contrary preferred, warrant, right, unit, trust, or partnership class for the tracked shares. `outcome_information_used=false`. Unresolved reason: none.

### WEST2

**Evidence URLs**
- https://www.dtcc.com/globals/pdfs/2010/july/23/otc140
- https://www.sec.gov/Archives/edgar/data/1560894/000121390012005806/sc13g1012brio_westinghouse.htm
- https://www.dtcc.com/-/media/Files/pdf/2013/9/27/OTC-187.pdf

DTCC identifies CUSIP `009720103` as Akeena Solar, Inc. common stock. SEC evidence identifies successor Westinghouse Solar CUSIP `96040V101` as common stock, and DTCC later records successor Andalay Solar CUSIP `033355108` as common stock. The canonical 2008 interval uses the Akeena identifier; the later identifiers are identity-chain history. All three legal-class records are common stock.

Contradiction search found no authoritative non-common tracked class. `outcome_information_used=false`. Unresolved reason: none.

### NEUP

**Evidence URLs**
- https://www.sec.gov/Archives/edgar/data/1191935/000121465924002864/j111243sc13ga1.htm
- https://depositaryreceipts.citi.com/adr/common/file.aspx?idf=6825
- https://depositaryreceipts.citi.com/adr/notices/previewPdf.aspx?caId=2630
- https://depositaryreceipts.citi.com/adr/common/file.aspx?idf=6857
- https://www.sec.gov/Archives/edgar/data/1191070/000110465926087379/xslSCHEDULE_13G_X02/primary_doc.xml

SEC and Citi depositary evidence establish that Bionomics CUSIP `09063M205` was an ADS representing ordinary shares. Citi records the December 2024 exchange/termination into Neuphoria Therapeutics common stock CUSIP `64136E102`, and SEC evidence identifies that successor security as Common Stock. The legal form changes from an ADS on ordinary shares to direct common stock; both are `common` under the review policy. `Q1521J108` remains an identity-chain anomaly and is not needed to infer the legal type.

Contradiction search covered preferred/preference ADSs, warrants, rights, units, trusts, and partnership interests. No contrary legal class was established for the tracked security. `outcome_information_used=false`. Unresolved reason: none.

## Summary

- Resolved common: **8**
- Resolved non_common: **0**
- Split: **0**
- Unresolved: **0**
- Unresolved names: **none**
- Outcome information used: **false**

Classification changes from the prior durable-shard-06 review: `HOKUQ`, `FLNA`, `TT2`, `PSIG`, `OSI2`, `MITI1`, `WEST2`, and `NEUP` each change from `unresolved` to `common`.

Classification changes from the original queue hypothesis: **none**. All eight queue hypotheses were `common`.

No replay or backtest was run.
