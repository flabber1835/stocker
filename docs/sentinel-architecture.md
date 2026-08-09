# Sentinel — architecture and build plan

**Status: DESIGN ONLY. Nothing in this document is implemented.**

**UPDATED 2026-08-09 — the frozen research harness has ARRIVED** and is committed
at `docs/sentinel-handoff/`. It answers three of the four open questions in §8
and CORRECTS a material error in the original draft: **Sentinel 1.1 is NOT a
binary controller.** See §7a. Read `docs/sentinel-handoff/00_README/` first —
`FROZEN_SENTINEL_1P1_RULE.json` is the authoritative parameter set and
`09_GAPS/MISSING_OR_UNRECOVERED.md` states what is still missing.

**LATER THE SAME DAY — the missing breadth classifier and a full standalone
reference implementation arrived.** §8 Q2 no longer reads "NOT FOUND". The
executable rules are in `docs/sentinel-breadth-reconstruction/recovered_breadth_classifier.py`,
a complete independent 1.1 run is in `docs/sentinel-reference-implementation/`,
and `docs/sentinel-reproduction-kit/` carries the reproduction contract and the
certified Wealth Core payloads. Their parity claims have **not** been verified in
this repository — that needs the raw Sharadar corpus — so the
`UNCERTIFIED_BREADTH` gate and the "no decision logic before the tape is
reproduced" rule both still stand. Stocker is
being retired in favour of Sentinel, a much smaller deterministic trading
appliance built from Stocker's proven parts. This file is written so that a
context with no memory of the conversation that produced it can pick up the
build.

Read this before `docs/wealth-core-certification.md` if you are new; read the
certification manifest first if you are continuing the Wealth Core rehearsal,
which is unrelated work still in flight.

---

## 1. What Sentinel is

**Sentinel is not a stock-picking strategy.** It is a deterministic risk and
exposure controller wrapped around Wealth Core.

Wealth Core remains the alpha engine and the authoritative book. Sentinel only
decides **how much** of the live account is exposed to Wealth Core versus a
defensive Treasury-bill sleeve. It never decides **what** Wealth Core holds.

```text
Market/session data
      |
      v
Wealth Core            <- authoritative strategy state, ALWAYS fully invested
      |
      v
Immutable shadow       <- the same book, never de-risked; the truth source
      |
      v
Sentinel features      <- drawdown, breadth, momentum, vol, all from the SHADOW
      |
      v
Sentinel state machine <- fast + slow severe causes, tracked separately
      |
      v
Target exposure        <- 0.0 | 0.55 | 0.65 | 1.0  (see 7a, NOT binary)
      |
      v
Execution projection   <- shadow holdings x exposure -> real share quantities
      |
      v
Next-open execution    <- orders, fills, cash, reconciliation
```

### The single most important invariant

**The shadow never de-risks.** When the live account goes defensive, the shadow
continues as if Wealth Core had remained fully invested. Every Sentinel
measurement comes from the shadow, never from the de-risked live book.

Without this, the controller distorts the signals it uses to decide recovery: a
book that de-risked would show a shallower drawdown, which would look like
recovery, which would re-enter, which would deepen the drawdown. The shadow
breaks that loop by construction.

### The dependency direction, which must never invert

```text
Wealth Core shadow  ->  Sentinel evidence  ->  live exposure
```

Never `live book -> rebuild shadow`. The shadow is authoritative; the live book
is derived.

---

## 2. Why Stocker is retired

Stocker was a general-purpose quant research platform: ~16 services, an LLM
evaluator in the loop, news sentiment, a strategy marketplace, multiple
portfolio builders, a factor experimentation framework, and two simulators.
That shape was right for exploration and is wrong for operating one frozen
deterministic strategy.

Sentinel is a radically smaller problem: **one deterministic engine, two runtime
roles, one database.**

### Retire, do not erase

Keep the Stocker repository and history. Tag it (`stocker-legacy-2026-08`) and
mine it. Before discarding any subsystem, check whether it contains one of four
things worth carrying forward:

```text
1  broker / execution plumbing
2  data ingestion and normalisation
3  operational UI and alerting
4  proven edge-case fixtures and invariants
```

Category 4 is the most valuable and the easiest to overlook. Stocker's invariant
tests encode outages that actually happened — the `DateAnchor` re-trigger loop,
`/health` performing dependency I/O, the capacity contract between planner and
risk gate. Those are worth more than most of the code.

### What is carried forward, essentially intact

The Wealth Core engine and everything certified around it:

```text
shared/stock_strategy_shared/wealth_core/
  run.py            the session driver; already supports deterministic resumption
  adapter.py        the fixed daily event ordering (spec §11)
  state.py          slots, episodes, peaks, cooldowns, review flags
  terminal.py       corporate actions, C1/C2 settlement waterfall
  settlement.py     the terminal-settlement rule, pure
  marks.py          mark status and the resolved/estimated equity split
  eligibility.py    point-in-time investability
  feed.py           normalised vendor bars, warm-up windows
  hashes.py         the seven parity hashes + streaming primitives
  performance.py    CAGR, drawdown, turnover, benchmark comparison
  golden.py         the golden scenario
  risk_profile.py   wealth_core_v1
```

Plus the certification apparatus: the golden fixture, the restart matrix, the
parity manifest, and `services/bt-engine/app/wealth_core_chain.py`'s rehearsal.

### What is explicitly NOT carried forward

Do not rebuild these unless a need is proven:

