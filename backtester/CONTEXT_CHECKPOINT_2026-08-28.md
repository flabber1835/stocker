# Backtester context checkpoint — 2026-08-28

This file is the durable handoff for the current A/D causal/PIT historical replay work. It records conclusions, evidence, design decisions, active runs, known caveats, and next actions so a new context window can continue without reconstructing the investigation.

## Objective and non-negotiable standard

The objective is a trustworthy historical A/D comparison whose economic output is attributable to the frozen strategy and historical market data.

Accuracy requirements:

- Execute a fresh chronological replay. No prerecorded holdings, decisions, allocations, NAV, crisis schedule, or future-derived strategy state.
- Preserve exact next-open timing for Sentinel allocation changes.
- Use source-backed corporate-action economics. Never fabricate missing open prices or settlement terms.
- Preserve frozen Wealth Core mechanics, prices, accounting, ranking, admissions, exits, sizing, and execution semantics.
- Any speed optimization must prove economic equivalence before being used for an authoritative result.
- Research changes stay on `research/backtester`. Production `main` is untouched.

## Frozen production source

All current replay work pins production strategy source to:

`c502d077cae9c494f8b74a41ee8be7f40b25837d`

Commit message: `Make Sentinel GO certification fail-fast and observable (#278)`.

The GitHub workflows check out that commit separately as read-only `main-src` and verify its identity before replay.

## A/D experiment semantics

### A

Current-main/current-Sharadar-metadata control. Sentinel sector contagion uses current Sharadar sector grouping.

### D

Retained best-effort causal/PIT economic variant.

Current D v2 implementation keeps the Wealth Core path exactly equal to A and applies the economically active metadata correction at Sentinel's grouping seam:

- sector: strict-prior SEC CIK/SIC evidence -> frozen FF12 grouping;
- missing causal sector: singleton `UNKNOWN:<security_id>` peer;
- category: retained prior research proved zero Wealth Core/economic delta when removed from the historical path;
- issuer family: retained SEC-CIK causal authority work proved zero primary A/B economic delta after the causal boundary;
- exchange: inert/non-authoritative in this path.

Important wording: D v2 is an **economically equivalent implementation of the retained best-effort PIT treatment under current evidence**. It does not literally inject causal replacements for category/issuer/exchange into Wealth Core on every session. The reason those duplicate mutations are absent is the retained zero-economic-delta evidence. Sector is the active historical metadata difference.

## Conceptual architecture established

For this experiment:

`historical data -> Wealth Core book -> Sentinel variant -> LD-RC -> exposure/NAV`

A and D share the same Wealth Core book by experiment design. They may differ only in Sentinel's sector/peer-stress interpretation and subsequent Sentinel/LD-RC exposure decisions.

Therefore the required A/D invariants are:

- same Wealth Core holdings;
- same Wealth Core shares;
- same Wealth Core cash;
- same Wealth Core trades and settlement;
- same Wealth Core prices;
- same Wealth Core path-dependent state;
- separate Sentinel state and overlay NAV are allowed to differ.

The base runner already calls `state_wc_parity(state_a, state_b, session)` every session and fails immediately if shared economic state diverges.

This architecture is specific to Sentinel-only variants. A future variant that changes Wealth Core eligibility, ranking, sizing, exits, admissions, signals, or other Wealth Core inputs/mechanics would require its own Wealth Core path.

## Fresh A/D v2 replay that failed

Workflow run:

- run: `33176809574`
- job: `98867447731`
- workflow: `Backtester - sector A/D fresh replay v2`
- branch SHA: `711f45d3b61dc74c0ae119091965a4139396c2fc`
- URL: `https://github.com/flabber1835/stocker/actions/runs/33176809574`

The v2 fix successfully crossed the earlier 1998-07-06 Wealth Core parity failure and also crossed the original 2001-06-04 unresolved-open boundary.

### Valid cumulative checkpoints from the failed run

CAGR is cumulative NAV from `1998-01-02`, annualized by exact elapsed calendar days using 365.2425 days/year.

