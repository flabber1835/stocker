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

## Current Design Choice

Start with:

```text
Alpha Vantage + Alpaca
```

Add new sources later only if specific weaknesses matter.
