# Twenty-year champion certification replay and PIT composition

User authorization: 2026-09-10, run the documented simplification and hardening
champion for twenty years and record PIT portfolio composition, tickers and
percentage weights. This authorizes one fresh Core replay. The completed
seven-slot ramp campaign remains closed.

## Authority and delivery

Verified main base: `86580bdd19232b443ba80f3aefb2ea53dbc61318`.
Delivery branch: `research/champion-certification-20y-v1`, through a PR to main.
GitHub API verified the base independently of the isolated local worktree.

Selected strategy: `compact_simplified_no_ramp`, documented at
`6a73739b9bb6557d14571daff72cba5a96b23b96` in research PR #350 / issue #349.
Its complete source is frozen at
`f6ad7b543fbd20ffe363127d1120f4472caa9360`, path
`research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/sources/compact_simplified_no_ramp.py`,
SHA256 `3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663`.

Expected results and daily reference tracks are frozen at
`05727f2c65a235306fa55d61f254e06bed351776`, campaign run `34528401951`,
attempt 1. The reference ending multiple is `56.265349336558316`.

Replay stack: `eaddca3f04f279e99663f832bf7293e92ee15662` and its pinned
composite setup. Dataset SHA256:
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
Canonical package:
`ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`.

## Scope of the certification claim

This run certifies repeatability of the frozen research champion, its causal
replay clock, exact controller/reference and restart comparisons, and exported
portfolio accounting on the pinned reconstructed PIT corpus. It preserves
classification and terminal-economics provenance, including the existing
reviewed security-type overlay and carried marks. It reports their use.

Production transition certification and deployment authority remain governed by
`docs/production-certification-separation.md` and the production certification
contracts. This research result grants no production or broker authority.
The historical economic-preservation and robustness screens retain their
recorded FAIL outcomes. This is a repeatability run on previously examined data.

## Measurement and observer

Warmup starts 2006-01-03. Measurement is 2006-07-31 through 2026-07-31,
5,032 measured sessions and 5,176 total observations. Starting Core capital,
holdings, sizing, prices, costs, dividends, controller rules and execution clock
are inherited from the exact selected source.

One read-only observer call is inserted at the end of the existing daily loop.
Removing this call must restore an AST identical to the frozen source.
Controller blocks and every economic statement remain byte-identical.
The observer writes rows as sessions finish and never drives a trading decision.

`portfolio-composition.csv` contains each closing stock position with its
permanent ID, session-effective ticker, quantity, actual mark used, mark source,
reference market value, shadow weight percentage, effective model weight
percentage and next-target model weight percentage. Separate rows account for
Core cash, accrued dividend receivables and the defensive Treasury-bill sleeve.
`portfolio-sessions.csv` records daily totals and exposure timing.

Weight definitions:

- `shadow_weight_pct = 100 * reference_value / closing_core_equity`.
- `effective_model_weight_pct = shadow_weight_pct * effective_exposure`.
- `next_target_model_weight_pct = shadow_weight_pct * close_desired_exposure`.
- The Treasury-bill row has zero shadow weight and the complementary model
  weights `100 * (1 - exposure)`.

These are the scalar strategy's closing composition and next-decision model
weights. They are not broker-fill holdings or evidence of an independently
simulated share-level execution account. The daily reference book includes its
structural cash and receivables. Tickers come from `metadata_for(id, session)`;
static startup/current tickers cannot supply historical labels. Treasury cash
uses the pinned canonical cash-factor series; `TBILL_SLEEVE` is an asset-bucket
label rather than a claim that BIL was listed for the entire interval.

## Gates

1. Exact source, setup, corpus and expected-result identities; one permanent
   slot claim immediately before the sole Core start. Claimed slots cannot retry.
2. Fresh Core tape, transactions and close decisions match frozen hashes.
3. Every measured champion allocation, target and reason matches the frozen
   daily reference. NAV tolerance is the inherited `1e-10` CSV tolerance;
   headline metric tolerance is `5e-10`.
4. Compact/reference controller and full accounting restart comparisons match
   exactly on the fresh observations. Existing synthetic boundary and causal
   clock checks run before the full replay.
5. Every observation date appears once and in order. Measured coverage is exact.
   Each stock has one permanent ID and a ticker valid as of that session.
6. Holdings plus cash and receivables reconcile to Core equity; all three weight
   columns reconcile to 100% per session, with finite nonnegative values.
7. Emitted holdings agree with the engine's measured permanent-ID holdings on
   every session. Effective exposure and close targets agree with the daily tape.

Targeted tests cover a historical rename, split neutrality, structural cash,
receivables, missing marks/metadata, zero and partial exposure, target timing,
multiple lots, conflicting identities and conservation failures. Tests include deliberate
invalid records and an altered source to establish rejection behavior.

## Budget and publication

The new namespace is
`research-budget/champion-certification-20y-v1/slot-01`. Only a change to this
campaign's `LAUNCH.json` starts the workflow. A claimed ref prevents a second
Core start, including Actions job retries. No fault sweep or optimization runs.

Preserve logs, source hashes, pinned runtime identity, corpus validation,
daily observations, composition and session exports, source snapshot,
checks and headline results in Actions artifacts and compressed GitHub files.
Publish partial evidence with a precise failed gate if the run fails. Result
commits do not touch the launch file. PR #350 and issue #349 link this campaign.
