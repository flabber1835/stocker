# Autonomous operation remediation and qualification

Decision: 2026-10-16, before implementation. The owner requested implementation
and qualification of the repository review findings and optimizations. This
decision preserves the independent canonical Wealth Core book, Sentinel's
exposure-only role, immutable published input history and the execution membrane.
The implementation baseline is `118b7c15249e47bd7ea79a23ecbc58b6dc947741`.

## Recovery classification

An observation boundary may wrap a database or writer-contention failure while
adding context. The worker must inspect causes through the explicitly owned
`ShadowObservationRefused` and `ShadowServiceRetry` wrappers. It must stop at
other exception types and must never turn an explicit integrity, authority or
configuration refusal into availability merely because it has an older
dependency failure as its cause. Connection loss, transaction retry and bounded
contention roll back and retry from the authenticated durable cursor. A lost
commit response does not authorize assuming rollback or advancing twice.

## Accounting and storage

[Accounting and storage remediation](autonomy-accounting-storage.md) defines
conversion ownership, compact candidate inputs and authenticated physical ledger
storage. Logical state, input and transition authentication remain independent
of compression and content-addressed physical representation. Old observations
remain readable; immutable history is not silently rewritten or removed.

## Execution and source recovery

[Execution remediation](autonomy-execution-remediation.md) defines current
instrument continuity, conservative available funding, native fill amounts and
bounded historical verification.
[Feed remediation](autonomy-feed-remediation.md) defines action coverage,
foreground retry, candidate history and source-storage retention changes.
Optimizations must preserve corrections, source observation clocks, identity,
pinning and exact command recovery. A shorter query is not evidence of parity.

## Live account ownership and activation

[Live trading readiness](live-trading-readiness.md) records the owner decisions,
implemented preparation and the native acceptance evidence still required.

The owner confirmed that Alpaca owns actual cash, positions, fills and account
activity, while the canonical model continues to own intended holdings and
Sentinel owns exposure. This applies in both environments. Paper retains its
existing independent shadow and paper account. Live preparation must not create
a second strategy book or import broker outcomes into strategy/controller state.

One exact normalized Alpaca trading endpoint determines PAPER versus LIVE;
unknown origins and credential-bearing/path/query/fragment endpoints refuse.
The existing paper configuration guard delegates to this same parser. It keeps
its paper-only mandate while closing permissive alternate ports and URL suffixes.
Environment and exact account identity must be part of authority and recovery
bindings. An endpoint edit cannot transfer paper authority to live money.

Purchases use settled, unreserved funds and conservative costs. Insufficient
funds cause a durable scoped deferral. A later-session purchase revalidates the
newest canonical intent and current execution window; it never blindly replays
stale quantities. No borrowing or synthetic broker cash is introduced.

The existing paper-only transport contract remains enforced until a separately
reviewed live authority contract and supported native account-event/recovery
capabilities pass their qualification. Implementing preparatory code, simulated
tests, or a readiness report does not issue live authority. This task authorizes
read-only provider qualification, isolated simulation and code changes; no live
orders, migration of the installed financial book or production activation.

## Qualification and delivery

[Qualification results](autonomy-qualification-results.md) records exact images,
test selections, measured resources, provider observations and open gates.

Each repaired behavior needs an executable regression that fails on the old
implementation, plus directly relevant tests. New guards need falsifiers.
Storage changes need legacy/new round trips, tamper and missing-object refusals,
canonical hash/transition/restart parity and measured size/resource evidence.
Retention needs populated PostgreSQL pinning, rollback and concurrency checks.

Real-provider GO changes must pass the documented isolated GET-only Alpaca /
OpenFIGI acquisition, verified backup/renewal, formation, restart/parity and
financial readiness run before publication. Evidence identifies exact source,
image, clocks, database, provider inputs and untested boundaries. Protected CI
and signed publication remain later release gates; local tests cannot issue
their verdicts or certify NAS/live operation.

The completion ledger must distinguish implemented and tested work, provider
qualification, protected CI, deployment qualification and live activation.
Historical research evidence and independent test oracles are retained. Git
delivery is a feature branch and pull request targeting `main`, without merge.

### Local functional environment

The root checkout's NAS deployment template does not name the active local
installation's target. Read-only Compose discovery identified the active
installation at `/home/bron/stocker-local-paper-20261016-118b7c15`, with the
existing operator-attested backup target
`/home/bron/sentinel-local-backup-20261003`. The latter is on Ubuntu's local
virtual disk. Its physical independence and NAS durability are not established.

Local functional qualification may use a fresh private child of that existing
configured target, preserving its operator attestation as an input and running
the ordinary target, ownership, marker and restore checks. It must not manufacture
a new independent-media claim, use the installed database or reuse its backup
namespace. Every Compose invocation and helper must name the private project.
Run genuine physical backups, schema-guarded preparation, formation, durable
book restart/parity and full semantic restore through their existing producers.
Keep signed certification, deployment admission, physical independence, NAS
capacity and live authority explicitly unproven. No backup policy is relaxed.

### Private harness filesystem identity

The immutable runtime retains its dependency lock at
`/tmp/req/requirements.lock`; the exact environment identity includes that
file's digest. Production Compose and the production semantic restore launcher
both leave this baked path visible. A private qualification harness must preserve
the same visibility. For a read-only root filesystem, mount only a dedicated
writable temporary subdirectory and set `TMPDIR` to it. Do not mask all `/tmp`.

The first two private attempts masked all `/tmp` in their ordinary CLI workers
but not in the restore worker. The final attempt captured an exact identity
refusal, without an OOM event. Verify the two filesystem identities directly
before applying the harness correction. Keep these failed attempts as failures.
Run a new complete, bounded cold qualification with the corrected filesystem
profile and newly computed native identity. Do not change the production identity
guard, copy a new identity onto an existing book, edit a checkpoint/admission or
raise resource limits to turn the refusal into a pass.

## Retained runtime compatibility

The forward-cash v2 economic migration remains its own explicit strategy
transition. A previously admitted v1 intermediate checkpoint may remain the
retained book only when its original HMAC-bound admission names the exact
retained v1 migration descriptor, origin, process, account-independent model
identity and checkpoint. The current process still needs a new v2 admission;
an old admission never authorizes new economics or an unauthenticated book.
Source compatibility also retains the independently pinned v1 descriptor's exact
transitions for unchanged implementation files. For files changed by v2, the v2
descriptor names each already reviewed v1 predecessor and successor explicitly
as a permitted predecessor of the one exact v2 implementation. The immutable v1
descriptor is not edited, and an arbitrary intermediate hash cannot establish
compatibility.

One closed autonomy source profile records the reviewed successor bytes for
the non-economic repairs and their exact baseline or previously reviewed
predecessor hashes. It also pins its checker, admission implementation and
named added modules. No glob, arbitrary source replacement, broker authority,
book reset or new compatibility exception is introduced. Historical profiles
remain immutable; their independent proof contracts are retained.

Compatibility proof validates the ordered source profiles before matching files,
then reuses those validated records for exact predecessor/successor comparisons.
It retains each profile's specialized addition validation, closed file/addition
sets, historical successor rules, canonical source seams and environment proof.
Matching a large retained source manifest does not repeatedly read and parse the
same authenticated descriptors for every file.
