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

**The engine itself now exists — `sentinel/breadth/` — which changes what is
owed, not whether anything is.** It is transcribed from the standalone source,
boundary-falsified, mutation-checked and cross-checked by a randomised
differential against the stored artefact on every test run. None of that is
tape reproduction: it proves the transcription faithful, not the lineage
reproduced. Both (a) and (b) still require the NAS and the authoritative corpus,
and `UNCERTIFIED_BREADTH` stands until they land. See
`docs/sentinel-controller-certification.md` §7d for the exact split.

`priority` is **not** an open Sentinel item, and it is worth being precise about
what it is instead. The historical `position_features()` helper returned more
than Sentinel consumes; `priority` was a per-name cohort ranking in that return
surface, used by the experimental Selective Survivor Firewall and by nothing
else. Sentinel's breadth dependency is `mean(amber)` and `mean(green)`, and the
logic producing both is recovered and codified. So an incomplete reconstruction
of the old helper is exactly that — it is not a Sentinel gap, blocker, runtime
dependency or unresolved breadth issue. See `docs/sentinel-architecture.md` §8,
"an unused output of the historical helper".

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

Sentinel therefore owns an explicit, one-time **operator-invoked migration**.
It is not an ordinary startup action. `prepare-paper-plan`,
`current-paper-plan`, `execute-paper-plan`, Compose startup, and the panel have
no path to it. Only the separately named `migrate-account` command may enter
this state machine, and it refuses a bound account before its first broker
call:

```text
OPERATOR INSPECTS THE NAMED PAPER ACCOUNT
      |
      v
STAGE + ACTIVATE AN OFFLINE-SIGNED ADMINISTRATIVE CERTIFICATE
FOR THE EXACT PROPOSED DEPLOYMENT / ACCOUNT / EPOCH 1
      |
      v
EXPLICIT migrate-account --expect-account <ACCOUNT_ID>
      |
      v
REFUSE IF ANY SENTINEL BINDING EXISTS
      |
      v
READ ACTUAL POSITIONS + OPEN ORDERS + CASH
      |
      v
LEGACY POSITIONS PRESENT? --no--> STABLE FLAT CHECK
      | yes
      v
CANCEL THE NAMED LEGACY OPEN ORDERS
      |
      v
DURABLY JOURNAL ONE ACCOUNT-BOUND, EXACT-SIZED SELL PER LEGACY POSITION
      |
      v
RE-OBSERVE; RE-RUN EXPLICITLY AFTER A CRASH IF STILL UNBOUND
      |
      v
REQUIRE TWO CONSECUTIVE AGREEING FLAT READS
      |
      v
COMMIT FLAT/OWNERSHIP EVENTS + ACCOUNT BINDING TOGETHER
      |
      v
STOP. A SEPARATE prepare-paper-plan MAY NOW ADOPT A PLAN
```

Migration uses the same recoverable command-identity law as ordinary execution:
each exact-sized SELL and its account/epoch-bound client key are durable before
transport, and an uncertain submit remains `UNKNOWN` until exact-key recovery.
The administrative command remains separate because it removes a book Sentinel
did not create; it may not be used for daily target maintenance. A short,
missing-side, or otherwise malformed inherited position refuses migration rather
than expanding exposure. The separately authorized production plan continues
through the durable executor only.

The inspection and handover commands are not exceptions to signed runtime
authority. Before a binding exists, the operator stages and activates a
certificate whose signed operation set is limited to `ADMIN_INSPECT` and/or
`ADMIN_MIGRATE` and whose subject names the proposed deployment, exact paper
account, and epoch 1. `inspect-paper-account` and `migration-plan` therefore
require both `--deployment-id` and `--expect-account`; neither can infer the
future deployment from credentials. `migrate-account` requires the separate
`ADMIN_MIGRATE` operation. A restored-host adoption uses a fresh
`ADMIN_ADOPT` certificate naming the exact current deployment/account/epoch.

Certificate staging, activation, and revocation contact no broker. The active
administrative certificate is verified before broker construction, around
each broker read, and immediately before every exact-id cancel or durable named
SELL. Its operations are structurally disjoint from ordinary paper execution,
and a signed admin certificate cannot authorize `execute-paper-plan` or the
automation service. The committed trust-root file remains disabled in this
change, so real administrative broker commands continue to refuse until formal
certification and reviewed root enrollment occur.

### Rules this sequence must satisfy

```text
TYPED REASON      LEGACY_STOCKER_BOOK_LIQUIDATION — its own reason code. It is
                  NOT a Wealth Core sell signal and NOT a Sentinel severe-stress
                  decision, and must never be readable as either in the audit
BYPASSES          the orphan-confirmation timer
IDEMPOTENT        an explicit re-run after interruption resolves every durable
                  exact client key before acting on the remaining inherited book
NON-DESTRUCTIVE   after binding, migrate-account refuses before broker contact;
                  ordinary startup can never re-arm the migration
RECONCILED        account state is re-read from Alpaca before every retry;
                  never act on a cached view
PERSISTED         the FLAT_CONFIRMED transition survives restart
GATING            canonical preparation cannot adopt an executable plan until
                  the binding exists and a further typed execution-adapter
                  reconciliation is COMPLETE, RUNNING, and clean
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

The stage is executable state, not an operator convention. Behavioural
PostgreSQL owns a versioned rollout row that is created as `PINNED_1_00`.
Preparation in that mode stamps an exposure of exactly `1` into the durable
plan even though the controller continues to advance in the canonical shadow.
The controller's transition remains recorded for audit and restart equivalence;
it does not become execution exposure until the rollout mode changes.

`PINNED_1_00` describes the actuator, not a low-risk posture. An explicit
transition from `CONTROLLER` back to `PINNED_1_00` can move exposure from 0,
0.55, or 0.65 to 1.00 and therefore **increase** risk. It is never labelled a
de-risking action and its CLI confirmation names that exposure-increase risk.
The rollout singleton is seeded only by the first versioned behavioral-schema
migration on a behaviorally empty database or a recognized pre-rollout schema.
Table absence alone is never upgrade evidence. The one-time compatibility
bridge for the complete intact schema shipped at `6113bffd` records the
migration version without changing its existing rollout row, history,
certificates, plans, or account state. A missing row, missing rollout table,
mixed old/new fingerprint, or missing/corrupt migration ledger is corruption;
routine startup refuses rather than recreating or resetting operational
intent. Inspection, DDL, the initial seed, and the migration record are
serialized by one transaction-scoped advisory lock and commit atomically.
Complete loss of every behavioral relation is indistinguishable inside an empty
catalog from a genuinely new deployment. Before the one-time 6113 bridge has
installed its ledger/witness, simultaneous loss of every rollout/certificate
table and plan-stamp column can likewise resemble the exact pre-rollout schema.
Do not use table-selective restores; preserve database/volume identity and
restore the whole verified backup so that all migration witnesses cannot vanish
together.

The transition is deliberately separate from daily preparation. An
operator-confirmed SHA-256 authenticates manifest bytes, not the issuer of the
`PASS`/`GO` statements inside them. The signed offline issuer and runtime trust
contract lives in `sentinel-stage-4-automation.md`; the current NO-GO and strict
xfails mean no real certificate may be issued in this work. Consequently, until
later formal certification and real public-root enrollment:

```text
install-system-certificate       refuses every unsigned/untrusted certificate
set-paper-rollout-mode CONTROLLER
                                 refuses without a valid signed certificate
