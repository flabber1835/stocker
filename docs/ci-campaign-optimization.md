# CI campaign optimization

Status: accepted design for tree reuse and parallel exact-head certification.

This document changes CI scheduling and evidence ownership only. It does not
change Sentinel, Wealth Core, execution, controller, broker, or publication
semantics.

## Problem

A broad pull request currently creates 24 jobs and approximately 175 Linux
runner-minutes. Most of that work is duplicate execution of the same campaigns
against the pull-request head and GitHub's synthetic merge commit. On an
up-to-date branch those commits normally have different commit identities but
the same Git tree.

The duplicate work is concentrated in two places:

- Sentinel safety executes the complete protected certification twice.
- Advisory backup, production-composition, internal-state, and Alpaca mutation
  campaigns execute both scopes even though they do not own required contexts.

Adding more shards would consume more runners without removing work. Selecting
individual tests from changed files would risk false negatives at shared
contracts. This migration instead makes the source tree the unit of reusable
test evidence.

## Stage-one decision: certify each source tree once

The four existing required context names remain unchanged:

```text
sentinel-exact-head
sentinel-synthetic-merge
host-python-38-exact-head
host-python-38-synthetic-merge
```

For pull requests, the exact-head jobs continue to execute the complete
protected Sentinel and minimum-host-Python certification. The synthetic-merge
jobs are tree-equivalence verifiers:

1. The checkout must be GitHub's two-parent synthetic merge commit.
2. Its first parent must be the advertised pull-request base.
3. Its second parent must be the exact pull-request head that was certified.
4. The synthetic merge tree must equal the exact-head tree.

If any proof fails, the synthetic context fails closed and the pull request
cannot merge. When the proof succeeds, every file consumed by the tests is
byte-for-byte the same tree already exercised by the exact-head context. Commit
identity is not treated as evidence equivalence.

Pushes to `main`, merge-group events, and manual runs have only the exact-head
scope and continue to execute the complete certification. Protected publication
therefore remains bound to a full run for the exact main commit and runtime
artifact; pull-request evidence is never substituted for publication evidence.

## Advisory campaign ownership

Advisory campaigns execute once per pull request against the synthetic merge
tree, because that is the tree proposed for integration with `main`. On
non-pull-request events they execute the exact event commit. The test inventory,
scenario catalogue, seeds, mutation set, and evidence validation remain
unchanged.

The owners using this policy are:

- backup reliability;
- production-composition authority;
- internal-state contract, lifecycle campaign, and core infrastructure;
- Alpaca mutations.

These jobs remain automatic. No label, comment command, or manual dispatch is
introduced. A contributor's workflow remains: ask Codex for a change, review
one pull request, and merge it when the required checks pass.

## Fail-closed authority

The test-responsibility validator owns the distinction between protected and
advisory scope matrices. It must reject:

- a protected owner that no longer exposes both required context names;
- protected execution that is absent from the exact-head scope;
- a synthetic protected context without the explicit tree-equivalence proof;
- an advisory owner that silently restores duplicate exact/synthetic pull-
  request execution;
- conditional matrix include/exclude rules that can suppress a declared scope.

The source-tree comparison is performed in both protected jobs rather than
being inferred from branch-protection settings. This keeps the proof inside the
required check run and fails safely if GitHub produces a non-equivalent merge.

## Expected effect

Using the representative 175-runner-minute pull request measured before this
change, single-scope advisory execution removes roughly 58 runner-minutes.
Tree-equivalent protected execution removes roughly another 30 runner-minutes
when the PR branch is current with `main`. Checkout, cache restore, and
equivalence-verifier overhead remains, so the expected result is approximately
a 50% reduction in runner consumption for the common green path without
reducing the executed test or scenario inventory for the proposed source tree.

## Deferred stage: merge queue and campaign tiers

Repository rules are external mutable state and are not changed by this code
pull request. After this stage is merged and observed, a separate explicitly
approved administrative change may enable GitHub's merge queue and make the
full merge-group certification the final admission point. PR smoke tiers,
rotating generated seeds, scheduled exhaustive campaigns, dependency-image
caching, and safe advisory path skipping remain follow-up optimizations. They
must preserve automatic operation and fail closed for unknown changes.

## Stage-two decision: parallel exact-head certification

The expanded exact-head certification reached its 75-minute deadline after
the complete Sentinel and champion suites passed, while source replay was
still executing. Independent suites now run in parallel within the same
Sentinel safety workflow. No tests, scenarios, mutations, coverage thresholds,
or authorized expected failures are removed, and no deadline is increased.

One runtime-build job builds the production image and its test lens once,
executes the existing runtime/durability/compile probes, and exports both images
in one Docker archive with a checksummed identity manifest. The single archive
deduplicates their shared production layers; low-level artifact compression
reduces repeated worker transfers. This temporary bundle is retained for one
day, while completed lane evidence remains available for 30 days.
Every worker loads those exact images;
it never rebuilds them. Identity includes the exact source commit and tree,
workflow run and attempt, and both Docker image IDs and source labels.

Seven independent suite lanes cover Sentinel main, the module-scoped
million-row source warmup, automation coverage, champion regressions and their
mutants, operator tests and shell/Compose validation, the prospective Wealth
Core boundary, and production mutants. Keeping the warmup module intact
avoids duplicating its expensive database fixture across test workers.
Sharadar replay uses its existing four-way deterministic test partition.
Steps inside each replay scenario and recovery test remain sequential.

The protected `certification-and-durability` job retains its existing context
names and logical test ownership. It explicitly depends on the build, all
suite lanes, and all replay shards. It runs even after a dependency failure
and refuses anything other than success for every dependency. It also requires
exactly one complete, checksummed receipt for each declared lane and shard,
bound to the same image manifest, commit/tree, run, and attempt. Missing,
duplicate, cancelled, skipped, stale-attempt, or mismatched evidence cannot
produce certification. A partial workflow rerun that reuses an older attempt's
bundle fails closed; certification requires a fresh complete workflow attempt.

The gate merges Sentinel partition JUnit and independently re-collects every
logical owner's complete test inventory, rejecting omissions, duplicates, or
unauthorized outcomes. The existing replay verifier checks the union of all
four shards, catalogue coverage, scenario steps, and corpus digests. This
same-workflow dependency-and-artifact binding replaces the former same-process
replay requirement; a point-in-time check from another workflow is still
forbidden. Workflow-source validation must reject removed dependencies,
suppressed lanes/shards, masked commands, or disabled evidence verification.

Synthetic-merge certification retains the strict identical-tree proof and
does not repeat heavy suites. Both protected scopes now wait for the mandatory
exact-head dependency graph. Main publication still exports the original
tested production image and unchanged software-certification input schema
only after the complete protected gate passes. Job names expose the active
suite or replay shard, and each receipt records its completed files and image
identity for inspection.
