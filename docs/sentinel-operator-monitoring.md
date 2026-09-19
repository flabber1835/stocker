# Caesar's Palace operator monitoring and Web Push contract

Status: implementation contract for GitHub issue 369. This document defines
operator projection and notification behavior. It does not grant financial or
broker authority.

## 1. Boundary and name

**Caesar's Palace** is the user-facing name of Sentinel's operator panel and
notifications. Internal package, database, service, and execution-contract
names remain `sentinel_*` so branding cannot create a second architecture.

The panel reads durable Sentinel evidence. It never constructs an Alpaca
client, never infers strategy state from broker state, and never computes an
execution permission. The only browser-originated writes are subscription
create/refresh and subscription removal in the dedicated Web Push enrollment
router. Those writes cannot name a command, plan, security, quantity, price,
control generation, certificate, or broker operation.

The private panel is served on one stable HTTPS Tailscale origin. Tailscale is
the authentication and reachability boundary; the application adds no login,
cookie, bearer token, or parallel session authority. Panel, JSON, manifest,
service-worker, subscription, and health responses use `Cache-Control:
no-store`. A reverse proxy must not cache them.

## 2. One recoverability policy

Every operational fact is classified by the same pure policy. The rendering
colors, `/panel.json`, `/operational-health`, and notification eligibility all
consume this result.

```text
GREEN   the required fact is current and valid
AMBER   a bounded, reviewed automatic recovery is active; no operator action
        is presently required
RED     recovery is absent, prohibited, exhausted, past its deadline, or
        impossible; operator action is required
```

`UNKNOWN` is an evidence condition, not a fourth optimistic health state. A
required-current unknown fact is red. `PENDING` remains available only for a
capability deliberately not installed or not activated; it cannot hide a
required runtime dependency.

An explicitly disabled automation control is the reviewed maintenance exception
and remains amber/inert. An enabled control whose emergency kill is engaged is
red: the alert is critical and the dashboard may not describe that state as
healthy maintenance.

A time-bearing row declares whether it is required-current and its cadence
budget. A stale required-current row is red unless durable evidence says a
bounded automatic recovery is active. Staleness never improves a pre-existing
failure. Future-dated evidence beyond the clock-skew allowance is red. The
generic historical behavior “stale OK becomes WARN” is not used for required
runtime facts.

The recovery evidence contains the phase, current attempt, configured maximum,
next attempt, and deadline when those facts exist. `attempt >= maximum`, a
missing next attempt for a nonterminal failure, or an expired deadline is red.
The panel does not guess recoverability from an error string.

The durable retry diagnostic also carries a reviewed typed failure domain when
one row needs a narrower recovery association than phase alone. In particular,
only a `BACKUP`-domain retry may make temporary backup/archive lag amber, and
only while the independent base/WAL/restore proof remains internally valid.
Unrelated retries cannot lend their recovery budget to backup evidence, and a
WAL gap, corrupt proof, or lost restore authority stays red even during a typed
backup retry.

Freshness follows producer cadence rather than a four-calendar-day tolerance:

- feed currency is measured in exchange sessions; READY with one or more
  sessions behind is not green;
- automation leader and authority verdict budgets remain derived from their
  heartbeat/check cadences;
- an account or broker observation is current for ten minutes while execution
  or reconciliation is active, and otherwise through the durable cycle's next
  scheduled wake;
- canonical book, exposure, and terminal evidence are current through the next
  required exchange-session decision. Session identity disagreement is red;
  elapsed holiday/weekend calendar time alone is not an outage;
- a backup proof is current only inside the configured 26-hour base-backup
  objective and its continuous WAL/integrity coverage remains valid.

No panel fetch may contact the broker merely to make a row fresh.

## 3. Required operator facts

The panel retains the operational execution projection in reviewed dual mode;
dual mode changes financial-performance authority, not runtime visibility.
Required rows include:

- Alpaca Account: durable account status, blocking flags, bound account
  identity, equity, cash, buying power, and multiplier;
