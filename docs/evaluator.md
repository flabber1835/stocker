# LLM Evaluator — design

Status: design (not yet built). Foundations in place: generic factor registry, JSONB
factor store, per-run **health record** (`shared/health_record.py`), `/validate-llm-change`
partition gate, backtester, strategy registry.

## Purpose & boundary

The evaluator closes a **human-gated learning loop** around the generic quant ranker:
observe outcomes → form evidence-scored hypotheses → (optionally) test them in a walled
backtester → propose a config diff → validate → backtest on a holdout → **human approves**
→ registry. It never trades, never sizes, never bypasses risk, and never deploys code or
config on its own. **LLM = suggest/interpret; Python = compute; human = approve.**

The dominant failure mode is **overfitting / data-snooping**, and the backtester-as-tool
*amplifies* it. Every design choice below exists to give the LLM rich evidence to reason
with while making it structurally hard to act on noise.

Three tiers (cadence increases with risk):
- **Tier 1 (weekly, read-only):** a written narrative + hypothesis-ledger updates from the
  evidence packet. Changes nothing.
- **Tier 2 (periodic, gated):** a `ready` hypothesis becomes a config diff → validate →
  backtest (holdout) → human → registry.
- The backtester tool lives in Tier 2's exploration, caged (below).

---

## The weekly evidence packet (the LLM's input)

Python computes this deterministically from accumulated history; the LLM interprets it.
It is **bounded** (summaries + per-factor scalars, never row dumps). Layers:

### 1. Per-factor predictive evidence — for EVERY factor, not just weighted ones
This is the enabler for "add/activate/promote a factor" recommendations. Computed for:
- the **weighted** factors,
- the **dormant** registry factors (issuance, small_cap, volume_surge, high_volatility —
  weight 0 but computed every run), and
- the **display indicators** (drawdown_21d, excess_dd_21d, idio_vol, beta, …) which are
  computed but not currently scored — so the LLM can recommend promoting e.g. falling-knife
  to a scoring factor *with numbers behind it*.

Per factor:
- **Realized IC** (rank/Spearman correlation of factor score vs forward return), at
  **multiple horizons** (e.g. 1-week and 1-month — holding is variable under the buffer
  model), computed by joining a *past* run's `factor_scores`/`rankings` JSONB with the
  realized forward return. (NOTE: cannot be computed at the run itself — needs forward data.)
- **Sample size `N` and an IC t-stat / standard error** — so confidence is explicit.
- **Rolling IC + decay** (not just a point estimate) — a high-but-unstable IC is
  overfit-prone; the LLM must see stability, not a lucky window.
- **Regime-conditional IC** (per detected regime) — *with a skepticism flag*: regime-
  conditional tuning is the classic overfit trap; provide the data, instruct caution.

### 2. Orthogonality / correlation structure
"Incremental value ≈ IC × (1 − corr to existing factors)" is the core decision rule, so the
packet must carry:
- the **factor–factor correlation matrix** (incl. dormant + display indicators), and
- each factor's **correlation to the current weighted composite**, and ideally
- **marginal IC** (IC controlling for the existing factors) — the real test of "does adding
  this factor *add* signal or just duplicate momentum?".

### 3. Attribution & regret
- Per-factor **contribution to realized return** (what helped/hurt, this period + cumulative).
- **Regret / opportunity cost:** performance of the **non-selected universe** — what we
  missed, and which factor would have caught it.

### 4. Risk, behavior & cost
- Turnover, realized vol vs `vol_target`, drawdown, hit rate, effective beta, weight drift.
- **Veto outcomes:** did falling-knife vetoes pay off (vetoed names that kept falling vs
  recovered) — direct evidence for tuning or promoting the drawdown signal.
- **Transaction-cost proxy from turnover** — a tweak that lifts IC but doubles turnover can
  be net-negative; the LLM needs the turnover delta to judge *net* benefit.

### 5. Bookkeeping
- `N` observations behind every claim; `config_hash`(es); regime; the run health-record
  references. The LLM must be instructed: **a single week's P&L is noise; require
  accumulated evidence; account for how many hypotheses have been tried (multiplicity).**

---

## What the LLM needs to do its job *correctly*

R1. **Decision rule, not metric-chasing.** It reasons about *net incremental value* —
`IC × (1 − corr) − cost`, stable across time/regime — not a single Sharpe number. The
packet (IC + correlation + turnover/cost + stability) exists to support exactly this.

