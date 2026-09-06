# P0 Fresh Path Delta

Date: 2026-09-06

## Scope

- Base branch: `research/champion-security-truth-held-pending-integration`
- Base head: `5b9d9ea2e378044f49d217fe311b36b45c73124c`
- Working branch: `research/champion-security-truth-p0-fresh-delta`
- Fresh queue: `research/champion-economic-integrity/security-truth/audit-v2/34051269919-1/replay/controlled/fresh-path-open-review-queue.csv`
- Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`
- Economic replay run: **false**
- Outcome information used: **false**

## Result

| Metric | Count |
|---|---:|
| Fresh P0 held/pending rows | 84 |
| Prior integrated P0 cases | 83 |
| Unchanged fresh cases covered by retained factual evidence | 73 |
| New fresh cases requiring factual review | 11 |
| Dropped old-path P0 cases | 10 |
| Fresh P0 cases with full type coverage | 84 |
| Fresh common | 84 |
| Fresh non-common | 0 |
| Fresh unresolved type | 0 |
| Identity-hygiene-only cases | 5 |

Every fresh P0 row is covered by retained factual evidence or by the new adjudications below. No overlapping `security_id` had a fresh canonical interval/CUSIP change that invalidated the retained decision-period type closure.

## Fresh-only P0 cases

| Ticker | security_id | Canonical interval | CUSIP(s) | Classification | Type finding |
|---|---|---|---|---|---|
| ING | 752127607694153326 | 2006-10-17..2026-07-31 | 456837103 | common | ADS/ADR representing ordinary shares |
| COR2 | 1112840042710916617 | 2015-10-29..2021-12-27 | 21870Q105 | common | Common stock |
| MRK | 899932545079148879 | 2016-06-29..2016-07-01 | 58933Y105, 589331107 | common | Common stock; both aggregate identifiers are common |
| PIRRQ | 902973650148541485 | 2008-04-10..2017-05-11 | 720279108, 720279504 | common | Common stock; successor identifier preserves type |
| INFY | 598818893906299772 | 2006-07-05..2026-07-31 | 456788108 | common | Sponsored ADR on equity shares |
| SQM | 141650404222899262 | 2008-04-14..2026-07-31 | 833635105 | common | ADS representing Series B common stock |
| COF | 326864109633904206 | 2006-08-31..2006-09-14 | 14040H105 | common | Common stock |
| BPZRQ | 619188589572857157 | 2008-03-26..2008-10-14 | 055639108, 63934Q101, 63934Q309 | common | Decision-period BPZ security is common stock; aggregate identity contamination retained separately |
| KGC | 756342866994377362 | 2006-08-11..2026-07-31 | 496902404, 496902107, 496902206 | common | Common shares |
| JRCCQ | 53502595376597645 | 2008-03-10..2012-11-12 | 470355207 | common | Common stock |
| EAC1 | 549611630133257860 | 2007-01-26..2010-03-09 | 29255W100 | common | Common stock |

## New factual evidence

### ING — 752127607694153326

ING's issuer prospectus states that its NYSE ADSs represent ordinary shares. An SEC-filed 13F binds CUSIP `456837103` to ING Groep NV equity. Classification: `common`.

Evidence:
- https://www.ing.com/MediaEditPage/US456837AK90-US456837AM56-US456837AL73-Prospectus-Supplement-to-Prospectus-dated-September-18-2018.htm
- https://www.sec.gov/Archives/edgar/data/1464332/000146433220000002/xslForm13F_X01/13f3-31-20.xml

### COR2 — 1112840042710916617

CoreSite Realty Corporation's SEC Schedule 14D-9/A identifies CUSIP `21870Q105` as common stock. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/1490892/000110465921153784/tm2136323d1_sc14d9a.htm

### MRK — 899932545079148879

SEC-filed holdings identify `58933Y105` and predecessor `589331107` as Merck common stock. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/1014315/000114036126002617/xslForm13F_X02/informationtable.xml
- https://www.sec.gov/Archives/edgar/data/1608531/000160853119000001/xslForm13F_X01/inftable.xml

### PIRRQ — 902973650148541485

SEC-filed holdings identify decision-period CUSIP `720279108` as Pier 1 common stock and successor CUSIP `720279504` as common stock. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/1406585/000140658516000028/xslForm13F_X01/infoTable.xml
- https://www.sec.gov/Archives/edgar/data/1512024/000106299319003337/xslForm13F_X01/form13fInfoTable.xml

### INFY — 598818893906299772

SEC records bind CUSIP `456788108` to the Infosys sponsored ADR line and to issuer equity-share voting. Under the contract, an ADR/ADS representing ordinary corporate equity is `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/1054587/000119312526051460/xslForm13F_X02/50678.xml
- https://www.sec.gov/Archives/edgar/data/1584433/000005193123000838/dwgi_npx.htm

