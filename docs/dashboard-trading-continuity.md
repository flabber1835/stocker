# Dashboard trading continuity and panic status

### Opening and closing evidence, November 27

A saved, current PAPER plan and a current execution callback can outlive the
strategy publisher that prepared them. During a positively proved opening,
missing independent reporting about the publisher or backup is an operator
warning. Keep the underlying rows visible and require review. A reported
integrity fence, pending publisher attempt without status, invalid backup,
lost authority or a blocked execution path still takes precedence. Treat
absent reporting as a distinct source fact. Retain the original plan,
callback and evidence deadlines. Once that opening proof expires, evaluate
the next action on its own evidence.

When the runtime has verified the current base and its WAL chain, a missing
operator backup or restore-drill report is also a reporting warning during
that proved opening. Validate every report that is present and stop using the
runtime evidence at its original expiry. A failed, stale or conflicting
restore chain still prevents this classification.

This opening allowance belongs to the locally authorized PAPER account.
LIVE retains its independently verified backup and funding requirements.

An opening can have planned orders, orders being sent and acknowledged
siblings at the same time. Describe that dispatch as active only while the
supervisor reports a current callback for the exact plan, cycle and original
window. During reconciliation the same allowance requires identified, already
submitted orders and a supervised reconciliation attempt. An order with an
unknown outcome, a failed callback or an expired window cannot establish
dispatch in progress.

A PAPER refresh can briefly withdraw the current display while orders change.
Keep the time of the last signed observation and its original expiry. While its
exact callback is still running, missing independent reports can retain their
warning status. A change to the strategy evidence ends that allowance. A
financial verifier that has explicitly yielded to the active writer can show
verification in progress until its original deadline. These states cannot
establish a fresh broker balance or confirm a fill.

At the close, the active producer's observed phase takes precedence over a
general publication wait for that session. When its lease expires or the job
finishes, use the independent publication or strategy evidence. During a
partial dashboard refresh, distinguish an unavailable current verdict from
a confirmed trading stop and keep dated warnings visible.

Decision, 2026-11-24, before implementation. The owner defines a red dashboard
as a panic signal: unattended trading cannot continue at the next eligible
opportunity without intervention. This decision supersedes the older rule that
every active failed operational row makes the human headline red. It changes
operator presentation and the operational health projection only. It does not
change the broker, execution, verification, authority, backup, or scheduling
guards and does not authorize LIVE trading.

## One current continuity decision

Publish a typed, scope-bound `trading_continuity` result from the existing
authenticated operational snapshot. Use the same result for the HTML headline,
`/panel.json`, and `/operational-health`. Durable automation-stop alerts retain
their separate producer-owned health check. The continuity result has a
status, controlled reason codes, original evidence times and expiry, the next
eligible scheduled action when proved, and the row keys that support it. Do not
derive it from display strings, the worst historical row, a successful HTTP
response, or the fact that an automation switch says ACTIVE. The decision must
be recomputed when its original evidence expires; refreshing the page cannot
extend a proof.

The visible colors have these meanings:

* **Red — trading stopped, action required.** A current fence, exhausted or
  forbidden recovery, or missing required current proof means the unattended
  path cannot be shown to resume at its next eligible action without an
  operator. Examples include the emergency kill, lost current authority or
  ownership, a critical integrity latch, unresolved broker command outcome,
  irreconcilable account/position/order evidence, or a required source/backup
  proof that has no valid automatic recovery path. Say which gate is stopping
  trading and what action is required. Red never means merely that an old cycle
  failed or that an incident awaits acknowledgement.
* **Amber — attention or review, automatic path remains.** A current issue has
  a proved bounded automatic recovery, or a past opportunity was missed but
  the current scheduler can prepare the next eligible session. Recovered and
  unacknowledged incidents, planned restarts, and dated stale idle observations
  stay visible here. Say what was missed or degraded, the next scheduled action
  and its evidence boundary. Amber does not claim an order can be submitted now.
* **Green — normal unattended path, reviewed interval.** Current required
  capabilities and ownership are proved, the system is doing its expected work
  or waiting for a proved scheduled action, and the operator review interval is
  clean. It is not a financial certificate or a promise of a future fill.
* **Neutral — current status cannot be established by this display.** An
  offline/stale browser or partial/unavailable dashboard observation cannot
  assert that trading is active or stopped. Show dated last-known facts and
  retry. Never turn this into green or renew a source clock. A fresh,
  authenticated current negative fact still takes precedence over a partial
  view.

