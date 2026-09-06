# Durable-ranked factual security-type review — shard 08

Date: 2026-09-06

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-durable-08`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

## Assignment

Reproduced exactly: filter `priority == P1_DURABLE_RANKED`; sort ascending by `(security_id as integer, ticker)`; assign zero-based `i`; retain `i % 10 == 8`.

Filtered rows: **442**. Assigned cases: **44**.

```text
8,18397188588917778,EQX
18,46705815074361203,SUN1
28,67573316626643986,BEAT1
38,112676300749674495,HMA1
48,157059211001311018,SA
58,187908770424317700,CEIN
68,213870456264344634,ACB
78,241154412158535428,AHPIQ
88,268270329065354602,MOVE1
98,284182997170685166,DFNS
108,305472410938548937,ITG1
118,337104369204997227,CPSL1
128,351896728434615816,MRINQ
138,368784581101499417,CAL1
148,404258436948279053,VTS1
158,414649767280734725,TW2
168,440725349157863081,QVCAQ
178,474205453544151570,YI
188,490068856428274586,PARAA
198,522562646919463671,QTT
208,556939594331583684,SII
218,576774468891329877,YELLQ
228,604275120822169397,ZG
238,619805285480648547,CDSCY
248,649261350427076980,JASO
258,673465785464250804,OCFT
268,696702663051800713,ADCT1
278,716118408840229184,ACORQ
288,748865578216434536,NYX1
298,778984265287479911,CYTOF
308,816141212186568365,LOGI
318,836772800751594867,OTRKQ
328,867730713416103703,EGO
338,888929808926387396,TRVG
348,918585837638518709,BZ2
358,944511016703721079,LLFLQ
368,968166522535685044,LFGRQ
378,997238311327022227,QMMM
388,1032449844265145568,APWR1
398,1050071176586409042,NMM
408,1083144803974890129,SDEV
418,1104896316141077892,DDAIF
428,1129027503593469049,TSEOF
438,1144505983159245450,AUQ
```

## Results

- common: **43**
- non_common: **1**
- split: **0**
- unresolved: **0**

Classification change: **NMM (`1050071176586409042`) changes from `common` to `non_common`.** SEC filings identify both old and successor CUSIPs as common units representing limited partner interests. Partnership units are `non_common` under the governing policy.

No factual legal-type transitions requiring interval splits were found. CUSIP, ticker, issuer-name, depositary-ratio, redomiciliation, merger, and reverse-split changes were treated as identity transitions where the legal class remained unchanged.

## Case ledger

| security_id | ticker | canonical interval | decision | legal security type |
|---:|---|---|---|---|
| 18397188588917778 | EQX | 2020-04-24–2026-07-31 | common | `COMMON_SHARES` |
| 46705815074361203 | SUN1 | 2006-07-05–2012-10-03 | common | `COMMON_STOCK` |
| 67573316626643986 | BEAT1 | 2009-05-01–2021-02-08 | common | `COMMON_STOCK` |
| 112676300749674495 | HMA1 | 2006-07-05–2014-01-24 | common | `CLASS_A_COMMON_STOCK` |
| 157059211001311018 | SA | 2010-05-20–2026-07-10 | common | `COMMON_SHARES` |
| 187908770424317700 | CEIN | 2011-03-09–2022-04-20 | common | `COMMON_STOCK` |
| 213870456264344634 | ACB | 2017-11-30–2025-03-05 | common | `COMMON_SHARES` |
| 241154412158535428 | AHPIQ | 2020-02-28–2021-12-21 | common | `COMMON_STOCK` |
| 268270329065354602 | MOVE1 | 2014-09-30–2014-11-13 | common | `COMMON_STOCK` |
| 284182997170685166 | DFNS | 2024-12-17–2026-07-31 | common | `ORDINARY_THEN_COMMON_SHARES` |
| 305472410938548937 | ITG1 | 2006-07-05–2019-01-16 | common | `COMMON_STOCK` |
| 337104369204997227 | CPSL1 | 2007-09-25–2008-06-18 | common | `COMMON_STOCK` |
| 351896728434615816 | MRINQ | 2018-12-24–2022-01-13 | common | `COMMON_STOCK` |
| 368784581101499417 | CAL1 | 2006-07-05–2010-09-30 | common | `CLASS_B_COMMON_STOCK` |
| 404258436948279053 | VTS1 | 2006-07-05–2007-01-11 | common | `COMMON_STOCK` |
| 414649767280734725 | TW2 | 2007-08-16–2016-01-04 | common | `COMMON_STOCK` |
| 440725349157863081 | QVCAQ | 2006-11-07–2023-03-01 | common | `SERIES_A_COMMON_STOCK` |
| 474205453544151570 | YI | 2021-02-11–2021-03-18 | common | `ADS_REPRESENTING_CLASS_A_ORDINARY_SHARES` |
| 490068856428274586 | PARAA | 2021-03-23–2021-04-26 | common | `CLASS_A_COMMON_STOCK` |
| 522562646919463671 | QTT | 2019-03-19–2021-03-22 | common | `ADS_REPRESENTING_CLASS_A_ORDINARY_SHARES` |
| 556939594331583684 | SII | 2025-01-06–2026-07-23 | common | `COMMON_SHARES` |
| 576774468891329877 | YELLQ | 2006-07-05–2023-08-15 | common | `COMMON_STOCK` |
| 604275120822169397 | ZG | 2012-05-07–2026-07-31 | common | `CLASS_A_COMMON_STOCK` |
| 619805285480648547 | CDSCY | 2006-07-14–2010-02-26 | common | `ADR_REPRESENTING_ORDINARY_SHARES` |
| 649261350427076980 | JASO | 2007-08-08–2015-06-12 | common | `ADS_REPRESENTING_ORDINARY_SHARES` |
| 673465785464250804 | OCFT | 2020-08-13–2021-07-09 | common | `ADS_REPRESENTING_ORDINARY_SHARES` |
| 696702663051800713 | ADCT1 | 2006-07-05–2010-09-15 | common | `COMMON_STOCK` |
| 716118408840229184 | ACORQ | 2006-09-26–2018-10-05 | common | `COMMON_STOCK` |
| 748865578216434536 | NYX1 | 2006-09-06–2013-11-12 | common | `COMMON_STOCK` |
| 778984265287479911 | CYTOF | 2020-12-01–2021-11-23 | common | `COMMON_SHARES` |
| 816141212186568365 | LOGI | 2007-01-23–2026-07-31 | common | `COMMON_SHARES` |
| 836772800751594867 | OTRKQ | 2020-08-06–2021-11-18 | common | `COMMON_STOCK` |
| 867730713416103703 | EGO | 2008-07-17–2026-07-31 | common | `COMMON_SHARES` |
| 888929808926387396 | TRVG | 2017-06-27–2021-03-26 | common | `ADS_REPRESENTING_CLASS_A_SHARES` |
| 918585837638518709 | BZ2 | 2010-03-19–2013-10-24 | common | `COMMON_STOCK` |
| 944511016703721079 | LLFLQ | 2011-07-13–2020-11-30 | common | `COMMON_STOCK` |
| 968166522535685044 | LFGRQ | 2006-07-26–2008-05-06 | common | `COMMON_STOCK` |
| 997238311327022227 | QMMM | 2025-09-09–2025-09-26 | common | `ORDINARY_SHARES` |
| 1032449844265145568 | APWR1 | 2008-06-20–2010-04-08 | common | `COMMON_STOCK` |
| 1050071176586409042 | NMM | 2021-05-05–2021-06-03 | non_common | `LIMITED_PARTNERSHIP_COMMON_UNITS` |
| 1083144803974890129 | SDEV | 2025-08-27–2026-01-28 | common | `COMMON_STOCK` |
| 1104896316141077892 | DDAIF | 2006-07-05–2010-06-11 | common | `REGISTERED_ORDINARY_SHARES_AND_ADR_REPRESENTING_ORDINARY_SHARES` |
| 1129027503593469049 | TSEOF | 2016-03-22–2022-04-29 | common | `ORDINARY_SHARES` |
| 1144505983159245450 | AUQ | 2009-11-16–2015-01-20 | common | `COMMON_SHARES` |

## Identity and contradiction review

Primary SEC, issuer, exchange, depositary, and DTCC records were used to bind legal class to the canonical identities. Notable lineage anomalies include CEIN/Camber Energy, CDSCY/Cadbury Schweppes ADR, CYTOF/Auris Medical–Altamira, and SDEV/NovaBay. These are identity-lineage effects and do not establish type transitions.

DFNS corporate-action evidence separates the ordinary/common share lineage from SPAC warrants, units, and rights. DDAIF records bind Daimler registered shares and ADR identifiers to ordinary/common equity. NMM records bind both CUSIPs to limited-partnership common units.

Contradiction searches found no evidence requiring an unresolved designation for the 43 common cases. NMM's partnership status is affirmative primary-source evidence for `non_common`.

## Unresolved worklist

None.

## Validation

- assignment formula reproduced: **true**
- every assigned case exactly once: **true**
- foreign cases: **0**
- all resolved cases evidence-backed: **true**
- outcome information used: **false**
- JSON SHA-256: `916fbb2fefb322243ace6ad6ff468a63e0e52bc6adf013f4431c8ec23504aca7`

Detailed CUSIPs, primary evidence URLs, effective intervals, factual findings, identity-transition analysis, contradiction search, and per-case review status are retained in `durable-shard-08.json`.
