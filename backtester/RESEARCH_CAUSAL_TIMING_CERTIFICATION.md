# Retained research causal-timing certification

**Scope:** retained strict-PIT research replay on the immutable 2006-01-03 through 2007-12-31 canonical dataset  
**Branch:** `research/strict-pit-causal-certification`  
**Production source pin:** `887f479b15ad861313da666ad698034d3847121c`  
**Status:** executable fail-closed certification contract

## Objective

Prove that every economically active output of the retained research replay through session `T` is a function only of observations and state available no later than `T`.

The proof is fail-closed. A future access, chronological violation, prefix mismatch, future-poisoning sensitivity, source-seam mismatch, or economically active static leakage finding fails certification.

This work does not tune parameters, optimize CAGR, alter canonical PIT reconstruction, admit current Sharadar metadata as historical authority, or change an economic strategy rule. The execution-open review-basis correction remains mandatory.

## Frozen authority

The bounded proof consumes only the immutable package pointer in `backtester/data/canonical-pit-2006-2007.json`.

Expected identity:

- package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:37b41e3b91a8e26cfa3030039467ca94d71d0090839dae48e290453d7a17eadb`
- dataset hash: `08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6`
- manifest SHA-256: `008f768539c8e6d0e5f2f01a05dab1baf93560c2ffeb7ca7b1521b1a236263e1`
- reconstruction code SHA: `eb873b399024679e6534797b1e9f4bcccbe36656`
- warmup start: `2006-01-03`
- measurement start: `2006-07-31`
- end: `2007-12-31`

The workflow pulls the package by digest, copies the dataset from the image, and runs `canonical_pit_package.py verify` before executing strategy code.

## Execution chronology under proof

For each chronological market session, the retained replay performs these phases:

1. Advance the session counter exactly once and establish the active causal session.
2. Expose the current session's canonical observation group.
3. Update causal rolling state using the current observation and previously retained ring-buffer values.
4. Construct the base eligible universe using listing, security type, continuity, price, liquidity, and finite-signal gates.
5. Rank the eligible universe by medium-term momentum, form the top-decile pool, rank that pool by durable score, and form the recent-leadership selection.
6. Apply the prior close's recent-leadership selection to the current close-to-close witness and update recent-leadership state.
7. At the current open, settle due receivables, apply current-session splits, process current-session terminal events, execute pending exits, and execute pending entries.
8. Apply current-session dividends using prior-close share quantity.
9. At the current close, update peaks, evaluate trailing stops, evaluate the age-119 review, and create pending exits.
10. Mark Wealth Core close equity and derive position breadth.
11. Generate new entry orders at the close from the current durable ranking.
12. Update Wealth Core drawdown and return state, native target, retained LD-RC state, desired allocation, and next-open pending allocation.
13. Apply the prior close's allocation decision at the current open and mark NAV through the current close.
14. Emit a canonical causal trace record for the session.

Close-generated orders cannot execute in the close phase. Their first possible execution point is the open phase of a later valid session.

## Runtime causal-access guard

The generated retained replay is wrapped by a session-scoped guard. The guard owns the authoritative ordered session list and rejects:

- a market, benchmark, cash, metadata, corporate-action, terminal-event, signal, or portfolio-state request whose source session is later than the active session;
- a repeated, skipped, reversed, or mismatched session transition;
- a session observation group containing a different date;
- a rolling dependency whose maximum source index is later than the active index;
- metadata selected from an effective session later than the request session;
- a close-generated fill on its signal session;
- an entry fill whose review basis differs from the adjusted execution-open value;
- a position age that differs from chronological session distance;
- split, dividend, or terminal processing assigned to another session;
- an allocation decision applied on its signal close.

Dataset validation and immutable-file loading occur before a strategy session is active. Economically active access during a session is permitted only through guarded session or as-of accessors.

### Vectorized and cached calculations

The benchmark frame may be initialized vectorially. At every active session the guard recomputes each benchmark feature from the prefix ending at that session and requires exact floating-point equality with the cached value. The strategy's stock signals are produced by chronological ring buffers; the guard verifies the active index and declared lag bounds for every session.

The metadata timeline and action table may be loaded once. Metadata selection uses right-bounded as-of lookup. Actions and terminal events use a guarded session map. Future rows may exist in storage but cannot be returned to the active strategy session.

## Canonical causal trace

Every session, including warmup, emits one canonical JSON record using sorted keys, compact separators, exact hexadecimal floating-point text, and deterministic security-ID ordering.

The record covers:

- complete signal-vector digest;
- eligible-universe count, members, and digest;
- ranking members and digest;
- selected-position state and digest;
- pending orders and digest;
- fills and digest;
- Wealth Core open and close equity;
- position ages and entry bases;
- breadth values;
- native target;
- retained LD-RC state;
- desired and effective allocation;
- NAV state;
- split, dividend, terminal, and age-review events;
- runtime-guard assertion counters.

Digest inputs are retained in canonical ordered byte form before hashing. Equality of trace lines proves equality of every covered output while keeping artifacts bounded.

## Prefix-invariance proof

For each cutoff `T`:

1. Run the complete immutable dataset through `2007-12-31` and retain the baseline trace.
2. Create a prefix view that physically removes observations, metadata timeline rows, actions, terminal events, benchmark rows, cash rows, and sessions after `T`.
3. Run the retained strategy with end session `T`.
4. Require the prefix trace to be byte-for-byte identical to the corresponding baseline trace prefix.

The comparison includes all warmup state. A mismatch reports the first unequal session and field and fails certification.

## Future-poisoning proof

For each cutoff `T`, construct a deterministic in-memory view of the same validated immutable dataset. Rows through `T` remain byte-identical. Rows after `T` are replaced with structurally valid adversarial values covering:

- raw and signal prices;
- reported and raw-compatible volume;
- listing, tradeability, metadata admission, security type, issuer, and sector fields;
- split ratios and dividends;
- corporate-action values and terminal classifications;
- terminal-event terms;
- benchmark factors and levels;
- cash factors.

The poisoned replay runs through `2007-12-31`. Its causal trace prefix through `T` must be byte-for-byte identical to the baseline prefix. The poison manifest records the seed, changed-domain row counts, cutoff, and digest.

## Timing assertions

The baseline run proves:

- no close-session signal produces a same-close fill;
- every close-generated order fills only on a later valid session's open;
- all rolling windows end at the active session;
- entry review basis equals the adjusted execution-open value and remains immutable;
- position age equals chronological session distance;
- every age-review event occurs at age 119 and cannot inspect a later session;
- split, dividend, and terminal processing is assigned only to the active session;
- allocation decided at close becomes effective no earlier than a later session open.

### MED factual correction and regression

The canonical retained-research trace disproves the earlier label that MED underwent an age-119 review in August 2006.

For security `1035638340512403010`, the regression requires this actual path:

- close order generated on `2006-07-05`;
- entry filled on the `2006-07-06` open;
- review basis equals the adjusted execution-open value;
- position age is 28 on `2006-08-15`;
- trailing stop creates the exit order on the `2006-08-15` close;
- exit fills on the `2006-08-16` open;
- no MED age-119 review event is emitted.

The first actual retained-research age-119 review cohort occurs on `2006-12-22`. That cohort is separately traced and asserted.

## Cutoff coverage

The bounded proof includes cutoffs around:

- the first valid session after measurement begins, carrying the complete warmup state;
- first measured close orders;
- first measured fills and exits;
- the MED August 2006 stop decision and next-open fill;
- a held-security split;
- the first observed research/production divergence date as a high-sensitivity checkpoint;
- quarter-end reporting;
- the first actual age-119 review cohort;
- a later held-security split;
- the bounded window's maximum drawdown and defensive-controller evaluation;
- final quarter-end and dataset end.

The 2006-2007 window contains no defensive allocation transition. Certification records the maximum-drawdown controller evaluation and separately asserts that the unchanged allocation state is causal.

## Static leakage audit

The generated strict-PIT research source is parsed and inspected for:

- negative shifts;
- centered rolling windows;
- backward filling;
- forward as-of joins;
- full-period normalization used before the period ends;
- whole-sample ranking or calibration;
- current-universe or survivor filtering;
- future-index joins;
- forward-populated metadata;
- precomputed arrays whose prefix values can depend on suffix rows.

Every finding is classified as `FORBIDDEN`, `GUARDED_CAUSAL`, or `REPORTING_ONLY`. Any `FORBIDDEN` finding fails certification. Safe constructs state the causal reason and the runtime or invariance evidence that covers them.

## Deliverables and fail-closed outputs

The workflow emits:

- `dataset-identity.json`;
- `execution-chronology.json`;
- `runtime-guard-report.json`;
- `prefix-invariance.json`;
- `future-poisoning.json`;
- `execution-timing.json`;
- `static-leakage-audit.json`;
- `cutoff-manifest.json`;
- `certification-summary.json`;
- the baseline canonical causal trace;
- per-run manifests and logs;
- `SHA256SUMS.txt`.

`certification-summary.json` has status `PASS` only when every runtime, prefix, poisoning, timing, MED, actual age-119 cohort, and static-audit gate passes. Unknown or missing evidence is a failure.

## Remaining full-window extension

Run `33331951602` completed and published the immutable 20-year canonical dataset. A separate full-window certification must bind that published package digest and execute the same guard, prefix, poison, timing, and static-audit contract across later crises, terminal terms, and actual defensive-allocation transitions.