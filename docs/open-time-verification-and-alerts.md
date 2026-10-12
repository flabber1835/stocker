# Market-open verification ownership and availability reporting

Decision: 2026-10-12. The installed PR510 release entered its Monday execution
callback on time, but still had zero broker commands when the fifteen-minute
callback boundary forced read-only reconciliation. Its gateway restores the
same authenticated rolling book before entering execution and again on broker
guards. The guarded structural scope starts after the gateway's initial proof,
and its inventory also binds broker-only cursors written by reconciliation.
Those choices repeat expensive immutable-book work inside a short execution
window. They are implementation/ownership defects; no execution clock, exposure
limit, order identity or UNKNOWN rule should be relaxed to compensate.

The shadow supervisor also maps every availability exit to source recovery.
A typed local corpus lock, database or backup deferral can therefore produce
SHADOW_SOURCE_DEADLINE_MISSED after the following open even when the current
decision book was already attested. Its recorded source-deadline claim is false.
Finally, the dashboard withdraws old broker facts when execution starts but
does not project the live callback's original finite refresh boundary.

## One immutable proof scope per execution gateway

Establish the existing structural-verification scope after acquiring the real
execution writer and publication pin, before the gateway's first retained-book
check. Its broker wrapper reuses that same owner scope. Full canonical proof
still runs on first use. Every broker operation retains fresh signed authority,
grant/cycle/plan, account/takeover, revocation, publication, time, cash and quantity
guards before and after reads and before mutation. No dashboard cache or durable
display verdict can authorize execution.

The automation adapter checks the exact durable plan id/fingerprint before
constructing its broker, but does not repeat the full plan/shadow bridge there.
That bridge belongs to the canonical execution gateway and still completes
under its real publication pin before the first broker interaction. Broker
construction grants no permission or network access.

The rolling-checkpoint slot depends on economic/retained source rows, not on
canonical broker/trial cursors sharing their table. Share an explicit namespace
classifier with the read-only dashboard; only its exact registered broker/trial
prefixes and exact incarnation anchor are excluded for this one structural slot.
Unknown namespaces, economic inputs, runtime admissions, authority/segment rows
and dual sizing records remain invalidating. Other structural slots retain their
complete inventory. Table identity/rewrite and transaction epoch fences remain.
Any ownership/pin loss or changed input during verification refuses. Retained
private results are detached for each caller, stay within one live callback,
and grant no independent freshness or transport permission.

## Typed availability outcomes

Add a distinct worker exit for local/database/backup dependency availability.
These outcomes retain bounded supervised retry and report a coalesced dependency
warning. They cannot claim a provider/source decision missed the next open.
Actual source coverage/provider waits retain their source recovery and deadline
escalation. Integrity/configuration errors still latch; unknown/unacknowledged
outcomes stay fenced. Preserve exception causes and use typed classification,
never an error-message substring to declare a healthy source.

## Broker observation presentation during a live callback

Project an active broker refresh only from the durable service invocation,
matching current cycle state, current control/lease generation and fencing
token, live lease and fresh service heartbeat. Its deadline is the persisted
callback deadline sampled before work, never the panel clock or market close.
Expired account/position observations remain explicitly stale and unverified;
while that exact invocation is bounded and alive they may render amber with
the original last-observed time and deadline. They never become current green.
An expired, mismatched, missing or withdrawn invocation loses this allowance.
Known failed/unreadable account or broker evidence remains red through retries.

## Interrupted transport is not completed transport

The installed dashboard marks order transport COMPLETE merely because an
EXECUTING cycle advanced into read-only RECONCILING. Monday's durable transition
explicitly records CallbackDeadlineExceeded and
EXECUTE_TIMEOUT_REQUIRES_RECOVERY; clean recovery then superseded the cycle with
zero commands. Advancing past this gate proves neither submission nor completion.
When the latest EXECUTING-to-RECONCILING transition records a failure, display
transport as interrupted and unverified through recovery or terminal failure.
Do not infer an empty journal, failed broker outcome or successful submission
from that transition. A subsequent successful transport transition or a clean
SUCCEEDED cycle may complete the gate. This is read-only presentation of existing
events; it changes no execution, recovery or alert policy.

## Qualification and release

Reproduce repeated retained verification with real PostgreSQL, the actual
guarded execution gateway, a broker simulator and the installed retained book
read-only. Count canonical loads across multiple reads, quotes, reconciliation
and broker-only cursor writes. Demonstrate preserved invalidation on economic,
unknown, dual-sizing and relation changes; falsify writer/pin/identity guards.
Exercise source waits versus typed local/database/backup availability through
the actual worker/supervisor boundary, genuine source deadline escalation,
configuration refusal, callback clocks, expired/mismatched owners and existing
known failures. Preserve producer clocks and all original safety deadlines.

Pin the exact new retained-source transition and preceding main source closure
independently. Use targeted adjacent tests, exact-head protected qualification,
signed image publication and the supported certified installer. Preserve the
book, account binding, previous cycles, receipts and command journal. Installation
must wait for or fence the existing execution owner through its supported
protocol; no live patch, manual order, historical transport or inferred fill.
An elapsed opening-increase window stays elapsed. Verify actual dashboard and
scheduled execution evidence after deployment without promising late trades.
