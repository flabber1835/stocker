# Architecture-defect experiment results and analysis ledger

This file is the durable results ledger for the 2026-09-04 Wealth Core / Sentinel architecture-defect investigation. It records completed economic experiments, zero-budget diagnostics, exact GitHub evidence, and the decision taken from each result. `main` remains read-only; all work is research-only.

## Experiment budget

Owner-authorized maximum: **10 completed economic candidate experiments**.

A candidate consumes one experiment only after its fresh chronological measured replay completes. Same-head control replays, screening, and observational diagnostics consume zero. Infrastructure failures before measured candidate replay consume zero.

**Current budget: 4 / 10 consumed; 6 remain.**

## Control — Strategy 9

Strategy 9 is the fixed control: Broad simplified fixed breadth calibration.

- Historical run: `33876316789`
- Head: `238891bf67cc75afa3efd4b82b71cfdb52c2fd75`
- Artifact: `9939066139`
- Stable economic projection SHA256: `3a8a03799ddd06f14e1d8625e2f6540192e7255a11cb33e9462b2c9ffd625053`
- Max-history: CAGR `19.7934%`, max DD `-33.4590%`, Sharpe `1.066746`, ending multiple `174.286531x`
- 20-year: CAGR `20.0964%`, max DD `-29.6266%`, Sharpe `1.091505`

The dynamic-breadth calibration later changed thresholds 19 times but produced identical signals and allocations. Breadth-scale tuning is therefore treated as an economic plateau and is not a useful direction for this architecture pass.

## Experiment 1 — owned-book divergence mode — REJECTED

Hypothesis: the stateful owned Wealth Core book can deteriorate before the recent-leadership witness, so add an owned-book divergence trigger while preserving the existing LD-RC path.

Rule added:

```text
native/effective full
AND wc_drawdown <= -10%
AND wc_r20 < 0
AND wc_r40 <= -8%
AND spy_r20 >= 0
```

Evidence:

- Actions run: `33908036047`
- Exact head: `d6719c6a0a3b394d344f4d54e01cebc9821981be`
- The fresh chronological candidate replay completed. The workflow later failed its old broad byte-level projection check because telemetry had widened the output schema; there is no immutable artifact for this run.

Result, max history:

| Surface | CAGR | Max DD | Sharpe |
|---|---:|---:|---:|
| Strategy 9 control | 19.7934% | -33.4590% | 1.06675 |
| E1 | 19.6191% | -33.4590% | 1.06530 |

Analysis: E1 added 10 owned-book divergence entries and increased allocation transitions from 37 to 50 without improving maximum drawdown. The new trigger fired in rebound states as well as genuine deterioration, including non-target episodes. It helped parts of late 2018, but the false defensive episodes outweighed that benefit.

**Decision: reject.** The owned-book sensor mismatch is real; this direct OR trigger is too permissive.

## Experiment 2 — r20-only post-severe recovery — REJECTED

Hypothesis: after severe defense, the existing dual-positive r20/r40 recovery gate is unnecessarily slow. Preserve the divergence latch but allow recovery after seven consecutive recent-leadership `r20 > 0` sessions once native exposure is above zero. Preserve the existing SPY V-rebound alternative.

Evidence:

- Same fresh multi-arm run: `33908036047`
- Exact head: `d6719c6a0a3b394d344f4d54e01cebc9821981be`

Result, max history:

| Surface | CAGR | Max DD | Sharpe |
|---|---:|---:|---:|
| Strategy 9 control | 19.7934% | -33.4590% | 1.06675 |
| E2 | 19.6964% | -37.1649% | 1.05665 |

Analysis: E2 solves the intended 2019 delayed re-entry, but it also treats the 2000 bear-market rebound as durable recovery and re-risks too early. The drawdown damage is material.

**Decision: reject.** The r40 component is economically load-bearing against false recovery. Any recovery repair must discriminate a broad durable repair from a rebound inside a damaged book.

## Experiment 3 — cross-surface recovery concordance — RETAINED

Hypothesis: early recovery is trustworthy only when the owned book, the current leadership opportunity set, and SPY are concordant.

Early-release rule while a recovery episode is active:

```text
recent_positive_streak >= existing LDRC_REC  # 7
AND wc_r20 > 0
AND recent_leadership_r20 >= wc_r20
AND spy_r20 >= wc_r20
```

No new fitted numeric threshold was introduced. Existing dual-positive r20/r40 recovery and SPY V-rebound remain fallback paths. Existing divergence mechanics remain unchanged.

