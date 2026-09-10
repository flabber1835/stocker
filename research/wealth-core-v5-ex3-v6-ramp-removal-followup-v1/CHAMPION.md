# Current simplification and hardening champion

Decision date: **2026-09-10**. Status: **SELECTED — current simplification and hardening research champion**.

At the user's explicit direction, the selected version is **Wealth Core V5 + Sentinel EX3 V6 — compact simplified, complete Native recovery-ramp removal**, track `compact_simplified_no_ramp`.

This is the **56.27× champion**. It is the reference implementation for subsequent simplification and hardening research.

## Verified 20-year headline

Measurement: **2006-07-31 to 2026-07-31**, 5,032 measured sessions; warmup begins 2006-01-03. Ending wealth is a multiple of starting wealth.

| Selected track | CAGR | Maximum drawdown | Sharpe | Ending wealth |
|---|---:|---:|---:|---:|
| compact_simplified_no_ramp | 22.32% | −26.53% | 1.154 | 56.27× |

Unrounded ending multiple: `56.265349336558316`.

The non-compact `simplified_no_ramp` reference has identical measured outputs. The compact implementation is the selected champion. The earlier simplified candidate is `simplified` at 51.92×.

This decision supersedes the earlier **54.78× Native-ramp-removal hardening research designation** recorded at [commit 44be821](https://github.com/flabber1835/stocker/blob/44be8212c01dcdab4c913cb1b03ef28ef6c293da/research/wealth-core-v5-ex3-v6-state-component-ablation-v1/HARDENING_CHAMPION.md). That version retains SPY rebound release; the selected 56.27× version removes it. Earlier results and decision records remain historical evidence.

## Exact implementation and evidence

- [Complete selected strategy source](https://github.com/flabber1835/stocker/blob/f6ad7b543fbd20ffe363127d1120f4472caa9360/research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/sources/compact_simplified_no_ramp.py).
- Source SHA256: `3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663`; see [source manifest](https://github.com/flabber1835/stocker/blob/f6ad7b543fbd20ffe363127d1120f4472caa9360/research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/SOURCE_MANIFEST.json).
- Experiment launch commit: `f6ad7b543fbd20ffe363127d1120f4472caa9360`.
- Completed [Actions run 34528401951](https://github.com/flabber1835/stocker/actions/runs/34528401951): **7/7 Core cases complete**, comprising one baseline and six fresh perturbations, with all six controller tracks evaluated per case.
- Immutable result commit: `05727f2c65a235306fa55d61f254e06bed351776`.
- [Full headline report](https://github.com/flabber1835/stocker/blob/05727f2c65a235306fa55d61f254e06bed351776/research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/results/34528401951-1/SUMMARY.md), [machine-readable results](https://github.com/flabber1835/stocker/blob/05727f2c65a235306fa55d61f254e06bed351776/research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/results/34528401951-1/SUMMARY.json), and [per-case checks and replay evidence](https://github.com/flabber1835/stocker/tree/05727f2c65a235306fa55d61f254e06bed351776/research/wealth-core-v5-ex3-v6-ramp-removal-followup-v1/results/34528401951-1/cases).
- Campaign discussion: [issue #349](https://github.com/flabber1835/stocker/issues/349) and [research PR #350](https://github.com/flabber1835/stocker/pull/350).

The implementation combines complete Native recovery-ramp removal, removed SPY rebound release, bounded Native state, five EX3 decision fields with separate audit counters, strict versioned snapshots, and exact selective/symmetric peer caching with the zero-red shortcut and integer peer vote.

## Validation status retained with the designation

The user's champion selection is a research decision. The preregistered acceptance thresholds and their recorded outcomes remain unchanged.

| Check | Result | Evidence and meaning |
|---|---|---|
| Compact/reference and restart equivalence | **PASS** | Both compact tracks match their respective ramp-free references in targets, reasons, effective allocations and NAV in all seven cases. Checkpoint restarts match exactly. Peer checks have zero mismatches across 5,176 observations per case. |
| Economic preservation against original and previous simplified | **FAIL / FAIL** | Across all 5/10/15/20-year windows, the screen requires absolute CAGR change ≤0.25pp, drawdown deterioration ≤1pp and absolute ending-wealth change ≤5%. The selected version's 20-year CAGR improves by 0.766pp versus original and 0.490pp versus previous simplified; wealth improves by 13.39% and 8.37%, exceeding the symmetric preservation limits. |
| Formal robustness screen | **FAIL** | Median individual fault allocation-area reduction is 24.72% versus original and 14.26% versus previous simplified. The required reduction is at least 50%, together with baseline CAGR loss ≤1pp. The area-reduction threshold is missed. |

Compact cleanup preserves the ramp-free reference outputs exactly. Ramp removal and SPY rebound removal change strategy behavior and economics.

Perturbation evidence is mixed: all six allocation-area comparisons improve versus original, and terminal allocation reconverges in five of six cases. Maximum drawdown is worse than original in five of six perturbations. The selected version's worst case, `drop_47`, produces **16.68% CAGR, −34.55% maximum drawdown and 21.88× ending wealth**, with a 5.641pp CAGR decline from its own baseline. These tests use the same historical dataset; independent temporal out-of-sample and production robustness remain unproven.

## Scope and authority

Wealth Core continues to decide **what to hold** through its immutable independent shadow book. Sentinel continues to decide **how much exposure to take**. Native severe-state zero exposure, the EX3 divergence latch, recovery persistence and cross-surface release remain in place. Broker-facing authority remains exclusively in execution.

This record selects the research champion. Production certification, deployment and merge authority remain unchanged and require separate review and authorization. This documentation update starts no backtests, consumes no additional experiment slots and changes no strategy source or existing result evidence.
