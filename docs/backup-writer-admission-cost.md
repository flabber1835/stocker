# Keep cold archive proof outside account ownership

Decision, 2026-10-30. A cold or expired runtime archive proof can read several
GiB twice. The account writer currently acquires its advisory lock before that
work. An otherwise idle shadow/retention writer can therefore hold execution
ownership while it reads backup files, causing a concurrent preparation to
refuse before either process needs account state.

An ordinary `journal.writer_lock` first proves backup authority before taking
the account lock. It still invokes the complete native guard immediately after
acquiring the lock and before yielding. The second check freshly observes media
markers, selected base, cluster identity, archiver health, required object and
sidecar metadata, aliases and the frontier; only unchanged content within the
existing process-local five-minute proof interval may reuse byte hashes. New or
changed objects still require both content passes. The preflight grants no
mutation authority, performs no commit, and a failed preflight rolls back.
The account lock remains nonblocking. Read-only recovery retains its explicit
existing exemption, and a nested ordinary lock cannot inherit that exemption.

The successful full scrub's completion time starts its reuse interval. Sampling
the clock before a long scrub incorrectly makes a newly completed proof already
expired at the next boundary. Only a successful complete double scrub may move
this timestamp; incremental frontier checks and cache hits never extend it.
Fresh metadata/alias/selection validation must finish before the proof is cached.
The interval measures time since a successful complete proof, not the age of
each individual object's last byte read. A long proof already spans reads of
different ages; completion anchoring makes that existing distinction explicit
and permits up to another 300 seconds before the next required full scrub.
This does not change the 300-second interval, byte/object ceilings, two content
passes, failure invalidation, transport gates or any caller deadline.
The interval is explicitly the age of the last completed proof, not a claim
that every individual byte was read within the last 300 seconds. A long proof
already spans its two passes before admission can succeed; this change avoids
immediately repeating that just-completed proof.

The proof key also names the operating-system process. Forked children must
perform their own full scrub even when they inherit an unchanged Python cache
and database DSN. No shared database/filesystem cache or new authority is added.

The shadow service retains canonical ownership through its actual financial
advance and the small validated health projection. It releases that ownership
before calling disposable feed retention. Retention independently reacquires
the ordinary writer/corpus locks, authenticates current restart dependencies
and enforces its existing deletion guards and timeouts. Its health hint does not
depend on retired price payloads: its authenticated inventory names current
processed-session and publication row versions, which retention does not alter.
The unchanged-session branch already verifies outside the financial writer and
uses the same post-verification best-effort retention helper. Cleanup cannot
turn a completed verified financial transition into an unsuccessful transition;
an unexpected cleanup failure rolls back that cleanup and leaves it for the
next maintenance wake. A failed financial advance never enters cleanup.

Qualification must execute the production archive guard against the strict
private-media adapter: slow scrubs followed by unchanged admission hash once
(two passes), later incremental checks do not renew expiry, a changed process
forces a full proof, and loss/corruption after preflight still refuses inside
the acquired writer. Record removed-preflight and removed-inner-guard falsifiers.
These tests establish work ordering and refusal behavior; they do not claim a
production latency measurement or eliminate genuine concurrent writers.