### SQM — 141650404222899262

Issuer filings state that SQM share capital contains Series A common stock and Series B common stock, and that each NYSE ADS represents one Series B common share. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/909037/000157587222000320/chm001_ex2-1.htm
- https://www.sec.gov/Archives/edgar/data/909037/000110465921041459/tm2110919d1_6k.htm

### COF — 326864109633904206

SEC Schedule 13G/A identifies Capital One Financial Corporation CUSIP `14040H105` as common stock. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/200217/000119312524256964/d793801dsc13ga.htm

### BPZRQ — 619188589572857157

SEC-filed holdings identify BPZ Resources CUSIP `055639108` as common stock. A separate SEC Schedule 13G proves aggregate CUSIP `63934Q101` belongs to unrelated Navidec, Inc. CUSIP `63934Q309` remains unbound in this review. The identity contamination does not alter the type of the authoritatively bound decision-period BPZ security. Classification: `common`. Identity hygiene: open.

Evidence:
- https://www.sec.gov/Archives/edgar/data/1081019/000108101913000013/xslForm13F_X01/13f_0913formatted.xml
- https://www.sec.gov/Archives/edgar/data/1012084/000093583601500101/nvdi13g.htm

### KGC — 756342866994377362

SEC Schedule 13G records identify Kinross Gold's listed equity as common shares/common stock under CUSIP `496902404`. No legal security-class transition was found across the canonical episode. Older aggregate identifiers remain identity history. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/701818/000086917819000086/schedule13g.htm
- https://www.sec.gov/Archives/edgar/data/701818/000205211325001414/xslSCHEDULE_13G_X01/primary_doc.xml

### JRCCQ — 53502595376597645

SEC-filed holdings identify James River Coal Company CUSIP `470355207` as common stock. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/80255/000008025513000607/xslForm13F_X01/infotable.xml

### EAC1 — 549611630133257860

SEC-filed holdings identify Encore Acquisition Co CUSIP `29255W100` as common stock. Classification: `common`.

Evidence:
- https://www.sec.gov/Archives/edgar/data/49205/000004920518000004/xslForm13F_X01/QTR32018_13F_HR.xml

## Dropped old-path P0 cases

| Ticker | security_id | Prior factual type |
|---|---|---|
| QIHU | 906755109876599247 | common |
| SHOP | 110098224381990417 | common |
| CCXI1 | 659896685009177378 | common |
| MMI1 | 430031587961498330 | common |
| SU | 345679706151556113 | common |
| GPRO1 | 803323372359949049 | common |
| NBEVQ | 481857333199692347 | common |
| KNX1 | 450783074872735055 | common |
| GOLLQ | 223489731780916334 | non_common |
| CIG | 572943415348500978 | non_common |

These names are absent from the fresh P0 path and require no fresh-path re-adjudication.

## Previously unresolved, now type-closed

The completed integration already converted the five shard first-pass unresolved cases into decision-period type closures:

- FMX `63371714929571534` — `common`
- HCR1 `718098875444344211` — `common`
- THOR1 `852684403524489499` — `common`
- UNTCQ `1025975490253483719` — `common`
- VTNRQ `895182212221004918` — `common`

HCR1, THOR1, UNTCQ, and VTNRQ retain identity-hygiene follow-up only. FMX's first-pass issue was the bundled-ADS policy structure and is closed for type.

## Identity-hygiene-only inventory

Five fresh P0 cases are type-closed while retaining identity metadata follow-up:

- HCR1 `718098875444344211`
- THOR1 `852684403524489499`
- UNTCQ `1025975490253483719`
- VTNRQ `895182212221004918`
- BPZRQ `619188589572857157`

No identity-hygiene item forces `unresolved` because the decision-period security itself is authoritatively bound to an unambiguous common-equity class.

## Validation

`73 retained-supported + 11 newly adjudicated = 84 fresh P0 rows`.

- Full fresh P0 type coverage: **84 / 84**
- Common: **84**
- Non-common: **0**
- Unresolved type: **0**
- Invalidated prior closures: **0**
- Outcome information used: **false**
- Economic replay run: **false**

Machine-readable result SHA-256:

`2b611325c48b6f08f4adabb90f2eb26e7e15b968ba016522f2a1a69aa1de00e6`  `p0-fresh-path-delta.json`
