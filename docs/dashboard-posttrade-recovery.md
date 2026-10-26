# Dashboard continuity and post-trade local handoff

Decision: 2026-10-26, before implementation. The owner authorized fixing the
additional dashboard defects and installing the local patch after the opening
cycle succeeded. Keep PAPER, the canonical book, source history, completed
commands/fills, controls and push history. No new trading policy or LIVE grant.

## Dashboard requests and verification

Concurrent HTML, JSON and operational-health requests join the same in-flight
panel build for the same configuration. They wait at most ten seconds; they do
not start duplicate reads or observers. Completion is shared only with overlapping
callers, with no completed-result cache. A new later request builds again. A
configuration change refuses sharing. A stalled build retains the existing
explicitly non-current HTML fallback and 503 machine response. Errors release
ownership. No additional web worker, background observer or extended deadline.

Account observations legitimately invalidate PAPER proof. In the interval before
the verifier publishes the new subject, an authenticated, still-unexpired prior
receipt may establish only a bounded CHECKING presentation, never current proof.
Require a fresh existing verifier owner heartbeat, no prior negative rows/errors,
and the prior receipt's original expiry. Decode its own authenticated subject;
then withdraw all current financial styling for the changed subject. Never
renew the expiry from a request/heartbeat, accept a forged receipt, mask a known
failure, or use an expired/missing receipt to create this wait. SHADOW stays
independent. A new negative result is immediately visible.

Next-session preview and current trading progress share the immutable sizing
authority's original, dated COMPLETE account snapshot. Validate plan fingerprint,
account, quantities and opening intents. That historical description of saved
intent does not become execution authority or a current account observation.
It can remain visible over weekends until the plan's scheduled execution,
without claiming the observation is fresh. Missing authority keeps the existing
bounded recent-observation fallback; malformed/foreign authority refuses.

## Post-trade delivery

Version the immutable delivery request with an explicit PRE_OPEN or POST_TRADE
mode. Existing request versions retain their original PRE_OPEN contract.
POST_TRADE is available only through the backed local PAPER adapter and requires
exactly one successful, completed current-generation cycle for today's exchange
session, no failure, no in-flight/uncertain commands, no other active cycle or
source job, and at least fifteen minutes before its recorded session close.
Retain the bound plan, last clean reconciliation, complete native PAPER GET-only
holdings and zero open orders. Compare old/new canonical book, original sizing,
protected projections and full state/history, including today's completed fills.
Final dashboard evidence must show that same SUCCEEDED trading run with no
unreadable/red facts and healthy notifications. Explicit pending post-close
verification is permitted amber; no false green or completed financial proof.

Preserve the existing original fifteen-minute handoff clocks, authenticated
shadow drain, one writer, current-image complete restore, shadow-first six-role
roll and unchanged archive-on PostgreSQL identity. The deferred pre-open request
is never reset/reused. A new operation obtains genuinely fresh current-state
admission. No plan/cycle is created or replayed by installation.

Preservation checks use exact PostgreSQL MVCC row versions for large immutable
checkpoint rows between full old/new canonical proofs. Hash cursor name, session,
xmin and ctid instead of repeatedly detoasting/serializing over 100 MB. INSERT,
UPDATE and DELETE change this witness; the independent full canonical proofs
still validate actual state contents. Never substitute a remembered hash for a
fresh financial proof. Qualify with real PostgreSQL update/delete falsifiers.

Tests cover concurrent actual routes, finite wait/error/configuration isolation,
receipt tampering/expiry/dead-owner/negative outcomes, weekend original intent,
settled/current-session admission and refusal, completed fill/history preservation,
and source identity. Retain private physical/semantic restore and actual old/new
canonical/runtime evidence before local application handoff; update existing PR
540 without waiting for CI or merging it, as the owner authorized.

The broad private composition uses synthetic market time with real PostgreSQL
lease/mutation clocks. Its generated, initially empty account binding must
predate its synthetic first observation, including when CI runs after the open.
Seed that historical binding and notification-activation date before installing
evidence projections. The fill-notification lower bound uses the same simulated
business timeline; its future-boundary refusals remain active. Never
change a production binding, lease clock, observation or admission guard. The
next-open HTTP reader still excludes a plan when its execution time has already
passed on the actual database clock. These tests prove callback composition,
not actual exchange opening latency.

After the simulated basket is terminal and its push receipts are delivered,
the HTTP observation phase follows an advancing wall clock, retaining a positive
offset only when the simulated business session is still in the future. It
never rewinds business time or changes PostgreSQL clocks. Refresh the native
GET-only account snapshot in that phase before producing receipts. Receipt
authentication, future-fact refusal and source-freshness checks remain active.
This avoids certifying real database timestamps with a frozen earlier envelope.

The clock sampler owns only a successfully allocated connection. Use a closing
scope around that connection so both normal sampling and query failures close
it, while allocation failures have nothing to close. Preserve availability
classification and refuse invalid connection factories; no clock sample or
scheduling progress can be created from a missing connection. This removes a
structurally unreachable normal-return cleanup branch rather than excluding it
from the automation branch-coverage requirement.

