# Preserve execution collector dependency causes before coalescing

## November 18 account publication contention

The opening collector's account INSERT timed out updating the shared PAPER
revision at 14:33:28 UTC. The trace establishes the blocked statement. It does
not identify the transaction holding that row. The account result had already
passed the native identity checks. Its successor was collected about a minute
later. The original per-exception outbox key also reused an older incident.

Keep the account evidence and its operational invalidation atomic. A periodic
sample keeps the database time acquired at the completed native read. If its
INSERT encounters a PostgreSQL lock timeout, roll back the failed transaction
and try publication in a fresh transaction within one bounded publication
interval. Recheck the binding, any proved working orders, and the original
opening observation. An expired or changed context cannot acquire a positive
proof through a retry. Never retry a commit with an uncertain outcome. A
newer account observation retains its later timestamp. Current operators must
still see adverse account states, and every material change keeps the existing
strict PAPER revision trigger and rollback semantics.

Give each account collection incident a durable occurrence in independent
operational metadata. Its first failure enqueues one warning. Repeated matching
failures update its count and last-seen time. A later successful periodic
observation closes earlier open occurrences in a separate transaction after
the sample commits. A diagnostic failure is reported independently and cannot
roll back or redate the sample. A concurrent, newer account observation supersedes a delayed
sample before the latter can commit. This preserves sequence and time ordering
for existing readers. No source flag is added to the account economics.
Use a separate collector-owned `COLLECTOR:ACCOUNT:<context>` row in the existing
backed operational receipts table. It has its own HMAC purpose and schema,
`sentinel.account-collection-incidents/1`. The context binds the physical
database and account/deployment/takeover identity. Keep sixteen recent episodes,
with the original warning retained in the outbox for older occurrences. No
financial reader selects this scope. Read the `episodes` array for first and
last observation, recurrence count, lock timeout count, and last recovery time.
Record the observed SQLSTATE and distinguish the account
revision trigger when PostgreSQL supplies its name. A timeout by itself cannot
identify the transaction holding the lock.

After the first evidenced lock timeout, a single independent read-only
PostgreSQL probe may sample the same backend during its retry. Use
`pg_blocking_pids` to identify actual concurrent blockers and constrain the
waiter to the same database, login, original backend lifetime and known account
publication statement. Record the observed blocker count, its server state and
the recognized last statement only for a single blocker. The last statement
cannot establish which earlier operation originally acquired the lock.
Multiple, unrecognized or inaccessible stages remain unattributed. The query
returns finite stage labels. No SQL, backend IDs, identities or arguments
leave PostgreSQL. A probe that loses the race or fails cannot delay publication
or change a retry, recovery or trading decision. Recovery bookkeeping runs
only after a committed observation and has a short independent lock timeout.

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
