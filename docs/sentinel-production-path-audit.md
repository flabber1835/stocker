# Sentinel 1.1 production-path audit

**Original audit date:** 2026-08-12

**Stage 2 status update:** 2026-08-12

**Scope:** clean installation through deterministic state preparation, durable
paper-plan adoption, and the separately authorized execution handoff

**Reference:** `docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`
and its terminal-and-issuer-corrected 5,032-session outputs

## Verdict

The integration gap identified by the original audit is closed at the code-path
level. Production now has one runnable, operator-invoked composition from the
published Sharadar corpus through canonical Wealth Core state, breadth and SPY
evidence, the controller transition, share-level projection, one durable current
plan, and the existing execution membrane.

This is **implemented, not activated**. The repository still defines no
scheduled or long-running decision engine. Compose starts only PostgreSQL and
the read-only panel by default; preparation, inspection, migration, and
execution remain distinct manual operations. Alpaca paper is the only accepted
broker endpoint, and no implementation or documentation change authorizes a
legacy-book migration or a paper-order submission. The sole operator command
sequence and checkpoints are in `docs/sentinel-paper-activation.md`.

The honest production status is therefore **production path implemented and
simulator/restart tested; deployment and paper activation remain operator-gated
and have not occurred**.

## Trace of the implemented path

### 1. Installation and startup

`Dockerfile.sentinel` builds a pinned Python image, installs the locked
dependency closure and canonical `shared/` Wealth Core package, copies the
digest-verified controller rule, and installs Sentinel. The Compose application
starts Sentinel's PostgreSQL and read-only panel. Its Sentinel service remains a
run-only CLI profile, so ordinary `docker compose up` cannot prepare a plan,
migrate an account, or submit an order.

There is deliberately no scheduler. Adding autonomous timing, retry policy, or
a long-running engine is a separate deployment decision; Stage 2 does not hide
one in Compose or a restart policy.

### 2. Data ingestion, publication, and readiness

The feed commands ingest Sharadar SEP, TICKERS, and ACTIONS into Sentinel's
database. Publications are atomic visibility boundaries: unpublished rows are
not planning inputs, and incoherent or stale corpora fail readiness. One outer
publication pin covers preparation's readiness check, warm-up or catch-up,
current marks, state persistence, and final plan adoption.

The exact pinned historical corpus remains external data rather than a
repository artifact. A clean installation must ingest or import, publish, and
pass readiness before preparation can produce a plan.

### 3. Canonical state, first boot, and catch-up

`SessionState` version 3 is the only production behavioral envelope. Its Wealth
Core portfolio, pending orders, ledger, and feed are canonical restart forms;
controller state and minimum rolling evidence are composed around them. There
is no second portfolio or realized-exposure model.

On a fresh boot, 252 completed XNYS sessions strictly before the decision
session warm only rolling features. Portfolio episodes, pending actions,
cooldowns, peaks, ages, ledger history, and controller memory start fresh; a
warm-up is not a reconstruction of path-dependent portfolio history. The
decision session then advances once through the same production transition used
on resume.

On resume, the durable cursor and state must agree. Each missed XNYS session is
advanced transactionally through `advance_and_persist`. Historical sessions
change deterministic state only. The final transition adopts its plan and
supersedes all older plans in the same transaction, leaving exactly one current
executable intent after catch-up or restart.

### 4. Breadth, SPY regime, controller, and decision adapter

The production transition builds per-holding breadth inputs from the canonical
shadow, loads SPY total-return history from the separately published `closeadj`
domain, derives typed controller evidence, and persists the controller
transition. Runtime does not read a breadth tape, allocation tape, or standalone
output.

The production decision adapter then converts the immutable shadow target and
durable controller exposure into the existing share-level `ExecutionPlan`. It:

- aggregates filled episodes and committed pending entries/exits by permanent
  security id;
- preserves Wealth Core cash instead of renormalizing it into invested weight;
- sizes the defensive BIL sleeve separately and leaves an unavailable sleeve in
  cash;
- uses `Decimal` for quantities, prices, account values, and projected shares;
- preserves still-wanted unpriced observed quantities, including signed working
  remainders, while allowing securities genuinely dropped by the shadow to
  remain reduction targets; and
- stamps publication, data version, decision/effective session, complete
  deployment/account/corpus identity, state fingerprint, controller transition,
  and strategy fingerprint into immutable plan economics.

Broker positions do not influence Wealth Core holdings or controller exposure.
They enter only reconciliation, unavailable-price preservation, and execution
delta calculation at the execution membrane.

### 5. Preparation and current-plan inspection

Paper preparation verifies the allowlisted endpoint, certified adapter,
ownership binding, account identity, readiness, publication pin, frontier, and
complete clean reconciliation. It then loads or creates canonical state,
processes missed sessions, and adopts one latest plan. It may perform broker
reads required for account sizing and reconciliation, but has no submit, cancel,
replace, or broker-native close call. Its `dry_run` claim is specifically about
broker mutation; preparation intentionally writes durable state and plan
records.

