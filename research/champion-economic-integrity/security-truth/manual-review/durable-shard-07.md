# Durable-ranked security-type review — shard 07

Base head: `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

## Assignment

Reproduced exactly from `fresh-path-open-review-queue.csv`: filter `priority == P1_DURABLE_RANKED`; sort ascending by `(security_id as integer, ticker)`; assign zero-based sequential index `i`; retain exactly `i % 10 == 7`.

P1 rows: **442**. Assigned rows: **44**.

| i | security_id | ticker |
|---:|---:|---|
| 7 | 11691645360688405 | SAFE2 |
| 17 | 44348566159439429 | NGD |
| 27 | 64207844585346273 | ROSEQ |
| 37 | 112246079093855408 | BELFA |
| 47 | 154787694246958247 | PPMIQ |
| 57 | 187001531571140956 | CRE1 |
| 67 | 210939526059118148 | ATLS1 |
| 77 | 233705247448419189 | ASTX2 |
| 87 | 264006574620812721 | SIFY |
| 97 | 283931002164964504 | TWOUQ |
| 107 | 304661060242084891 | GPT4 |
| 117 | 329261821474200437 | WLL2 |
| 127 | 349467349494008517 | OZK |
| 137 | 367809761125398317 | CEG1 |
| 147 | 400771702699245606 | GOEVQ |
| 157 | 414519427740402819 | BAC |
| 167 | 437064850062150131 | AVX1 |
| 177 | 470898446993080544 | CAM2 |
| 187 | 488901893881778762 | OPITQ |
| 197 | 517535898370665174 | ZNB |
| 207 | 556078666002943481 | OIGBQ |
| 217 | 575969493483321836 | RKLB |
| 227 | 603451986059143781 | MAXNQ |
| 237 | 618741754657237874 | SPIEF |
| 247 | 647967670841206151 | SUNWQ |
| 257 | 669039615450984041 | SVM1 |
| 267 | 695538091198475722 | SFR1 |
| 277 | 711458655922744689 | TFC |
| 287 | 747992771333504975 | CWTRQ |
| 297 | 767007442192935477 | SES |
| 307 | 810272368527364966 | GG |
| 317 | 835968569385277275 | DNRCQ |
| 327 | 863487155718577721 | FSRNQ |
| 337 | 888056120539582187 | SHEL |
| 347 | 911227416551377854 | UL |
| 357 | 944174442226145604 | MI2 |
| 367 | 966800855847192401 | FLY2 |
| 377 | 995805153065282380 | CMBT |
| 387 | 1025123653881873396 | ANGH |
| 397 | 1042882926694701041 | KB |
| 407 | 1082808592473316903 | NIKI |
| 417 | 1104508571422042454 | PKX |
| 427 | 1125828503689962237 | TPLMQ |
| 437 | 1144313377406956370 | XCOOQ |

## Results

Counts: **38 common**, **3 non_common**, **0 split**, **3 unresolved**.

### Classification changes

- `ATLS1` (`210939526059118148`): `common → non_common`. SEC identifies the security as common units representing limited partnership interests; OCC binds the ATLS1 adjusted security to Atlas Energy L.P. common units.
- `OPITQ` (`488901893881778762`): `common → non_common`. SEC identifies Government Properties Income Trust as a Maryland real estate investment trust issuing common shares of beneficial interest. Under the supplied policy, trust units are non_common.
- `SFR1` (`695538091198475722`): `common → non_common`. SEC identifies Starwood Waypoint Residential Trust as a Maryland real estate investment trust issuing common shares of beneficial interest. Under the supplied policy, trust units are non_common.
- `TFC` (`711458655922744689`): `unknown → common`. Truist filings identify TFC as common stock and separately enumerate preferred/depositary-share classes.

### Unresolved worklist

- `ROSEQ` (`64207844585346273`): the canonical 2010–2015 CUSIP/identity chain is not fully bound to the later Rosehill Resources Class A common-stock evidence.
- `ZNB` (`517535898370665174`): the nine-CUSIP multi-name/issuer chain lacks a complete primary-source legal-class binding.
- `NIKI` (`1082808592473316903`): the offshore three-CUSIP identity/class chain lacks reliable primary-source binding.

## Resolved case summary

| Ticker | Decision | Legal type / principal evidence |
|---|---|---|
| SAFE2 | common | Safehold Inc. common stock; SEC Schedule 13G/A |
| NGD | common | New Gold Inc. common shares; SEC Schedule 13G/A |
| BELFA | common | Bel Fuse Class A common stock; SEC Schedule 13D |
| PPMIQ | common | PMI Group common stock / COM NEW across both CUSIPs; DTCC notices |
| CRE1 | common | CarrAmerica Realty Corp. listed corporate equity; SEC N-PX identity record |
| ATLS1 | non_common | Atlas Energy L.P. common units representing limited partnership interests; SEC/OCC |
| ASTX2 | common | Astex Pharmaceuticals common stock; Schedule 14D-9 |
| SIFY | common | ADS representing Sify equity shares; SEC depositary form |
| TWOUQ | common | 2U Inc. common stock; SEC Schedule 13G |
| GPT4 | common | Gramercy Property Trust Inc. is a Maryland corporation; its security is reported as common stock |
| WLL2 | common | Whiting Petroleum Corp. common stock |
| OZK | common | Bank OZK common stock |
| CEG1 | common | Constellation Energy Group Inc. common stock |
| GOEVQ | common | Canoo Inc. Class A common stock |
| BAC | common | Bank of America Corp. common stock |
| AVX1 | common | AVX Corp. common stock |
| CAM2 | common | Cooper Cameron/Cameron International common stock across identity transition |
| OPITQ | non_common | Common shares of beneficial interest in Maryland REIT |
| OIGBQ | common | Orbital Infrastructure Group Inc. common stock |
| RKLB | common | Rocket Lab Corp. common stock |
| MAXNQ | common | Maxeon Solar Technologies ordinary shares |
| SPIEF | common | SPI Energy ordinary shares |
| SUNWQ | common | Sunworks Inc. common stock |
| SVM1 | common | Silvercorp Metals common shares |
| SFR1 | non_common | Common shares of beneficial interest in Maryland REIT |
| TFC | common | Truist common stock; preferred/depositary siblings separately identified |
| CWTRQ | common | Coldwater Creek common equity |
| SES | common | SES AI Class A common stock |
| GG | common | Goldcorp common equity |
| DNRCQ | common | Denbury Resources common stock |
| FSRNQ | common | Fisker Class A common stock |
| SHEL | common | ADS representing Shell ordinary shares |
| UL | common | ADR program with Unilever ordinary shares underlying |
| MI2 | common | Marshall & Ilsley common stock |
| FLY2 | common | ADS each representing one common share |
| CMBT | common | CMB.TECH ordinary shares |
| ANGH | common | Anghami ordinary shares; warrants separately listed as ANGHW |
| KB | common | ADS representing KB Financial common stock |
| PKX | common | POSCO ADS representing common stock |
| TPLMQ | common | Triangle Petroleum common stock |
| XCOOQ | common | EXCO Resources common stock |

The machine-readable JSON records the canonical interval, all queue CUSIPs, effective interval, evidence URLs, source documents, factual findings, identity-transition analysis, contradiction search, `outcome_information_used=false`, and review status for every assigned case.

## Validation

- Assignment formula reproduced: **PASS**
- Assigned cases: **44**
- Every assigned case exactly once: **PASS**
- Foreign cases: **0**
- Resolved cases evidence-backed: **PASS**
- Explicit unresolved worklist: **PASS**
- Factual type splits: **0**
- Outcome information used: **false for every case**
