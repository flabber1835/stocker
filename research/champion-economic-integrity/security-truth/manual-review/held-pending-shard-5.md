# Held/pending factual security-type review — shard 5

Date: 2026-09-06

Branch: `research/champion-security-truth-shard-5`

Parent branch/head at shard creation: `research/champion-certification-economic-integrity` @ `428721fd4a7494df477c2c9cd3d94ded1c1f5d37`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

Canonical inventory: `research/champion-economic-integrity/security-truth/audit-v2/34051269919-1/audit/all-held-or-pending-type-cases-v2.csv`

## Result

- Exact assigned coverage: **14/14**
- `common`: **12**
- `non_common`: **0**
- `unresolved`: **2**
- Candidate `common` changed to `non_common`: **none**
- Candidate `common` held unresolved for canonical identity defects: **UNTCQ, VTNRQ**
- Outcome information used: **false**
- JSON SHA-256: `d2c5d37752fae151ce9354706bb04332e982a337f29ef9ef8b65742ae0160c4a`

## Case table

| Ticker | security_id | Canonical CUSIP(s) | Canonical interval | Decision | Legal security type | Review status |
|---|---:|---|---|---|---|---|
| UNTCQ | 1025975490253483719 | 909218109 / 909218208 | 2006-07-05 → 2016-12-28 | unresolved | COMMON_STOCK | UNRESOLVED_CANONICAL_CUSIP_IDENTITY |
| GPRO1 | 803323372359949049 | 36866T103 | 2006-08-01 → 2012-07-31 | common | COMMON_STOCK | RESOLVED |
| STEC1 | 304762952062850296 | 784774101 / 828820100 / 828823104 | 2009-05-20 → 2011-08-26 | common | COMMON_STOCK | RESOLVED |
| PCXCQ | 229177174933045805 | 70336T104 / 70336T500 | 2008-05-05 → 2012-07-06 | common | COMMON_STOCK | RESOLVED |
| ADPTQ | 985915492195814773 | 006855100 | 2015-06-25 → 2016-11-30 | common | CLASS_A_COMMON_STOCK | RESOLVED |
| HMY | 794026657301614010 | 413216300 | 2006-07-05 → 2026-07-31 | common | ADR_ADS_REPRESENTING_ORDINARY_COMMON_SHARES | RESOLVED |
| SICPQ | 327333102048036914 | 82837P408 | 2020-12-14 → 2023-04-19 | common | CLASS_A_COMMON_STOCK | RESOLVED |
| HMIN | 558144031790701315 | 43713W107 / 43742E102 | 2007-06-07 → 2016-03-30 | common | ADS_REPRESENTING_ORDINARY_SHARES | RESOLVED |
| NBEVQ | 481857333199692347 | 64157V108 / 650194103 / 024718108 | 2018-09-19 → 2019-05-22 | common | COMMON_STOCK | RESOLVED |
| ATHN1 | 275516769506070811 | 04685W103 | 2009-01-28 → 2019-02-11 | common | COMMON_STOCK | RESOLVED |
| ALO1 | 36666266239592614 | 020813101 | 2006-12-13 → 2008-12-26 | common | CLASS_A_COMMON_STOCK | RESOLVED |
| SWI1 | 175647085019960977 | 83416B109 | 2009-11-17 → 2016-02-04 | common | COMMON_STOCK | RESOLVED |
| GLDN1 | 117268708159146582 | 38122G107 | 2007-06-18 → 2008-02-28 | common | COMMON_STOCK | RESOLVED |
| VTNRQ | 895182212221004918 | 92534K107 / 92861H107 / 981517105 | 2021-05-27 → 2023-04-25 | unresolved | COMMON_STOCK | UNRESOLVED_CANONICAL_CUSIP_IDENTITY |

## Findings

### UNTCQ — unresolved

Unit Corporation common stock is directly identified as CUSIP `909218109` in SEC filings. Unit Corporation's Form 8937 identifies the old Unit stock as `909218109` and the post-2020 stock as `909218406`/`909218505`. The canonical row also contains `909218208`; no authoritative Unit Corporation binding for that CUSIP was found. The legal type of the bound target security is common stock, but the task requires every canonical CUSIP to be bound, so this case remains unresolved.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1265376/000119312504187815/dsc13ga.htm
- https://www.sec.gov/Archives/edgar/data/798949/000125889720001384/dfs637.htm
- https://unitcorp.com/wp-content/uploads/2021/04/UnitForm8937Final.pdf

Contradiction search: authoritative issuer/SEC identity history does not reconcile `909218208` to Unit Corporation.

### GPRO1 — common

Gen-Probe Incorporated CUSIP `36866T103` is explicitly identified as common stock in SEC Schedule 13G filings. No contrary class evidence was found.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/820237/000119312512026965/d290491dsc13ga.htm
- https://www.sec.gov/Archives/edgar/data/820237/000126967811000109/genprobe13g.htm

### STEC1 — common

