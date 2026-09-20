# Recurring backup maintenance (Step 1)

## Decision, recorded before implementation

Maintenance is a host job using the existing physical producer, exact-path
status verifier and full physical plus semantic restore drill. It is not a
strategy service and has no broker credentials or broker calls. The same
immutable Sentinel image supplies the filesystem retention worker; that worker
has no network and receives only the backup mounts. No Docker socket is added
to a financial runtime container.
It runs as container root with all capabilities dropped except `DAC_OVERRIDE`,
which is required to traverse/delete PostgreSQL-owned 0700 WAL namespaces.
It does not change their ownership or weaken the production reader grants.
Its own 540-second alarm bounds abandoned workers independently of the host.

`scripts/sentinel-backup-maintenance.sh` is the production entry point. A
single invocation performs one tick; `--loop` retries ticks every 60 seconds,
including failures. Install it as a DSM user-defined scheduled task, using the
same approved host account as manual backup/restore commands. Schedule a tick
at least every minute (or supervise the loop and schedule its restart). Host
scheduler installation, reboot persistence and notifications are NAS
qualification, not something local tests can establish. The scripts do not edit
DSM's private scheduler database. Supported Task Scheduler entry points are
documented by [Synology](https://kb.synology.com/en-us/DSM/help/DSM/AdminCenter/system_taskscheduler?version=7).
The optional loop has a separate per-target supervisor flock, so a boot task
and periodic restart task cannot accumulate loops. Each child tick releases the
ordinary backup lock between attempts. Prefer scheduled single ticks when DSM
should notify on nonzero job completion; a long-running loop requires separate
log/health monitoring and must not be treated as healthy merely because it lives.

Each tick now runs under the process/output bounds recorded in
[autonomous paper readiness](autonomous-paper-readiness.md). The default outer
deadline is 3600 seconds; `--timeout-seconds` can lower it for a qualified host
budget. Cancellation kills the tick's private process group. Missing or invalid
runtime selection returns failure even if directory discovery would find a
complete backup; the verified producer is required to establish selection.

The existing per-target host lock serializes ticks, manual backup and manual
restore across checkouts under that account. In addition, actual Docker
workers hold a persistent filesystem flock: producer and retention exclusive,
restore shared from copying through PostgreSQL shutdown. It is never unlinked.
This second lock survives a dead host/Docker client while its worker lives.
The restore worker has a finite lifetime. Target filesystem flock semantics
and the one-host/one-operator-account restriction must be qualified on the NAS.

Disposable restore containers, volumes and internal networks carry an explicit
`sentinel.restore-drill=v1` label. The recurring coordinator removes only
well-formed, labeled restore volumes/networks older than two hours that Docker
reports as unused. Active resources are never reaped. This recovers disk space
after a killed host skips its cleanup trap; Docker still rejects concurrent use.
Physical and semantic workers have their own deadlines, independent of the host.
Names include a random 128-bit attempt suffix as well as UTC time and host PID;
cleanup tracks successful resource creation so a failed name reservation does
not authorize removing an existing object.

The PostgreSQL 16 drill exposed a timing-dependent recovery check: plain
`recovery.signal` can automatically finish recovery at archive end before the
host checks `pg_is_in_recovery()`. The restore worker therefore sets the recorded
marker LSN as `recovery_target_lsn` with `recovery_target_action=pause`. The host
must see the marker while recovery remains active, then explicitly promote for
semantic validation. Archive-end timing must not decide acceptance.
This behavior is specified by [PostgreSQL 16 recovery targets](https://www.postgresql.org/docs/16/runtime-config-wal.html#RUNTIME-CONFIG-WAL-RECOVERY-TARGET).
Legacy explicit restores remain available; their unbound evidence cannot
authorize current-cluster retention.

## Renewal and recovery

Use the cluster-bound runtime selection record; never discover a different
generation after a malformed selection. Read its bounded, nonaliased metadata.
Renew when the selected base reaches 12 hours, its inclusive WAL footprint
reaches 256 MiB, or the primary moves to a later timeline. The footprint uses
the primary's current WAL position, including unarchived activity. These are
early triggers, not a guarantee against arbitrarily fast WAL production.
The existing 1 GiB/1024-object runtime refusal remains authoritative.

After renewal, verify the exact returned path and re-read the selection. A
full restore must succeed before deletion. Persist a restore evidence row
binding the generation's metadata digest and immutable runtime image; old
unbound or physical-only evidence cannot authorize retention. A restart before
that row exists repeats the restore. A restart after it exists can reuse the
identity-bound proof, but must freshly validate the selected runtime chain.
Unresolved preflight media, identity, clock, producer, restore or evidence
failures stop that tick without deletion. Failures during deletion preserve the
journal for guarded recovery. Scheduled retries do not silently repair corruption.

## Retention

Preserve all bases younger than 24 hours, the selected generation, the newest
two generations, seven distinct UTC daily representatives and four distinct
ISO-week representatives (all available representatives while history builds).
Take the newest generation in each bucket. Completed metadata must be valid
and current-cluster-bound before an inventory can authorize deletion; unknown,
foreign, aliased or incomplete generations require operator disposition.
Inventory entry and aggregate metadata byte limits bound each worker.

A durable deletion journal records candidates and the identities of every
protected base before any rename. Move each obsolete base to a reserved
quarantine name and fsync the parent before fd-safe recursive removal. A
restart validates the journal and protected identities before resuming; it
never treats a half-deleted directory as a healthy backup. Only one journal
exists, and selection changes cannot authorize deleting its protected bases.
The journal retains its observation time; a clock regression blocks resumption.

After base deletion completes, freshly compute the earliest **Start-LSN** over
every manifest WAL range of every remaining base. Only if all ranges use one
timeline may retention remove matching current-cluster WAL segments strictly
before the segment containing that minimum. Keep the boundary segment, other
timelines, every timeline-history object, backup-history file and unknown name.
Delete a segment and its checksum sidecar idempotently. Mixed timelines retain
all WAL until a separately reviewed cross-timeline policy exists.

This follows PostgreSQL's requirement to retain the WAL needed by retained
base backups; `pg_verifybackup` alone is not a successful restore drill.
See [PostgreSQL 16 continuous archiving](https://www.postgresql.org/docs/16/continuous-archiving.html).

## Acceptance and qualification

Local acceptance must exercise renewal/no-renewal, exact successor verification,
restore evidence identity, failed/physical-only restore, restart on both sides
of publication, real filesystem journal recovery and retention bucket/WAL
boundaries with an independent expected set. Falsifiers must kill disabled
renewal, proof, protected-base and WAL-floor guards. Run real process-lock death
tests and PostgreSQL physical tests; simulations do not establish deployed
filesystem, throughput, free-space, scheduler or notification guarantees.

NAS handoff must install the schedule, retain scheduler configuration and image
identity, demonstrate renewal before the horizon limit under measured load,
reboot/restart recovery, seven daily/four weekly policy, interrupted deletion,
successful full semantic restore and operator-visible failure. Failure or
missing evidence keeps Step 1 deployment qualification/economic certification
open. Maintenance never marks provider or historical replay gates complete.
