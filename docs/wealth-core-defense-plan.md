# Wealth Core defensive controller — DESIGN PLAN

**Status: DESIGN ONLY.** Nothing here is implemented. Nothing here is activated.
Base Wealth Core remains NO-GO (docs/wealth-core-certification.md), and this
overlay sits on top of it.

> ### State of play — 2026-08-06
>
> All four owner decisions in §6 are SETTLED, and the DTB3 rate source in §3.10
> is settled. No controller code exists yet.
>
> **Prerequisite defect work** (these are wrong TODAY, independent of the
> overlay, and three of the four are done):
>
> ```text
> DONE      defect 1  unknown crash-brake signal re-risked the whole book   889406a
> DONE      defect 2  stressed_stop was dead config promising a risk control 89cfa05
> DONE      defect 5  parity compared a call SITE, not behaviour             f7104c1
> OUTSTANDING defect 3  no persisted controller state / hysteresis
>                       — subsumed by this design's §3.3, build step 7
> SHADOW    defect 4  conflicting intents, no reconciliation
>                     — built per §3.8, SHADOW-WRITTEN, executor read NOT switched
> ```
>
> **Defect 4 — what exists now.** Migration 0052 adds `intent_proposals`
> (append-only, deliberately unconstrained) and `net_intents` (the unique index on
> `(run_id, account_id, ticker)` lives HERE). The composition rule is pure in
> `shared/stock_strategy_shared/intent_reconciliation.py`; the write statements
> are `services/pipeline/app/intent_writes.py`; the delta step writes both tables
> inside a SAVEPOINT and logs the divergence report.
>
> **`delta_intents` is untouched and the trade-executor still reads it.** That is
> the remaining half: switching the executor's read is a separate change, and its
> precondition is having WATCHED the reconciliation resolve a real conflict —
> which needs the crash brake to actually engage, or a rehearsal that makes it.
> A reconciliation nobody has seen fire is not evidence that it fires correctly.
> When the read does switch, the delta step's `except` around the shadow write
> MUST become fatal: a missing net intent would by then be a missing trade.
>
> **Cutover gate (not a market event).** Waiting for a real crash to observe a
> conflict means testing the untested path on a live book.
> `tests/integration/test_intent_cutover_rehearsal.py` manufactures four
> conflicts — one per composition branch, each with a different winner — and
> requires all six conditions including that a re-run cannot produce a second net
> intent for a key. Still owed before cutover: `account_id` is schema-ready but
> behaviourally unwired (single-account deploy), and `intent_proposals` is
> append-only by convention rather than by database privilege.
>
> **Next actions, in order:** (1) observe the shadow — confirm `net_intents` is
> populated on live runs and `intent_reconciliation.agrees` is true on brake-off
> days, then switch the executor read; (2) the DTB3 ingest per §3.10, whose
> point-in-time and revision rules are settled and must be implemented as
> written; (3) base Wealth Core certification, which gates everything from build
> step 3.

The target: an immutable full-exposure shadow book, a systemic-confirmed fast
shock override moving the book to 40% Wealth Core / 60% short-duration
government paper, an independent 15.5% portfolio backstop, and a
shadow-controlled recovery. Claimed research result 21.14% CAGR / −31.61% max
drawdown / 217.8× terminal wealth, against 19.97% / −41.16% / 166.0× for base
Wealth Core.

**Those numbers are not reproducible in this system today.** See blocker 2.

---

## 1. The load-bearing idea, stated first

The shadow book is not bookkeeping. It is the only honest recovery signal, and
that is the whole reason it must be immutable and full-exposure.

Once the overlay cuts the live book, the live book's returns stop describing the
STRATEGY and start describing the DEFENSIVE POSTURE. A controller that reads its
own output to decide when to stand down has no fixed point: at 40% exposure the
book recovers slowly by construction, so a recovery rule keyed on live returns
either releases far too late or has to be tuned to compensate for the very
suppression it caused. The shadow book answers the question the live book can no
longer answer — *would the unmodified strategy be working right now?* — and that
is what a release decision actually needs.

Everything else in this design follows from keeping that reference honest.

---

## 2. Blockers, in the order they can kill the project

### Blocker 1 — RESOLVED: the sleeve is a rate accrual, not an ETF

