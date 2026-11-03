# Dashboard resilience, history and current health

Owner decision, November 3 2026, before implementation: perform a full dashboard
pass after weeks of brittle refreshes, slow page loads and ambiguous red states.
This work changes operator presentation and nonfinancial acknowledgement only.
Execution, strategy state, immutable trial verdicts, broker UNKNOWN outcomes,
source guards, account binding, authority and financial clocks remain authoritative.

## Accepted colour contract

Green means expected, healthy operation and a clean interval since the last
explicit acknowledgement. Waiting for market close, opening time, the next
decision or another proved scheduled step is green when that is the state the
system should occupy. Pending ordinary work is not itself an incident.

Red means a failure remains present. Acknowledging an active failure cannot make
it green. A failure that corrects itself becomes amber, retaining its incident
until acknowledgement. Amber never automatically becomes green merely because
the process recovered, a timer elapsed, a page refreshed or a service restarted.
Acknowledgement establishes a new clean interval; it never deletes history or
changes a historical trial or performance verdict. Planned deployments and
restarts also create a recorded amber state requiring acknowledgement, including
when the operation completes normally.

The owner separately selected neutral browser freshness. A phone sleeping,
going offline or waiting for a page response shows "status not current" and
dated last-known values. It does not create a system incident. A stale browser
cannot display a current green claim or renew evidence expiry. A fresh server
response restores the server's actual health and acknowledgement state.

Health, financial verification and connection freshness are independent facts.
A historical pre-transport cycle can correctly remain NOT_VERIFIED after a
new authorized generation replaces it. Its two supersession reason codes are
not evidence that the new current plan failed. Genuine account, source,
reconciliation, transport or UNKNOWN failures remain failures. Operator
acknowledgement never grants financial authority.

## Confirmed baseline and causal evidence

Verified base is main2e5e856c34e50958810a51f89e32b20db6a776a2. Production is
that signed immutable release, genuinely ACTIVE at control126. Canonical
installation fenced123, deactivated124, activated125 and released126. It safely
retired the unexecuted generation122 cycle and prepared the current November3
plan through the normal authority and reconciliation gates.

The old-cycle trial payload contains only CONTROL_GENERATION_SUPERSEDED and
CYCLE_SUPERSEDED. The terminal verifier correctly retains NOT_VERIFIED; the
notifier marks every such result critical. The alert model makes all
unacknowledged critical history FAIL and required-current, producing red even
while the current plan, account, leader and backups are healthy. The original
final-readiness refusal was reproduced with the identical stderr hash.

Browser code additionally derives hardFailure from the global red badge.
Resume can therefore add not-current even when the server has a fresh snapshot.
CSS then repaints all twenty model slots red. That is a page freshness overlay,
not twenty separate holdings failures. Current rendering conflates two facts.

One bounded read of each surface measured local HTML headers4.164seconds,
public HTML3.541seconds and public header image0.030seconds. A separate normal
read-only page build took6.1499seconds: feed2.0434, runtime2.6468,
operator evidence0.6914, worker probe0.4703, financial receipt0.2487,
automation0.0250, ownership0.0143 and segment disclosure0.0076seconds.
This is baseline evidence, not a stress test or a claim about physical iPhone
network performance. No production service was changed for these observations.

## Implementation decisions

### Durable operator review, separate from financial authority

Use a small PostgreSQL presentation extension for a scope-bound health row and
append-only event history. Its scope binds the durable deployment, broker account,
takeover epoch and selected endpoint; source upgrades do not reset history.
Register a panel incarnation once, retaining an amber restart/deployment event.
The existing page-build admission owner records only typed health transitions:
failure, recovery and a reviewed baseline. There is no additional observer,
timer, native unit or root/log watcher. Financial source collection remains
SELECT-only; the additional writes affect only this presentation extension and
the ordinary notification acknowledgement metadata explicitly reviewed by the
operator. They never touch a plan, command, book, control or certificate.

A page build's current facts determine active failure independently of old alert
severity. Proved normal scheduled waits are healthy. An active negative fact is
red; a recovered fact, unreviewed material warning or planned restart is amber.
The append-only review history prevents either amber or recovered red from
becoming green automatically. A backend read failure is retained in the process
until PostgreSQL is available; the same latch covers uncaught backend rendering
and serialization errors. An ordinary queued-refresh timeout is neutral and does
not set it. Losing that process necessarily creates a new
unreviewed incarnation event. An unavailable/malformed review store cannot
establish green. This is bounded operator-state persistence, not a new diagnostic
or error-monitoring service.
An unavailable review store displays a controlled schema/database/refusal reason.
Never render a raw SQL/connection exception or credential-bearing driver detail.

Acknowledgement uses an explicit, same-origin nonfinancial POST and a signed,
short-lived exact-view token. Re-read current facts, compare the scope and event
head, and refuse an active failure, changed view, expired token or concurrent new
incident. Record actor, original event head and acknowledgement time atomically.
The view binds material health conditions, selected software, publication, account
scope and plan identities. Advancing heartbeat clocks and live account prices do
not invalidate an otherwise unchanged review. A concurrent review/restart/new
notification still changes the durable head and refuses the old token.
The short acknowledgement transaction locks only ordinary notification metadata
against concurrent insertion/update, within the existing finite lock/statement
budgets. It locks no plan, command, control or authority row.
Reviewing a state never rewrites a trial verdict. Ordinary alert delivery and
historical acknowledgement remain separate facts; explicitly reviewed legacy
notifications may be acknowledged through their existing metadata contract.

