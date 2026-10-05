# Installing the CI-certified single runtime

[Paper installation qualification](paper-installation-qualification.md) records
the real GO result, installation failures, corrections, local test boundaries,
and the remaining actual paper deployment evidence.

## Operator services are installation dependencies

Decision: 2026-10-05. Every installation mode starts the private panel and waits
for its database/schema readiness. If Web Push or the legacy alert webhook is
configured, start the independent dispatcher using the same pinned runtime and
wait for its health before releasing automation. Recheck both services before
writing a successful installation receipt, including after the final backup.
An unavailable configured sender is an installation failure, not an optional
omission. A deliberately unconfigured transport remains explicitly unavailable.
Do not start broker automation to obtain notification delivery, stop the sender
when financial activation fails, or grant the panel broker credentials.

Docker readiness alone does not supervise a stopped container. The durable
dispatcher heartbeat and the panel's operational verdict remain the independent
observations of absence, including while trading is disabled. Test submission
reports sender availability and a durable receipt; the browser checks that
receipt for push-service acceptance rather than claiming delivery from enqueue.
Transport acceptance cannot prove that iOS displayed a notification.

## Independent failure cleanup

Decision: 2026-10-04. After a deployment transition fails, first attempt the
durable emergency fence, then independently attempt to stop automation and
shadow. Failure to stop either service must not suppress the other stop attempt.
Report each unavailable cleanup boundary and preserve the original deployment
failure. Do not describe best-effort cleanup as confirmed fencing when the
database or Docker operation failed. Qualify the actual public installer class
with emergency-fence failure and each service-stop failure.

## Administrative identity on weekends and holidays

Decision: 2026-10-04. Installing a paper account must not depend on the wall
clock falling on a trading date. Administrative inspection and empty-account
binding use the XNYS session at or before the current New York calendar date
for their symbol-identity resolver. On a trading date this remains that date,
including before the open; on a weekend or exchange holiday it is the preceding
session. The broker account is still observed at the actual current time.

Keep the rolling reader's existing identity bound: a request beyond the
published close may use only the immediately following exchange session.
Do not extend stale publications, change time, infer a future listing, relax
signatures, or alter order scheduling to make installation pass. Ordinary
execution and recovery continue using their explicit plan/cycle sessions.
Apply the same administrative policy to inherited-account inspection,
empty-account inspection, and empty-account binding. Qualify all three CLI
owners with the real exchange calendar and real PostgreSQL rolling resolver,
including weekends, holidays, New York date boundaries, and refusal when the
publication is genuinely too old. Installation at any time does not permit
trading outside the execution contract's session window.

## Deployment backups and recurring maintenance

Decision: 2026-10-04. Pre-migration and final deployment base backups wait for
the existing canonical target lock for at most 3,660 seconds. This covers the
maintenance invocation's 3,600-second outer deadline and 60 seconds for process
cleanup and lock handoff. The wait covers the entire tick, not just its
2,100-second restore subprocess. Recurring
maintenance may hold that lock while it verifies a physical restore; normal
contention must not abort an otherwise valid installation. The installer
requests this wait explicitly. Ordinary backup and maintenance commands retain
their immediate contention refusal. Waiting neither terminates the owner nor
accepts its result as the installer's required fresh backup.

Use nonblocking flock attempts and one monotonic deadline, then verify exclusive
descriptor ownership before starting the child. Invalid wait requests, timeout,
target/ownership failure and backup failures remain refusals. Waiting cannot
renew or replace the deadline, change an inherited lock, or run two producers.
Qualify actual process contention, timeout, argument validation, inheritance,
and both installer backup phases.

## Qualification scope for the operational provider replacement

The 2026-10-04 local campaign also covers the Alpaca/OpenFIGI replacement.
Review and exercise the source transport, typed security classification,
classification age and restart reuse, raw/split price pairing, corporate
actions, normalized snapshot publication, formation and daily continuation.
Use real captured data for the cold acquisition and appliance run, and isolated
PostgreSQL tests with explicit provider/clock fixtures for deterministically
reproducing unavailable or malformed responses and next-session behavior.
A fixture result must not be described as a real-provider daily deployment.