- Broker/book/exposure/terminals: the existing durable observation, immutable
  Wealth Core shadow book, exposure plan, and command-journal projection;
- Backup / Restore: the latest successful physical-base-backup/WAL proof and
  latest successful restore-drill proof, with objective ages;
- Runtime Identity: running Git commit and image digest compared with the
  active signed certificate's reviewed deployment-artifact claims and the
  latest durable runtime authority verdict.

Environment variables are observations of the running container, never review
authority. Runtime Identity is green only when the durable active certificate,
its reviewed Git/image claims, and the runtime observations agree. A missing
claim, missing runtime observation, inactive certificate, or mismatch is red.

Alpaca account evidence is written only by the execution membrane after its
normal account-identity checks. Backup evidence is written by the backup and
restore authority paths. Both are append-only operational evidence and are
never inputs to Wealth Core or Sentinel exposure decisions.

Backup proof content has a digest, but the digest is not an observation clock.
Re-verifying unchanged valid proof appends a new row with a new database time;
it is never collapsed into the older row merely because the restore chain did
not change. This lets freshness mean "last successfully checked" while retaining
the complete append-only history.

`GET /health` remains a database/schema readiness probe. `GET
/operational-health` projects the same recoverability model as the panel and
returns 2xx only for green or amber. Any red required fact returns 503. It may
not substitute a shallower liveness calculation.

The Home Screen view carries a prominent presentation heartbeat derived only
from the server generation timestamp. It advances an explicit "updated N
seconds ago" counter while the document is current and changes to HEARTBEAT
LOST / red when the 45-second presentation budget expires, the device goes
offline, a backgrounded page resumes, or a back-forward-cache page is restored.
This browser heartbeat may withdraw old green but may never manufacture green;
fresh server and durable producer evidence are still required after reload.

The current automation cycle is expanded into durable step rows: discovery,
data refresh, plan preparation, open wait, order transport, broker
reconciliation, and completion. A step is green only after its transition is
witnessed or a later permitted transition proves that gate was passed; the
current step is amber only inside its schedule/retry deadline; future steps are
pending; and the failed step plus completion are red after a terminal refusal.
`RETRY_WAIT` is attached to its durable retry phase and displays attempt,
maximum, and next-wake evidence. The existing control, leader, authority,
account, feed, alert, and dispatcher rows remain separate so progress cannot
hide the prerequisites around the cycle.

## 4. Notification policy

The default is quiet:

- green state and recovery-to-green transitions never send Web Push;
- enrollment can send one test notification only from the user's explicit
  button gesture;
- the first amber transition for one logical incident may notify; further
  retries with the same cycle, phase, and failure fingerprint are coalesced;
- fenced data-not-ready and expected shadow source-final waits are one logical
  incident per decision session; changing exception prose, frontier
  diagnostics, or progressing from ingest lag to the expected source-final
  wait may not create another push for that session, while the panel continues
  to project the authoritative feed and readiness evidence;
- that fenced source-recovery window ends at the decision session's following
  XNYS open. Before the open it is amber with one stable incident identity; at
  or after the open it is a distinct red deadline-missed incident. Any other
  shadow integrity refusal is immediately red;
- the dedicated shadow supervisor applies that same per-session coalescing and
  following-open escalation to causal waits and provider availability. A
  semantic worker retry emits one amber incident per decision session while
  below its configured threshold; the existing terminal latch is the distinct
  red escalation at exhaustion;
- amber-to-red escalation sends one red notification;
- a red incident, kill engagement, dead-lettered alert, or nonrecoverable
  failure sends once per immutable logical event;
- every unique durable `sentinel_fills` row sends one fill notification,
  including each distinct partial fill.

The old `AUTOMATION_EXECUTED` label for entry into `RECONCILING` is forbidden:
submission/reconciliation is not execution completion. When retained as an
operational event it is named `AUTOMATION_TRANSPORT_SUBMITTED`, but it is not a
default push-worthy green event.

Fill notification identity is `fill:<broker_order_id>:<fill_key>`. Its payload
contains BUY/SELL, ticker, permanent security identity, quantity, price,
broker fill time, and broker order identity. The immutable command supplies
side and security metadata; the fill supplies quantity, price, and time. A
missing or contradictory join is red evidence and never fabricated.