execute-paper-plan               refuses before broker read without that chain
```

The refusal applies to unsigned rows installed by an older build or restored
from backup as well as to new operator-authored files. Service installation is
also inert: Stage 4 starts disabled and killed. Certificate installation,
automation activation, and kill release are three separate audited boundaries.

The current certification harness also does not emit an activation profile
while the known strict xfails and Wealth Core `NO-GO` remain. Even after those
evidence gaps are resolved, a signed profile must explicitly allow
`CONTROLLER` and record controller certification `PASS`; changing mode will
then increment the rollout version and require a newly prepared plan. A
previously durable plan must remain stale even if its numeric target is 1.00.

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

### 8a. Production snapshots persist a bounded restart image, not feed history

`SessionState` is the authoritative one-session production envelope. Its feed
member exists only to continue the next deterministic calculation; it is not a
second copy of the versioned Sharadar corpus and must not grow as sessions pass.

The production snapshot schema therefore persists an explicitly bounded feed
restart image:

```text
global session index            absolute and monotonic across restarts
recent session/index map        current plus exactly 126 prior market sessions
active per-security anchor      security id, current ticker, current issuer id,
                                cumulative split factor, retained only while
                                rolling or path-dependent state needs it
per-security rolling evidence   observations whose GLOBAL index is inside that
                                same 127-session window: session, index, signal
                                close, raw close and volume
```

The 127-session bound is derived rather than tuned. Wealth Core needs closes
from `t-126` through `t` inclusive for eligibility, momentum and formation
volatility. That window strictly contains the 20-session ADV input and
Sentinel's 21/63-session holding breadth inputs. Controller NAV, breadth and
completed-stop histories remain in their already-bounded top-level fields; SPY
inputs remain published session inputs. No production calculation reads an
older feed observation.

Expiration is by **global market-session index**, not by a security's row count.
At a boundary, the observation at `t-126` remains and `t-127` is discarded.
Anchor ownership follows the same bounded-restart rule: keep an anchor when its
series still has a retained observation, or when the security is named by
authoritative path-dependent state. The latter includes a filled episode, a
reserved slot or pending order, a security cooldown, and every unresolved or
pending terminal/mark-carry record. `last_known` is a raw-mark cache, not a
second market-data history, and is retained only for that path-dependent set.
This keeps dormant universe members out of both maps without pruning a security
whose next transition can still depend on its identity, split basis or stale
mark.

An evicted security may later print again. The production loader must then
reconstruct the missing anchor from the **pinned corpus before** handing the
session to Wealth Core: multiply every earlier published `split_ratio` for that
permanent security id in session order, and resolve the issuer from the pinned
security metadata. The query also proves whether any earlier published
observation exists, so a genuine first observation may begin at factor `1.0`.
If an earlier observation exists but either the split basis or issuer identity
cannot be reconstructed, production fails closed. It must never take the
canonical feed's new-series defaults for a returning security, because doing so
would silently rebase its signal series or replace its issuer identity. A
retained path-dependent anchor remains authoritative until that state clears;
corpus reconstruction is only the re-entry path for an anchor already evicted.

The persistence wrapper must canonicalise the prior envelope **before** asking
the loader which current securities need corpus anchors. This sequencing is
part of the restart contract, not an optimisation: a v2 or early-v3 envelope
can still name a dormant series that migration will evict. Letting that raw name
suppress corpus reconstruction and only then pruning it creates a first-upgrade
restart failure exactly when the security returns. The loader's known-security
set therefore comes only from the migrated, bounded feed image, and that same
canonical envelope is the input to the session transition.

Every persisted series that survives canonicalisation has a complete anchor.
`security_id`, ticker, issuer id and cumulative split factor are required stored
fields; the id must match the series-map key, labels must be non-empty, and the
factor must be finite and positive. Loading never manufactures `S:<id>` or
`1.0` for a retained rolling or path-dependent series. An incomplete legacy or
current envelope fails closed because guessing either value can change issuer
exclusivity or silently rebase every subsequent signal close.

The boundedness contract applies to the feed restart image, `last_known`, and
the other explicitly rolling caches. The top-level Wealth Core ledger is an
immutable event history and intentionally grows when economic events occur.
Therefore a quiescent or cache-only workload reaches a byte plateau after
warm-up, while an envelope that continues posting ledger events grows only by
those intentional events; the contract is not that every possible envelope is
byte-constant.

The evidence record is diagnostic, not authoritative state. `last_evidence`
stores the observation, breadth inputs and a whitelisted plan summary, but never
the plan's `state_after` or `pending_after` copies. Wealth Core state and pending
orders exist exactly once, in the envelope's top-level `wealth_core` and
`pending` fields.

Snapshot schema v3 introduces this representation. A v2 envelope is migrated on
load by deterministic pruning because it contains the same feed fields plus
older observations and dormant anchors/marks; its embedded plan copies are
removed at the same boundary. Early v3 envelopes are canonicalised by the same
retention pass, so deploying the cardinality bound requires no parallel state or
one-off rewrite. Complete anchors are a migration precondition rather than a
field-defaulting opportunity. The migration changes storage shape only and must
prove continuation parity against an uninterrupted run, including the case
where a just-evicted security returns on the first upgraded session. V1 remains
explicitly refused because it lacks lifetime shadow-peak and completed-stop
event memory and cannot be repaired from a short history window.

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

### 10a. A result is evidence only if the environment is NAMED

Once corporate actions are placed through an exchange calendar, "the same code
and the same corpus" no longer identifies the computation. The calendar decides
what the next valid session is; that placement decides which session a dividend
or a split lands on; that lands cash and shares in the book. **The calendar
implementation is part of the strategy's data contract**, and so is the
interpreter that runs it and the base image that carries both.

So every certified run records, before it starts:

```text
python version                    exact, and whether it is the certified one
base image digest                 Dockerfile.sentinel pins by @sha256, not by tag
exchange_calendars, pandas,       exact, from sentinel/requirements.txt, with any
numpy, tzdata, and the rest       DRIFT from the pin file named per package
calendar exchange + version       the authority the sessions came from
sentinel source hash              hashed separately from Wealth Core: they are
wealth core source hash           certified against different things
vendor corpus hash                sentinel_actions + sentinel_universe
normalised corpus hash            sentinel_bars over the certified interval
```

```bash
$COMPOSE run --rm sentinel \
  identity --require-certified --start 2021-01-04 --end 2023-12-29