The existing PWA offline fallback says `STATUS NOT CURRENT — OFFLINE`. It is a
neutral, browser-local notice and does not report a trading stop. Preserve its
exact service-worker bytes in this release: the backed PAPER installer includes
`SERVICE_WORKER` in its canonical predecessor/candidate proof. Changing that
copy requires a separate, qualified release decision.

The classifier must distinguish **current execution permission** from
**unattended continuity**. A market closed for the night, a normal opening
wait, or the ten-minute new-buy cutoff being over does not mean the system is
permanently stopped. It must name the next eligible action from actual owned
scheduling evidence. If the current window is lost, retain that incident and
its economic consequence as amber; do not backfill or replay an expired BUY.
If no bounded next-session path can be proved, do not claim automatic recovery.
"Trading active" means the scheduler can pursue the next eligible plan under
all its existing guards. It does not promise an order today, an intraday crash
sale, automatic liquidation, or protection from a market decline. A green or
amber continuity display must never imply those capabilities.

## The November 24 examples and hard boundaries

A terminal `SUPERSEDED` / `CONTROL_GENERATION_SUPERSEDED` cycle can keep its
immutable `NOT_VERIFIED` verdict and zero-order result. Its failed step rows
are historical when the current generation has a proved enabled leader,
authority, current account and next decision path, with no unresolved command,
working order, or journal hazard. Show the missed session and retained review
warning in amber. Never relabel that old trial as successful or adopt its plan.
If supersession is ambiguous, if an order may have been sent, or if the
current generation is fenced, the relevant current stop remains red.

The same bounded amber classification also applies to a terminal
`SUPERSEDED` cycle in the **current** generation with the exact failure code
`MISSED_EXECUTION_WINDOW` or `MAX_EXECUTION_LATENESS_EXCEEDED`. This covers an
unattended reboot or network interruption that exhausts the opening window.
Require zero attempts, exact current binding and configuration, a negative
canonical cycle-event and command-journal check, no active or uncertain order,
current leader and authority, a complete idle broker observation, and a
future next decision from the installed schedule. A transport-capable recovery
that ends with the same failure code does not qualify. Keep the old trial
failure, missed opportunity and review warning visible. Unknown send status,
an older unrelated cycle, a stale owner or any missing proof stays red.

The verifier must derive that next decision using the same validated
`AutomationConfig` identity as the automation worker. The supported Compose
release passes the verifier only the configuration inputs consumed by
`config_from_env`, including the public BUY-policy identity and optional
PAPER debug window; it does not pass broker credentials or the broader
authorized-worker environment. The verifier checks the resulting fingerprint
against current control and health before issuing the bounded signed warning.
A missing or different configuration refuses the amber claim.

The backed local installer may admit this one verifier-only Compose forwarding
change from the `420a860a0` predecessor. Its automation Compose bytes have
SHA-256 `fa94441022dc618ef598d3d1f08b117b3d8c609b77a4168967882f7274cb5dde`;
the reviewed candidate bytes have SHA-256
`768bfbf7a4beb4ee37ccc21cc750aa9fec8945ef932ed15e55889b4d6e7e4029`.
The installer requires that exact predecessor/candidate pair and the exact
insertion inside `sentinel-verifier`; its existing qualified source-file hash
and named allowed-delta checks still apply. This grants no broader Compose
edits, broker credentials, PAPER authority, or installation bypass.

A full broker order/position snapshot keeps its original observation time.
When execution is idle, no order or journal hazard exists, and an owned next
pre-open check will obtain a new complete snapshot before any order, expiry of
the old full snapshot is an amber dated warning, not a panic state. A fresh
account observation is not a new full broker snapshot. During active execution,
reconciliation, or outstanding command/order work, the existing ten-minute
full-snapshot requirement remains. An expired or incomplete required snapshot
cannot authorize an order; without an active bounded recovery it is red.

A terminal cycle must not inherit the worker's next poll time and display it
as that cycle's next wake. Show the terminal time on the old cycle and the
worker's separately sourced next action on the current scheduler. The next
action is a prediction only when its owner, generation, lease and original
deadline are current.

