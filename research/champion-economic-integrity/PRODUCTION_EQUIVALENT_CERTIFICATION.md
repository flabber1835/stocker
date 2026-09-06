# Champion Production-Equivalent Certification

Status: **PRODUCTION_EQUIVALENT_CERTIFIED**

Date: 2026-09-06

Certifying replay: https://github.com/flabber1835/stocker/actions/runs/34064302990

## Certified claim

> If the frozen system had been switched on in 2006, and its live security classifier had correctly identified every security's type each day, this is how the system would have behaved through 2026.

This is a **Production-equivalent perfect-classification backtest certificate**. It is not a strict archival source-availability certificate for what historical documents were obtainable on each historical day.

## Frozen identity

- Formal Champion source: `27bb992087182c42c3c051e62bf837895f5d2ab7`
- Candidate source: `ba74e79490beb8950611b1d17f5d124833b3d91e`
- Pinned Production runtime: `887f479b15ad861313da666ad698034d3847121c`
- Profile: `strategy9-e3-research-champion-v1`
- Profile SHA-256: `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`
- Canonical PIT corpus hash: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Canonical package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`

Warm-up starts 2006-01-03. Measurement is 2006-07-31 through 2026-07-31, 5,032 sessions.

## Security-truth closure

The final truth corpus validator passed with:

- durable: 442
- leadership: 182
- ranking/base: 61
- unique parent securities: 685
- new P0 adjudications: 11
- final effective securities: **696**
- unresolved factual security-type cases: **0**
- validator issues: **0**

The final integration confirms the required transition boundaries:

- `AM`: non-common through 2019-03-12; common from 2019-03-13.
- `CBDBY`: non-common through 2020-03-04; common from 2020-03-05.
- `ERF`: non-common through 2010-12-31; common from 2011-01-03.
- `OBE`: non-common through 2010-12-31; common from 2011-01-03.
- `PVX`: non-common through 2010-12-31; common from 2011-01-03.
- `PDS`: non-common through 2010-06-01; common from 2010-06-02 through the canonical episode end 2015-06-04.

Known identity/CUSIP hygiene anomalies remain separate metadata findings and do not leave any factual security-type case unresolved.

## Production-equivalent economic semantics

The final executable program uses the frozen economic contract:

- no synthetic whole-order capacity participation cap;
- final closed security-truth classifier;
- dividend entitlement from prior-close post-split shares;
- ex-date dividend receivable accrues before open equity;
- dividend settlement lag exactly **1 session**;
- current-session terminal security participates in ranking and is then vetoed for admission;
- no cumulative permanent terminal-retirement set;
- pending entry into a current terminal security is cancelled on the event session;
- recent-leadership next witness ranks the normal cross-section and then excludes current-session terminal IDs;
- leadership return uses exact terminal consideration when available, otherwise the observed signal close, otherwise Production zero-contribution behavior;
- a missing held mark carries the last trustworthy raw mark, marks state unresolved, and blocks admissions without an immediate hard abort;
- all other frozen Champion mechanics remain unchanged.

Performance results were not used to select classifications or economic corrections.

## Preflight identity

The source-only preflight passed before the replay. Its Production-equivalent generated source and the replay's generated source have the same path-normalized AST identity:

`3cba94dd8389decd99f893a023260c50bc5b0c3472b3fc63d824be045dcbf9a7`

Replay generated-source SHA-256:

`bb89658e769adcdfd3a2f91238f60a7ee152a9c51add1b0ba383580e38a9488a`

The full replay explicitly executed with `RESEARCH_REPLAY_MODE=fullpit` and asserted both `MODE == 'fullpit'` and `PIT_MODE is True` before strategy execution.

## Certifying replay

Run: **34064302990**

Head: `5b4b4681fa46b3f867557c7ad8be9829a4e1be62`

Conclusion: **success**

Artifact: `champion-production-equivalent-final-34064302990-1`

Artifact ID: `9999003664`

Artifact digest:

`sha256:b1970671c05aa205da560a7890d421691408a7ecdec17c49d05bd37aeed9d0d8`

Embedded replay certificate SHA-256:

`6473b67629abd39404b4c5b2a4ed861fb02115e3dd76efb86d1a82b0d7e4335b`

Daily equity/output SHA-256:

`85d95eb403376bcfc6de0cb2632512bf306aca46487ee627c25198dbc2f8b77d`

## Certified results

| Window | Champion CAGR | SPY CAGR | Champion ending multiple | Champion max drawdown | Champion Sharpe |
|---|---:|---:|---:|---:|---:|
| **20 years** | **18.7246%** | 11.2563% | **30.9634x** | **-22.8801%** | **1.0511** |
| 15 years | 17.9232% | 14.4382% | 11.8539x | -22.8801% | 1.0453 |
| 10 years | 21.4589% | 15.0059% | 6.9817x | -22.8801% | 1.1201 |
| 5 years | 20.7052% | 12.8256% | 2.5594x | -20.1434% | 1.0772 |

For the full 20-year measurement interval, SPY's ending multiple was 8.4433x, max drawdown was -55.2019%, and daily-252 Sharpe was 0.6473.

## Fullpit mode cross-check

The earlier completed diagnostic run 34063672162 was deliberately not accepted for certification because its runtime mode was not explicitly forced to `fullpit`.

After forcing `fullpit`, the certifying run produced the **exact same daily output file** as that diagnostic run:

`daily.csv SHA-256 = 85d95eb403376bcfc6de0cb2632512bf306aca46487ee627c25198dbc2f8b77d`

Thus the stale `nonpit` mode setting did not change the economics of the already-canonicalized path, while the certifying run removes that ambiguity by explicitly asserting `fullpit` before execution.

## Certification decision

All required factual-classification and economic-semantic gates are closed, the canonical package identity was verified, the exact executable preflight matched the replay program, and the clean 5,032-session fullpit replay completed successfully.

**Certification status: `PRODUCTION_EQUIVALENT_CERTIFIED`.**