```text
LLM evaluator, LLM memory, llm-gateway, Ollama
news sentiment, Tavily
Alpha Vantage ingestion
the generic regime machinery
the factor experimentation framework
multiple independent portfolio builders
the strategy marketplace / registry
microservices per pipeline stage
duplicate simulators
separate backtest-only strategy implementations
```

Research on new strategies happens outside the production platform. When
something is worth promoting, the deterministic rule is implemented in the small
core and certified.

---

## 3. Runtime architecture

```text
image: sentinel-engine:<git-sha>          ONE artifact

  sentinel-live     mode=live       small memory limit
  sentinel-bt       mode=backtest   large memory limit
  postgres          one database
```

**Invariant: live and backtest containers may differ in configuration and
runtime role, but never in engine code artifact.** This makes live/backtest
parity structural instead of something tests must keep re-proving — the artifact
being certified is literally the artifact that executes.

**Two containers, not one.** Stocker learned this the expensive way: a live
deploy that recreates containers mid-backtest destroys the run, and three
consecutive nightly baselines were lost to exactly that before an in-flight
guard was added. Separate lifecycles are not optional.

A UI can start inside `sentinel-live` and move out only if it earns its own
container. Same for the broker adapter.

---

## 4. `run_until(date)` — the core capability

There is no `backtester -> live engine` split. There is one deterministic
session machine with one entry point:

```text
engine.restore(snapshot)        load a trusted snapshot
engine.prime(history_window)    rebuild rolling signal inputs; MUTATES NOTHING else
engine.run_until(date)          advance sessions
```

Historical certification: warm up, run 2006..2026.
Production on Monday: restore Friday's snapshot, prime, process Monday.

**The only difference is the source of the next session.**

### Warm-up has a narrow meaning

Warm-up rebuilds **rolling signal inputs** (the trailing window the ranker
needs). It does **not** reconstruct path-dependent portfolio history — slots,
cooldowns, episode peaks, review flags and pending actions come from the
snapshot, because a 127-session price window cannot derive them.

### `prime()` must use a fresh Feed by construction

```text
feed = Feed.from_history(window)      # correct
engine.attach_feed(feed)

engine.feed.prime(window)             # WRONG — invites mutation of a restored feed
```

`Feed` is stateful. Stocker's chain rehearsal already has to build a *second*
warmed feed for its bulk replay, because sharing one replays the whole run
through it twice and surfaces as a divergence with nothing to do with the
strategy. That is the exact hazard `prime()` reopens.

**Falsifier (write this test):**

```text
uninterrupted_run(d)
  ==
restore(snapshot_s) + prime(history_before_s) + run_until(d)
```

compared on: portfolio state hash, feed hash, pending-action hash, ledger hash,
decision hash, candidate_audit hash, daily_state hash, daily_equity hash,
final_result hash, and the exact ordered decisions and fills of the suffix.

---

## 5. Snapshots and recovery

**The live book is reconstructible, not disposable.** The precise contract:

> The live book is reconstructible from a pinned corpus version + a persisted
> engine snapshot + subsequent immutable session inputs and fills.

This matters because **historical data is not immutable**. Sharadar restates;
`bt_data_version` exists and gets bumped when data is corrected in place. If you
replay from inception against today's corpus you may not reproduce the book you
actually traded, and the divergence report cannot tell you whether the broker
drifted or the history moved.

### Two distinct operations

```text
resume_live()
    load latest trusted snapshot
    verify strategy fingerprint + data_version + snapshot_schema_version
    replay only sessions after the snapshot
    reconcile against broker

audit_reconstruct()
    pin an EXPLICIT historical corpus version
    replay from an earlier trusted anchor or inception
    compare hashes
```

Full-inception replay is a deliberate audit operation, **not the boot path**.
Measured: 6.62M bars over 3.5 years is ~2.9 GB resident; twenty years at ~10k
tickers is ~17M bars ~ 7.5 GB, more than the current NAS has.

### Snapshot cadence and retention

Snapshot **every completed session** — the state is small and it minimises the
recovery surface. Retain daily for 90 days, monthly indefinitely.

### Snapshot schema versioning is mandatory from day one

`snapshot_schema_version` belongs **inside the state hash**, so a mismatched
schema cannot produce a hash that looks comparable.

```text
state_hash = H(
    snapshot_schema_version,
    portfolio_state, slot_state, security_state,
    pending_actions, ledger_state, sentinel_state)
```

**Absent-means-zero is forbidden for behavioural fields.** Stocker's
`PortfolioState.from_dict` currently defaults missing fields to zero, justified
by a comment saying Wealth Core has never run in production. That justification
expires the moment snapshots become operational truth.

Field taxonomy for migrations:

```text
STATIC / intrinsic        serialise and validate directly
DERIVED / replayable      may be rebuilt from pinned history
EVENT-MEMORY              observable only once, in the past; MUST be serialised
                          or recovered from an earlier authoritative anchor
```

Worked example from the C1 settlement work:

```text
sessions_since_valid_mark      DERIVED     — rebuildable from marks
terminal_pending_sessions      EVENT-MEMORY — the ACTIONS row appeared on ONE
terminal_pending_terms         EVENT-MEMORY   session and never again
```

So a v1 -> v2 migration is **conditional**: safe when nothing is mid-grace,
otherwise it must FAIL and say "restore from an earlier trusted anchor". And
"nothing is mid-grace" may not be inferred from the absence of the fields.

> **A migration is allowed to fail. Silent reinterpretation is not.**

---

## 6. Versioning and fingerprints

