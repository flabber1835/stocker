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
stored digest; clear it on configuration change and clock regression. The
November 4 launch decision below replaces the original one-minute eviction with
reuse only while that exact physical row version still matches. A changed/deleted/reinserted/restored row forces
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

### Presentation DDL coverage transition and failed-install recovery

The first installed PR564 activation exposed a migration sequencing defect.
Creating the two review tables and their function advanced the independent
public-DDL epoch by three; the five statements include two trigger creations
whose event records do not carry a public schema name. Both authenticated
financial evidence inventories still bound the earlier epoch. The runtime
correctly refused EVIDENCE_COVERAGE_BINDING_CHANGED. This is a software
installation defect, not permission to weaken the global DDL witness.

Before creating an absent presentation extension, the explicit fenced installer
will hold the existing migration/financial-writer locks and SHARE locks on all
relations in both evidence inventories. It captures each authenticated prefix,
its tracking head, account binding and complete inventory material before DDL.
Absent coverage remains absent. Existing coverage must authenticate and retain
its original stage and sequence boundary; migration grants no new completeness.
After the exact review DDL, require the exact presentation catalog, the same
physical relation/account/tracking identities and precisely three DDL advances.
Transfer only those previously captured prefix bodies and boundaries to the new
inventory, atomically with schema creation. Unexpected drift rolls everything
back. An already installed extension is an idempotent catalog check and never
rebinds an invalidated prefix.

The production failure occurred before such a capture existed. Recovery therefore
uses a separate explicit, signed pre-DDL witness from a paused isolated physical
restore. Reuse the existing streaming source-byte proof used by progress recovery,
including its complete watched-source set, filtered processed-session identities,
physical tuples and empty unlogged-scratch contract. The new witness has a
distinct dashboard purpose/schema, requires an absent presentation extension and
genuine current authenticated prefixes on that restore, and binds physical system,
account, epoch, heads, prefix digests, backup marker and metadata hash. Do not
substitute the progress migration's sixty-six-DDL witness.

Applying this witness requires the exact installed review catalog, disabled/killed
control, the canonical lifecycle/writer owners, locked watched sources, unchanged
physical/account/heads/prefix identities and byte-for-byte equal source proofs,
with only the exact three-DDL epoch difference. It updates only the two derived
coverage inventory/signature records; their body, boundary, history and all
financial rows remain unchanged. Any source difference or missing pre-DDL proof
refuses. Snapshot/recovery is an explicit operator action through the signed
release; ordinary readers and activation never invoke it. No production restore,
schema rollback, history deletion, direct reseal or guard suppression is allowed.
The recovery transaction also SHARE-locks the evidence tracking/coverage tables
and independent DDL epoch table until commit. Thus an unrelated concurrent DDL
event cannot advance the epoch between the final check and prefix publication.
Qualification must execute that concurrent DDL attempt at the publication boundary
and show that removing the epoch lock permits the forbidden race.

Qualification must exercise the actual populated predecessor migration and
post-failure recovery, transaction rollback/idempotence, absent/partial/stale
coverage, unexpected DDL, changed source bytes with intact catalog, account/head/
reset drift, physical-restore requirements and executed removed-guard controls.
Preserve the installed f58 complete source map as a new predecessor witness when
finalizing the repaired source seal; retain every older map and financial witness.

The repair qualification passed40 unique cases in53 targeted executions on
private Python3.12/PostgreSQL17 with no network or production credentials. A real
pg_basebackup was restored and paused; its authenticated witness recovered the
separately failed primary migration without changing prefix bodies. Concurrent
DDL attempted at the publication boundary was blocked, and removing that lock
killed the test. Removed migration/epoch/head/source-byte guards were exercised.
Initial fixture setup errors were retained and corrected to the actual private
account binding; no production guard was relaxed. Only new or directly affected
cases were executed. Production recovery still requires its own genuine isolated
restore witness after signed release delivery; private tests do not substitute
for that evidence. The complete repaired map contains442 Python files and retains
the independently compared440-file installed f58 map and all earlier witnesses.

PR564's first full CI exposed predecessor test assumptions outside the initial
targeted dashboard set: the old headline/offline colors, a preview double that
did not accept the display-only loader, and schema doubles without the optional
presentation-catalog reads. The repair changes those tests only. Historical
financial source hashes are retained by subtracting the exact documented
presentation overlay before checking the original predecessor bytes; every old
catalog witness and authenticated financial contract remains unchanged. New
counterexamples show that changes to the original schema, catalog checker or
catalog entries still fail that comparison. The remaining and directly affected
private rounds passed47 cases, including the existing removed-guard controls,
with no failures or skips. New-head required CI remains mandatory.

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

## Saved-plan labels for exited broker positions

A saved next-open preview includes held positions that the plan exits, even when
those positions have no target or decision-session bar. Its retained canonical
ticker map therefore need not cover every displayed leg. For an original-intent
preview, fill only missing ticker labels from the matching instrument's symbol
in that same immutable sizing authority's broker observation. Existing canonical
labels take precedence. Do not query the broker or infer an instrument from a
different observation to fill a display label.

