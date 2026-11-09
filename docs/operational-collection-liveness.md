# Actual collection progress is process liveness

Decision, 2026-11-08, before implementation. The completed c2569 installation
refused its initial application start because the verifier was temporarily
unhealthy. Its operational collector had entered a bounded job which timed out;
the services later became healthy with no restart. The current operational
heartbeat is written only after PUBLISHED, so a responsive supervised collector
cannot report liveness until a complete publication succeeds. The earlier cheap
verifier entrypoint removed cold imports but deliberately deferred this producer
protocol correction (`cheap-verifier-health.md`).

Write the existing operational heartbeat once when `collect_result` actually
executes in its admitted child. Place the write inside that function's existing
started/deadline/try context, before collection. The normal Collector has already
constructed its process-owned Observer, and the reusable worker has established
parent-death supervision, received and validated this call's command, and entered
the function. Process creation, queued input, a parent retry or a failed
admission is not this progress. Keep the existing parent post-PUBLISHED pulse.
There is no new parent callback, pipe frame, thread, process or heartbeat path.

This timestamp means process execution, never successful publication, financial
verification, readiness or authority. An actual admitted job may return FAILED
or SUPERSEDED while process health remains current. The signed operational
failure or unchanged original snapshot expiry continues to show its real
negative/unavailable state. Preserve the failure latch and every review/event
transition; an entry pulse cannot acknowledge or clear a failure. This decision
supersedes only the success-heartbeat interpretation in the superseded-work
paragraph of `operational-state-contract.md`: supersession still creates no
successful publication/review evidence and never renews the previous receipt.

The original 20-second parent-owned call budget includes this child filesystem
write. A blocked write is killed with that same job, rather than blocking a
parent admission callback. A write failure is handled as a negative collection
failure and must never proceed into positive composition. Failed process start,
prior unreaped-child admission refusal, or Observer construction failure occurs
before function entry and produces no pulse. A previously admitted job may leave
one old pulse after timeout; it expires under the original health bound. An
unreaped child blocks its successor and cannot generate new admission pulses.

The verifier's independent main heartbeat still requires actual owned loop
progress. Both existing timestamps must remain parseable, nonfuture and at most
45 seconds old. A child cannot keep a blocked/dead verifier owner healthy. Keep
the same health predicate, Compose grace/timeout/retry policy, owner and worker
deadlines, result schema/2 KiB limit, source/subject/context checks, publication
atomicity and original financial/operational clocks. A process-health pass alone
never establishes a green dashboard or permits a broker action.

Focused qualification must use the actual spawned Worker and Collector to show
the entry pulse exists before blocked collection completes. Include an executed
removed-pulse falsifier, failed serialization/start, a real live predecessor in
the unreaped admission set, Observer construction refusal, bounded blocked/write
failure, and an expired old pulse after a killed job. Keep the actual signed
negative financial receipt and original snapshot bytes/clocks unchanged while
only liveness advances. Retain the existing failure-latch, worker protocol,
parent-death and exact 45-second negative health regressions. No broad suite,
production fault injection or financial golden change is required.
