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
The single request, 15-second timeout and five-second retry bound remain.

Qualification executes the rendered JavaScript over successive healthy document
replacements, slow responses, original expiry during a read, failed responses
and overlapping browser wakeups. Restoring the old premature invalidation and
removing failure or age withdrawal must fail the behavioral acceptance checks.
The executable admission catalog pins the exact installed renderer and reviewed
replacement, alongside historical renderer bytes independently retained in the
source-history manifests. No other presentation change is implicitly admitted.

## Idle discovery and maintenance observations

Decision: 2026-10-11. A newly activated control generation can legitimately
have no daily cycle while its current leader waits for a new eligible decision.
The cycle summary must carry the same bounded current-holder discovery evidence
as its individual steps. It remains amber, never green or a claim of completed
execution. Missing, expired, foreign-holder or failed discovery evidence remains
red when automation is enabled. Historical blocked cycles and unacknowledged
incidents remain visible; this repair does not replay them or acknowledge them.

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
