# A / D / E fully-PIT experiment specification

**Branch:** `research/backtester`  
**Purpose:** define the forward control / fully-PIT / fully-PIT-dynamic-peer experiment family.  
**Production `main`:** read-only. This document does not authorize any production change.

## Naming

The forward experiment nomenclature is:

| Variant | Definition |
| --- | --- |
| **A** | Exact current strategy from the declared `main` SHA, with the same input semantics currently used by `main`. This is the production-semantics control and may contain known non-PIT metadata. |
| **D** | The same strategy economics and mechanics as A, with every economically relevant non-PIT input dependency either eliminated or replaced by a causally valid PIT source. Sentinel contagion grouping uses causal **SEC SIC -> FF12**. |
| **E** | **D plus causal dynamic peers**: fully-PIT D with the FF12 grouping used by Sentinel contagion replaced by dynamically calculated causal peer relationships derived only from historical market information available strictly before the decision session. |

The previously used B/C labels are not the forward names for these variants. Historical artifacts keep their original labels and are not renamed retroactively.

## Experimental objective

Measure the economic effect of removing hindsight metadata from the current strategy while preserving strategy mechanics.

The intended comparisons are:

1. **A -> D:** economic effect of making all economically relevant strategy inputs genuinely causal/PIT.
2. **D -> E:** economic effect of replacing causal structural FF12 grouping with causal dynamic price-derived peers after the rest of the strategy is already fully PIT.

A, D, and E must run for the same historical session before advancing to the next session. Shared mechanics, market data, execution timing, accounting, Wealth Core rules, Sentinel thresholds, and LD-RC rules remain identical unless this specification explicitly declares a substitution.

## Variant A — current-main control

A executes the exact strategy semantics from the run's declared `main` SHA using the same effective input semantics as production `main`.

A is the control. A must not be described as fully PIT when current-snapshot metadata is economically relevant to its historical path.

A exists to answer whether the research replay reproduces current-main economics faithfully. If A control parity is materially wrong, headline D/E results are invalid until the discrepancy is resolved.

## Variant D — fully PIT by elimination and substitution

D is allowed to be called **fully PIT** only when every economically relevant input read during a historical decision is either:

- an observation that was available as of that simulated session;
- a frozen PIT reconstruction with an explicit causal/as-of rule; or
- a deterministic transformation of such causal inputs.

No present-day Sharadar metadata snapshot may influence D's historical economic path.

### Required substitutions / eliminations

| Domain | D treatment |
| --- | --- |
| Historical prices / volume | Historical causal market observations only. |
| Corporate actions | Frozen PIT corporate-action reconstruction with causal effective-date handling. |
| Permanent security / ticker identity | Causal historical security/ticker identity. A present-day ticker must not be used as a historical shortcut. |
| Issuer / issuer-family identity | Existing frozen PIT SEC issuer/CIK lineage. Current Sharadar `relatedtickers` or equivalent present-day issuer-family metadata must not affect the historical path. |
| Sector / peer grouping | Latest SEC SIC causally available before the decision session, mapped through the frozen FF12 definition. Missing PIT SIC must fail closed or use an explicitly non-contagious singleton-unknown treatment that cannot manufacture cross-security stress. |
| Exchange | Eliminate the dependency where it is not economically required. If any rule still requires exchange, provide a causal source before D may be called fully PIT. |
| First / last price dates | Derive causally from observations seen up to the simulated session; do not read replay-end listing dates. |
| Category / security type | Eliminate the dependency where possible. Where eligibility genuinely requires security type, use the frozen causal SEC/EDGAR security-type evidence. Missing evidence must follow an explicit fail-closed rule. |
| Benchmarks / defensive asset | Frozen causal SPY/BIL history and factors. |

### D acceptance gate

Before reporting D as fully PIT, the run evidence must prove that no economically relevant code path read present-day Sharadar metadata or any other future-known value.

A simple label or certification flag is insufficient. The evidence must identify each input domain, its source, its information cutoff, and its hash/manifest identity.

If one economically relevant input cannot satisfy that test, D must be reported as **not fully PIT** and its headline CAGR/Sharpe/DD must not be presented as the fully-PIT result.

## Variant E — fully PIT with causal dynamic peers

E inherits **all D requirements**. The only intended D/E difference is Sentinel's peer/group contagion input.

Instead of SEC SIC -> FF12, E uses dynamically calculated causal peers from historical market data.

Initial frozen peer definition:

- lookback: 252 market sessions;
- minimum common observations: 120;
- market adjustment: residual return after SPY-beta adjustment;
- similarity: Pearson correlation of residual returns;
- maximum peers: 3;
- correlation floor: 0.145;
- information cutoff: sessions strictly before the current decision session; the current-session return is excluded.

The dynamic-peer parameters are experiment inputs, not strategy-tuning variables during a replay. Any later parameter change defines a new experiment configuration and must be recorded explicitly.

### Dynamic-peer cache policy

E may consume a precomputed/hash-pinned market-derived peer cache created by a separate dataset-maintenance workflow, provided the cache contains only causal market-derived features and obeys the strict-prior information cutoff.

Allowed cached material includes prior-only returns, SPY-beta residual returns, rolling correlations, ranked peer relationships, and peer/cluster identifiers derived solely from those inputs.

The cache must never contain or encode strategy-dependent decisions or path state, including holdings, damaged breadth, Sentinel targets, LD-RC allocations, trades, pending orders, crisis schedules, or NAV.

## Mechanics that remain frozen across A / D / E

Unless a future experiment explicitly declares otherwise, all variants use the same:

- Wealth Core selection, sizing, admissions, exits, stops, cooldowns, and slot mechanics;
- corporate-action economic treatment;
- order timing and next-open execution semantics;
- cash, settlement, dividends, and accounting;
- native Sentinel thresholds and controller mechanics;
- recent-leadership witness;
- LD-RC state machine;
- defensive-asset accounting;
- transaction-cost assumptions;
- starting capital;
- historical session axis and measurement windows.

## Replay and provenance requirements

All A/D/E results remain subject to `docs/backtester-experiment-contract.md`.

In particular:

- `main` is read-only and pinned by exact SHA;
- all PIT datasets must exist and be hash-pinned before economic replay begins;
- PIT reconstruction/repair is not performed inside the backtest;
- no prerecorded decisions, holdings, trades, allocations, NAV, or oracle path may drive the replay;
- the replay starts from fresh state and advances chronologically one session at a time;
- A/D/E are evaluated on the same session before advancing;
- result artifacts include daily evidence, metrics, code/data hashes, and explicit PIT-domain provenance.

## Reporting

For each of 5-, 10-, 15-, and 20-year windows, report at minimum:

- CAGR;
- maximum drawdown;
- Sharpe ratio;
- SPY comparison;
- exact dates and session counts.

The result summary must separately state:

- A control-parity status;
- D fully-PIT acceptance status;
- E fully-PIT acceptance status;
- the exact D/E grouping difference;
- any missing or fail-closed metadata events that occurred.

## Current run compatibility

Any A/B run already in flight when this specification is committed remains an A/B historical experiment and is not reinterpreted as D. Its B arm tests only the previously declared sector substitution.

A future D run must implement and prove the complete elimination/substitution set above before its result is labeled fully PIT.