```

**The database is part of the certified environment.** With a corpus requested,
`--require-certified` REFUSES a Postgres that is not the pinned 16.14 — the
corpus digests are produced by reading rows back out of that server, so a minor
upgrade can move `corpus_hash` without a single row changing. A warning would
have been the wrong shape: it prints, and then the run proceeds.

**The whole dependency closure is fingerprinted and artifact-hash LOCKED.**
`requirements.txt` pins the direct dependencies; pip resolves everything
underneath them, so two builds can declare identical versions and install
different closures. `identity` therefore hashes every installed distribution and
folds it into `identity_hash` — two differing closures can never be mistaken for
one environment. That makes them *distinguishable*; `sentinel/requirements.lock`
is what makes them *reproducible*:

```bash
scripts/sentinel-lock.sh          # resolve the closure and emit SHA-256 hashes
git add sentinel/requirements.lock && git commit
# rebuild — the Dockerfile requires the lock — and verify the image identity
```

The Dockerfile has no unlocked or version-only fallback. It installs with
`--require-hashes --only-binary=:all:` and normal TLS verification; a missing
hash, changed artifact, source-only release, or missing lock fails the image
build. **`sentinel-certify.sh` also stops on a missing or unhashed lock before
the truncate.** A refusal that comes after an irreversible step is not a
refusal. The harness stores `distributions_hash` and still fails if the loaded
closure differs from the previous certified environment.

**The lock is bound to the IMAGE, not to the checkout.** `identity` reports
`image_lock_sha256` — the digest of the lock file baked in at `/tmp/req` — and
the harness requires it to equal the checkout's. `--verify-only` does not
rebuild, so without that binding an old image could pass beside a newly edited
lock. The committed hash list is the reviewed trust decision; regeneration is a
dependency change and requires the same review and certification as a pin
change.

**Host orchestration has its own compatibility boundary.** The application and
test images remain Python 3.12.13. The NAS shell entry points and the Python
utilities they invoke support host Python **3.8.15 or newer**. Certification
runs a semantic preflight through that host interpreter before any image build,
push, corpus mutation, or evidence publication. The preflight imports the real
host evidence producers and exercises their immutable RepoDigest parsers; a
version check alone would not have falsified the Synology failure.

### 10d. The record must name the BUILT IMAGE, not only its inputs

`sentinel identity` describes the environment inside the container. It cannot
describe the image — a process has no reliable way to discover the id of the
image it is running in — and the image is the artefact being certified.
Everything else (base digest, package closure, source hashes) describes INPUTS
to a build.

So `scripts/sentinel_manifest.py` assembles the rest on the HOST, into
`artifacts/sentinel/manifest-<window>.json`:

```text
git_commit + git_tree_clean          a dirty tree invalidates the commit line
sentinel_runtime_image  id + digest  the artefact
sentinel_test_image     id + digest  what the suite actually ran in
postgres_image          id + digest
identity_hash, distributions_hash, requirements_lock_sha256
sentinel_source_hash, wealth_core_source_hash
corpus_hash, book_artifact_sha256, rejection_audit_sha256, rehearsal_hashes
```

The last four are `null` until later steps fill them, so an incomplete manifest
is visibly incomplete rather than a differently shaped object.

`repo_digests` is empty until the image is pushed, and is recorded as a field
anyway: **deploying to another machine must go by immutable registry digest**,
not by rebuilding from the same Dockerfile and calling the result equivalent.
That assumption is exactly what the pins, the lock and this manifest exist to
remove.

Build, promotion, and certification are therefore separate supported phases.
The build phase never claims registry identity. The push phase tags the exact
local runtime and test image ids with the source Git SHA, pushes those tags, and
atomically retains the resulting RepoDigests. The verify phase refuses mutable
tags and runs identity, source comparison, the Sentinel suite, and manifest
assembly through the retained digest-qualified references. Rebuilding between
push and verify changes the local image id and is a refusal, not an implicit new
attempt. The exact NAS commands are in `docs/nas-deployment-remediation.md`.

Dependency-closure history is certification evidence, not attempt state.
`distributions_hash.prev` is not an authority and is no longer written. A later
run names the exact prior `FINALIZED`/`PASS` manifest whose closure is its
baseline. A `FROZEN`, `READY_FOR_REHEARSAL`, `FINALIZING`, `BLOCKED`, failed, or
abandoned manifest can never become that baseline. If the lock and closure
legitimately change, the operator creates and reviews an immutable transition
record binding the prior manifest bytes, old closure, new lock, new closure,
and new Git commit, then supplies that record explicitly. Neither the old
manifest nor the transition record is deleted or overwritten when the new run
eventually finalizes. The one-time unlocked bootstrap closure is retained too;
an explicitly named certified baseline supersedes it without moving or deleting
the bootstrap evidence.

Every named image is MANDATORY before the truncate (`--require-images`), and the
Postgres reference is the digest-qualified one read out of the compose file
rather than the bare `postgres:16` tag. It produces the corpus being certified:
on a clean machine the bare tag resolved to nothing and certification continued,
and on a machine with some other local `postgres:16` it would have recorded an
unrelated server. A dirty working tree also refuses — it invalidates the
`git_commit` line above it.

### 10e. Finalizing the rehearsal is automated too

```bash
scripts/sentinel-finalize-rehearsal.sh --start 2021-01-04 --end 2023-12-29 \
    --run-id <bt_wealth_core_runs.run_id>
```

It reads `summary.book_artifact` out of the run row, checks its window, re-runs
the rejection audit against the REALISED book, and completes the manifest. The
pre-seed audit asserted an empty book; that was true before the first bootstrap
and is false of the interval the rehearsal traded, so re-running it is not
optional. A summary with no `book_artifact` came from an older engine and is
REFUSED — writing the book by hand is precisely what this removes.

**It AUTHENTICATES the run, not only its book.** The book's window rules out the
wrong date range and nothing else: a different chain rehearsal over exactly the
same dates under altered configuration would pass a window check, and the
manifest would close around its hashes. So `status`, `mode`, `spec.start_date`,
`spec.end_date` and the presence of `parity_hashes` are all checked, and the
spec is recorded in the manifest — the configuration the rehearsal *ran under*,
not the one someone believes it ran under.

**The engine that ran it is RECORDED BY THE RUN, and bound to the certified
image.** bt-engine writes `spec.engine_identity` at run start — interpreter,
the Wealth Core source hash it imported, and an injected image id when the
deploy supplies one. Inspecting a mutable `:latest` tag at finalization answers
a different question: what the tag points at NOW. Rebuild it between the run and
the finalization and the manifest names the wrong image, with nothing about it
looking wrong.

**The manifest NAMES the engine before it runs anything.** `sentinel-certify.sh`
builds bt-engine (and deliberately does not start it — that is the launcher's
job) and freezes its image id and loader source hash into the manifest at the
same moment as everything else. The finalizer then compares the run against
those FROZEN values rather than against a fresh `docker image inspect`, which
answers "what does the tag point at now" and would accept any correctly
self-identifying artefact that happens to run after the freeze — including one
built from loader source that changed afterwards, which the Wealth Core hash
would not catch because Wealth Core had not moved.

The loader hash is read OUT OF THE BUILT IMAGE, not from the checkout. The
bt-engine Dockerfile assembles `/app/app` from its certification app plus the
two surviving backtester corpus adapters. Deleted Stocker pipeline,
portfolio-builder and scheduler sources are not certification dependencies.
A digest of `services/bt-engine/app` alone is still different from the image
tree, so the artefact itself remains the hashing authority.

Finalization also re-checks `git HEAD == manifest.git_commit` and a clean tree.
Everything else binds images and hashes; this binds the CHECKOUT — without it
the manifest can name commit A while the tree has become B, and every artefact
comparison still passes because they all compare against values frozen from A.

The revision label is necessary and not sufficient. A Docker build labels the
commit named by `HEAD`; it cannot prove that the build context was clean. A
dirty build from commit A can therefore carry the label for A. Cleaning the
checkout and running `--verify-only` must not turn that image into evidence for
the clean commit. The frozen manifest hashes the clean checkout and the
corresponding paths read back out of each image, then requires exact equality:
Sentinel, Wealth Core, bt-data's corpus writer, the assembled bt-engine app, and
the certification test/input bundle. A missing path or unequal digest refuses
before corpus mutation. Image labels bind ancestry; source hashes bind bytes.

`scripts/bt-engine-up.sh` makes the same comparison BEFORE the run, so a
drifted engine costs a second rather than three hours. `ALLOW_DRIFT=1` starts
it anyway for non-certification work.

**After a freeze, start the frozen image — do not rebuild it.**

```bash
scripts/bt-engine-up.sh --no-build --start 2021-01-04 --end 2023-12-29
```

Two things are deliberate here. `--no-build` is the certified path because
certification already built bt-engine and froze that image into the manifest;
rebuilding at launch can only produce a different artefact, which the finalizer
would refuse after three hours. And `--start/--end` names the manifest for the
interval being run: selecting the newest manifest by mtime compares against
whatever certification happened to run last, which may cover an unrelated
window — a comparison that then passes or fails for reasons having nothing to
do with the run about to start. The mtime path survives only as a default, and
says so when it is used. `--manifest <path>` names one outright.

### One resolver decides which image is meant

The harness freezes the bt-engine image; the launcher injects its id. Both need
its name, and both used to infer it as `$(basename $(pwd))-bt-engine`. That is
wrong here: `docker-compose.backtest.yml` declares `name: stocker-bt`, and
Compose uses the top-level `name:` as the PROJECT ahead of the directory
basename, so the image it builds is `stocker-bt-bt-engine`. Close enough to
read as a typo, different enough never to resolve.

`scripts/compose_image.py` is the single answer both scripts call — explicit
`services.<name>.image` first, then `<project>-<service>`, then REFUSE. It
never guesses, because a wrong image name that RESOLVES is worse than one that
does not: the manifest would name an artefact nobody ran and every later
comparison against it would pass. The falsifier is a compose fixture whose
project name is deliberately not the directory's.

**Both branches answer in that same order**, and that is where the rule was
broken twice. `docker compose config` is authoritative when it runs; the file,
parsed exactly with PyYAML, answers when it does not. The first version read
only the top-level `name:` with a regex and derived `<project>-<service>`,
skipping the explicit-image step entirely — so a service that had declared its
image outright got a derived name. It passed its own test because that test ran
wherever Compose was available and therefore never exercised the degraded path
it was silent about. Every resolution test is now parametrised over both.

The authoritative branch had the same bug from the other side: **a
profile-gated service is OMITTED from `docker compose config`**, and reading
that absence as "declares no image" derives a name for a service that has one.
`docker-compose.sentinel.yml` is exactly this case — `sentinel` sits behind
`profiles: ["cli"]` and its image is selected by Compose from
`SENTINEL_RUNTIME_IMAGE_REF` with a local-development default. A service missing
from the rendered model now falls through to the file rather than being
derived; because that image is interpolated, the fallback then refuses instead
of pretending to reproduce Compose's `.env` and configured-env-file rules.

What the file cannot settle, it refuses over, because reading a compose file is
not the same as reading Compose's resolved application model:

```text
no PyYAML / unparseable      cannot attribute image: to a service      REFUSE
service not in the file      absent is not "has no explicit image"     REFUSE
image: contains ${...}       uninterpolated; Compose would expand it   REFUSE
extends:                     image or build may come from elsewhere    REFUSE
neither image: nor build:    no artefact for a derived name to name    REFUSE
```

The `${...}` rule is checked on BOTH branches, not just the file one: Compose
interpolates an UNSET variable to the empty string, so `image: thing:${TAG}`
renders as `thing:` — malformed, non-empty, and otherwise about to be written
into the manifest as the name of an artefact.

A standing test resolves every non-interpolated service in both real Compose
files down both branches and requires the answers to be identical. Interpolated
services have a separate falsifier proving the file fallback refuses even when
the same variable is present in the Python process environment. One resolver
stopped the two scripts disagreeing; these checks stop its two branches from
forming different opinions where a file alone can settle the answer.

### The base is rebuilt before the engine, and then verified

`services/bt-engine/Dockerfile` begins `FROM stocker-base:latest` — a MUTABLE
tag carrying `shared/`, and therefore Wealth Core. Certification rebuilds it
unconditionally before building bt-engine, for the reason the deploy scripts
already do: the editable install caches the module list, so a new shared file
stays invisible until the base is rebuilt. It is a `docker build`; it starts no
Stocker service.

Step **2c** then asks the built engine for its Wealth Core source hash and
requires it to equal the certified Sentinel image's, BEFORE the truncate. The
rebuild establishes the intended provenance; this proves the artefact actually
carries it. They fail differently — a skipped rebuild is an operator mistake, a
mismatched result is a build that did not do what it was told — and without the
check the rehearsal would surface a stale Wealth Core as a source-hash mismatch
only after the seed and three hours of simulation. An unreadable hash blocks
too: absent is not equal, and empty compared against empty would have passed.

Three fields are bound, not merely recorded, and all three BLOCK when missing:

```text
wealth_core_source_hash     what the run IMPORTED vs what the certified image
                            CARRIES. A mismatch means these numbers came from
                            a different engine — the one mismatch in the record
                            that is about economics rather than packaging