The additive presentation schema is optional for financial runtime admission and
mandatory for a green dashboard. It has an exact catalog witness, append-only
history guards and an explicit fenced installer; HTTP startup/reads never CREATE
or repair tables. Recognize its exact catalog separately from the immutable
financial extension contracts, preserving their installed marker and all old
component definitions. Unknown/partial presentation objects still refuse.

### Browser lifecycle

Keep server health and browser freshness as separate state. A server red badge
must not seed a browser transport hard failure. A sleeping, offline, clock-skewed
or expired document withdraws current styling into a neutral last-known view;
all twenty slots retain their dated model states rather than becoming twenty
red failures. Only a new complete, current server document restores current
styling. Keep original evidence times, finite request/refresh bounds, one request
in flight, source/configuration checks, and the rule that JavaScript cannot
create a financial verdict. The PWA offline page uses the same neutral contract.

### Request cost

The measured repeated cost is full loading, canonical copying and validation of
two large, immutable sizing records for dated intent display. Keep canonical full
validation on a miss. A bounded display-only memo may retain only the small
validated intent projection, never executable sizing authority or a complete
operational result. Every use must re-read the exact row identity/version, plan,
binding and current mutable facts. Bind the memo to database/physical incarnation,
relation identity, full transaction epoch plus tuple xmin/ctid, cursor/session and
stored digest; clear it on configuration change and clock regression and expire
it after a short fixed interval. A changed/deleted/reinserted/restored row forces
full validation; a changed row with an unchanged claimed digest must refuse.
Do not re-date any returned observation, plan or expiry. Execution and standalone
callers retain the original uncached loader.

Only content-addressed static brand assets may use long browser caching. HTML,
JSON, operational health, review actions and financial evidence remain no-store.
Measure the corrected full request path and payload without a production load
test; qualify mutable/tampered-row, expiry and removed-guard controls privately.

## Review and delivery boundaries

Review every source group and dependency, independent verifier and projections,
schema/read budgets, request admission and fallback, all HTML/JSON/health
surfaces, the twenty-slot overview, current-plan/run/account details, browser
resume/offline/expiry, images/PWA and push subscription boundaries. A confirmed
finding needs a causal reproduction and a targeted refusal or falsifier.

Keep HTTP financial reads SELECT-only and broker-free. No new error/root-cause
monitor, extra supervisor, backtest change, daemon reset, Windows/root USB
cutover, prototype stash, widened financial deadline or stale authority cache.
Record additional implementation choices here before changing code. Qualification
uses an isolated, bounded private lens and meaningful affected tests, including
mobile lifecycle execution; it does not claim a physical iPhone test.

Finalize the actual complete candidate source map only after reviewed code is
settled, retain the exact installed2e5e856c predecessor and every existing
historical/economic source mapping, and prove unknown/missing/extra sources still
refuse. Deliver through a ready PR from codex/dashboard-resilience-pass, with
exact base, tests and measured limitations. No direct-main or runtime patch.

The URL-selected complete-source descriptor advances to version4 to add the exact
installed PR563 predecessor (434 Python files; closure
85165e291f835307e86d45a1c678d44529ce42d1d46713614147c676ade7c47b).
The older PR561 map remains independently count/hash pinned. Its names must be a
subset of the new complete candidate because this delivery adds presentation
modules. The complete actual-candidate equality guard remains unchanged; no
individual file, partial map or unknown source gains compatibility. Preserve the
422-file base, structural profile, economic mappings and all older witnesses.

Private measurement on one 300,863-byte sizing fixture used five reads per path:
full canonical loading averaged0.003028seconds; version-checked dated-intent reuse
averaged0.000586seconds. This measures only the repaired component, not a deployed
full-page latency or a physical-phone result. Every reuse still queried the row
version. Production has not been patched for this measurement.

## Qualification

The bounded private qualification passed1,277 unique targeted Python cases across
initial, remaining-only and affected-path rounds. Earlier failures and harness
refusals were retained; no failed or skipped Python case remains unresolved.
The final rounds rechecked controlled refusal copy, server-render failure versus
ordinary queued refresh, the exact final source map and its removed-guard
falsifier. This is an aggregate of targeted rounds, not a claim that an unchanged
whole suite was repeatedly run.

The five new dashboard test modules cover PostgreSQL restart/history integrity,
active failure and recovery, acknowledgement races and origin/size/expiry gates,
immutable-row tampering/reinsertion/incarnation and clock changes, small defensive
memo copies, native installation sequencing and the actual acknowledgement
JavaScript. Affected dashboard, scheduling, post-open mirror, installation and
source-acceptance tests cover the retained contracts. Python3.12.13 and private
PostgreSQL17.11 were used with frozen source,1CPU/1.5GiB and no network or
production credentials. Production PostgreSQL remains16; protected CI is still
required before delivery.

Real Playwright1.63.0 execution passed19 WebKit cases and21 installed Edge
Chromium cases against the actual frozen ASGI app at its existing0.5CPU/1GiB
budget. These include twenty neutral slot borders, mobile resume/expiry, real PNG
decoding and recovery, PWA offline503/no-store, push permissions and receipts.
The cached full Chromium executable failed before launching; its evidence was
retained and only the unexecuted Chromium project ran with installed Edge.
Engine-specific exclusions are intentional: Chromium handles PWA/push and WebKit
handles its mobile lifecycle paths. No physical iPhone result is claimed.

The browser server had no operational credentials, used an internal-only Docker
network. Its published port was unreachable from the test host, so a finite
localhost stdio relay carried the actual responses. All
test containers, networks and relays were removed. No production acknowledgement,
runtime installation, Windows/root handover or monitoring service was performed.