The bounded dated-intent memo must retain that position instrument's symbol
alongside its permanent security ID. Its canonical admission, row-version
recheck, byte bound, expiry and defensive-copy behavior remain unchanged.

If a missing label has no nonblank string symbol in the retained position,
refuse that preview rather than present an internal security UUID as a ticker.
The fallback changes display labels only: permanent security IDs, quantities,
opening intents, plan fingerprints, dated observations and saved authority remain
unchanged. Historical mirror and trial verdicts keep their original scope.

An explicitly owner-authorized local application of this display-only change
may overlay the preview and its dated-intent memo modules in the panel container
and restart only that panel.
Retain the original bytes and exact base-image/container identity, require the
tested source delta, and record the overlay commit and file hashes separately
from the signed base image. Preserve the control generation, admitted plan,
canonical state and all other services. Local acceptance must verify the exact
overlay as well as the existing base-runtime checks; it must not relabel the
overlay as signed base-image content. A failed operation restores only its own
known bytes and never overwrites an unknown concurrent change.

## Backup readiness after an archive advance

The delivery observer must distinguish a maintenance tick's checkpoint-refresh
result from current backup readiness. `continuity_ready=false` means that tick
did not publish a checkpoint. The canonical runtime may already have published
a newer authenticated checkpoint after its independent external verification.
This is an observer correction; the production backup writers, financial
admission, archive equality guards and autonomous schedules do not change.

Keep the narrow comparison in `tools/paper_backup_readiness.py`, shared by the
qualified delivery observer and its regression tests. It is a pure diagnostic
comparison, not financial mutation authority or a public JSON admission API.
Its caller must first authenticate the checkpoint and physical-capacity proof
with the canonical continuity reader, verify the native evidence row, and supply
current primary/account/runtime observations. The outer observer separately
enforces the exact native invocation, stable owner, tick age and host checks.

When a successful native scan could not refresh its checkpoint, accept the
alternative only if the independently authenticated checkpoint strictly advances
that verified prefix and exactly reaches the observed primary archive boundary
with its original archive-success timestamp. Require a fresh supplementary
observation, current account/epoch/postmaster/source/engine/capacity context and
the same complete base/timeline/range geometry. Stale, degraded, unauthenticated,
incomplete or merely asserted newer evidence refuses. A checkpoint still behind
the primary is a genuine pending condition, not grounds to alter its timestamp.

Preserve both documented integrity producer formats. The native maintenance
scan reports one complete sidecar pass. The runtime reports two passes for any
newly hashed objects and may report zero new hashes for unchanged objects within
its existing process-local 300-second reuse limit. A runtime full scrub hashes
every object twice; incremental/cache checks never renew that limit. Trust this
format only in the authenticated canonical proof from the admitted runtime;
do not create another proof cache or run a manual verifier to obtain green.
See [the existing proof reuse contract](backup-writer-admission-cost.md).

Keep the original false refresh flag and both verified WAL boundaries in the
acceptance record. A historical snapshot may qualify the comparison but cannot
pass the outer current-tick age check. The exact-view acknowledgement still
requires independent fresh readiness, an unchanged review subject/head and exact
notification set, a newly issued token, and the existing server transaction.

## Home-screen launch and foreground return

November 4 owner report: a home-screen launch can remain black for 7–10 seconds,
and foreground return can show refreshing for 4–5 seconds on both Wi-Fi and
mobile data. Current paired local/public reads took 1.1–1.5 seconds before HTML
headers, while static PWA resources took 3–21 milliseconds. The worker currently
awaits the complete network navigation response, so no document can paint while
status collection or connection establishment is pending. Existing resume tests
exercise an already loaded document; they do not cover that missing first paint.

Make an ordinary root document navigation return a small static, neutral launch
document before any database, worker or review read. The existing installed
worker also returns that same static document directly for same-origin GET root
navigations. Keep the manifest ID/start URL, all other routes and push behavior.
The launch document fetches the existing root HTML as a non-navigation request,
then installs it only after the same complete-document, original-clock and
finite-age checks used by ordinary refresh. Share that parser with refresh.
There is one request in flight and a finite abort bound; offline/failure stays
neutral with an explicit retry. Hidden/late responses cannot install current
authority. Neither the worker nor the launch document stores HTML, review tokens,
financial values or successful health in Cache Storage/local storage. The static
launch response is CONNECTING, not CURRENT; offline launch can return that static
200 document and subsequently show an offline notice. A no-JavaScript link uses
the explicit read-only `?document=1` server-rendered path.

A separate read-only miss/hit profile reproduced an unnecessary foreground cost:
with imports warm, unchanged canonical intent validation took 1.36 seconds and
the request took 2.52 seconds; its already validated display projection needed
0.035 seconds and the request took 1.09 seconds. The old memo discards that
immutable projection after every minute even if the physical row is unchanged.
Retain the small bounded LRU projection for that exact physical row version
instead. Every hit still reads database/system/postmaster/relation/tuple/full-XID
epoch/session/digest identity; configuration changes and monotonic-clock rollback
clear it. Changed, deleted, reinserted or restored rows force canonical validation,
including changes retaining a claimed digest. The entry/byte bounds remain.
Current generation, account, plan selection, opening intents, observations and
execution time are read afresh outside this memo. Their original timestamps and
all financial/evidence expiries stay unchanged. Execution/notification loaders
remain uncached. This removes repeated validation of unchanged immutable bytes;
it does not cache a complete operational result or extend authority.

