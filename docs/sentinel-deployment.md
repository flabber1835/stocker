# Sentinel — operational deployment ground truth

**Status: DIRECTION SET 2026-08-09. Stocker is retired as a runtime. Sentinel is
the operational target. Paper trading only.**

This document supersedes, in the places named below, both
`docs/sentinel-architecture.md` and the retirement note in `CLAUDE.md`. Where it
conflicts with either, this file wins. Where it conflicts with the **frozen
research harness** (`docs/sentinel-handoff/`), the harness wins — see §3.

Read `docs/sentinel-architecture.md` for the architecture. Read this for what is
being deployed, in what order, and what "done" means.

---

## 1. Stocker is retired

Stocker is no longer the production runtime. Concretely:

```text
DO NOT   add operational behaviour to Stocker services
DO NOT   design a migration that depends on Stocker continuing to run
DO NOT   restart Stocker in order to unwind its own book (see §5)
DO       keep the repository and its history — it is the source of proven
         broker plumbing, ingestion, fixtures, invariant tests and the
         canonical Wealth Core implementation lineage
```

The invariant tests are the most valuable thing being retained: they encode
outages that actually happened. Mine them; do not re-derive them.

### `stocker-base` is a BUILD ARTEFACT, not the retired runtime

The name misleads and has already caused one round of confusion, so state it
plainly: `stocker-base` is the image built by `Dockerfile.base` that packages
the `shared/` Python package — including the canonical Wealth Core modules.
**Rebuilding it is `docker build`. It starts no service and revives nothing.**

```text
RETIRED RUNTIME     docker-compose.yml — scheduler, pipeline, trade-executor,
                    av-ingestor, risk-service, api, dashboard. None of these
                    start again
CERTIFICATION RIG   docker-compose.backtest.yml — bt-engine + bt-postgres.
                    These hold the Sharadar corpus and the rehearsal endpoint.
                    Item D in §12 CANNOT run without them. Running the rig is
                    not running the runtime
BUILD ARTEFACT      stocker-base:latest. A layer, not a process
```

A `shared/` change that adds a NEW module file is invisible to every service
until this image is rebuilt — the editable install caches the module list — so
the rebuild is mandatory before any parity claim or rehearsal. That requirement
is unchanged by the retirement, because it is a property of the build, not of
the runtime.

**RENAME PENDING** (owner decision 2026-08-09): the artefact should be called
something like `wealth-core-base` so the ownership boundary is unmistakable.
Deferred rather than done, and deliberately: the name appears 27 times across
`build.sh`, `up.sh`, `deploy-all.sh`, `deploy-wealth-core.sh` and
`docker-compose.override.yml` — i.e. throughout the path that runs the
rehearsal. Renaming it immediately before an overnight run trades a naming
improvement for a deploy-path regression. Do it after item D closes and before
item E, as one mechanical commit with a smoke check.

## 2. Paper trading only

Alpaca paper. No real money, and **real-money concerns stay off the critical
path** — no brokerage authorisation workflow, no live-trading gates to design.

This lowers financial risk. It does not lower the engineering bar. The purpose of
the paper deployment is to validate an architecture we may eventually trust with
money, so it must have deterministic state, restart safety, auditability and
correct execution semantics from the start.

**Do not build a throwaway "paper-only strategy implementation."** The semantics
deployed here are the semantics intended to survive.

## 3. The frozen oracle outranks the prose

`docs/sentinel-architecture.md` §7/§7a were transcribed from prospectus PDFs.
They are for orientation. The frozen research harness — the rule JSON, the exact
daily oracle, the transition oracle — is authoritative wherever the two differ,
and Sentinel must be **certified against the transition oracle**, not against a
reading of the document.

The one place this has already bitten: the retained 1.1 candidate carries the
**zero-gate recovery ramp**, so a canonical severe recovery is not `0% → 100%`.
It is:

```text
0.0  ->  0.55 Core / 0.45 BIL
     ->  0.65 after 10 consecutive canonical healthy closes
     ->  1.00 after another 10
renewed canonical severe evidence at any point  ->  0.0, ramp abandoned
```

§7a of the architecture doc states this correctly. It is repeated here because
"recovery means going back to fully invested" is the intuitive reading and it is
wrong.

## 4. Steps 0–2 are RESOLVED

`docs/sentinel-architecture.md` §8 and §11 describe steps 0–2 as blocking. That
assessment is **stale as of 2026-08-09**.

```text
0  frozen harness      RESOLVED. docs/sentinel-handoff/
1  scalar vs share     RESOLVED. SCALAR allocation overlay on an immutable,
                       continuously running Wealth Core shadow. There is NOT a
                       second share-level Wealth Core state machine on the
                       live/paper side
2  breadth semantics   RESOLVED. The recovered classifier reproduces the frozen
                       breadth oracle exactly: 7,061/7,061 sessions on GREEN and
                       on AMBER/damaged, over 160,715 holding-days
```