```text
strategy_fingerprint = SHA256(
    wealth_core_config_hash
    sentinel_config_hash
    ordering_profile_hash
    execution_model_hash
    data_contract_version
    golden_fixture_hash)          <- BEHAVIOURAL identity, see below

provenance (recorded, NOT in the fingerprint):
    git_sha
    image_digest
    build_timestamp

recorded on every decision, alongside the fingerprint:
    data_version                  <- which corpus the rules were evaluated against
    snapshot_schema_version
    snapshot_hash
    prior_decision_hash
```

**Why the golden fixture hash and not a code hash.** A code SHA answers "what
source built this binary?"; the golden hash answers "what semantics does this
engine exhibit?". Certification cares about the second. In Stocker the golden
hash moved when the C1 grace period changed semantics and did **not** move when
streaming hashes, settlement counters or retention bounding were added — exactly
the discrimination wanted. A release can then say:

```text
git_sha changed, image_digest changed, behavioural hash unchanged
=> implementation changed; certified behaviour did not
```

**`data_version` is deliberately outside the fingerprint.** The strategy did not
change when the vendor corrected a historical record. Keeping them separate lets
you answer two different questions: which rules produced this decision, and
against which corpus were they evaluated.

### PREREQUISITE: the golden fixture is not yet a complete semantic discriminator

**Do not put the golden hash into the fingerprint until this is fixed.** Three
demonstrated gaps in Stocker:

```text
1  the terms-block path is no longer exercised at all — SEC_STRANDED was its
   only case and now correctly CARRIES instead
2  the grace-clock defect was invisible to it — SEC_STRANDED keeps printing and
   its terms arrive on session 10 of a 10-session grace, so the counter reached
   9 and never expired. The hash would not have moved had the clock been wrong
3  the settlement counters are deliberately excluded from the hash
```

### Semantic coverage must be OBSERVED from execution, not inferred from scenario

Stocker already names its scenario constants and asserts they are referenced.
That was not enough: the scenario did not change, the **semantics** did.
`STRANDED_ANNOUNCED` still fires and still has an assertion, but what it proves
changed from "block" to "carry". Coverage was lost with no constant going
unreferenced.

So the **engine** must emit branch-level markers, and CI must gate on them:

```text
semantic_branch IDs (coarse, stable, versioned — NOT diagnostic prose):
  terminal_announced, terminal_carry, terminal_grace_expired,
  terminal_terms_block, terminal_settled, write_off, conversion_applied,
  split_applied, dividend_applied, stop_triggered, cooldown_entered,
  review_fired, ... plus every Sentinel transition
```

The manifest has two sections with different force:

```text
required_semantic_surfaces:      NORMATIVE — must be exercised every release by
  terminal_terms_block: PASS     the synthetic/golden suite, regardless of which
  terminal_grace_expiry: PASS    historical window is being certified
  ...

corpus_observed_surfaces:        DESCRIPTIVE — evidence quality, never a
  terminal_terms_block: 0        substitute for the floor. A quiet window must
  terminal_settle: 11            not lower the bar; it says so in its manifest
  stop_triggered: 384
```

**Fixture and corpus are near-disjoint on settlement, which is why both are
needed.** Sharadar states no per-share consideration for any of its 19,216
delisted securities, so `EXACT_TERMS` is structurally unreachable from the
corpus — while it is the branch the golden fixture exercises most. The corpus
instead proves the carry -> derived-last-mark path at a scale no fixture can
manufacture.

```text
synthetic fixture   BRANCH COMPLETENESS
historical corpus   PRODUCTION-SHAPED STRESS AND FREQUENCY
```

### Namespaces that must never share keys

Stocker had a real bug here: `SettlementDecision.provenance()` carried a bare
`reason` key that dict-spread let the caller's block reason clobber, so the
audit said `NO_TRUSTWORTHY_MARK` where `MISSING_CASH_PER_SHARE` belonged. Two
questions, one key, resolved silently by insertion order.

```text
semantic_branch   what behaviour occurred      TERMINAL_BLOCK
decision_reason   why the engine chose it      MISSING_CASH_PER_SHARE
evidence          what facts supported it      {last_valid_mark_reason: ...}
```

Typed objects, not free-form dicts.

---

## 7. Sentinel 1.1 — the controller

**Source of truth is the frozen research harness, NOT this document.** The
numbers below are transcribed from the prospectus PDFs and are here for
orientation. They must be imported as explicit versioned configuration from the
harness code before implementation. Re-inferring Sentinel from prose is how you
get a Sentinel that merely resembles 1.1.

### States

```text
NORMAL                live = 100% Wealth Core
ORDINARY_STRESS       live = 100% Wealth Core  <- a SENSOR, not an actuator
SEVERE_STRESS_FAST    live = 0%, defensive sleeve = 100%
SEVERE_STRESS_SLOW    live = 0%, defensive sleeve = 100%
```

Unlike earlier versions, **ordinary stress does not reduce exposure.** Sentinel
1.1 stays invested through ordinary corrections. Ordinary stress exists so the
slow path can ask whether Wealth Core has been impaired long enough; its trigger
is shadow drawdown crossing about **-15.5%**, which starts/maintains the stress
clock and changes no allocation.

### Fast path — sudden systemic crash

All of the following, simultaneously:

```text
shadow drawdown        <= -10%
damaged breadth        >= 85%
green breadth          <= 20%
AND (shadow r5 <= -5%  OR  shadow r10 <= -8%)
damaged breadth increased >= 40 percentage points over 5 sessions
SPY vol5 / vol20 - 1   >= 4%
AND (SPY r20 <= -1%    OR  shadow r10 <= -10%)
```

