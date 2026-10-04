# Installing the CI-certified single runtime

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
