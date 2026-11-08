# Preserve the scheduler decision before notification coalescing

## Selected decision

The owner asked for root causes of recurring scheduler warnings, including why
earlier observations lost their cause. Leadership notifications intentionally
share one immutable episode until stable recovery. That policy must not discard
the exact evidence for a later negative scheduler observation in the same episode.

The health reader supplies an optional closed `scheduler_diagnostic` object made
only from its already sampled coherent lease/instance decision inputs. It records
the exact failed predicate, original database sample time, lease heartbeat and
expiry, instance heartbeat and state, calculated heartbeat age and lease window,
generation and fence, the bounded process holder identity, and the
presence/matching/current flags and original callback start/deadline used by the
decision. The holder is an operational process identity, not an account identity.
It contains no account identifiers, SQL, exception messages, credentials, or
arbitrary diagnostic text. It authorizes
no operation and changes no policy, deadline, retry, callback, or financial guard.

The health object uses `sentinel.scheduler-diagnostic/1` and is present for
`SCHEDULER_STALLED` or `WAITING_FOR_LEADER`. Its predicate is exactly one of
`LEASE_HOLDER_MISSING`, `LEASE_GENERATION_MISMATCH`, `LEASE_EXPIRY_MISSING`,
`LEASE_EXPIRED`, `INSTANCE_MISSING`, `INSTANCE_HOLDER_MISMATCH`,
`INSTANCE_HEARTBEAT_MISSING`, `INSTANCE_HEARTBEAT_FUTURE`, or
`INSTANCE_HEARTBEAT_STALE`. The closed model contains `sampled_at`,
`control_generation`, `fence`, `holder`, `holder_present`, `holder_matches`,
`leader_active`, `service_heartbeat_fresh`, `lease_heartbeat_at`,
`lease_expires_at`, `instance_state`, `instance_heartbeat_at`,
`heartbeat_age_seconds`, `heartbeat_window_seconds`, `callback_started_at`,
`callback_deadline_at`, `callback_current`, `scheduler_overdue`, and
`read_elapsed_seconds`. Datetimes retain their original aware values, numerical
values must be finite, and holder/state strings have bounded safe syntax. The
optional field defaults to absent for older callers and incomplete early reads.

Before notification identity lookup or leadership episode coalescing, the alert
dispatcher validates and emits that object as `sentinel.scheduler-incident/1`.
The record uses the existing bounded nonblocking pipe writer in
`sentinel.supervisor_io`: one complete JSON line within `PIPE_BUF`, with no child,
fallback logger, filesystem storage, SQL, retries, or external delivery. A full or
unavailable sink drops this best-effort record without delaying the control path.
The event's monotonic emission time is additional metadata; it never replaces the
health reader's original database observation time.

One state object owned by the dispatcher retains only the last negative
`(generation, holder_identity, fence, failed_predicate)` key. The first negative
observation, a predicate or leader identity change, or a negative observation
following a proved current fresh pulse emits one record. Repeated polls with the
same key emit nothing even as age increases. Unknown, unavailable, or incomplete
observations retain the key: absence of evidence must not simulate recovery or
rearm repeated logging.
A failed emission consumes that attempt, avoiding repeated full-pipe work. A
dispatcher restart begins with an empty key and may emit its first negative
observation again. This is a bounded process-local diagnostic deduplicator, not a
new durable health history or source of readiness.

The same validated object is attached to a genuinely new health alert occurrence.
An existing leadership episode returns its original alert unchanged. A repeated
ordinary occurrence also retains its original payload, with or without diagnostic
fields. Diagnostic arrival, changed clocks, or changed predicates must never
rewrite historical payloads, change an occurrence's identity, or create another
notification for the same episode.

## Qualification

Use private synthetic health inputs and a private PostgreSQL database. Verify
that repeated negative polls emit once, predicate changes emit before an existing
episode returns, a new negative interval emits again, and the state occupies one
key. Verify exact supplied clocks survive unchanged and a new outbox payload
contains the same closed facts. Existing payloads and idempotency keys must remain
identical. Malformed/extra fields and a real secret canary must never enter the
record. Full-pipe and non-pipe tests must demonstrate no fallback helper and no
notification behavior change. Remove the emission or new-payload attachment in
isolated falsifiers and verify the corresponding assertions fail.