| Session | Sessions | A multiple | A CAGR | D multiple | D CAGR |
|---|---:|---:|---:|---:|---:|
| 1998-04-02 | 63 | 1.0000000000 | 0.0000000000% | 1.0000000000 | 0.0000000000% |
| 1998-07-02 | 126 | 1.0000000000 | 0.0000000000% | 1.0000000000 | 0.0000000000% |
| 1998-10-01 | 189 | 0.9185423791 | -10.7826167170% | 0.9185423791 | -10.7826167170% |
| 1998-12-31 | 252 | 1.0975759104 | 9.8207381956% | 1.0975759104 | 9.8207381956% |
| 1999-04-05 | 315 | 1.3700452765 | 28.5412049299% | 1.3700452765 | 28.5412049299% |
| 1999-07-02 | 378 | 1.3951498507 | 24.9519418512% | 1.3951498507 | 24.9519418512% |
| 1999-10-01 | 441 | 1.3814896254 | 20.3572897209% | 1.3814896254 | 20.3572897209% |
| 1999-12-31 | 504 | 2.2027187861 | 48.6157599633% | 2.2027187861 | 48.6157599633% |
| 2000-03-31 | 567 | 2.6384092568 | 54.1354017681% | 2.6384092568 | 54.1354017681% |
| 2000-06-30 | 630 | 2.6384092568 | 47.6087691721% | 2.6384092568 | 47.6087691721% |
| 2000-09-29 | 693 | 2.6384092568 | 42.4748886678% | 2.6384092568 | 42.4748886678% |
| 2000-12-29 | 756 | 2.6384092568 | 38.3333196682% | 2.6384092568 | 38.3333196682% |
| 2001-04-02 | 819 | 2.6384092568 | 34.8208998347% | 2.6384092568 | 34.8208998347% |
| 2001-07-02 | 882 | 2.7632255660 | 33.7371792581% | 2.7632255660 | 33.7371792581% |
| 2001-10-05 | 945 | 2.5661664540 | 28.5157700540% | 2.5661664540 | 28.5157700540% |

At the last completed checkpoint A and D were still economically identical. Retained prior work indicates the first sector-driven damaged-breadth difference appears later, with first retained allocation change in 2011, so equality this early is expected.

These partial numbers are diagnostic continuity evidence only. They are not final/certified A/D results because the replay failed before completion.

## Original 2001-06-04 corporate-action blocker and repair

Earlier replay failed on `2001-06-04` because Sentinel needed an allocation change at an open where Wealth Core open equity was unresolved.

Unresolved holdings were:

- `CIT.A`, security_id `122131`, 295,584 shares;
- `LIT1`, security_id `120448`, 116,977 shares.

Source-backed repair terms were assembled and frozen in:

- `backtester/data/causal-terminal-terms-v1.json`
- `backtester/data/causal-terminal-terms-v1.SHA256`

Pinned term bundle SHA256:

`f93a3ac12452f2f29a9c57ee93474ce14a44c51d2e81b538a3e150e9089129c9`

### LIT1 / Litton

- cash merger;
- each Litton common share -> exactly `$80.00` cash;
- completed May 30, 2001;
- frozen effective session `2001-05-30`;
- `known_by=2001-04-30`.

### CIT.A / CIT Group

- each CIT share -> `0.6907` Tyco common shares;
- effective `2001-06-01`;
- delivered security `TYC`, security_id `573113`;
- fractional entitlement paid in cash using Tyco close on preceding trading day;
- frozen CIL witness price `57.45`, causal by `2001-05-31`.

For 295,584 CIT shares the exact entitlement is:

- 204,159 whole TYC shares;
- fractional entitlement 0.8688;
- cash in lieu `$49.91256`.

Integration verification proved the repair and the A/D v2 replay emitted:

`[PASS] 2001-06-04 Wealth Core open resolved exactly: 242839480.805039`

So the 2001-06-04 repair is working and is not the cause of the later failure.

## Current later crash

After the `2001-10-05` checkpoint, run `33176809574` failed again with:

`RuntimeError: A allocation transition coincides with unresolved Wealth Core open; exact next-open attribution is impossible`