Exercise the actual shadow worker entrypoint through publication, durable
formation, source failure, retry, next-session commit, and repeat/restart.
Assert that legacy Sharadar acquisition cannot be reached and no broker plan,
command or fill is created. Qualify the adjacent GO renewal/deadline, installer
fence/recovery, automation source-check and leader/retry paths separately.
The broker-capable deployment phase remains separate: simulator evidence and
shadow success do not establish actual paper account execution or unattended
trading. Record incomplete qualification explicitly before publication.

## Semantic restore after book formation

Decision: 2026-10-04. An empty or still-forming database does not exercise
rolling-origin verification. A formed rolling book requires its reviewed source,
configuration and initial-publication bindings as well as the actual runtime
commit and immutable image digest. The isolated semantic restore launcher must
forward exactly those five non-secret deployment facts, alongside the receipt
key and isolated restore database connection. It must not forward the primary
database URL, provider credentials, signing key, execution authorization or a
whole host environment. The validator still compares the retained checkpoint
with the actual source/runtime and configuration; absent or changed facts must
refuse, never fall back to trusting the restored payload alone.

Qualify the actual launcher argument/environment boundary and falsify a missing
or changed binding. A successful pre-formation restore is not evidence for a
formed book: exercise a complete physical restore and semantic validation after
the real book has earned its attestation, using the exact immutable runtime.

## Bounded shadow health after full formation

Decision: 2026-10-04. The real full-universe appliance earned a prospective
SHADOW_GO/VERIFIED decision but its five-second container health probes could
not finish repeated retained-book authentication. Killing a probe parent also
left its dependency child readers behind. Health must not reproduce the book.

After the canonical worker fully verifies a rolling decision, it may publish a
small, authenticated health projection bound to that exact runtime/config,
database identity, authority record, and fresh PostgreSQL row versions of the
retained behavioral and publication inventory. The projection is health-only:
GO, strategy status, execution admission and broker guards retain full financial
verification and never consume it. Probes reread the cheap inventory and causal
session boundary; missing, malformed, stale or changed projections cannot report
an attested healthy book. A fresh database without a retained origin continues
through the existing reconstruction/liveness checks. A worker projection write
failure cannot change or acknowledge a financial result.

Use an atomic bounded file and publication-receipt HMAC. Do not cache verdicts
across row-version/config/database changes or claim that a health projection is
financial authority. Qualify tampering, changed rows/publication/config, causal
lag, restart, projection I/O failure and a large retained origin without decoding
its payload in the probe. Linux dependency observer children must install a
parent-death SIGKILL before opening dependencies, with a parent identity race
check; killing a Docker probe parent cannot leave readers running indefinitely.
Use Docker's init process for the long-running shadow, automation and alert
supervisors so dead orphan observers are reaped. Do not add a supervisor-wide
waitpid(-1) handler: it could consume a financial worker outcome owned by Popen.
Test parent death and orphan reaping through the actual container configuration.
Preserve the formed book and incident evidence,
then repeat exact-image local GO and persistent shadow qualification before PR.

## Cold dual installation and the canonical writer lock

Decision: 2026-10-04. Cold formation and administrative/execution certificate
installation acquire the same exclusive Sentinel writer lock. Complete strict
empty-account enrollment and observation authority installation while all
publishers remain quiesced and automation remains disabled and killed. Then
start the broker-free shadow, wait for its exact signed decision-close
attestation, and prepare and reconcile the paper plan before releasing paper
automation. Installing authority is not trading activation. Never solve this
startup race by removing the lock or retrying an unknown certificate mutation.
An enrollment/authority failure cannot start shadow or release automation.
## Heartbeat observation availability during formation

