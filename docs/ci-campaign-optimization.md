# CI campaign optimization

Status: accepted design for the first migration stage.

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
