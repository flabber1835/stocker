# Wealth Core defensive controller — DESIGN PLAN

**Status: DESIGN ONLY.** Nothing here is implemented. Nothing here is activated.
Base Wealth Core remains NO-GO (docs/wealth-core-certification.md), and this
overlay sits on top of it.

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

### Blocker 1 — the defensive asset may have no price domain

**This is the one that can invalidate the design as specified.**

Wealth Core marks the book and fills orders in the AS-TRADED domain
(`bt_prices.close_unadjusted`). That is structural, not a preference:
`assert_raw_price_domain` refuses to run at all below the coverage floor, because
SEP.close is split-adjusted and substituting it would value every post-split
holding at the wrong level without failing.

Measured on the NAS on 2026-08-06, the exact scan returned 43 tickers with
**zero** as-traded close, and they are systematically non-common-stock: ETFs
(SPY, QQQ, IWM, SOXX — 5,681 rows each, 0 covered), warrants (`.WS`), units
(`.U`), preferred series (OCCIM/N/O/P), SPACs, an ADR.

SHY and BIL are ETFs. Everything about that pattern says they will be uncovered
too. **This must be confirmed before any implementation begins**, because it
decides the shape of the sleeve rather than a detail of it.

Options if uncovered:

| | approach | verdict |
|---|---|---|
| a | model the sleeve as a **cash-equivalent accrual** from a short-rate series — no ETF prices at all | **recommended** |
| b | ingest SHY/BIL from another vendor or another domain | new data source, new vintage-consistency problem of exactly the kind the raw-close work just closed |
| c | price the sleeve on `adjusted_close` while the equity book uses `close_unadjusted` | **refuse** — two price domains inside one book is the precise defect class this corpus work exists to prevent |

(a) is also the better answer even if SHY/BIL *are* covered. The corpus starts
2003-01 and `bt_actions` now reaches back to 1998; BIL did not exist until 2007
and SHY until 2002, so any ETF-priced sleeve needs a pre-inception fallback
regardless. A rate accrual needs no fallback, has no corporate actions, no
split/dividend vintage question, and no liquidity assumption. The cost is that it
models the sleeve's *return* rather than its *tradability* — acceptable for an
instrument whose entire purpose is to be boring, and it should be recorded as a
caveat rather than hidden.

### Blocker 2 — there is no scoring path today

The wind tunnel currently **refuses every config in the repo**. The
definition-coverage gate fails because `quality_use_gross_profitability` is set
everywhere while the corpus was never backfilled with SF1's `gp`/`assets`, and
`earnings_surprise` has no Sharadar equivalent. Auto-promotion is paused. That is
the intended state — the alternative is promoting on evidence known to be wrong.

Consequence: whatever produced 21.14% / −31.61% / 217.8×, it was **not this
tunnel**, and this system cannot currently reproduce or refute it. Building the
overlay before restoring the scoring path means building something we cannot
evaluate, which is how a research result becomes a deployed assumption.

The SF1 re-backfill is therefore a prerequisite, not a parallel task.

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

So the honest position, which should be written into the certification record
rather than discovered later: **this overlay can be characterised on three
events; it cannot be statistically certified on them.** That is not an argument
against building it. It is an argument against ever describing its backtest
number as an expectation.

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
ShadowState       a SECOND WealthCoreState advanced by the SAME plan_session /
                  run_sessions, at full exposure, never touched by the overlay
```

**Invariant: the shadow book is driven by the same engine object, not a
reimplementation.** Two readers of one strategy that agree until they quietly do
not is the exact failure the factor-coverage contract was written after, and a
shadow book is unusually exposed to it because nothing trades on it — a drift
would produce no symptom at all until it changed a release decision.

The falsifier (build step 3): with the overlay permanently disengaged, shadow and
live must be **bit-identical, all seven hashes**. If they can differ at all when
the overlay never fires, the shadow book is not a reference.

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

### 3.6 The independent 15.5% backstop, and the priority rule

The backstop tracks the live book's high-water mark and fires at −15.5%,
independent of the shock override. Two controls acting on one book need an
explicit composition rule or their disagreement is undefined behaviour:

> **When both are active, the MORE DEFENSIVE target wins, and release requires
> BOTH to permit release.**

Conservative composition is the only rule that cannot be gamed by a
disagreement, and asymmetric release is what stops one control's recovery
condition from overriding the other's judgement that the book is still damaged.

### 3.7 Unknown means preserve — by construction, not retrofit

Every input here can be unavailable: breadth, SPY volatility, the shadow return,
the corpus itself. The controller returns `DefenseDecision(evaluable=False)` and
the caller preserves `last_evaluable_regime`.

This is defect 1's lesson applied up front. It is also the reason to land the
defect-1 fix before this work rather than after: the pattern, the vocabulary and
the falsifier shape all already exist for the next control to copy.

### 3.8 One net intent per ticker

Defect 4's lesson. The controller emits a target exposure; a single
reconciliation step merges per-name decisions and overlay moves into **one net
instruction per ticker** before anything reaches `delta_intents`, plus a unique
index on `(run_id, ticker)` so the invariant is enforced by the database rather
than by convention.

### 3.9 Parity and the golden fixture

Controller state must enter the hash chain, or live and the tunnel can diverge
invisibly — the failure mode a shadow book is least able to signal. Either an
eighth hash or defense state folded into `daily_state`.

Either way this forces a golden-fixture re-pin, which is governed by the standing
rule: **one deliberate re-pin per batch of semantics, with the movement
decomposed** — show what moved and what did not. A fixture patched until it
passes records whatever the code now does.

---

## 4. Build order

Each step gated on the previous one. Steps 1 and 2 are prerequisites, not
parallel work.

```
0  remaining defect fixes: 2 (dead stressed_stop config), 4 (intent
   reconciliation + unique index), 5 (behavioural parity test).   [1 is DONE]
1  confirm the defensive asset's price domain — one NAS query
2  SF1 re-backfill, so the tunnel stops refusing every config
3  shadow ledger ALONE — no overlay, no trading. Falsifier: overlay
   permanently off => shadow and live bit-identical on all seven hashes
4  defensive-asset accounting (rate accrual)
5  trigger + recovery as pure functions, one falsifier per condition,
   each shown to fail
6  controller state persistence + restart cuts through every transition
7  wire into the WEALTH CORE chain — never the legacy crash brake
8  tri-engine hash parity; ONE deliberate golden re-pin, decomposed
9  authoritative ACTIONS replay + chain rehearsal
10 only now: score it. Only after that: discuss activation.
```

---

## 5. Recommended against

- **Building on the legacy crash brake.** Different strategy, different
  semantics, different owner.
- **Certifying the overlay before base Wealth Core is certified.** Two
  uncertified things at once means a divergence cannot be attributed to either.
- **Quoting the research CAGR as an expectation** at any point before step 10.

---

## 6. Open questions

1. **Defensive asset** — rate accrual (recommended) or real ETF prices? Decides
   step 4 entirely, and step 1 may decide it for us.
2. **Priority rule** — confirm "most defensive wins, both must permit release".
3. **Scope** — Wealth Core only, or should the overlay also be available to the
   target-portfolio strategies that carry the legacy brake today?
4. **Sequencing** — base Wealth Core certification first, or overlay in parallel?
   Recommendation: first, per §5.