**Why step 2 is accepted as resolved rather than merely claimed.** The
classifier was recovered mathematically AND independently corroborated by the
retained Sentinel source: `docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`
was reconstructed by a different route and contains the same predicates.

That corroboration was briefly strengthened to a measurement: the earlier
package's 20-year output matched the frozen oracle 5,032/5,032 on allocation and
on damaged/green breadth, verified in this repository. **That measurement now
describes a SUPERSEDED book.** The terminal-order correction (2026-08-09) showed
the replay had bought a security on its own delisting date and had spent five
admission slots on securities already terminated at the close, so the shadow it
produced — and every breadth value read off it — was wrong.

What survives is the part that matters for step 2: **the CLASSIFIER is
unchanged.** The same predicates run on a corrected holdings panel and therefore
produce different values. Breadth semantics are resolved; the tape they were
first checked against is not the tape to check against now.

Still **owed**, and item F below is where it lands: (a) OUR breadth engine
reproducing the CORRECTED tape
(`docs/sentinel-reference-implementation/sentinel_1p1_daily.csv`), and (b)
re-deriving that tape from the raw corpus rather than trusting a shipped CSV.
See `docs/sentinel-reference-implementation/PROVENANCE.md`.

The unrecovered `priority` formula is **not** a Sentinel blocker. It belonged to
the experimental Selective Survivor Firewall's cohort ranking. Sentinel consumes
`mean(amber)` and `mean(green)`, both now exact. See
`docs/sentinel-architecture.md` §8, "which strategy that blocks".

### The recovered semantics, normative

```python
green = ((own_dd > -0.075) & (r21 > 0.0)
         & ((age_sessions < 63) | (r63 > 0.0)))
red   = (own_dd <= -0.10) & (r21 < 0.0)
sector_stress = mean(red) within each sector on the decision date
amber = ((own_dd <= -0.10) | (r21 <= -0.03)
         | ((sector_stress >= 0.50) & (~green)))
```

Boundaries are asymmetric on purpose: GREEN strict, RED strict, AMBER inclusive.
**Preserve the original lag-price precision behaviour** — the retained replay
stored lag closes in float32 before dividing. A float64 reimplementation will
disagree on boundary rows, and every boundary here is strict-vs-inclusive.

## 5. First operational requirement — retire the legacy paper book

An Alpaca paper portfolio exists that Stocker created. Sentinel takes ownership
of account initialisation.

**Neither of the obvious routes is acceptable:**

```text
restart Stocker to liquidate     rejected — Stocker is retired; reviving it to
                                 unwind itself makes the retirement conditional
use Stocker's target/orphan path rejected — orphan_confirmation_days = 2 is
                                 ordinary target-management hysteresis. A
                                 deliberate platform migration is not a rank
                                 change and must not wait two builds for one
```

Sentinel therefore owns an explicit, one-time startup liquidation:

```text
SENTINEL START
      |
      v
CONNECT TO ALPACA PAPER ACCOUNT
      |
      v
READ ACTUAL POSITIONS + OPEN ORDERS + CASH
      |
      v
LEGACY POSITIONS PRESENT? --no--> FLAT_CONFIRMED
      | yes
      v
CANCEL INCOMPATIBLE LEGACY OPEN ORDERS
      |
      v
ISSUE LEGACY_STOCKER_BOOK_LIQUIDATION INTENT
      |
      v
DELTA / RISK / EXECUTOR  ->  ALPACA PAPER SELL ORDERS
      |
      v
RECONCILE FILLS
      |
      v
ACCOUNT FLAT? --no--> retain pending intent, retry, re-reconcile
      | yes
      v
FLAT_CONFIRMED  (PERSISTED)
      |
      v
INITIALIZE SENTINEL / WEALTH CORE PAPER STATE
```

### Rules this sequence must satisfy

```text
TYPED REASON      LEGACY_STOCKER_BOOK_LIQUIDATION — its own reason code. It is
                  NOT a Wealth Core sell signal and NOT a Sentinel severe-stress
                  decision, and must never be readable as either in the audit
BYPASSES          the orphan-confirmation timer
IDEMPOTENT        a restart mid-liquidation submits no duplicate orders
NON-DESTRUCTIVE   a restart AFTER flat does not liquidate the newly initialised
                  Sentinel book. This is the dangerous one: the same code path
                  that empties a legacy book will happily empty a live one
RECONCILED        account state is re-read from Alpaca before every retry;
                  never act on a cached view
PERSISTED         the FLAT_CONFIRMED transition survives restart
GATING            Wealth Core does not bootstrap until reconciliation has
                  reached an explicitly acceptable state
```

The ownership boundary this buys:

```text
everything before FLAT_CONFIRMED   legacy Stocker paper state
everything after  FLAT_CONFIRMED   Sentinel-owned paper state
```

## 6. Wealth Core is staged BEFORE Sentinel controls exposure

First operational milestone: **Wealth Core running correctly in the Sentinel
runtime with the Sentinel actuator pinned to 1.00.**

```text
Wealth Core shadow
      |
      v
Sentinel actuator, temporarily pinned to 1.00
      |
      v
execution projection
      |
      v
Alpaca paper book
```

This is not the final system. It is the cleanest way to certify the feed, the
planning, the state persistence, the execution and the reconciliation before
anything is allowed to vary exposure.

Once it works, enabling the controller changes **how much** of an
already-certified Wealth Core target is executed. It must never change **what**
Wealth Core wants to own.

## 7. The shadow-independence falsifier, stated correctly

The weak version — "Sentinel disabled equals Sentinel at 100%" — proves almost
nothing, because both runs execute the same basket. The falsifier is:

```text
run A   Sentinel disabled, normal full exposure
run B   Sentinel live exposure FORCED to 0% for an interval

assert the Wealth Core SHADOW is bit-identical across A and B:
  state, NAV, holdings, episodes, peaks, slot state, cooldowns,
  review state, corporate-action/terminal state, pending actions, hashes
```

The paper account may be completely different between the two. The shadow must
not know or care. What this proves is the **dependency direction**:

```text
PROVEN     Wealth Core shadow -> Sentinel -> broker
FORBIDDEN  broker -> Sentinel -> Wealth Core shadow
```

Realised broker exposure is never an input to Sentinel state. Sentinel judges the
immutable shadow plus its own event memory.

## 8. Live-data readiness is a gate, and "126 rows" is not the test

Before Wealth Core creates its first paper portfolio, prove the operational feed
satisfies the **data contract**, not a row count:

```text
canonical market sessions available
exact CONTINUOUS 126-session history for eligibility
enough history for the formation-volatility calculation
signal-close availability
raw / as-traded OPEN availability
raw mark-close availability
volume / ADV history
security identity and sector metadata
corporate-action continuity
```

**252 sessions is the preferred startup window** — it comfortably covers the
Wealth Core and Sentinel rolling features with margin.

**Warm-up reconstructs rolling features. It does not reconstruct path-dependent
portfolio state.** Once a book exists, episode peaks, ages, review flags,
cooldowns, pending actions and event memory come from the persisted
snapshot/replay contract — never inferred from price rows. Inferring them would
produce a fresh, looser peak on every restart: a risk control failing silently
toward less protection.

## 9. Price-domain validation must be Wealth-Core-specific

Do not assume live's Alpha-Vantage-adjusted `daily_prices` is equivalent to the
Sharadar corpus Wealth Core was certified on. Wealth Core deliberately separates
price domains; validate each one:

```text
split-adjusted / dividend-unadjusted signal close
split-adjusted stop peak
raw / as-traded execution open
raw / as-traded mark close
volume, splits, dividends, terminal corporate actions
```

This matters most for the **30% holding-episode trailing stop**: a different
adjusted-price history produces a different peak and therefore a different exit.
Live's `adjusted_close` is AV-VINTAGE (re-based only when AV restates); Sharadar's
is UNIFORMLY restated. Swapping one for the other is a strategy change arriving
as a data change.

**Report discrepancies. Do not silently normalise them away.**

## 9a. Exactly ONE mutable corpus, eventually

**The principle** (owner decision, 2026-08-09):

> There must eventually be exactly ONE mutable authoritative corpus. Historical
> certification corpora may exist only as IMMUTABLE VERSIONED ARTIFACTS.

Today there are two Postgres instances holding the same economic history:

```text
bt-postgres        the certification corpus. ~35M rows. What the golden hash and
                   the 2021-2023 rehearsal are measured against
sentinel-postgres   the operational corpus, owned by the new runtime
```

**Keep them separate while the golden pin is open.** That is the safety
property, and it is specific: an ingestion change, a schema migration or an
accidental refresh must not be able to move the evidence underneath the
certification exercise. A corpus that shifts while a hash is being certified
against it makes the hash meaningless.

**After the re-pin lands and Sentinel's data-contract path is proven**, converge:
the Sentinel database becomes the sole continuously maintained source of truth,
and the bt corpus is **FROZEN, not deleted** — a read-only snapshot that records
exactly what data produced certification hash X. Frozen, it is not a second
database in any operational sense; it is an artifact.

The danger being eliminated is **two independently EVOLVING corpora of the same
economic history**, because that is where divergence becomes both possible and
invisible. It is not "two Postgres processes".

