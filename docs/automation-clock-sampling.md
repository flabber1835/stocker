# Automation clock sampling and uncertainty recovery

Decision: 2026-10-17, before implementation. This refines the sampling policy in
[readiness workflow](readiness-workflow.md#worker-clock-sampling-after-database-delays).
The owner requested triage, repair and qualification in PR #530. The verified
main base is `90a960547b58bb245c998ae3f70d0baed1fe95d0`; the pre-fix PR head is
`18a4c8b732b50eace554cd3da53e909c27baaada`.

[Qualification results](automation-clock-qualification.md) bind the completed
repair to its exact source, images, falsifiers and fresh real-provider campaign.

## Confirmed defect

The existing sampler raises a fatal `AutomationRefused` for any negative host
wall-clock interval. A simulated 1.6 ms backward correction reproduces the
reported worker failure even though the configured skew limit is five seconds.
Its wall and monotonic readings also bracket different intervals: a scheduling
pause between adjacent readings can be misclassified as a host clock jump.
The supervisor's recovery does not make either false failure acceptable.

## Measurement and classification

Keep the existing configured skew limit. Establish the dedicated database
connection before sampling. Capture, in order:

1. Monotonic `m0`, first aware UTC host time, monotonic `m1`.
2. The database's current time, monotonic `m2`.
3. Close the dedicated connection, then final aware UTC host time and monotonic
   `m3`. Connection cleanup is therefore included in timing uncertainty.

All four monotonic values must be finite and ordered. A violated monotonic
invariant remains a fatal refusal. With host interval `wall`, the actual elapsed
time between the host readings lies within `[m2-m1, m3-m0]`. The possible host
clock change is therefore `[wall-(m3-m0), wall-(m2-m1)]`.

Refuse a proven material host clock change only when that entire change
interval is strictly outside the configured positive or negative limit. Do not
infer a clock jump from a scheduling gap. A negative wall interval, a smaller
wall/monotonic inconsistency, or an outer sampling interval longer than the
limit is an uncertain sample: raise `TransientInfrastructureFailure`. No
clock-adjustment tolerance is added to the accepted financial boundary.

For a precise, consistent sample, preserve the existing conservative database
comparison. A database time beyond the whole host interval by more than the
limit proves excessive skew and remains fatal. If either host endpoint is
outside the limit but the whole interval cannot prove excessive skew, the
sample remains uncertain. Only a passing sample returns the final fresh host
time for scheduling. Explicit fixed-clock callers retain their strict existing
host/database comparison.

## Retry and diagnostics

Take one bounded sample per tick. The existing transient-failure path returns
`WAITING` before lease acquisition, scheduling mutations or financial callbacks.
The ordinary bounded polling delay provides the next fresh sample; there is no
inner retry loop, busy spin or stale-sample fallback. Repeated uncertainty keeps
the process alive and financial work fenced. A later valid sample may continue
through all ordinary authority, lease and execution-window guards.

Record refused and uncertain samples with a structured reason, configured
limit, both host timestamps, database timestamp, all monotonic readings and
derived interval bounds. Use finite JSON values only; a nonfinite monotonic
value is represented as null with its invariant-failure reason. Measurements
contain no credentials, query text, account data or financial values. Attach the
same bounded diagnostic to the exception so a fatal worker failure retains it
through the existing instance error record. Uncertain samples use the existing
nonfatal WAITING policy and structured bounded container logs; they do not create
a critical incident, acknowledge old alerts or change instance health semantics.
Successful routine samples do not generate a new periodic log stream.

## Retained source admission

Add one separate authenticated clock-sampling transition with
`authority_effect: NONE`. Its changed scope is exactly `automation/service.py`,
`runtime_admission.py` and `autonomy_runtime_upgrade.py`; its sole runtime
addition is the new clock-sampling checker. Pin exact finite predecessor and
successor bytes, the unchanged native-read checker, and both existing native
and autonomy descriptors. Existing historical descriptors and strategy identity
remain unchanged. Require the new checker to be present and exact; unknown
predecessors, adjacent edits, missing additions and profile/checker tampering
remain refusals. Keep the existing successor window intact when adding this
transition.

Qualify an actual already formed book through this transition with new
formation and provider acquisition forbidden, preserved book/journal identities
and repeated restart parity. This is compatible executable admission, not a new
book, authority grant or live activation.

## Qualification scope

Add deterministic falsifiers for millisecond forward/backward adjustments,
scheduling gaps at each wall-read edge, slow database and connection cleanup,
nonfinite/reversed monotonic samples, exact limit boundaries, genuine excessive
skew and material host jumps. Prove zero leases, cycles, financial callbacks and
broker commands during uncertainty; prove a bounded poll and later recovery.
Remove representative guards and require their tests to fail at the intended
assertions. Preserve existing expired-execution and real-drift guards.

After the source transition is frozen, build exact runtime/test images and run
the directly relevant suites and fixed native acceptance inventory. Changes to
retained admission also require a fresh isolated real-provider GO campaign,
including actual inputs, formation/parity, readiness, durable restart, full
populated restore and private-project cleanup before updating PR #530. Previous
qualification keeps its original commit/image attribution. Live-account checks
remain deferred; no installed-stack change or broker mutation is authorized by
this repair.
