# Simplified Concordance LD-RC re-optimization after Sharadar correctness fixes and SEC PIT replay

Date: 2026-08-22

## Purpose

Re-optimize only the small Simplified Concordance LD-RC overlay after the historical data semantics were corrected, while keeping the corrected Wealth Core / Sharadar economics fixed. The aim is to see whether a small, defensible threshold retune can recover CAGR lost as data correctness improved, without fitting to the extraordinary 2026 SNDK episode.

This study incorporates:

- corrected SEP dollar-volume semantics;
- corrected dividend basis and same-session split/dividend ordering;
- PR #230 stock-split / ADR-ratio / effective-date / terminal-event semantics;
- SEC-filing point-in-time reconstruction for issuer / related-security identity using the PR #208 causal resolver;
- the current Simplified Concordance LD-RC state machine.

The primary optimization window ends on **2025-12-31**, deliberately excluding the exceptional 2026 SNDK run from model selection.

## Code and evidence boundary

Research branch base: `7d0948ee6c75d3cd95c437818c010f396dfdc04b` (main after #231).

The corporate-action semantics under test were merged in PR #230 (`81a1aa4c21cf7e46975cb5e84be8499f31d136db`; PR head `28faaf8749236d5f00f61186b24807360bac2b78`).

The SEC PIT issuer resolver is the same causal method established in PR #208: only filings available by the replay session are allowed to define historical related-security / issuer identity. Pre-coverage warm-up is held identical rather than backfilled with future filings.

## SEC PIT result

Applying the SEC-filing PIT issuer reconstruction to the fully corrected post-#230 replay caused **zero economic change** over the tested history.

Verified locally:

- post-#230 corrected daily tape SHA-256: `c96ea62ea5b2490b3278107600ff7068b5917d5e24db0a6da3eb16d401bd1f47`;
- SEC-PIT daily tape SHA-256: `c96ea62ea5b2490b3278107600ff7068b5917d5e24db0a6da3eb16d401bd1f47`;
- daily files: byte-identical;
- executed buys: byte-identical;
- ending holdings: byte-identical;
- held split decisions: byte-identical.

Therefore the SEC PIT correction does not alter the strategy path on this corpus. It nevertheless remains important as a causality proof: the zero delta is measured, not assumed.

## Correct baseline

The relevant baseline for optimization is the **post-split-fix, post-volume-fix, post-dividend-fix, SEC-PIT replay through 2025-12-31**, not the 2026 headline that contains SNDK.

| Variant | CAGR | Max drawdown | Sharpe | Ending multiple |
|---|---:|---:|---:|---:|
| Current LD-RC (`spy_v_rebound=0.11`) | 21.2638% | -21.8724% | 1.2041 | 42.27x |
| Recommended (`spy_v_rebound=0.10`) | **21.7898%** | **-21.8724%** | **1.2244** | **45.98x** |
| Aggressive grid winner (not recommended) | 22.0311% | -20.9582% | 1.2173 | 47.78x |

The conservative one-parameter retune therefore recovers about **+0.526 percentage point / +52.6 bps of annual CAGR** with no observed worsening in maximum drawdown and with higher Sharpe.

## Recommended change

Change only:

```text
spy_v_rebound: 0.11 -> 0.10
```

Leave the other Simplified LD-RC thresholds unchanged.

### Why 0.10 rather than the numerical grid maximum

The historical allocation path is flat across a neighborhood around 0.10 (approximately 0.0925-0.1025 in the one-at-a-time sweep). `0.10` is therefore a simple central point on a behavioral plateau, not a precision-selected decimal.

The gain comes from allowing a sufficiently strong SPY rebound to clear the recovery latch somewhat earlier in a small number of historical recovery episodes. Only a tiny fraction of all sessions change exposure. The largest historical benefit is from an older recovery episode rather than from the 2026 SNDK period.

## Rolling-window robustness

| Window ending 2025-12-31 | Current CAGR | Recommended 0.10 | CAGR gain | Current MDD | Recommended MDD |
|---|---:|---:|---:|---:|---:|
| 5 years | 19.7630% | 19.8755% | +0.1124 pp | -21.8724% | -21.8724% |
| 10 years | 23.8659% | 23.9240% | +0.0581 pp | -21.8724% | -21.8724% |
| 15 years | 21.3029% | 21.3082% | +0.0053 pp | -21.8724% | -21.8724% |
| Full 2006-07-31 -> 2025-12-31 | 21.2638% | **21.7898%** | **+0.5260 pp** | -21.8724% | -21.8724% |

Interpretation: the full-history improvement is real in the replay but is concentrated in older recovery episodes. Recent-window uplift is modest. This is why the recommendation is limited to the one parameter and why further return maximization is rejected.

## What was swept

One-at-a-time sensitivity was run around all six Simplified LD-RC parameters:

- divergence ceiling;
- Wealth Core drawdown trigger;
- recent-leadership 20-session trigger;
- SPY 20-session floor for divergence entry;
- recovery persistence sessions;
- SPY V-rebound threshold.

A 6,750-configuration interaction grid was also evaluated around plausible neighborhoods. Compact summaries of the one-at-a-time sweep, rolling-window table, and top distinct grid outcomes are committed beside this note.

The current fast damaged-breadth delta threshold from the earlier volume-fix retune was also revisited separately. The current `0.30` remains on a broad stable plateau; moving it back toward `0.40` materially degrades CAGR and drawdown. No reversal is recommended.

## Aggressive result rejected

The interaction grid contains configurations around roughly:

```text
spy_v_rebound ~= 0.09
recovery_sessions = 6
spy_r20_floor ~= 0.07-0.09
```

that reach approximately **22.03% CAGR / -20.96% max drawdown** through 2025.

Do **not** promote this configuration from this evidence. The additional gain depends on very few historical LD-divergence / recovery episodes, and multiple parameter combinations collapse to the same few historical decisions. That is insufficient event count for a structural retune and has a high curve-fitting risk.

## Recommendation

1. Treat **21.2638%** as the corrected current pre-SNDK historical baseline for this optimization study.
2. SEC-filing PIT issuer reconstruction causes **zero strategy/economic delta** on this corpus, so it does not change the optimization conclusion.
3. If a small retune is desired, promote only **`spy_v_rebound: 0.11 -> 0.10`** to a challenger/certification pass.
4. Do not change the other Simplified LD-RC thresholds based on this sweep.
5. Do not adopt the ~22.03% multi-parameter grid winner without materially more independent episodes / out-of-sample evidence.
6. Preserve the remaining historical metadata caveat: SEC filings causally reconstruct issuer relationships, but they do not independently reconstruct every historical Sharadar security `category/type` value. That separate PIT question remains unless certified elsewhere.

## Evidence files

- `ldrc-sec-pit-reoptimization-windows.csv` — current vs recommended vs aggressive across trailing windows.
- `ldrc-sec-pit-oat-summary.csv` — best observed one-at-a-time result for each LD-RC parameter.
- `ldrc-sec-pit-grid-top30.csv` — top distinct economic outcomes from the 6,750-case interaction grid.

The study is research evidence only. It does **not** change production strategy parameters by itself.