STEC, Inc. CUSIP `784774101` is explicitly common stock. The canonical identity chain also includes predecessor SimpleTech identifiers `828820100` and `828823104`; historical identifier/holdings records bind those to the same predecessor common-equity lineage. No preferred, unit, warrant, or trust conversion was found.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1135730/000091957410002100/d1077311_13g-a.htm
- https://www.sec.gov/Archives/edgar/data/93751/000095012313005634/xslForm13F_X01/form13fInfoTable.xml
- https://www.fidelity.com/products/stocksbonds/content/previous.html
- https://investor.bankofamerica.com/regulatory-and-other-filings/subsidiary-and-country-disclosures/merrill-lynch-all-sec-filings/content/0000728612-04-000045/0000728612-04-000045.pdf

### PCXCQ — common

Patriot Coal CUSIP `70336T104` is identified as common stock, and successor CUSIP `70336T500` is also identified as common. The restructuring/CUSIP transition does not evidence a class change.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1360710/000114420413060383/xslForm13F_X01/infotable.xml
- https://www.sec.gov/Archives/edgar/data/902367/000114420415045872/xslForm13F_X01/infotable.xml

### ADPTQ — common

Adeptus Health Inc. CUSIP `006855100` is Class A common stock in SEC filings. No class change was found during the canonical interval.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1602367/000089914016001309/a032116a.htm
- https://www.sec.gov/Archives/edgar/data/102909/000093247116010654/adeptushealthinc.htm

### HMY — common

Harmony Gold CUSIP `413216300` is an ADR/ADS program representing ordinary shares. The issuer states that one ADR represents one ordinary share. Under existing Champion semantics, ADR/ADS on ordinary/common equity is `common`.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/869178/000086917815000010/schedule13g.htm
- https://www.sec.gov/Archives/edgar/data/1023514/000119312522248671/d374135dsc13g.htm
- https://www.harmony.co.za/investors/share-information/adr-faqs/

### SICPQ — common

Silvergate Capital CUSIP `82837P408` is Class A common stock in filings before and during 2023. The Q-suffix/ticker-status transition does not change the legal security class.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1312109/000119312520110631/d917645dsc13g.htm
- https://www.sec.gov/Archives/edgar/data/1353254/000089534521000522/ff-287910_13g-silvergate.htm
- https://www.sec.gov/Archives/edgar/data/1312109/000095010323002158/dp188680_sc13ga-1blumer.htm

### HMIN — common

Both Home Inns CUSIPs are explicitly ADSs representing ordinary shares: `43713W107` and successor `43742E102`. The identifier changed; the underlying ordinary-share class did not.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1376972/000072888914000760/homeinnhotels.htm
- https://www.sec.gov/Archives/edgar/data/1376972/000072888915000757/homeinnshotels.htm

### NBEVQ — common

The target-period New Age Beverages CUSIP `64157V108` is common stock. Later NewAge CUSIP `650194103` is also common stock. DTCC binds predecessor American Brewing to CUSIP `024718108`. No evidence of a security-class conversion was found across the predecessor/name-change/successor chain.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1484021/000149315217004953/sch13g.htm
- https://www.sec.gov/Archives/edgar/data/1425930/000121390020036399/xslForm13F_X01/infotable.xml
- https://www.dtcc.com/globals/pdfs/2014/july/21/otc-138

### ATHN1 — common

athenahealth, Inc. CUSIP `04685W103` is explicitly common stock. No class transition was found.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1131096/000093247117000912/athenahealthinc.htm

### ALO1 — common

Alpharma Inc. CUSIP `020813101` is Class A common stock in SEC transaction filings covering the end of the canonical episode.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/730469/000095012308011426/y00194sc14d9.htm
- https://www.sec.gov/Archives/edgar/data/0000730469/000080724908000307/alo_00.htm

### SWI1 — common

SolarWinds, Inc. CUSIP `83416B109` is explicitly common stock. No contrary class evidence was found.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1061165/000090266411001395/p11-1527sc13g.htm

### GLDN1 — common

Golden Telecom, Inc. CUSIP `38122G107` is common stock in SEC filings spanning the reviewed episode. No class transition was found.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/1089874/000095013306005212/w27706sc13dza.htm
- https://www.sec.gov/Archives/edgar/data/0001089874/000119312508043935/dsc13e3a.htm

### VTNRQ — unresolved

Vertex Energy CUSIP `92534K107` is conclusively common stock. DTCC directly links predecessor World Waste Technologies CUSIP `981517105` to successor Vertex Energy CUSIP `92534K107`. Canonical CUSIP `92861H107` could not be bound to the Vertex/World Waste lineage using authoritative sources. The bound target-period security is common stock, but complete canonical CUSIP binding is unresolved.

Primary evidence:
- https://www.sec.gov/Archives/edgar/data/890447/000093583622000192/vertexenergy13ga.htm
- https://www.sec.gov/Archives/edgar/data/890447/000158069522000089/vtnr-13da_071222.htm
- https://www.dtcc.com/-/media/Files/pdf/2009/5/4/OTC084.pdf

Contradiction search: authoritative lineage evidence connects `981517105` directly to `92534K107`; no authoritative Vertex/World Waste binding for `92861H107` was found.

## Validation

The review contains exactly the 14 assigned tickers and no extras. Every resolved case has class evidence. Both unresolved cases identify the exact canonical CUSIP defect preventing full identity closure. Every case records `outcome_information_used=false`. No performance, return, ranking, portfolio, survival, index-membership, or strategy-outcome information was used for classification.
