# Preserve execution collector dependency causes before coalescing

Decision before implementation, November8. A current fill-collection warning
retained only `DependencyError`. The parent already received the safe original
exception class, errno and SQLSTATE in that wrapper, but replaced them with its
outer type before logging and recording the unchanged warning. Retained logs
cannot now establish the original04:17 dependency cause.

Before the existing parent failure log or failure-recording call, emit one
closed diagnostic with schema `sentinel.execution-collector-diagnostic/1`,
collection kind ACCOUNT/FILL/ISSUER, stage COLLECT_JOB, actual parent observation
time in UTC, monotonic observation time, and the existing validated
`supervisor_io.error_diagnostic` result. If recording the failure itself fails,
emit a separate FAILURE_RECORD diagnostic; it cannot replace the primary fact.
These stages identify only observed parent boundaries, not unobserved child
database/provider phases.

Use the existing immediate nonblocking pipe writer directly. A full pipe,
non-pipe destination, unavailable procfs, malformed diagnostic or logging error
returns false. No logging helper, stdout fallback, database query, wait or new
thread is admitted. Do not emit exception messages/repr/causes, SQL, URLs,
credentials, account values, provider responses or caller-supplied context.
The generated fixed-field record must remain within the existing atomic record
byte limit; kind/stage and numeric/time fields are strictly validated.

Keep at most one last successfully emitted safe cause per kind/stage (six
fixed slots). Suppress unchanged repeated failures until a positive collection
result: ACCOUNT/FILL must return literal COLLECTED; ISSUER must return its
existing explicit REFRESHED status. REFUSED, CACHED, DEFERRED, absent or unknown
results do not prove recovery. A failed nonblocking emission does not suppress
a later genuine failure observation; it creates no retry timer or pending job.
Changed causes emit immediately on the existing poll. This state is diagnostic
coalescing only and never grants healthy/financial/collection authority.

Existing outbox keys, reason strings, immutable payload/history, severity,
retry/deadline/poll policy, heartbeat and collection results remain unchanged.
Do not add the diagnostic to an existing idempotency key or replace an old
payload with a new time/cause. No schema migration, financial cursor, broker
operation or current verdict is introduced. This repairs missing future evidence;
it does not establish or repair the underlying04:17 dependency failure.

Qualification must execute the parent path with wrapped original causes,
secondary recording failure, secret canaries, full/non-pipe sinks, no helper
creation, bounded dedup/recovery and real immutable outbox reuse. An executed
removed-unwrapping falsifier must demonstrate loss of the underlying SQLSTATE.
