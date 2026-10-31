# Current dashboard evidence and idle leadership

Decision: 2026-10-10. This is a repair to the operator and scheduler boundaries,
not financial authority or a second book. The installed system demonstrated an
expired leader lease with a fresh WAITING instance, and the panel displayed an
unknown account/runtime even though the canonical binding and signed runtime
agreed.

## Lease renewal and financial writer ownership

Renewal of an existing, unexpired lease owned by the same instance uses the
ordinary conditional heartbeat fence. It does not take the financial writer
lock. Control must still be enabled and not killed, and holder, token, control
generation and PostgreSQL expiry must still agree at the renewal statement.
Initial acquisition, expired-lease reacquisition and takeover continue to require
the exclusive financial writer lock. A failed renewal is never a resurrection.
Cycle creation and every financial mutation retain their own writer/fence checks.
Thus a slow shadow writer can delay financial work without starving the live
scheduler's lease; an unavailable, killed or replaced owner remains refused.

Qualification holds a real PostgreSQL writer lock longer than a short lease,
renews the original owner repeatedly, and checks continuous database-time
leadership. It also proves that competitors, expired owners, control-generation
changes and kills cannot use this renewal path to acquire authority. An idle
scheduler must retain its lease while returning a bounded financial-writer wait.

## Canonical account and signed runtime projection

The panel resolves the account only from the canonical SENTINEL_OWNED binding.
An absent, foreign or unreadable binding cannot become a matched account.
Runtime identity comes from the signed certificate's recognized claim shape:
standing PAPER_OBSERVATION_ONLY certificates bind Git/image in `bindings`;
historical execution certificates bind them in `deployment_artifacts`.
Environment variables remain observations, never the reviewed identity. Missing
or contradictory claims, revocation, inactive lifecycle and mismatches stay red.

## Financial observations and the canonical book

This supersedes the one-use presentation policy in `anytime-paper-activation.md`:
a second HTTP request is not evidence that a completed verification failed.
The same completed observation may be displayed during its existing 30-second
validity only, with its original observation time and exact configuration key.
Requests never refresh that proof's timestamp or extend its expiry.
Every request checks a bounded read-only key of the retained book row versions,
current publication, rollout and, for dual mode, control generation, binding,
current plan/cycle, command/observation frontier, active certificate and
revocations. Volatile service heartbeats are excluded. The worker must match
that key before and after full verification. A changed or unreadable key
withdraws the result immediately, including within its 30-second validity.
The large retained state is not decoded or hashed by this invalidation query:
PostgreSQL's `xmin` and `ctid`, together with cursor/session identity, identify
its row version. Any UPDATE, replacement or deletion invalidates the proof;
vacuum movement may conservatively invalidate it too. These tokens never prove
financial validity. The finite full reader still authenticates the complete
state and history before any positive observation is published. This avoids
repeating multi-gigabyte JSON work in the HTTP request's small read budget.

After expiry, one owned finite observer performs the complete check. While its
original five-minute wall-clock budget remains live, report CHECK IN PROGRESS
as amber, with retained numbers explicitly LAST KNOWN and not current. This is
a bounded presentation query, not a positive verification or trading permission.
A failed or negative completed check stays red during subsequent attempts until
a complete new check succeeds. Malformed, future-dated, timed-out, expired-worker
and changed-configuration evidence never inherits verified styling. An observer
may not renew its own attempt deadline or overlap another observer. Trading
continues to use its canonical complete financial readers.

An authenticated, unexpired failed PAPER receipt may retain only its negative
historical status when the input revision changes and the independent verifier
still has a fresh bounded ownership heartbeat. Show `LAST CHECK FAILED ·
RECHECKING`, the original failure and original observation/expiry; do not turn
that expected refresh into an opaque `ValueError`. This is not a current-subject
financial proof. Remove retained account, plan, order, trading-run and typed
readiness payloads. A successful old-subject receipt still loses positive
styling immediately. Missing/dead ownership, expired/tampered evidence, producer
errors and unknown results keep their existing strict unavailable behavior.