This is another unresolved historical open/corporate-action boundary in A. It is independent of the A/D PIT-sector difference.

The guard is intentional and should remain. If an allocation changes at the open, the runner needs exact Wealth Core open equity. Close-to-close substitution would contaminate next-open economic attribution.

## Active focused diagnostic

Focused diagnostic workflow:

- run `33191669062`
- job `98918416889`
- URL: `https://github.com/flabber1835/stocker/actions/runs/33191669062`
- status at this checkpoint: in progress, step `Run A-only diagnostic`.

Purpose:

- replay A only with the frozen terminal overlay;
- stop at the next unresolved-open allocation boundary;
- capture exact failing session;
- capture unresolved security IDs and holdings;
- capture terminal source rows/events;
- capture nearby ACTIONS and SEP history;
- provide detailed evidence for the specific next repair.

File:

`backtester/diagnostics/unresolved_open_with_terminal_overlay.py`

This diagnostic remains useful even though a broader scanner is being developed because it collects richer evidence around the immediate failure.

## Acceleration work

### Observation

The base A/D runner performs two full `production.advance_state()` calls per session. Inside each call, production reconstructs Wealth Core state/feed and calls `plan_session()` before performing Sentinel breadth/controller/LD-RC logic.

Because the A/D experiment requires exact Wealth Core equality, running the expensive Wealth Core plan twice is redundant.

Production flow confirmed from frozen `sentinel/core/production.py`:

1. reconstruct PortfolioState/pending/ledger/feed;
2. call `plan_session(...)` — Wealth Core;
3. build holdings using `published.sectors`;
4. calculate breadth;
5. controller/native allocation;
6. Concordance witness + LD-RC;
7. persist the resulting SessionState.

The sector map is consumed after `plan_session()`, at the Sentinel holdings/breadth seam. This makes `plan_session()` the correct research-side acceleration seam for A/D.

### Shared-Wealth-Core accelerated runner

File:

`backtester/run_sector_ad_shared_wealth_core.py`

Current design:

- A executes the real frozen-main `production.plan_session()`.
- Before A executes, snapshot the complete mutable Wealth Core inputs: PortfolioState, pending orders, Ledger, last-known marks, and Feed.
- After A executes, snapshot the complete mutated Wealth Core objects and deep-copy the returned `LiveSessionPlan`.
- D reaches the same `plan_session()` call.
- Fail closed unless D's complete pre-plan Wealth Core objects are equal to A's pre-plan objects.
- Transplant the exact A post-plan mutable objects into D.
- Return a deep-copy of A's exact `LiveSessionPlan` to D.
- D then continues through the normal frozen production Sentinel/controller/Concordance/LD-RC code using D's FF12 sector map.
- The base runner's existing `state_wc_parity()` remains active after both full production state transitions.
- Exactly two plan calls per session are required: one real A call and one reuse D call.

This optimization changes computation reuse only. It does not change market sessions, bars, prices, signals, ranking, holdings, shares, trades, settlement, cash, accounting, Sentinel logic, LD-RC logic, or PIT sector rules.

### Equivalence gate

Workflow:

`.github/workflows/backtester-shared-wealth-core-equivalence.yml`

Latest corrected run:

- run `33196651817`
- URL: `https://github.com/flabber1835/stocker/actions/runs/33196651817`

The workflow performs:

1. baseline replay through `1998-12-31` using the original two-Wealth-Core-call runner;
2. accelerated replay through the same date;
3. byte comparison of deterministic `daily.csv.gz`;
4. byte comparison of `metrics.csv`;
5. SHA256 comparison and exact expected session-row count;
6. elapsed-time measurement for baseline and optimized paths.

Acceptance rule: the optimization is not authoritative until economic outputs are identical.

Important validation caveat for a future context: the first bounded equivalence run covers 252 sessions in 1998, before known A/D sector decisions diverge. It proves reuse correctness over that tested interval and exercises nontrivial Wealth Core state. Before calling acceleration fully certified for the 20-year A/D experiment, extend equivalence confidence through a period where A and D Sentinel state actually diverge, or complete a full run with all parity gates active. The structural seam is strong because D continues through normal production Sentinel logic and the shared-WC input-equality/parity assertions remain active, but the bounded test alone should not be overstated.

