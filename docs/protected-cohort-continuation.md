# Protected paper cohort continuation

Decision: 2026-10-20. Native cash reflected opening fills before their zero-fill
acknowledgements were reconciled into the journal. Conservative live holds
deferred later names; two resting DAY orders then prevented executor re-entry.
The immediate-fill gateway rehearsal did not exercise that composition.

## Existing basis and positive evidence

Initial funding admission remains clean, COMPLETE and quiescent. Subsequently
one canonical predicate, checked during recovery routing and again under the
financial writer lock, may permit the existing protected cohort to continue
under its original immutable basis. This narrowly supersedes the earlier
quiescent restart restriction; it cannot earn a new nonquiescent basis.
Require exact current deployment/epoch, plan, immutable projection, policy,
endpoint and certified broker composition; current complete clean
reconciliation; and a retained basis bound to those identities. An observation
used for continuation must be nonfuture and at most 60 seconds old at the
admission boundary; a repeated read does not renew its timestamp. Every working
order must positively match an owned same-plan protected BUY in ACKNOWLEDGED or
PARTIALLY_FILLED state, including native/client identities, quantity and exact
terms. UNKNOWN, SEND_PENDING, CANCEL_PENDING, other-plan/foreign orders,
working SELLs, replacements, missing evidence and contradictions retain their
existing refusals. A recovery routing verdict grants no transport capability.

Retain fresh active-account, identity, blocking-flag and 1x multiplier checks.
Buying power below cash is allowed only through the supported protected path;
it does not prove settlement or attribute a reservation. Buying power above
cash remains refused under the existing tolerance. Preserve all three funding
bounds: native buying power, fresh cash minus remaining potentially live
promises, and the original fixed gross ceiling minus other original maximum
charges. No cash movement implies a fill. No sale, deposit, cancellation or
terminal saving increases the basis.

At the first temporary protected funding deferral return promptly to recovery
instead of retrying every later name against an unchanged journal. Canonical
complete reconciliation positively synchronizes fills. Continue only proven
unsent actionable deltas; never duplicate orders or enlarge persisted terms.
All source, authority, action, freshness, long-only and per-call broker guards
remain. Preserve the original execution clock and final nonawaiting pre-POST
cutoff. After cutoff missed BUYs stay unsent, including today's commands.

## Working orders and monitoring

A current clean COMPLETE observation proving only known protected DAY orders
remain earns a bounded observation wait with explicit evidence and a fixed
deadline ten minutes after the actual regular-session close. Pending display
and wait evidence expires no later than ten minutes after that observation;
only a new complete observation renews its evidence time. This broader pending
observation interval does not extend the 60-second financial continuation gate.
This ordinary wait does not consume the
infrastructure failure budget or claim completed execution. Keep legal durable
recovery transitions and independent recovery. Uncertain commands, stale or
contradictory evidence, authority failure and writer-lock exceptions retain
their error treatment. Escalate an expired observation deadline.

Schedule retries from a fresh callback-completion sample in the existing
injected clock domain. Preserve failure history, deadlines and execution
cutoffs; recheck them after recovery before further execution. Do not publish
retry wakes already overdue solely because their callback was lengthy.

The panel distinguishes positively matched owned resting reservations from
unexplained buying-power differences using current bound observation evidence.
Margin, foreign/unknown holds, contradictions and stale evidence remain visible.
Known working orders are pending, never proof of full target completion.
Preserve history; acknowledge reviewed alerts with the supported CLI. An
acknowledgement cannot turn a failing current gate green.

## Qualification and release

Retain the immediate-fill 120-second first-POST / 300-second complete-basket
baseline separately. Add a persistent actual scheduler scenario using local
provider state shared across callback processes: zero-fill acknowledgements,
independently delayed/partial fills, cash changing before journal reconciliation,
reduced buying power and two resting DAY BUYs. Measure every intended
acknowledgement against one original opening clock and unchanged cutoff.
Verify fixed limits/basis, conserved cash, no duplicate keys, accurate pending
health and continued recovery after cutoff with zero late POSTs. Exercise
bounded ownership contention and concurrent private monitoring under enforced
resource limits. Use the exact signed candidate image and an isolated current
source database, without native broker mutations, production mounts or backtest
access. Preserve failed evidence and consumed campaign namespaces.