Fast recovery: minimum severe hold of ~10 sessions, then **three consecutive**
healthy closes with `shadow r20 > 0`, `damaged breadth <= 60%`,
`green breadth >= 20%`. The detector re-arms only after shadow drawdown improves
above roughly **-6%** and the shock condition is absent.

### Slow path — grinding bear

Evaluated only while ordinary stress is active:

```text
ordinary stress active
stress age                       >= 30 sessions
shadow return since stress start <= -2%
shadow r40                       <= -3%
damaged breadth                  >= 75%
green breadth                    <= 25%
```

(An older research form also required `positive-day share <= 50%`; the
simplified version removed it because it changed no historical decision.)

Slow recovery is deliberately more conservative: at least **20 sessions** in the
slow severe state, then **five consecutive** healthy closes on the same three
conditions.

### 7a. CORRECTION — the actuator is NOT binary

The original draft of this document said target exposure is 0.0 or 1.0. **That
is wrong.** The frozen rule adds a *selective recovery ramp* after a canonical
severe recovery:

```text
target_core_exposure in {0.0, 0.55, 0.65, 1.0}
```

On the session a canonical severe recovery fires, the controller asks whether
the recovery is FRAGILE, using prior-close information over a 5-session gate
horizon:

```text
fragile  iff  delta_r40_5 <= 0.0

not fragile   -> target_core = 1.0 immediately
fragile       -> 0.55
                 then 10 consecutive HEALTHY sessions -> 0.65
                 then 10 more                          -> 1.0
                 a renewed severe cause at any point   -> 0.0, ramp abandoned
```

`healthy` here is the same triple used everywhere else: `shadow_r20 > 0`,
`damaged_breadth <= 0.6`, `green_breadth >= 0.2`.

The simplification note in the frozen rule is worth carrying: fragility was
tightened from `<= +0.01` to `<= 0.0` and **the exact historical path did not
change** — so that threshold is on a plateau, not a knife edge.

Consequences for everything else in this document: the three-quantity execution
model in §9 is unchanged and now matters more (a 0.55 target is a real basket,
not a corner case), and the ramp's step counters are additional **event-memory**
state that must be persisted and fail closed:

```text
ramp_active, ramp_step (0.55 | 0.65), ramp_healthy_streak,
ramp_entry_session, ramp_fragility_evaluated_at
```

### Causes are tracked separately; the actuator is still trivial

```text
fast_severe_active: bool
slow_severe_active: bool
severe = fast_severe_active or slow_severe_active

target_core_exposure = 0.0 if severe else ramp_target()   # 0.55 | 0.65 | 1.0
```

**Not one generic severe flag.** The causes can overlap and their recovery
semantics differ; if fast clears while slow remains active, exposure stays 0%
but the governing recovery clock changes. Reason codes must preserve which cause
fired and record cause-set transitions as auditable events even when target
exposure is unchanged.

### Evidence records, not boolean expressions

Seven conditions with two embedded disjunctions is where a transcription error
hides silently. Each predicate carries value, availability and pass/fail
separately:

```text
FastSevereEvidence(
    shadow_dd            = PredicateResult(value=..., available=..., passed=...),
    damaged_breadth      = ...,
    green_breadth        = ...,
    short_loss_r5        = ...,
    short_loss_r10       = ...,
    damage_acceleration  = ...,
    vol_acceleration     = ...,
    spy_r20              = ...,
    shadow_r10_fallback  = ...,
)
```

`None` means **unavailable** and must stay distinguishable from `False`. A
required-but-unavailable predicate fails the transition **closed**, with an
explicit reason (`FAST_EVIDENCE_UNAVAILABLE`), never coerced into an ordinary
negative.

This is a direct lesson from Stocker's crash brake, which was fail-open on the
restore side because one boolean answered both "the evidence says no crash" and
"there is no evidence". Both engines must emit the same canonical
`transition_record()` / `transition_hash()`; parity is asserted on the decision
record, not on the presence of a call site.

### Execution semantics

Decisions are made **after the close**; any exposure change is effective at the
**next eligible open**. The overnight gap belongs to the old allocation —
Sentinel does not pretend it could have exited at the decision close.
Transaction costs are charged only on changed notional. The defensive sleeve is
BIL / short-duration Treasury total return, and the research replay must use the
frozen proxy consistently.

### Sentinel event-memory state (mandatory in the snapshot, fail closed)

```text
ordinary_stress_active
ordinary_stress_start_session
ordinary_stress_start_shadow_nav
ordinary_stress_age
fast_severe_active
fast_severe_entry_session
fast_healthy_streak
fast_rearm_armed
slow_severe_active
slow_severe_entry_session
slow_healthy_streak
slow_stress_reference_session
```

None of these are replayable from a short history window. A silently reset
slow-stress clock delays a severe exit by 30 sessions while looking healthy.

---

## 8. OPEN QUESTIONS — FOUR ANSWERED, ONE UNVERIFIED HERE

The frozen harness arrived 2026-08-09 (`docs/sentinel-handoff/`). Answers below.

```text
Q1  scalar or share-level?     ANSWERED: SCALAR
Q2  breadth definitions        SUPPLIED, claimed exact, NOT VERIFIED IN THIS
                               REPO. The UNCERTIFIED_BREADTH gate STANDS
Q3  recovery episode semantics MOOT (follows from Q1)
Q4  how live NAV is computed   ANSWERED: return-series overlay, so the
                               execution claim is BOUNDED-ERROR, not exact
```