Decision: 2026-10-04. The real appliance repeated a one-second filesystem
heartbeat observation timeout while the canonical formation worker remained
alive. A supervisor heartbeat is a liveness projection, not the durable
acknowledgement of the financial worker. An unavailable heartbeat write must
leave health stale and retry its bounded observation without abandoning a
supervised worker or guessing its outcome. Coalesce the warning until recovery.
The original monotonic worker deadline continues through observation failures;
only an observed worker result or observed supervised signal termination can
acknowledge its durable pending attempt. A terminal worker refusal still latches
with heartbeat storage unavailable. Arming, active-worker proof and durable
acknowledgement failures retain their existing fences. Startup with an
unacknowledged pending attempt remains refused. No broker authority changes.
Qualify transient recovery, persistent filesystem stalls, deadline termination,
terminal refusal and restart with actual child processes. Compare automation's
existing bounded observation-loss deadline behavior and execution recovery too.
## Local shadow qualification before publication

Decision: 2026-10-04. Qualify deployment changes locally before opening the
fix PR. Use a clean feature branch and its exact single runtime image, real
Alpaca/OpenFIGI inputs, the ordinary durable backup producer and runtime
guards, canonical book formation, post-commit shadow verification, and restart
verification. Broker trading remains disabled and killed. Preserve the prior
database and incident markers before a fresh diagnostic installation; never
discard historical research data or import simulated decisions as proof.

This is explicitly unpublished operational qualification, not CI certification
or signed deployment admission. It must not issue account-binding/execution
certificates, enable paper automation, modify the production certificate gates,
or claim that a local PASS is a certified deployment. Exercise backup renewal
while formation is active and preserve actual failures, fixes, image/commit
identity, checkpoint progress and the boundaries left untested. Continue local
fixes and targeted regressions until the complete shadow path passes; then
publish one validated PR. Broker enrollment and activation follow separately
after the resulting release is certified.

The local cold qualification preserves the previous failed appliance database
under a distinct retained name before creating an empty `sentinel` database.
It uses the ordinary Compose project, selected immutable local image ID and
backup scripts, avoiding project-name or certificate bypasses. Existing keys,
research archives and backup generations remain untouched. The old backup timer
is paused during this explicit transition, then recurring maintenance uses the
same clean checkout and image as the diagnostic shadow. Local reviewed facts
are bound to a diagnostic report marked `LOCAL_ONLY`, never a forged GO ZIP.
The existing certified installation remains reproducible from its clean checkout;
the diagnostic installation cannot be admitted to paper execution.

## Archive metadata during backup renewal

Decision: 2026-10-04. PostgreSQL's `pg_stat_archiver.last_archived_wal`
reports the latest successfully archived object, which can be a backup-history
or timeline-history file rather than a WAL segment. A canonical PostgreSQL
metadata name is a temporary restore-frontier observation: refuse financial
mutation with the existing retryable backup-unavailable type until an actual
WAL segment is reported. It grants no restore-chain or mutation authority and
must not be parsed as a segment, truncated into a segment name, or silently
replaced by an older successful proof. Existing recurring backup maintenance
publishes its recovery marker and advances archival normally.

Malformed object names, invalid timeline/segment geometry, missing selection,
checksum contradictions, symlinks and hardlinks retain their existing integrity
refusals. Valid WAL segments still require the complete bounded, cluster-bound
restore-chain proof. Qualify this distinction at the runtime guard, common
writer boundaries, shadow worker and automation dependency classifier, including
recovery and negative falsifiers. Backup files and their checksums are preserved.

The host status checkpoint uses the same host-Python-compatible name classifier.
For valid history metadata it rereads the complete archive observation for at
most 30 one-second waits. A segment proceeds through the existing full proof;
expiry returns `WAL_ARCHIVE_FRONTIER_PENDING`, without creating another base
or treating metadata as corruption. Invalid metadata still fails immediately.

## Fresh archiver observations inside transactions