For the owner-requested local presentation repair, qualify and preview the HTTP
consumer separately from the financial verifier and trading workers. A local
presentation image may layer the exact qualified presentation bytes and matching
structural source pins over the installed signed foundation. Retain its actual
commit/image, foundation and qualification in operator evidence. The financial
runtime identity and verifier's evidence subjects remain unchanged. Preview only
read-only GETs on a loopback port with the panel's existing broker-free environment.
Replace only the HTTP panel through an operation-private image-selector overlay,
preserving its configuration, mounts, ports and dependencies. Do not recreate
financial roles, change control generation, issue authority, replay a plan or run
backup/restore work. A failed panel startup or read check restores only the prior
panel image; it grants no financial recovery permission.

Decision, 2026-10-30, before implementation: the unchanged installed foundation
for a presentation-only component may also be a verified backed local
application image whose immutable completed handoff, exact build and qualified
source evidence lead back to the signed release. Require that complete ancestry
and the actual installed foundation image identity; a local tag or an
uncompleted operation is insufficient. Record the component's separate source,
file hashes, qualification and resulting image without presenting it as a new
signed financial release. Preserve the foundation's runtime identity and baked
source revision, verifier subjects, private environment, current native Compose
graph and image selectors. Replace only the HTTP panel, verify all financial
container identities remain unchanged, and restore only the immediately prior
panel image on failure. This admits no financial service roll, new GO,
activation, PostgreSQL transition, backup/restore work or account mutation.

Reviewed dual mode must project its actual immutable shadow state and current
paper intent. A missing legacy catchup cursor does not prove that this book is
absent. The projection must use existing canonical readers and their lineage
checks, not form a new book, infer holdings from broker positions, or relax
plan/controller/rollout agreement. Book, terminal and exposure rows come from
the same fully verified shadow result, joined to the sole current plan and
durable rollout. The legacy catchup cursor remains the legacy-mode source;
reviewed shadow/dual modes do not consult it as an alternative book. Broker
observations remain a separate durable execution projection. All compact rows
fit the observer's finite allocation boundary; no complete book crosses its pipe.
The verified result uses the canonical SessionState envelope version declared
by `sentinel.core.session`, currently version 4. The presentation adapter checks
that exact version. Legacy catchup projection keeps its explicit version-3
contract; neither path accepts an arbitrary version or an unverified state.

Qualification joins repeated HTTP reads, original proof expiry, negative
verification, configuration changes, a real spawned observer deadline and
canonical book/plan/rollout disagreements. Exact old source manifests, including
the installed release, must pass book-preserving executable admission. Broken
expiry, negative-result, lease and source-closure guards require behavioral
falsifiers before publication.

Historical unacknowledged incidents remain visible. Expected next-session waits
remain amber and cannot claim order transport or a completed daily cycle. No
notification acknowledgement, financial reset or runtime workaround is part of
this repair. The exact new software must pass protected certification and the
supported book-preserving upgrade before it is installed.

The later human-health policy in `dashboard-plan-first.md` separates healthy
autonomous scheduling from those unchanged raw financial verdicts. An eligible
historical-only audit record may remain amber in System details while complete
current evidence makes the health header green; it is not an unacknowledged
current incident, a resolved historical discrepancy or trading permission.

## Stable refresh and explicit checking states

Decision: 2026-10-11. The installed full verification takes longer than the
former 30-second presentation lifetime. A successful check now has a maximum
ten-minute lifetime measured from its original completion. After five minutes,
one finite background check starts while the previous successful observation
remains valid. This leaves the original five-minute worker budget within the
remaining proof lifetime. Reads never move either deadline. Every HTTP request
still reads the exact compact evidence key; any changed or unreadable key
withdraws the old result immediately. Control, leadership, signed authority and
other current operational rows continue to be read independently on each request.
This lifetime is display evidence only and cannot authorize an order.