## Closing-data preparation display

The exchange close makes today's source frontier due, but acquisition and
publication start after that close. The feed display must cover the interval
before a new ingest record exists and between bounded source retries. Reuse the
existing authenticated SOURCE_FRONTIER wait and its historical canonical book,
with a current healthy shadow publisher. Require exactly the next closed session
after that book/frontier, its actual scheduled close, and the original next-open
deadline. A request or heartbeat cannot extend that deadline. Match the separately
read feed frontier to that authenticated historical session and require a still
valid, affirmative data-contract verdict. Only that single-session lag may read
amber, explicitly "waiting for closing data"; it never becomes current data or GO.

Missing/expired/foreign historical evidence, a stopped/stale/unreadable publisher,
multiple missing sessions, future clocks/frontiers, failed or expired contract
checks and explicit ingest failures retain their ordinary failure classification.
Other red rows and source errors remain visible. HTML, JSON and operational
health share the same projection, with the original earliest evidence expiry.
No provider request, data write, execution authority or scheduler change is added.

Subsequent backed local patches may consume the preceding operation's completed
VERIFIED receipt. Validate its original digest-linked journal, exact build and
qualification subjects, unchanged retained predecessor-receipt hash and a bounded,
acyclic chain back to the original completed dual activation. The current runtime
must match the latest verified candidate; the original control/certificate anchor
and the preserved archive-on PostgreSQL identity must still match. Hold the
canonical authority locks and retained source GO locks. An incomplete, altered,
foreign or cyclic predecessor grants no installation permission. This does not
reopen old operations or bypass current-source, restore, idle handoff or readiness
gates. Wait for acquisition and publication to reach their supported idle state.
Dockerfile FROM uses the retained signed reference or existing local source-layer
tag, whose exact image ID and foundation are checked before and after building.
A bare local image ID is not treated as a Docker registry reference.

Long atomic candidate writes renew their job lease inside the publishing
transaction. Other readers see the last committed heartbeat, so that timestamp
alone cannot classify the writer as stalled. After the observer's existing
bounded corpus-pin retries exhaust, only the actual CorpusLockUnavailable type
may produce a publication-wait result. Require the current operational job's
validated request/hash and closed-session target, original immutable deadline,
registered owner, and a live transaction updating that exact job tuple while
holding the corpus writer lock. Match pg_stat_activity.backend_xid to the visible
tuple's xmax, plus the granted exclusive advisory lock; an arbitrary live backend
or an expired committed lease alone is insufficient. No lease is revived.

This signed display result contains no portfolio values, holdings, completed
financial verification or GO. It names publication in progress until the earlier
of the original job deadline and actual next-session open. Recheck the normal
subject before/after observation. Missing/foreign/dead writer evidence, negative
job states, wrong targets and other exceptions retain the original refusal.
The independent fresh publisher row remains required. During that proven state,
only raw WARN ingest/building rows may reuse its fixed deadline. A still-positive
but aged authority verdict may become "recheck pending after data" only during a
healthy bounded automatic refresh; it loses PASS styling. Lifecycle failures,
negative/unknown verdicts, stopped workers and other red rows remain red.

## Long normalized work and the observed publisher halt

The October 26 publisher refused at the owned job boundary after an extended
atomic normalized-block write. Normalized bar iteration already checkpoints its
owner; benchmark-block iteration must also checkpoint before and after each
stored session. Reuse rolling_work's caller-supplied heartbeat in the same
transaction. Never commit partial candidate work, revive an expired lease,
increase its 600-second maximum or extend the immutable job deadline.

Distinguish an otherwise live, same-owner/same-fence ACTIVE job whose lease alone
expired as JobLeaseExpired, a typed JobWaiting refusal. Roll back and allow the
normal new fenced claim; no work continues on the expired permit. The supervisor
already retries JobWaiting. Missing/terminal jobs, changed owners/fences and
other integrity refusals remain terminal; JobDeadlineExceeded keeps its separate
existing behavior. Prove slow benchmark iteration, exact deadline exhaustion,
expired individual work and fence loss on real private PostgreSQL, plus a
falsifier removing the checkpoints. Do not clear the current critical incident
until its underlying cause is repaired and the operator recovery contract passes.

For an inspected critical publisher incident that prevents ordinary healthy
application handoff, the operator may use the existing broker-free `shadow-run
--once` entry with the exactly qualified, physically and semantically restored
candidate image. Stop the latched shadow service first and hold its persistent
publisher owner lock for the complete foreground invocation. Retain both
incident markers throughout this repair. Use the unchanged operational account,
source configuration and original durable job deadlines; no execution entry or
authority/control mutation is part of this operation. Record the exact image,
outcome and original incident bytes. Only after current source and canonical
shadow verification succeeds may the operator archive both markers under the
existing incident-clearance rule and restart the service. Ordinary healthy
PRE_OPEN handoff requirements still apply to installing the full application.