Decision: 2026-10-04. Real PostgreSQL 16 qualification reproduced cached
`pg_stat_archiver` values in a held transaction after another connection saw
archival advance. Durability checks and the stale-target probe must discard
that backend's statistics snapshot before each archiver read. Use
`pg_stat_clear_snapshot()`, not a statistics reset, transaction commit, rollback,
or isolation change. This prevents a cached success from hiding a newer failure
and a stale frontier from contradicting a newly selected base. Filesystem and
business publication proofs retain their existing pinning and complete checks.
Qualify concurrent advancement and failure as well as the real PostgreSQL cache
behavior. This is durability observation only; strategy and broker rules do not
change.

## Reviewed command environments and active shadow workers

Decision: 2026-10-04. The real certified cold installation exposed two adapter
failures after GO passed. Every reviewed read-only subprocess must receive its
own exact environment, including the selected image, reviewed shadow bindings
and removal of broker credentials. The installer runner forwards that environment
and the caller's unchecked-result contract without mutating its shared environment.
The preflight and the post-fence recheck use the same adapter.

The durable shadow pending marker means an outcome has not been acknowledged.
It remains mandatory before spawn, and any retained pending marker at supervisor
startup still prevents a new worker. During a live attempt it is not a critical
latch. An ephemeral process proof links the pending attempt nonce to the exact
supervisor and its child, using Linux boot identity, PID, process start ticks and
parent identity. A fresh heartbeat and an unexpired worker deadline are also
required. A critical latch always wins; absent, malformed, abandoned or stale
proof never turns an unacknowledged outcome green. The proof cannot acknowledge
work, remove a durable guard or authorize trading.

Container health admits a proven active worker while it forms or reconstructs
the book; structural refusals remain red. Financial readiness remains a separate
gate: the installer must wait for the exact verified decision-close attestation
before issuing execution authority, and automation retains its existing admission
checks. Without a proven active worker, reconstruction remains unhealthy. Worker
outcomes, bounded semantic retries, signal termination and restart fencing retain
their existing contracts. No strategy, broker state or economic logic changes.

Decision: 2026-10-03. This completes the existing single-runtime contract from
`sentinel-handoff/ci-certified-runtime/PR-C.md` and `PR-D.md` at the reviewed
paper installer. A successful real GO exposed legacy installer checks that
required a distinct candidate image and attempted another image publication.

Normal GO records the same immutable local image ID for its candidate and
runtime roles. Reviewed installation accepts that alias, inspects the image
once, and still requires the exact clean main commit, OCI revision, runtime
source identity, reviewed publication, current account and all admission gates.
The existing explicit local-full path may retain a distinct test lens layered
on the exact runtime; its prefix-layer verification remains mandatory.
Auxiliary image aliases and duplicate inspection records remain refusals.

The reviewed preparation record may include the producer's last 512 sanitized
progress events. The installer validates them with the same bounded progress
parser used by GO. They remain diagnostics; they cannot replace a preparation
PASS, a source proof or any admission gate. Unknown fields and malformed events
remain refusals.

The single-runtime path independently verifies the signed GitHub certification
for current main before entering deployment. It rechecks certification when
selecting the image, binds the registry digest to the reviewed local image ID,
and reuses that immutable registry reference. It never builds, reruns the full
software suite, pushes a replacement image, or treats a local JSON PASS as CI
certification. The legacy test-digest certificate field names the same runtime
digest for this path.

Offline issuer tools are taken from the same verified clean checkout and mounted
read-only at `/app/tools` into this runtime for the issuer invocation only.
Signing retains `--network none`, the existing read-only private-key mount and
the private authority-output mount. The offline tool runs as the host installer
UID/GID so it can read the private key and write private attempt directories
without granting other users access. No second deployable image or persistent
tooling service is introduced. Provider and broker credentials are absent from
the signer. The production runtime modules continue to come from the certified
image, not a source-directory overlay.

This repairs installer conformance; it changes no strategy, account binding,
trust root, signed-certificate requirement, broker endpoint, backup requirement,
fencing or reconciliation rule. A local parser/installer regression test grants
no authority to activate unmerged code. Production activation still waits for
the fixed release's normal merge certification and a matching GO bundle.

