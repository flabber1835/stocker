# Remove work whose inputs have not changed

Decision: 2026-11-07, following the owner's measured PR 571/572 installation
trace and explicit request to correct both installation and daily operation.
The financial book, command identities, PAPER boundary, UNKNOWN outcomes and
long-only/unlevered guards remain authoritative. Repeated names alone do not
prove duplication: a fresh broker, lease, clock or media observation can change.

## Restore readiness follows the worker phase

The existing private restore worker owns copy, `pg_verifybackup`, and PostgreSQL
startup in that order. The host currently invokes `docker exec pg_isready`
throughout copy, when success is impossible. Replace that loop with one bounded
Docker log stream carrying an exact invocation-bound phase sequence. Only after
the same worker announces PostgreSQL startup may readiness probes begin. Copy,
verification and readiness share the original 1,200-second readiness budget;
the existing worker, outer recovery and final SQL/replay deadlines stay intact.
EOF, malformed own-phase records, failed verification and timeout refuse. A
phase is scheduling information, never evidence of a successful restore. Keep
the actual final readiness, recovery-marker/replay and semantic checks. Terminate
and reap only the log client on completion/refusal; canonical cleanup still owns
the private worker, volume and network.

## Daily renewal is independent of a full semantic drill

An activation checkpoint may consume a verified base and archive its newly saved
state. A genuinely due base must be renewed once under the same target lock and
whole invocation deadline. Authenticate the producer's exact selected name,
cluster, metadata and physical verification, then commit the activation witness,
wait for archive arrival and verify its actual WAL chain once. Record whether a
new base was made. Never call this a full restore or change a genuine drill date.
After any renewal or witness mutation, failures refuse: do not fall back to a
second base allocation or an unrelated full restore. Explicit full/physical
restore commands and migration recovery requirements retain their contracts.

## Exact retained-source compatibility

The current installed C0 source has 455 runtime Python modules. Pin that complete
predecessor without rewriting its bytes, preserve every older retained map and
the structural/economic baseline, and seal this exact successor's operational
reader/projection and combined plan-verification changes plus one new display
projection module. Refresh only the candidate map and normalized checker pin;
keep `authority_effect=NONE`. Unknown, missing or extra source modules must retain
their actual identity and refuse old compatibility. No financial fixture/result
or strategy identity is re-pinned to make these operational changes pass.

The frozen PAPER lifecycle equivalence manifest remains unchanged. Its separate
reviewed-delta inventory records only the changed `current_paper_plan` definition,
preserving its historical AST identity and all other definition records. Reference
this one-proof design and its behavior tests there; it is a source-change audit,
not a new financial result or a relaxation of any other definition's fingerprint.

## Recovered operational read failure on 7 November

Review event 2820 was published at 15:08:28.632838 UTC and recovered as event
2821 at 15:08:38.660897. The exact retained PostgreSQL window shows four statement
timeouts: two supervisor-instance reads, verifier-owner row admission, and a late
leader/instance read. The canonical primary container did not restart. The amber
headline is the unacknowledged recovery, with current observations and plan ready.
The logs identify the failed database reads, but contain no historical backend
wait sample proving whether the triggering stall was CPU, I/O or a competing lock.
Do not invent that attribution. Bounded local qualification was concurrent.

The operational collector currently promotes its first transient SQL read refusal
to a complete negative snapshot, despite the existing 20-second call budget.
Allow one fresh whole-collection retry for typed statement/lock timeouts in the
pre-review read phases only, with bounded backoff and the same original outer
deadline. Never retry after commit admission, reuse a partial panel, extend a
positive snapshot's clocks, hide a completed negative fact, or retry a malformed
identity/signature. Persistent refusal still publishes its true negative result.
Keep the failed stage and typed safe diagnostic in append-only review history so
a later recovery cannot erase the evidence needed to explain a real incident.
This addresses the observed failure-escalation path; the exact host-stall cause
remains limited by evidence retained at the time.

Local qualification must use disk-backed, test-owned scratch and bounded memory;
do not repeatedly copy large unchanged fixtures into a RAM filesystem on the
running PAPER host. Incremental native source staging preserves actual Git LF
bytes and makes repeated test runs reuse unchanged source files. Production
volumes, credentials, Docker socket and network stay outside the test container.

## Daily SHADOW verification and current execution presentation

The read-only current-PAPER-plan command currently verifies shadow once inside
plan reconciliation and immediately verifies it again to obtain the same result.
Return the verified intent and its reconciliation together from one canonical
operation. The existing report-only API remains a wrapper over that operation.
All original state/session/exposure/sizing/hand-over checks remain; callers cannot
supply a purportedly verified result. This removes a duplicate in both daily
inspection and installation readback without carrying authority across commands.

The independent SHADOW receipt will bind a bounded inventory of all non-PAPER
processed-session row identities, publications, physical relation identities,
transaction epoch, installed schema/DDL witness and the existing source/config
context. Unknown cursor namespaces remain included. Reading row identities does
not decode retained strategy state. Plan and rollout changes are absent from this
content subject because they do not modify the canonical shadow. Missing,
oversized or changed inventories refuse/reverify, never reuse an old PASS.

