# Final bounded simplification and architecture freeze

**Status: DECIDED 2026-09-01.** This is the final repository-wide
simplification pass. It changes implementation ownership and module boundaries
only. Strategy, controller, certificate, rollout, execution, feed, and broker
semantics remain unchanged.

After this pass, architecture is frozen. Subsequent work targets correctness,
test coverage, and operational reliability. A later structural change requires
a concrete correctness or reliability defect and its own reviewed design
decision.

## 1. Preserved ownership boundaries

The production dependency direction remains:

```text
Sharadar -> Wealth Core -> Sentinel controller -> execution projection -> broker
```

The following owners remain singular:

```text
Wealth Core state and decisions          stock_strategy_shared.wealth_core
Canonical production session transition sentinel.core.kernel.advance_session
Sentinel exposure decision               sentinel.controller
Feed publication                         sentinel.feed.publication
Corporate-action interpretation          canonical shared/feed owners
Broker transport                         sentinel.execution.alpaca
Broker reconciliation                    sentinel.execution.reconcile
Execution authority                      sentinel.execution.authority_gate
```

This pass does not introduce overlays, adapters, alternate implementations, or
test-selected production owners for those behaviors.

## 2. CLI ownership

The executable surface has one parser construction path and one router in
`sentinel.cli.main`. Parsing, common pre-dispatch gates, exception-to-exit-code
mapping, and the direct command-handler association are visible there.

Each command handler has one static family owner:

| Owner | Commands |
|---|---|
| `sentinel.cli.status` | status, shadow-status, shadow-run |
| `sentinel.cli.account` | migration-plan, target-book, plan, migrate-account, adopt-restored-account, establish-ownership |
| `sentinel.cli.paper` | compare-paper-warmup, inspect-paper-account, inspect-empty-paper-account, bind-empty-paper-account, prepare-paper-plan, current-paper-plan, execute-paper-plan |
| `sentinel.cli.authority` | candidate creation, certificate lifecycle, key revocation, rollout transition |
| `sentinel.cli.automation` | status, health, activation, kill control, deactivation, alert acknowledgement, service run |
| `sentinel.cli.feed` | feed status/seed/daily/repair, check-data, rejection audit, identity |

`sentinel.cli._shared` owns only shared exit codes, logging, static refusal
rendering, and the authorized-runtime marker gate. It owns no command and no
router.

`sentinel.__main__` invokes `sentinel.cli.main.main` directly. The retained
`sentinel._main_impl`, lazy CLI symbol discovery, forwarding, and CLI
monkeypatch synchronization have no supported production caller and are
deleted. Tests patch or call the final static owner.

The extraction preserves command names, arguments, defaults, help, output,
exit codes, refusal ordering, transaction behavior, and broker-contact gates.
The authorized-image gate remains before configuration and database access for
the existing broker- and authority-capable command set. Emergency revocation
and kill operations retain their current reachability and lock behavior.

## 3. Authority ownership

`sentinel.authority` becomes an explicit package with this dependency order:

```text
model <- canonical <- validation <- repository <- lifecycle
```

The responsibilities are:

| Owner | Responsibility |
|---|---|
| `authority.model` | Frozen certificate, context, trust-root, and rollout types; policy/schema constants |
| `authority.canonical` | Canonical JSON grammar, strict decoding/encoding, base64url, hashing, public-key identity |
| `authority.validation` | Claim, binding, trust-root, signature, runtime, source, and configuration verification |
| `authority.repository` | PostgreSQL reads/writes, row conversion, retained unsigned-row inspection, rollout persistence |
| `authority.lifecycle` | Install, activate, retire, revoke, key revoke, execution checks, observation checks, rollout transitions |

`authority.__init__` is a small explicit public API composed with ordinary
imports. Production callers use the concrete owner when they need an internal
function. The package uses no `__getattr__`, wildcard import, namespace copy,
or mutation propagation.

Canonicalization, signed bytes, certificate digests, signature checks, trust
root bytes, claim evaluation order, exception types, and refusal messages are
preserved. Pure verification accepts explicit roots and time and performs no
database work.

Repository helpers do not commit, roll back, or acquire new locks. Lifecycle
functions preserve the current SQL statement order, `FOR UPDATE` placement,
lock order, commit flags, rollback-on-`BaseException` behavior, and caller-owned
writer-lock boundary. Emergency certificate and key revocation remain outside
the execution writer lock.

