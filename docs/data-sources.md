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

### Design Decision: Russell 3000 proxy via ETF holdings

The equity universe is built by downloading the holdings of an ETF that tracks the Russell 3000 Index, not by subscribing to an official Russell membership list.

Preferred ETFs:

```text
IWV  = iShares Russell 3000 ETF  (BlackRock)
VTHR = Vanguard Russell 3000 ETF (Vanguard)
```

Both track the Russell 3000 Index. VTHR holds roughly 3,000 stocks representing approximately 98% of the investable U.S. equity market.

How it works:

```text
1. Download the ETF's current holdings file (CSV or JSON, published daily by the provider)
2. Extract the ticker list
3. Store tickers in Postgres as the active universe snapshot
4. Use that ticker list as the input to av-ingestor and factor-engine
5. Refresh the holdings on a schedule (monthly before rebalance, or more frequently)
```

Where to download holdings:

```text
IWV:  https://www.ishares.com/us/products/239714/ (Holdings tab, CSV export)
VTHR: https://investor.vanguard.com/etf/profile/portfolio/VTHR (Holdings export)
```

Why this approach:

```text
- No official Russell 3000 API exists for retail subscribers
- ETF providers publish daily holdings and are legally required to track the index closely
- IWV and VTHR holdings diverge from the true index by at most a few tickers
- This is the standard proxy used by quant researchers without institutional index access
```

Limitations to keep in mind:

```text
- Holdings reflect the ETF rebalance lag, not the live Russell index
- Small differences may exist between IWV and VTHR due to sampling or rebalance timing
- Delisted or suspended tickers may linger briefly before the ETF removes them
- Does not provide the historical point-in-time Russell membership needed for clean backtesting
```

For backtesting survivorship bias:

```text
The holdings snapshot gives today's universe, not the universe at a historical date.
This introduces survivorship bias in backtests. Accept this limitation for Phase 5.
If clean historical universe data becomes a priority, evaluate Sharadar or a similar
historical constituents dataset.
```

## Current Design Choice

Start with:

```text
Alpha Vantage + Alpaca
Russell 3000 proxy via IWV or VTHR ETF holdings
```

Add new sources later only if specific weaknesses matter.
