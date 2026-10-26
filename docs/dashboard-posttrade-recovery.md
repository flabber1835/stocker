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
