# GO renewal after acquisition WAL growth

GO's initial backup check is a point-in-time observation. Retained acquisition
parts and candidate construction can subsequently generate more WAL than the
runtime integrity proof budget permits. That condition must stop mutation but
must not turn a resumable preparation job into a terminal source failure.

Only the runtime archive-object/byte ceilings raise `BackupHorizonExceeded`, a
subclass of the existing runtime refusal. Geometry, cluster, checksum, alias,
missing-media and configuration failures retain their existing classifications.
No ceiling increases and no cached integrity proof are introduced.

At a worker boundary, the publisher rolls back the interrupted transaction and
persists `RETRY_WAIT/BACKUP_HORIZON_EXCEEDED` under its existing fenced lease. It
releases that lease and retains the same request, absolute deadline, committed
parts and any sealed candidate. Only after this succeeds does its failure carry
the resumable job ID. The exception escapes the in-container source wait loop.
Closing the failed preparation process releases its database locks before any
host backup operation begins.

Within the certified, lifecycle-locked GO preparation, the host accepts exactly
one structured horizon failure with a resumable job ID. It invokes the existing
backup-status, verified base-backup and exact-path verification path, with broker
authority removed and clean certified checkout checks. Only successful backup
verification permits another preparation invocation. At most two such renewals
are permitted (after acquisition and after candidate construction). All attempts
and backup commands share one monotonic preparation deadline; neither renewal
nor subprocess restart resets the durable acquisition deadline.

The next preparation explicitly resumes the named operational job. Its request
must still equal the current strategy, dependencies, publication CAS and source
window. Expired, terminal, comparison, leased or unrelated jobs cannot be silently
replaced by a newly enqueued job. Provider revisions continue to use the existing
bounded successor mechanism. Retained parts are revalidated by the existing
source and content checks; unchanged parts are not downloaded again. Uncommitted
candidate work may need rebuilding. Previously terminal jobs from older software
are not resurrected; already retired data cannot be recovered by this fix.

Backup renewal results and failures remain in the local backup audit. Preparation
evidence binds the whole renewal history, preserves elapsed time and attempted
work, and keeps earlier progress while reporting the final failure if any.
Interruption leaves a waiting job for a later ordinary GO invocation within its
original deadline. A failed renewal, malformed signal, changed checkout, expired
deadline or exhausted renewal count leaves GO at NO_GO.

Validation must compose real PostgreSQL job/part persistence and the host retry
boundary: healthy start, completed downloads, a runtime horizon refusal, verified
renewal and successful reuse. Exercise the READY boundary as well as ACQUIRING,
failed renewal, interruption, deadline exhaustion, malformed signals and a
non-horizon integrity refusal. Falsify the resumable-state and retry guards.
