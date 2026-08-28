# Backtester PIT certification checkpoint — 2026-08-28 / 07

## Scope and immutable production source

All work described here is research-only on `research/backtester`.

Pinned production/main source used for the replay and financial semantics:

`c502d077cae9c494f8b74a41ee8be7f40b25837d`

Commit message: `Make Sentinel GO certification fail-fast and observable (#278)`.

`main` has not been modified by this work.

## Certification objective

The target is a financially defensible causal/PIT economic replay of the current strategy.

Variant A is the exact current-main Sharadar-sector control.

Variant D uses the exact same Wealth Core path and applies strict-prior SEC SIC -> FF12 grouping at the Sentinel peer/breadth seam. A/D Wealth Core holdings, trades, shares, cash, prices and Wealth Core state must remain identical every session.

The final replay is certifiable only after every input capable of changing the economic path is causal, exactly reconstructed, primary-source adjudicated, or proven economically irrelevant.

## Terminal/corporate-action repairs already verified

Research-only frozen terminal terms currently cover:

- LIT1 / Litton: $80.00 cash/share, effective 2001-05-30.
- CIT.A / CIT Group: 0.6907 TYC shares per CIT share, effective 2001-06-01, exact whole-share conversion plus fractional cash-in-lieu.
- GPU: $36.50 cash/share no-election settlement, causal known-by 2001-11-06.

GPU proof: 204,677 shares -> exactly $7,470,710.50 cash and holding extinguished.

Current terminal bundle digest from the earlier checkpoint chain:

`b9a143e84548e2569391aa8080d75b97034d61187c81f40319f640480fb16a4a`

The terminal verification/integration chain is green for these repaired events.

## Full-corpus split audit

Fast normalization-only audit run:

- Workflow run: `#33213682310`
- Bars processed: `46,238,394`
- Last session: `2026-07-31`
- Initial unresolved split reconciliations: `128`

The exact 128-event population is durably retained in:

`backtester/data/full-corpus-unresolved-splits-2026-08-28.csv`

This is important because unresolved splits can affect Wealth Core before ownership by altering momentum, ranking, admissions and later path-dependent state. Holding intersection alone is not a sufficient certification criterion.

## Complete 128-event nearby-session classification

Workflow run:

`#33217768333`

Result: PASS.

Classification counts:

- `44` shifted direct matches
- `4` shifted inverse matches
- `3` exact inverse matches
- `66` exact no-transition / no-nearby-match cases
- `11` unresolved price-domain conflicts

Interpretation:

- The 51 shifted/inverted-match events have a clear relationship between ACTIONS and SEP price-domain evidence. Their event-date/orientation semantics require durable causal treatment before final certification.
- The 66 no-transition cases need classification of the underlying corporate action type. Some may represent stock dividends or other share-count events that do not appear as a conventional SEP split transition.
- The 11 price-domain conflicts require direct adjudication from authoritative source evidence.

Examples of exact/shifted inverse evidence already found include AZN 1998-04-08, NCRI 2003-06-16 and ETELY 2007-09-04.

## Primary-source split adjudication batch 1

A research-only adjudication mechanism was added with checksum and frozen-corpus witness binding:

- `backtester/causal_split_overrides.py`
- `backtester/data/causal-split-overrides-v1.json`
- `backtester/data/causal-split-overrides-v1.SHA256`

Dataset digest:

`8951eb47afef2987b2101a80a9411c0e24356d50813a510c3fee4e773a982a9c`

Four events are primary-source adjudicated and independently verified:

1. MTL — 2008-05-20
   - original Sharadar stated value: `0.5`
   - frozen SEP derived witness: `3.0000088894420096`
   - legal multiplier: `3.0`
   - security_id: `190296`

2. MTL — 2016-01-12
   - original Sharadar stated value: `3.0`
   - frozen SEP derived witness: `0.5`
   - legal multiplier: `0.5`
   - security_id: `190296`

3. ACER — 2017-09-21
   - original Sharadar stated value: `0.09662`
   - frozen SEP derived witness: `0.09996041171813144`
   - legal multiplier: `0.09656678988910945`
   - security_id: `196508`

4. GOLLQ — 2017-11-22
   - original Sharadar stated value: `2.0`
   - frozen SEP derived witness: `2.5000000000000004`
   - legal multiplier: `2.5`
   - security_id: `121549`

Verification workflow:

`#33218018749` — PASS.

Each event retains the original Sharadar value and SEP witness and records the applied legal multiplier with disposition:

`research_primary_source_adjudicated`

## Full-corpus adjudicated split gate

Workflow run:

`#33218143982`

Result: PASS.

The exact same `46,238,394` bars through `2026-07-31` were normalized with the four adjudications active.

Required reduction occurred exactly:

- adjudicated: `4`
- unresolved before: `128`
- unresolved after: `124`

This proves batch 1 changes exactly the four intended split dispositions across the complete frozen corpus.

## Remaining genuine price-domain conflicts

The 128-event classifier found 11 unresolved price-domain conflicts. Four are already repaired by batch 1. Seven therefore remain in this highest-priority class.