Wealth Core marks the book and fills orders in the AS-TRADED domain
(`bt_prices.close_unadjusted`). That is structural: `assert_raw_price_domain`
refuses to run below the coverage floor, because SEP.close is split-adjusted and
substituting it would value every post-split holding at the wrong level without
failing.

Two measurements settled this on 2026-08-06. The exact scan found 43 tickers with
**zero** as-traded close, systematically non-common-stock — SPY, QQQ, IWM, SOXX
at 5,681 rows and 0 covered, plus warrants, units, preferred series, SPACs, an
ADR. And a direct probe for the candidate sleeve instruments returned **0 rows**:

```text
SELECT ... FROM bt_prices WHERE ticker IN ('SHY','BIL','IEF','GOVT','SGOV')
=> (0 rows)
```

Not "present but uncovered" — **absent from the corpus entirely.** An ETF-priced
sleeve would require a new ingest before a single line of controller code could
be tested.

**DECIDED: a deterministic short-Treasury rate sleeve.** It avoids mixed price
domains, ETF inception gaps, dividend and corporate-action treatment, and any
dependence on ETF coverage — and it better represents the economic intent, which
is temporary low-duration risk-free exposure rather than a tactical ETF trade.
Named `treasury_accrual_sleeve` in config and code, deliberately **not** "BIL" or
"SHY", so nobody later assumes ETF-price behaviour.

Pricing the sleeve on `adjusted_close` while the equity book uses
`close_unadjusted` is **refused**: two price domains inside one book is the
precise defect class this corpus work exists to prevent.

The rate series must be point-in-time and fully specified before implementation.
Seven items, none of which may be left to the implementation to decide:

```text
1  which rate            1-3 month Treasury / T-bill total-return proxy
2  accrual convention    daily, and the day-count basis
3  publication lag       what was KNOWABLE on the session, not what was revised
4  weekends + holidays   accrual across non-sessions
5  missing values        carry-forward vs refuse; and the refusal path
6  transition days       does cash earn accrual BEFORE or AFTER execution
7  revisions             no hindsight-filled values, ever
```

Item 3 and item 7 are the ones that silently destroy a backtest: a rate series
fetched today carries revisions that were not knowable then, and a sleeve earning
a revised rate is a small, permanent, invisible look-ahead.

### Blocker 2 — no scoring path today; it blocks CLAIMS, not the module

The wind tunnel currently **refuses every config in the repo**. The
definition-coverage gate fails because `quality_use_gross_profitability` is set
everywhere while the corpus was never backfilled with SF1's `gp`/`assets`, and
`earnings_surprise` has no Sharadar equivalent. Auto-promotion is paused. That is
the intended state — the alternative is promoting on evidence known to be wrong.

Consequence: whatever produced 21.14% / −31.61% / 217.8×, it was **not this
tunnel**. That is a research result, not evidence that this repository reproduces
it, and the two must never be conflated in the record.

But the blocker is narrower than "build nothing first". These proceed safely
without the re-backfill, because none of them depends on a historical return:

```text
state definitions              persistence + restart cuts
pure transition logic          controller composition
unknown-data semantics         intent reconciliation
overlay-off identity tests     synthetic scenario tests
```

These must wait for it:

```text
historical threshold evaluation      crisis characterisation from repo paths
performance comparison               any promotion or re-pin based on returns
```

So the SF1 re-backfill gates the EVIDENCE, not the ENGINEERING.

### Blocker 3 — the parameter count is the largest in the system

The trigger and recovery rules carry roughly fourteen free thresholds:

```
trigger    shadow_drawdown_min           damaged_breadth_min
           green_breadth_max             wc_return_5_max
           wc_return_10_max              breadth_deterioration_5_min
confirm    spy_vol_acceleration_min      spy_return_weak_max
           wc_loss_severe_max
recover    min_defensive_sessions        healthy_sessions_required
           shadow_return_20_min          breadth_normalized_min
sizing     defensive_equity_fraction     backstop_drawdown_pct
```

Against how many independent events? Three that matter — 2008, 2020, 2022. A
fourteen-parameter compound predicate fitted against three observations is close
to the worst case this repo's own DSR/PBO machinery exists to penalise.

