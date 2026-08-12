# Sentinel 1.1 production-path audit

**Audit date:** 2026-08-12  
**Scope:** clean installation through the daily allocation decision and execution handoff  
**Reference:** `docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`
and its terminal-and-issuer-corrected 5,032-session outputs

## Verdict

The repository contains most of the required components, but it does **not**
contain an actual production cold-boot-to-daily-decision path. It therefore
cannot yet demonstrate behavioral equivalence to the independently reproduced
reference.

This is an integration gap, not evidence that the individual Wealth Core,
breadth, SPY-regime, controller, or execution algorithms are wrong. The shipped
Compose application says there is no long-running engine, the CLI exposes only
read-only target/planning and one-time handover commands, and no production
caller composes the implemented seams into the daily state transition.

The minimum honest production status is therefore **components implemented,
runtime not activated, end-to-end equivalence unproved**.

## Trace of the path that exists

### 1. Installation and startup

`Dockerfile.sentinel` builds a pinned Python image, installs the locked dependency
closure and `shared/` Wealth Core package, copies the digest-verified controller
rule, and installs the `sentinel` package. `docker-compose.sentinel.yml` starts
Sentinel's PostgreSQL and the read-only panel. The `sentinel` service is a
run-only CLI profile whose default command is `status`; there is deliberately no
scheduled or long-running decision process.

Account ownership is persisted in PostgreSQL and checked against the broker.
The destructive legacy handover is an explicit `migrate-account` operation and
ordinary startup has no liquidation path. This is appropriate operational
machinery, but completing it only permits Wealth Core bootstrap; it does not
start a daily engine.

### 2. Data ingestion and publication

`feed-seed` and `feed-daily` ingest Sharadar SEP, TICKERS and ACTIONS into
Sentinel's database. Publication records create a visibility boundary: readers
cannot consume rows committed by an ingest that failed before publication.
Readiness checks gate target-book construction and reject stale, incomplete or
incoherent data. The loader maps published rows to canonical Wealth Core
`VendorBar` and `SecurityMeta` objects, including raw price domains, split and
dividend fields, point-in-time identities, issuer relations and terminal events.

This is production-needed machinery. It does not depend on a daily oracle or a
frozen output CSV. The exact pinned 32-file historical corpus remains external
data and is not a repository installation artifact, which is appropriate, but a
clean boot must be supplied with Sharadar credentials or an explicitly imported
and verified corpus before historical equivalence can be measured.

### 3. Wealth Core and state reconstruction

The `target-book` command loads a trailing window, calls `Feed.warmup` without
trading, runs one decision session and prints a fresh target at exposure 1.00.
That is explicitly a **new-book bootstrap**. It deliberately does not recreate
historical episodes, peaks, ages, cooldowns, pending orders or controller state.

The repository separately contains transaction-safe catch-up, state tables,
book-artifact serialization and restart-aware execution journals. However,
`catch_up` accepts injected `advance_state` and `decide` functions, and no
production module supplies the composition. Consequently a cold machine cannot
currently choose between (a) creating a genuinely new book, (b) restoring a
persisted book, and (c) replaying missed sessions, then advance that choice into
one authoritative daily shadow state.

### 4. Breadth and SPY regime sensing

The recovered breadth classifier is pure code and consumes Wealth Core shadow
holdings. The SPY regime sensor is pure code and explicitly requires the
total-return `SEP.closeadj` series. Both expose observation-field mappings for a
future caller. Neither reads the frozen breadth tape or transition oracle.

There is no production caller that builds the required per-holding return/age/
drawdown inputs from the live shadow state, invokes breadth for every processed
session, loads the SPY total-return window, or joins these results with shadow
returns and drawdown into a controller `Observation`. Thus the components are
codified but absent from the actual path.

### 5. Controller and allocation

The controller is a deterministic state machine with persisted-state shapes,
typed evidence, fail-closed unavailable-input behavior and the 0/55/65/100
recovery ramp. Its thresholds are read from
`docs/sentinel-handoff/00_README/FROZEN_SENTINEL_1P1_RULE.json` and verified
against the handoff SHA-256 manifest.

That JSON is a frozen **rule/configuration artifact**, not an oracle output. It
is a genuine runtime dependency today. The oracle CSVs are research and
certification evidence only and are not read by runtime code. The rule artifact
is acceptable for behavioral fidelity, but independent reconstruction would be
stronger if its normalized values were promoted to a versioned production
configuration with the same digest and schema validation, leaving the handoff
directory test-only.

Most importantly, the controller is not called by production. `TargetBook`
hard-codes exposure to 1.00, and the breadth and SPY modules both say their
forward seams do not activate the chain. No daily allocation decision is
persisted or emitted.

### 6. Execution handoff

The repository implements execution plans, scalar-to-share projection, command
journaling, idempotency, broker reconciliation, recovery and a simulator. The
catch-up layer can persist one latest plan and supersede intermediate missed-day
plans. These are production-needed components rather than historical research.

