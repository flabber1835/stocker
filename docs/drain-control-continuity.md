# Responsive drain and predecessor continuity

This is a corrective development decision for the local PAPER application
installer. It does not change financial authority, broker permissions, deadlines,
the canonical book, UNKNOWN recovery, or the frozen economic implementation.
The independently installed diagnostic image remains a separate artifact.

## Demonstrated defects

The publisher's 300-second idle interval refreshes its heartbeat but does not
consume a drain request until the next worker-admission boundary. The installer
waits only 180 seconds, starting a new acknowledgement subprocess every two
seconds. A healthy idle publisher can therefore miss the finite handoff deadline.

Docker restarts retain a container's ID and image. Those two facts alone do not
prove that an acknowledgement still belongs to the process about to be stopped.
A final incarnation read can correctly refuse a changed process, but a read alone
cannot prevent automatic restart between acknowledgement and stop.

These are independently demonstrated control defects. Neither proves the
historical cause of a database timeout or supervisor ARM timeout.

## Idle acknowledgement

The existing bounded heartbeat operation also observes drain control. An
acknowledgement-only function acquires the existing admission lock and consumes
only an authenticated, unexpired request for the exact binding and supervisor
incarnation. It never arms a worker, changes the next market-poll deadline, starts
a process, or performs readiness/database/broker work.

Pending or critical work prevents acknowledgement. Existing request, ownership,
expiry, original acknowledgement-clock and unresolved-work guards remain intact.
The ordinary worker-admission path uses the same request/acknowledgement logic.
The heartbeat's existing bounded child contains filesystem/lock failure; no new
fork or installer readiness loop is introduced.

## Continuity hold before requesting drain

Before a policy update, the existing DRAIN_REQUESTED journal transition records
the exact predecessor container/image, StartedAt, RestartCount and original
reviewed Docker restart policy. The cooperative drain path idempotently changes
only that container's policy to `no`, and verifies the policy and process identity
afterwards. A changed incarnation, pending restart or unexpected policy refuses.

The hold remains enforced throughout acknowledgement and clean application stop.
Identity/counters/policy are checked around acknowledgement and immediately before
and after stop; a check is evidence, while the policy hold prevents automatic
restart across those checks. The existing global delivery lock excludes competing
supported installers. External operator/container mutations are forbidden during
the owned operation and any detected mutation refuses.

The supported path still waits for a genuine finite authenticated acknowledgement.
It never kills an idle publisher to manufacture quiescence. Installation of a new
candidate recreates shadow from reviewed Compose, restoring its reviewed restart
policy naturally. An incomplete old receipt without the continuity target cannot
be upgraded silently or continue destructive work.

## Explicit abandonment and recovery

A refused operation does not silently restore admission. A supported
`abandon-drain` operation owns the existing global delivery lock and is allowed
only before installation changes, while the original environment/Compose and the
other predecessor applications remain intact. It first durably records terminal
abandonment bound to the immutable request, current receipt and journaled target.
Every later installation advance checks this terminal record and refuses.

Only after terminal intent exists may recovery restore the journaled exact
original policy on the exact old container/image. It observes Docker process
counters, running/restarting state and existing pending/critical state without
removing or reinterpreting those files. An ambiguous/foreign target or policy
refuses. A running predecessor continues through its original finite request
expiry; release does not invent acknowledgement or clear its request.

If the exact predecessor has already exited, the explicit recovery command may
start that exact container after policy restoration. Startup uses the installed
UNKNOWN/pending/critical recovery rules; recovery never asserts that the old ACK
is current or that unresolved work succeeded. A durable abandonment completion
record captures the observed result. The single terminal record has finite
INTENT, START_REQUESTED and COMPLETE recovery checkpoints. Lost acknowledgement
resumes this terminal recovery only: policy restoration is idempotent, and a
changed StartedAt with Docker's manual-start RestartCount of zero positively
proves the one requested start, even if installed startup subsequently refused.
An unchanged start clock after START_REQUESTED is UNKNOWN, never permission for
another start. This can require inspection of the outstanding Docker operation;
the command neither invents a successful start nor retries uncertain admission.
A subsequent installation requires a fresh NEW operation and fresh current-state
proofs. COMPLETE describes policy recovery, not financial readiness.

The exact supported command is `abandon-drain --operation-dir <original-dir>`
on `python -B scripts/sentinel_local_delivery.py` or the backed adapter
`python -B scripts/sentinel_backed_local_patch.py`. `status` reports terminal
abandonment separately from the unchanged last installation stage. No automatic
invocation is added.

No receipt clock is extended, no financial/source/notification history is reset,
and no background process may clear a hold merely because the operator has left.

## Qualification

Focused tests must cover heartbeat-only idle acknowledgement, absence/expiry and
foreign incarnation, pending/critical refusal, preservation of the first ACK clock,
and no early worker admission. Removing the idle observation must fail its timing
falsifier. Installer tests must cover same-ID/image restart before/during ACK,
restart-policy mutation, lost update acknowledgement, stopped predecessor,
continuity checks around stop, terminal abandonment before policy restoration,
lost recovery acknowledgements, and refusal of advance after release. A falsifier
must show why a StartedAt check without a restart hold is insufficient.