**Q1 — SCALAR, confirmed.** `execution_reference.model` reads *"SCALAR exposure
overlay on immutable Wealth Core shadow"*. There are no live Wealth Core
episodes in the harness; peaks, ages, review flags, cooldowns and terminal state
exist only in the shadow. §9 is therefore the production architecture.

**Q4 — answered precisely, and it settles the certification wording:**

```text
decision_time    official_close
effective_time   next_session_open
cost             10 bps one-way on abs(new_alloc - old_alloc)
defensive proxy  BIL total return
formula          overnight OLD allocation owns close->next-open;
                 intraday NEW allocation owns open->close
```

That is a **return-series overlay**, not next-open basket valuation. A
share-level book cannot reproduce it exactly once integer shares, no-print legs
and cash residuals exist. The execution claim in §10 is therefore a
**bounded-error equivalence** claim. State it that way; do not force a false
equality.

**Q3 — moot.** Scalar means there is no live episode to re-enter.

**Q2 — the classifier ARRIVED later the same day, claiming exact parity.**
Read this sub-section before the forensic history below it: the history records a
reconstruction that fell short, and the file that superseded it is a different
artifact reached by a different route.

```text
docs/sentinel-breadth-reconstruction/recovered_breadth_classifier.py
docs/sentinel-reproduction-kit/04_EXACT_BREADTH_RECOVERY/   (same file + status)
docs/sentinel-reference-implementation/sentinel_1p1.py      (a full standalone
                                                             run, 585 lines)
```

The recovered semantics, verbatim:

```python
green = (own_dd > -0.075) & (r21 > 0.0) & ((age_sessions < 63) | (r63 > 0.0))
red   = (own_dd <= -0.10) & (r21 < 0.0)
sector_stress = mean(red) within each sector on the decision date
amber = (own_dd <= -0.10) | (r21 <= -0.03) | ((sector_stress >= 0.50) & ~green)
```

Two terms the forensic pass could not find are now supplied, and both sit
exactly where its residuals pointed:

```text
AGE-63 EXEMPTION      GREEN's r63 condition is WAIVED for positions younger
                      than 63 sessions. The old reconstruction required r63 >= 0
                      unconditionally, so it under-counted green on young books
SECTOR ESCALATION     AMBER's third clause. This is the one-sided damaged
                      shortfall the residual analysis proved must exist —
                      "amber = damaged_core OR <escalation>" — and the >= 0.50
                      RED-fraction threshold matches the `secv >= .50` constant
                      observed at line 140 of the retained run_firewall_v2_fixed.py
```

Boundaries are asymmetric on purpose and are load-bearing: GREEN uses strict
`own_dd > -7.5%` and `r21 > 0`; RED uses strict `r21 < 0`; AMBER uses inclusive
`r21 <= -3%`. Claimed validation: 7,061/7,061 sessions exact on BOTH green and
amber counts over 160,715 holding-days, mean absolute daily count error 0.000.

**That claim is the author's, and this repository has not tested it.** Verifying
it needs the raw Sharadar corpus (SEP 1998-2026, ACTIONS, TICKERS, SFP) and the
regenerated holding panel; neither is here. What HAS been checked locally is
thin and should not be mistaken for the claim: both files compile, and the four
synthetic controller unit tests shipped with `sentinel_1p1.py` pass. Those
exercise hysteresis and ramp logic on hand-built sequences — they never touch
breadth. So the gate below stands unchanged until someone runs the tape.

Numerical contract, and it is a real reproduction hazard: the original replay
stored lag closes in **float32** before dividing the current close by the lag, so
`r21`/`r63` carry float32 rounding. Reproduce that or prove equivalence — a
float64 reimplementation will disagree on boundary rows, and every boundary in
this classifier is strict-vs-inclusive.

### `priority` is unrecovered, and which strategy that blocks

```text
Sentinel 1.1                              NO  — not consumed, cannot be
Selective Survivor Firewall reconstruction YES — it IS the actuator
```

**Sentinel 1.1 never needs it, and the reason is structural rather than
incidental.** Sentinel reads only AGGREGATE shadow-state signals — damaged
breadth, green breadth, shadow drawdown, short-horizon shadow returns, damage
acceleration, SPY confirmation, recovery-health conditions — and emits ONE
number, a portfolio exposure target. It never asks *which* damaged holding is
worst, so a per-name ranking has no place to be consumed even in principle.
Confirmed in the reference implementation: `priority` appears zero times in
`sentinel_1p1.py`, and every controller predicate there reads only the two
scalars from `green_b = greens/len(held)` / `damaged_b = ambers/len(held)`.

**The firewall does need it**, because that strategy chose SPECIFIC damaged
names to trim (`run_firewall_v2_fixed.py` lines 94 and 100 sort the non-green
candidates by `-priority` and take the top `rank_n`). Anyone reconstructing the
Selective Survivor Firewall is blocked on `priority`; anyone building Sentinel
is not.

`position_features()` in the recovered module therefore raises
`PriorityNotRecoveredError` rather than returning a guess. That is the right
failure and the reason is worth keeping: a fabricated ranking would run, produce
plausible-looking cohorts, and be wrong with no symptom. Failing the whole
function closed also stops the exact-recovered breadth outputs it computes
alongside from carrying an invented one out with them.

---

**Q2 as it stood BEFORE that file arrived — the forensic pass (2026-08-09,
`docs/sentinel-breadth-reconstruction/`), retained because its residual
analysis is what makes the recovered rule credible.**

