# Production integration of the compact champion

Owner decision, 2026-09-11: integrate the certified
`compact_simplified_no_ramp` champion into the production application before
continuing the full-system universe replay. Base:
`4bba6875b07288cf6ebc6a149b926075b1e41c60`.

## Frozen authority

The economic authority is the complete source at
`f6ad7b543fbd20ffe363127d1120f4472caa9360`, path
`research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/sources/compact_simplified_no_ramp.py`,
SHA256 `3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663`.
PR #352 retained the independent replay at
`2a1bd486241ae524eac395490b135cc79715e497`, run `34544522249-1`:
56.265349336558316 times initial wealth, 22.323600023175572% CAGR,
2006-07-31 through 2026-07-31, following warmup from 2006-01-03.
Its canonical dataset is
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.

## Application ownership

The canonical Wealth Core owns the twenty-slot V5 book, 5% opening dollar
intents, Median-5 selection, exits, accounting and permanent security identity.
Sentinel owns the frozen compact native and recovery transitions, including
REC8 and removal of the recovery ramp. Production modules contain their
implementation and versioned restart state. Production imports no experiment
module and performs no runtime source rewriting. The retained PR #342 port
supplies the starting implementation of V5 and opening sizing; the new
integration must revalidate it against current main and the selected champion.

Production owns startup, warmup, data sufficiency, ticker eligibility,
publication, retry classification, recovery and execution. The system replay
may supply external service responses and simulated time, and record/assert
results. It may not replace the production loader, ignore readiness failures
by session count, change strategy thresholds or manufacture readiness.
Source data simulation must preserve observed zero volume versus missing
volume before production normalization.

A data-wait or execution-deferral result must retain the production reason and
be exercised through production recovery. Twenty-year reliability requires
complete scheduled coverage, correct recovery, durable state integrity and
no unexplained loss of progress. A successful prefix or handled refusal alone
does not prove that result.

## State and execution

The strategy identity binds the frozen reference, production implementation,
Wealth Core configuration, controller semantics and snapshot schemas. Prior
strategy state is not silently relabelled as champion state. Existing lineage
and execution authority checks own adoption of a changed strategy.

Opening quantities are computed through the production execution boundary,
persisted before order submission and reused after restart. Splits and ticker
changes follow permanent security identity. Broker state remains an input to
execution only; it cannot change the canonical shadow or controller decisions.

## Verification and delivery

Retain the complete frozen reference as test evidence. Verify controller
transitions and snapshot restoration independently, canonical book economics,
opening sizing and restart behavior, and the full historical differential over
all 5,176 sessions. Historical comparison uses the production kernel and records
its exact source identity; it does not patch application behavior.

This integration is delivered through a PR targeting main. Source integration,
historical strategy equivalence, full-system twenty-year reliability and
deployment certification are separately recorded results. Existing signing,
backup and deployment authorization contracts remain authoritative.

The paper lifecycle decomposition manifest remains a historical snapshot.
`production-champion-paper-deltas.json` records the explicitly changed lifecycle
definitions, their current AST hashes and behavioral regression suites. The
architecture check continues to verify unchanged definitions against the
historical manifest and independently checks the backup gates before validating
the authorized deltas. Economic result pins are not regenerated.
