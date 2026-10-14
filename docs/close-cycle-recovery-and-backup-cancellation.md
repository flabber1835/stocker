# Close-cycle recovery and backup cancellation

Decision: 2026-10-12. The observed close cycle attempted preflight broker
recovery using its following execution session before refreshing its decision
inputs. A Friday publication supports Monday identities, not Tuesday. The
existing `ROLLING_IDENTITY_BEYOND_NEXT_SESSION` guard correctly refused; the
orchestrator recorded an unreviewed software defect before acquisition.

Preflight recovery is observation, not prospective execution. For a discovered
cycle or its explicitly pending preflight retry, with no plan bound, resolve
broker identities for the current exchange-date session on or after that date,
capped at the cycle's effective session. Use the canonical exchange calendar and
actual UTC clock. Ordinary transport recovery retains the effective-session
resolver. Missing current-session coverage is a typed availability wait only in
this preflight path; other identity/integrity failures remain refusals. Do not
extend identity authority, invent prices, bypass UNKNOWN, reorder the mandatory
shared-journal proof behind publication, or move broker inputs into the strategy.

Extend the existing separately authorized unsent recovery contract with
`PREFLIGHT_IDENTITY_BEYOND_FRONTIER`. Eligibility requires a nonhistorical blocked
cycle with `SoftwareDefect`, the exact unreviewed
`sentinel.execution.feed_inputs.ExecutionInputsRefused:
ROLLING_IDENTITY_BEYOND_NEXT_SESSION` exception, and the persisted
`PREFLIGHT_RECOVER` / `SOFTWARE_DEFECT` diagnostic. There must be no plan, no
transport/reconciliation events, no commands or UNKNOWN outcomes. All existing
lineage, exact-binding, killed/stopped-writer, pre-open, fresh-authority,
predecessor, idempotency and fresh-plan guards remain mandatory. The receipt
records its actual recovery kind; arbitrary errors or operator descriptions
cannot qualify. Old contention recovery and immutable receipts remain valid.

The concurrent incident showed a physical backup at 96% when its in-primary
600-second timeout coincided with SIGTERM of a PostgreSQL backend and a
three-second database recovery. An isolated reproduction of the in-primary
timeout terminated a server backend and caused the same database recovery.
Moving the client into a separate PID namespace prevents that cancellation
from reaching primary processes. Qualify this on a disposable instance.

Run the physical backup client in a disposable container with its own PID
namespace, using the already pinned PostgreSQL image and existing backup mount.
It shares the primary network namespace through Compose's service network mode,
so local replication authentication remains unchanged; it never shares the PID
namespace. It receives only database/backup configuration, not
broker credentials. It retains the canonical media lock through copy and
verification; cancellation can signal only that client's processes. Primary
SQL probes and exact recovery/manifest/WAL checks retain their existing owners.
No incomplete stage becomes a selected base, no selection is guessed, and no
primary process is intentionally terminated. A failed attempt preserves the
last admitted recovery chain and yields to ordinary supervised maintenance.

The finite client budget is the existing 900-second host base-command budget
minus 60 seconds; its 30-second termination grace stays inside the outer budget.
Trading callback budgets and backup identity/retention/restore gates do not
change. Qualify real cancellation, normal copy/verification, database continuity,
media-lock exclusion and cleanup after interruption. Qualification must use a
disposable database and backup target, never production crash injection.

Retained executable admission gets a new exact predecessor/target profile.
Earlier profiles and fixtures remain unchanged; no economic state, calendar,
capital, market-data policy or immutable historical record is re-pinned.

Deployment must use the protected certified image and supported fenced installer
and activation. Archive the inspected shadow incident markers only after the
installer stops the publisher and preserves its retained lineage, following
the existing [operator clearance procedure](autonomous-paper-readiness.md).
At activation's enabled-but-killed checkpoint, before the canonical kill release,
authorize this unsent cycle with exact incident, decision, binding and certificate
confirmations. Then release the kill through its existing contract and verify a
fresh Tuesday plan reaches `WAITING_OPEN` before opening. Use the existing
certified operator CLI and writer-handoff proofs; never start a blocked dispatcher
as an intermediate activation test or bypass an authority check.

Expose this insertion as an explicit, reusable activation request, not a custom
driver override. Normal requests retain schema version 1 and never recover
cycles. Version 2 seals a confirmed unsent-recovery payload (blocked cycle,
decision session, actor and reason) in the same immutable request. Queue creation
requires the separate explicit recovery confirmation; shadow-only requests
refuse it. Both canonical paper activation implementations call the existing
authorized recovery CLI after backup verification and stopped-writer proofs,
while control is enabled and killed, immediately before ordinary kill release.
Require the CLI receipt to match the requested cycle/session and newly activated
certificate, retain it in the activation evidence, and refuse release on any
failed or ambiguous recovery. All financial eligibility remains owned by the
certified generic recovery CLI. Completed activation requests remain one-shot.
An authorization or a healthy process alone does not establish trading readiness.

The shadow incident is a third boundary error: a worker that began against the
previous close reached current readiness after the exchange close changed.
Its otherwise valid previous publication failed only the source-final frontier
clause, which was misclassified as terminal integrity. Introduce a typed
`RollingSourceFrontierPending` only when that is the sole failed readiness
clause and the authenticated input session is older than the source-final
target. The shadow service reports the existing bounded waiting outcome and
the next scheduled attempt acquires the new close. Future frontiers, combined
failures, population/domain failures, and immutable identity failures remain
terminal refusals. No stale publication earns trading authority. The new
exact retained-source profile also pins this reader and service adapter.

The dual status bridge preserves this pending classification when the public
shadow wrapper retains `RollingSourceFrontierPending` as its direct typed cause.
Only that native cause maps to `DualReconciliationPending`; matching text,
unrelated causes, future frontiers and combined readiness failures remain
permanent refusals. Refresh then uses its existing bounded `SourceDataPending`
retry path, without granting stale intent or altering execution deadlines.

For a legacy cycle already latched by this adapter defect, add the explicit
unsent-recovery kind `ROLLING_SOURCE_FRONTIER_MISCLASSIFIED`. Require no plan,
`NonRetryableCallbackRefused`, the exact shadow-status/frontier refusal detail,
`retry_phase=REFRESH`, permanent callback/terminal diagnostics and the exact
exception type. All original lineage, stopped-writer, killed control, exact
binding/certificate, latest-close/pre-open, negative transport/command/UNKNOWN,
one-shot and fresh-plan conditions remain. The unchanged generic recovery owner
creates a fresh cycle and preserves the failed predecessor and its events.
Seal this separately confirmed recovery in the existing activation request;
the initial-paper anchor repair may accompany it, but neither is inferred by
ordinary activation. Never reopen a missed execution window.

The supervised GO check exposed a host-to-image permission defect: its private
umask produced a mode-0600 retained-source manifest owned by the host UID, while
the certified image runs as a different non-root UID. This manifest contains
only untrusted Git source evidence and hashes, never credentials. Publish the
completed temporary file with explicit mode 0444 before its existing single-file
read-only bind mount. Keep the host temporary directory private and retain its
bounded lifetime and cleanup. Do not alter secret-file permissions, image users,
broker authority, manifest contents, or image-side authentication. Qualify a
restrictive host umask, omission of the permission step, and a real non-root
image reading the mounted evidence.