The longer private persistent scenario receives one explicitly declared
30-minute retained-review context fixed at campaign start, covering preparation,
the original submission window and two post-cutoff recovery observations.
The separate immediate-fill baseline keeps its existing 20-minute context.
Neither budget changes production review lifetimes, financial authority,
source-frontier checks, first-POST limits or any original submission deadline.

Add falsifiers for foreign/stale/unknown orders, altered terms/basis, insufficient
cash, margin, revoked authority, real lock failure, expired waits and removed
cutoff guards. Component tests do not replace composed gateway qualification.
Require reviewed PR CI, immutable signed-image publication, explicitly scoped
retained-runtime admission, canonical INSTALLED/FENCED installation and the
ordinary current-image restore/reconciliation and conditional activation gates.
Preserve strategy state, binding, orders, incidents and the running backtest.

The executable successor has its own closed source descriptor. Keep prior JSON
descriptors and complete historical witnesses unchanged. The predecessor's
opening checker may delegate only its exact reviewed normalized implementation
and source transitions to that new descriptor; pin both its normalized checker
and exact replacement bytes there. This extends the existing authenticated
checker chain without a wildcard, new economic lineage or software authority.
Retain atomic predecessor additions checks when a member has an exact reviewed
successor, and independently reject missing, altered or unlisted members.

Today's dispatched plan cannot be renewed under a new certificate. Preserve
the old runtime context until native DAY orders positively settle and ordinary
broker-GET-only preparation can reconcile them. Financial activation of the
new release requires the next actual closed-session decision and its accepted
publication and verified shadow. Do not substitute unsent-recovery flags or
replay today's historical missed BUYs to complete that cutover.

## Physical ordering for snapshot verification

Decision, 2026-10-20: add a nonunique B-tree index on
`sentinel_snapshot_bars (candidate_id, session, security_id COLLATE "C")`.
The exact private qualification database uses `en_US.utf8`; its existing
primary key uses the default security-ID collation. A bounded read-only
`EXPLAIN` of the canonical snapshot reader therefore includes an incremental
sort to produce its required C ordering. The new index matches that existing
ordering directly. Keep the primary key, query, complete payload scan, schema
validation, canonical serialization and all three content hashes unchanged.
Do not add covering columns or infer a measured latency benefit from a plan.

Install the index only through the existing explicit atomic feed migration,
while the deployment is fenced and its migration ownership is held. Runtime
readers and validators never build or repair it. Preserve all candidate rows,
manifests, publication receipts, strategy state and existing immutable-input
rules. The index is a physical access path and grants no execution authority.
Index creation must succeed before the migration commits; the ordinary lock
timeout and rollback behavior remain in force. No production or campaign
database receives an ad hoc index operation.

The read-only feed catalog contract requires this usable nonunique B-tree,
with exactly these ordered keys and C collation and no predicate or covering
columns. Its absence or altered shape is an explicit schema mismatch. This
makes the supported installer take its existing fenced migration path and
fresh pre-migration backup, rather than reporting an unchanged catalog and
skipping index installation. No historical book or source witness is rewritten
to satisfy this physical schema upgrade.

Focused private PostgreSQL tests must show canonical migration idempotence,
exact row order and unchanged sealed hashes before and after installation,
and an unforced plan using the matching index without an ordering sort.
Removing the index or its C collation must fail that access-path assertion.
Retain the original first-POST and complete-recovery limits and qualify a fresh
exact image and namespace; this index alone is not evidence those limits pass.

## One traversal for full verification and readiness facts

Decision, 2026-10-20: during the first mandatory complete snapshot verification,
also accumulate raw per-session population and positive-domain counts, the
bounded canonical benchmark axis, and exact `(security_id, ticker)` uses as
session bitmasks. The initial execution resolver verifies content before it
constructs `SnapshotReferences`; a later readiness observer must not miss that
first scan. Keep the original complete row-model validation, row order,
serialization, hashes, axes and streaming checkpoints. Only after every bar,
benchmark, hash and final ownership check succeeds may one completed private
record become reusable under the original live publication pin. Preserve
`verify_content`'s public manifest result.
Unscoped verification and a different publication candidate allocate no summary
and keep the existing mapped readiness path.