If evidence changes while a previous-key check is running, the panel reports
CHECK IN PROGRESS with an explicit explanation that it is waiting for the old
check to finish before checking the new evidence. It retains no old verified
numbers for the new key, starts no overlapping worker, and uses the old worker's
original deadline. A bounded active observer supplies explicit recovery evidence
to the shared color policy, so both HTML and JSON report amber before that
deadline. A completed error, negative verification, malformed output, unreadable
identity or exhausted worker remains red; a refresh error immediately withdraws
an otherwise unexpired positive result. Only a complete successful new check can
clear a known failure. Clock rollback and future-dated results cannot renew proof.
While this bounded check is active, absent metrics say UNAVAILABLE in amber;
retained metrics say LAST KNOWN in amber. Neither claims a verified number.
A fully observed ordinary PAPER wait keeps the producer's amber classification
instead of being reclassified as a failed required dependency. Positive completed
rows remain required-current; original expiry and changed-key withdrawal apply
to the whole completed observation.

The full retained-data observer exceeded the old panel's 512 MiB ceiling in an
isolated exact-reader measurement. The reviewed panel budget is 1 GiB with the
same half CPU and single HTTP worker. Its single finite financial observer and
request admission remain bounded; qualification measures peak memory with the
actual retained data and complete Reader/JSON/HTML composition at this ceiling.
This is a deployment resource correction, not permission to grow without limit.

Qualification must compose the actual Reader, Panel, JSON and HTML projections;
checking only the raw row's WARN status missed the installed false-red defect.
Exercise repeated refreshes over several complete lifetimes, slow verification,
key changes during work, observer failures, original expiry and bounded ownership.
The source-admission catalog pins the exact changed presentation adapter and its
installed predecessor; upgrade qualification must preserve the canonical book.

The worker serializes dataclass rows, including nested recovery evidence. The
parent reconstructs and validates that evidence before either operator surface
consumes it. Malformed clocks, flags or recovery bounds are a failed observation,
never a page-rendering exception or an implicitly active recovery.

The browser's ordinary 30-second refresh starts a background request without
withdrawing a still-current document's original 45-second validity. It does not
reset that timestamp, extend its lifetime, or restore a withdrawn positive state.
A rejected, malformed, non-current or timed-out response withdraws current
styling immediately and retains the visible values as LAST KNOWN. Original age
expiry also withdraws styling while a request is pending. Only a complete fresh
server document can replace it. Offline events, return from a background tab and
restoration from the browser's page cache still withdraw styling immediately.
The bounded resume presentation below supersedes the red colour used for that
withdrawal. The single request, 15-second timeout and five-second retry remain.

Qualification executes the rendered JavaScript over successive healthy document
replacements, slow responses, original expiry during a read, failed responses
and overlapping browser wakeups. Restoring the old premature invalidation and
removing failure or age withdrawal must fail the behavioral acceptance checks.
The executable admission catalog pins the exact installed renderer and reviewed
replacement, alongside historical renderer bytes independently retained in the
source-history manifests. No other presentation change is implicitly admitted.

### App resume is a bounded refresh, not a newly observed system failure

Decision, 2026-10-16, before implementation. Returning to the installed iPhone
app currently calls `invalidate(true)` immediately. This paints every reopening
red before its first network answer, although the current backend is healthy.
The existing tests explicitly required this misleading presentation.

Withdraw cached positive styling when an already-visible page is backgrounded.
On return, page-cache restoration or an initial explicitly LAST_KNOWN document,
show amber **Refreshing status**, with saved values explicitly last known. Start
one fixed 15-second foreground refresh budget; overlapping lifecycle events,
retries and repeated hiding/showing cannot restart it. A fresh complete server
document is the only way to earn current styling. The original generation time,
row clocks, 45-second document validity and every server/execution gate remain
unchanged. This foreground budget describes a connection attempt, not current
financial evidence. No broker call, new polling loop or backup is introduced.

