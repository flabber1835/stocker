# Synthetic Market Lab v1 — Architecture

Status: Phase-1 design locked before implementation.

## Purpose and isolation

This namespace builds causal artificial equity-market histories for adversarial research. It is independent of Caesar 20, Median-5, Champion, Wealth Core, Sentinel, certified historical PIT datasets, production runtime, and historical backtest evidence.

The generator is strategy-blind. No strategy outputs, returns, holdings, ranks, selections, or parameters are inputs to world generation or calibration.

All code, configuration, tests, generated manifests, and documentation live under `research/synthetic_market_lab/`. The existing historical data path is unchanged. Integration is through a synthetic adapter that exports the conceptual `bt_prices`, `bt_fundamentals`, `bt_universe`, and corporate-action contracts described in `docs/backtester-v2-plan.md`.

## Information membrane

The world has five strictly ordered information domains:

1. `ground_truth/macro`: latent macro/regime state and shock identities.
2. `ground_truth/companies`: latent company health, fair-value state, true fundamentals, factor exposures, and distress probabilities.
3. `public/disclosures`: dated public filings, action announcements, security-master events, and reported values.
4. `public/market`: prices, liquidity, volume, spreads, and PIT universe state generated causally from current/past state.
5. `adapter`: strategy-facing PIT records derived only from the public namespace.

The adapter is constructed from the public directory only. It has no ground-truth path or API. Ground-truth columns never appear in strategy-facing schemas.

## Deterministic execution model

World generation is a forward-only simulation over deterministic business sessions. Every subsystem receives an independent named RNG stream derived by SHA-256 from `(generator_version, world_seed, stream_name)`. Adding random draws to one subsystem therefore cannot shift another subsystem's stream.

Phase 1 uses NumPy `PCG64DXSM` and pins the NumPy version in the lab's isolated requirements. Canonical JSON uses sorted keys and fixed separators. CSV artifacts use stable column order, stable row order, LF newlines, UTF-8, and gzip `mtime=0`. The manifest hashes compressed bytes with SHA-256.

Byte-for-byte replay is guaranteed for the same generator version, pinned dependency versions, configuration, seed, and Python major/minor environment recorded in the manifest.

## Layer 1 — macro/regime engine

The macro engine combines a persistent Markov regime with continuous autoregressive state and overlapping shock processes.

Persistent base regimes include expansion, recession, recovery, inflationary stagnation, disinflation, deflation, tight money, easy money, calm/low-volatility, and high-volatility/sideways states. They are structural labels, not mappings to historical calendar episodes.

Continuous state includes growth, inflation, policy rate, yield-curve slope, credit spread, liquidity, commodity impulse, volatility, productivity, and risk appetite. Rare shock processes include credit stress, energy/commodity shock, supply interruption, geopolitical shock, liquidity seizure, productivity boom, and speculative-bubble pressure. Shocks have persistence, decay, and may overlap.

The macro transition and shock parameters are configuration inputs. Future macro state is never pre-exposed to public data.

## Layer 2 — industries and factors

Synthetic sectors have heterogeneous exposure vectors to macro variables and factor premia. Company latent exposures include market beta, size, value, growth, profitability, quality, leverage, momentum, cyclicality, duration/rate sensitivity, credit sensitivity, commodity sensitivity, inflation sensitivity, volatility, and liquidity.

Factor premia are state variables with mean reversion, regime-dependent sign and magnitude, crowding pressure, and shock sensitivity. No factor has a permanently positive premium. Correlation rises under configured liquidity/volatility stress.

World-family presets alter structural parameters only. They are never conditioned on strategy behavior.

## Layer 3 — companies and lifecycle

A world contains persistent company identities with security identities layered on top. Company state evolves causally from prior company state, contemporaneous macro/sector state, and current shocks.

