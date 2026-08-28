# Backtester context checkpoint — 2026-08-28 / split adjudication batch 1

Branch: `research/backtester`

Pinned production/main source: `c502d077cae9c494f8b74a41ee8be7f40b25837d`

Production/main remains untouched.

## Current objective

Complete a financially trustworthy A/D chronological replay. A and D share an identical Wealth Core path; D changes only Sentinel peer/sector grouping to strict-prior SEC SIC -> frozen FF12. Economic output must be attributable to frozen strategy execution and causally valid data semantics.

## Terminal corporate-action repairs already certified

Research-only frozen terminal terms currently cover LIT1, CIT.A -> TYC, and GPU. Current terminal digest:

`b9a143e84548e2569391aa8080d75b97034d61187c81f40319f640480fb16a4a`

Three-event verification run `33211232016` is green.

GPU exact settlement: 204,677 shares * $36.50 = $7,470,710.50.

## Full-corpus split integrity finding

Normalization-only run `33213682310` completed successfully across 46,238,394 frozen SEP bars through 2026-07-31 and found 128 unresolved split reconciliations under exact frozen-main semantics.

Artifact ID: `9702956209`

Artifact ZIP SHA256:
`2df5fa78404e41ea437240dd64ce4495e4fcc131f83143c48a3c124b81724cba`

Result JSON SHA256:
`ea821c8c63d463438c8e9e77352957751268e9a357d7d05b11823086c2240feb`

Important economic rule: a split conflict can change Wealth Core before ownership because split-adjusted signal history feeds momentum/ranking/candidate admissions. Holding-date intersection alone cannot certify irrelevance.

## Primary-source split adjudication batch 1

Frozen research dataset:

- `backtester/data/causal-split-overrides-v1.json`
- `backtester/data/causal-split-overrides-v1.SHA256`

Dataset digest:
`8951eb47afef2987b2101a80a9411c0e24356d50813a510c3fee4e773a982a9c`

Strict loader/adjudicator:
`backtester/causal_split_overrides.py`

The overlay preserves the original Sharadar ACTIONS value and the independent SEP-derived witness. It applies the exact legal multiplier only when both frozen witnesses match the adjudication record. The resulting audit disposition is:

`research_primary_source_adjudicated`

Any vendor or SEP witness drift fails closed.

### Batch 1 exact events

1. **MTL — 2008-05-20**
   - security_id `190296`
   - Sharadar stated: `0.5`
   - SEP-derived: `3.0000088894420096`
   - legal multiplier: `3.0`
   - primary evidence: Mechel SEC Form 20-F, ADS ratio 1:3 -> 1:1, two additional ADS per old ADS.
   - source: `https://www.sec.gov/Archives/edgar/data/1302362/000104746908007591/a2186351z20-f.htm`

2. **MTL — 2016-01-12**
   - security_id `190296`
   - Sharadar stated: `3.0`
   - SEP-derived: `0.5`
   - legal multiplier: `0.5`
   - evidence: ADS ratio 1 ADS:1 common -> 1 ADS:2 common.
   - SEC source: `https://www.sec.gov/Archives/edgar/data/1302362/000119312521085807/d29899dex21.htm`
   - issuer report: `https://mechel.com/upload/iblock/7ca/7ca0c375c51d12adc8df55c1b69ae5bc.pdf`

3. **ACER — 2017-09-21**
   - security_id `196508`
   - Sharadar stated: `0.09662`
   - SEP-derived: `0.09996041171813144`
   - exact legal multiplier: `1 / 10.355527 = 0.09656678988910945`
   - SEC confirms 1-for-10.355527 reverse split; post-split ACER began trading 2017-09-21.
   - source: `https://www.sec.gov/Archives/edgar/data/1069308/000156459018004714/R8.htm`

4. **GOLLQ — 2017-11-22**
   - security_id `121549`
   - Sharadar stated: `2.0`
   - SEP-derived: `2.5000000000000004`
   - legal multiplier: `2.5`
   - SEC 6-K: ADS ratio 1 ADS:5 preferred -> 1 ADS:2 preferred; 1.5 additional ADS per old ADS.
   - source: `https://www.sec.gov/Archives/edgar/data/1291733/000129281417002835/gol20171109_6k2.htm`

## Batch 1 verification — SUCCESS

Workflow run: `33218018749`

Job: `99005915032`

Artifact ID: `9704143054`

Artifact ZIP SHA256:
`9257409df2e0082e4207782f03e7fe1a5194fa4246124724eacd371c641f54c2`

Exact frozen-main normalization verified all four events:

- original vendor stated value preserved;
- original frozen SEP-derived value preserved;
- historical permanent security identity resolved;
- exact legal multiplier applied to `VendorBar.split_ratio`;
- disposition exactly `research_primary_source_adjudicated`;
- dataset digest verified.

Do not wire these adjudications into the A/D economic replay until the full-corpus adjudicated normalization audit passes.

## Full-corpus batch-1 reduction gate

Script:
`backtester/diagnostics/scan_full_corpus_unresolved_splits_adjudicated.py`

