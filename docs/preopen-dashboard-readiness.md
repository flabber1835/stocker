# Scheduled pre-open dashboard readiness

Decision: 2026-10-21. In reviewed dual operation, a current admitted plan can be
ready and waiting for its scheduled execution while post-close share-unit mirror
evidence does not yet exist. The dashboard currently marks every active mirror
cycle WARN, making operational green impossible before that future evidence.
This decision supersedes only the normal pre-open amber presentation in
`dashboard-verification-monitor.md`; economic verification remains pending.

## Explicit expected future state

Add SCHEDULED as an operational-OK PAPER mirror presentation. Its visible value
and detail continue to say PAPER NOT VERIFIED and post-close evidence PENDING.
It is never CLEAN, a reconciliation, performance certification or execution
authority. All other current panel rows retain their ordinary aggregate gates.
Any unreadable, failed or stale authority, broker, backup, plan, runtime or shadow
fact therefore prevents the operational headline from becoming green.

The projection can select SCHEDULED only after existing all-history transport
and exact-current-plan informational mirror checks pass. It additionally requires:

- The exact current native health cycle is WAITING_OPEN, without failure, and
  its actual execution time is still in the future.
- Native SELECT-only automation health reports enabled, kill released, a live
  current leader, operational readiness, current authority and no unresolved
  broker outcomes.
- The current stamped unsuperseded native journal plan agrees with that cycle's
  plan ID/fingerprint, decision/effective sessions and current publication.
- Plan, cycle, current rollout and current health share the same certificate
  and rollout mode/version. The cycle is nonhistorical and eligible under the
  current control generation using the canonical cycle/event predicate.
- The publication frontier is the plan's decision and its effective session is
  the next exchange session. No historical clean mirror row substitutes for
  the exact plan's existing pending stamp.

These are bounded database reads in the existing read-only PAPER observer.
There is no new provider request, broker client, full-corpus reconstruction or
financial mutation. Failures retain the existing amber/red result.

## Cached observations expire at the real boundary

The scheduled row is required-current with its original valid_until strictly
before execute_at. Serialization and the background observer must preserve that
boundary; refreshing the displayed observed_at cannot extend it. At or after
execute_at, a cached scheduled row fails currentness and a new observation uses
the existing execution/recovery/mirror classification. PLAN_READY, blocked,
failed, absent, stale or foreign-generation/certificate cycles never gain the
scheduled classification. Future fills and post-close evidence are not invented.

## Retained executable identity and qualification

The exact model/source changes require a new protected source profile. Preserve
the complete previous 1b3ee286 profile bytes as a separately pinned retained
predecessor, add its exact after identities to the allowed predecessor sets, and
compute the reviewed successor's actual source/checker/profile hashes. Preserve
all financial implementation after hashes outside panel/model.py and
panel/sources.py. No fixtures, origin, book or old receipt are rewritten.

Targeted model/source/observer tests cover a ready scheduled plan, the exact
execution boundary through serialization, and rejection of missing pending
stamp, past time, failed/wrong cycle, historical or wrong generation, mismatched
plan/fingerprint/publication/rollout/certificate, disabled/killed/stale authority
or unresolved broker outcome. Remove guards in controlled local mutants and
prove their corresponding falsifiers fail. New software still requires ordinary
signed CI, exact-image qualification, installation and activation; this UI
projection grants none of them.
