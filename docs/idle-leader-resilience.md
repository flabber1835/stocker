# Idle leadership, bounded observation and incident recovery

Decision: 2026-10-17, before implementation, following the owner's approval of
the read-only incident triage. Base: `c0be72ed708b20cc8fff25b0cd8e1796889377f0`.

[Qualification evidence](idle-leader-qualification.md) records exercised failure
boundaries, exact commands, resource limits and the release claim's scope.

## Incident and limits of the evidence

The installed PR530 worker emitted six leadership-loss and three stalled-worker
alerts between 23:06 and 00:04 UTC. One automation child was replaced and the
shadow container restarted once. PostgreSQL statement timeouts, supervisor
observation timeouts, CPU throttling and a WSL kernel allocation failure with
only 11 MiB swap free corroborate resource pressure. They do not identify the
workload that originally produced that pressure or the exact shadow exit path.
The two uncertain clock samples occurred outside the alert transitions; they
are not evidence that the PR530 clock repair initiated this incident.

Idle scheduling nevertheless repeats cycle-lineage scans, executable/package
hashes and signed authority validation while a twelve-second lease is running.
The main loop publishes its heartbeat only after those checks. The operational
alert cursor treats changed leadership symptoms as separate incidents.

## Main-loop progress and fencing

Keep the configured lease and all financial callback deadlines. Do not install
a free-running idle heartbeat that could keep a blocked main worker alive.
Publish the new instance before its first lease acquisition, then renew an
already owned, unexpired permit at explicit main-loop progress boundaries:
before a tick, before the idle control check and after it completes. Record
instance progress at these boundaries. Renewal must continue to require the
same holder, fence and enabled control generation; kill, takeover and expiry
remain refusals. A stale permit is discarded, never resurrected by liveness.

A completed uncertain clock sample can preserve an existing valid owner's
liveness at such a boundary. It still cannot acquire new leadership or enter
financial work. A blocked boundary receives no independent renewal and must
still expire and be detected. Eliminate identical lineage validation repeated
within one unchanged tick, without carrying a lineage proof across ticks or
mutations. Existing execution-time revalidation remains mandatory.

## Bound repeated idle attestation

Runtime source and installed packages are not currently OS-enforced immutable.
Do not memoize their identity as if they were. Full source, package, policy,
certificate and publication validation remains mandatory at startup, before
financial callbacks and at every execution authorization boundary.

The nonfinancial idle display attestation may run at a maximum thirty-second
interval for the same control, certificate and live ownership identity. Its
original checked-at time is retained between checks; a skipped check cannot
publish another PASS or grant any financial permission. Continue polling current
enabled/kill/generation and certificate lifecycle/revocation at the ordinary
control cadence. Changed control/ownership/certificate, expired or revoked
authority, a failed observation, or clock rollback requires immediate full
validation or the existing refusal. Unsuccessful checks cannot earn the next
reuse interval. Fenced data continuation keeps its existing independent wake.

Avoid duplicate writes of the same successful authority observation within one
idle validation. Record bounded slow-stage diagnostics without credentials,
financial data or periodic successful log spam. These diagnostics identify
source/authority work versus dependency latency on a future recurrence.

## One leadership incident across recovery

Only `WAITING_FOR_LEADER` and `SCHEDULER_STALLED` share a durable leadership
episode. Preserve its first immutable alert and reason; changing between those
symptoms must not enqueue another critical push. Do not acknowledge or delete
existing alerts, weaken current health, or group authority/integrity/execution
failures into this episode. A changed control generation or unresolved broker
outcome identity remains independently actionable.

Rearm a leadership episode only after sixty seconds of continuously observed
operational readiness: an active lease, fresh current-holder heartbeat and the
same holder/fence. Recovery observations must have nondecreasing database time;
a gap exceeding `max(10 seconds, twice the dispatcher poll interval)`, an unknown
observation, a failed state or owner/fence change resets that recovery interval.
Recovery sends no push. Retained unacknowledged critical history still renders
red and remains available for explicit operator acknowledgement. Existing cursor
and outbox records must remain readable across deployment without a new schema.

## Qualification and release boundary

Add one exact retained-executable successor profile with `authority_effect:
NONE` for the scheduler, idle adapter, alert observer and admission/checker
wiring changed here. Preserve all historical descriptors and predecessor hashes.
The previous clock-sampling checker may accept only the independently pinned
new checker and admission bytes; unknown predecessors, adjacent edits, missing
checkers and profile tampering remain refusals. This is executable compatibility
for the existing book, never permission to change its economics or certification.

The formed-book successor scenario belongs to the existing canonical retained
upgrade integration test in `test_operational_liveness_upgrade.py`. Extend that
test's predecessor parameter with the authenticated main manifest. Its declared
fixture controls runtime attestation and physical-backup policy to isolate
book/admission/restart behavior; it is not a production GO or backup proof.
The new source-pin test module keeps real default guards and adds no legacy
fixture exemptions. Reuse this established test owner instead of duplicating
its synthetic book fixture or running unrelated physical restore qualification.

Use isolated Python 3.12/PostgreSQL fixtures without production credentials or
broker orders. Exercise an established leader across repeated clock uncertainty,
sequential slow idle stages, a genuinely blocked main loop, expired/replaced
ownership, kill and revocation, startup observation, immutable source drift at
the next full check, and the opening execution boundary. Prove bounded check
counts and unchanged callback/command identities. Test alert transitions,
dispatcher restart, long observation gaps, rollback and sixty-second recovery.
Break representative new guards and require the corresponding falsifiers to
fail. Retain current red and separate safety failures through the composition.
Include the new scheduler regression module in the mandatory automation CI
lane so its main-progress branches participate in the existing 100% branch
coverage gate. Preserve complete, nonoverlapping test ownership.

Measure the isolated workload within explicit CPU/memory ceilings; never stress
the installed stack. Record measured scope and limitations rather than claiming
that passing unit tests proves laptop resource availability. Deliver through a
reviewable PR with exact commands/results. Installation, signed certification,
existing-book compatibility and production observation remain separate release
gates; this change does not reset a book or alter backup, broker, price-domain,
execution-window, long-only or unlevered policies.