The state transition or fill is committed before notification materialization.
On every dispatcher claim, committed events and fills without an outbox row are
reconstructed with the same idempotency key. This closes the crash window and
converges to one logical alert. Transport is at-least-once: a crash after a
remote acceptance may repeat a request. The service worker uses the immutable
alert id as its notification `tag`, and per-subscription delivery rows prevent
already-confirmed devices from being resent during a partial fan-out retry.
This is logical deduplication, not a false claim of exactly-once networking.

The additive schema records a one-time Web Push activation timestamp. Fill and
new coalesced-incident reconstruction applies only to events whose economic or
transition time is on or after that boundary. Existing outbox rows older than
the boundary are closed without first-party delivery. This prevents rollout
from replaying historical fills or old retry incidents as a notification
storm. Current red health is independently projected after dispatcher startup,
so suppressing historical transport does not manufacture a current green.

## 5. First-party Web Push

The web application supplies a manifest, 180/192/512 pixel branded icons, a
service worker, and an explicit Subscribe button. It calls
`Notification.requestPermission()` and `PushManager.subscribe()` only inside
that user gesture. The VAPID public key may reach the browser. The VAPID private
key exists only in the dispatcher environment and is never rendered, logged,
stored in a subscription row, or returned by an endpoint.

Subscriptions are durable and multi-device. The endpoint is treated as a
secret: operator output and transport errors name only a subscription digest
and HTTP status. A 404 or 410 response retires that subscription. Other
retryable failures use the bounded alert policy. Fan-out succeeds only when
every recipient captured for that logical alert is delivered or terminally
retired; a device added later does not receive historical alerts.

The service worker handles a browser `pushsubscriptionchange` by obtaining the
public VAPID key, reusing or recreating the browser subscription, and calling a
dedicated same-origin refresh endpoint. That endpoint can only upsert the new
notification capability and retire the named previous endpoint in one database
transaction; it queues no enrollment test and cannot express financial intent.
An unchanged endpoint with rotated keys is refreshed in place. Permission
revocation that prevents replacement is ultimately retired by the push
service's terminal 404/410 response or by explicit device removal.

Endpoint replacement preserves notification obligations. Retain the predecessor
subscription and its durable successor link, and carry its eligibility time to
the replacement. Thus rotation before first fan-out does not lose an alert;
rotation after capture resolves the original pending recipient to the current
endpoint. Delivered recipients remain delivered. A later unrelated enrollment
does not inherit earlier alerts. Explicit removal ends continuity; re-enrollment
starts a new eligibility interval even when the endpoint is reused.

Enrollment, removal, fan-out capture and delivery-result writes serialize on the
notification policy row, never across network I/O. Result transactions acquire
the policy row before renewing the outbox claim, matching enrollment's lock
order. Immediately before each
request, resolve the recipient again and snapshot its endpoint, keys and refresh
revision. The result write must match that same current subscription revision
and the existing outbox attempt. Rotation during HTTP makes the old response
retryable without recording success or retirement against the successor. This
includes key rotation without an endpoint change. Missing, cyclic or conflicting
succession refuses; no browser refresh may merge two independently active devices.
Explicit schema migration installs the successor and eligibility fields;
runtime never repairs missing schema or invents succession for legacy retired
subscriptions. Existing already-terminal deliveries are not resurrected.
The additive Stage-4 catalog fingerprint, measured on isolated PostgreSQL, is
`9d80e0801cf8c8e98b739e337eab3d883f3aac3495e47766b3214423ff90b7c1`.

The service worker displays every received push, focuses an existing
Caesar's Palace window on click, or opens the stable start URL. It does not
cache panel health. An offline navigation renders an explicit red offline page
rather than a saved green panel. Foreground, `pageshow`, back-forward cache,
visibility, online, and offline events invalidate old status immediately and
fetch a no-store projection.