bt_engine_app_source_hash   the loader itself. The Wealth Core tree alone does
                            not identify the engine that READ the corpus and
                            built the rehearsal inputs
image_id                    the exact artefact. Two bt-engine containers can
                            carry the same Wealth Core tree and different
                            interpreters, dependencies, loader code and client
                            libraries
```

**Start bt-engine with `scripts/bt-engine-up.sh`.** It builds, INSPECTS the
image, and only then starts the container with `BT_ENGINE_IMAGE_ID` injected —
in that order, because the id has to come from the image about to run rather
than from whatever the tag pointed at before the build. An ordinary
`docker compose up -d bt-engine` still works and records `null`, which the
certification path refuses: a rehearsal started the casual way cannot be
certified by accident, only re-run.

**Only the database path can finalize.** JSON envelopes remain useful audit and
transport artefacts, but validating fields supplied by the file is not
authentication. `scripts/sentinel-finalize-rehearsal.sh` therefore requires a
run id and `BT_DATABASE_URL`; it reads and validates the authoritative row in
one invocation. There is no `--from-json` finalization entrance.

The real-corpus parity report is frozen into the manifest, not merely printed
beside it. It names Sentinel's published `data_version`, the canonical bt-data
generation, and the canonical `source_mode`. The rehearsal row records the
generation it actually loaded under `summary.provenance`. Finalization requires
the canonical generation and source mode to match exactly and requires the
current Sentinel identity/corpus hash to remain the one parity certified.
Passing parity on G1 and rehearsing or finalizing against G2 is a refusal even
when both generations independently report `READY`.

Manifest completion is a state transition, not the presence of several hashes.
The frozen record begins `FROZEN`, becomes `READY_FOR_REHEARSAL` only after the
corpus identity and parity generations are bound, and becomes `FINALIZED` only
after every final gate passes. Any failed finalization persists `BLOCKED` plus
its failure list and keeps all completion fields null. The attempted evidence is
retained separately for diagnosis; it cannot make a blocked manifest look
complete merely because hashing happened before a later gate failed.

**The envelope separates the ROW's claims from the RUN's payload**, permanently:

```text
{ schema, run_id, status, mode, spec, parity_hashes,   <- the database row
  summary: { book_artifact, equivalence, ... } }       <- what the run produced
```

The export used to flatten the summary over the row fields with `**summary`, so
a payload field named `status` or `mode` would overwrite what the database
actually said. `ChainRehearsal` carries neither today, so nothing was wrong in
practice — and the boundary was defeated structurally, which is the kind of
defect that waits for a field to be added. Nesting beats re-ordering the merge:
ordering is a property someone has to keep getting right, nesting makes the two
categories impossible to confuse.

**The certification conditions are GATES, not narration.** These were recorded
and then described to the operator, so a run with unreconciled episodes printed
`REHEARSAL FINALIZED`. All of them now have to hold:

```text
equivalence.state_hash_matches / ledger_hash_matches / final_cash_matches
terminal_reconciliation.unreconciled_episodes == []
terminal_reconciliation.unexplained_episodes  == []
terminal_reconciliation.residual              == 0
terminal_reconciliation.cash_coverage_fraction == 1.0
```

**Coverage is compared against 1.0, not merely checked for presence.** Verifying
the field EXISTS proves nothing, and a present-but-partial coverage is precisely
the historical failure: `residual: 0.00` with both episode lists empty while the
cash bucket held 3 of 8 episodes and $132k of $342k. If exact-terms non-cash
settlement is ever supported, the general rule becomes an ACCOUNTED coverage
fraction spanning both buckets; for this certification the accepted gate is 100%
of the population inside the cash reconciliation.

A MISSING field fails the same way a violated one does: absent and `== []` are
different statements, and only one of them is a reconciliation. On failure the
evidence is still written and the run ends `FINALIZATION BLOCKED`.

`--require-certified` exits non-zero when the interpreter or any pin differs, so
a rehearsal script refuses to produce evidence from an environment it cannot
name. `identity_hash` covers the environment and the source; `corpus_hash`
covers the data. They are separate on purpose — the same environment with a
different corpus is a data finding, the same corpus on a different environment
is a machine finding, and one combined hash cannot tell them apart.

The corpus digests are FULL SCANS of the interval, not samples or counts. A
vendor restating a price in place changes neither the row count nor the date
span; only reading the values detects it. That is the exact failure the Stocker
factor cache shipped for months, which is why `bt_data_version` exists.

### 10b. Refused rows are a CERTIFICATION item, not only an operational WARN

Readiness reports ingest refusals as a WARN, which is right for the question it
asks — is the feed healthy enough to plan a book tomorrow — where a few
unnameable instruments are ordinary. It is the wrong answer to "is THIS replay,
over THIS interval, complete?"

A rejection is not automatically a rehearsal failure; the ticker may be
economically irrelevant. **"We did not check" is.** So the certification report
answers, for the exact rehearsal interval:

```text
how many refused price rows
how many distinct refused tickers
could any have entered the universe / ranking / selection
did any intersect a holding, a pending terminal episode, or a corporate action
```

```bash
$COMPOSE run --rm sentinel \
  rejection-audit --start 2021-01-04 --end 2023-12-29 \
  --held AAPL,MSFT --pending-terminal XYZ