Qualify held-network launch before the first document, foreground freshness,
offline/no fabricated green, single-flight/abort/hidden-response/parser guards,
the real worker and WebKit document path, plus idle reuse and every physical-row
invalidation with removed-guard falsifiers. A physical iPhone is not available
to this test harness; report that limit and measured browser results explicitly.

The owner explicitly authorizes a local panel-only overlay of pwa, app, render
and intent_memo after qualification, preserving the already installed DELL
preview and the signed base identity separately. Save exact original bytes and
metadata, restart only that panel, compare unchanged financial/other-role
witnesses, and refuse rollback over unknown concurrent bytes. A planned restart
retains the existing review/acknowledgement contract.

The old-worker migration regression additionally reproduced a stripped Fetch
Metadata path: its forwarded navigation retained `Accept: text/html` but omitted
Sec-Fetch-Mode/Dest. Recognize document destination, navigation mode, or an HTML
Accept request at the root. Bootstrap/ordinary current-document fetches keep
their normal `*/*` Accept and receive the full current response. The explicit
`?document=1` path always bypasses launch selection. This covers existing
installed workers before their update as well as older WebKit metadata support.


### Known submitted orders awaiting reconciliation (November 4)

The November4 opening cycle produced a clean, authorized execution result with
COMMANDS_IN_FLIGHT and moved EXECUTING to RECONCILING. Its DELL SELL2 later
filled and the same cycle reached SUCCEEDED with clean reconciliation335.
The panel nevertheless interpreted any nonempty failure_code as an active
cycle failure and any such transition detail as interrupted transport. The
failure_code field also contains nonterminal progress; its presence alone is
not sufficient to classify a failed transport.

Use one pure display predicate for the summary and transport-event projection.
Recognize only COMMANDS_IN_FLIGHT on a matching saved plan, with the producer's
explicit submission-authorized/attention-not-required booleans, RUNNING execution,
nonempty unique submitted keys, no refusal/deferred/restricted work, and matching
positive clean preflight/final reconciliation identities without unresolved or
foreign items. Require aware original cycle/open/execute/update/close clocks and
a next wake strictly after the update and no later than that original close.
This yields bounded RECONCILING progress, not an interrupted transport or a
completed cycle. Missing, contradictory or malformed evidence retains failure.

No failure-code-only or text-matching exception is admitted. UNKNOWN and cancel
uncertainty in the current command/trading-run and broker rows remain independent
required-current failures. No execution, schedule, financial authority, command,
plan, observation or immutable event is changed. The display predicate grants
neither green nor execution authority and cannot extend the original deadline.
Historical mirror verification and the durable review interval retain their
existing amber requirements. Existing false incidents stay in immutable history;
they are not silently erased or automatically acknowledged by this repair.


### Completed-day historical PAPER audits (November 4)

The existing producer already authenticates COMPLETED_WITH_HISTORY only after
proving the exact current day's clean completed plan, original sizing/fingerprint,
publication, account binding, current authority/leader and zero unresolved outcomes.
It retains the earlier informational mirror discrepancy and the current plan's
pending post-close stamp. The verifier is completing these observations normally.
Human health incorrectly recognizes the historical-audit scheduled state only
before execution; a positive completion is then mistaken for a new material
trading warning. Periodic owned checks hide that classification temporarily,
causing repeated REVIEW/RECOVERED changes and unstable ACK eligibility.

Extend only the human current-health projection for this existing typed completed
state. Keep the financial row amber/NOT_VERIFIED, the historical discrepancy,
original trial verdicts, immutable events and machine overall/operational status.
The tag alone is insufficient. Require local PAPER, a unique row set, no source
errors, fresh dated independent current capability rows, enabled/non-killed
control, current leader, authority, complete broker/account proof and the same
accepted closed-session feed/shadow context as the completed intent. Require the
canonical current trading_run for today, SUCCEEDED, original completion time,
all recorded commands FILLED (or no commands for a genuine no-change plan), and
current SUCCEEDED cycle/completion-step rows dated at the exact same completion.
An unfilled, UNKNOWN, cancelled, rejected, superseded, foreign-date or stale
current fact never acquires this allowance. Do not substitute an older-generation
completed_trading_run for a current cycle in this narrowly scoped repair.

Label the human card today's trading complete and keep the historical audit
visible in System details with explicit post-close verification caveats. It may
become green only through the existing explicit exact-view acknowledgement and
only while all current guards continue to pass. Bound human freshness by the
minimum original historical-row, completed-run, account, source and leader clocks;
never retime or extend any proof. Keep ordinary queued-check behavior and the
canonical verifier/owner/scheduler unchanged. No broker/provider calls, manual
verification, financial rewrite, automatic ACK or green override is introduced.