Known names in the 11-event set include:

- DAYR 1998-03-18
- ONSM 2003-06-24
- MTL 2008-05-20 — repaired
- PRTK 2009-02-06
- NEOM 2014-05-29
- MTL 2016-01-12 — repaired
- PTIX 2016-07-27
- PRPO 2017-06-06
- ACER 2017-09-21 — repaired
- GOLLQ 2017-11-22 — repaired
- SQNS 2019-11-29

Primary evidence already located but not yet promoted into the frozen adjudication dataset:

- SQNS: 1-for-4 ADS consolidation evidence.
- PTIX: 1-for-15,463.7183 share treatment evidence.
- NEOM: 1-for-15 reverse split evidence.
- ONSM: 1-for-9 reverse split evidence.

Do not promote these until exact issuer identity, effective trading session, causal known-by boundary and frozen SEP/ACTIONS witnesses are all bound in the same way as batch 1.

## Research replay launcher with split adjudication

Dormant launcher prepared:

`backtester/run_sector_ad_causal_terminal_splits_v3.py`

This is intentionally disconnected from the active A/D workflow at this checkpoint.

Its role is to combine:

- exact pinned main strategy source,
- A/D v2 semantics,
- causal terminal-term overlay,
- research primary-source split adjudication,
- result-manifest provenance for both frozen datasets.

Do not use v3 for authoritative headline results until the remaining split/corporate-action certification work is closed and acceleration equivalence is green.

## Shared-Wealth-Core acceleration

Goal: execute the expensive Wealth Core plan once per session and reuse the exact post-Wealth-Core state/plan for D, while running the separate Sentinel/controller/LD-RC branches normally.

Equivalence workflow:

`#33217309808`

Current state at this checkpoint:

- setup: PASS
- bounded final split-audit seam: PASS
- baseline through 1998-12-31: PASS
- accelerated arm: currently running
- byte-identical economic path comparison: pending

The previous failed equivalence attempt reached a harness-only off-axis terminal-event problem. That bounded pre-2001 issue was corrected before run #33217309808.

No speedup may be treated as certified until the final byte-identical comparison passes.

## Active long-running economic/scanner jobs

### A/D replay v2

Run: `#33210946520`

Status at this checkpoint: `in_progress`.

This is the existing chronological A/D replay with the verified terminal repairs. It predates split-adjudication v3 and is preserved for diagnostic continuity.

### Original unresolved-open scanner

Run: `#33196508963`

Status: `in_progress`.

Purpose: locate allocation-transition sessions where exact Wealth Core open equity cannot be resolved.

### Comprehensive held-terminal scanner

Run: `#33211049538`

Status: `in_progress`.

Purpose: record every held unresolved terminal/open gap, including economically relevant gaps that may not immediately coincide with a Sentinel allocation transition.

Do not cancel either scanner. Their outputs answer different questions.

## Important certification principles established

1. A split conflict can change the strategy before ownership through momentum/ranking/admissions.
2. Corporate-action repair must be identity-bound; historical ticker reuse makes ticker-only primary-source research unsafe.
3. A primary-source adjudication must preserve the original vendor assertion and independent price-domain witness in the evidence bundle.
4. Research overrides are accepted only when checksum, security identity, effective session, causal known-by date, original Sharadar value and expected frozen SEP witness all match.
5. A/D Wealth Core parity is mandatory every session.
6. No final CAGR/Sharpe/drawdown result is certifiable while an economically reachable unresolved data boundary remains.
7. The final accurate label for D is `certified causal/PIT economic replay` once all gates close.

## Exact next actions

1. Finish shared-Wealth-Core equivalence run `#33217309808`. If byte-identical, use the accelerated computation path for subsequent certification replays.
2. Let terminal scanners `#33196508963` and `#33211049538` finish. Research and freeze any additional held corporate-action terms they identify.
3. Resolve the seven remaining genuine price-domain split conflicts with issuer-bound primary sources and add them in small verified batches.
4. Work through the 51 shifted/inverted-match events and determine the correct event-date/orientation semantics with causal evidence.
5. Investigate the 66 no-transition cases by corporate-action type, especially potential stock-dividend/share-distribution semantics.
6. After each split-adjudication batch, rerun the full `46,238,394`-bar normalization audit and require the unresolved count to decrease by exactly the number of newly adjudicated events.
7. Once the split population and terminal-gap population are fully closed, activate the v3 replay path.
8. Run the full chronological A/D replay from 1998-01-02 through 2026-07-31 with all fail-closed gates active.
9. Produce final 5/10/15/20-year CAGR, Sharpe, max drawdown, final multiple and SPY comparison only from the fully certified result bundle.

## Current conclusion

The PIT certification boundary has materially narrowed.

The split population is now fully enumerated and structurally classified. Four genuine conflicts are primary-source repaired and full-corpus verified. The remaining work is finite and explicitly categorized. Final PIT economic metrics are still pending completion of the remaining split adjudications, terminal scanners, and runner-equivalence gate.
