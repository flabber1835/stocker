# Paper lifecycle decomposition

**Decision status:** accepted for Step 4 implementation
**Verified base:** `887f479b15ad861313da666ad698034d3847121c`
**Behavioral source:** `sentinel/paper.py` at SHA-256
`c14cc619ca19e91b53e3f618543ea782e97f5a87bdde65af6370bd313bd63ffe`

## Objective

Replace the 3,202-line `sentinel/paper.py` module with a statically readable
`sentinel.paper` package. Every paper-trading lifecycle rule retains one
canonical implementation. The change preserves the production call sequence,
transaction ownership, broker authority, failure classification, economic
inputs, economic outputs, and public `sentinel.paper` entry points.

The package remains an orchestration layer. Canonical strategy, feed,
authority, cash accounting, database schema, reconciliation, command journaling,
and broker execution stay in their existing domain modules.

## Package ownership

```text
sentinel/paper/
    __init__.py       declarative compatibility exports only
    model.py          lifecycle exceptions and machine-readable result models
    inspection.py     read-only broker/account inspection and identity evidence
    validation.py     paper-specific readiness, authority, plan and grant checks
    cash.py           broker-cash evidence, account economics and cash authority
    targets.py        target/action projection, pre-open units, deltas and instruments
    reconciliation.py account/order observation validation and settled evidence
    finalization.py   prior-cycle close NAV, fill interval and trial finalization
    preparation.py    state warm/replay, immutable plan adoption and plan status
    execution.py      final execute gate and canonical executor orchestration
    recovery.py       restart and unresolved-cycle recovery orchestration
```

### `model.py`

Owns `PaperActivationRefused`, `PaperRetryableRefused`,
`PreOpenShareUnitAuthorityUnavailable`, `PaperAccountInspection`,
`PreparationResult`, and `ExecutionResult`. These definitions preserve their
existing constructors, serialized representations, and exception meaning.

### `inspection.py`

Owns certified-broker verification, strict account inspection, account-binding
checks, account-evidence quiescence, recovery identity checks,
`inspect_paper_account`, and `build_security_resolver`. It performs no broker
mutation. The same native broker account id, paper/live distinction, permanent
asset identity, and expected-account evidence remain authoritative.

### `validation.py`

Owns the paper-specific validation kernel: strategy witness authority, stable
hashing, readiness, execution-window checks, missed-session validation,
deterministic plan-id verification, state/current-plan loading, current plan
authority, fresh-connection enforcement, automation grant validation, broker
grant validation, and guarded-broker construction. It delegates signed
authority and guarded broker behavior to the existing canonical authority and
execution modules.

### `cash.py`

Owns broker/account economics extraction, broker cash-state inspection,
endpoint-lag evidence, and the exact cash-authority decision. Broker cash remains
execution/reconciliation evidence. It cannot enter Wealth Core state, Sentinel
controller state, or target sizing except through the already-certified account
snapshot and target construction path.

### `targets.py`

Owns scalar corporate-action lookup and multipliers, post-projection action
multipliers, target reprojection orchestration, active permanent security ids,
pre-open unit views and revalidation, informational active symbols, plan deltas,
clean-empty no-op proof, official pre-open cutoff, and broker instrument
mapping. The canonical implementation of target reprojection remains
`sentinel.execution.target_reprojection`; this module only supplies the paper
lifecycle orchestration around it.

### `reconciliation.py`

Owns reconciliation-result cleanliness, dual-observation mutation checks,
settled account-evidence bracketing, and the account/order observation boundary.
It explicitly exposes the canonical `sentinel.execution.reconcile` dependency
used by tests and orchestration. UNKNOWN, partial-fill, terminal, duplicate,
contradictory, and unresolved evidence semantics remain in the canonical
execution reconciliation engine.

### `finalization.py`

Owns prior-cycle close-NAV recording, fill-interval recording, and succeeded
cycle finalization. It preserves the requirement that durable complete evidence
exists before finalization and that retryable evidence gaps cannot be converted
into successful completion.

### `preparation.py`

Owns the frozen paper strategy selection, marks/ticker loading, state warm-up,
state replay, immutable plan adoption, `prepare_paper_plan`, and
`current_paper_plan`. Preparation remains read-only at the broker. It may write
durable Sentinel state under the existing writer lock and pinned publication
transaction.

### `execution.py`

Owns execution observation timing, `_execute_current_paper_plan`, manual and
automated execution entry points. It repeats all authority and readiness checks,
loads the durable current plan, preserves durable command identity and
`SEND_PENDING` ordering, and delegates broker command handling to the canonical
executor.

### `recovery.py`

Owns `recover_automated_paper_cycle`. It coordinates restart reconciliation and
terminal recovery through the canonical execution subsystem. Separating this
high-level phase keeps the lower reconciliation evidence module independent of
preparation and execution orchestration and prevents a package import cycle.

## Dependency direction

The paper package has an acyclic internal dependency graph:

```text
model
  ↑
inspection     validation
  ↑               ↑
  └──── cash   targets
          ↑       ↑
          reconciliation
             ↑
          finalization
             ↑
          preparation
          ↗        ↖
     execution    recovery
```

More precisely:

* `model` imports no paper module.
* `inspection` and `validation` depend on `model`.
* `cash` depends on `model` and `validation`.
* `targets` depends on `model`.
* `reconciliation` depends on `model`, `inspection`, `cash`, `validation`, and
  `targets`.
* `finalization` depends on `model` and `targets`.
* `preparation` depends on the lower lifecycle modules.
* `execution` and `recovery` depend on the lower lifecycle modules and
  `preparation`.
* `__init__.py` imports canonical definitions for compatibility and contains no
  mutation, synchronization, installer, registry, or dispatch logic.

All paper modules point downward into canonical strategy, feed, authority,
persistence, and execution domains. Automation and CLI continue to point into
the paper package.

## Production lifecycle ordering

The decomposition preserves the actual sequence in the verified source.

### Preparation and plan adoption

```text
assert paper endpoint and certified adapter
→ require runtime schema
→ validate exact expected account and preparation grant
→ select the frozen strategy identity
→ acquire journal writer lock
→ prove no legacy account path and load rollout authority
→ pin the publication with caller-owned commit behavior
→ require readiness, latest closed session and exact published frontier
→ require signed preparation authority
→ construct the guarded read-only broker
→ validate restart/current-plan economics when present
→ reconcile commands/orders/positions
→ inspect the exact account and broker cash evidence
→ validate cash authority
→ finalize a due succeeded prior cycle when eligible
→ reject working-order ambiguity
→ warm or restore state and replay missed sessions
→ construct and adopt the immutable next-session plan
→ persist the immutable cash baseline
```

Dual informational paper mode retains its existing independently attested shadow
lineage, source-final timing boundary, mirror revalidation, dual plan authority,
and single explicit commit after plan and authority adoption.

### Execution

```text
load durable state/current plan
→ require current rollout/publication/runtime/account authority
→ reconcile unresolved prior commands and broker evidence
→ validate account identity and broker cash authority
→ establish target reprojection and pre-open share-unit authority
→ derive exact command deltas and deterministic identities
→ persist command and SEND_PENDING before transport
→ send through the canonical guarded execution broker
→ observe and reconcile
→ retain UNKNOWN when outcome is ambiguous
→ return durable machine-readable execution state
```

### Restart recovery

```text
validate recovery-scoped automation grant and exact account identity
→ reconcile durable commands against complete broker evidence
→ validate cash and target projection authority
→ revalidate pre-open units when the open boundary was crossed
→ resolve only through canonical reconciliation/recovery transitions
→ leave unresolved or incomplete evidence fail-closed
```

### Prior-cycle finalization

```text
prove the succeeded cycle is due
→ record authoritative close NAV
→ record authoritative fill interval
→ reproject target units through relevant scalar actions
→ require complete durable trial evidence
→ finalize exactly once
```

## Transaction ownership

The module move does not add a connection, cursor, commit, rollback, savepoint,
or lock.

| Operation | Existing owner retained | Boundary retained |
|---|---|---|
| account inspection | caller connection | read-only cursor operations |
| preparation | `prepare_paper_plan` | `journal.writer_lock` plus `publication.pinned(commit=False)` |
| normal catch-up/adoption | canonical catch-up/journal code | existing caller transaction |
| dual plan adoption | `prepare_paper_plan` | plan, dual authority and cash baseline committed together |
| account-endpoint lag evidence | cash authority helper | same insert/read and commit behavior |
| execution | `_execute_current_paper_plan` | same explicit commit/rollback points around durable command execution |
| recovery | `recover_automated_paper_cycle` | same commit point after successful durable recovery |
| finalization | preparation/finalization call chain | same enclosing preparation transaction and evidence functions |

Nested helpers continue to receive the caller-owned connection. A helper that
previously assumed an open transaction keeps that assumption.

## Compatibility

`import sentinel.paper` remains valid. The package initializer explicitly
re-exports the original public API:

```text
DEFENSIVE_SYMBOL
ExecutionResult
PaperAccountInspection
PaperActivationRefused
PaperRetryableRefused
PreOpenShareUnitAuthorityUnavailable
PreparationResult
build_security_resolver
current_paper_plan
execute_automated_paper_plan
execute_paper_plan
inspect_paper_account
prepare_paper_plan
recover_automated_paper_cycle
```

Private definitions used by existing production code receive explicit canonical
imports at their owning module. Layout-only tests move to the canonical owner.
Tests that patch a real dependency boundary patch the owning lifecycle module or
its explicit canonical dependency. No package symbol is copied dynamically and
no import order constructs the production path.

## Equivalence proof

The implementation must provide all of the following before review:

1. normalized AST equality for every moved function/class body;
2. exact inventory showing one owner for every original top-level definition;
3. import-order and canonical-export tests;
4. unchanged exception classes and serialized result shapes;
5. focused characterization for inspection, preparation, cash authority,
   reprojection, reconciliation, execution, recovery and finalization;
6. durable before/after economic snapshots for target positions, quantities,
   commands, command identities, cash, reconciliation state and cycle outcome;
7. no changes to economic, strategy, certification or golden fixtures.

`sentinel/paper.py` is deleted after the package compiles and the compatibility
surface is proven. The original file does not remain as a fallback or alternate
implementation.