The full verifier supplies a typed, authenticated, small render basis alongside
its canonical holdings: session, controller target and book counts/values. Each
consumer then reads the current plan/rollout in its coherent read transaction
and applies the existing adoption/coherence checks to that basis. Plan/rollout
changes therefore update exposure/unpriced presentation without rescanning
retained history. They still invalidate PAPER evidence. Do not make broker
inputs part of SHADOW, omit unknown strategy namespaces, or reuse a synthetic
financial state. This basis is display data, never strategy/execution authority.

Preserve the original full proof clocks and 600-second expiry. Periodic full
integrity refresh remains: this change does not claim metadata proves the
continued integrity of every stored input byte. It removes plan/progress-induced
reverification during that already-valid proof, not independent media-integrity
requirements. Consumer reads cannot create verification jobs or extend proof age.

## Keep PostgreSQL's existing helper mount when its content is identical

The primary reads only the standalone archive helper from its read-only scripts
directory bind. The public Compose resolver will inspect the one canonical
PostgreSQL container and compare that mounted directory's regular helper bytes
with the current reviewed helper. With exact project/service/image/mount identity
and matching bytes, retain the existing directory source in a generated Compose
override. A release pathname is not a configuration change. Do not switch to a
new content-addressed directory solely to implement this fix: that itself would
cause another unnecessary restart. Retain the mounted release while it supplies
infrastructure. Changed/missing helper content selects the current reviewed
directory and ordinary Compose reconciliation; malformed ownership refuses.
Actual archive publication and backup identity checks remain unchanged.
Ownership discovery must succeed; an unavailable daemon is not evidence that
there is no existing primary. The resolver refuses rather than guess a mount.

## One GO owner verifies immutable software once

Compose graph discovery may be reused only inside one process/runner, keyed by
the resolved checkout, complete caller environment digest, resolver/configuration
source bytes, private dotenv digest, generated graph/runtime selector bytes and
the selected mounted archive helper bytes. Reobserve that cheap local context
on reuse; changed inputs require fresh discovery. Return copies of the argument
list. No Docker/SQL/broker readiness result is cached, and no context crosses an
owner/process boundary. CPU/storage/actual image checks remain at their existing
mutation boundaries. Reconcile actual service state normally.

Run financial validation and its runtime promotion in one host process under the
existing GO lock/output guard. They share only the existing process-local signed
software verification session, whose clean-source/verifier/trust context is
checked on every reuse. Promotion still requires the current run's genuine
financial PASS, current main/source and actual local image identity. A new owner
or independent promotion command authenticates software afresh. No disk PASS,
environment capability or installation receipt substitutes for signed software.
Installation and activation keep their independent initial authentication.

When a reviewed bundle is already supplied, the coordinator need not quiesce
before parsing its bytes: the activation body owns the single fresh fence before
financial lineage and mutations. When the coordinator must run GO, keep its
pre-GO fence and the later post-GO fence, since GO may start source services.

## Scope and qualification

Correct the shared owners, including normal daily maintenance, rather than adding
an operator skip switch. Separate immutable content proof from mutable execution
and presentation facts before narrowing invalidation. In particular the existing
shadow display includes plan adoption/rollout, so deleting their invalidation
without separating that projection is forbidden. Subsequent design choices for
the stable PostgreSQL helper mount, proof subjects and owner-context reuse are
recorded here before their implementation.

Qualification uses isolated processes/databases without production backups or
broker credentials. Assert actual worker/client/probe counts, shared deadlines,
same-subject reuse and changed-subject refusals. Execute removed-guard falsifiers.
Required CI precedes the authorized merge and signed PAPER installation; compare
the next real trace against the original, retaining failures and coverage limits.

## Disposition of the other repeated trace entries

The removed work is phase-ineligible restore probing, path-only primary
recreation, implicit full drills for a due daily base, a second signed download
inside one GO, repeated unchanged Compose discovery inside one owner, redundant
pre-fencing for an already supplied bundle, plan-only SHADOW invalidation, and
the second full shadow read inside current-plan inspection. The attended wrapper
also omits the old extra diagnostic software verification and queues activation
directly after successful GO and the maintenance handover.

Keep the full WAL integrity scrub at each distinct admission boundary. A prior
filename/count/metadata observation does not prove current removable-media bytes
or arrival of the new activation checkpoint. Normal daily maintenance still owns
its one genuine chain check. There is no safe content witness in the current
storage contract that can remove those independent reads. Likewise engine and
actual service checks at distinct mutation boundaries, installation/GO/activation
admission, broker/account/orders/UNKNOWN and post-GO fences have mutable subjects.
Their identical command names do not make the observations interchangeable.

An operational-only financial-authority release class is not introduced by this
patch. The existing complete-source and signed-image admission remains required;
the compatibility seal changes comparison views only, with no authority effect.
Removing that admission would change the financial safety contract. This patch
does remove the avoidable duplicate work inside those existing owners.

Real private-PostgreSQL qualification holds the actual verifier-owner row across
the first collection, observes its typed statement timeout, and releases it
before the bounded fresh attempt. The transient case commits without a FAILED
event. Two actual read timeouts publish one negative result with OWNER, attempt
count and safe diagnostic retained in review history. It does not establish which
host resource caused the historical 15:08 stall.