Evidence:

- Actions run: `33912976460`
- Exact head: `3f27834db427e71d9bb8d0b6160c8835b739c906`
- Artifact: `9953264982`
- Artifact ZIP digest: `sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f`
- Fresh control stable projection parity: PASS

Headline results:

| Window | Control CAGR | E3 CAGR | Control DD | E3 DD | Control Sharpe | E3 Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 10y | 24.0168% | 24.4037% | -29.6266% | -28.6186% | 1.183121 | 1.198502 |
| 15y | 20.3371% | 20.6461% | -29.6266% | -28.6186% | 1.116104 | 1.129585 |
| 20y | 20.0964% | 20.3277% | -29.6266% | -28.6186% | 1.091505 | 1.101492 |
| max | 19.7934% | 19.9548% | -33.4590% | -33.4590% | 1.066746 | 1.073666 |

Max-history E3 ending multiple: `181.122029x` versus control `174.286531x`.

E3 added exactly three cross-surface releases:

| Decision | Difference interval | Prior control | E3 | Core return in interval | E3 minus control |
|---|---|---:|---:|---:|---:|
| 2012-01-18 | 2012-01-19..2012-01-26 | 0% | 100% | +0.5860% | +0.3370% |
| 2016-02-25 | 2016-02-26..2016-03-11 | 65% | 100% | +1.4503% | +0.3957% |
| 2019-02-04 | 2019-02-05..2019-02-22 | 0% | 100% | +3.1045% | +2.8370% |

It did not create an early release in the 2000-2001, 2008-2009, or 2022 weak/false recovery cases.

Analysis: this is the first surviving architecture change. It fixes most of the 2019 re-entry delay without weakening the historical bear-market protection and improves long-horizon CAGR, drawdown, and Sharpe. It does not repair the earlier 2018 Wealth Core deterioration; that is a separate problem.

**Decision: retain E3 as the current Sentinel architecture.**

## Zero-budget diagnostic — 2018 Wealth Core retention asymmetry

Purpose: establish whether the 2018 loss was concentrated after held securities had already deteriorated relative to Wealth Core's existing admission-quality information.

Diagnostic condition:

```text
held security outside existing top-10% momentum pool
AND existing recent-21 return < 0
```

Evidence:

- Actions run: `33917445284`
- Exact head: `154fcfdeb06d46ca578c8c4230f16921b84a2cb6`
- Artifact: `9954537697`
- Artifact ZIP digest: `sha256:a84a158f5a774fc9229a6df3cff9e5913892171bbb49a6d060e0f39033f72a48`
- Strategy decisions changed: false
- Experiment budget consumed: 0

2018 observations:

- Wealth Core calendar return: `-19.1185%`
- Wealth Core within-year max DD: `-31.5475%`
- 12 deterioration episodes / 12 tickers first detected in 2018
- Gross negative holding P&L after deterioration: `$-2.5223bn`
- Share of gross negative holding P&L after deterioration: `76.1945%`
- Post-deterioration net P&L: `$-143.5m`
- Post-deterioration net loss as share of total Wealth Core calendar net loss: `44.02%`
- Sessions retained after first deterioration: mean `63.17`, median `65.5`, max `115`

Longest observed examples included WGHTQ (115 sessions), CAT (104), EC (97), IBKR (82), REGI (80), and GYRE (68).

Analysis: the 2018 weakness is strongly associated with stale retention after a name has left the quality set used for admission. This proves a structural asymmetry exists. It does not prove that immediate symmetry is the correct repair.

## Experiment 4 — immediate symmetric deterioration exit — REJECTED

Hypothesis: repair the admission/retention asymmetry by immediately scheduling a next-open exit when a held security is outside the existing top-10% momentum pool and has negative existing recent-21 return. Existing trailing stop remains first priority; age-119 review remains; 21-session cooldown remains; E3 remains downstream.

Evidence:

- Actions run: `33920953006`
- Exact head: `43e6bbe2d7a73cc37f1eee4cda3312a2bc9c9588`
- Artifact: `9956419168`
- Artifact ZIP digest: `sha256:1c78a71a41ebe932e3bad1ab18db9b261a6c40b1a4521341ed5262d26fbdcea5`
- Fresh E3 control parity: PASS
- New fitted numeric thresholds: 0
- Deterioration signals/executed exits: `1849 / 1849`

E3-controlled results:

| Window | E3 control CAGR | E4 CAGR | E3 control DD | E4 DD | E3 control Sharpe | E4 Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 5y | 27.2967% | 16.7197% | -20.4865% | -30.7409% | 1.318578 | 0.775501 |
| 10y | 24.4037% | 17.0936% | -28.6186% | -30.7409% | 1.198502 | 0.826339 |
| 15y | 20.6461% | 12.9354% | -28.6186% | -30.7409% | 1.129585 | 0.702805 |
| 20y | 20.3277% | 12.3836% | -28.6186% | -33.0801% | 1.101492 | 0.682533 |
| max | 19.9548% | 12.7469% | -33.4590% | -42.2478% | 1.073666 | 0.705060 |

Wealth Core itself fell from max-history CAGR `17.1971%` / DD `-45.1420%` / Sharpe `0.853550` to CAGR `12.0524%` / DD `-55.8012%` / Sharpe `0.610323`.

Turnover changed from `747 buys / 727 sells` to `2400 buys / 2391 sells`.

2018 did improve dramatically:

- E3-controlled calendar 2018: `-20.0204%` -> E4 `+15.9299%`
- Wealth Core calendar 2018: `-19.1185%` -> E4 Core `+1.8785%`
- Jun 12 to Sep 20: `-10.5022%` -> `+7.6960%`
- Sep 20 to Dec 19: `-19.6631%` -> `-4.9862%`

Across changed calendar years, E4 was better in 7 and worse in 22.

Analysis: E4 is a clean falsification of the naive symmetric repair. The diagnostic was correct that stale retention caused material 2018 damage, but reacting immediately whenever admission-quality conditions cease to hold converts Wealth Core into a high-churn short-horizon momentum system. It discards the long-duration winners the original retention architecture was deliberately designed to preserve. The result is not a reason to tune top-decile, recent-return, persistence, or other thresholds until the backtest improves.

**Decision: reject E4 unchanged. The structural diagnosis survives; the immediate-exit implementation does not.**

## Intentional one-time review — specification finding

Repository inspection after E4 established that the age-119 review is explicitly one-time by design, not an accidental implementation bug. Passing the review permanently marks the holding reviewed; repeated reviews were deliberately excluded to avoid turning temporary rank slippage into recurrent exits.

Therefore a repeated age-119 review would be a new strategy design, not a mechanical bug fix. It must not be introduced under the label of bug repair.

## Current zero-budget mechanical diagnostic

The next step is a mechanical audit before spending Experiment #5. It measures review state, exit fill delay, slot/replacement pressure, and a possible research-replay/canonical cooldown convention mismatch.

- First attempt: run `33926159642`, head `b99a1472fe90aecebc4da2ead989130d0fb887bc`
- Outcome: infrastructure/harness failure before replay. Exact error: `fill diagnostic: expected one seam, found 0`. Budget impact: zero.
- Fixed rerun: `33926503274`, head `a9297b8669217ee1613a7f8d132a3e5180c21640`
- Status at ledger update: fresh zero-budget mechanical replay in progress.

No conclusion from this diagnostic is recorded until the rerun completes and its artifact validates.

## Rejected zero-budget screens

A naive selection-divergence overlay based on `wc_dd <= -10%`, Core r20 negative, recent leadership r20 positive, and SPY r20 positive was screened from prior evidence and rejected without consuming budget. It overfired across roughly 48 episodes. A raw sign-mismatch persistence screen similarly did not isolate the 2018 path. These directions are closed unless new causal evidence changes the mechanism.

## Current architecture position

- **Retained Sentinel change:** E3 cross-surface recovery concordance.
- **Rejected:** E1 owned-book divergence OR, E2 r20-only recovery, E4 immediate symmetric Wealth Core exit.
- **Established diagnosis:** 2018 includes a Wealth Core retention/selection weakness; 2019 included a Sentinel recovery-delay weakness substantially repaired by E3.
- **Not established:** the correct minimal Wealth Core retention repair.
- **Do not tune E4 thresholds.** First determine whether there is a true mechanical defect in cooldown, replacement capacity, exit execution, or review-state handling. If no defect is found, any further change to retention is explicitly strategy redesign.

## Budget ledger

| # | Candidate | Decision | Budget |
|---:|---|---|---:|
| 1 | owned-book divergence mode | REJECTED | consumed |
| 2 | r20-only post-severe recovery | REJECTED | consumed |
| 3 | cross-surface recovery concordance | RETAINED | consumed |
| 4 | immediate symmetric deterioration exit | REJECTED | consumed |
| 5-10 | uncommitted | reserved | not consumed |

**4 / 10 consumed. 6 experiments remain.**
