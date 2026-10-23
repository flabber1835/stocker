# Bounded rolling-writer scheduling

Decision: 2026-10-23, before implementation. Recurring finite dashboard readers
held the shared corpus pin across repeated immediate publisher try-locks. Today
the source job completed only after a temporary panel pause. A live reader was
making progress, so resetting WSL, cancelling readers or weakening publication
verification would not address the scheduling problem.

## One lock and an explicit place in its queue

The three owned rolling-writer phases (freeze, candidate build and publication)
first request a bounded queued EXCLUSIVE session advisory lock on the existing
corpus key. The existing writer context then acquires that same lock reentrantly
and retains all original mutation guards, ownership checks and atomic commit
behavior. Each acquisition has exactly one matching release. Other writers
keep their nonblocking contract. Readers keep their current shared try-locks,
snapshot provenance, verification deadlines, freshness and failure semantics.

PostgreSQL's existing lock queue prevents independent fresh readers overtaking
a waiting exclusive writer. Existing readers, including their nested pins, may
finish normally; the writer never moves the data underneath them. No new lock
key, durable waiting flag, schema migration, process scheduler or second book
is introduced. Corpus acquisition remains before the journal writer lock.

## Finite authority and cleanup

The maximum drain interval is 330 seconds, covering the existing 300-second
financial observer and its finite shutdown. Clip it to the currently owned
source job's server-clock deadline and lease, the already supplied shadow child
deadline, and any active acquisition-work budget. Read/commit ownership before
waiting so neither a job row lock nor a transaction read pin is retained across
the queue. Do not renew a lease during waiting or extend any absolute deadline.
Recheck current fenced ownership and remaining time after acquisition and before
entering the original mutation context. Stale ownership permits no mutation.

Use a scoped PostgreSQL lock timeout, never wider than an existing nonzero lock
timeout. Leave statement timeouts unchanged. Restore the prior lock timeout
before mutation and on known timeout. A confirmed lock timeout remains typed
`CorpusLockUnavailable`; integrity/configuration errors retain their type.
Cancellation, lost acquisition responses, failed commits or failed unlocks can
leave session ownership uncertain: dispose of that connection and preserve the
original exception. Never unlock all advisory locks or guess an unknown result.
The enclosing publisher skips database failure/cleanup calls on a disposed
connection so bookkeeping cannot mask the primary error; the durable owner lease
then follows its existing expiry/reclaim path. Healthy reusable connections keep
the original failure recording and scratch cleanup.

## Identity, qualification and delivery

Scheduling changes when a mutation can begin, not its economic computation.
Add a separate closed source-pair contribution for the exact reviewed publisher
successor, retaining the installed publisher's economic identity and its existing
diagnostic source contribution. Qualification removes only the exact scheduling
wrappers/import and disposed-connection bookkeeping guards, and compares the
complete remaining module with the independently verified installed baseline.
Keep the earlier diagnostic source pair and baseline fixtures immutable. Unknown
neighboring bytes and any economic edit contribute their actual source identity
and fail standing strategy authority. The full executable identity always covers
the actual scheduler, publisher and source-mapping code.

Use isolated real PostgreSQL tests to establish an actual queued writer under
continuous independent reader attempts, stable old-reader data, exclusion during
mutation, serial writers, nested lock balance, cancellation/response-loss cleanup,
timeout restoration and unchanged lease/deadline refusal. Remove the queued guard
to falsify writer priority. Exercise the actual rolling coordinator's three
scopes and retain its exception ordering and mutation boundaries. No production
fault injection, broker order or test push is part of qualification.

Local PAPER delivery remains owner-authorized. Preserve publication 6, the saved
October 23 decision / October 26 WAITING_OPEN plan, control generation 46,
canonical book, journal, holdings, order policy, subscriptions and alert history.
Use one fresh old/new canonical comparison and bounded row hashes around the
normal four-application handoff, shadow first; PostgreSQL remains running.
Backups, archives and restore work remain disabled. The backtest is untouched.