## Plain-language casino dashboard

Decision: 2026-10-04, requested by the operator. Present the current simulated
strategy portfolio separately from the Alpaca paper account. Reviewed shadow
mode must use the same independently verified shadow reader as dual mode, but
omit paper reconciliation rather than reading obsolete trial certificates. A
missing, unreadable or stale shadow remains explicitly unverified; presentation
never changes a verdict or uses the health projection as financial authority.

Keep stable internal row keys and raw financial values. A pure presentation
layer supplies familiar labels, descriptions of what each fact means and an
explicit warning when it is not current. Retain original technical values,
reasons and timestamps in expandable details. Explain simulated book formation,
market data and paper account differences on the page, including shadow-only
operation and intentionally disabled paper trading. Notification removal means
disabling that device's subscription, not deleting a received message.

Use a dark casino lounge with gold marquee lights, decorative slot reels,
moving chips and original vector hostess silhouettes. Decorations are
noninteractive, hidden from accessibility APIs and independent of financial
numbers. Animate only CSS transforms/opacity, stop animations for reduced-motion
preferences and keep contrasting status text, legible mobile cards and touch
targets. Serve all art locally. No new trade controls, provider calls, execution
authority or external asset dependency. Qualify both mode selection and truthful
failure/staleness presentation, then inspect the actual desktop and phone views.

The document generation time is sampled after the bounded status reads finish,
not before a potentially slow financial verification. This prevents an old
render timestamp from making every delivered page immediately expire and
reload. Individual fact timestamps and causal validity boundaries are retained
unchanged and evaluated against completion time, so slow reads cannot make an
old healthy fact current. Explicit test clocks remain deterministic.

The read-only semantic restore uses a dedicated 16 MiB temporary directory at
`/tmp/sentinel-restore` and sets `TMPDIR` to that path. Mounting tmpfs over all of
`/tmp` hides the image's baked `/tmp/req/requirements.lock` and changes its
computational identity. Keep that immutable build metadata visible; never
compensate by ignoring the dependency-lock hash or weakening runtime comparison.
The database password, like the receipt key, is forwarded by environment name
and never included in Docker command arguments.

## Installation timing and a fenced source-final wait

Decision: 2026-10-05. A cold installation must not require the operator to
start more than 4h52m30s before the next open. That fixed reserve belongs to the
GO database processing benchmark. It is not an elapsed installation deadline.
The installer may bind an independently verified source-final publication while
its actual following XNYS open is still future. Recheck actual time after
parity and publication verification, before paper-plan preparation and immediately
before releasing the kill switch. Losing that window fences activation; never
backdate evidence, replay a missed open or extend the execution window.

Before the source-final boundary or after a missed open, keep installation
staged with automation disabled and killed. Start and verify the private panel
and configured notification dispatcher before this wait. Financial publishers
remain quiesced until publication and account authority are bound.

When a new source-final session becomes eligible, refresh a behind rolling
publication through the same canonical Alpaca/OpenFIGI acquisition and durable
backup guards, with no broker mutations and no Sharadar fallback. Reuse retained
provider parts and permit one successful refresh per target; polling current
ready data does not reacquire it. Then re-earn exact parity, readiness, image,
source/config, account and lineage checks before binding. The original reviewed
bundle remains unchanged, and the later binding receipt identifies the new
publication. A changed target during refresh or binding returns to the same
bounded wait; corruption and non-temporal failures refuse. One monotonic wait
budget covers the entire attempt, including retries and backup renewal.

Installation may stage at any time; active paper operation still requires an
actual prospective attested decision and all existing execution/reconciliation
gates. A slow formation that misses its open fails closed and preserves its
state for explicit recovery. No local test or staged receipt is trading authority.
Qualify the former 4h52 boundary, actual-open equality, post-close/source-final
lag, weekends/holidays, target changes, zero repeated acquisition on polling,
wait-budget exhaustion, loss of fencing and expiry before kill release.