The named stress regimes (`gfc_2008`, `covid_2020`, `bear_2022`,
`energy_shock_2015`, `volmageddon_2018`) can characterise behaviour but are
**diagnostic only and can never promote** — their spans are crash/recovery
halves, not a tune/hold-out pair.

And three OVERSTATES the effective sample. The thresholds are correlated with
each other, and the episodes are not homogeneous — a liquidity spiral, a
pandemic gap-down and a rate-driven grind are not three draws from one
distribution. The effective number of independent observations is smaller than
the count of crises, and possibly much smaller.

So the rule is treated as a **frozen, mechanistically motivated challenger — not
an estimated optimum.** The record must say, in these terms:

> The historical results establish plausibility and explainability, not a
> reliable expected return or expected maximum drawdown.

Validation therefore emphasises FALSIFICATION rather than fit:

```text
leave-one-crisis-out, with NO threshold changes
neighbouring-threshold stability across a broad grid
rolling-origin tests
false-positive analysis OUTSIDE the named crises   <- the one most often skipped
exact next-open ledger execution
untouched forward shadow operation
overlay benefit BEFORE and AFTER realistic transition costs
```

False-positive analysis outside the crises is the load-bearing one: a controller
tuned on three drawdowns will trip on ordinary weakness, and the cost of that is
paid in every year that contains no crisis at all — which is most of them.

---

## 3. Architecture

### 3.1 Placement

New pure module `shared/stock_strategy_shared/wealth_core/defense.py`. No DB, no
env, no clock — the same discipline as `crash_brake.py` and the rest of
`wealth_core/`. Live, the backtester and the wind tunnel consume it through
`sys.modules` re-export shims, preserving module IDENTITY. It is **never copied**.

New shared module ⇒ `docker build --network host -t stocker-base:latest -f
Dockerfile.base .` before any consumer is rebuilt, both stacks.

It is **not** an extension of the legacy `crash_brake.py`. That module is a
target-portfolio control with different semantics, different inputs and a
different owner; merging them would give one file two strategies' worth of
meaning.

### 3.2 Two ledgers

```
WealthCoreState   the live book — exists today
ShadowState       a SECOND, INDEPENDENT WealthCoreState instance, advanced by the
                  same engine IMPLEMENTATION and the same configuration, at full
                  exposure, never touched by the overlay
```

**Same implementation and configuration — NOT the same mutable engine object.**
An earlier draft of this plan said "the same engine object", which invites
exactly the bug it was trying to prevent: shared mutable caches, event cursors,
execution queues or memoised frames would silently couple live and shadow, and
the coupling would be undetectable precisely because nothing trades on the
shadow. Two independent state instances, and the engine must be demonstrably
stateless apart from the state passed in. If it is not, that is a defect to fix
before the shadow book is built on top of it.

**The shadow is base Wealth Core, not a stripped strategy.** It excludes only the
PORTFOLIO DEFENSE controls — the shock override and the 15.5% backstop. It keeps
every native Wealth Core mechanism:

```text
KEPT      30% trailing position stops     21-session cooldowns
          119-session one-time review     dividends
          terminal actions                permanent security identity
EXCLUDED  shock override                  portfolio backstop
```

Without the native controls the shadow would answer a different hypothetical —
"how would an unmanaged momentum book be doing?" — when the question a release
decision needs is "would CERTIFIED Wealth Core be working right now?".

The falsifier (build step 3): with the overlay permanently disengaged, shadow and
live must be **bit-identical, all seven economic hashes**. If they can differ at
all when the overlay never fires, the shadow book is not a reference.

### 3.3 Controller state — persisted

Defect 3's lesson. The legacy brake recomputes from scratch every session and
cannot express duration, hysteresis or recovery, and cannot survive a restart.

```
regime                   normal | defensive | recovering
entered_defensive_on     session
defensive_sessions       int      -- minimum-duration counter
healthy_sessions         int      -- consecutive, resets on any unhealthy session
last_evaluable_regime    the fallback for an unreadable session
backstop_armed           bool
backstop_peak            float    -- FROZEN high-water mark, independent
```

New table `wealth_core_defense_state`, one row per session, fully
replay-reconstructible. Restart cuts through every transition are part of
certification, as they already are for the base engine.

### 3.4 The trigger

