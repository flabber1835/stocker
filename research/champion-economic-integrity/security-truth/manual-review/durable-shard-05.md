# Durable-ranked factual security-type review — shard 05

Date: 2026-09-06

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-durable-05`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

## Assignment

Reproduced exactly:

1. filter `priority == P1_DURABLE_RANKED`;
2. sort ascending by `(security_id as integer, ticker)`;
3. assign zero-based sequential index `i`;
4. retain only `i % 10 == 5`.

Filtered population: **442**. Assigned shard: **44**. The assigned list was frozen before external research.

| i | security_id | ticker | canonical interval | decision | legal security type |
|---:|---:|---|---|---|---|
| 5 | 7927904980452015 | NM | 2007-10-15..2008-06-12 | common | foreign ordinary/common shares |
| 15 | 36353796762386872 | TCSGQ | 2021-02-16..2021-03-29 | common | corporate common stock |
| 25 | 57411840384698119 | UBS | 2006-07-05..2026-07-31 | common | registered ordinary shares |
| 35 | 105422700513565499 | ST | 2011-12-27..2012-02-07 | common | ordinary shares |
| 45 | 153535438649515067 | AX | 2024-03-22..2024-03-27 | common | corporate common stock |
| 55 | 177752727931112051 | LVNTA | 2013-02-13..2018-03-09 | common | Series A tracking common stock |
| 65 | 207779119312695497 | ARB1 | 2007-07-31..2013-09-27 | common | corporate common stock |
| 75 | 227060587393674304 | PCL1 | 2006-07-05..2016-02-19 | common | REIT corporate common stock |
| 85 | 257995258404860206 | ERF | 2006-07-05..2024-05-30 | split | trust units through 2010-12-31; corporate common shares from 2011-01-03 |
| 95 | 280245678029102713 | RADA | 2014-09-17..2014-10-03 | common | ordinary shares |
| 105 | 297972758990644181 | ICON1 | 2006-12-19..2016-01-12 | common | corporate common stock |
| 115 | 324243700516094246 | SGYPQ | 2015-06-17..2017-12-08 | common | corporate common stock |
| 125 | 345679706151556113 | SU | 2006-07-05..2026-07-31 | common | common shares |
| 135 | 365000158987626639 | OREXQ | 2010-12-08..2015-05-29 | common | corporate common stock |
| 145 | 393159556686986931 | PALDF | 2008-02-22..2011-03-25 | common | common shares |
| 155 | 410782084757237754 | ERIC | 2006-07-05..2026-07-31 | common | ADS representing Class B ordinary/common shares |
| 165 | 434115552006977400 | BBAR | 2025-01-08..2025-11-24 | common | ADS representing ordinary/common shares |
| 175 | 466470751566741991 | FG2 | 2017-06-19..2020-06-01 | common | corporate common stock |
| 185 | 483640223480714943 | TT | 2016-06-22..2018-02-12 | common | ordinary shares |
| 195 | 503186678476381570 | VELO | 2021-11-23..2021-11-30 | common | corporate common stock |
| 205 | 551894809158706341 | JAVA1 | 2006-07-05..2010-01-26 | common | corporate common stock |
| 215 | 573486634399361097 | ITRMF | 2021-01-26..2021-07-23 | common | ordinary shares |
| 225 | 596606942920510462 | BTE | 2011-05-16..2026-07-31 | common | common shares |
| 235 | 616300714786925804 | AWHHF | 2007-06-27..2017-07-27 | common | registered common shares |
| 245 | 645812499638572541 | FRANQ | 2012-04-18..2020-07-29 | common | corporate common stock |
| 255 | 660854745015090064 | FSM | 2020-06-19..2026-07-31 | common | common shares |
| 265 | 685580789639317612 | RIO | 2006-07-05..2026-07-31 | common | ADR/ADS representing ordinary shares |
| 275 | 704264673016955521 | GLG2 | 2007-11-16..2010-06-28 | common | common shares |
| 285 | 744983426264406452 | MM1 | 2007-03-05..2008-03-14 | common | corporate common stock |
| 295 | 765856696925416500 | SHLDQ | 2006-07-05..2017-04-27 | common | corporate common stock |
| 305 | 804009952146469650 | PCG | 2006-08-25..2023-02-17 | common | corporate common stock |
| 315 | 825629841091930724 | PTEIQ | 2018-06-11..2018-07-27 | common | corporate common stock |
| 325 | 854640941096794054 | ENLV | 2020-10-02..2021-03-04 | common | ordinary shares |
| 335 | 882904858327189489 | BEL | 2007-02-27..2019-04-15 | common | Class A/common shares |
| 345 | 909161371475655803 | CCK | 2006-07-05..2026-07-31 | common | corporate common stock |
| 355 | 937472210068847237 | VRN | 2016-03-24..2025-05-09 | common | common shares |
| 365 | 962456727331389556 | TROO | 2021-07-09..2021-09-23 | common | ordinary shares |
| 375 | 987173547474629718 | TECK | 2007-02-22..2026-07-31 | common | Class B subordinate voting common equity |
| 385 | 1015632908539209151 | ORIG | 2018-06-27..2018-11-14 | common | common shares |
| 395 | 1042287044744322383 | JMEI | 2014-11-20..2016-01-25 | common | ADS representing Class A ordinary shares |
| 405 | 1075904931462548556 | VISN1 | 2008-08-04..2008-08-26 | common | ADS representing ordinary/common shares |
| 415 | 1101080509353697420 | VVUSQ | 2009-09-09..2014-03-31 | common | corporate common stock |
| 425 | 1123392224175347435 | LSPD | 2021-03-15..2024-06-12 | common | subordinate voting common equity |
| 435 | 1142929555094712623 | BLIAQ | 2007-01-12..2007-11-27 | common | Class A common stock |

## Results

- Common: **43**
- Non-common: **0**
- Split: **1**
- Unresolved: **0**
- Outcome information used: **false**

### Classification changes

**ERF — split.** Enerplus Resources Fund was an income trust. SEC issuer materials establish that the conversion became effective January 1, 2011 and each trust unit was exchanged one-for-one for an Enerplus Corporation common share. The production-equivalent classification is therefore `non_common` through 2010-12-31 and `common` from 2011-01-03 through the canonical end date. This is a factual legal-type transition, not an identifier-only change.

**PCG — common.** The queue candidate was `unknown`. CUSIP 69331C108 is PG&E Corporation common stock and CUSIP 694308107 is Pacific Gas & Electric Company common stock. The identity chain contains two corporate issuers but no security-type change; the episode is `common`.

All other assigned cases remain `common`. CUSIP/name/reorganization changes were reviewed as identity changes and no contradictory preferred, partnership-unit, trust-unit, warrant, right, or other non-common class was established.

## Edge-policy findings

- ADR/ADS cases such as ERIC, RIO, BBAR, JMEI and VISN1 represent ordinary/common equity and therefore classify `common`.
- LVNTA is tracking common stock and remains `common`.
- TECK Class B subordinate voting shares and LSPD subordinate voting shares are common equity under the stated policy.
- PCL1's listed security is corporate common stock; REIT status does not make the listed share a trust unit.
- ERF is the sole factual type transition in this shard.

## Evidence and contradiction search

Per-case evidence URLs, source documents, findings, CUSIP binding, identity-transition analysis, and contradiction-search notes are retained in `durable-shard-05.json`. SEC, issuer, and depositary evidence was preferred. Later authoritative evidence was used only to establish historical legal security facts under the contract. Prices, returns, ranks, Champion selections, survival, profitability, future index membership, and strategy outcomes were not used.

## Validation

- Assignment formula reproduced: **PASS**
- Filtered P1 durable-ranked count: **442**
- Assigned cases: **44**
- Every assigned case exactly once: **PASS**
- Foreign cases: **0**
- Resolved cases evidence-backed: **PASS**
- Explicit unresolved worklist: **present, empty**
- Outcome information used: **false**

JSON SHA-256: `34bddf6ee0a2d156e01570246618ea6e8cb3524e7d3d27d119f621d1f292d352`
