# Backup maintenance continuity and initiating failures

Decision 2026-11-10 before implementation, owner-authorized local PAPER patch.
Verified main is 1e7f4b181fbcb998b3086833ab813c21b1c2ca8e; installed application
and maintenance are 9484f7ec9612148f0496320db01a838696979719. Preserve their
immutable sources, the canonical book, stored plan and command journal.

## Admit the existing maintenance state before the clock transition

The November 10 daily backup published BASE_BACKUP progress at 09:06:33 UTC.
The last ordinary chain expired at 09:11:29.788358. A projection formed before
that boundary ignored the known progress and emitted an OK row with no recovery.
That same row became FAILED at 09:11:31.201430; the next collection recognized
the unchanged progress at 09:11:45.572126. The completed new base was proved at
09:17:10.936811 and its runtime chain at 09:17:16.359731.

Emit the already-existing typed BACKUP CHECK IN PROGRESS / WARN row when a
valid active BASE_BACKUP predecessor attempt is known, while the old chain is
still current as well as during its cadence-only lag. Require every existing
physical-system, exact predecessor/base lineage, start/observation, immutable
attempt deadline, base-age and semantic-drill guard. No hard failure can be
excused. Keep successor verification and FAILED/COMPLETE handling unchanged.
This represents a known operating phase immediately; it does not turn an
expired integrity proof into a positive proof or change financial admission.
The existing exact typed scheduled-maintenance classification remains the only
reason that this WARN phase can be normal on the headline. Independent failures
still prevent green and remain reviewable.

Replay one pre-expiry row through its original chain boundary without rebuilding
it. Compare fresh and retained projections and their exact incident conditions.
Fail at the original attempt/base/drill boundary, on invalid lineage, failed or
completed progress without a fresh independent chain, and on hard proof errors.
Execute a falsifier which restores the old expired-only admission condition.

## Preserve failures before cleanup and retain finite timing facts

The bounded freshness child spent 243 seconds in the proof path with negligible
owner wait. Its exception chain ends in TimeoutError but transaction cleanup
could replace the initiating error before the current diagnostic captures it.
The exact slow SQL/I/O subphase was not recorded and remains unproved. Do not
guess contention, media corruption or a database outage from that chain.

Retain a worker-owned deadline interrupt at the actual alarm handler before
raising it, and preserve the first initiating failure before transaction cleanup
can replace it. Keep initiating and cleanup outcomes separate. Never infer a
retryable failure from a generic nested TimeoutError; original deadlines,
classified retry eligibility and cleanup requirements remain unchanged. Retain
safe finite alarm-budget/fired and absolute start/failure facts at their owner,
using a closed versioned diagnostic protocol if fields change. No raw SQL, DSN,
credentials or arbitrary exception prose is exported. Add failure-during-cleanup
falsifiers and preserve old positive proof wire semantics.

Maintenance pass/refresh diagnostics must retain their actual observation times:
the supervisor currently buffers child output until the complete bulk pass ends.
Add owner-produced absolute timing facts rather than treating flush time as the
failure time. Keep one coordinator, finite output/process bounds and existing
writer safety. Failure while publishing FAILED progress must preserve the outer
initiating exception rather than lose it through Python exception-name clearing.

## Delivery and limits

Use the existing qualified backed local application installer and signed reader
handover, with same-commit qualification for the new maintenance reader. Preserve
the original 300-second byte-proof clock, 600-second chain lifetime, one-hour
maximum maintenance attempt, retention policy, independent genuine restore
qualification and pre-open fifteen-minute execution margin. Never interrupt an
active backup/deletion, fabricate a proof or bypass admission to meet the clock.
Validate targeted contracts, preserve all retained source histories and all116
economic contributors byte-for-byte from the installed release, then verify
current dashboard/account/plan and normal renewal after installation. Historical
failure records remain; acknowledgement uses only the supported exact-view API
after all active conditions have resolved. LIVE remains forbidden; UNKNOWN stays
explicit; long-only/unlevered and backtest protections are unchanged.

## Selected worker failure wire

Emit `sentinel.maintenance-integrity-failure/2` for new failures; the successful
proof remains `sentinel.maintenance-integrity/1`. Version two adds required
`timing` facts (nullable armed alarm budget, actual alarm-fired flag, UTC start
and first-failure clocks) and a separate bounded `cleanup_exception_chain` using
the existing closed class/SQLSTATE/errno vocabulary. Capture the worker's own
deadline exception in the alarm handler before raising, and never overwrite the
first retained cause during transaction or lock cleanup. Capture ordinary
failures inside the outer transaction boundary as well. A nested TimeoutError
does not establish that the worker alarm fired. Deadline and failed cleanup
remain hard refusals. Historical version-one records retain their exact closed
parser contract and are not upgraded with invented timing facts.

## Pass timing wire

Select `sentinel.maintenance-pass-result/2` for PASS and REFRESH records. Add
required UTC `started_at` and `finished_at` fields at the producing invocation.
Forward the record unchanged through buffered transport; journal emission time
is not its observation time. Synthetic supervisor refusals retain the bounded
child invocation's own start and finish. These fields are diagnostic only:
publication time remains the only renewal anchor and no deadline is reset.