## Full unresolved-open scanner

Repeated multi-hour replays were discovering one unresolved-open boundary at a time. A scanner has been added to discover all such boundaries in one chronological traversal.

Files:

- `backtester/diagnostics/scan_all_unresolved_open_boundaries.py`
- `.github/workflows/backtester-scan-all-unresolved-open.yml`

Latest corrected run:

- run `33196508963`
- URL: `https://github.com/flabber1835/stocker/actions/runs/33196508963`

Scanner semantics:

- exact frozen production A transition;
- frozen causal terminal overlay applied;
- second arm collapsed onto A to avoid duplicate strategy computation;
- on an unresolved-open allocation boundary, record session, unresolved IDs, holdings, terminal state and targets;
- continue production-state traversal to find later boundaries.

After the first unresolved-open boundary, research OverlayAccount NAV is explicitly non-authoritative. This is acceptable for the scanner because production Wealth Core/Sentinel state does not consume the research overlay NAV. The scanner is a defect-discovery tool and must never publish its post-boundary NAV as an economic backtest result.

The first scanner launch failed immediately before market processing due to an import wiring error (`runner.production`). It was corrected to import `sentinel.core.production` directly. No market result from the failed launch is relevant.

## Why the scanner and focused diagnostic both run

They serve different purposes:

- focused diagnostic `33191669062`: detailed forensic evidence for the immediate next 2001 failure;
- full scanner `33196508963`: complete list of remaining unresolved-open boundaries across the historical path;
- equivalence workflow `33196651817`: validates computation acceleration.

They use separate GitHub-hosted runners and can run concurrently.

## Additional safe optimization ideas

### 1. Immutable normalized SEP replay cache

Current `raw_sep_rows()` re-reads each annual compressed Sharadar SEP file with pandas, validates the source hash, sorts `(date,ticker,_seq)`, applies keep-last duplicate semantics, and yields canonical rows every fresh replay.

A safe future optimization is a generated immutable normalized replay corpus with:

- exact source-file SHA bindings;
- exact normalization-code SHA binding;
- deterministic row ordering;
- exact raw fields required by production normalization;
- deterministic artifact checksum.

The cached representation must be validated against the current normalizer before use. This can eliminate repeated gzip decode, pandas parsing, sorting, and de-duplication without changing economic inputs.

### 2. Exact checkpoint/resume

A future replay should write periodic restart checkpoints containing enough state to resume identically:

- complete A and D `SessionState.to_dict()`;
- A and D OverlayAccount state (`nav`, `effective`, `pending`, transitions/cost);
- prior core close;
- prior split factors;
- seen counts;
- prior signal closes / latest ticker state required by runner;
- session pointer;
- frozen input hashes;
- pinned main SHA;
- research runner SHA;
- terminal-term bundle SHA;
- output prefix/hash commitment up to checkpoint.

Resume must first verify all hashes and state schema, then continue at the next session. A resumed run should be compared against a continuous run over a bounded interval before being accepted.

This optimization does not reduce CPU per session but prevents a late defect or infrastructure failure from forcing a restart from 1998.

### 3. Profile before lower-level micro-optimization

After shared Wealth Core is validated, profile the accelerated runner. Likely remaining costs include:

- SEP gzip/pandas load/sort/de-dup;
- construction/serialization of bounded SessionState feed images;
- repeated full-universe feed/eligibility/scoring work;
- SEC FF12 lookup overhead (already cached by `(sid, session)` but may still have opportunities);
- output serialization.

Do not optimize these speculatively if the change could alter ordering, floating-point operations, or state semantics. Require deterministic equivalence tests.

## Unsafe speedups to reject

Do not use:

- sampled trading sessions;
- skipped quiet days;
- reduced stock universe;
- approximate corporate-action settlement;
- substituted close for missing open;
- synthetic/fabricated prices;
- prerecorded historical decisions/holdings/NAV;
- future/current metadata projected backward where the experiment claims PIT;
- simplified Wealth Core accounting;
- changed execution timing;
- changed strategy parameters.

