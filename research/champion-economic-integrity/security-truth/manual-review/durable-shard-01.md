# Durable-ranked security-type review — shard 01

- Base commit: `5b9d9ea2e378044f49d217fe311b36b45c73124c`
- Branch: `research/champion-security-truth-durable-01`
- Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`
- Outcome information used: `false`

## Assignment assertions

- `priority == P1_DURABLE_RANKED`: **442** rows
- sort: `(security_id as integer, ticker)`
- shard: `i % 10 == 1`
- assigned: **45** rows
- indices: `1,11,21,...,441`
- all assertions: **PASS**

## Retained assignment and decisions

| i | security_id | ticker | canonical interval | queue CUSIPs | decision | legal security type | status |
|---:|---:|---|---|---|---|---|---|
| 1 | 4192202939672513 | GIG1 | 2006-10-23 → 2006-12-07 | 37518Q109 37517Y103 | **common** | GigPeak/GigaBeam common stock | resolved |
| 11 | 23018337810254348 | MMATQ | 2021-02-08 → 2022-12-29 | 59134N104 89102U103 59134N302 731100103 | **common** | Meta Materials common stock | resolved |
| 21 | 55788727182912640 | PRET | 2007-04-04 → 2017-12-01 | 709102107 709102800 | **non_common** | trust beneficial interests | resolved |
| 31 | 98300450827989858 | PLD1 | 2006-07-05 → 2011-06-02 | 743410102 743410300 814138103 814138301 | **non_common** | trust beneficial interests | resolved |
| 41 | 133867923656910566 | QGEN | 2007-06-13 → 2026-07-31 | N72482123 N72482206 N72482149 N72482107 N72482156 | **common** | ordinary shares | resolved |
| 51 | 172506604651624661 | ABI1 | 2006-07-05 → 2008-11-21 | 038149100 038020103 714041100 69332S201 69332S102 | **common** | Anheuser-Busch/common corporate equity chain | resolved |
| 61 | 195255558794917781 | SVNTQ | 2007-12-13 → 2011-06-02 | 80517Q100 090578105 | **common** | Savient Pharmaceuticals common stock | resolved |
| 71 | 218406372066695280 | GMRRQ | 2006-07-05 → 2010-07-16 | Y2693R101 Y2692M103 | **common** | General Maritime common stock | resolved |
| 81 | 247760171879345881 | INSYQ | 2014-03-05 → 2018-02-01 | 45824V209 45824V100 | **common** | INSYS Therapeutics common stock | resolved |
| 91 | 273915692055386629 | EVKG | 2020-10-23 → 2021-08-12 | 299766204 033495409 299766105 | **common** | Ever-Glory common stock | resolved |
| 101 | 288236439289729704 | HLTH1 | 2006-07-05 → 2008-12-19 | 40422Y101 422209106 290849108 94769M105 | **common** | common stock/ordinary common equity | resolved |
| 111 | 316608182834195623 | CJESQ | 2012-01-30 → 2015-09-03 | 12467B304 G3164Q101 | **common** | C&J Energy Services common stock | resolved |
| 121 | 339544981944706278 | ELGXQ | 2014-03-21 → 2017-01-25 | 29266S106 29266S304 750241101 14160K102 | **common** | Endologix common stock | resolved |
| 131 | 358282078487960651 | RSHCQ | 2006-07-05 → 2012-05-23 | 750438103 875382103 74979E101 | **common** | RadioShack common stock | resolved |
| 141 | 387061962353650732 | TMBRQ | 2021-03-11 → 2021-04-05 | 09072X101 887080109 09072X309 887080208 | **common** | Timber Pharmaceuticals common stock | resolved |
| 151 | 406563920163442612 | OR | 2022-03-23 → 2026-07-31 | 68827L101 68390D106 | **common** | Osisko Gold Royalties common shares | resolved |
| 161 | 427694133028893811 | PQUEQ | 2008-06-09 → 2008-10-09 | 716748108 716748306 683930200 | **common** | PetroQuest common stock | resolved |
| 171 | 454790526979868507 | SEELQ | 2019-03-08 → 2021-06-14 | 81577F109 03832V109 03832V307 81577F208 81577F307 81577F406 652903105 | **common** | Seelos Therapeutics common stock | resolved |
| 181 | 480937238539887084 | ID1 | 2007-05-07 → 2011-07-19 | 50212A106 92675K205 92675K106 | **common** | L-1 Identity Solutions/common stock | resolved |
| 191 | 493313832415681080 | NXY | 2006-07-05 → 2013-02-25 | 65334H102 136420106 | **common** | Nexen common shares | resolved |
| 201 | 545177556909447372 | EBIXQ | 2009-11-04 → 2022-04-05 | 278715206 247171101 278715107 247171200 | **common** | Ebix common stock | resolved |
| 211 | 565875166075379849 | ATTU | 2019-02-08 → 2019-03-20 | M15332121 M15332105 M5733B104 | **common** | ordinary shares | resolved |
| 221 | 590583760882916204 | CVNS1 | 2007-05-07 → 2007-06-05 | 22281W103 20452F107 | **common** | Covansys common stock | resolved |
| 231 | 605056745802848097 | BCE | 2007-04-04 → 2026-07-31 | 05534B760 05534B109 | **common** | BCE common shares | resolved |
| 241 | 624049122246070482 | KEM1 | 2017-07-19 → 2020-06-12 | 488360207 488360108 | **common** | KEMET common stock | resolved |
| 251 | 653469424920855695 | FCE.A | 2007-04-12 → 2018-12-07 | 345605109 345550107 | **common** | Class A common stock | resolved |
| 261 | 678547141734698310 | RIDEQ | 2020-08-04 → 2022-06-09 | 54405Q100 25280H100 54405Q209 25280H209 | **common** | Class A common stock | resolved |
| 271 | 697624355036831787 | NWG | 2008-10-09 → 2026-07-31 | 639057207 780097689 639057108 780097721 | **common** | ADR on ordinary shares | resolved |
| 281 | 725891032563178553 | ENLK | 2013-11-13 → 2019-01-25 | 29336U107 22765U102 | **non_common** | limited partnership common units | resolved |
| 291 | 760379920259343544 | AUOTY | 2006-07-05 → 2015-02-26 | 002255107 002255404 | **common** | ADR on ordinary shares | resolved |
| 301 | 789337046778155238 | BIN | 2016-01-19 → 2016-05-02 | 74339G101 44951D108 | **common** | Progressive Waste Solutions common stock | resolved |
| 311 | 819475645860203151 | MTLQQ | 2006-07-05 → 2009-07-10 | 370442105 370442402 370442501 62010U101 62010A105 | **common** | common stock/ordinary common equity | resolved |
| 321 | 842477555715340828 | RESI1 | 2013-10-03 → 2020-12-21 | 02153W100 35904G107 | **common** | common stock | resolved |
| 331 | 872471219798280015 | SDA | 2023-05-31 → 2023-06-29 | G3970D104 G85727108 | **common** | Class A ordinary shares | resolved |
| 341 | 897131622084018597 | SNN | 2011-01-27 → 2026-07-31 | 83175M205 83175M106 | **common** | ADS on ordinary shares | resolved |
| 351 | 928269154341959595 | AY | 2014-12-11 → 2024-12-11 | G0751N103 G00349103 | **common** | ordinary/common equity shares | resolved |
| 361 | 953174271952728833 | SNY | 2006-07-05 → 2026-07-31 | 80105N105 80105N204 | **common** | ADR on ordinary shares | resolved |
| 371 | 977786382894847089 | FABC | 2006-09-25 → 2026-05-26 | 054748108 054748207 92931L302 054748306 92931L401 26210U203 26210U104 92931L203 92931L104 | **common** | common stock | resolved |
| 381 | 1004199661649856090 | GRML | 2025-06-09 → 2025-07-11 | 758083109 49876K103 03465T108 | **common** | common equity | resolved |
| 391 | 1035830090364021089 | HQCL | 2007-12-03 → 2011-02-14 | 41135V103 41135V301 83415U108 | **common** | ADS on ordinary shares | resolved |
| 401 | 1065019148125218525 | DOGZ | 2022-01-10 → 2022-05-10 | G2788T103 G2788T111 | **common** | Class A ordinary/common shares | resolved |
| 411 | 1089135472417080980 | KCG1 | 2006-07-05 → 2012-12-26 | 499005106 499063105 499067106 499068104 | **common** | Knight/KCG common stock | resolved |
| 421 | 1117414376686089641 | ZVOI | 2011-07-27 → 2011-08-19 | 10807M105 98979V102 | **common** | Bridgepoint Education/Zovio common stock | resolved |
| 431 | 1133666028208707131 | DELL1 | 2006-07-05 → 2013-10-29 | 24702R101 247025109 | **common** | Dell common stock | resolved |
| 441 | 1150032651693992592 | TKC | 2007-08-16 → 2025-10-15 | 900111204 900111105 | **common** | ADR/ADS on ordinary shares | resolved |

## Factual adjudications

Every case was checked for contradictory type evidence using the queue CUSIP(s), issuer/ticker history, and terms covering common stock, preferred stock, partnership/trust units, warrants, rights, and ADR/ADS where applicable. Identifier, CUSIP, name, split, merger, and reorganization transitions were analyzed separately from legal security type. The JSON file contains the per-case evidence URL, factual finding, identity-transition analysis, contradiction-search result, effective interval, and `outcome_information_used=false` field.

### Classification changes

1. **PRET — common → non_common.** SEC filing identifies CUSIP `709102107` as Pennsylvania Real Estate Investment Trust **Common Shares of Beneficial Interest**. Under the supplied policy, trust beneficial interests are `non_common`. Evidence: https://www.sec.gov/Archives/edgar/data/905134/000090513403000050/r13g.htm
2. **PLD1 — common → non_common.** SEC-hosted historical material identifies CUSIP `743410102` as ProLogis **Common Shares of Beneficial Interest**. Under the supplied policy, trust beneficial interests are `non_common`. Evidence: https://www.sec.gov/Archives/edgar/data/722574/000003540206000033/faequityvalue_00150n-2526.htm
3. **ENLK — common → non_common.** SEC Schedule 13D identifies CUSIP `29336U107` as **Common Units Representing Limited Partnership Interests**. Under the supplied policy, partnership units are `non_common`. Evidence: https://www.sec.gov/Archives/edgar/data/1179060/000110465918048087/a18-17496_1sc13d.htm

### Identity/type examples

- **RIDEQ:** Nasdaq maps DiamondPeak/Lordstown Class A common-stock CUSIPs and separately identifies warrants; the business-combination transition is identity-only for type purposes.
- **SDA:** Nasdaq maps Goldenbridge ordinary shares to SunCar Class A ordinary shares and separately identifies warrants/rights/units.
- **RESI1:** SEC explicitly identifies CUSIP `02153W100` as common stock of a Maryland corporation; REIT terminology does not establish a trust-unit legal form.
- **FABC:** issuer/name/CUSIP continuity is anomalous; preferred/warrant references concern separate instruments or conversion rights, while reviewed equity CUSIPs are common stock.

## Summary

- assigned count: **45**
- common: **42**
- non_common: **3**
- split: **0**
- unresolved: **0**
- classification changes: **PRET, PLD1, ENLK**
- unresolved names: **none**
- outcome information used: **false**
- replay/backtest performed: **no**