```

Every refused ticker lands in exactly one verdict, and the interval is
certifiable only when nothing is in the last two:

```text
IMMATERIAL    it could not have been admitted even at its BEST observed values,
              judged against the same EligibilityConfig the engine applies
MATERIAL      it intersects a holding, a pending terminal episode, or a
              corporate action in the interval
UNDETERMINED  anything else — including a refusal recorded with no price
```

The asymmetry is deliberate: the audit proves NEGATIVES only. A security whose
best observed as-traded close never reached the floor could not have been
admitted on any session it was refused on, whatever else is unknown. It never
claims a rejection WOULD have been admitted — the momentum series, the
volatility and the issuer group died with the dropped row. **If the answer is
unknown, the rehearsal fails closed**, and the command exits non-zero on
anything short of CLEAR.

This is why `sentinel_ingest_rejections` stores the price and volume: without
them every rejection is permanently UNDETERMINED, and a fail-closed rule with an
undecidable input blocks the rehearsal instead of informing it.

**There is deliberately NO history-length proof.** An earlier version cleared a
ticker whose *rejected* session count fell below the 126 sessions admission
requires. Those are not the same 126: the table counts what was DROPPED, so a
security with 300 valid sessions and one refused row read as "could not have
been ranked". A history argument needs the security's complete history through
that date, which is the opposite of what a rejection table holds.

**The book must be supplied, or the answer is UNKNOWN.** `--held` /
`--pending-terminal` / `--book` default to *unavailable*, not to empty — an
empty set is the claim "nothing was held", and a caller that said nothing would
otherwise make that claim silently, which is how the two strongest materiality
checks became a no-op on the certification path. Before the first bootstrap the
book genuinely is empty; say so with `--assert-no-holdings`. **After the
rehearsal, re-run the audit with the realised book** — the pre-seed assertion
was true then and is not true of the interval the rehearsal traded.

**The realised book is EMITTED BY THE RUN, never typed by a human.**
`rehearse_chain` builds it from the bulk `RunResult` and puts it on the result as
`book_artifact` (and in `to_dict()`, so it survives to the persisted run row):
the union, over the whole interval, of every raw ticker the ledger names and
every ticker with a terminal event the run carried or resolved. `--book` then
consumes it. A person retyping a ticker list sits in the evidentiary chain, and
a typo there does not error — it produces a CLEAN certification.

The canonical module is `stock_strategy_shared.book_artifact`, with
`sentinel.core.book_artifact` a module-identity shim. It has to be shared:
bt-engine PRODUCES it and Sentinel CONSUMES it, and neither may import the
other. It is deliberately **not** under `wealth_core/` — that tree is hashed as
`wealth_core_source` in every certification record and has been byte-identical
across four reviews, which is worth more than a tidier import path for a helper
that executes during no run.

**The window must match the audit exactly.** `load(path, start=…, end=…)`
refuses a book whose window differs, and refuses an unrecognised `schema`. A
valid 2022 book handed to a 2021-2023 audit omits every name held only in 2021
or 2023, and a refused row on one of those is then judged by admission floors
that do not govern an open position. A well-formed file for the wrong period is
more dangerous than a malformed one, because nothing about it looks wrong.

The union is deliberately **over-inclusive**, and the asymmetry is the design:

```text
a ticker wrongly PRESENT   an irrelevant rejection is called MATERIAL. The
                           interval refuses, a human looks, and says so.
                           Costly, visible, safe
a ticker wrongly ABSENT    a rejection on a security the run HELD is judged by
                           the admission floors, which do not govern an open
                           position at all. Free, invisible, wrong
```

`book_artifact.load` refuses a file missing either key. `.get("pending_terminal",
[])` would turn a book naming only `held` into the claim "nothing was pending" —
silently, on the field most likely to be forgotten.

Three further things block an interval, all of them recorded during ingest
because a warning that scrolled past during a six-hour seed is not something a
certification can consult:

```text
truncated evidence   `sentinel_rejection_truncation`. The report retains at
                     most `max_rejections` refusals per chunk and counts the
                     rest — correct, and the count used to die with the process,
                     so an audit could examine 50,000 of 175,000 refusals and
                     report CLEAR
split disagreement   ACTIONS and the price domains describing different events.
                     ACTIONS winning RESOLVES the conflict; it does not explain
                     which source is wrong about a share count
unusable dividend    a distribution the vendor stated no amount for. The corpus
                     holds 0.0 for that and for "no distribution"; only this
                     record separates them
```

`SPLIT_ONLY_DERIVED` and `SEAM_SPLIT_UNCORROBORATED` gate certification unless
full-interval counterfactual evidence proves that every plausible split
treatment produces identical eligibility, rankings, selections, holdings,
accounting and hashes. Event-day price or liquidity cannot prove that: a split
changes the cumulative signal series on every later session, when the security
may cross either floor. Absence from the observed book is also not proof,
because the uncertain split can be the cause of that absence. No such
counterfactual engine exists today, so both dispositions block; authoritative
and directly/reciprocally corroborated dispositions clear.

These rows are publication-scoped evidence. Each ingest observation is retained
with its writer run; only the newest successfully published disposition for a
split `(ticker, session)` is active. An unpublished corrective ingest cannot
retire the prior active blocker. Live candidate evidence is explicitly
`PENDING` and keeps coherence/readiness closed. A failed or reclaimed run is
durably `ABORTED` under the corpus writer lock, so its immutable history does
not poison every later coherent publication. A successful retry atomically
publishes its disposition and supersedes older pending evidence for the same
covered event. Pre-upgrade rows remain a fail-closed legacy baseline until a
later published observation supersedes the same event, so a schema upgrade
cannot manufacture a clean interval by forgetting evidence. Publication also
refuses stamped anomaly observations from any run not durably marked
`success`, and a failed publication rolls lifecycle changes back atomically.

Correction by absence is explicit rather than inferred. Complete ACTIONS fetches
are append-only generations: current rows are `PRESENT`, formerly active rows
missing from the fetched raw-date window are `REMOVED`, and publication selects
the active generation without deleting history. Failed and unpublished fetches
cannot hide a previously active action. A current valid dividend row emits
`DIVIDEND_RESOLVED` for the earlier unusable event. A removed split emits
`SPLIT_RESOLVED_NO_EVENT` only when the current ACTIONS generation is complete,
SEP compared the event with a real predecessor and derived no split, and the
candidate effective split ratio is exactly `1.0`. A preserved non-1 base ratio
is corrected by an append-only `1.0` repair overlay published atomically with
the action removal and resolved disposition. Silence, incomplete coverage, or a
missing repair leaves the old blocker active.

Every ACTIONS generation also carries an append-only lifecycle. Failed or
reclaimed candidates are `ABORTED`; a successfully published covering retry
marks an older publication-failed candidate `SUPERSEDED`; and only a live
`PENDING` candidate blocks coherence. A narrower retry cannot retire a wider
unresolved snapshot. Split-repair overlay history follows the same effective
rule: only published repairs apply, and a later published repair for the same
bar makes the older unpublished retry terminal for coherence without deleting
it.

### 10c. Synthetic parity is not corpus parity

`tests/sentinel/test_loader_parity.py` proves the two loading MAPPINGS agree on
rows both were handed. It found two real defects and it is not the claim that
matters here. Run the real-window comparison as well:

```bash
BT_DATABASE_URL=... python -m tools.corpus_parity \
  --start 2021-01-04 --end 2023-12-29
