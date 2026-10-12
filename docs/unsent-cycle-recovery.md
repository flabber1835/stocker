# Operator recovery of an unsent prospective cycle

Decision: 2026-10-11. An older authority adapter classified a typed local
availability failure as permanent. Repairing that adapter preserves the
`BLOCKED` cycle, but the prospective replacement policy correctly rejects that
history. Add a separately authorized, reusable recovery path for this reviewed
failure category. No dates, account identities or cycle ids are compiled into it.

The first recovery kind is `LOCAL_CONTENTION_MISCLASSIFIED`: an ordinary
non-historical blocked cycle whose final control-poll refusal records
`NonRetryableCallbackRefused` and the adapter's typed `CorpusLockUnavailable`
or `WriterLockUnavailable` cause. Other integrity, signature, ownership,
configuration and unknown failures remain ineligible. Additional recovery kinds
require a reviewed design and independent qualification; arbitrary operator
text never changes eligibility.

The independently qualified `PREFLIGHT_IDENTITY_BEYOND_FRONTIER` subtype is
specified in [close-cycle recovery](close-cycle-recovery-and-backup-cancellation.md).
It admits only the exact unreviewed identity-boundary exception in a planless,
unsent preflight block. Its receipt kind must match the confirmed predecessor;
all negative transport, lineage, authority, time and writer-fencing proofs remain.

`authorize-unsent-paper-recovery` runs only in the certified authorized CLI. It
requires exact deployment/account/certificate, decision session and originating
blocked-cycle confirmations, actor/reason, explicit old-writer fencing and an
explicit recovery confirmation. Current automation must be activated with its
kill engaged and no live leader. It verifies fresh signed AUTOMATION authority,
backup authority and the complete immutable control/cycle lineage while holding
the canonical execution writer. The actual latest closed decision must match;
both verified host time and PostgreSQL time must precede the intended session
open. Missing or ambiguous evidence refuses.

Every predecessor in the exact deployment/account/takeover/decision scope must
be an ordinary unsent generation supersession or an eligible contention block.
Any execution/reconciliation event, current nonterminal cycle, historical-only
cycle, newer/equal originating generation or durable command for a predecessor
or the scoped execution session refuses. Unresolved commands anywhere in this
account scope also refuse. The command does not contact a broker or create a
plan. Fresh broker reconciliation remains mandatory at the replacement cycle's
ordinary read-only preflight before preparation or transport.

Success advances the control generation behind the existing kill fence and
appends an existing `KILL_ENGAGED` control event with strict typed
`sentinel.unsent-recovery/1` authorization detail. This subtype requires the
fence already engaged; ordinary kill engagement still requires a released kill.
Its detail binds current control authority, decision/effective session,
the complete sorted predecessor set and fingerprints of their retained records.
The original cycle, failure events, book and financial journal remain unchanged.
No new schema or DDL is required. Kill release is still a separate exact-authority
operation. The authorization is usable only through that immediately following
release generation; reactivation, another kill or certificate/config/account
change requires a new authorization. A repeated request while still fenced
recovers the identical receipt rather than creating additional generations.

Retained executable admission uses a new independently pinned
`unsent-recovery-upgrade.json` profile. It covers only the exact scheduler,
lineage and CLI source transitions and exact new recovery-module bytes. Its
predecessors are the verified current-main source closure and already reviewed
historical source manifests/profiles. Earlier profiles and fixtures stay intact;
no economic module, environment, calendar, dependency or capital change is
admitted. The profile itself grants no deployment or broker authority.

Prospective discovery and creation repeat the same predecessor, command,
binding and time proof under the canonical writer. Authorized blocked
predecessors are admitted only with the retained exact receipt. The new cycle's
genesis binds that receipt generation, as well as every predecessor. Its
deterministic per-generation identity remains idempotent across polling,
concurrent creation and process restart. Lineage validation authenticates the
receipt and predecessor fingerprints for the lifetime of the new cycle, without
reinterpreting a past authorization using today's wall clock. It never executes
an old plan, infers a fill, relaxes UNKNOWN or changes next-open execution.
The replacement cycle may not bind any predecessor plan id. If ordinary
same-session preparation would reuse that id, it must refuse; use the existing
reviewed same-mode certificate/rollout renewal before authorizing recovery.
This keeps fresh authority and plan construction explicit without changing
execution-plan economics or command identity.

## Operator sequence

Install the certified recovery release and complete ordinary retained-state
activation, leaving the kill engaged. Stop/fence the prior worker, then run the
authorized command with the exact current certificate and selected failed cycle:

```text
authorize-unsent-paper-recovery
  --confirm-paper-account <account> --confirm-deployment-id <deployment>
  --confirm-certificate-sha256 <current-certificate>
  --decision-session <closed-session> --blocked-cycle-id <cycle>
  --confirm-old-writer-fenced --confirm-authorize-unsent-paper-recovery
  --actor <operator> --reason <incident>
```

Release the kill through the normal authorized command and resume the ordinary
scheduler. Verify fresh preflight, preparation and `WAITING_OPEN` before the
session opens. An authorization alone is not execution readiness. Once the open
is reached, recovery cannot create a plan for that open; the next actual closed
decision follows the existing scheduler policy.

## Qualification

Use isolated PostgreSQL and broker simulators. Cover exact eligibility and its
falsifiers; permanent/unknown refusals; all-predecessor, binding/config/authority,
command/UNKNOWN, historical, clock/open and fencing guards; rollback,
idempotency, concurrent creation, restart and immutable receipt/lineage tampering.
Join the real CLI, control replay, scheduler discovery, read-only preflight,
fresh preparation and execution-grant checks. Qualify exact retained-source
upgrade admission and reject neighboring edits. Run adjacent automation,
authority, paper execution, schema, dashboard, backup and source-admission tests.
No tests mutate the installed account, issue real orders or fabricate software
certification. Existing economic/controller fixtures remain unchanged.
