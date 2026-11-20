# November 18 idle authority liveness

Decision, 2026-11-18, before implementation. The verified base is
`3603de84ef193e0e07f6fe6adfbde410418af204` (installed PR606). This
corrects the broker-free idle control poll. It changes no PAPER financial
authority, command, book, backup, execution window, or lease duration.

## Observed failure and boundary

On November 18 the last foreground heartbeat was 14:57:22.910 UTC and its
twelve-second lease expired at 14:57:34.910. A signed-authority-publication
check ran approximately 14:57:25.454–14:57:42.937, for 17.483 seconds, across
that expiry. PostgreSQL observations and the supervisor also timed out. A
database backend exited later at 14:58:12.363; its role and statement were not
retained. The earlier lease loss therefore has a demonstrated software path:
the synchronous full idle proof blocks the only foreground progress boundary
longer than the lease. The host had exhausted swap, but its initiating workload
and the backend exit cause remain unproved.

The existing [idle leader contract](idle-leader-resilience.md) still governs:
no independent heartbeat may keep a blocked foreground alive; a stale permit
cannot be renewed; full runtime/package/policy/publication proof remains due
at startup and before every financial callback or mutation; idle reuse is at
most thirty seconds from the original full-check start. Current control,
certificate lifecycle/revocation and rollout are checked each idle poll.

## Single-flight idle proof

The foreground starts at most one broker-free full idle authority observer in
a fresh spawned process, on its own database connection. The observer may run
across ordinary scheduler ticks. The foreground continues its actual tick,
control and alert work and renews the lease only at its existing main-loop
progress boundaries. The observer never heartbeats, acquires a leader, creates
a broker or command, or writes a control verdict or cycle. It returns bounded,
typed facts from the existing complete authority validation. A child process
cannot publish a PASS that the owner has not accepted.

The observer has one fixed wall-clock deadline measured from flight creation,
including process launch and cleanup, shorter than the ordinary thirty-second
idle-attestation age. A late result is refused even if the child completed
before the foreground noticed it. The child is cancelled and reaped on expiry;
an OS-stalled reap prevents another observer and financial callback admission.
Its
running or timed-out state never extends the old PASS timestamp, the lease,
the callback deadline or any financial grant. Only one observer exists at a
time. A timeout or temporary dependency error leaves the original checked-at
time unchanged, schedules a finite backed-off retry and makes the absence of
fresh authority diagnosable. Retry admission is bounded; there is no rapid
spawn loop or indefinite single invocation.

An idle retry has one deadline from the first failure until the foreground
admits another full observer. Subsequent heartbeat, database or lock failures
while waiting cannot move that deadline or increase the failure count. After
the deadline, a busy poll returns the ordinary future poll wake and keeps the
retry eligible. The first eligible poll that passes the current safety checks
may start an observer. Admission consumes the deadline, so a failed new
attempt can back off again. A backwards observation clock invalidates a
pending wall-clock deadline and requires fresh checks. Only a successful
fenced publication resets the failure count and refreshes the evidence.

During idle qualification, vary the phase of short exclusive maintenance
holds across repeated polls. Check the recorded PASS through contention and
recovery, including a writer held beyond the five-minute evidence lifetime.
Every pending poll still checks mutable authority. Revocation must take effect
during backoff, and a cancelled child awaiting reap must yield a future wake.

The parent-side idle control read uses its own short-budget database connection,
separate from financial callbacks and their existing SQL budgets. Connection
admission and the cumulative control/lease/lifecycle/result-publication work
share a monotonic foreground budget below the lease headroom; each SQL statement
also has a short timeout. When that budget is exhausted, the parent stops before
another stage or verdict write, retains the old evidence clock and returns a
finite retry. An expired fence still refuses at the database write itself.
Disabled and killed control still runs the existing broker-free fenced data
continuation on the scheduler's original connection and budget; the short idle
authority budget does not cap feed ingestion or shadow advancement.