```

It compares the bars actually seeded against the ones the canonical Wealth Core
path produces from the Sharadar corpus — real splits, ticker reuse, delistings
mid-window, restatements that landed in one store and not the other. ACTIONS
authority and `tradeable` both changed in this batch, so this is where that
shows up. Read a divergence in order: **membership first** (a field mismatch on
a bar that should not exist is noise), then `split_ratio`, then dividends, then
prices.

An unreadable canonical corpus exits non-zero. Not having run the check is not
the same as passing it.

#### Cold-boot identity collapse is a loader failure, not membership drift

A rebuilt bt-data database can legitimately have the complete historical SEP
price corpus and only a current TICKERS observation. Do not backdate that
observation. The canonical identity loader may use its vendor
`firstpricedate` / `lastpricedate` interval solely to prove which permaticker
owned a ticker on each historical session; current category, relationships and
labels remain unavailable to historical decisions.

If the requested price window is non-empty but no bar can be resolved, parity
reports `canonical_loader_failure: identity_authority` and exits non-zero. It
must not report `canonical_bars: 0` followed by every Sentinel bar as an
ordinary `extra_in_sentinel` population. For identity/corpus parity, repair
only TICKERS, then rerun:

```bash
curl -fsS -X POST http://localhost:8021/jobs/backfill-universe
```

This fetches no SEP prices. The observation is dated today. An operator must
not pass a historical date or update the NAS tables by hand.

This repair does not reconstruct decision metadata. A causal multi-year Wealth
Core rehearsal requires the legitimately observed TICKERS snapshot for every
measured session so category, label, listing eligibility, and issuer-family
changes become effective only when observed. A current-only snapshot can prove
historical identity through bounded listing intervals, but the rehearsal must
refuse it rather than silently run a partial or cash-only universe. Restore that
snapshot history separately; do not refetch or rewrite the 42-million-row price
corpus and do not backdate today's TICKERS delivery.

It lives in `tools/`, not in the `sentinel` package, because the canonical
module imports SQLAlchemy at module scope and that is a retired-stack
dependency — `tests/sentinel/test_image_layout.py` refuses to let the runtime
image acquire it.

## 10e-bis. The `.env` is built by SUBTRACTION from Stocker's

Sentinel reads six variables. The retired Stocker `.env` has around forty, and
copying it forward carries three distinct hazards:

```text
PAPER_ONLY=true             read by NOTHING. The only surviving mention is a
LIVE_TRADING_ENABLED=false  COMMENT in sentinel/config.py describing the design
KILL_SWITCH=false           that was deleted. A line that looks like a safety
MAX_ORDER_NOTIONAL          interlock and is inert is worse than no line
ALPACA_BASE_URL             if the old deployment pointed at the live host,
                            Sentinel refuses to start on the inherited value —
                            a confusing failure, and a fact worth surfacing
AV_API_KEY, ANTHROPIC_...   credentials for services that no longer exist. A
TAVILY_API_KEY, IBKR_*      secret with no consumer is pure liability
```

The guard that actually stops Sentinel reaching real money is `LIVE_HOSTS` in
`sentinel/config.py`, which refuses `api.alpaca.markets` and has **no
override**. Re-adding the old flags adds nothing.

```bash
scripts/sentinel-env-from-stocker.py --from ~/stocker-old/.env --dry-run
scripts/sentinel-env-from-stocker.py --from ~/stocker-old/.env
```

Writes mode 0600, refuses to overwrite without `--force`, and **never prints a
value** — the report names variables and says what happened to each. That last
property is why it is a script: this runs on the NAS over SSH, and a terminal
that has echoed a Sharadar key has put it in scrollback and in the session
transcript.

It refuses if `SHARADAR_API_KEY` is absent or still a placeholder, generates
`SENTINEL_POSTGRES_PASSWORD` (the Stocker file has no equivalent, and compose
declares it `:?` so it will not start without one), and warns when a carried
password contains a character compose splices into a DSN or a literal `$` it
would interpolate.

The Sharadar client also treats an authenticated request as a redaction
boundary. `httpx`/`httpcore` URL diagnostics are suppressed while the request,
status handling, and exception conversion run, and propagated errors contain a
request target with `api_key` omitted. Raising log verbosity therefore cannot
put the query credential back into terminal output or collected log records.

## 10f. The resource envelope is MEASURED, and the measurement is an artefact

`docker-compose.sentinel.yml` sets four service limits under comments that say
what they are:

> SET EARLY AND GENEROUSLY, tightened to the measured envelope later. The value
> is not the point yet; ENFORCEMENT is.

```text
sentinel-postgres   mem_limit 1g    cpus 1.5   shm_size 1gb
sentinel            mem_limit 2g    cpus 2.0
sentinel-automation mem_limit 2g    cpus 1.0   profile: automation
sentinel-panel      mem_limit 512m  cpus 0.5
```

"Later" is finding #15. It needs a Docker daemon and the seeded corpus, so it
runs on the NAS and nowhere else. Run it with `scripts/sentinel-measure.sh`
rather than by hand:

```bash
scripts/sentinel-measure.sh seed  -- sentinel feed-seed --date-from 1998-01-01
scripts/sentinel-measure.sh daily -- sentinel feed-daily
scripts/sentinel-measure.sh plan  -- sentinel target-book --sessions 253 --cash 100000
scripts/sentinel-measure.sh ready -- sentinel check-data
```

Each writes `artifacts/envelope/<phase>-<stamp>.{csv,json,log}` — a per-sample
CSV, a peak/headroom report, and the phase's own output.

**Catch-up is now reached only through `prepare-paper-plan`.** That command
holds the publication pin and writer lock, advances canonical missed sessions,
and adopts the latest plan. It is broker-read-only but deliberately writes
behavioral state, so measure it only after the named paper account has passed
the ownership and migration checkpoints in the activation runbook. Stage 4
invokes that same canonical preparation path from its separately reviewed
scheduler; there is no second catch-up implementation. The scheduler's Compose
service is omitted unless the `automation` profile is explicit, and it starts
durably disabled and killed.

### What it samples, and why each one is there

```text
docker stats --no-stream   peak RSS and CPU per container, on a TIMER. Not the
                           streaming form: it redraws with control codes, so a
                           tee'd log is neither readable nor parseable, and the
                           first frame's CPU number is meaningless
/proc/meminfo              host MemAvailable. A container inside its limit on a
                           host that is swapping has not passed
pg_stat_database           temp_bytes delta. The corpus sort SPILLS, and a spill
                           is invisible to `docker stats` — it is disk, and it
                           is what the staging table exists to bound
du on the data volume      disk growth across the phase
docker inspect             OOMKilled and RestartCount, read from the DAEMON. A
                           container killed at its limit and restarted reports
                           healthy afterwards, with a truncated log
elapsed wall time          a phase that fits in 1g by taking nine hours has not
                           passed either
```

### The verdicts

```text
PASS          every peak at least 20% below its enforced limit
TIGHT         a peak within 20%. Sampling is on a timer, so a spike between two
              frames is invisible; a peak near the wall has probably touched it
UNMEASURED    no samples. NOT a pass
PHASE FAILED  the phase exited non-zero — the envelope describes a run that did
              not finish
OOM KILLED    read from the daemon, not inferred from a silent exit
```

The limits are read out of the compose file at run time, never transcribed, so
the comparison cannot go stale against the deployment it describes.
`tests/sentinel/test_certification_harness.py::TestTheResourceMeasurementHarness`
pins that, and pins that the harness can destroy no state — measurement is
read-only about the corpus; `sentinel-certify.sh` step 3 owns truncation.

### Not every host can ENFORCE every declared limit

The first real #15 run, on a Synology DS216+II, never started a container:

```text
Error response from daemon: NanoCPUs can not be set, as your kernel does not
support CPU CFS scheduler or the cgroup is not mounted
```

```text
Docker 24.0.2   kernel 3.10.108   cgroup v1   btrfs   Celeron N3060, 2 cores

ENFORCED      memory, memory+swap, cpu_shares
              (/proc/cgroups has cpu, cpuacct, memory, blkio, cpuset all on)
UNSUPPORTED   cpu cfs quota, cpu cfs period, all four blkio throttles,
              kernel memory TCP
