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

GO supplies the durable job's absolute UTC deadline from the host preparation
budget, captured before the initial backup check. Initial backup, container
startup, schema preparation, acquisition, renewal and validation all consume
that same budget. The host also enforces its monotonic deadline independently.
The GO path must not fall back to the standalone preparation API's one-hour
default. A supplied deadline is validated against the database clock and the
existing maximum job horizon of 24 hours. Resuming or coalescing an existing job
never extends its original deadline; expired jobs remain refused.

The runtime reports job deadline exhaustion distinctly from a lost worker lease
or fence. The ten-minute worker lease and its ownership checks are unchanged.
The host accepts the builder's bounded rolling identity, normalization, sealing,
validation and publication progress, including only validated job UUIDs and
enumerated subphases. It must not keep showing a completed source partition
while discarding those later progress events. Qualification uses a controlled
clock to compose work beyond one hour with backup renewal, unchanged deadline
on resume, retained-part reuse, and refusal at the actual deadline.

The next preparation explicitly resumes the named operational job. Its request
must still equal the current strategy, dependencies, publication CAS and source
window. Expired, terminal, comparison, leased or unrelated jobs cannot be silently
replaced by a newly enqueued job. Provider revisions continue to use the existing
bounded successor mechanism. Retained reference parts are revalidated immediately.
For an unsealed candidate, retained SEP price payloads are checked against their
manifests during the mandatory independent coverage scan, before sealing; this
avoids a separate full price-row pass. READY resumes keep immediate verification.
Unchanged parts are not downloaded again. Uncommitted
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

## Progress across the remaining worker stages

### Check restore capacity before repeated work

Decision: 2026-10-03. Operational preparation checks the restore horizon at
the start of READY-candidate validation, before reading the whole candidate.
Run that validation before the final provider corroboration. A WAL horizon
failure therefore reaches the existing host renewal path before another assets
and actions download. After renewal, verify retained source parts and the sealed
candidate, then corroborate the provider once before publication. The final
publication backup check remains mandatory. The comparison-only path retains
its existing ordering. No proof is cached, no integrity ceiling is increased,
and no deadline, fence or source-consistency requirement is removed.

Local daily diagnostics must preserve the previous input fixture separately
when they do not install an authenticated operational checkpoint. Production
retention already pins an admitted restart checkpoint; an unadmitted in-memory
or on-disk diagnostic book does not create that database dependency. Fixture
preservation grants no admission, checkpoint or broker authority. Report the
diagnostic scope separately from durable automation qualification.

The overall preparation deadline does not replace the ten-minute worker lease.
Sealing, source corroboration and operational validation must renew at stage
boundaries and during bounded units of actual work. Snapshot storage scans pulse
after each 5,000 rows, and corroboration pulses between bounded provider checks.
A scoped callback on the worker's existing connection supplies the heartbeat;
outside that scope (including read-only GO, panel and strategy readers) the
storage hook does nothing. The scope is always reset on success or failure.
Callbacks never commit candidate construction or create a second writer. Every
renewal checks the original owner, fence, current lease and absolute job deadline.
An uninterrupted blocking unit that exceeds its lease still refuses.
The publication transaction applies the same scoped renewal while retaining
sparse action history, with checkpoints between action dates. That scope ends
before the job becomes terminal; no heartbeat may resurrect a published job.

Both foreground GO and scheduled rolling publication use this same publisher.
Automation leadership remains a separate supervised lease; renewing acquisition
never renews broker authority. Alpaca transport ambiguity retains UNKNOWN and
the existing deterministic command identity. Qualification must slow the actual
storage/source work between callbacks, rather than manufacture heartbeats in a
test wrapper, and cover deadline expiry, stolen fences and scope cleanup.

Host diagnostics also accept the existing historical-formation progress events.
Display completed sessions out of the fixed 126-session formation, plus a
validated session date when present. These bounded counters describe canonical
startup work after acquisition; they are not another source download or a GO
verdict. Reject malformed counters, dates and unreviewed fields as before.

## Scheduled shadow acquisition budget

The rolling shadow service owns daily acquisition; paper automation waits for
its verified result. Each supervised shadow attempt supplies its absolute UTC
cutoff to the rolling acquisition job, captured before spawning the worker.
The existing configurable 30–7200 second supervisor limit remains unchanged.
Direct service calls capture the same configured budget before preflight.
Preflight and acquisition consume one allowance; neither nested calls nor
coalescing an existing durable job may extend its original deadline.

An exhausted durable acquisition deadline is a retryable availability outcome,
like the supervisor's process timeout, not evidence of integrity failure. The
expired job remains terminal; a later attempt may enqueue a new job and reuse
independently validated retained source parts. Uncommitted candidate work may
need rebuilding. Stolen fences, invalid identities and other integrity refusals
still latch. Publication and following-open timing checks remain mandatory and
no stale shadow result becomes broker authority. A local controlled-clock test
must traverse the actual shadow service, exceed one hour with legitimate work
renewals, and separately exhaust the configured cutoff without publication.

## Bounded final handoff

Promotion-time Git and final Docker/Compose subprocesses must also honor the
host command timeout. Run each in an owned process group and terminate/reap that
group on timeout or interruption. Do not remove persistent service containers
when terminating their Compose client; an interrupted handoff is refused and
ordinary retry inspects/recreates the named panel. This command helper grants no
broker authority and is independent of the acquisition budget.

Panel finalization waits for the existing health check with a 180-second startup
bound, then verifies both healthy/running state and exact image identity before
writing handoff evidence. Wrong image, unhealthy/exited/restarting state, timeout
or unobservable health cannot produce a successful handoff. The selected runtime
and completed data publication remain available for retry.
