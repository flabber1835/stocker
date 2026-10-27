# Sentinel current operating contract

[Bounded database recovery](database-recovery-local-patch.md) records the owner's
2026-10-26 local patch exception and its backed application-roll requirements.
[Dashboard continuity and post-trade handoff](dashboard-posttrade-recovery.md)
extends that authorized local patch after the completed opening cycle.

Current owner instruction: backed-up PAPER releases through CI and PR delivery.
The 2026-10-24 [release restoration decision](paper-backed-release-20261024.md)
supersedes the earlier backup suspension and direct local delivery exception.
The transition must preserve the installed account/book and earn real durability
proofs before financial activation; authorization is not a claim that the old
archive-off installation has already been converted. This document describes the
selected behavior; [historical deployment decisions](sentinel-deployment-history.md)
retain their original dates and certification scope.

The backed owner PAPER source handover also requires the
[closed retained-origin transition](backed-paper-retained-origin.md). Its exact
origin/current-source proof and fresh account scope preserve the canonical book;
they do not extend ordinary or LIVE admission.

## Architecture and authority

Wealth Core owns the deterministic canonical holdings and immutable shadow book.
Sentinel selects exposure. Execution alone contacts the broker. Broker holdings,
fills, outages and rejects never change strategy decisions or controller inputs.
Use the canonical implementation and its original book; do not form another book
or reset a binding to install software.

The installed account is Alpaca PAPER only. Local operating mode is
`OWNER_AUTHORIZED_FUNCTION_FIRST_V1`; the literal configuration must name the
exact durable account binding and actual clean commit/image/source identities.
Live endpoints remain forbidden. Current operating permission is independent of
historical performance certification. A green dashboard means current operational
readiness, not completed trades or certified investment returns.

See [architecture](sentinel-architecture.md), [execution contract](sentinel-execution-contract.md),
[local PAPER mode](local-paper-function-first.md) and
[controller certification](sentinel-controller-certification.md).

## Market inputs and daily plan

Current operational inputs use `ALPACA_OPENFIGI_VALIDATED_CLOSED_SESSION_V2`.
The provider history, reference classifications and corporate actions must pass
coverage, corroboration, price-domain and immutable publication checks. Acquisition
starts after a session closes; there is no fixed promise that publication finishes
at a particular minute. Historical Sharadar research identities retain their scope.

An owned publisher waits for a finite place in the existing corpus lock queue.
Existing readers finish normally; fresh independent readers yield to the queued
writer. Deadlines, fenced leases, CAS checks and uncertain-session disposal remain
enforced. A dashboard request cannot create a competing expensive verification
worker. See [writer scheduling](corpus-writer-scheduling.md).

The daily decision produces a saved plan for the next exchange session. Normal
execution starts one minute after the regular open (9:31 a.m. New York,
6:31 a.m. Pacific). New increases stop ten minutes
after the regular open. The calendar's actual session times are authoritative.
A separate explicitly authenticated debug window retains its historical contract;
normal operation does not silently acquire one.

## Quantities, prices and recovery

- Continuing positions keep their durable account share targets at unchanged
  controller exposure. Entries, strategy exits, exposure changes and authenticated
  share-unit actions retain their normal sizing rules.
- BUYs use whole shares and `PROTECTED_LIMIT_DAY_V1`: authenticated prior closed
  RAW prices, the owner's 100-basis-point maximum premium, fixed allocated budgets
  and cash headroom. The limit may tighten to fit the budget.
- DAY buys may remain working until market close. A price above the cap may leave
  an order unfilled. A saved target or successful cycle does not invent fills.
- Preserve the long-only/unlevered envelope, durable order identity and terms,
  fresh final account/source/clock/authority checks, and explicit UNKNOWN outcomes.
- Positive reconciliation governs recovery. Restarts cannot resend an uncertain
  command as if it were known unsent. Historical plans, fills and policy bytes
  remain immutable.