Workflow:
`.github/workflows/backtester-scan-full-corpus-unresolved-splits-adjudicated.yml`

Run: `33218143982`
Job: `99006285840`

Current state at checkpoint: in progress, scanning full exact normalization path.

Hard acceptance condition:

- bars processed = `46,238,394`
- last session = `2026-07-31`
- adjudicated count = `4`
- unresolved count = `124`

Any other result blocks A/D integration.

## Full 128-event nearby-session classifier

Script:
`backtester/diagnostics/triage_all_unresolved_split_windows.py`

Workflow:
`.github/workflows/backtester-triage-all-unresolved-split-windows.yml`

Run: `33217768333`
Job: `99005149484`

Current state at checkpoint: in progress, reproducing exact 128-event source population.

Classifier examines +/-25 calendar days around each ACTIONS date and separates:

- exact direct match
- exact inverse match
- shifted direct match
- shifted inverse match
- exact no-transition with no nearby match
- unresolved price-domain conflict

This result is required before classifying the 114 apparent no-transition rows as non-events or shifted effective dates.

## Additional primary-source candidates held out of batch 1

These are researched but not yet frozen because exact session classification is still pending.

### SQNS — 2019-11-29

SEC evidence says ADS ratio changed from 1 ADS = 1 ordinary share to 1 ADS = 4 ordinary shares, economically a 1-for-4 ADS consolidation. Legal multiplier `0.25`, matching frozen SEP. Sharadar states `0.4`.

Sources:
- `https://www.sec.gov/Archives/edgar/data/1383395/000119312520311743/d16684d424b5.htm`
- `https://www.sec.gov/Archives/edgar/data/1383395/000119312520140667/d865094d424b2.htm`

### PTIX — 2016-07-27

SEC confirms a 1-for-15,463.7183 reverse split effective 2016-07-27. Exact multiplier approximately `0.0000646674997953112`. Sharadar states `0.00006`; SEP derived approximately `0.00006500260010400415`.

Sources:
- `https://www.sec.gov/Archives/edgar/data/1022899/000143774917001988/atrn20170207_424b3.htm`
- `https://www.sec.gov/Archives/edgar/data/1022899/000119312516462444/d128148d8k.htm`

### NEOM — 2014-05-29

SEC corporate evidence establishes a 1-for-15 reverse split; exact multiplier `1/15`. A historical custodian corporate-action notice identifies 2014-05-29 as effective trading date. Sharadar states `0.06667`; SEP appears ~1/14 because of price-domain rounding/representation.

Sources:
- `https://www.sec.gov/Archives/edgar/data/1022701/000114420414029543/v378319_8k.htm`
- Citibank historical corporate announcement page identifying 2014-05-29 effective date.

### ONSM — 2003-06-24

SEC confirms 1-for-9 reverse split on 2003-06-24. Exact multiplier `1/9`. Sharadar states `1/6`; SEP derived `1/15`, so the legal source is necessary.

Source:
`https://www.sec.gov/Archives/edgar/data/1034842/000110465903026474/a03-5217_110q.htm`

## Shared-Wealth-Core acceleration

Accelerated runner:
`backtester/run_sector_ad_shared_wealth_core.py`

Contract:

- A executes real frozen-main `plan_session()` once.
- D receives an exact deep-copied post-plan Wealth Core state/plan.
- D continues independent Sentinel/controller/LD-RC logic.
- A/D pre-plan equality and post-session Wealth Core parity fail closed.

Current equivalence run:
`33217309808`
job `99003711529`

At checkpoint: in progress, bounded baseline step.

A pre-2001 bounded-test plumbing problem was fixed in commit:
`19ac4b2caf9e29656e3c54ad2856ec9f606b9906`

The fix excludes frozen 2001 terminal records only from a 1998-only equivalence window. Full replay terminal handling is unchanged.

No acceleration claim is valid until baseline and optimized paths are byte-identical and plan-call counts prove one real + one reused Wealth Core plan per session.

## Other active long jobs

- A/D replay v2: run `33210946520`, job `98983779472`, in progress.
- allocation-boundary unresolved-open scanner: run `33196508963`, job `98934905157`, in progress.
- comprehensive held-terminal-gap scanner: run `33211049538`, job `98984067249`, in progress.

These older runs do not contain split adjudication batch 1. They remain useful for progress/terminal-gap evidence, but they cannot become the final certified A/D result while unresolved split conflicts remain.

## Required next actions

1. Check `33218143982`. Integrate batch 1 into the research A/D runner only if the exact 128 -> 124 gate passes.
2. Check `33217768333`; use its complete classification before handling the remaining no-transition population.
3. Check `33217309808`; certify or repair shared-Wealth-Core acceleration.
4. Promote SQNS/PTIX/NEOM/ONSM only after their exact session/corpus witnesses are confirmed by the full classifier and the adjudication record has a defensible causal availability date.
5. Continue primary-source research for the remaining material conflicts. Never globally invert ACTIONS values and never globally trust SEP-derived ratios.
6. Resolve all economically reachable split conflicts before calling any final CAGR/Sharpe authoritative.
7. Preserve future work in the next checkpoint before context turnover.