This record contains raw facts, never `VendorBar` objects, price arrays,
strategy decisions, readiness verdicts or broker permissions. Limit reference
uses to 100,000 distinct identity/ticker pairs. On overflow discard the entire
summary optimization and use the existing mapped readiness stream; continue
the complete original content verification. Never truncate identities, skip a
row check or alter input eligibility to meet that bound. Retain no material
outside the exact database, publication, candidate, manifest and original live
pin; partial scans, lost pins and changed identities install no record.

Readiness still admits `SnapshotReferences`, current metadata, source/validation
bindings, canonical aliases, action dates, terminals and distributions. Select
its existing exact warmup/decision and benchmark axes from the raw facts and
check every represented selected identity/date through the same canonical
resolver predicate as the mapped reader. A first/last date interval is
insufficient: a reused symbol on an interior date must refuse, while an absent
interior row must not be invented. Preserve dynamic source-final and readiness
clauses and all execution authority/freshness guards. Economic input readers,
canonical strategy state and the running backtest remain unchanged.

Focused tests must cross the real resolver-first boundary, prove one complete
stream before readiness, compare counts with independent SQL, exercise middle
date identity errors and absent dates, and preserve corruption, action, domain,
pin-loss, changed-generation and interrupted-scan refusals. Demonstrate guard
removal falsifiers, detached returned material and complete old-path fallback on
the reference bound. Only a fresh exact-image gateway can establish a latency
benefit; the original 120/300-second qualification deadlines stay fixed.

## Preserve bytes while reducing repeated serialization work

Decision, 2026-10-20: reduce pure Python bookkeeping in the existing complete
verification and runtime source fingerprint. Keep every fresh source-tree
enumeration, file-byte read, model validation, content hash and authority check.
No runtime observation or authority is shared across guard invocations.

The source fingerprint may obtain a normal pathlib child's relative POSIX name
by joining its exact suffix parts when the ordinary concrete Path types and
lexical parent prefix match. Unusual paths retain the original relative_to
operation. Preserve sorting, exclusions, fresh file reads, failures and the exact
path/NUL/content-digest/newline framing; combining consecutive hasher updates
must produce identical bytes. Retain no source inventory or file digest cache.

One uncached snapshot verification may create one standard JSONEncoder with
the exact canonical_json options and reuse only that encoder for its rows.
Preserve complete encoding before updating the hasher, ASCII encoding and the
newline framing. Keep the canonical_json API and sealing behavior unchanged.
The encoder retains no row, facts, completed proof or cross-call lifetime.

Independent byte/hash oracles must compare against the original algorithms,
including unusual labels, paths, error domains, changed files and final-row
corruption. Mutating serialization or path framing must falsify those checks.
Measure unprofiled algorithm timings separately; neither a microbenchmark nor
the diagnostic profiles proves sufficient opening margin. A fresh exact-image
gateway must still pass the unchanged first-POST and recovered-basket limits.

## Retain safe qualification heartbeat failure evidence

Decision, 2026-10-20: a private gateway refusal must retain enough evidence to
distinguish its heartbeat boundary from its callback boundary. Record only fixed
exception domains, exception type/module and validated SQLSTATE, never exception
messages, arguments, connection strings or SQL text. Keep the last four actual
parent-process heartbeat connection/renewal observations, including elapsed
times and success or safe failure classification. These are pass-through
observers: call the original operation once, preserve its exact return value or
exception object, and never retry, renew independently or change any bound.

Only after a callback invocation fails, before its IDLE cleanup erases callback
metadata, attempt one read-only snapshot of the exact private physical database.
Use the existing 3-second connection/statement and 1-second lock bounds. Read
the database clock, control/lease/instance state and bounded activity/blocker
metadata without account bindings, query text or provider data. Snapshot and
reporting failures are secondary diagnostics and cannot replace the original
refusal. IDLE cleanup failure also preserves an already-raised primary exception;
cleanup failure after an otherwise successful callback still refuses the run.

No snapshot SQL or diagnostic report is added to a passing callback. Production
runtime source, lease/callback deadlines, retry policy, clocks, cancellation,
ownership and authority remain unchanged. Consumed campaigns remain immutable;
only a fresh namespace may run the newly reviewed harness.