```
damage  = shadow_drawdown          >= shadow_drawdown_min
      AND damaged_breadth          >= damaged_breadth_min
      AND green_breadth            <= green_breadth_max
      AND wc_return_5              <= wc_return_5_max
      AND wc_return_10             <= wc_return_10_max
      AND breadth_deterioration_5  >= breadth_deterioration_5_min

confirm = spy_vol_accelerating
      AND (spy_return_weak OR wc_loss_severe)

engage  = damage AND confirm
```

Every threshold named in config; none hardcoded. `damage` is the book's own
evidence, `confirm` is the systemic cross-check — the separation is what stops a
single idiosyncratic bad week from cutting the book.

### 3.5 Recovery

```
release = defensive_sessions >= min_defensive_sessions      (>= 10)
      AND healthy_sessions   >= healthy_sessions_required   (>= 3)
      AND shadow_return_20   >  0
      AND breadth_normalized
```

All four. `shadow_return_20` is why the shadow book exists — see §1.

### 3.6 The independent 15.5% backstop, and the composition rule

The backstop tracks the live book's high-water mark and fires at −15.5%,
independent of the shock override. Two controls acting on one book need an
explicit composition rule or their disagreement is undefined behaviour:

```text
effective_target = min(normal_target,
                       portfolio_backstop_target,
                       shock_override_target)
```

**Most defensive wins.** Release occurs only when EVERY active controller
independently permits its own relaxation — one controller clearing must never
override another that remains defensive. Conservative composition is the only
rule that cannot be gamed by a disagreement, and the asymmetric release is what
stops one control's recovery condition from overruling the other's judgement that
the book is still damaged.

Transitions, stated so they cannot be decided per-implementation:

```text
a MORE defensive target   takes effect at the next executable open
a LESS defensive target   takes effect at the next executable open  (same rule —
                          de-risking is not privileged with an earlier fill)
controllers read          the immutable shadow + PERSISTED prior controller
                          state — never partially executed live orders
unknown inputs            preserve the controller's prior REQUESTED target
```

Reading partially executed live orders would make the controller's decision a
function of fill timing, which is the one input that is not reproducible between
live and the tunnel.

### 3.7 Unknown means preserve — by construction, not retrofit

Every input here can be unavailable: breadth, SPY volatility, the shadow return,
the corpus itself. The controller returns `DefenseDecision(evaluable=False)` and
the caller preserves `last_evaluable_regime`.

This is defect 1's lesson applied up front. It is also the reason to land the
defect-1 fix before this work rather than after: the pattern, the vocabulary and
the falsifier shape all already exist for the next control to copy.

### 3.8 One net intent per ticker — reconciled, not merely constrained

Defect 4's lesson, with an important refinement: **a unique index on
`delta_intents` would turn conflicting logic into an insertion failure rather
than resolving it.** Uniqueness is not reconciliation. The layering:

```text
proposals        APPEND-ONLY audit table. Every contributing proposal survives,
                 including ones the reconciliation discarded — diagnostics are
                 not the thing to sacrifice for the invariant.
net_intent       ONE final economic instruction per (run_id, account_id, ticker).
                 The unique index lives HERE.
provenance       every contributing proposal + the priority rule that resolved
                 them, stored with the net intent
```

So the database enforces the invariant on the table that represents the final
executable instruction, while the raw proposals stay inspectable. A reviewer
asking "why did this ticker get this instruction?" gets an answer rather than an
absence.

### 3.9 Three hashes, so the certification anchor survives

Controller state must be verifiable, or live and the tunnel can diverge
invisibly — the failure mode a shadow book is least able to signal, since nothing
trades on it.

An earlier draft proposed an eighth hash or folding defense state into
`daily_state`. **Both are wrong**, because either would re-pin the certified base
Wealth Core hash merely because dormant controller metadata was added — spending
the certification anchor on a change with no economic content. Instead:

```text
wealth_core_economic_hash        the existing seven layers, UNCHANGED. Adding the
                                 shadow engine, controller persistence and intent
                                 reconciliation must not move this at all.
defense_controller_state_hash    regime, counters, frozen peak, requested targets
combined_run_hash                the pair, for whole-system parity
```

This keeps movement attributable: a change in the combined hash with an unchanged
economic hash is a controller change and nothing else, which is exactly the
question a reviewer will have. It also means the overlay-off identity proof is
expressible as an equality rather than a re-pin.