The original `position_features(g, cfg)` in
`/mnt/data/selective_firewall/run_firewall_experiment.py` was identified by
provenance — `run_firewall_v2_fixed.py` imports that exact path and calls that
exact function — but its bytes are gone. Verified in the retained source:

```text
line  77   damaged_breadth = float(d['amber'].mean())
line 160   green_breadth   = float(d['green'].mean())
```

So Sentinel's `damaged` IS the firewall's `amber` fraction, and `green` is the
`green` fraction. The forensic pass then regenerated the 1998-2026 fixed-30
holding panel (160,715 holding-days) and confirmed it by reproducing the frozen
shadow NAV to floating-point precision — so the reconstruction is operating on
the correct portfolio history.

Two structural findings worth keeping:

```text
DENOMINATOR   the frozen fractions divide by the position-panel ROW COUNT for
              the session, NOT the `holdings` column in the health CSV. With the
              right denominator every frozen fraction resolves to an integer
              count of positions
GREEN         own_dd >= -7.5% AND r21 >= 0 AND r63 >= 0
              exact on 90.27% of 7,061 sessions, mean error 0.119 positions
DAMAGED core  own_dd <= -10% OR r21 <= -3%
              exact on 69.69%, and it NEVER over-predicts — short by 0.403
              positions/session on average, max 5
```

That one-sided residual is the useful part: it proves the original was
`amber = damaged_core OR <escalation>` rather than a different base rule. The
escalation is most plausibly the sector/cluster term, since `position_features`
also returned a `sector_stress` object — but no simple sector proxy reproduces
it, and none has been promoted.

**WHY THIS IS NOT YET USABLE, stated in the direction that matters.** Aggregate
agreement flatters it. On the predicates Sentinel actually evaluates:

```text
predicate                 agreement   true sessions   reconstructed
fast_damaged_ge_0.85        98.7%          216            126     <- misses 42%
slow_damaged_ge_0.75        97.5%          547            372     <- misses 32%
recovery_damaged_le_0.60    96.9%         5792           6011
green predicates           99.4-99.7%      ...            ...     close
```

98.7% agreement on `fast_damaged >= 0.85` means the reconstruction FAILS TO FIRE
on 90 of the 216 sessions where the frozen oracle does. Because the damaged
error is one-sided, every one of those is a missed severe entry — **fail-open,
in the exact place a risk controller must not be**. The green side is close;
the damaged side is not.

That table is the standard the recovered classifier must be held to. It is also
the reason aggregate parity is not enough on its own: a rule can agree on 98.7%
of sessions and still miss 42% of the severe entries, because the sessions that
matter are rare. When the recovered classifier is validated, validate it on the
PREDICATES, not on mean absolute count error.

**Standing rule, UNCHANGED by the recovery:** certify the controller against the
FROZEN breadth oracle, keep any production breadth generation behind an explicit
`UNCERTIFIED_BREADTH` gate, and require exact session-by-session parity with the
frozen tape before that gate is removed. A supplied classifier asserting parity
is a candidate for that test, not a pass of it.

---

**Original Q2 statement, retained:**
`09_GAPS/MISSING_OR_UNRECOVERED.md`: the security-level damaged/green
classifier is *"NOT FOUND in the retained artifacts"*. What survived is the
**aggregate daily tape**, which is enough to certify against but not enough to
implement from.

```text
retained    04_BREADTH_ORACLES/fundamental_portfolio_health_daily.csv
              daily damaged/green, 1998-07-06 onward
            04_BREADTH_ORACLES/sentinel_1p1_exact_daily_with_breadth.csv
              2006-07-31 onward, with canonical/candidate alloc
missing     the per-security classifier that produced them
```

The frozen rule states the constraint: *"DO NOT RE-INFER. Any implementation
must reproduce the frozen breadth tape before controller coding is accepted."*
So a reconstruction is permitted — it just has to be **proven against the tape**,
and until it is, no controller logic may be written.

### The certification target already exists

`02_SENTINEL_1P1_FROZEN_ORACLE/sentinel_1p1_transition_oracle.csv` — **21
transitions over twenty years**, with the breadth and momentum inputs beside
each one. That is the controller acceptance test: same inputs in, same
transitions and allocations out.

Reference metrics, 2006-07-31 to 2026-07-31:

```text
                    Sentinel 1.1      canonical parent (1.0x)
CAGR                22.25%            22.12%
max drawdown        -21.95%           -23.93%
ending multiple     55.61x            54.42x
```

The ramp buys ~2pp of drawdown for ~0.13pp of CAGR — which is what a recovery
ramp is supposed to do, and worth restating whenever someone proposes removing
it for simplicity.

### Remaining harness-reading order

```text
1  reproduce the breadth tape from a candidate classifier      (Q2, BLOCKING)
   the candidate now EXISTS — docs/sentinel-breadth-reconstruction/
   recovered_breadth_classifier.py — and claims exact parity. Step 1 is
   therefore RUNNABLE, and is now a verification rather than a search. It
   needs the raw Sharadar corpus, which is not in this repo
2  replay the 21-transition oracle from those inputs
3  only then write controller code
```

### Q1 (pivotal). Scalar or share-level?

> Does the frozen harness maintain an independent share-level live portfolio, or
> does it compute live performance as an exposure scalar applied to the shadow?

Evidence points at **scalar**: binary target exposure, "costs on changed
notional" (scalar language — a share-level book charges per-security costs on
actual trades), and an immutable shadow as the sole underlying book.

If scalar, there are no live Wealth Core episodes at all, and Q3 dissolves.

