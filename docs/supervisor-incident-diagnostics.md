# Attributable supervisor and observation failures

Decision before implementation, 8 November 2026. The owner approved the
recommended diagnostic-only local patch and set the objective of establishing
the causes of shadow restart, leadership interruption, maintenance starvation,
diagnostic loss, expensive health checks and overlapping reads. This diagnostic
change addresses the independently reproduced loss of causal information; it
does not assert that the historical operational trigger has been established.
The local PAPER qualification and delivery contract remains mandatory. The
owner's local-first sequence precedes any PR delivery after demonstrated stability.

## Preserve the initiating failure without disclosing private values

The dependency child currently flattens its exception to text and the parent
rethrows RuntimeError. Supervisor callers then retain only RuntimeError, even
when logging succeeds. Return a bounded closed diagnostic envelope containing
exception class, integer errno when present and five-character SQLSTATE when
present. The parent's typed error remains a RuntimeError subclass, preserving
existing catch/control behavior. Do not put exception arguments, SQL, DSNs,
environment values, arbitrary object reprs or messages in structured events.
Timeouts keep their original type, deadline and cleanup behavior.

## Reporting uses the existing sink without another child deadline

On Linux pipe-backed stderr, reopen the already owned descriptor through procfs
with independent O_NONBLOCK and O_CLOEXEC flags. Emit one bounded compact JSON
line within PIPE_BUF using one atomic write. Do not mutate flags on the inherited
descriptor, allocate a logging child, wait for a full pipe or retry the write.
Full/unavailable sinks return a negative delivery result; no record is described
as durably delivered solely because emission was attempted. Non-pipe/unavailable
procfs cases retain a finite isolated fallback rather than unbounded stream I/O.
This fixes the reproduced secondary logging-deadline loss mechanism while
preserving honest loss on a genuinely unavailable sink.

All new structured supervisor records select immediate emission: if the nonblocking pipe path
is unavailable, return False without entering even the finite fallback. A
diagnostic sink must not add a helper/reap delay between a kill decision and its
signal or age an already confirmed heartbeat decision. In particular, the
child's durable-arm record must not add another helper deadline between marker
sync and IPC acknowledgement. Existing plain-text reporting retains its finite
fallback only for its pre-existing non-pipe use cases.

## Record decisions where their original facts are owned

Shadow admission emits bounded stage records for arming begin/acceptance/failure,
active-proof failure, worker-spawn failure, acknowledgement failure and outer
ownership failure. Include only component, incarnation, process identity,
monotonic elapsed duration, exact already-known attempt identity and the closed
error envelope. Failure reporting must not read another file or change admission,
pending markers, worker outcomes, retry policy, restart behavior or hard bounds.

Snapshot-store instrumentation was rejected by private economic-manifest
qualification. Its entire module is a frozen economic dependency. Retain its
exact installed bytes and economic baseline. Full-read cost/overlap attribution
uses private causal reproductions and external database observations; any future
identity diagnostics must live at a separately qualified operational caller seam.

Automation records snapshot versus confirmation failures and, before termination,
the already confirmed heartbeat age/state, owned child PID, monotonic observation
begin/end and decision time. Reuse the actual decision facts; perform no extra
database probe or freshness renewal. Preserve the second confirmation, callback
deadline, group termination and replacement policy exactly.

## Notifications retain typed cause independently of policy

Attach a bounded optional typed observation diagnostic to newly created health
and alert metadata. Unreadable observations continue to receive the current
conservative policy. Preserve severity, existing incident identity, financial
guards and original immutable historical payloads. Expose closed type/stage and
safe codes only; arbitrary health.reason text must not become a notification
payload. This separates attribution from authority and does not rehabilitate
invalid evidence or retry an unknown mutation.

## Required qualification

Private tests must exercise the real subprocess exception envelope, early stage
failures, exact pre-termination fact capture and unchanged decision outcomes.
On a real Linux pipe, assert that logging creates no helper, leaves inherited
flags unchanged and returns promptly on a full/broken sink. Test malformed IPC
diagnostics and unsafe exception strings, including a synthetic secret canary.
Remove or break the relevant guards and demonstrate the behavioral assertions
fail. No production fault injection, broker operations, liveness cache or wider
deadline is part of this change. Existing signed evidence and source-identity
compatibility require ordinary exact candidate qualification before installation.

For the source-only diagnostic layer, retain the complete independently archived
installed 8fafcfae9c46f471a834d7bd221497d6d940732a Python source map as a new
explicit predecessor. Preserve every earlier map, the structural/economic
baseline and existing source unknown/missing/extra rejection. Seal only the exact
diagnostic successor; the source edge has authority_effect=NONE and supplies no
financial or LIVE permission. No economic golden fixture or canonical result is
re-pinned for an operational diagnostic change.
