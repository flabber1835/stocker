# Backtester experiment contract

**Branch:** `research/backtester`  
**Status:** mandatory operating contract for research backtests on this branch

This branch is a long-lived experiment laboratory. Its purpose is to run reproducible historical experiments against exact strategy code and frozen historical datasets without ever changing production `main`.

## Hard invariants

### 1. `main` is read-only

Backtester workflows may resolve, fetch, inspect, or check out an exact `main` commit SHA as strategy source material. They must never push, merge, commit, tag, rewrite, or otherwise mutate `main`.

No backtester workflow may automatically open or merge a pull request into `main`.

If a workflow has repository write permission for research-data maintenance, it must verify that its only write target is `research/backtester` before making any repository mutation.

Experiment results do not confer promotion authority. Promotion into production requires a separate explicitly requested review outside the backtester workflow.

### 2. Backtests consume pre-existing branch-owned input datasets

Every backtest must use historical input data that already exists on `research/backtester` before the experiment begins.

This includes, as applicable:

- raw Sharadar source snapshots;
- finished PIT-reconstructed datasets;
- corporate actions;
- SPY/BIL and other benchmark data;
- PIT issuer/security-type/SIC/FF12 or other reconstructed metadata;
- any other causal historical input required by the experiment;
- manifests, hashes, coverage metadata, and provenance for those datasets.

A backtest run may validate, load, filter, join, or transform its declared inputs in memory for the mechanics of the replay. It may not reconstruct missing PIT history, scrape replacement history, infer missing historical metadata, or repair the dataset during the experiment.

PIT construction is a separate dataset-maintenance operation. Once a PIT reconstruction is accepted, its finished output must be stored as a content-addressed GitHub Container Registry package. A small pointer committed to `research/backtester` must pin the package digest, canonical dataset hash, reconstruction SHA, source run, date window, and manifest hash. Future experiments resolve that branch-owned pointer and consume the frozen package directly.

The package digest is immutable. A mutable package tag, an Actions cache, an expiring Actions artifact, or an unpinned workflow run is not a valid experiment input. Actions artifacts may be retained as redundant build evidence.

If a required dataset is missing, incomplete, or hash-mismatched, the experiment must fail before economic replay starts.

### 3. No prerecorded decisions, tapes, or oracles may drive a backtest

The simulation may not use any prior generated path as an economic input, including:

- prerecorded holdings or positions;
- prerecorded trades or pending orders;
- prior Wealth Core state;
- prior Sentinel decisions or native targets;
- prior LD-RC state or allocation targets;
- precomputed crisis/confirmation dates;
- prior NAV/equity curves;
- transition schedules;
- "certified tapes", "frozen tapes", oracle outputs, or equivalent historical decision files.

Such files may exist on this research branch as historical evidence or post-run comparison material. They may only be consulted after a fresh replay has completed, never used to drive that replay.

The rule is:

> Frozen inputs are allowed. Frozen decisions are not.

### 4. Every reported economic result comes from a fresh chronological replay

A backtest starts from an explicitly defined initial state and advances one historical trading session at a time.

For each simulated session:

1. expose only information causally available as of that session;
2. run the actual strategy logic for that session;
3. record the resulting state/decision;
4. apply execution/accounting at the strategy's correct historical timing;
5. advance to the next session.

All path-dependent state must arise inside this replay: holdings, cash, stops, cooldowns, pending orders, settlement, Sentinel state, LD-RC state, allocations, and NAV.

For A/B/C or other multi-arm experiments, all variants must be evaluated for the same historical session before the simulation advances. Shared mechanics and shared inputs must remain identical except for the explicitly declared experimental difference.

## Strategy-source rule

By default, "current strategy" means the exact current `main` SHA resolved at experiment start. The run manifest must record that SHA.

The backtester branch may contain experiment wrappers or variant logic, but a control claiming to represent production `main` must execute the production strategy semantics from the declared exact `main` SHA, not a stale copied implementation.

## Dataset identity and provenance

Every run must declare the exact dataset identity it consumed. At minimum, the run evidence must record:

- dataset manifest/version identifier;
- SHA-256 hashes for required input files or an equivalent aggregate manifest hash;
- coverage start/end dates;
- PIT status of each metadata domain relevant to the experiment;
- exact strategy SHA;
- exact backtester experiment-code SHA;
- experiment configuration and requested historical windows.

An input that is known not to be point-in-time must be explicitly labeled non-PIT in the result. A result must not be described as PIT-certified when any economically relevant input used by that variant is non-PIT.

## Results and artifacts

Backtest output should be written to GitHub Actions artifacts or branch-local research output, never to `main`.

A standard result should include, when applicable:

- CAGR;
- maximum drawdown;
- Sharpe ratio;
- SPY comparison;
- session count and exact date window;
- control/variant identity;
- daily NAV/decision output sufficient for audit;
- manifest with code and data hashes;
- explicit PASS/FAIL for control parity when an unchanged control is required.

Headline numbers are invalid if the control does not reproduce the intended strategy semantics and timing.

## GitHub Actions safety

Backtester workflows should default to `contents: read`.

Any workflow that requires `contents: write` for dataset maintenance must:

1. be explicitly research-only;
2. verify `research/backtester` as the current branch;
3. push only to `research/backtester`;
4. contain no push/merge path to `main`;
5. never use a successful experiment as automatic production promotion.

A dataset-maintenance workflow may also request `packages: write` solely to
publish a content-addressed canonical input package. It must commit the
resulting immutable package digest only to `research/backtester`. Economic
replay workflows receive `contents: read` and `packages: read`; they have no
dataset-construction or publication authority.

Experiment workflows should prefer immutable downloadable Actions artifacts for results.

## Historical files already on this branch

This branch contains older recovered harnesses, oracle outputs, transition files, prior experiment results, and files whose names may contain terms such as `tape`, `oracle`, `frozen`, or `certified`.

Their presence does not authorize their use as simulation inputs. They are historical evidence only unless they are raw/frozen data inputs covered by a current dataset manifest.

When in doubt, reconstruct the strategy state by fresh chronological execution from declared market/PIT inputs.

## Required pre-run checklist

Before reporting a backtest result, prove all of the following:

- the strategy source SHA is exact and recorded;
- `main` has not been modified;
- all required historical inputs were already present before the run;
- all required hashes matched;
- no PIT synthesis occurred during the experiment;
- no prerecorded decision/state/NAV path was used as an input;
- the replay advanced chronologically with causal information only;
- multi-arm variants changed only their declared experimental dimension;
- execution timing is correct;
- results and provenance artifacts were retained.

If any item cannot be proven, do not present the resulting CAGR, drawdown, or Sharpe as an authoritative backtest result.