**Acceptance test, stronger than ordinary parity:** with the defensive overlay
disabled, introducing the shadow engine, controller persistence and intent
reconciliation must leave every existing Wealth Core economic output
**bit-identical**. Not "equivalent", not "within tolerance" — identical.

A golden re-pin becomes necessary only if the ECONOMIC hash moves, and if that
happens it is a finding, not a formality: it means the overlay changed base
behaviour while disabled.

### 3.9b The controller transition record — what parity actually compares

Defect 5's lesson generalised. Asserting that the live source *contains a call to*
the shared evaluator is presence, not equivalence, and presence is what let the
fail-open defect stay green.

Parity compares a **serialised controller transition record**, hashed identically
by the live pipeline, the wind tunnel and the backtester:

```text
prior persisted state
every input, WITH its available_at
evaluation status              (evaluable / not, and why)
trigger predicates             each condition's own boolean, not just the AND
requested exposure
healthy-session + minimum-duration counters
resulting persisted state
scheduled next-open action
final reconciled intents
```

Recording each predicate separately rather than only their conjunction is what
makes a divergence diagnosable: two engines can agree on "engaged" while
disagreeing about which condition carried it, and that disagreement is a real
defect that a single boolean hides.

The decisive property: this makes **semantic divergence visible even when the
resulting exposure happens to match**. Two engines producing the same exposure by
different reasoning are not in parity — they are one input away from disagreeing,
and the current test could not tell.

## 3.10 The treasury_accrual_sleeve rate source — SETTLED

**Source: Federal Reserve H.15 daily 3-month Treasury bill secondary-market
rate, series DTB3**, ingested into Stocker as a dated observation table. History
extends to 1954, covering the whole Wealth Core period with room to spare.

Explicitly rejected, and why:

```text
FRED download at replay time      a runtime dependency on a mutable remote
ALFRED as a runtime dependency    same, plus vintage complexity at the wrong layer
Treasury daily bill archive       downloadable bill-rate history starts 2002
3-month CONSTANT MATURITY         a modeled yield-curve point, not the observed
                                  bill proxy
SHY / BIL returns                 absent from the corpus; ETF-price semantics
```

### Point-in-time rule

For session *t*, accrue using the most recent DTB3 observation **publicly
available before the beginning of session t**.

```text
an observation dated Monday       cannot earn Monday's return
                                  becomes eligible for Tuesday, if published
                                  before Tuesday's session
holidays / missing observations   carry forward the last ELIGIBLE published rate
a missing historical observation  is NEVER backfilled from a later one
the ingest stores                 observation_date AND available_at
```

Storing `available_at` separately from `observation_date` is the whole point:
FRED reports observation and update timing separately, so availability can be
modelled rather than assumed equal to the observation date.

### Vintage and revisions — proportionate, and explicitly provisional

A full vintage database is **not** built initially. Instead:

```text
1  ingest the complete DTB3 history ONCE
2  record source, retrieval timestamp, immutable content hash
3  treat that snapshot as the FROZEN research corpus
4  forward operation APPENDS; it never rewrites stored rows
5  an ingest that would change an existing observation is REJECTED unless
   processed as an explicit revision event
6  a one-time ALFRED comparison over representative old dates quantifies
   whether H.15 revisions are material
```

This does not prove the present historical file equals what was published each
day decades ago. It makes that limitation **explicit** and prevents silent
history mutation, which is the failure that actually matters. The proportionality
is justified: prior research attributed roughly **0.38pp** of cumulative
contribution to the defensive sleeve against **28.76pp** from reduced equity
exposure — the sleeve is not where the effect lives.

**This is the one provisional item.** Step 6 must settle whether DTB3 revisions
are immaterial BEFORE any historical performance number is promoted.

### Accrual convention

DTB3 is quoted on a **bank-discount basis**, so `rate / 252` is wrong. Convert
the quotation to an investment-equivalent holding return:

```text
1  discount yield -> implied purchase price of a hypothetical 91-day bill
2  that price -> its 91-day holding-period return
3  holding-period return -> daily GEOMETRIC accrual
4  apply over ACTUAL CALENDAR DAYS between portfolio valuation timestamps
```

The exact formula and day count are frozen in the specification, not chosen at
implementation time. **Weekends earn Treasury accrual even though no equity
session occurs**; the accumulated calendar-day accrual is credited at the next
portfolio valuation.

