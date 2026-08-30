# Forward-bias certification runbook

This runbook defines the fail-closed procedure for certifying retained-research backtests as causally executable and free of forward-observation dependence.

It is intentionally separate from research/production economic equivalence. A causal certificate can pass while an equivalence run still finds a research/production logic mismatch.

## Certified reference result

The bounded 2006-2007 retained-research proof is the reference implementation of this procedure.

- Verdict: `PASS`
- GitHub Actions run: `33337390544`
- Certified source SHA: `ee613775aaa7542e731a67099901562bbed090cf`
- Production source pin used by the proof: `887f479b15ad861313da666ad698034d3847121c`
- Evidence artifact ID: `9739699658`
- Evidence artifact digest: `sha256:269ab50f7353309ec3d79c3f69772f6d4da099e4ad28633ba48badeb8874e373`
- Dataset hash: `08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6`
- Canonical package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:37b41e3b91a8e26cfa3030039467ca94d71d0090839dae48e290453d7a17eadb`
- Warmup start: `2006-01-03`
- Measurement start: `2006-07-31`
- End: `2007-12-31`
- Sessions causally traced: `502`
- Prefix-invariance cutoffs: `13`, all passed
- Future-poisoning cutoffs: `12`, all passed
- Static leakage findings inspected: `31`
- Forbidden leakage findings: `0`
- Baseline evidence bundle trace SHA-256: `768811aba0c614888855b6de36da9c013a5ca58fbf916cdf6f2d7c418db5aa34`

Execution timing gates also passed for next-open fills, rolling windows, entry review basis, position age, splits, dividends, terminal events, metadata as-of access, allocation timing, the MED regression, and the actual age-119 review cohort.

No new economic strategy defect was found by this certification. The existing execution-open review-basis correction was preserved. The certification harness itself required dtype and poison-domain bookkeeping repairs; those were not strategy-rule changes.

The later commit `6aa8e46e4c9a477b077934bf7d12f3ec451a95cd` added regression coverage for the terminal poison-domain mapping. The formal successful certificate above remains bound to the exact successful run SHA `ee613775aaa7542e731a67099901562bbed090cf`.

## What this certificate proves

For every certified cutoff `T`, economically active retained-research outputs through `T` were unchanged when:

1. All dataset rows after `T` were physically removed in a prefix replay.
2. All future market prices, volume, metadata, eligibility, corporate actions, terminal evidence, benchmark data, and cash factors after `T` were replaced with deterministic adversarial values.
3. Runtime guards rejected any access whose source session exceeded the active session.
4. Execution-timing assertions checked that close-generated decisions did not execute on the same close and that all chronological state transitions respected their declared timing.
5. The generated research source passed a static leakage audit with zero unresolved forbidden constructs.

This is evidence of causal execution for the exact retained source, transforms, dataset package, and certification machinery used by the successful run.

## What this certificate does not prove

This certificate does not prove research/production economic equivalence, correct parameter choice, future investment performance, or full-history correctness outside the certified dataset window.

A research/production divergence is therefore a separate defect class. Do not alter or weaken causal gates to make an equivalence test pass.

## Required evidence for every future certification

A future certification is valid only if all of the following are pinned and recorded:

- retained research source SHA;
- any source-transform/instrumentation SHA;
- production source pin when production modules are imported by the proof;
- immutable canonical dataset package digest;
- dataset hash, dataset ID, manifest SHA-256, and reconstruction-code SHA;
- warmup, measurement, and end sessions;
- GitHub Actions run ID;
- evidence artifact ID and digest;
- canonical trace digest;
- complete certification summary and SHA256SUMS evidence file.

Unknown, mutable, or silently substituted authority invalidates the certificate.

## Required certification gates

Every future run must fail closed unless all gates pass.

### 1. Immutable dataset identity

Verify the package by digest before strategy execution. Require the manifest and pointer to agree on dataset identity, coverage window, reconstruction SHA, and unresolved-action status.

Never use current Sharadar metadata as historical authority and never silently fall back to a mutable source.

### 2. Runtime causal-access guard

During active session `T`, reject any market observation, metadata row, benchmark or cash input, corporate action, terminal event, signal dependency, or portfolio state originating after `T`.

The guard must cover cached and vectorized paths, not only obvious row-by-row lookups.

### 3. Prefix invariance

Choose economically meaningful cutoffs and rerun using a dataset view physically truncated after each cutoff.

Require byte-for-byte equality through `T` for the canonical trace, covering at minimum:

- eligible universe;
- signals and ranking;
- selected positions;
- orders and fills;
- Wealth Core equity;
- breadth;
- native target;
- LD-RC state;
- allocation;
- NAV;
- split, dividend, terminal, and age-review events.

### 4. Future poisoning

For the same cutoffs, deterministically replace all future values after `T` while preserving schema and structural validity.

The poison manifest must prove that every required future domain actually changed. A poison test that leaves a required domain unchanged is not evidence and must fail.

Require the output trace through `T` to remain byte-for-byte identical.

### 5. Execution timing

Require explicit assertions that:

- close-session signals never fill at the same close;
- close-generated orders fill no earlier than a later valid session open;
- rolling windows use no source later than the active session;
- entry review basis equals the adjusted execution-open value;
- position age is chronological;
- age reviews occur only at the configured chronological age;
- splits, dividends, and terminal events cannot affect earlier state;
- close allocation decisions become effective no earlier than a later open.

Keep targeted regressions for previously investigated high-risk cases, including MED.

### 6. Static leakage audit

Inspect the exact generated strategy source used by the replay for at least:

- negative shifts;
- centered rolling windows;
- backward fill;
- forward as-of joins;
- full-period normalization;
- whole-sample ranking or calibration;
- survivor/current-universe filtering;
- future-index joins;
- forward-populated metadata;
- precomputed arrays whose earlier values depend on suffix data.

Every finding must be classified. Any unresolved economically active forbidden finding fails certification.

## Cutoff selection policy

Do not certify only arbitrary dates. Include cutoffs around economically important state transitions wherever they exist:

- warmup completion;
- first entries;
- first fills and exits;
- rebalances;
- prior divergence dates;
- age-review events;
- held-security splits;
- dividends and terminal/delist events;
- maximum drawdown/controller evaluations;
- defensive allocation transitions;
- quarter and year ends;
- final dataset session.

For a full 20-year certificate, later market regimes and actual defensive-allocation transitions must be represented.

## Invalidation rules

Rerun certification whenever any economically active retained source, generated transform, timing rule, data reconstruction rule, or canonical dataset package changes.

A pure test or documentation change does not alter economic behavior, but the published certificate should still name the exact successful source SHA rather than implicitly certifying a newer head.

If a future run exposes a mismatch or future sensitivity, stop and investigate the first divergence. Do not suppress the gate, tune parameters, or modify canonical PIT rules merely to restore a prior CAGR.

## Interpreting defects

Keep these categories separate:

- **Data defect:** historical evidence or PIT reconstruction is wrong or non-causal.
- **Research strategy defect:** retained backtester economics or timing differ from the intended strategy.
- **Production strategy defect:** production economics or timing are wrong.
- **Equivalence defect:** research and production implement different economics despite individually causal execution.
- **Certification-harness defect:** the proof machinery crashes, corrupts schema, or fails to exercise a required domain; this is not by itself evidence of strategy bias.

Record the defect category and economic impact before changing strategy code.

## Full-history next step

The bounded 2006-2007 certificate is complete. Full historical forward-bias certification requires running this same contract against the immutable completed 20-year canonical PIT package, with cutoffs extended across the full period and including actual defensive-allocation transitions.

The 20-year result must produce a new certificate bound to its own exact source SHA, dataset digest, run ID, trace digest, and evidence artifact. Do not treat the bounded certificate as automatically extending beyond `2007-12-31`.