An unbound inherited account is refused before the first broker read. Only the
explicit administrative migration path may classify and unwind that book.
Current-plan inspection is database-only and constructs no broker client.

### 6. Separately authorized paper execution

The execution command accepts no caller-supplied portfolio economics. It reloads
the journal's durable current plan and requires explicit confirmation of the
paper account, plan id, effective session, and paper submission authority. While
holding the writer lock and publication pin, it repeats ownership, account,
readiness, publication, frontier, state, strategy, session, and reconciliation
checks before delegating to the existing executor.

The existing unknown-submit, partial-fill, restart-recovery, stale-plan,
foreign-activity, and incomplete-observation behavior remains authoritative.
Reductions precede every increase. Increases wait until all required reductions
are filled and a new complete, clean observation has re-established account
facts and re-sized the remaining orders. A rejected, cancelled, absent,
partially filled, still-working, or UNKNOWN reduction cannot fund an increase.

### 7. Broker and timing boundary

The typed Alpaca adapter is certified only for the exact paper endpoint. It
submits DAY market orders and does not claim market-on-open capability. The
current operational model is therefore an operator-timed invocation during the
confirmed effective session, after the market is available. An exchange-native
opening-auction order type would require a separate adapter change and
certification.

## Oracle and artifact inventory

| Item | Runtime status | Classification |
|---|---|---|
| Corrected `sentinel_1p1_daily.csv` and summary | Not read | Historical specification/certification evidence |
| Frozen transition and breadth oracle CSVs | Not read | Targeted certification evidence |
| Standalone Python implementation | Not imported | Independently executable specification |
| Frozen rule JSON + SHA-256 manifest | Read by controller | Versioned, digest-verified runtime configuration |
| Sharadar corpus | Required through API/import | Legitimate source data; exact historical pin is external to a clean install |
| Version-3 `SessionState` | Produced/consumed by production | Canonical behavioral state |
| Durable execution plan and command journal | Produced/consumed by production | Immutable intent and recovery authority |
| Broker observation | Execution membrane only | Reconciliation and delta evidence, never alpha/controller input |

No production decision is supplied by an oracle tape. The 5,032-session
controller certification remains historical evidence; the new end-to-end
simulator and durable-boundary tests establish production wiring and restart
convergence, not a paper-deployment outcome.

## Disposition of the original findings

| Original finding | Current disposition |
|---|---|
| No runnable daily composition | Closed by `SessionState`, `advance_and_persist`, and paper preparation |
| Bootstrap is not historical reconstruction | Retained deliberately: warm-up reconstructs rolling features only |
| Shadow is not continuously advanced | Closed for operator-invoked preparation and missed-session catch-up |
| Breadth inputs are not produced | Closed by the production holdings adapter and session transition |
| SPY sensing is not wired | Closed through the published `closeadj` loader |
| Controller state is not restored or persisted | Closed in version-3 canonical state |
| Exposure remains pinned to 1.00 | Implemented as the one-time ledger-authorized initial durable rollout for an empty or recognized pre-rollout behavioral schema; controller exposure remains blocked behind an explicit certified transition |
| Execution is unreachable | Gateway implemented, but intentionally unreachable until trusted certificate issuance/signature verification is separately reviewed |
| No clean-path/restart evidence | Closed for the specified simulator and durable-boundary scenarios |
| Runtime rule lives in the handoff artifact tree | Still true; digest verification makes it explicit and reproducible |

## Remaining operational limitations

1. **Not activated.** This record does not mean the feature branch is merged,
   an image is deployed, a paper account is migrated, or any order is submitted.
2. **Paper only.** The live endpoint and all unknown endpoints remain refused;
   there is no environment override.
3. **No scheduler.** Daily preparation and final execution are separate manual
   actions. Missed sessions converge when preparation is invoked, but nothing
   invokes it automatically.
4. **DAY market timing.** The adapter does not provide MOO/OPG semantics, so the
   operator owns effective-session timing.
5. **Migration stays administrative.** An inherited book must be inspected,
   explicitly migrated, fully reconciled, and re-observed before a new Sentinel
   increase can proceed. Daily preparation never silently liquidates it.
6. **Fresh warm-up is not portfolio replay.** A deployment that must preserve an
   existing Sentinel path-dependent state must restore its canonical database;
   it cannot infer that history from prices.
7. **Historical corpus remains external.** Exact full-history differential
   reproduction still depends on access to the pinned Sharadar corpus and is
   distinct from runtime activation.
8. **System certification still blocks submission.** Execution requires a
   trusted-issuer-authenticated activation profile with zero strict xfails,
   Wealth Core `GO`, and exact runtime/source identity. No trust root or
   signature verifier exists; installation and runtime authorization therefore
   refuse all unsigned profiles, including legacy database rows. The gateway is
   implemented but intentionally non-executable.

Operator commands and expected checkpoints are intentionally not duplicated
here. `docs/sentinel-paper-activation.md` is the sole runbook.
