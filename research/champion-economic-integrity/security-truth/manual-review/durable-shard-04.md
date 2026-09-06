# Durable security-truth review — shard 04

## Scope and assignment

Base SHA: `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Review branch: `research/champion-security-truth-durable-04`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

Queue: `research/champion-economic-integrity/security-truth/audit-v2/34051269919-1/replay/controlled/fresh-path-open-review-queue.csv`

Assignment assertions reproduced before research:

- filter: `priority == P1_DURABLE_RANKED`
- sort: `(security_id as integer, ticker)` ascending
- indexing: zero-based
- filtered P1 count: **442**
- shard predicate: `i % 10 == 4`
- assigned count: **44**
- assigned indices: `4,14,24,...,434`

| i | security_id | ticker |
|---:|---:|---|
| 4 | 7654535568111663 | QUCY |
| 14 | 35648591532554242 | GSIW |
| 24 | 57164568713095417 | DMKPQ |
| 34 | 103118562012262941 | GMXRQ |
| 44 | 153133684265451089 | HEROQ |
| 54 | 177331179426033273 | X |
| 64 | 203648306270562714 | VOD |
| 74 | 226304402817445814 | GTE |
| 84 | 254714768819945876 | CBDBY |
| 94 | 278777860356753160 | DXTRQ |
| 104 | 293425155284498872 | RGSEQ |
| 114 | 324099600050715051 | OSG1 |
| 124 | 342547763356080649 | VRAYQ |
| 134 | 360577262931860442 | GPLDF |
| 144 | 389698694766158960 | TFII |
| 154 | 410442889828988458 | LUMN |
| 164 | 429771193252933866 | WPGGQ |
| 174 | 461686511677193081 | QSI |
| 184 | 482282576872746124 | PL1 |
| 194 | 500990921491854993 | CNR2 |
| 204 | 550959200502870769 | YVRLF |
| 214 | 572436205509811668 | PHG |
| 224 | 595797892257193253 | FRCB |
| 234 | 615127660198584874 | GFASY |
| 244 | 643299980994811152 | DSHK |
| 254 | 659537267342817477 | DPTRQ |
| 264 | 682451706837485270 | AROC |
| 274 | 703395824663586593 | DNN |
| 284 | 729518976069560821 | WKEY |
| 294 | 764180993476052960 | CSUNY |
| 304 | 801493210686105331 | NKLAQ |
| 314 | 823234404046056619 | XL1 |
| 324 | 847737169274061170 | VEDL |
| 334 | 881385647571236858 | ORIO |
| 344 | 908793440963430061 | ACIIQ |
| 354 | 937288233487556127 | SUNEQ |
| 364 | 961331422153064591 | LINEQ |
| 374 | 986831973571639238 | BSIN |
| 384 | 1014729179793648627 | FRG2 |
| 394 | 1040390510887244462 | NSLR |
| 404 | 1073048220598422763 | ZKIN |
| 414 | 1100231611071698839 | LAR |
| 424 | 1121292966566317463 | TLRDQ |
| 434 | 1139717773370432743 | HLT1 |

The required ticker list is reproduced exactly and in order.

## Research method

Fresh external authoritative research was performed for all 44 cases, led by SEC filings and issuer documents. For every case, the queue CUSIP chain was checked for security-class evidence and for contradictory preferred-stock, preferred-ADS, partnership/unit, trust, warrant/right, or other non-common legal-form evidence. CUSIP changes, reverse splits, issuer renames, mergers, reorganizations, SPAC transitions and depositary-ratio changes were analyzed separately from true legal security-type changes.

No future returns, prices, ranks, Champion selections, strategy outcomes, survival, profitability, or future index membership were used. `outcome_information_used=false` for every case.

## Results

| ticker | canonical interval | queue CUSIPs | decision | legal security type / effective interval | primary evidence |
|---|---|---|---|---|---|
| QUCY | 2026-05-13—2026-06-15 | N5436L101, N5436L119 | common | common stock / ordinary common equity | https://www.sec.gov/Archives/edgar/data/1874252/000210558526000006/xslSCHEDULE_13G_X01/primary_doc.xml |
| GSIW | 2024-09-19—2024-10-08 | G3730L107, G3730L131, G3730L123 | common | ordinary shares | https://www.sec.gov/Archives/edgar/data/1954269/000185141625000016/xslSCHEDULE_13G_X01/primary_doc.xml |
| DMKPQ | 2021-01-20—2021-02-26 | 00547W208, 00547W307, 15115L103, 00547W109 | common | common stock | https://www.sec.gov/Archives/edgar/data/887247/000183988223014903/versi-sc13d_052523.htm |
| GMXRQ | 2008-06-11—2011-03-04 | 38011M603, 38011M108, 38011M124, 38011M207 | common | common shares/common stock | https://www.sec.gov/Archives/edgar/data/1035917/000103591710000005/gmx13g123109.pdf |
| HEROQ | 2006-11-17—2014-07-21 | 427093109, 427093307, 427093117 | common | common stock | https://www.sec.gov/Archives/edgar/data/80255/000008025514000558/xslForm13F_X01/infotable.xml |
| X | 2009-11-20—2010-01-15 | 912909108, 90337T101 | common | common stock | https://www.sec.gov/Archives/edgar/data/1163302/000001961714000298/US_Steel.HTM |
| VOD | 2006-07-05—2026-07-31 | 92857W308, 92857W209, 92857W100, 92857T107, 92858D200, 92858D101 | common | ordinary shares / ADR-ADS representing ordinary shares | https://www.sec.gov/Archives/edgar/data/839923/000120864626000022/xslSCHEDULE_13G_X02/primary_doc.xml |
| GTE | 2008-06-27—2008-07-18 | 38500T101, 38500T200 | common | common stock/common shares | https://www.sec.gov/Archives/edgar/data/1273441/000093583626000385/xslSCHEDULE_13G_X02/primary_doc.xml |
| CBDBY | 2008-03-05—2021-03-24 | 20440T201, 20440T300 | **split** | **non_common preferred-share ADS through 2020-03-04; common-share ADS from 2020-03-05** | https://www.sec.gov/Archives/edgar/data/728889/000072888913000174/companhiabrasileira.htm ; https://www.sec.gov/Archives/edgar/data/1038572/000129281420000560/cbd20200227_8a.htm ; https://www.sec.gov/Archives/edgar/data/1038572/000129281424002600/cbdform20f_2023.htm |
| DXTRQ | 2007-09-10—2007-10-09 | 14141R101, 252366109, 14141R309 | common | common stock | https://www.sec.gov/Archives/edgar/data/763212/000110465918051393/xslForm13F_X01/a18-18656_1informationtable.xml |
| RGSEQ | 2013-05-28—2016-10-24 | 75601N104, 75601N500, 75601N203, 75601N302 | common | Class A/common stock across reverse-split CUSIPs | https://www.sec.gov/Archives/edgar/data/1469336/000090266416007724/p16-1637sc13g.htm ; https://www.sec.gov/Archives/edgar/data/1591625/000101905614000195/xslForm13F_X01/infotable.xml |
| OSG1 | 2024-06-04—2024-06-17 | 69036R863, 69036R301 | common | Class A common stock | https://www.sec.gov/Archives/edgar/data/75208/000149315224020723/formsc14d-9c.htm ; https://www.sec.gov/Archives/edgar/data/75208/000089843221000553/sc13d-a.htm |
| VRAYQ | 2018-08-02—2021-02-01 | 92672L107, 92672W103 | common | common stock | https://www.sec.gov/Archives/edgar/data/1447884/000110465920084644/tm2025070d1_sc13da.htm |
| GPLDF | 2011-03-17—2011-03-31 | 39115V101, 39115V309, 39115T106 | common | common stock | https://www.sec.gov/Archives/edgar/data/1455915/000145591518000004/xslForm13F_X01/info_table_amended.xml |
| TFII | 2021-02-05—2026-07-31 | 87241L109, 89366H103 | common | common shares/common stock | https://www.sec.gov/Archives/edgar/data/1588823/000031898926000081/xslSCHEDULE_13G_X02/primary_doc.xml |
| LUMN | 2007-10-26—2020-10-23 | 156700106, 550241103 | common | common stock | https://www.sec.gov/Archives/edgar/data/1608376/000160837618000006/xslForm13F_X01/13F.xml |
| WPGGQ | 2014-11-11—2021-07-01 | 93964W108, 92939N102, 939647103, 93964W405 | common | common stock | https://www.sec.gov/Archives/edgar/data/1594686/000143774921021538/ex_281479.htm |
| QSI | 2021-03-09—2021-03-18 | 74765K105, 42984L105 | common | Class A/Class B common stock | https://www.sec.gov/Archives/edgar/data/1076352/000114036126034869/xslSCHEDULE_13D_X02/primary_doc.xml |
| PL1 | 2007-02-08—2015-01-30 | 743674103, 743674202 | common | common corporate equity | https://www.sec.gov/Archives/edgar/data/93751/000095012314008382/xslForm13F_X01/form13fInfoTable.xml |
| CNR2 | 2006-07-05—2022-07-22 | 628852204, 21925D109, 628852105 | common | common stock | https://www.sec.gov/Archives/edgar/data/1456670/000095012322000187/xslForm13F_X01/0000950123-22-000187-8968.xml |
| YVRLF | 2021-03-17—2021-08-02 | 53634Q204, 52170U207, 53634Q105, 52170U108, 10970E104, 53634Q402 | common | common shares | https://www.sec.gov/Archives/edgar/data/1769419/000175392622000148/g082597_sch13ga.htm |
| PHG | 2006-07-05—2026-07-31 | 500472303, 500472105, 500472204, 718337504 | common | ADR representing ordinary shares | https://www.sec.gov/Archives/edgar/data/1086619/000156761920014990/xslForm13F_X01/form13fInfoTable.xml |
| FRCB | 2011-06-24—2023-05-01 | 33616C100, 336158100 | common | common stock | https://www.sec.gov/Archives/edgar/data/1132979/000093247117002257/firstrepublicbank.htm |
| GFASY | 2007-12-18—2012-03-06 | 362607301, 362607400, 362607608 | common | ADS representing common shares | https://www.sec.gov/Archives/edgar/data/1389207/000091957415007313/d6850794_13-g.htm |
| DSHK | 2006-12-22—2014-11-25 | 262077100, 65105M108, 65105M603, 65105M504 | common | common stock | https://www.sec.gov/Archives/edgar/data/1741619/000114420418041950/xslForm13F_X01/infotable.xml |
| DPTRQ | 2006-09-15—2009-10-19 | 247907207, 247907306 | common | common stock | https://www.sec.gov/Archives/edgar/data/319029/000119312508038258/dsc13d.htm |
| AROC | 2009-08-05—2015-10-21 | 03957W106, 30225X103 | common | corporate common stock | https://www.sec.gov/Archives/edgar/data/1389050/000210011926000095/xslSCHEDULE_13G_X02/primary_doc.xml |
| DNN | 2021-02-12—2026-07-31 | 248356107, 46052H102 | common | common shares | https://www.sec.gov/Archives/edgar/data/1063259/000090514826002485/xslSCHEDULE_13G_X02/primary_doc.xml |
| WKEY | 2021-03-18—2025-11-14 | 97727L200, 97727L408, 97727L309 | common | ADS representing Class B ordinary shares | https://www.sec.gov/Archives/edgar/data/1896009/000119380521001693/e621123_sc13d-wisekey.htm |
| CSUNY | 2007-11-14—2008-09-22 | 16942X302, 16942X104 | common | ADS representing ordinary shares | https://www.sec.gov/Archives/edgar/data/824468/000082446809000065/chinasunergyrevised13ga.htm |
| NKLAQ | 2020-03-04—2025-01-17 | 654110105, 654110303, 92243N103, 92243N202 | common | common stock | https://www.sec.gov/Archives/edgar/data/1731289/000114036121029046/brhc10028171_sc13da.htm |
| XL1 | 2006-07-05—2018-09-11 | G98294104, G98290102, G98255105, G32429105, G3242A102 | common | common/ordinary shares | https://www.sec.gov/Archives/edgar/data/812295/000114036116085960/xslForm13F_X01/form13fInfoTable.xml |
| VEDL | 2007-12-18—2021-11-05 | 92242Y100, 78413F103, 859737207 | common | ADS representing equity/ordinary shares | https://www.sec.gov/Archives/edgar/data/1370431/000119380515000697/e613612_424b3-vedanta.htm |
| ORIO | 2021-02-11—2025-07-11 | 60800C109, 60800C208, 608008108, 68627G104 | common | common corporate equity | https://www.sec.gov/Archives/edgar/data/728083/000156761919017153/xslForm13F_X01/form13fInfoTable.xml |
| ACIIQ | 2006-07-05—2015-09-25 | 039380100, 039380308 | common | common stock | https://www.sec.gov/Archives/edgar/data/1393818/000095012314009155/xslForm13F_X01/form13fInfoTable.xml |
| SUNEQ | 2006-07-05—2016-03-28 | 86732Y109, 552715104 | common | common stock | https://www.sec.gov/Archives/edgar/data/945436/000093247116011569/sunedisoninc.htm |
| LINEQ | 2007-12-12—2015-08-26 | 536020100, 53601P304 | **non_common** | **units representing limited liability company interests of Linn Energy, LLC** | https://www.sec.gov/Archives/edgar/data/1326428/000119312515193680/d927939d424b5.htm ; https://www.sec.gov/Archives/edgar/data/1326428/000132642816000071/linnform10-k2015.htm |
| BSIN | 2021-07-14—2025-02-04 | 911805109, 911805307, 911805208 | common | common stock | https://www.sec.gov/Archives/edgar/data/101594/000143774926026861/bsin20260613_10q.htm |
| FRG2 | 2011-02-03—2011-03-14 | 35903Q106, 359032109 | common | common stock | https://www.sec.gov/Archives/edgar/data/1271129/000114420410054080/v199128_sc13ga.htm |
| NSLR | 2012-02-13—2012-06-06 | 86887Q109, 36191J101, 86944Q100 | common | common stock | https://www.sec.gov/Archives/edgar/data/1021249/000095012318005186/xslForm13F_X01/form13fInfoTable.xml |
| ZKIN | 2021-03-15—2025-05-21 | G9892K100, G9892K209 | common | ordinary shares | https://www.sec.gov/Archives/edgar/data/1687451/000114420418008712/tv486065_sc13g.htm |
| LAR | 2020-09-21—2026-06-18 | 53680Q207, 53681K100, H5012F103 | common | common shares | https://www.sec.gov/Archives/edgar/data/1440972/000121390021008426/ea135305-13ga2bcp_lithium.htm |
| TLRDQ | 2006-07-18—2019-10-09 | 87403A107, 587118100 | common | common stock | https://www.sec.gov/Archives/edgar/data/102909/000093247118004236/tailoredbrandsinc.htm |
| HLT1 | 2006-07-05—2007-10-23 | 432848109, 432848208 | common | common corporate equity | https://www.sec.gov/Archives/edgar/data/1729045/000114420419019734/xslForm13F_X01/infotable.xml |

The JSON companion contains the complete per-case structured record: security ID, ticker, canonical interval, all queue CUSIPs, decision, legal security type, effective interval(s), evidence URLs, factual findings, identity-transition analysis, contradiction search, `outcome_information_used=false`, and review status.

## Material adjudications

### CBDBY — true security-type transition

SEC ownership evidence identifies CUSIP `20440T201` as American Depositary Shares, each representing one **Preferred Share**. Companhia Brasileira de Distribuição's SEC-filed Form 8-A records shareholder approval to convert all preferred shares into common shares. Its later Form 20-F states the preferred shares were converted on February 28, 2020, U.S. preferred ADS positions were converted into common ADS positions on March 4, 2020, and trading under the new common-ADS CUSIP began March 5, 2020.

Adjudication:

- `2008-03-05` through `2020-03-04`: **non_common** — ADS representing preferred shares.
- `2020-03-05` through `2021-03-24`: **common** — ADS representing common shares.

This is a genuine legal security-type change. It is not a stale-CUSIP or identity-chain artifact.

### LINEQ — LLC unit legal form

Linn Energy's SEC prospectus describes the traded `LINE` securities as **units representing limited liability company interests**. Its Form 10-K identifies Linn Energy, LLC as a Delaware limited liability company and states that those units traded on Nasdaq under `LINE`.

Adjudication for `2007-12-12` through `2015-08-26`: **non_common**.

The instrument was an LLC unit interest. The prior `UNRESOLVED_HYBRID_LEGAL_FORM` status is closed by direct issuer legal-form evidence.

## Identity-transition and contradiction findings

- Reverse splits and replacement CUSIPs did not create a type change where the underlying class remained common stock or ordinary shares. Direct examples include RGSEQ, VRAYQ, DPTRQ, NKLAQ, ZKIN and BSIN.
- ADR/ADS status was classified from the represented security. VOD, PHG, GFASY, WKEY, CSUNY and VEDL represent ordinary/common equity and therefore classify `common` under the policy.
- Distinct non-common securities were explicitly separated from the reviewed common equity. OSG filings distinguish warrants from Class A common stock. WPG filings distinguish preferred stock from common stock. HERO filings separately identify convertible debt from the common equity.
- SPAC predecessor units/warrants were treated as distinct instruments where present; the reviewed QSI and NKLA equity CUSIPs were established as common stock.
- Corporate reorganizations, issuer-name changes and mergers were treated as identity changes unless primary evidence established a legal-class change. CBDBY is the only assigned case where primary evidence establishes such a transition.

## Counts and classification changes

- assigned: **44**
- common: **42**
- non_common: **1**
- split: **1**
- unresolved: **0**
- classification changes from the queue common hypothesis: **CBDBY, LINEQ**
- unresolved names: **none**

`CBDBY`: common hypothesis → split (`non_common` preferred-share ADS through 2020-03-04; `common` common-share ADS from 2020-03-05).

`LINEQ`: common hypothesis / previously unresolved hybrid → `non_common` LLC unit interest.

## Validation

- exact assignment reproduced before research: **pass**
- every assigned case reviewed exactly once: **pass**
- foreign cases: **0**
- fresh external primary-source research: **performed**
- contradiction search: **performed for every case**
- `outcome_information_used=false`: **all 44 cases**
- unresolved cases: **0**
- replay/backtest run: **0**
- economic/runtime/strategy changes: **0**
