# Fresh worker supervision and bounded verifier recovery

Decision: 2026-11-02, before implementation. The owner requested the two source
fixes identified during the PAPER leader-incident analysis. This changes worker
supervision and display-verifier recovery, with no broker or financial authority.

## Evidence and scope

The first termination log reported a 12.725-second-old heartbeat although the
same worker's retained heartbeat was 9.739 seconds old at the log timestamp. The
exact signal and probe times were not retained, so an unnecessary termination
is possible, not proved. The second worker's heartbeat really exceeded thirteen
seconds. Independent supervisor dependency reads exceeded their one-second
budget, and the verifier exited on a three-second ownership-renewal statement
timeout. PostgreSQL memory/I/O pressure is a suspected upstream contributor;
these observations do not establish its incident-time physical cause.

## Worker termination consumes fresh evidence

Keep the existing one-second dependency-observation budget. Measure the entire
snapshot call with the monotonic clock and reject a late result even if its
observer process has already exited when the parent resumes. A future, nonfinite
or over-budget elapsed interval is not usable liveness evidence.

Only when the ordinary observation would terminate an idle worker, obtain one
more bounded observation of that same supervisor-owned worker incarnation.
Evaluate state, heartbeat and callback deadlines from the confirmation. A fresh
heartbeat or a valid callback cancels the old idle-stall decision; a confirmed
stall still terminates the complete existing worker session. Report the idle
termination after issuing termination, so logging cannot age its evidence first.
Healthy polling needs no extra database observation.

A failed or late confirmation uses the existing database-unobservable branch.
Do not clear its first-failure anchor merely because the preceding probe worked.
Repeated confirmation failures cannot reset that anchor. Preserve the original
callback invocation/deadline, startup grace, lease duration and hard deadline
while authority is unobservable. Do not add an independent idle heartbeat that
could conceal a blocked main loop.

## Verifier timeouts retain the original owner and proof clocks

Handle only PostgreSQL statement cancellation and lock-acquisition timeout in
the already-owned loop. Roll back the failed transaction and retry on the same
open, unbroken connection, which retains the sole session advisory lock. A lost
connection, ownership mismatch, integrity error or other exception follows the
existing fail-closed shutdown and normal replacement path; never reconnect inside
the retry loop or adopt another owner's jobs.

Use a twenty-second retry-admission window anchored at the first failed
iteration's start, capped by the last confirmed owner's original expiry. Sleep
at most half a second between attempts. Repeated failures and intermediate
successful renewals do not move that window. Once the whole iteration succeeds,
ordinary fifteen-second polling resumes. Each SQL operation retains its existing
three-second timeout; already-admitted observations retain their original queue,
work and reap deadlines.

Read owner expiry and database time from claim/renewal results. Map their remaining
interval conservatively onto the monotonic call-start time; reject late renewal
results and expired known ownership before admitting more work. SQL continues to
require the same owner ID and unexpired durable ownership. A retry cannot revive
expired ownership. Ownership renewal never changes any verification receipt's
observation time, expiry, subject, signature or verdict.

Do not update the verifier health file on a failed iteration, publish an old
result with a new clock, or suppress an existing negative result. Preserve
subject revalidation and commit ordering. On stop/refusal retain session
ownership until already-admitted Reader jobs finish their existing bounded work,
then release it through the existing drain path.

## Closed source acceptance and qualification

Finalize the existing complete URL-selected source contract for this exact
successor. Preserve its original e790 baseline, structural witness, economic
mappings and retained 4036/71b predecessors. Add only the independently read
installed bdb975c88c90a80c1ee7c98aed6dceeee12c8fc5 complete predecessor: 434
Python files, closure a8b6cce6e00654f402fd74735b66e0711331c44b3ea171e0241a40230b4096a4.
Its exact whole-source hash/count constrain the newer retained path set, including
its original checker. Refresh the candidate map and normalized checker/profile
pins after all source edits. Unknown, missing, extra or changed source still
refuses; actual runtime identity and authority_effect NONE remain unchanged.

Qualification covers a heartbeat advancing between observations, a genuinely
stuck worker, a completed-but-late probe, blocked confirmation through the
original hard deadline, and reporting order. Verifier tests exercise real private
PostgreSQL timeout rollback/recovery, fixed retry admission, expired/foreign
ownership, connection loss, stop/drain and unchanged receipt clocks. Execute
guard-removal falsifiers and the directly affected existing supervision,
projection and complete-source regressions in an isolated credential-free test
environment. No production fault injection, resource-limit changes, generic
monitor, broker action, backtest change or runtime patch belongs to this task.

Delivery is a protected feature PR from verified current main. This document
records intent; an opened PR does not claim the installed release contains it.