R2. **Confidence & sample size on everything.** N, t-stats, rolling stability — so it can
distinguish signal from a lucky window and say "not enough evidence yet."

R3. **Memory via the hypothesis ledger** (not re-deciding weekly): `evaluator_hypotheses`
rows {statement, status candidate→ready→confirmed/rejected, weeks_supported/total,
confidence, economic_rationale}. Counters accumulate; a hypothesis graduates only on
sustained evidence.

R4. **The action map** — it must know what it can act on vs only recommend:
- **Activate a dormant registry factor** (weight 0 → weight): **config-only** → can drive
  through the gate end-to-end.
- **Promote a display indicator to a scoring factor** (e.g. falling-knife/excess_dd): needs
  a few lines of **code** (registry + FactorWeights + composite wiring) → **recommend only**;
  a human implements, then it's gated.
- **A genuinely new factor** (new math): **recommend only**.
- It must never propose a protected-field change (identity / data-source / falling-knife
  veto thresholds) — `/validate-llm-change` rejects those by construction.

R5. **Self-skepticism prompting** — explicit instruction to assume noise, penalize
multiplicity, and prefer "no change" when evidence is thin.

---

## Backtester as a tool (the cage)

Exposing the backtester turns the evaluator from a blind proposer into an **iterative
experimenter** — and into the most efficient overfitting engine in the system unless caged.
The tool is **read-only** (no trades/config change), so the danger is statistical, not
operational. Requirements:

T1. **Constrained contract.** Input: a config **diff within the tunable partition** (the
tool calls `validate_llm_tunable_diff` and **refuses** a protected-field diff — enforced by
the tool, not the prompt). Output: **bounded metrics** (Sharpe, max drawdown, turnover,
per-factor IC/attribution, vs-benchmark) for a **specified window** — NOT the full trade log
(token blowup + invites curve-fitting on noise).

T2. **Walled data.** The tool runs ONLY on a **train/validation window**. The **holdout is
never reachable by the tool** — the tool rejects a window that overlaps it. Final validation
on the holdout happens **outside** the LLM loop, deterministically.

T3. **Iteration budget + full logging.** Hard cap on backtest calls per cycle; **every call
logged** (diff, window, result) so the search path is auditable for overfitting. No silent
unlimited search; log what was tried and how many.

T4. **Pre-registration + multiplicity penalty.** The LLM states the hypothesis + **economic
rationale before** backtesting. A proposal justified only by "best of N tries" is rejected;
the more configs tried, the higher the evidence bar.

T5. **Per-factor metrics in the output.** The backtest result must expose per-factor
IC/attribution (not just portfolio Sharpe) so an "add/activate factor X" hypothesis can be
tested as "does it improve backtested IC/Sharpe *net of turnover*", linking the packet's
observational IC to a backtested result.

T6. **Out-of-loop confirmation is mandatory.** A config that wins the train/val loop is still
only `candidate` → must clear the **holdout backtest + forward paper** before `ready`. The
tool accelerates *hypothesis generation*, never *approval*.

T7. **Determinism.** Backtests are deterministic given (config, window); the tool returns
`config_hash` + window so any result is reproducible and auditable.

The packet (cheap, observational) **generates** hypotheses; the walled backtester (expensive)
**tests** them; the holdout + human gate **prevent acting on noise**. All three are required
— packet without backtester = can't validate; backtester without holdout/budget = overfit.

---

## Proposal lifecycle

```
weekly packet → LLM narrative + ledger updates (candidate)
  → [evidence threshold] → ready
  → LLM emits config diff (tunable partition) + economic rationale
  → /validate-llm-change (schema + safety + partition)
  → backtester: long history + accumulated paper + RESERVED HOLDOUT (out-of-loop)
  → human review/approve  → strategy registry  → activate
```
Never auto-deploys. A permanent untouched holdout is reserved so the live number stays
trustworthy. Keep mechanical regime-rotation OFF — adaptation = slow, evidence-gated drift.

---

## Relationship to the health record

The per-run **health record** (`artifacts/runs/run_<session>.json`) is the raw per-run
evidence + invariant audit. The **weekly packet** is the *derived* view: it joins multiple
runs' scores with realized forward returns to add IC, correlation, attribution, and regret —
the things that need history and forward data. Same lineage, two cadences: the health record
is written at chain end; the packet is computed weekly from accumulated records + returns.