### Transition-day ordering

```text
a sale at Tuesday's open       starts earning sleeve accrual from Tuesday,
                               AFTER execution
a repurchase at Tuesday's open stops earning sleeve accrual AT execution
never simultaneously           no capital may earn equity and treasury return
                               over the same interval
cash awaiting next-open        remains in the PRIOR economic asset until
                               execution — never retrospectively in the
                               destination sleeve
```

The last rule is the one that quietly inflates a backtest: crediting pending cash
to the destination sleeve on the decision day pays a risk-free return on capital
that was still at equity risk.

## 4. Build order

Each step gated on the previous one. Note that the SF1 re-backfill no longer
blocks steps 3-7 — it gates the EVIDENCE, not the engineering (Blocker 2).

```text
PRE   0  remaining defect fixes: 2 (dead stressed_stop config), 4 (intent
         reconciliation + unique index), 5 (behavioural parity test). [1 DONE]
      1  DONE — defensive asset settled: rate accrual, corpus has no ETFs
      2  the seven-item point-in-time rate spec, agreed before code

BASE  3  base Wealth Core certification completes; baseline hashes FROZEN

BUILD 4  shadow ledger ALONE — no overlay, no trading, no controller.
         FALSIFIER: overlay permanently off => economic hash bit-identical
      5  treasury_accrual_sleeve accounting
      6  trigger + recovery as pure functions; one falsifier per condition,
         each SHOWN TO FAIL
      7  controller state persistence + restart cuts through every transition
      8  intent reconciliation: one net instruction per ticker
      9  wire into the WEALTH CORE chain — never the legacy crash brake
     10  three-hash parity across live / backtester / wind tunnel

EVID 11  SF1 re-backfill; tunnel stops refusing configs
     12  falsification suite (Blocker 3): leave-one-crisis-out, threshold
         stability, rolling origin, FALSE POSITIVES OUTSIDE CRISES, costs
     13  authoritative ACTIONS replay + chain rehearsal
     14  only now: score it. Only after that: discuss activation.
```

Steps 4-10 can proceed behind a disabled flag during base certification ONLY
where they cannot alter certified base behaviour — which step 4's falsifier is
precisely what proves.

## 5. Recommended against

- **Building on the legacy crash brake.** Different strategy, different
  semantics, different owner.
- **Certifying the overlay before base Wealth Core is certified.** Two
  uncertified things at once means a divergence cannot be attributed to either.
- **Quoting the research CAGR as an expectation** at any point before step 10.

---

## 6. Decisions (settled 2026-08-06)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Rate accrual**, named `treasury_accrual_sleeve` | SHY/BIL/IEF/GOVT/SGOV are absent from the corpus entirely (0 rows). Avoids mixed price domains, inception gaps, corporate actions. Seven-item point-in-time spec required first — see Blocker 1. |
| 2 | **`min()` composition; both must permit release** | Conservative composition is the only rule immune to a disagreement between two independent controls. Transition rules fixed in §3.6. |
| 3 | **Wealth Core ONLY** | The signals are Wealth Core semantics — persistent positions, trailing-stop damage, immutable ownership state, shadow holdings. Target-portfolio strategies reconstruct a desired book each cycle and carry a materially different legacy brake; one configurable controller across both would invite semantic compromise and FALSE PARITY. Low-level utilities may be reused later; the controller stays explicitly Wealth Core-specific. |
| 4 | **Base certification first** | Promotion order: base certification → frozen baseline hashes → overlay implementation → overlay-off identity proof → overlay certification. The overlay may be developed behind a disabled flag in parallel ONLY where that cannot alter certified base behaviour. |

## 7. The largest remaining conceptual risk

Not the controller logic. It is **preserving exact point-in-time equivalence
between live and shadow inputs while giving only the live ledger reduced
exposure.**

Both ledgers must see the same prices, the same eligibility, the same corporate
actions, the same session calendar, and the same factor inputs, on the same
sessions, with only the exposure scalar differing. Any divergence in those inputs
turns the shadow from a reference into a second, subtly different strategy — and
because nothing trades on it, the symptom would first appear as an unexplained
release decision, long after the cause.

That is what build step 3 exists to prove, and why it comes before any trigger
logic is written.
