# Data Sources

## Initial Sources

### Alpha Vantage Premium

Used as the monthly research source.

Assumption:

```text
75 requests per minute
```

Use for:

```text
daily prices
adjusted prices
volume
fundamentals
company overview
financial statements
earnings
news sentiment
macro/economic data
listing status
```

Limitations:

```text
not official Russell 3000 membership
not perfect point-in-time fundamentals
not ideal for intraday monitoring
limited for analyst revisions
limited for detailed segment revenue or thematic exposure
```

### Alpaca API

Used for real-time monitoring and execution.

Use for:

```text
real-time or near-real-time market data
positions
orders
fills
account state
paper trading
live trading later
```

Only `trade-executor` should submit orders.

### Broker selection (Alpaca / IBKR)

Broker access is abstracted behind a shared `BrokerAdapter`
(`shared/stock_strategy_shared/broker/`). Exactly ONE broker is active per
deployment, chosen at deploy time by the `BROKER` env var (default `alpaca`).
Each machine runs one book against one broker with its own Postgres; there is no
runtime multi-broker routing. IBKR is the planned second broker
(`BROKER=ibkr` + an `IBKRBrokerAdapter` + a `--profile ibkr` session sidecar).
See `docs/service-boundaries.md` → "Broker abstraction" for the full design.

## Future Optional Sources

### Sharadar

Potential use:

```text
cleaner fundamentals
delisted coverage
better backtesting
historical factor research
```

### Financial Modeling Prep

Potential use:

```text
earnings transcripts
analyst estimates
price targets
news
thematic overlays
```

### Polygon/Massive

Potential use:

```text
stronger real-time data
minute bars
websocket feeds
flat files
intraday backtesting
```

## Universe Construction

### Design Decision: Alpha Vantage LISTING_STATUS as canonical universe source

The equity universe is built from the Alpha Vantage LISTING_STATUS API endpoint, not from ETF holdings CSV downloads.

API endpoint:

```text
https://www.alphavantage.co/query?function=LISTING_STATUS&apikey={api_key}
```

How it works:

```text
1. Fetch the full LISTING_STATUS CSV from Alpha Vantage
2. Filter to: status=active, assetType=Stock, exchange in US_EXCHANGES
3. Apply ticker regex validation (1–5 uppercase letters, optional suffix)
4. Store the resulting ticker list in Postgres as the active universe snapshot
5. Use that ticker list as the input to factor-engine
6. Refresh on a schedule (monthly before rebalance, or more frequently)
```

US exchanges included:

```text
NYSE, NASDAQ, NYSE MKT, NYSE ARCA, NYSE American, BATS, OTC
```

Why this approach:

```text
- Stable, API-native — no dependency on third-party file hosting or Cloudflare-blocked downloads
- Alpha Vantage is already a required dependency for prices and fundamentals
- Returns 3000+ active US equities, covering the broad investable universe
- No separate ETF holdings file to maintain or download
```

Limitations to keep in mind:

```text
- Not an official index — does not exactly match Russell 3000 or any benchmark
- May include tickers delisted with a slight lag; factor filters (min_price, min_avg_dollar_volume_20d) remove illiquid names
- Does not provide historical point-in-time membership for survivorship-bias-free backtesting
- For clean historical universe data, evaluate Sharadar in a future phase
```

## Current Design Choice

Start with:

```text
Alpha Vantage + Alpaca
AV LISTING_STATUS as the canonical equity universe source
```

Add new sources later only if specific weaknesses matter.