**A correction, recorded because the wrong version of this argument was made in
review.** Sentinel reading from the same PostgreSQL *server* would not by itself
make Stocker a runtime dependency. Dependency is about OWNERSHIP AND INTERFACES,
not about the name of a process. A single instance with separate databases and
roles is a clean boundary and is probably simpler to operate:

```text
sentinel_runtime      RW   sentinel
certification_runner  RO   certification_2026_08
retired_stocker            disabled — no runtime consumers
```

What must remain true is that no Sentinel code path depends on a Stocker
SERVICE, and that the certification snapshot has no writer.

**Do not attempt the merge mid-certification.** Converge deliberately, after the
pin closes — the whole point of the current exercise is a hash that moves
exactly once.

## 10. Finish the three-year rehearsal, and do not reduce it to CAGR

The 2021-2023 chain rehearsal is one of the highest-value acceptance tests.
Finish it before declaring the alpha engine operational, and compare behavioural
artefacts:

```text
candidate decisions, admissions, fill dates, fill prices, holding episodes,
review decisions, trailing-stop exits, corporate actions, cash, positions,
NAV, pending actions, state hashes, ledger hashes, decision hashes
```

Any unexplained divergence blocks a Wealth Core paper-parity claim. A CAGR that
looks reasonable is not evidence; the settlement counters and the hashes are.

## 11. `execution_model` activation is a versioned operational event

If enabling the Wealth Core / Sentinel path requires changing a protected
`execution_model`, do it deliberately and record:

```text
previous_execution_model, new_execution_model, strategy_fingerprint,
git_sha, image_digest, timestamp, reason, operator
```

**No deployment default or environment variable may silently flip execution
semantics.** This is the same class of defect as a `mem_limit` that lives only in
configuration: a setting believed to be in force, that is not.

## 12. Implementation order

```text
A  Freeze Stocker. No new features. Preserve history for lineage
B  Sentinel startup ownership: connect, inspect, liquidate the legacy book,
   reconcile to flat, persist FLAT_CONFIRMED, restart-safe and idempotent
C  Verify operational data against the §8 contract (252-session preferred)
D  Finish the Wealth Core rehearsal; require EXPLAINED behavioural parity
E  Wealth Core in Sentinel with exposure pinned to 1.00 — paper only, full
   persistence, order/fill reconciliation, restart tests, daily hashes
F  Install the exact recovered breadth engine, preserving numerical
   semantics, with boundary fixtures.
   THE ACCEPTANCE TARGET CHANGED 2026-08-09 and the old wording is void.
   "Reproduce the frozen tape" was discharged against the SUPERSEDED
   lineage (5,032/5,032 allocation and breadth parity, measured in this
   repo) — and the terminal-order correction then changed the shadow book,
   so the corrected path diverges from the frozen oracle by construction:
   breadth from 2016-02-05, allocation on 20 sessions from 2025-04-08.
   The CLASSIFIER is unchanged and still exact; its INPUT book is not.
   Restated target: our breadth engine must reproduce
   docs/sentinel-reference-implementation/sentinel_1p1_daily.csv — the
   corrected lineage — on the same holdings panel. The frozen oracle stays
   as the audit artifact for the OLD lineage and is not overwritten.
   That file has since moved again (terminal + ISSUER corrected, 2026-08-09):
   the issuer-identity parse removed a simultaneous GOOG/GOOGL holding. The
   Sentinel allocation path is unchanged by it; the Wealth Core book is not
G  Implement the frozen controller: ordinary-stress memory, fast severe, slow
   severe, independent cause/recovery memory, typed evidence records, FAIL
   CLOSED on unavailable required evidence
H  Implement the 1.1 recovery ramp against the frozen zero-gate oracle;
   reproduce transition dates and 0/55/65/100 allocations exactly
I  Share-level execution projection:
       desired basket = shadow target x Sentinel target Core exposure
   Integer shares, affordability, missing prints, pending legs, BIL sleeve,
   costs and reconciliation belong HERE, never inside Wealth Core
J  Extend snapshot/restart certification across every new object
```

Restart tests must cover: fast severe, slow severe, both, mid-ramp, partially
executed, and while the shadow and paper books intentionally differ.

## 13. Definition of the first milestone

Not "Sentinel produced orders." This:

> Stocker is shut down; Sentinel starts against the Alpaca paper account, safely
> and idempotently removes the legacy Stocker paper portfolio, establishes a
> clean persisted ownership boundary, boots the canonical Wealth Core engine from
> valid data, and thereafter maintains a deterministic 100%-exposure Wealth Core
> paper book with correct decisions, next-open execution, reconciliation and
> restart behaviour.

Only after that milestone passes does the Sentinel risk controller get activated
and certified against the frozen oracle.

**Do not redesign the strategy while doing this work.** The research stage is
over for this deployment path. What remains is faithful implementation,
operational separation, and falsifiable certification.