The retained unsigned system-certificate reader and revoker remain supported
for restore validation of deployed historical databases. These rows never
satisfy execution authority. Their deletion condition is a separately reviewed
schema migration proving every supported database has removed the legacy table
and rows.

## 4. Compatibility rule

Every compatibility-shaped surface is classified by runtime caller evidence:

1. A surface with no supported caller is deleted and its useful tests move to
   the canonical owner.
2. A static helper with a real production caller may remain when moving it
   would expand this pass into an economic or feed redesign. Its owner and
   deletion condition are recorded in the pull request.
3. Import-time module mutation and duplicate economically significant owners
   are release blockers unless converted to one static owner in this pass or
   retained with a concrete safety blocker and deletion condition.

File movement alone does not satisfy this rule. The final runtime must contain
fewer routing paths, mutable handoffs, branches, and apparent implementation
owners.

Two import-time mutation paths are in scope and receive static owners:

- `PortfolioState.from_dict` calls the pure persisted-state validator directly
  before decoding. The package initializer no longer replaces the classmethod,
  and the installer module and marker are deleted. Validation order, refusal
  type/message, valid-state round trips, restart behavior, and economic hashes
  remain exact.
- `sentinel.shadow_runtime` uses the segmented PostgreSQL observation store
  directly and owns the complete reviewed-genesis check for segment zero and
  later append-only segments. The segment record/rollover module remains the
  owner of segment facts. Import-order installation, runtime assignment, and
  installation markers are deleted. Existing segment-zero durable records keep
  their current validation contract.

The remaining bounded, caller-free facades removed in this pass are:

- the Sentinel-local book-artifact module identity shim, after callers import
  the shared canonical artifact owner directly;
- the `core.production` transition and return aliases, after tests use the
  production kernel and result type directly;
- the `core.loader` terminal-event/result wrappers, after runtime callers use
  `core.terminal` directly;
- private PAPER initializer forwarding and unused reconciliation-evidence
  aliases, while the documented PAPER package API remains explicit; and
- the feed-store `ensure_schema` transition spelling, after every supported
  runtime and test caller uses the fail-closed `require_feed_schema` owner; and
- wildcard feed re-exports and duplicate unguarded orchestration functions that
  have no production caller. Feed normalization, cursor, readiness, corpus,
  reconciliation-store, and seed-proof helpers with real callers remain their
  static implementation owners in this pass.

The operator GO-validation and autonomous-deploy composition overlays remain
supported by `scripts/sentinel-go-validate.sh` and
`scripts/sentinel-autonomous-deploy.sh`. Deleting them requires a separate
deployment-safety design proving byte-identical evidence, verdict, timing,
exit-code, and refusal behavior under one static composition. Durable schema,
segment-zero, broker-handover, and persisted-row compatibility remains until a
reviewed migration proves that every supported deployment has retired the old
representation.

The `shadow-run` CLI command remains the explicit foreground, non-recovery
runner and delegates once to `shadow_service`, the same base service wrapped by
the worker recovery policy. The worker and supervisor retain their distinct
outage-recovery operational contract; changing that command contract is outside
this ownership-only pass.

## 5. Verification and freeze gate

The pass is accepted only when all of these hold on the exact pull-request head
and GitHub's current-main synthetic merge:

- all 42 CLI commands map directly to the declared owner;
- one parser and one router exist;
- `_main_impl.py`, lazy CLI discovery, and CLI mutation synchronization are
  absent;
- canonical authority byte and hash vectors remain exact;
- valid and invalid certificate vectors retain their outcomes and reasons;
- runtime and source binding remain fail-closed;
- authority lifecycle transaction, rollback, event, and concurrency behavior
  remains coherent;
- representative production decision, replay, broker, plan, execution, and
  reconciliation artifacts remain exact;
- the complete Sentinel and prospective Wealth Core suites pass in the pinned
  test image;
- the Python 3.8 host compatibility lane passes;
- `sentinel-exact-head`, `sentinel-synthetic-merge`,
  `host-python-38-exact-head`, and `host-python-38-synthetic-merge` pass.

Passing this gate ends the broad simplification campaign. An independent
financial and safety review is the final acceptance step.