See [protected orders](free-data-execution-proposal.md),
[cohort continuation](protected-cohort-continuation.md),
[persistent targets](persistent-account-share-targets.md) and
[share-unit actions](automatic-share-unit-reconciliation.md).

## Dashboard and notifications

[Bounded shared-snapshot verification](shadow-streaming-verification.md) removes
the full-window blocking sort from shared input reads and gives failed financial
observations the existing short retry interval without weakening verification.

[Verification workflow simplification](verification-workflow-simplification.md)
removes duplicate source/catalog work and intent-only installation comparisons.

The mobile view leads with one operational status card, the saved trading plan,
recorded paper account and the twenty canonical slots/cooldowns. System details
contains operational diagnostics. Failures remain visibly named even when details
are collapsed. HTML and JSON use the same evidence eligibility and original clocks.
Future intent, current execution progress, historical shadow values and actual
paper holdings remain distinct; missing data is unavailable rather than zero.

Independent bounded shadow/PAPER monitors refresh without an open browser.
Retained pages withdraw current authority until fresh verification succeeds.
Push controls, subscriptions, durable fill notices and delivered-warning recovery
recipient bindings remain intact. Current source waits are distinguished from
stopped workers; historical warnings retain their original cause and timestamp.

See [plan-first dashboard](dashboard-plan-first.md),
[verification monitor](dashboard-verification-monitor.md),
[notification diagnostics](worker-notification-diagnostics.md) and
[fill notification recovery](paper-fill-notification-recovery.md).

## Qualification and local installation

[GO child image identity](go-probe-artifact-identity.md) records the complete
runtime/test artifact handoff required by retained owner-PAPER preparation and
read-only financial probes.

The owner restored the release workflow on 2026-10-24. Develop on a feature
branch, qualify changes, run required exact-head CI, merge the approved PR and
verify protected main validation and signed immutable image publication. Use the
canonical full installer and separate dual PAPER activation described in
[CI-certified installation](ci-certified-paper-installation.md),
[installation/activation separation](installation-activation-separation.md) and
[the restored release decision](paper-backed-release-20261024.md). Preserve the
distinct owner-authorized PAPER financial context; restoring backups does not
authorize a new book, LIVE, or unrelated historical certification claims.

Installation preserves PostgreSQL identity and all financial/source/notification
history. One owned operation compares the exact old/new canonical state read-only,
checks native paper holdings/open orders GET-only, waits for an idle handoff and
rolls only shadow, automation, panel, alert dispatcher, verifier and GET-only
execution collector, shadow first. Each continuation validates
its immutable request, exact image, fresh receipt and unchanged current state.
Finish by verifying healthy exact-image services, advancing leadership and the
actual dashboard. A refused gate stops the stage; diagnose rather than erase it.

[Code consolidation](code-simplification-20261023.md) defines the refactor,
source-compatibility boundary and focused qualification requirements.
The [local delivery guide](local-paper-delivery.md) documents the tracked CLI,
qualification inputs, durable stages and supported recovery boundaries.

## Restored durability and protected workloads

Backups, WAL archiving, maintenance, backup verification and private restore
qualification are authorized again. Backed-up owner PAPER operation explicitly
selects `SENTINEL_LOCAL_PAPER_BACKUP_POLICY=REQUIRED_V1`; its ordinary real guards
and exact-image restore evidence must pass. Empty selection preserves dated
legacy suspended behavior; it is not the selected policy for the new full
installation. Unknown policy values refuse.

The existing backtest and its sources, data, outputs, processes and resources
remain untouched. Do not reset/prune Docker or WSL. The restored full-install
transition may narrowly fence writers and recreate only PostgreSQL to enable
archiving/add the independent backup mount while preserving its exact data volume
and physical system identity. This is separate from the old application-only
delivery command, which retains its archive-off invariants and is not the new
full-install path. Use canonical media ownership, actual capacity checks and one
eligible exact-image recovery milestone; never manufacture backup readiness.