Those alter the experiment or its economic attribution.

## Retained historical results for continuity only

Archived older research (not the current fresh authoritative replay) found:

- A 20y CAGR `22.6302156206%`, Sharpe `1.213813871`, max DD `-21.6958215%`, ending multiple `59.1542869x`;
- best-effort PIT historical result about `21.64%` CAGR, Sharpe `1.164`, max DD about `-27.68%`;
- category-free: zero changed Wealth Core buys, NAV sessions, native allocation sessions, final allocation sessions;
- SEC-PIT issuer authority: zero primary A/B economic delta after causal boundary;
- sector PIT first damaged-breadth change retained at `2006-08-11`;
- first retained allocation change `2011-10-31`.

These are background/provenance references. The current objective remains a fresh chronological A/D replay with the repaired terminal-action path.

Archived provenance branch:

`research/correct-pit-sector-ab-2026-08-23`

Files include:

- `research/correct-pit-metadata-ab/RESULTS.md`
- `research/correct-pit-metadata-ab/PROVENANCE.md`
- `research/correct-pit-metadata-ab/parity.json`

## Immediate next actions

1. Read the focused diagnostic `33191669062` when complete. Identify the exact next security/event and source-backed settlement terms.
2. Read full scanner `33196508963` when complete. Build one complete repair queue of every unresolved-open boundary.
3. Add source-backed causal terminal terms for all proven missing events to the frozen terminal-term bundle, with checksum/schema/identity/price-witness validation.
4. Re-run terminal integration tests after every bundle expansion.
5. Read equivalence run `33196651817`. Record baseline vs optimized elapsed time and exact output hashes.
6. If equivalence fails, diagnose the first divergent field/session; do not use the accelerated runner.
7. If equivalence passes, extend validation confidence beyond 1998, ideally through a period with actual A/D Sentinel divergence while Wealth Core remains identical.
8. Implement exact checkpoint/resume after the shared-WC seam is stable.
9. Consider a hash-bound normalized SEP cache after profiling confirms I/O/normalization is material.
10. Launch the fresh full A/D replay only after the known unresolved terminal holes are repaired and acceleration has passed its equivalence gates.
11. Final results are authoritative only after full completion and result-bundle/hash verification. Never promote partial-run CAGR as a certified result.

## Current research files of interest

- `backtester/experiments/2026-08-27-sector-abc/run.py` — base fresh chronological A/B runner used as the research engine.
- `backtester/run_sector_ad_causal_terminal_terms_v2.py` — current A/D wrapper with causal terminal overlay and 63-session CAGR checkpoints.
- `backtester/run_sector_ad_shared_wealth_core.py` — accelerated shared-Wealth-Core implementation under validation.
- `backtester/causal_terminal_terms.py` — strict loader/validator/merger for frozen exact terminal terms.
- `backtester/data/causal-terminal-terms-v1.json` — frozen terminal evidence bundle.
- `backtester/data/causal-terminal-terms-v1.SHA256` — checksum binding.
- `backtester/diagnostics/unresolved_open_with_terminal_overlay.py` — focused next-boundary diagnostic.
- `backtester/diagnostics/scan_all_unresolved_open_boundaries.py` — full-history unresolved-open scanner.
- `.github/workflows/backtester-sector-ad-v2.yml` — full v2 A/D replay workflow.
- `.github/workflows/backtester-unresolved-open-terminal-overlay.yml` — focused diagnostic workflow.
- `.github/workflows/backtester-scan-all-unresolved-open.yml` — full unresolved-open scanner workflow.
- `.github/workflows/backtester-shared-wealth-core-equivalence.yml` — acceleration equivalence workflow.

## Interpretation discipline

A failed/partial replay can establish local facts such as state equality, corporate-action repair success, or a cumulative NAV checkpoint through the last completed session. It cannot establish final 5/10/15/20-year CAGR, Sharpe, drawdown, or variant superiority.

The final A/D comparison must come from one fully completed chronological replay, with frozen-source provenance and verified output hashes.