**But scalar is a gap, not a simplification.** A broker cannot hold "1.0 x
shadow". Production needs share-level quantities, next-open fills and
reconciliation. That means the production engine **extends** the harness rather
than reproducing it, and the certification claim must be worded accordingly
(see §9).

### Q2. Breadth definitions — the hard blocker

`damaged_breadth` and `green_breadth` appear in every threshold of both paths
and **are not defined anywhere in this repository.** They live in the frozen
harness.

**No Sentinel decision logic may be written until they are imported from the
certified code path and proven against a known breadth tape.** They are part of
the strategy definition, not a feature to reproduce later: if their semantics
drift, both paths become different strategies even with every threshold
transcribed perfectly.

### Q3. Recovery episode semantics (moot if Q1 is scalar)

When Sentinel returns to 100%, do live positions inherit shadow episode state?

```text
A  fresh live episode        entry price, peak, age, review clock all reset
B  shadow continuation       inherits peak, age, review state
```

Wealth Core's own semantics say a re-entry is a **new episode with a fresh
peak** — so under A, every defensive round-trip re-arms every trailing stop and
resets every 119-session review clock. Materially different from B. Do not
choose from first principles.

**Harness query:** on a recovery date where the shadow holds a security
materially below its episode peak, what peak/entry/review state does the newly
live position receive?

### Q4. How exactly is live NAV computed during and across transitions?

Actual next-open basket values, or a multiplied return series? This determines
whether a share-level implementation can reproduce the reference **exactly** or
only within a **bounded error**.

### Harness-reading order

```text
1  scalar vs independent live book              (Q1)
2  if scalar: live NAV, BIL return, changed-notional cost computation
3  transitions: real next-open basket values or multiplied return series  (Q4)
4  breadth definitions                          (Q2)
5  recovery episode semantics                   (Q3)
6  THEN decide the production architecture
```

---

## 9. Production architecture if Q1 is scalar (most likely)

Not two Wealth Core books — **one state machine, one controller, one execution
projection.**

```text
WEALTH CORE SHADOW          authoritative strategy state: episodes, selection,
                            stops, cooldowns, corporate actions, target weights
        |
        v
SENTINEL                    target exposure in {0, 1}
        |
        v
EXECUTION PROJECTION        desired holdings = shadow target holdings x exposure
        |
        v
BROKER                      quantities, orders, fills, cash, reconciliation
```

The live side is **not** a second Wealth Core state machine. Do not duplicate
slot state, peaks, review clocks, cooldowns or terminal memory into it. Live
state holds only what is needed to execute and reconcile:

```text
broker positions, quantities, cash, pending orders, fills,
mark/NAV, reconciliation status
```

Worked example. Shadow owns XYZ at 4%, its episode peak 25% above current price.
Sentinel goes defensive: live sells XYZ, the shadow keeps its episode running.
Sentinel recovers: live buys XYZ again — but this creates **no new Wealth Core
episode**. The shadow still considers it the same old episode, and if the
shadow's continuing stop fires tomorrow the desired live target drops it too.

### Three exposure quantities, never conflated

```text
sentinel_target_exposure    0.0 or 1.0 — what the certified controller wants
execution_target_exposure   translated into a concrete target basket
realized_exposure           what the broker actually achieved
```

This state is legitimate and must be representable:

```text
sentinel target   1.00
execution target  1.00
realized          0.96
pending           0.04
execution_status  PARTIAL
```

**Realized exposure must never feed back into Sentinel's state machine.**
Sentinel judges the immutable shadow and its own event memory. Otherwise an
operational fill problem becomes a market-state input.

> **Execution incompleteness may delay achievement of Sentinel's target, but it
> must never change Sentinel's target or clear the pending intent.**

Recovery flow:

```text
close t      Sentinel decides target = 1.0
open t+1     build orders for the current shadow basket
             fill every executable leg; leave non-fillable legs PENDING
after fills  compute realized_exposure; persist the outstanding delta
later opens  retry pending legs under the frozen execution rules
```

Share rounding and affordability live here too: with 25 names, exact 4% weights
are not achievable in integer shares. Persist both target and realized basket
weights; leftover cash is execution residual, not a Sentinel decision.

### The exposure gap is directional, and the two directions are opposite failures

```text
transition_direction = DEFENSIVE | RECOVERY
target_exposure, realized_exposure, exposure_gap,
pending_notional, pending_leg_count, sessions_since_transition
```

```text
RECOVERY   target 1.00, realized 0.96, gap -0.04
           opportunity cost. Underinvested. A footnote.

DEFENSIVE  target 0.00, realized 0.08, gap +0.08
           8% of NAV still exposed after Sentinel declared severe stress.
           The controller is correct; execution is incomplete. HIGH severity.
```

Partial execution is overwhelmingly a **recovery** phenomenon — liquidations
fill wherever there is a print, purchases face affordability, rounding and
no-print legs. The dangerous exception is a security that **halts during a
crash** and cannot be sold. Stocker's `PendingOrder` already persists intent
across non-tradeable sessions for exactly this reason.

Metrics, split by direction:

```text
RECOVERY   recovery_time_to_target_sessions, recovery_peak_underexposure,
           recovery_pending_notional_peak, recovery_unfilled_leg_sessions
DEFENSIVE  defensive_time_to_target_sessions, defensive_peak_residual_exposure,
           defensive_residual_notional_peak, defensive_unliquidated_leg_sessions
```

Persist offending security IDs and reasons, not just the aggregate gap — "8%
residual" does not say whether that is one position or four, or why.