Any claim of automatic recovery must identify its exact typed owner, phase,
remaining attempt/deadline and the future gate it will recheck. A generic
retry string, a future timestamp alone, or another domain's retry budget is
insufficient. Preserve the UNKNOWN outcome rule, exact command identity,
account binding, long-only/unlevered envelope, current source and backup
proofs, and all original cutoffs. Presentation cannot grant financial
authority, acknowledge an incident, or resume a fence.

## Public contracts and alerts

`/panel.json` exposes `trading_continuity` with the visible status, color,
controlled reasons, blocking keys, warning keys, next action and original
validity. Keep raw financial and operational rows, immutable verdicts,
`overall` and `operational` as separately named strict diagnostics; label them
as such so an old raw FAIL cannot be mistaken for a current trading stop.
`dashboard_health.color` and the HTML headline follow the continuity decision
plus the existing review requirement. Details show the dated raw evidence and
review history without a red panic badge for a historical event.

Observer receipts encode `trial_reason_codes` as a JSON array even though the
typed panel row holds a tuple. Normalize this field before signing the receipt
so an in-memory envelope and its PostgreSQL JSONB round trip are identical;
validate and restore the tuple only when decoding the row. This representation
change grants no new trial verdict or trading authority.

`/operational-health` reports the same current continuity status/color and
blocking/warning keys when the strict observation is current. Return 503 for a
current red trading stop or when its strict observation is unavailable. An
unavailable strict response is neutral/unknown and may carry a separately
named bounded display projection; it never fabricates a red trading stop.
An independently current, authenticated negative fact still reports red.
Return 2xx for proved
green or amber continuity while preserving the raw strict diagnostic verdict
in a separate response field. Before changing the endpoint's status behavior,
audit every in-repository and installed consumer that may treat 2xx as
execution authority; update or retain a distinct strict readiness check for
that consumer. Never use this endpoint itself to admit an order.

The durable automation health alert remains the trading-stop notification
source; this dashboard projection does not change its trigger, severity, or
delivery. A missed past session, idle snapshot expiry, recovered condition, or
unacknowledged history remains visible as an amber dashboard warning/review
event. Do not delete, rewrite, auto-acknowledge, or replay old notifications.
Raw critical evidence stays available for audit. A notification-delivery
failure cannot manufacture a green claim.
When the exact signed safe missed-open continuity witness is current, a failed
alert dispatcher or dead-letter row is a separate amber human notification
warning; its raw FAIL remains visible. Delivery does not fence the scheduler or
execution, so it cannot by itself turn that proved unattended next-decision
path red. Without the bounded witness, or with any other current trading stop,
this exception does not apply. No alert health change grants order authority.

### Prospective missed-window cycle alerts

The cycle-transition outbox also emits a durable incident. Its existing blanket
`SUPERSEDED` severity is critical even for an unsent missed window. For **new**
events only, classify that specific historical loss as `WARN` when the fenced
transition writer proves all of these in its transaction: the cycle came from
a pre-transport state, its attempt count is zero, its failure code is one of
`CONTROL_GENERATION_SUPERSEDED`, `MISSED_EXECUTION_WINDOW`, or
`MAX_EXECUTION_LATENESS_EXCEEDED`, and the existing scoped event and command
journal check finds no transport or unresolved command. Append a versioned
no-send witness and the failure code to that immutable event. A transition
without the witness remains `CRITICAL`; a retry, transport-capable cycle,
ambiguous journal, or unknown failure code never earns warning severity. The
extra negative check must not prevent the original terminal transition when
it cannot prove no-send; it only withholds the warning classification.

The notifier reads only the immutable event and validates the exact witness
shape and permitted code before assigning `WARN`. Keep the existing event
identity and outbox reconstruction behavior. Do not rewrite already-created
alerts, change the active automation health alert, or use alert severity to
admit an order. Test new no-send missed windows, absent or malformed witness,
transport-capable supersession, and crash-gap reconstruction from the event.

Qualify the classifier and all three surfaces with a superseded zero-order
cycle, expired idle full broker snapshot, genuine unresolved UNKNOWN, active
execution snapshot expiry, emergency kill, lost leader/authority, source or
backup integrity refusal, bounded recovery, missed cutoff, current clean wait,
unreviewed history and stale/partial browser or server observation. Include
falsifiers that remove the no-hazard or next-action proof and force the
expected red/neutral result. Verify any strict endpoint consumer separately
before installation.
