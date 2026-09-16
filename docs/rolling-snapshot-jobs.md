# Durable rolling snapshot preparation jobs

The second implementation boundary for feature #384 builds on
[immutable candidate storage](rolling-snapshot-storage.md).

One preparation request freezes its 300-session axis, expected prior publication,
durable cursor, strategy identity and live-dependency digest. Concurrent wakes
coalesce into one nonterminal job for that exact request. A terminal attempt is
retained; a later observation may create a new job for the same target. Publishing
identical content remains the publisher's separate idempotency decision.

PostgreSQL owns the absolute end-to-end deadline, retry time and worker lease.
Claiming/reclaiming a job increments its fencing token. Every progress update,
checkpoint and state transition checks that token, current owner, lease and
deadline under the same row lock. An expired worker cannot finish the new
owner's job. Reclaiming a lease never extends the request deadline. Workers use
the remaining server-measured budget to cap their local monotonic network work.

States are ACQUIRING, WAIT_SOURCE, STAGING, VALIDATING, READY, RETRY_WAIT,
INTERRUPTED, REFUSED, ABORTED and PUBLISHED. Waiting releases ownership and
records an explicit resumption stage and retry time. READY requires a sealed
candidate matching the frozen request window, prior publication and dependency
digest. READY is storage preparation, not financial verification or GO. The
later publisher must recheck source/reference readiness and durable state before
atomically binding a corpus publication and marking PUBLISHED.

Verified source components are immutable checkpoints keyed by a component name
and source-generation digest. A different generation under the same component
does not overwrite or inherit completion. The worker must refuse that attempt
and prepare a new source observation. Checksums and request identities are
stored; credentials, source rows, authenticated URLs and local paths are not.
The existing source cache remains a non-authoritative optimization: a checkpoint
never proves a cache file still exists or that a source generation remains current.

Progress records rows and bytes actually completed. Heartbeats renew the lease
but do not move the last meaningful progress timestamp. Counters cannot regress
inside a stage. Stage changes reset stage-local counters and begin a new phase
clock. Reasons are bounded machine codes, not raw exception text. Operator
diagnostics remain responsible for safe details and may label a database wait
only when measured.

The job API owns no network operation, subprocess or broker capability. It does
not commit the caller's transaction. The worker owns cancellation and must stop
its children when ownership is lost. The direct publisher integration will own
backup authority and the transaction that makes the final publication visible.
Installing the job schema alone changes no GO, CLI or automation routing.

The opt-in [direct comparison publisher](rolling-snapshot-publisher.md) now
connects these jobs to Sharadar. A comparison catalog entry leaves the job READY
with `COMPARISON_ONLY`, never PUBLISHED. Such completed comparison jobs cannot
be reclaimed or expired by the generic job worker. Their idempotent receipt is
read from the separate comparison catalog, not the operational corpus ledger.