The HTTPS webhook adapter remains optional for migration and external testing;
ntfy is not a production dependency. Web Push is the first-party production
transport. Periodic healthy test pushes are prohibited because they are noisy
and Web Push notifications must remain visible.

When both transports are configured, Web Push remains the selected operator
transport and the webhook is reserved for reporting dispatcher database loss.
Its probe must not run in that mode: a secondary-path success may neither clear
a primary Web Push failure nor create periodic healthy notification traffic.
The bounded webhook probe runs only when the webhook is the selected legacy
transport.

A contiguous dispatcher database outage is one webhook incident, not a new
notification each minute. Until one fallback request is accepted, retries keep
the same idempotency key; after acceptance the outage stays silent. A successful
database loop closes the incident and is the only event that re-arms a later
database-outage notification.

A fresh successful dispatcher loop may therefore report healthy before any
real notification has been needed. Its heartbeat proves the worker/config/DB
loop; active subscription count is shown separately, and last delivery remains
visible evidence rather than a prerequisite that creates test noise. An actual
delivery failure moves the dispatcher to bounded degraded/failed state and an
idle loop cannot clear it—only a later real delivery success can.

## 6. Validation and rollout

Automated validation covers the pure recovery matrix, session-stale feed,
cadence expiry, dual-mode runtime rows, account/backup/runtime-identity rows,
operational-health status codes, immutable fill reconstruction, duplicate and
partial fills, per-device retry/retirement, VAPID encryption, explicit-gesture
enrollment, service-worker click handling, no-cache/offline behavior, and phone
portrait/landscape plus light/dark/dynamic-text/long-content layouts in a
WebKit-capable browser job.

Playwright WebKit validates iPhone-sized layout and page lifecycle behavior;
Chromium injects a synthetic push into the actual registered service worker,
asserts the browser-retained notification, and validates offline response,
explicit enrollment gesture, and click routing against the exact served worker
code. PWA actions wait for an activated worker that actually controls the page;
`serviceWorker.ready` alone can resolve during activation. A test-only HTTP
gate holds activation and observes completed readiness snapshots to falsify this
barrier without sleeps or racing unrelated worker-metadata reads. Offline
acceptance captures the main-frame service-worker response event before reload,
then requires HTTP 503, `Cache-Control: no-store`, and the explicit red document;
the reload API's nullable return is not response authority. Push acceptance
records browser-retained notification metadata in the real registered worker
immediately after its original native `showNotification` promise succeeds. It
does not manufacture a notification or substitute the handler's arguments for
browser evidence, and does not require the OS to retain a toast until a later
page poll. Delivery-stage and worker-error diagnostics accompany a refusal.
Playwright service-worker inspection is Chromium-only, and desktop
WebKit automation does not implement the iOS Home Screen delivery channel, so
a physical iPhone acceptance run remains a deployment check: install from the
Tailscale HTTPS origin, subscribe by button gesture, close the app, deliver a
synthetic server push, open it from the notification, rotate, change text size
and appearance, and verify an actual paper fill produces one notification.

Schema rollout is additive. Subscription, recipient-delivery, account-evidence,
backup-evidence, and restore-evidence tables join the closed Stage 4 catalog.
The new image must run the explicit schema migration before panel or dispatcher
startup. Rolling back code does not delete evidence; old code simply does not
consume the additive tables.

The production origin is configured in this order:

1. Assign one stable tailnet DNS name and expose `127.0.0.1:8004` through
   Tailscale Serve HTTPS. Keep the dashboard private to tailnet ACLs and disable
   intermediary caching.
2. Put that exact scheme/host/port origin in `SENTINEL_PUBLIC_ORIGIN`; generate
   and securely retain one P-256 VAPID keypair and subject. Never copy the
   private scalar into panel configuration.
3. Run the explicit schema migration, deploy panel and dispatcher, then install
   Caesar's Palace from Safari using Add to Home Screen. Enrollment must occur
   from the app's button and must deliver its one test notification.
4. Complete the physical-iPhone closed-app notification/click/resume/rotation/
   appearance/text-size acceptance run before removing a migration webhook.
