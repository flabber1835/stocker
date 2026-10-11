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
