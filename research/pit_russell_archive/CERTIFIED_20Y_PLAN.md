# Certified 20-year Russell 3000 backtest plan

Status: **RESEARCH ONLY — isolated implementation plan**

Branch: `research/pit-russell-archive-reconstruction`

Protected source refs that this work must not modify:

- `main@8b42b1e109b2ff3cb6832f92757a45ced0df4c60`
- `research/backtester@e088bfd26c695309e259cfc44ab1e8982d6f858d`

## Objective

Produce a 20-year backtest whose investable universe is defined by causally available Russell 3000 membership and whose final result can be certified for the stated PIT/causality/universe/execution contract.

Candidate success banner:

`PIT CERTIFIED — point-in-time Russell 3000 universe, identity, causality, execution, and forward-bias checks passed`

Certification does not claim freedom from model-selection, overfitting, statistical, or economic bias.

## Strategy/data boundary

Russell 3000 annual membership becomes the authoritative eligibility overlay. Sharadar remains the market-data source.

Required external strategy data is intentionally narrow:

- annual Russell 3000 membership and its publication/effective-time evidence;
- stable security identity sufficient to prevent ticker reuse from joining unrelated securities;
- observed session;
- observed unadjusted open;
- observed unadjusted close;
- observed volume;
- split ratio;
- dividend per share;
- SPY adjusted close used by Sentinel;
- BIL data if the defensive sleeve remains enabled.

Historical Sharadar category/share-class metadata is not required once the strategy contract explicitly makes Russell 3000 membership the eligibility authority.

## Stage 1 — authoritative annual universe corpus

For every annual universe needed to support the 20-year measurement period:

1. Recover an original Russell/FTSE Russell membership artifact when available.
2. Record original URL, archive capture timestamp where applicable, source SHA-256, parser contract, constituent count, evidence grade, publication date, and effective date.
3. Parse the artifact deterministically.
4. Require a plausible constituent count and zero unresolved duplicate-ticker/company conflicts.
5. Retain raw third-party source documents only ephemerally unless a later data-rights decision explicitly permits storage.
6. Surface missing years explicitly. A missing year can never be silently filled with current/future membership.

Target output: one machine-readable annual-universe manifest covering the full backtest horizon.

## Stage 2 — holdout validation for reconstructed years

If any year lacks a full authoritative list, allow a Grade C reconstruction only after validating the reconstruction method on one or more years whose complete authoritative list is independently available.

Metrics:

- intersection count;
- false inclusions;
- false exclusions;
- Jaccard similarity;
- membership differences surviving the strategy's 127-session history and liquidity gates;
- selection/portfolio-days affected;
- resulting P&L sensitivity.

A reconstruction method with economically material holdout error is rejected.

## Stage 3 — Russell-to-Sharadar identity authority

Map each annual Russell constituent to the correct Sharadar security episode using only causal evidence.

Required invariants:

1. Ticker continuity alone cannot join unrelated securities.
2. Ticker reuse must create separate security identities.
3. Legitimate ticker changes must preserve identity only when supported by dated evidence.
4. An ambiguous join fails closed for that candidate.
5. Every accepted mapping records its evidence/provenance and confidence class.
6. The strategy must never inherit price history across an unresolved identity boundary.

This is expected to be the principal remaining historical identity problem, but it is bounded to Russell constituents rather than the full U.S. listing history.

## Stage 4 — minimal market corpus

Build the replay corpus only for Russell-eligible identities plus required SPY/BIL observations.

Hard rules:

- no interpolation or fabrication of open, close, or volume;
- no future metadata used to repair historical observations;
- split/dividend handling remains deterministic and causal;
- the strategy's 127-session lookback must contain only sessions available by the decision time;
- missing observations cause explicit exclusion/failure according to the approved contract.

## Stage 5 — terminal-position contract

A held security may not disappear from the replay without an economic settlement.

The final contract must define:

- authoritative settlement when causally known;
- fail-closed/conservative treatment when exact terminal economics cannot be established;
- explicit reporting of every unresolved/conservative terminal settlement;
- sensitivity of CAGR/drawdown to those settlements.

## Stage 6 — isolated harness integration

Do not modify `research/backtester`.

The research workflow will check out the exact pinned backtester ref read-only into a separate runtime directory and check out this Russell research branch into another directory. Russell adapters/overlays and new tests live only on this branch.

This allows the existing certification machinery to be reused while preserving the original backtester branch byte-for-byte.

The integration must pin and record:

- backtester source SHA;
- Production/main strategy source SHA under test;
- Russell universe corpus hash;
- Sharadar market corpus hash;
- identity-map hash;
- terminal-policy version;
- runner/runtime identity required by the existing harness.

## Stage 7 — certification proof suite

The final proof suite must fail closed unless all required assertions pass:

### Universe

- active annual Russell universe is causally available for every decision session;
- every admitted security is a member of the active universe;
- no future membership is used before its publication/effective boundary;
- annual universe artifacts/hashes match the approved manifest.

### Identity

- every selected/held security resolves to one accepted historical identity;
- no ambiguous or reused ticker crosses an identity boundary;
- 127-session histories do not cross unrelated security episodes.

### Market causality

- signal inputs stop at the decision session;
- no future open/close/volume is visible to the signal calculation;
- split/dividend transformations use only causally known events according to the approved contract;
- SPY/BIL inputs obey their own causal domains.

### Execution

- decisions made after session `t` execute only under the approved next-session/open contract;
- fills cannot use future prices;
- whole-share/cash constraints and pending-order semantics match the strategy under test.

### Stateful strategy causality

- holdings, episode peaks, cooldowns, pending orders, review state, and other durable state are derived only from prior causal transitions;
- checkpoint/resume is equivalent to uninterrupted replay.

### Terminal handling

- every held terminal security receives an explicit causal settlement outcome;
- no position silently vanishes.

### Forward-leakage challenge

- perturbation/truncation tests demonstrate that future source changes cannot alter earlier decisions or state.

### Exact-code identity

- the certificate identifies the exact strategy, harness, universe, identity map, market corpus, and policy revisions.

## Stage 8 — 20-year replay and certification

Run the complete stateful replay across the approved 20-year measurement interval with warm-up as required by the 127-session history contract.

Publish:

- machine-readable certificate;
- human-readable certificate summary;
- annual checkpoints;
- portfolio/equity curve and performance metrics;
- corpus and source hashes;
- uncertainty/exception counters;
- exact source SHAs.

A run with any unresolved required property must end with:

`PIT NOT CERTIFIED — <specific reason>`

## Current progress

- GitHub-hosted runners can query/download Internet Archive captures.
- Direct archived Russell 3000 membership PDFs have been recovered for 2005, 2006, and 2009–2013.
- 2009–2013 pass the current deterministic membership parser/count/ambiguity gates.
- 2005/2006 use a different legacy PDF layout; a strict raw-record parser has been added and is under CI validation.
- A 2005–2026 annual coverage discovery is being split into early/middle/recent parallel jobs to expose gaps without archive-latency coupling.
- No Production or backtester branch changes have been made.

## Stop conditions

Do not adopt the Russell-overlay strategy or issue a normal PIT certificate if:

- one or more required annual universes cannot be established under the approved evidence contract;
- identity ambiguity materially affects eligible candidates and cannot be bounded safely;
- holdout reconstruction error is economically material;
- market observations required by selected holdings are materially incomplete;
- terminal uncertainty materially dominates performance;
- forward-leakage tests fail;
- exact source/corpus identities cannot be established.