```

Confirmed rather than assumed: `docker run --memory=256m --memory-swap=256m
sentinel:latest status` exits 0 on that host. The memory envelope #15 measures
there is a real one.

Two consequences worth reading together. **cpu_shares works** — the cpu cgroup
is present, only CFS bandwidth is missing — so relative CPU weighting is
available if it is ever wanted; it is deliberately not used, because a share is
a priority and not a ceiling, and presenting one as the other would be the same
overclaim. And **blkio throttling is unavailable**, which matters for a seed
that is I/O-bound on spinning disks: disk pressure cannot be bounded here
either, only observed.

The daemon **refusing** is correct, and it is why the answer is a probe rather
than deleting the resource controls. A CPU ceiling the kernel silently ignored
is §11's own defect — a setting believed to be in force, that is not.

```text
scripts/sentinel_host_capabilities.py   asks the DAEMON what it enforces, not
                                        the kernel version, then actively
                                        creates (never runs) a pinned local
                                        image with NanoCPUs
scripts/sentinel_strip_cpu_limits.py    deletes `cpus:` and nothing else
scripts/sentinel-compose.sh             the ONE resolver. Probes, and prints
                                        the `-f` args every entry point uses
```

A compose override cannot do this: overrides MERGE, so `cpus: 0` would start
the container — the daemon's check is gated on `NanoCPUs > 0` — but the field
survives into `docker compose config` and the deployment still advertises a
ceiling it does not have. The CPU-free file is therefore **generated** from the
canonical one on every invocation, by deleting exactly those lines. It cannot
drift, it diffs cleanly, and no operator edits YAML.

`SENTINEL_FORCE_CPU_LIMITS=1` keeps the canonical file unprobed, for proving on
a capable host that that path still works.

`SENTINEL_FORCE_NO_CPU_LIMITS=1` is the recorded recovery path when an older
daemon's metadata is false or the active probe cannot be made. The two force
modes are mutually exclusive. The no-CPU mode sets the capability artifact to
`OBSERVED_NOT_BOUNDED`; memory and shared-memory controls remain unchanged.

**UNKNOWN keeps the limits.** Only a positive UNSUPPORTED strips them, so an
unprobed host — no daemon, CI — retains its declared ceilings and fails loudly
if it cannot hold them. The opposite default would silently drop every CPU
limit on a machine that could.

#### What this means for #15

```text
memory   a real envelope. mem_limit and shm_size are enforced here
CPU      MEASURED, not BOUNDED. `cpus:` never reaches the kernel, so peak CPU
         percent is observational and #15 must NOT report a CPU envelope as
         certified on this host
```

The harness reports these separately — `memory_verdict` and `cpu_verdict`, with
`cpu_limit_enforcement` naming the capability — because one summary word would
either overclaim CPU or discard a real memory measurement. It writes
`capabilities-<stamp>.json` beside every phase, so the record says which limits
were actually in force when the numbers were taken.

On two 1.6GHz cores the wall-time figure is likely to matter more than either.

### What `sentinel-certify.sh` does NOT cover

Nine steps, and none of them is a resource measurement. Nothing in that script
samples memory, CPU, temp spill or wall time, and nothing compares an observed
peak against a declared limit. A fully green certification says nothing about
whether the seed fits in 1g. That is why #15 is a separate job with its own
harness rather than a step folded into the existing one — and why the compose
limits stay provisional until the artefacts above exist.

### 10g. PostgreSQL requires a second-target backup, not only a volume

`sentinel_pgdata` is the canonical strategy state, behavioral-migration ledger,
rollout intent and history, account binding, current plan, execution journal and
corpus. A named volume protects it from container
replacement; it does not protect it from disk loss, corruption or operator
error. Production operation therefore includes continuous WAL archiving to an
operator-owned second durable target, periodic physical base backups, an age
alarm and an isolated restore drill.

The backup location must be absolute, pre-created, outside this repository and
outside Docker's data root. A separate NAS backup dataset or mounted backup
share is appropriate. The scripts refuse root, home, repository, missing and
symlink targets, verify the target is not below Docker's data root, and require
a different backing device. If a remote mount layer reports the same Linux
device number (or Docker's root is not inspectable), the operator must first
verify independent durability and set
`SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1`. The scripts also run a write probe
as the PostgreSQL container uid; host-root writability is not sufficient.

The inside-Docker-root comparison is lexical and runs before traversal, so an
attestation can never authorize a child of the daemon root. When that root is a
protected Synology path, validation does not attempt to traverse it after an
explicit attestation; without attestation, absent or unreadable metadata still
fails closed.

```bash
export SENTINEL_BACKUP_DIR=/mnt/second-target/sentinel
mkdir -p "$SENTINEL_BACKUP_DIR/wal" "$SENTINEL_BACKUP_DIR/base"

COMPOSE="bash scripts/sentinel-compose.sh --run"

# One reviewed restart enables archive_mode; it never removes a volume.
$COMPOSE up -d --force-recreate sentinel-postgres
$COMPOSE exec -T sentinel-postgres psql -U sentinel -d sentinel -Atc \
  "SHOW archive_mode"
# checkpoint: on

scripts/sentinel-base-backup.sh
scripts/sentinel-backup-status.sh
scripts/sentinel-restore-drill.sh
```

Checkpoints are `verified_base_backup:...`, `backup_ready:true`, and
`restore_drill_ready:true`. A base backup is not promoted as ready until a
unique recovery marker written after the base has crossed `archive_command`.
Status refuses disabled archiving, a stale last success, or a failure newer
than the last success. The restore drill copies the newest base backup to a
uniquely named disposable Docker volume, starts PostgreSQL with no network and
no published port, applies archived WAL through that exact post-base marker and
LSN, checks the canonical tables including the behavioral-migration ledger and
rollout state, then
removes only that named container and volume. It never writes the primary.

`archive_command` publishes each WAL filename as an immutable object. Merely
finding the final pathname is not success: an existing regular, non-symlink
file is accepted only when its byte length and contents exactly match the
completed source WAL. A new archive is copied to a unique hidden temporary
file in the destination directory, checked against a stable source size and
byte-compared, fsynced, and then atomically renamed without clobbering. The
destination directory is fsynced after publication. If another invocation won
the name race, its final file must pass the same exact comparison before the
retry succeeds. Copy, validation, fsync, or rename failure removes only the
temporary file and returns failure; it must never leave a final pathname that
a retry can mistake for a complete segment. A mismatched or partial final file
is a hard archive failure and PostgreSQL retains the source WAL for operator
repair.

Run base backup daily, status/age monitoring at least hourly, and a restore
drill after every schema/certification change and at least monthly. Retention is
owned by the second target: keep at least seven daily and four weekly verified
base backups plus all WAL needed from the oldest retained base. Never prune WAL
until a newer base has passed both `pg_verifybackup` and the restore drill.

### 10h. The panel reports durable facts, never deployment-stage placeholders

The read-only panel is an operational projection of the canonical PostgreSQL
records. Once the production state and execution projection exist, it must not
keep reporting hard-coded scaffolding values (an assumed `1.00 PINNED`, book
unavailable, broker unavailable). Those values look safe while hiding the
system that is actually prepared. A genuine durable pinned rollout still
displays `1.00 PINNED`, but only after the state/plan/rollout records agree.

```text
ownership     canonical account binding; SENTINEL OWNED records the historical
              flat handover boundary and never claims that current positions
              are flat; the broker row is the current-position evidence
authority     a runtime authority verdict only when the automation service has
              durably persisted one; certificate lifecycle/revocation/expiry
              facts remain explicitly labelled lifecycle-only and never
              manufacture a VALID verdict
exposure      one unsuperseded execution plan, checked against the canonical
              processed-session cursor and durable rollout state; PINNED_1_00
              displays 1.00 PINNED even while the shadow controller continues
              computing its independent decision, while CONTROLLER must equal
              that canonical decision and name its certificate
book          canonical v3 SessionState: slots, estimated NAV, shadow cash,
              pending actions, blocked decision and unresolved terminals
terminals     current unresolved and carried terminal state from that same
              canonical envelope; cumulative settlement mix is not invented
