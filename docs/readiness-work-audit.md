# Readiness work audit after PR 548

The owner requested a further duplicate-work and simplification audit on October
29, after PR 548 was installed. The verified base is
`c681db9b34ed62c65b81bfbd1b922474a2a2f5fd`. This review concerns the release and
operational evidence paths, not the strategy, controller or economic book.

## Confirmed repetitions and fixes

| Path | Previous work | Selected change |
| --- | --- | --- |
| One activation owner | Installation promotion, reviewed preflight and bootstrap promotion independently downloaded and verified the same software certification. | Reuse the completed software proof within that deployment object only. Check the process, clean commit/tree, verifier policy and exact image at reuse; keep fresh financial and account checks. |
| GO panel handoff | Unconditionally recreated the panel even when the immutable image and Compose configuration already matched. | Let Compose reconcile configuration, then independently require the selected exact image and healthy process. |
| Ordinary account writer admission | Acquired the account writer lock before a cold or due archive byte scrub. | Earn the expensive backup proof before acquiring account ownership, then require current backup admission again under ownership. |
| Backup proof age | Timestamped a successful full scrub before its two byte passes. A slow scrub could already be expired when it returned. | Start the reuse interval when the complete successful proof finishes. Metadata-only and incremental checks do not renew that interval. |
| Backup proof process scope | A fork inherited the module dictionary despite its documented process-local contract. | Include the process identity in the cache scope. A child must earn its own proof. |
| Shadow advancement | Kept the financial writer lock through independently guarded disposable input retention. | Publish verified shadow health while still owning the financial transition; release that ownership before retention acquires its own guards. Cleanup failure cannot undo the completed financial verification. |
| One dashboard read snapshot | Computed the same cluster, installation, DDL epoch and environment facts separately for SHADOW and PAPER subjects. | Read those common facts once in the existing repeatable-read snapshot. Keep independent scope revisions and byte-identical subject digests. |
| Verifier restart | Discarded still-valid authenticated completed display evidence and immediately repeated the expensive observation. | Restore only a completed, exact-current-subject receipt under the sole verifier owner. Preserve its original observation and expiry; never resume another owner's pending work. |
| Verification diagnostics | A queued check did not identify why it was needed. | Distinguish changed subject, expiry, periodic refresh, prior failure and absence of a completed proof. These are display diagnostics, not new authority. |

The detailed decisions and invalidation rules are in
[software proof reuse](activation-software-proof-reuse.md),
[dashboard verification](dashboard-verification-monitor.md), and
[backup writer admission](backup-writer-admission-cost.md). The source compatibility seal admits only these exact
reviewed operational successors; historical baselines and economic compiler
identities remain unchanged.

## Work that still earns new evidence

The normal daily input job advances the validated closed session. In the observed
release it moved from October 28 to October 29 and fetched the current 300-session
window. Its generation includes the as-of session, listing/identity selection and
corporate actions. The full overlap also detects historical provider corrections.
`acquisition_parts.Parts.get` already reuses complete parts within a job and its
bounded revision lineage; `put` shares identical stored price payloads across
jobs after authenticating their content. Reusing an earlier day's network answer
without observing corrections would change the data contract. No such shortcut
is introduced here.

The sealed input-window verifier already shares a completed scan within the
original live corpus pin. Its manifest, publication and lock checks prevent
incomplete or stale scans from becoming reusable facts. Independent processes
and later publication pins are separate evidence boundaries. This change does
not replace their scans with a persisted PASS or remove input corruption checks.

The two archive byte passes compare content as well as metadata. They detect
changes during verification and are not duplicate permission checks. New WAL
objects, changed metadata, expired complete proofs, missing media, aliases and
changed base selection still require the native checks. Host backup-status and
final activation checkpoint also cover different horizons: the latter includes
newly committed plan, control and authority state. No base backup or full restore
is added by these optimizations.

The first normal scheduler callback already adopted the activation plan in the
observed release: zero replayed sessions, zero warmup sessions and the same plan
identity. Fresh broker, funding, source, command, leader and generation checks at
that handoff remain necessary. Preparation is not order submission authority.

## Qualification and operational boundary

Use targeted host tests, count assertions and executed guard-removal falsifiers.
Measure the removed downloads, database reads, scrubs and lock ordering directly;
do not infer a production wall-clock improvement from small synthetic inputs.
Required CI remains the release qualification boundary. No Docker test image,
physical database copy, production service restart, scheduled monitor or broker
operation is needed to develop this change.

The prior disk-pressure incident is not permission to erase retained evidence,
backup media or unrelated workloads. This task uses a sparse worktree, small
isolated host dependencies and bounded test outputs. Existing private Docker
qualification capacity guards remain in force.
