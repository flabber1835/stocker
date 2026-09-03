# S&P 500 point-in-time universe corpus

## Scope

This workstream builds a deterministic best-effort point-in-time S&P 500 membership corpus from 1996-01-02 through 2026-09-03. It is isolated on `research/backtester-sp500-pit`.

The LD-RC development period is 2006-2026. The 1996-01-02 through 2005-12-30 interval is reserved as a sealed historical out-of-sample period. Economic results from that interval must not be used to change the strategy before the first frozen-code evaluation.

## Membership authority

The historical spine is pinned to:

- repository: `fja05680/sp500`
- commit: `c31ac3cc56f28cf9a02b4e694eff7ceab596a0ff`
- file: `sp500_ticker_start_end.csv`
- Git blob SHA-1: `4aeb5f6046dea43063f9c7be72dfdf16e96d2821`

That file is derived from the repository's historical point-in-time snapshot series. Its `end_date` is the first snapshot on which a ticker is absent, so membership intervals use `[member_from, member_until_exclusive)` semantics.

The source maintainer explicitly warns that the earliest portion is less complete. The first 1996 snapshot contains 487 symbols; by 2001-01-16 the series reaches 494 and does not fall below that level afterward. The corpus therefore labels base intervals beginning before 2001-01-16 `secondary_early_best_effort` and later base intervals `secondary_historical`.

## 2026 primary-source overlay

The pinned historical source was last updated 2026-07-13. Official S&P Dow Jones Indices announcements are committed as a small deterministic overlay for later S&P 500 changes through 2026-09-03:

- 2026-08-05: add FERG, delete EA.
- 2026-08-18: add RDDT, delete AVB.

These events are effective prior to the market open on their stated effective dates. Added intervals are labeled `official_primary`; official deletion evidence is attached to the closing boundary of the affected historical interval.

## Artifact

The builder emits:

```text
sp500-pit-1996-2026/
  sp500-membership-intervals.csv.gz
  sp500-transitions.csv.gz
  quality.json
  manifest.json
  SHA256SUMS.txt
```

The artifact is deterministic and content-addressed. It records source lineage, confidence tiers, checkpoint constituent counts, the sealed OOS boundary, and hashes for every emitted member.

## Stage-1 acceptance gate

The membership corpus is accepted only when the exact-head GitHub Actions build proves all of the following:

- pinned source Git blob matches `4aeb5f6046dea43063f9c7be72dfdf16e96d2821`;
- source contains exactly 1,259 membership episodes and 1,206 unique historical tickers;
- rebuilt corpus contains 1,261 episodes and 1,208 unique tickers after the two official 2026 additions;
- constituent count is 487 on 1996-01-02;
- constituent count is 494 on 2001-01-16;
- constituent count is 503 after the 2026-08-05 and 2026-08-18 replacements and on 2026-09-03;
- all emitted files pass deterministic SHA-256 verification;
- the sealed LD-RC OOS boundary remains 1996-01-02 through 2005-12-30.

This is a best-effort PIT universe corpus. Historical membership prior to the official 2026 overlay is supported by the pinned secondary historical series. Security-identity mapping into the canonical Sharadar/SEP corpus is the next construction stage.
