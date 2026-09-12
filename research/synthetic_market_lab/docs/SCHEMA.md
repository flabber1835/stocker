# Synthetic Market Lab v1 — World Schema

## Identifiers

- `world_id`: SHA-256 over generator version + canonical config + seed.
- `company_id`: immutable economic-entity identifier, e.g. `C000123`.
- `security_id`: immutable listed-security identifier, e.g. `S000123-01`.
- `ticker`: public symbol valid only within a dated identity interval.

Ticker and security identifiers may change while `company_id` remains constant.

## Ground-truth tables

### `ground_truth/macro_daily.csv.gz`

`date, session, regime, growth, inflation, policy_rate, yield_slope, credit_spread, liquidity, commodity_impulse, volatility, productivity, risk_appetite, shock_credit, shock_energy, shock_supply, shock_geopolitical, shock_liquidity, shock_productivity, shock_bubble`

Strategy access: forbidden.

### `ground_truth/factor_daily.csv.gz`

`date, session, market, size, value, growth, profitability, quality, leverage, momentum, duration, credit, commodity, inflation, volatility, liquidity`

These are true realized/premium states used by price formation. Strategy access: forbidden.

### `ground_truth/company_quarterly.csv.gz`

`company_id, period_end, session, age_days, health, distress_probability, true_revenue, true_expenses, true_net_income, true_assets, true_liabilities, true_equity, true_cash, true_debt, true_shares, true_growth, true_margin, true_quality, latent_value`

Accounting invariant: `true_assets = true_liabilities + true_equity` within numeric tolerance.

### `ground_truth/shocks.csv.gz`

`date, session, shock_id, shock_type, intensity, source, affected_scope`

Strategy access: forbidden.

### `ground_truth/causal_dependencies.json`

Machine-readable dependency graph. Every current observable lists only contemporaneous or lagged parents. Positive/future lags are invalid.

## Public tables

### `public/security_master.csv.gz`

`company_id, security_id, ticker, valid_from, valid_to, listing_date, delist_date, delist_reason, sector, industry`

One company may have multiple identity intervals. Historical intervals remain present forever.

### `public/prices.csv.gz`

`date, session, company_id, security_id, ticker, open, high, low, close, adj_close, volume, dollar_volume, spread_bps`

`close` is raw transaction-price space. `adj_close` is a causal forward-adjusted economic-price series whose scale changes only when an action becomes effective; prior rows are never rewritten by future actions.

### `public/disclosures.csv.gz`

`company_id, security_id, ticker, period_end, filed_at, version, report_type, revenue, expenses, net_income, assets, liabilities, equity, cash, debt, shares_outstanding, revenue_growth, margin, leverage, quality, is_restatement`

PIT rule: a query at `T` may use only rows where `filed_at <= T`. For each `(company_id, period_end)`, it may select only the latest version among those visible rows.

### `public/actions.csv.gz`

`company_id, security_id, ticker, announced_at, effective_date, action_type, ratio, cash_amount, new_ticker, new_security_id, reason`

Minimum Phase-1 action types: `ipo`, `dividend`, `split`, `reverse_split`, `ticker_change`, `identifier_change`, `issuance`, `buyback`, `bankruptcy`, `delisting`, `acquisition`.

PIT rule: strategy visibility is controlled by `announced_at`; economic effects occur at `effective_date`.

### `public/universe.csv.gz`

`snapshot_date, session, company_id, security_id, ticker, sector, industry`

A row exists only when the security is publicly listed and active on the snapshot date. Historical rows are immutable and retained after delisting.

## Backtester adapter exports

### `adapter/bt_prices.csv.gz`

Required conceptual columns:

`ticker, date, open, high, low, close, adj_close, volume`

Additional identity columns may be included after the required columns.

### `adapter/bt_fundamentals.csv.gz`

`ticker, datekey, period_end, version, revenue, expenses, net_income, assets, liabilities, equity, cash, debt, shares_outstanding, revenue_growth, margin, leverage, quality`

`datekey` is exactly the public `filed_at` timestamp/date. Restatements are new later rows.

### `adapter/bt_universe.csv.gz`

`snapshot_date, ticker, security_id, company_id, sector, industry`

### `adapter/bt_actions.csv.gz`

`announced_at, effective_date, ticker, security_id, company_id, action_type, ratio, cash_amount, new_ticker, new_security_id, reason`

## Manifest

`manifest.json` contains:

- `generator_version`
- `world_id`
- `seed`
- `config`
- `config_sha256`
- `python_version`
- `numpy_version`
- `pydantic_version`
- `rng_algorithm`
- `rng_streams`
- `sessions`
- `companies`
- `files` mapping relative path to SHA-256 and byte size
- summary statistics

## World configuration

The validated JSON configuration contains:

- calendar/session count and starting date
- company count and sector definitions
- macro transition matrix and state parameters
- shock arrival/persistence parameters
- factor parameters
- company lifecycle parameters
- disclosure delay/noise/restatement parameters
- price/volatility/liquidity parameters
- corporate-action parameters

Every parameter is strategy-independent.