broker        newest durable broker observation plus unresolved command-journal
              state; rendering the panel never performs a broker read
automation    durable installed/enabled/kill policy; leader holder/fence/
              heartbeat/expiry; last/next cycle, last clean reconciliation and
              current failure; pending/dead-letter/unacknowledged outbox facts;
              fresh installation is DISABLED and KILLED
```

Every query has the panel's existing connection and statement timeouts. The
runtime schema is feature-detected before a table is queried, so an older or
partial database renders the affected rows `UNKNOWN` instead of taking down the
page or substituting zero. A missing canonical record is named as not yet
prepared/observed; malformed JSON, multiple current plans, cursor/decision/plan
disagreement, or an unreadable required table is `UNKNOWN` and is included in
the source-error banner. Each value carries the timestamp of the durable fact
it describes. The panel imports no execution adapter and receives no Alpaca
credentials, so refreshes remain SELECT-only and cannot become unattended
broker traffic.

## 11. `execution_model` activation is a versioned operational event

### ACTIONS source-row identity and failed-daily recovery (2026-08-14)

Sharadar ACTIONS does not promise that ``(ticker,date,action)`` is a source-row
key.  Sentinel receives seven source fields: ``date``, ``action``, ``ticker``,
``name``, ``value``, ``contraticker`` and ``contraname``.  Production returned
multiple distinct ``relation`` rows for XRN on 2026-08-14.  Relationship,
terminal and distribution vocabularies can all carry siblings at that coarse
key, so uniqueness must not be inferred from the action verb.

The durable grain is now a SHA-256 of canonical complete source content.  NULL
is encoded separately from an empty string and numerically equal values have
one canonical spelling.  Exact repeats are idempotent; distinct rows survive.
A restatement is the disappearance of the old content identity plus presence of
the new one.  Complete-window PRESENT/REMOVED observations and publication rank
that identity.  The old ``sentinel_actions`` table remains an immutable legacy
baseline; migration adds identity to append-only observations and does not
rewrite or discard the baseline.

Economic consumers remain deliberately narrower than source storage.  Positive
cash distributions on one ticker/effective session sum once per distinct source
row.  More than one distinct split row on one ticker/effective session has no
vendor-defined composition order: Sentinel applies no ACTIONS multiplier and
publishes ``AMBIGUOUS_SPLIT_MULTIPLICITY`` certification evidence.  It may not
pick the first/last row.

Terminal consumers map every distinct source row before coalescing.  The
economic key is ``(effective exchange session, permanent security id)`` -- not
the raw ticker, action name, or vendor date.  Sharadar normally states one
termination with a reason-specific row plus a bare ``delisted`` row.  The
canonical backtester has always collapsed that representation by retaining the
richest supported mapped record; Sentinel and the backtester now call the same
shared selector.  Richness comes only from supported terminal fields.  ACTIONS
``value`` remains transaction-size provenance and never makes a record richer
as cash per share, an exchange ratio, or any other settlement term.

Selection is deterministic and independent of source-row order.  A less
informative generic row may be subsumed by a reason-specific row.  Candidates
at the same richest information level must agree on mapped economics; otherwise
the group produces no event and every source row is ``CONFLICTING_TERMINAL_TERMS``.
One selected source row is ``resolved`` and every other source row for an
accepted group is recorded separately as ``collapsed`` with reason
``COALESCED_TERMINAL_SOURCE_ROW``.  Thus source-row conservation includes four
explicit buckets -- excluded, resolved, collapsed, unresolved -- while Wealth
Core receives exactly one event per economic key.

``check-data`` loads this exact normalized stream and verifies both source-row
conservation and uniqueness of the stream Wealth Core will consume.  Bootstrap,
one-session production, forward-chain certification, and the canonical replay
all use the same coalescing rule.  An unresolved identity or irreconcilable
richest-record conflict remains fail-closed and names ticker, permanent security
id when known, source dates/actions, source-row identities, and reason.
Relationship rows have no ranking, price, split, dividend, terminal, or issuer-
family effect.

This normalization is a reader correction.  Existing published rows such as
IGMS ``acquisitionby`` + ``delisted`` on 2025-08-13 are valid evidence and need
no deletion, manual SQL mutation, reseed, database restore, or Sharadar refetch.
After deploying the corrected images, run ``check-data`` and ``target-book``
again against the existing corpus.

The failed production daily run
``7a0e20f4-9a51-4737-8fd6-ecbfadf39075`` stopped in ACTIONS after committing
13,216 run-stamped rows.  They are unpublished and invisible; v2 remains the
published corpus with frontier 2026-08-13, freshness fails for 2026-08-14, the
required SFP SPY tail is missing, and coherence/frontier/freshness are the three
failed checks.  A normal corrected ``feed-daily`` retry is the recovery path:
startup durably fails any orphan candidate, the required SPY tail and price
overlap rewrite their economic-date keys, ACTIONS lifecycle state is retired,
and the full TICKERS refresh writes a newer dated snapshot.  In the publication
transaction, that complete newer universe snapshot retires rows owned by
durably failed unpublished runs at or before its snapshot date and records the
retired run/count evidence.  It never deletes or rewrites a row named by a
publication, and it never retires a future-dated candidate.  Bars, SPY and the
legacy destructive ACTIONS table do not receive this deletion rule: a failed
upsert may have replaced a previously published key, so the retry must actually
rewrite every remaining owner or publication refuses.  Publication moves only
after no destructive blocker remains.  Manual SQL deletion and database restore
are not the normal recovery.

#### Wealth Core and CAGR impact

``relation`` is storage/audit-only in the current strategy.  The price
normaliser selects only ``SPLIT_ACTIONS`` and ``DIVIDEND_ACTIONS``; the terminal
loader selects only the explicit target/acquirer vocabulary and accounts for a
relation row as unsupported/non-terminal; ranking reads normalized bars and
security metadata; issuer-family construction reads TICKERS ``relatedtickers``.
Consequently the two XRN relation rows cannot alter signal prices, ranking,
selection, split shares, dividend cash, terminal settlement, or issuer grouping.
They also cannot have changed an already published CAGR: the production ingest
refused before publishing August 14, and relation is absent from every economic
consumer even when present.

That conclusion is intentionally narrower than claiming every historical form
of multiplicity is harmless.  The legacy ``bt_actions`` and pre-fix Sentinel
tables collapsed ``(ticker,date,action)`` and therefore cannot prove that no
distinct same-key economic rows ever existed.  Distinct dividend rows would add
cash; distinct split rows are now blocking rather than first/last/product;
terminal siblings are retained but one effective terminal event is applied.
``python -m tools.sentinel_actions_profile <sanitized.jsonl>`` reports source,
distinct, repeat and multiplicity-key counts by action type without echoing rows
or request URLs.  A certification that wants a corpus-wide historical CAGR
claim must run that diagnostic on an authorized sanitized export; collapsed
legacy storage is not evidence of absence.

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

The paper-only preparation, explicit execution authority, and exact operator
sequence are defined in `docs/sentinel-paper-activation.md`. That runbook is the
only supported path from an inherited paper account to a Sentinel target. In
particular, `prepare-paper-plan` cannot migrate or submit, `execute-paper-plan`
cannot choose or rebuild a plan, and neither command may be scheduled or made a
deployment default by this change.

## 13. Definition of the first milestone

Not "Sentinel produced orders." This:

> Stocker is shut down; an operator explicitly runs Sentinel's one-time
> `migrate-account` command against the named Alpaca paper account, which safely
> and idempotently removes the legacy Stocker paper portfolio and establishes a
> clean persisted ownership boundary. Only then does a separate preparation
> boot the canonical Wealth Core engine from valid data and a separate confirmed
> execution maintain a deterministic paper book with correct decisions,
> next-session execution, reconciliation, and restart behaviour.

Only after that milestone passes does the Sentinel risk controller get activated
and certified against the frozen oracle.

**Do not redesign the strategy while doing this work.** The research stage is
over for this deployment path. What remains is faithful implementation,
operational separation, and falsifiable certification.