They are not reachable from a production daily runner. Compose has no engine
service, the CLI `plan` command concerns ownership/startup and submits nothing,
and `target-book` also stores and submits nothing. Therefore there is no path
that multiplies the continuously maintained Wealth Core shadow target by the
controller exposure, handles the BIL/cash sleeve, emits the execution plan and
hands it to the executor under the account/data-version/state guards.

## Oracle and artifact inventory

| Item | Runtime status | Classification |
|---|---|---|
| Corrected `sentinel_1p1_daily.csv` and summary | Not read | Historical specification/certification evidence |
| Frozen transition and breadth oracle CSVs | Not read | Superseded or targeted regression evidence |
| Standalone Python implementation | Not imported | Independently executable specification |
| Frozen rule JSON + SHA-256 manifest | Read by controller | Manual/frozen runtime configuration, verified but not independently derived at boot |
| Sharadar corpus | Required through API/import | Legitimate source data; exact historical pin is external to a clean install |
| Wealth Core book artifact | Produced/consumed by code | Legitimate persisted behavioral state, not an oracle |
| Broker observation and execution journal | Produced/consumed by code | Legitimate operational authority/audit state |

No production decision is currently supplied by an oracle tape. The more basic
problem is that production supplies no integrated Sentinel allocation decision
at all.

## Discrepancies from the 5,032-session specification

1. **No runnable daily composition.** There is no entry point from publication
   through shadow advancement, observation assembly, controller transition,
   allocation persistence, projection and execution.
2. **Bootstrap is not historical reconstruction.** The available command warms
   signals and creates a new target; it cannot reproduce the reference's
   path-dependent book or controller state from raw history.
3. **The shadow is not continuously advanced in production.** Catch-up has the
   transaction and supersession semantics, but its strategy callbacks are
   unbound.
4. **Breadth inputs are not produced from the production shadow.** The classifier
   exists, but the holdings-panel adapter and daily invocation do not.
5. **SPY sensing is not wired to the published `closeadj` history.** The sensor
   exists, but the production observation assembler does not.
6. **Controller state is not restored or persisted by a daily runner.** The pure
   transition exists; the runtime lifecycle does not.
7. **Exposure remains pinned to 1.00.** Production cannot emit the reference
   0/55/65/100 allocations.
8. **Execution is implemented but unreachable from a daily decision.** There is
   no authoritative decision-to-plan-to-executor handoff.
9. **No clean-install equivalence test exists.** Component and simulator tests
   cannot establish the 5,032 sessions, exact summary, 722 buys, 1/5 terminal
   blocks, or 7,188/0 issuer invariant result through the production path.
10. **The runtime rule still lives in a handoff artifact tree.** It is digest
    protected and not an oracle, but it is the remaining manually supplied
    strategy input rather than production-owned configuration.

## Minimum work, in dependency order

1. **Define one production session-state envelope.** Version and persist Wealth
   Core shadow state, pending orders, controller state/history, last processed
   session, data version and strategy identity together. Reuse the existing
   book artifact and journal formats; do not invent a second Wealth Core.
2. **Implement `advance_state`.** For each published missed session, restore the
   prior envelope, run canonical Wealth Core in its fixed ordering (including
   terminal and issuer rules), derive the holdings panel, breadth, SPY regime,
   shadow returns/drawdown and controller observation, call `controller.step`,
   and atomically persist the next envelope and evidence.
3. **Implement `decide`.** Convert the latest shadow target and controller Core
   exposure into the existing share-level projection, including BIL/cash,
   affordability, missing-print and unpriceable rules. Stamp the plan with the
   state identity and corpus publication version.
4. **Add one daily runner and explicit CLI dry-run.** Bind those callbacks to
   `catch_up`, reconcile the broker, persist/supersede exactly one current plan,
   and invoke the existing executor only after ownership, freshness and
   idempotency guards. Add it as a long-running/scheduled Compose service only
   after the dry-run path is certified.
5. **Promote the rule configuration.** Copy the exact normalized rule into a
   production-owned, versioned config location while retaining digest/schema
   checks; keep handoff CSVs and historical outputs outside the runtime image.
6. **Build a production-path differential harness.** Run the new composition in
   execution-simulator mode over the exact pinned 32-file corpus and compare
   every session's shadow state, breadth, regime evidence, controller state,
   allocation, trades, terminal blocks and issuer invariant checks against the
   corrected reference. Summary equality alone is insufficient.
7. **Certify restart boundaries.** Repeat from empty database, restored snapshot,
   mid-catch-up, mid-ramp, pending-entry, partial-fill and stale-publication
   states. Prove identical final state and commands, then perform a paper-only
   cold boot with execution disabled before enabling submission.

Until steps 1–4 exist, production Sentinel is not independently reconstructible.
Until steps 6–7 pass, behavioral equivalence to the 5,032-session specification
is not demonstrated.
