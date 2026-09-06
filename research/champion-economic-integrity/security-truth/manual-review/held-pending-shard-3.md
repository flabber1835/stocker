# Held/Pending Security Truth — Shard 3

Reviewed: 2026-09-06  
Parent: `research/champion-certification-economic-integrity` @ `428721fd4a7494df477c2c9cd3d94ded1c1f5d37`  
Scope: exactly 15 assigned securities  
Outcome information used: `false`

## Result

| Ticker | Canonical interval | CUSIP(s) | Decision | Finding |
|---|---|---|---|---|
| IHS2 | 2007-07-10 — 2016-07-12 | 451734107 | common | IHS Inc. Class A common equity. |
| GLOG | 2014-01-31 — 2021-03-19 | G37585109 | common | GasLog Ltd common shares; preferred issues are separate classes. |
| ON | 2006-07-31 — 2026-07-31 | 682189105 | common | ON Semiconductor/onsemi common stock. |
| SNDA1 | 2006-12-20 — 2010-06-25 | 81941Q203 | common | Sponsored ADR representing Shanda ordinary equity. |
| PWER1 | 2010-05-05 — 2013-05-17 | 73930R102, 739308104 | common | Power-One common-stock CUSIP chain; no class change in canonical interval. |
| MMI1 | 2011-06-23 — 2012-05-21 | 620097105 | common | Motorola Mobility Holdings common stock. |
| CNQ | 2006-07-05 — 2026-07-31 | 136385101 | common | Canadian Natural Resources common shares. |
| ESINQ | 2006-07-05 — 2014-11-11 | 45068B109 | common | ITT Educational Services common stock; later bankruptcy suffix does not change historical type. |
| IRM | 2011-03-16 — 2011-04-07 | 46284V101, 462846106, 46284P104 | common | Iron Mountain common-stock identity chain. |
| VRUS1 | 2011-03-08 — 2012-01-17 | 71715N106 | common | Pharmasset common stock. |
| CVE | 2010-05-20 — 2026-07-31 | 15135U109 | common | Cenovus Energy common shares. |
| FALB | 2006-07-05 — 2006-08-15 | 655422103, 306104100 | common | Noranda predecessor to Falconbridge New 2005 common-share chain; transition predates canonical interval. |
| AQN | 2019-10-22 — 2026-07-31 | 015857105 | common | Algonquin Power & Utilities common shares. |
| B | 2007-03-07 — 2007-03-13 | 067901108, 06849F108 | common | Barrick common-share chain; later Barrick Mining identifier transition is outside 2007 interval. |
| THOR1 | 2008-08-05 — 2015-10-07 | 885175307, 885175109 | unresolved | 885175307 is Thoratec common stock; predecessor CUSIP 885175109 was not independently bound strongly enough for full-chain closure. |

## Counts

- `common`: 14
- `non_common`: 0
- `unresolved`: 1
- total: 15

## Identity / interval findings

No canonical interval required a security-type split. PWER1, IRM, FALB, B and THOR1 carry multiple assigned CUSIPs. The resolved multi-CUSIP cases remain common equity across their authenticated identity chains. FALB's Noranda-to-Falconbridge transition predates its July–August 2006 canonical interval. B's later Barrick identifier/name transition postdates its March 2007 canonical interval. THOR1 remains unresolved solely because the older CUSIP `885175109` lacks sufficient independent identity-chain evidence.

No preferred security, preferred ADS, partnership unit, trust unit, warrant, right, or other non-common structure was established for any resolved assigned security.

## Evidence discipline

The review used issuer/security identity and class evidence, including SEC-filed 13F class descriptions and historical security/CUSIP records. Later evidence was used only to establish historical legal/security identity. Future returns, prices, ranks, survival, portfolio outcomes, strategy results and index membership were not used. Every JSON case records `outcome_information_used=false`.

Detailed source URLs, source-document dates, factual findings, transition analyses and contradiction-search results are retained per case in `held-pending-shard-3.json`.

## Integrity

Canonicalized JSON SHA-256 (UTF-8, recursively sorted object keys, compact separators):

`52d7f10bc5b12d371326ed41a54799d4a784145849f80cea6daad180358501ed`
