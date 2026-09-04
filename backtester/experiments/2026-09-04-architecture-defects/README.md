# Wealth Core / Sentinel architecture-defect investigation — 2026-09-04

## Status

Research only. No production activation. `main` is read-only.

Owner-authorized hard budget: **at most 10 completed economic candidate experiments**. Screening and observational diagnostics consume zero. A candidate arm consumes one experiment once its fresh chronological measured replay completes. Infrastructure failure before measured replay consumes zero.

**Current budget: 4 / 10 consumed; 6 remain.**

The complete durable record of hypotheses, exact runs, artifact IDs/digests, metrics, diagnostics, analysis, and decisions is in [`RESULTS_AND_ANALYSIS_LEDGER.md`](./RESULTS_AND_ANALYSIS_LEDGER.md).

## Baseline

Control: Strategy 9, **Broad simplified fixed breadth calibration**.

- Historical Actions run: `33876316789`
- Head: `238891bf67cc75afa3efd4b82b71cfdb52c2fd75`
- Artifact: `9939066139`
- Stable economic projection SHA256: `3a8a03799ddd06f14e1d8625e2f6540192e7255a11cb33e9462b2c9ffd625053`
- Max-history: CAGR `19.7934%`, max DD `-33.4590%`, Sharpe `1.066746`
- 20-year: CAGR `20.0964%`, max DD `-29.6266%`, Sharpe `1.091505`

The dynamic breadth experiment produced identical signals/allocations despite repeated threshold changes; breadth-scale tuning is an economic plateau and is closed for this pass.

## Completed experiment ledger

| # | Candidate | Evidence | Decision |
|---:|---|---|---|
| 1 | owned-book divergence mode | run `33908036047`, head `d6719c6a0a3b394d344f4d54e01cebc9821981be` | **REJECTED** — too many false defensive entries; no DD gain |
| 2 | r20-only post-severe recovery | same fresh multi-arm run | **REJECTED** — false 2000 bear-market recovery; DD worsened |
| 3 | cross-surface recovery concordance | run `33912976460`, artifact `9953264982` | **RETAINED** — improves 10/15/20y CAGR, DD and Sharpe; fixes most 2019 delay |
| 4 | immediate symmetric Wealth Core deterioration exit | run `33920953006`, artifact `9956419168` | **REJECTED** — fixes 2018 but creates extreme churn and destroys long-run economics |
| 5-10 | uncommitted | — | reserved |

Detailed Experiment 3 record: [`EXPERIMENT3_RECOVERY_CONCORDANCE.md`](./EXPERIMENT3_RECOVERY_CONCORDANCE.md).

Detailed Experiment 4 design, results, attribution and rejection analysis: [`EXPERIMENT4_SYMMETRIC_EXIT.md`](./EXPERIMENT4_SYMMETRIC_EXIT.md).

## Current architecture position

**Sentinel:** retain Experiment 3 cross-surface recovery concordance. It added only three early recovery releases — 2012-01-18, 2016-02-25, and 2019-02-04 — and did not weaken the 2000-2001, 2008-2009, or 2022 weak-recovery cases.

**Wealth Core:** 2018 contains a real retention/selection weakness, but the correct repair is not yet established. The zero-budget 2018 diagnostic showed 76.19% of gross negative holding P&L occurred after the 12 identified held names were already outside the existing top-10% momentum pool with negative recent-21 return; they remained held a median 65.5 sessions after first detection. Experiment 4 proved that immediate daily symmetry is far too aggressive.

The age-119 review is intentionally one-time by specification. Repeating it would be a strategy redesign, not a bug fix.

## Zero-budget evidence

### 2018 retention diagnostic — completed

- Run: `33917445284`
- Head: `154fcfdeb06d46ca578c8c4230f16921b84a2cb6`
- Artifact: `9954537697`
- Artifact digest: `sha256:a84a158f5a774fc9229a6df3cff9e5913892171bbb49a6d060e0f39033f72a48`
- Decisions changed: false
- Budget consumed: 0

Key findings: 2018 Wealth Core `-19.1185%`, within-year DD `-31.5475%`; 12 deterioration episodes; 76.1945% of gross negative holding P&L occurred after deterioration; median retention after first detection 65.5 sessions, max 115.

### Mechanical-state diagnostic — in progress

This is the pre-Experiment-5 audit of review state, exit-fill delay, admission/replacement pressure, and a possible research-replay/canonical cooldown convention mismatch.

- First attempt: `33926159642` at `b99a1472fe90aecebc4da2ead989130d0fb887bc`; harness failed before replay on an obsolete source seam. Budget impact: 0.
- Fixed rerun: `33926503274` at `a9297b8669217ee1613a7f8d132a3e5180c21640`; fresh zero-budget replay currently running.

No result from this diagnostic is accepted until the rerun completes and its validation/artifact pass.

## Research discipline

A surviving change must have a structural mechanism, use contemporaneous/strict-prior information, preserve next-open execution, avoid episode-specific tuning, and survive broad-history falsification. A disappointing experiment is rejected as specified; its thresholds are not adjusted until it works.

In particular, **do not tune Experiment 4**. First determine whether cooldown, replacement capacity, exit execution, or review-state handling contains an actual mechanical defect. If no defect exists, any further retention change is explicitly a strategy redesign and must be treated as such.
