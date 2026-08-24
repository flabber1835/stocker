# Correct PIT sector A/B — root cause and status

Research-only record for the replacement of retracted issue #241. Nothing here changes `main`, production strategy semantics, or the deployed NAS.

## Root cause of the apparent 22.63% -> 18.48% CAGR drop

The drop was **not a PIT-sector effect**. The experiment was invalid because its control had already diverged before sector was changed.

Authoritative current Simplified Concordance LD-RC fingerprint (30pp parent):

- 20Y CAGR: **22.6302156206%**
- Sharpe: **1.2138138710**
- max drawdown: **-21.6958215101%**
- ending multiple: **59.1542869097x**
- sessions: **5,032**

Retracted #241 first-pass, same 30pp threshold:

- inherited #241 base + current Sharadar sector: **18.43172395% CAGR**
- same inherited #241 base + causal SEC SIC->FF12: **18.47948391% CAGR**
- actual sector-only difference inside that invalid harness: **+0.04775996 percentage points/year**

Therefore the apparent `22.6302 -> 18.4795` difference cannot be attributed to PIT sector. The roughly **-4.20 pp/year discontinuity was already present in the nominal current-sector control**.

## Why the #241 control was not the current system

Two classes of control violation are established.

### 1. Sector grouping semantics were changed even on the supposed control

Missing current Sharadar sector values were transformed from the authoritative shared `Unknown` bucket into per-security singleton keys such as `UNK:<id>`. That is not the current strategy's breadth semantics.

This is a concrete control violation. It proves the control was not a faithful replay, although it is not by itself claimed to explain the entire 4.20 pp/year gap.

### 2. The experiment started from an already-mutated intermediate PIT tape

`sector_market_experiment.py` did not start from the authoritative 22.63% current-system tape. Its base was the transient local file:

`/mnt/data/pit_exp_currentcat_ff12_out/sentinel_1p1_daily.csv`

That tape came from an earlier research lineage that had already changed upstream metadata/universe treatment. The retained label described it as a category-free quantitative universe with SEC PIT issuer treatment and strict-before SIC reconstruction. Thus the later sector A/B held the wrong base fixed.

The branch also failed to retain several load-bearing transient generator/input files as bytes; only their `/mnt/data` paths and hashes survived. That prevented full forensic reconstruction of every contribution to the 22.63 -> 18.43 mismatch.

## Confirmed upstream sensitivity from PR #208

PR #208 separately demonstrated one concrete way an over-strict PIT reconstruction can alter the strategy before the measured window begins.

Correct causal issuer policy:

- preserve the unsupported 1998-2005 warm-up behavior;
- switch to SEC PIT issuer authority only when SEC evidence exists (from 2006-01-04);
- result: **zero changed trades and zero performance delta**, preserving 22.6302156206%.

Rejected strict-precoverage sensitivity:

- applies SEC-mode treatment before causal SEC evidence exists;
- 20Y CAGR: **21.34915344%** versus 22.63021562% control;
- effect: **-1.28106218 pp/year**.

This is a confirmed material upstream mechanism, not a claim that it alone explains the whole invalid #241 gap.

## Consequence

The following #241 headline results are retracted as production-relevant estimates:

- 18.43% current-sector control;
- 18.48% SEC-FF12 PIT-sector result;
- 20.11% dynamic-peer result;
- the symbolic ceilings/alpha budget derived from that altered base.

They may remain useful only as internal relative experiments on that altered tape.

## Correct experiment contract

The replacement experiment must:

1. reproduce the authoritative **22.6302156206%** current-sector control first;
2. preserve current Wealth Core shadow/trades, current category semantics, accepted PR #208 issuer PIT boundary, recent-leadership witness, controller state, LD-RC state, execution timing, BIL accounting and costs;
3. change **only** the sector authority used for breadth escalation;
4. use strictly point-in-time SEC SIC evidence (`filed < decision session`) mapped through the frozen FF12 table;
5. report first session of divergence plus 5Y/10Y/15Y/20Y CAGR, Sharpe, max drawdown, allocation transitions and daily tape hashes;
6. refuse to publish a sector result if the A-side control fails the 22.6302156206% calibration.

## SEC SIC input now retained through GitHub Actions

The corrected branch has a successful `SEC PIT reconstruction` run at head `5fad3375d3fa2c108f16a71ddfe10d52014f6f72`.

Retained artifact:

- name: `corrected-pit-sec-sic-tape`
- artifact id: `9504961483`
- artifact digest: `sha256:61d1b572bbb8b9c7efddae00c4573a85d4ce3562d5dfac4af1d9c66620882028`
- workflow run: `32683774522`

The tape contains `sec_sic_submissions.csv` plus provenance and is derived from the public SEC mirror with the mirror database file SHA-256 pinned by the workflow.

## Current status

- #241: **closed/retracted as invalid**.
- This corrected branch / draft PR #242: **research-only, not for merge**.
- Root cause: **resolved at the methodological/control level** — 18.48% was never a valid sector-only comparison to 22.63%.
- Corrected PIT-sector B-side performance: **not yet published**. It must be generated only after the A-side reproduces the authoritative control under the contract above.