Lifecycle events include IPO, seasoned listing, growth, maturity, deterioration, turnaround, distress, bankruptcy, delisting, acquisition, ticker change, identifier change, split/reverse split, dividend, issuance, and buyback. Phase 1 implements IPOs, bankruptcies/delistings, dividends, splits/reverse splits, ticker/identifier changes, issuance/buybacks, and acquisitions. Merger/spin-off data structures are reserved for later expansion.

Dead companies and dead securities remain immutable historical records.

## Layer 4 — fundamentals and disclosures

Quarterly true fundamentals are generated in ground truth. Accounting identities are enforced at generation time, including `assets = liabilities + equity` within configured numeric tolerance.

Public reports are separate versioned disclosure events with `period_end`, `filed_at`, `version`, and reported values. Filing delay, missing filings, reporting noise, and later restatements are independently parameterized. A PIT query at time `T` selects only rows with `filed_at <= T` and returns the latest visible version for each period.

A later restatement never rewrites the earlier public row.

## Layer 5 — price formation

Each daily economic return is generated from contemporaneous market state, sector state, time-varying factor premia, company exposures, current/past fundamental innovations, momentum/mean-reversion state, idiosyncratic Student-t shocks, liquidity stress, and corporate-event effects.

Conditional volatility follows a simple persistent shock/decay process to create clustering. Regime stress changes common-factor correlation. Overnight and intraday components are generated separately to create gaps and daily OHLC ranges.

Prices are generated forward only. No future state or future random draw is an input to a current price.

## Layer 6 — liquidity/execution environment

Volume, dollar volume, and spread are generated from company size, baseline liquidity, current volatility, macro liquidity, and temporary liquidity shocks. Phase 1 records sufficient fields for future impact, participation-limit, slippage, and order-book models without implementing those execution models.

## Layer 7 — corporate actions

Corporate actions are immutable events with announcement and effective dates. Mechanical price/share effects occur on the effective date. Public visibility is controlled by announcement time.

The public price table carries a causal forward-adjusted `adj_close`: the adjustment scale changes only when an action occurs and never rewrites prior rows. A split changes raw price and shares while preserving economic market value. Dividend events reduce company cash and create a consistent ex-dividend price effect.

## Layer 8 — synthetic PIT adapter

The adapter consumes only `world/public/` and exports:

- `bt_prices`: ticker, date, open, high, low, close, adj_close, volume plus optional synthetic diagnostics.
- `bt_fundamentals`: ticker, datekey (= public filing time), period_end, version, and reported fundamentals.
- `bt_universe`: snapshot_date, ticker, security_id, company_id.
- `bt_actions`: announced_at, effective_date, security_id/ticker, action type, and action terms.

The historical Sharadar path is untouched.

## Storage layout

A generated world uses:

```text
world/
  manifest.json
  public/
    prices.csv.gz
    disclosures.csv.gz
    actions.csv.gz
    security_master.csv.gz
    universe.csv.gz
  ground_truth/
    macro_daily.csv.gz
    company_quarterly.csv.gz
    factor_daily.csv.gz
    shocks.csv.gz
    causal_dependencies.json
  validation.json
```

The reference world data itself is generated locally/CI from the committed configuration. The repository stores its canonical manifest, expected hashes/statistics, and reproduction command; it does not require committing the million-row generated tables.

## Validation gate

No strategy evaluation is permitted until generator validation passes. The validation suite proves deterministic replay, PIT disclosure semantics, revision isolation, IPO/delist chronology, dead-company retention, no survivorship filtering, split/dividend reconciliation, identity continuity, causal dependency lags, PIT universe membership, seed separation, and accounting closure.

## Scaling boundary

Phase 1 is single-process and optimized for inspectability. The world ID is the SHA-256 of generator version + canonical configuration + seed. Independent worlds can later be partitioned trivially by world ID and generated in parallel. Large-world storage can move to pinned Parquet/Arrow after deterministic encoding is certified; Phase 1 uses canonical gzip/CSV for simpler byte-level replay proofs.
