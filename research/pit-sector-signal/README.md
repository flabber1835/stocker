# PIT sector-signal research

Research-only retention for issue #241. Nothing in this directory is production strategy authority.

## Branch / code provenance

- Research branch: `research/pit-sector-signal-2026-08-23`
- Branch point: `cafd4871735e02f49e361c788d860ace34176c15`
- Current Simplified Concordance LD-RC controller remains version 3.
- The current corrected-volume native Sentinel parent uses a **30 percentage-point** five-session damaged-breadth acceleration threshold. The old 40pp recovered Sentinel 1.1 threshold is retained only as a sensitivity.

### Important correction retained for future contexts

The previously discussed `~19.98% current Sharadar sector vs ~17.99% SEC FF12` 20-year comparison was produced by the **40pp sensitivity**. It demonstrates that taxonomy can be economically load-bearing, but it is not the authoritative current 30pp parent result. Primary follow-up research in issue #241 must use 30pp.

## Causal data boundary

The causal sector reconstruction uses SEC Financial Statement Data Set `SUB` filings from 2009Q2 through 2026Q1, now complete after adding 2011Q2. SIC becomes usable only after its filing date; no future backfill is permitted. SIC is mapped deterministically to a frozen FF12 grouping.

2011Q2 added 1,695 unique dated SIC observations and changed the reconstructed sector labels for held DTGF/APKT on 16 sessions, but caused 0 fast-trigger changes, 0 native-allocation changes, 0 LD-RC changes and 0 NAV change.

Issuer identity uses dated SEC CIK evidence plus permanent security identity. Price/action semantics follow the corrected Sharadar domain treatment. Current Sharadar sector is used only as a non-PIT comparison control.

## Why sector matters

Sentinel does not consume a sector name as alpha. For each held name it computes GREEN/RED from that security's own state. Sector stress is the RED fraction inside a peer group. A sector with >=50% RED can escalate a non-GREEN name to AMBER. Damaged breadth is then the AMBER fraction of the current book, and the fast native parent reads the five-session acceleration in damaged breadth.

Therefore the useful latent variable is not `sector`. It is **peer contagion**: which holdings are economically related strongly enough that distress in some members is evidence of imminent/systemic distress in the others.

## First market-derived experiment already retained

The first experiment held the Wealth Core shadow and controller inputs fixed and recomputed only damaged breadth from alternative peer definitions. It evaluated both 30pp (authoritative current parent) and 40pp (historical sensitivity):

- current Sharadar sector (non-PIT control)
- SEC SIC -> FF12 (causal static taxonomy)
- sector-neutral negative control
- daily correlation hard clusters with 6/8/10 groups using prior 126 sessions
- monthly-stable 8-cluster correlation groups
- nearest-3 correlation peer stress
- SIC-derived Sharadar-like mapping sensitivity

Primary 30pp 20-year results from that first pass:

| variant | CAGR | Sharpe | max DD | ending multiple |
|---|---:|---:|---:|---:|
| nearest3_daily | 18.6524% | 1.0671 | -25.00% | 30.589x |
| SEC FF12 | 18.4795% | 1.0439 | -25.21% | 29.709x |
| corr10_daily | 18.4795% | 1.0439 | -25.21% | 29.709x |
| current Sharadar sector | 18.4317% | 1.0421 | -25.21% | 29.471x |
| corr6/corr8/corr8-monthly | 18.4317% | 1.0421 | -25.21% | 29.471x |
| sector-neutral | 17.5501% | 0.9944 | -28.64% | 25.380x |

This is an exploratory result, not a promotion result. Nearest-3 improved the full-period result only modestly over causal FF12 and has not yet passed an out-of-sample/walk-forward test.

The 40pp sensitivity is retained because it reveals nonlinear taxonomy dependence. Current Sharadar sector was ~19.9794% CAGR, causal FF12 ~17.9905%, and correlation/monthly/nearest-neighbor variants landed between them. This must not be confused with the current 30pp strategy.

## Working definition of an ideal sector signal

An ideal sector/peer signal should estimate, using only information available at close t:

> `P(holding j becomes damaged / participates in the same stress episode | peers i are already RED)`

It should add cross-sectional contagion information beyond the common market move. This suggests that plain raw-return correlation is only a baseline because high-beta securities can correlate simply because SPY moved.

The next research ladder should therefore test:

1. market-residual correlation peers (remove rolling SPY beta first);
2. downside/tail correlation peers (focus similarity on negative-return states);
3. nearest-neighbor peer stress with continuous correlation weights rather than hard sectors;
4. hybrid SEC-SIC + dynamic correlation priors;
5. a non-deployable hindsight oracle at the fast-trigger level to measure headroom and classify false-positive/false-negative stress episodes;
6. discovery/validation or walk-forward selection so the peer definition is not optimized on the same full 20-year tape used to score it.

## Decision standard

A candidate is not interesting merely because its full-period CAGR is higher. It should be strictly PIT, economically coherent, stable across nearby lookbacks/peer counts, improve or preserve Sharpe and drawdown, survive out-of-sample evaluation, and not depend on one isolated threshold crossing.

## Files / regeneration

`FILES_MANIFEST.tsv` records SHA-256 and byte size for every local input/output that existed at the checkpoint. Large transient source matrices are intentionally represented by hash + deterministic script provenance rather than silently omitted. `sector_market_experiment.py` is the exact first-pass peer experiment script. `results-summary.csv` and `results-summary.json` retain the complete scored first-pass table.