Also persist `residual_exposure_pnl_since_defensive_signal`, so you can say:
*Sentinel requested zero exposure on date X; execution could not remove 7.4% of
NAV; that residual subsequently cost 1.2% of NAV before liquidation was
possible.* That separates strategy drawdown from execution-imposed drawdown.

---

## 10. Certification: two claims, not one

**Controller certification (exact):**

> Given the same immutable shadow observations, production Sentinel emits
> exactly the same fast/slow state, reason record and binary target exposure as
> the frozen research harness.

**Execution certification (exact or bounded, depending on Q4):**

> Given those same target exposures and shadow target holdings, the share-level
> execution projection reproduces the scalar reference within the defined
> execution and cost model.

Run both simultaneously and decompose any residual into: share rounding,
missing/open-price policy, transaction-cost modelling, cash residual,
corporate-action timing, unfilled legs. Once proven, the share-level
implementation becomes the stronger certification anchor.

If the harness is a pure return-series scalar, call the second claim a
**bounded-error execution-equivalence** claim. Forcing a false equality is worse
than stating the bound.

### Live performance is then additively decomposable

```text
live return = shadow return        strategy   — did Wealth Core work?
            + Sentinel timing      intent     — did the exposure calls help?
            + execution slippage   attainment — did we achieve them?
```

Every term is already computed: the shadow is authoritative and continuous, the
scalar reference (shadow when 1.0, BIL when 0.0) is the counterfactual for the
middle term, and the difference between reference and realized is the third.

This is what makes Sentinel 1.2 evaluable — identical shadow, identical
execution model, different controller, and the middle term is the whole
comparison. It is also what answers "was that the strategy, the controller, or
the plumbing?" after a bad quarter. A design that cannot separate those invites
the wrong fix.

---

## 11. Implementation order

Steps 0-2 are blocking. Do not reorder them.

```text
0  Locate and attach the frozen research harness. Sentinel 1.1 is NOT fully
   specifiable from this repository alone.
1  Answer Q1 and Q4 (scalar vs share-level; how live NAV is computed).
   This determines the whole production architecture.
2  PROVE breadth semantics (Q2) against a known frozen tape. The classifier
   itself no longer has to be found — it is in the repo — but the proof is
   still owed, and no decision logic may be written before it lands.
3  Answer Q3 if Q1 turns out to be share-level.
4  Introduce the shadow/live split appropriate to the Q1 answer.
5  Extend snapshot/restart to every new object: shadow state, shadow ledger,
   live/execution state, Sentinel controller state, pending actions.
6  Shadow-independence falsifier: run with Sentinel disabled vs Sentinel at 0%
   for an interval; assert shadow state, NAV, holdings, peaks, slot state,
   cooldowns, review state, terminal state and decision hashes are IDENTICAL.
7  Sentinel event-memory snapshot schema, fail-closed restore.
8  Typed fast/slow evidence records; no None -> False coercion.
9  Canonical transition records and hashes, emitted identically in both roles.
10 Fast and slow state machines, independently.
11 Trivial actuator: severe = fast or slow; exposure = 0 or 1.
12 Execution projection and next-open execution, live side only.
13 Extend the restart matrix across the new seams.
```

### Restart matrix cases the new seams require

```text
fast severe active
slow severe active
both active
pending transition at the boundary
healthy streak mid-count
ordinary stress clock mid-run
restart while live and shadow differ
```

Plus the case that connects Sentinel to the settlement work:

```text
Sentinel at 0% live exposure
shadow holds SEC_X
SEC_X has terminal_pending_terms / a grace in progress
  -> restart
  -> shadow event state identical
  -> grace counter does NOT reset
  -> live remains empty
  -> subsequent settlement outcome identical to an uninterrupted run
```

> **Shadow state persistence is independent of live ownership.** At 0% exposure
> the shadow holds everything and live holds nothing, so terminal terms, grace
> counters, last-valid-mark state, conversion state, dividend receivables and
> pending settlements all live in the shadow with no live counterpart. A restore
> implementation must never derive "which securities need persisted event
> memory" from live holdings.

That bug would stay invisible for many sessions and surface only when the
terminal branch finally resolved.

---

## 12. The invariants, collected

```text
1   Same image, different roles. sentinel-live and sentinel-bt run the same
    sentinel-engine:<git-sha> artifact.
2   Behavioural identity, not source identity. The golden fixture hash
    participates in the strategy fingerprint; git SHA is provenance only —
    AFTER the fixture is proven a complete semantic discriminator.
3   Pinned input history. Every snapshot and decision records data_version.
4   Versioned state semantics. snapshot_schema_version is inside the state hash;
    behavioural fields fail closed, never default.
5   Restart equivalence. restore + prime + run_until is hash-equivalent to
    uninterrupted execution.
6   No mutable shared Feed across replay seams.
7   Live recovery is snapshot + short replay. Full-inception reconstruction is
    an audit operation, not a boot path.
8   The shadow never de-risks and is never derived from the live book.
9   Sentinel scales HOW MUCH of the target is held, never WHAT is in it.
10  Realized exposure never feeds back into the controller.
11  Execution incompleteness delays attainment; it never changes intent.
12  Fast and slow severe causes are tracked separately and permanently.
13  Close-t decision executes at open-t+1; the overnight gap belongs to the old
    allocation.
14  Semantic coverage is observed from execution, never inferred from scenario
    construction. Fixture coverage is normative; corpus coverage is descriptive.
```

Nearly all of these are falsifiable. Each should have a test that fails when it
is violated, and #9, #10 and #11 in particular are the ones a well-meaning
refactor is most likely to break silently.