At every pending poll, fresh control, holder/fence, certificate lifecycle and
revocation are still observed. Kill, takeover, expiry or changed control
cancels and discards the observer. A positively revoked/invalid certificate
continues through the existing fenced terminal block or kill path without
waiting for the full proof. A financial callback first cancels and reaps the
idle observer; its own complete fresh gate then runs under the callback's
independent hard deadline. The worker cancels its observer on stop and
handover. If it cannot reap the observer before callback admission, it refuses
that callback; it never forks a financial child alongside an unresolved idle
observer thread.

The foreground mutable certificate check uses one short SQL observation and
bounded in-memory comparison to the **exact previously authenticated signed
bytes**. It requires the active hash, raw-byte SHA-256, stored envelope/claims,
issuer/key identity, lifecycle, certificate/key revocations, and original
not-before/expiry rule to agree. Same-label row replacement or parsed-payload
tampering cannot renew PASS. It does not read a trust-root file or perform
signature verification on the foreground: those complete checks remain in the
killable full observer at the original thirty-second cadence and at every
financial callback. Current durable revocation is checked every idle poll.

Before a completed idle verdict is accepted, the foreground takes nonblocking
shared transaction locks against the authority transition and corpus writer
locks, plus a short shared lock on the rollout row. It compares the exact
certificate bytes, current rollout, and indexed publication head and receipt
identity that the full child authenticated. For a rolling publication it also
compares the indexed operational snapshot binding. It holds those locks through
the fenced verdict write. This short comparison never replays the publication
receipt chain or rolling snapshot proof on the foreground; those complete
checks stay in the child and at financial callback admission. Writer contention
or an unavailable head discards the result and schedules a finite retry.

When a full proof returns, including a refusal, the foreground requires its
original control, certificate, rollout and publication subject to remain
current under the same live lease before it writes the existing fenced verdict
or acts on the refusal. The proof must still be younger than thirty seconds
from its original start **before** a PASS can be published or its durable
checked-at time moved. Any
changed or unavailable fact discards the result and requires a fresh proof.
Only a current success may start a new idle reuse interval, dated from the
proof's original start. A genuine authority refusal persists FAIL through the
existing live fence and blocks the current cycle or latches the kill switch.
No result from an expired or replaced holder can write or suppress authority
truth. Financial callbacks never consume this nonfinancial idle reuse.

The refusal-to-terminal path must not cross an unfenced gap. If the original
fenced FAIL publication cannot commit, discard the refusal and do no terminal
mutation. A current-cycle block retains its existing fenced transition. With
no current cycle, latch kill only through one atomic store operation whose
database predicate requires the same live original holder, fence and control
generation at the kill write. The same rule applies to an immediate certificate
refusal from the cheap pending-poll facts. A takeover between FAIL and kill
must leave the replacement generation untouched.

## Diagnostics and qualification

Use closed stage names for observer launch, current-fact check, runtime source
and packages, signed authority/publication, and fenced publication. Retain
monotonic elapsed time, outcome class, budget and the observer's PostgreSQL
backend PID when available. Diagnostic sharing is lock-free so a killed child
cannot block the parent while it records a timeout. Emit bounded slow/failure records without
credentials, account data, SQL text or periodic successful log spam. Logging
failure cannot change authority, liveness or financial decisions.

Private isolated tests must show a proof lasting longer than the twelve-second
lease can finish while one unchanged foreground leader keeps making real
progress; it is accepted only with fresh facts. Falsifiers cover a blocked
foreground, expired/replaced permit, kill/revocation while proof is in flight,
late success after supersession, timeout and bounded retry, callback admission
and stop/handover cancellation, no PASS renewal on unavailable proof, and
terminal refusal under the original fence. A slow proof cannot block a due
financial callback. Run tests with no broker or production volumes and a
one-CPU, at-most-1-GiB resource cap. Final source-seal qualification and
installed-open observation remain separate release gates.