Known failed/unknown server verdicts, offline state, malformed/future clocks or
invalid budgets remain red immediately. Malformed/non-current evidence marked
CURRENT also fails immediately. A busy/LAST_KNOWN response or network delay may
remain amber only until the original fixed foreground deadline; exhaustion is
sticky red until a fresh server document arrives. Ordinary visible-page expiry
retains its existing immediate withdrawal. Hidden timer callbacks must not race
the foreground event and invent a system failure before the connection attempt.

Qualify the actual renderer script for suspension beyond document expiry,
timer-before-visibility ordering, successful restoration, repeated wakeups,
busy/network timeout, deadline exhaustion, offline and known failures. Exercise
the rendered page in iPhone WebKit and Chromium, preserve detail expansion and
scroll, and falsify both the neutral-resume and non-renewable deadline guards.
Pin only the exact reviewed renderer successor through the existing shadow UI
admission profile, preserving all predecessors and the original book.

## Idle discovery and maintenance observations

Decision: 2026-10-11. A newly activated control generation can legitimately
have no daily cycle while its current leader waits for a new eligible decision.
The cycle summary must carry the same bounded current-holder discovery evidence
as its individual steps. It remains amber, never green or a claim of completed
execution. Missing, expired, foreign-holder or failed discovery evidence remains
red when automation is enabled. Historical blocked cycles and unacknowledged
incidents remain visible; this repair does not replay them or acknowledge them.

Decision: 2026-10-11. A scheduled poll becoming due is a normal transition, not
evidence of a failed worker. The same current-holder `WAITING` observation may
remain amber while that poll runs. Keep its original scheduled wake visible,
including when it is in the past. Bound this observation by the earlier of the
current lease expiry and 30 seconds after the durable instance heartbeat. A
renewed lease cannot extend the instance deadline; only a new durable instance
observation can establish a new interval. Reject wakes outside that heartbeat's
30-second neighborhood, invalid clocks, holder changes, errors and actual daily
cycles. Never replace the durable wake or heartbeat with the reader's clock.
Qualification must cross the due instant, delayed result registration, repeated
lease renewal without instance progress, and the exact exhaustion boundary in
both JSON and HTML. The complete preceding certified source closure must remain
admitted without reformation, source acquisition or changes to book records.

Decision: 2026-10-11. A complete, well-formed observation can verify the shadow
and book while separately reporting a PAPER reconciliation failure or unreadable
PAPER result. That PAPER problem must remain red, but cannot classify the
independent shadow check as failed. Only the producer's explicitly scoped PAPER
source errors may accompany this mixed result; an unscoped error remains a
failed observation. When the proof expires after an idle browser interval,
the next finite verification shows the independent rows as CHECK IN PROGRESS;
the known PAPER failure remains visible as LAST KNOWN with its original clock.
No positive proof is extended past its original validity. A failed observer,
malformed result, unscoped source error or failed shadow/book
verification still withdraws current proof and stays red during retries. An
evidence-key change discards retained values and failures. Qualification must
exercise mixed shadow-success/PAPER-failure through idle expiry, slow refresh,
successful replacement, failed replacement and finite timeout on JSON and HTML.

Normal maintenance already verifies the selected base and its complete retained
WAL chain. Publish that successful exact-base observation as append-only
RUNTIME_CHAIN evidence before reporting a healthy tick. Its proof names the
selected cluster, base, interval, marker and actual checksum scrub. A malformed
or contradictory report or failed evidence write refuses the tick. This makes
backup visibility independent of whether an execution callback happens to run.
The status verifier itself remains read-only; the existing maintenance owner
publishes the compact observation. No extra base, restore, order or financial
control mutation is introduced. Each successful tick appends at most one small
operational row; the original observation time is never rewritten.

Qualification must compose idle discovery through actual JSON and HTML, prove
deadline and owner withdrawal, and exercise both maintenance paths (reuse and
renewal) through proof publication. An installed-base fixture must reproduce the
old missing-chain projection and verify the new exact proof with the same panel
row policy. Failed verification/publication must never be reported healthy.