## Historical section links

These anchors preserve links into the earlier deployment document. Each target
is historical and does not supersede the current operating contract above.

<a id="current-installation-boundary"></a>
[Current installation boundary](sentinel-deployment-history.md#current-installation-boundary)

<a id="sentinel--operational-deployment-ground-truth"></a>
[Sentinel â€” operational deployment ground truth](sentinel-deployment-history.md#sentinel--operational-deployment-ground-truth)

<a id="local-go-validation-before-publication"></a>
[Local GO validation before publication](sentinel-deployment-history.md#local-go-validation-before-publication)

<a id="1-stocker-is-retired"></a>
[1. Stocker is retired](sentinel-deployment-history.md#1-stocker-is-retired)

<a id="stocker-base-is-a-build-artefact-not-the-retired-runtime"></a>
[`stocker-base` is a BUILD ARTEFACT, not the retired runtime](sentinel-deployment-history.md#stocker-base-is-a-build-artefact-not-the-retired-runtime)

<a id="2-paper-trading-only"></a>
[2. Paper trading only](sentinel-deployment-history.md#2-paper-trading-only)

<a id="3-the-frozen-oracle-outranks-the-prose"></a>
[3. The frozen oracle outranks the prose](sentinel-deployment-history.md#3-the-frozen-oracle-outranks-the-prose)

<a id="4-steps-02-are-resolved"></a>
[4. Steps 0â€“2 are RESOLVED](sentinel-deployment-history.md#4-steps-02-are-resolved)

<a id="the-recovered-semantics-normative"></a>
[The recovered semantics, normative](sentinel-deployment-history.md#the-recovered-semantics-normative)

<a id="5-first-operational-requirement--retire-the-legacy-paper-book"></a>
[5. First operational requirement â€” retire the legacy paper book](sentinel-deployment-history.md#5-first-operational-requirement--retire-the-legacy-paper-book)

<a id="rules-this-sequence-must-satisfy"></a>
[Rules this sequence must satisfy](sentinel-deployment-history.md#rules-this-sequence-must-satisfy)

<a id="6-wealth-core-is-staged-before-sentinel-controls-exposure"></a>
[6. Wealth Core is staged BEFORE Sentinel controls exposure](sentinel-deployment-history.md#6-wealth-core-is-staged-before-sentinel-controls-exposure)

<a id="7-the-shadow-independence-falsifier-stated-correctly"></a>
[7. The shadow-independence falsifier, stated correctly](sentinel-deployment-history.md#7-the-shadow-independence-falsifier-stated-correctly)

<a id="8-live-data-readiness-is-a-gate-and-126-rows-is-not-the-test"></a>
[8. Live-data readiness is a gate, and "126 rows" is not the test](sentinel-deployment-history.md#8-live-data-readiness-is-a-gate-and-126-rows-is-not-the-test)

<a id="8a-production-snapshots-persist-a-bounded-restart-image-not-feed-history"></a>
[8a. Production snapshots persist a bounded restart image, not feed history](sentinel-deployment-history.md#8a-production-snapshots-persist-a-bounded-restart-image-not-feed-history)

<a id="9-price-domain-validation-must-be-wealth-core-specific"></a>
[9. Price-domain validation must be Wealth-Core-specific](sentinel-deployment-history.md#9-price-domain-validation-must-be-wealth-core-specific)

<a id="9a-exactly-one-mutable-corpus-eventually"></a>
[9a. Exactly ONE mutable corpus, eventually](sentinel-deployment-history.md#9a-exactly-one-mutable-corpus-eventually)

<a id="10-finish-the-three-year-rehearsal-and-do-not-reduce-it-to-cagr"></a>
[10. Finish the three-year rehearsal, and do not reduce it to CAGR](sentinel-deployment-history.md#10-finish-the-three-year-rehearsal-and-do-not-reduce-it-to-cagr)

<a id="10a-a-result-is-evidence-only-if-the-environment-is-named"></a>
[10a. A result is evidence only if the environment is NAMED](sentinel-deployment-history.md#10a-a-result-is-evidence-only-if-the-environment-is-named)

<a id="10aa-a-feed-writer-is-authorized-by-the-current-clean-checkout"></a>
[10aa. A feed writer is authorized by the current clean checkout](sentinel-deployment-history.md#10aa-a-feed-writer-is-authorized-by-the-current-clean-checkout)

<a id="rebuild--the-dockerfile-requires-the-lock--and-verify-the-image-identity"></a>
[rebuild â€” the Dockerfile requires the lock â€” and verify the image identity](sentinel-deployment-history.md#rebuild--the-dockerfile-requires-the-lock--and-verify-the-image-identity)

<a id="10d-the-record-must-name-the-built-image-not-only-its-inputs"></a>
[10d. The record must name the BUILT IMAGE, not only its inputs](sentinel-deployment-history.md#10d-the-record-must-name-the-built-image-not-only-its-inputs)

<a id="10e-finalizing-the-rehearsal-is-automated-too"></a>
[10e. Finalizing the rehearsal is automated too](sentinel-deployment-history.md#10e-finalizing-the-rehearsal-is-automated-too)

<a id="one-resolver-decides-which-image-is-meant"></a>
[One resolver decides which image is meant](sentinel-deployment-history.md#one-resolver-decides-which-image-is-meant)

<a id="the-base-is-rebuilt-before-the-engine-and-then-verified"></a>
[The base is rebuilt before the engine, and then verified](sentinel-deployment-history.md#the-base-is-rebuilt-before-the-engine-and-then-verified)

<a id="10b-refused-rows-are-a-certification-item-not-only-an-operational-warn"></a>
[10b. Refused rows are a CERTIFICATION item, not only an operational WARN](sentinel-deployment-history.md#10b-refused-rows-are-a-certification-item-not-only-an-operational-warn)

<a id="split-reconciliation-has-one-implementation-and-is-an-operational-gate"></a>
[Split reconciliation has one implementation and is an operational gate](sentinel-deployment-history.md#split-reconciliation-has-one-implementation-and-is-an-operational-gate)

<a id="10c-synthetic-parity-is-not-corpus-parity"></a>
[10c. Synthetic parity is not corpus parity](sentinel-deployment-history.md#10c-synthetic-parity-is-not-corpus-parity)

<a id="cold-boot-identity-collapse-is-a-loader-failure-not-membership-drift"></a>
[Cold-boot identity collapse is a loader failure, not membership drift](sentinel-deployment-history.md#cold-boot-identity-collapse-is-a-loader-failure-not-membership-drift)

<a id="10e-bis-the-env-is-built-by-subtraction-from-stockers"></a>
[10e-bis. The `.env` is built by SUBTRACTION from Stocker's](sentinel-deployment-history.md#10e-bis-the-env-is-built-by-subtraction-from-stockers)

<a id="10f-the-resource-envelope-is-measured-and-the-measurement-is-an-artefact"></a>
[10f. The resource envelope is MEASURED, and the measurement is an artefact](sentinel-deployment-history.md#10f-the-resource-envelope-is-measured-and-the-measurement-is-an-artefact)

<a id="what-it-samples-and-why-each-one-is-there"></a>
[What it samples, and why each one is there](sentinel-deployment-history.md#what-it-samples-and-why-each-one-is-there)

<a id="the-verdicts"></a>
[The verdicts](sentinel-deployment-history.md#the-verdicts)

<a id="not-every-host-can-enforce-every-declared-limit"></a>
[Not every host can ENFORCE every declared limit](sentinel-deployment-history.md#not-every-host-can-enforce-every-declared-limit)

<a id="what-this-means-for-15"></a>
[What this means for #15](sentinel-deployment-history.md#what-this-means-for-15)

<a id="what-sentinel-certifysh-does-not-cover"></a>
[What `sentinel-certify.sh` does NOT cover](sentinel-deployment-history.md#what-sentinel-certifysh-does-not-cover)

<a id="10g-postgresql-requires-a-second-target-backup-not-only-a-volume"></a>
[10g. PostgreSQL requires a second-target backup, not only a volume](sentinel-deployment-history.md#10g-postgresql-requires-a-second-target-backup-not-only-a-volume)

<a id="one-reviewed-restart-enables-archive_mode-it-never-removes-a-volume"></a>
[One reviewed restart enables archive_mode; it never removes a volume.](sentinel-deployment-history.md#one-reviewed-restart-enables-archive_mode-it-never-removes-a-volume)

<a id="checkpoint-on"></a>
[checkpoint: on](sentinel-deployment-history.md#checkpoint-on)

<a id="10h-the-panel-reports-durable-facts-never-deployment-stage-placeholders"></a>
[10h. The panel reports durable facts, never deployment-stage placeholders](sentinel-deployment-history.md#10h-the-panel-reports-durable-facts-never-deployment-stage-placeholders)

<a id="11-execution_model-activation-is-a-versioned-operational-event"></a>
[11. `execution_model` activation is a versioned operational event](sentinel-deployment-history.md#11-execution_model-activation-is-a-versioned-operational-event)

<a id="actions-source-row-identity-and-failed-daily-recovery-2026-08-14"></a>
[ACTIONS source-row identity and failed-daily recovery (2026-08-14)](sentinel-deployment-history.md#actions-source-row-identity-and-failed-daily-recovery-2026-08-14)

<a id="wealth-core-and-cagr-impact"></a>
[Wealth Core and CAGR impact](sentinel-deployment-history.md#wealth-core-and-cagr-impact)

<a id="12-implementation-order"></a>
[12. Implementation order](sentinel-deployment-history.md#12-implementation-order)

<a id="13-definition-of-the-first-milestone"></a>
[13. Definition of the first milestone](sentinel-deployment-history.md#13-definition-of-the-first-milestone)

<a id="backup-upgrade-checkpoint-september-2026"></a>
[Backup upgrade checkpoint (September 2026)](sentinel-deployment-history.md#backup-upgrade-checkpoint-september-2026)


## Current local PAPER architecture migration (October 23, 2026)

The owner-authorized local PAPER profile uses the qualified feature checkout and
the resumable local delivery coordinator. Its architecture and one-time b2e308bb
quiescence bridge are specified in [the operational architecture decision](operational-architecture-20261023.md).
The candidate adds a broker-free verifier and a GET-only execution collector to
the shadow, automation, panel and notification-sender roles; all six roles use
one exact qualified image. The sender has no broker credentials. Schema and
bounded projection bootstrap occur explicitly after application quiescence;
runtime reads never migrate or reseed coverage.

Backups, archiving, restore drills and their verification remain suspended by
the owner in this profile. PostgreSQL identity, volumes, canonical history and
financial journals are preserved. This local PAPER profile does not authorize
live endpoints or satisfy the separately reviewed live-operation requirements.
# Current local PAPER architecture migration (October 23, 2026)

The owner-authorized local PAPER profile uses the qualified feature checkout and
the resumable local delivery coordinator. Its architecture and one-time b2e308bb
quiescence bridge are specified in [the operational architecture decision](operational-architecture-20261023.md).
The candidate adds a broker-free verifier and a GET-only execution collector to
the shadow, automation, panel and notification-sender roles; all six roles use
one exact qualified image. The sender has no broker credentials. Schema and
bounded projection bootstrap occur explicitly after application quiescence;
runtime reads never migrate or reseed coverage.

Backups, archiving, restore drills and their verification remain suspended by
the owner in this profile. PostgreSQL identity, volumes, canonical history and
financial journals are preserved. This local PAPER profile does not authorize
live endpoints or satisfy the separately reviewed live-operation requirements.
