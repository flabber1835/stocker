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
fundamentals (OVERVIEW)
company overview
earnings (point-in-time)
listing status (universe)
balance sheet (total assets, shares outstanding — issuance factor)
```

NOT currently ingested from AV (doc/code reconciliation — av-ingestor audit):
```text
news sentiment        — sourced via Tavily in llm-vetter instead, not AV NEWS_SENTIMENT
macro/economic data   — unbuilt (no REAL_GDP/CPI/etc. calls)
financial statements  — only BALANCE_SHEET; income statement & cash flow unbuilt
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

## Forward-Looking (Leading) Signals

The core factor stack (momentum, quality, value, growth, low-vol, liquidity,
earnings-surprise) is built entirely from realized price and already-reported
fundamentals — i.e. TRAILING data. A forward-looking factor taps a different
information set (expectations / text), so it is low-correlation to the trailing
stack and anticipatory at fundamental inflections. The benefit is incremental
risk-adjusted return ≈ IC × (1 − correlation to existing factors): even a modest
leading signal can beat an eighth trailing factor because the trailing factors
co-move through the price/business cycle.

### Decision: snapshot AV OVERVIEW analyst fields (Phase 1, deterministic)

The first forward signal is built from data we ALREADY pay for. Alpha Vantage's
`OVERVIEW` payload — already fetched per ticker for fundamentals — carries analyst
fields the ingestor previously discarded:

```text
AnalystTargetPrice
AnalystRatingStrongBuy / Buy / Hold / Sell / StrongSell
ForwardPE
PEGRatio
```

These are captured at NO extra API call (same payload) into the `analyst_snapshots`
table (migration 0029), point-in-time keyed by `snapshot_date`. The eventual factor
is a REVISION: latest snapshot vs a prior snapshot (target-price change,
rating-upgrade breadth).

Critical point-in-time constraint: AV exposes only the CURRENT consensus, so there
is NO clean free historical backfill. We accumulate our own history by snapshotting
each fetch. Consequence — the revision factor must be evaluated FORWARD /
out-of-sample (paper), NOT backtested over dates before snapshots existed. Same
honesty constraint applies even more strongly to any LLM-generated leading factor
(a frozen-knowledge model scoring a historical date has look-ahead).

This migration lands ONLY the raw snapshot store + ingest. The derived factor
column + scoring weight are a separate change once enough history accumulates.

### Free forward-looking sources (evaluated; for later phases)

```text
SEC EDGAR        free, no key, ToS-clean; 8-K Item 2.02 + Ex-99.1 (guidance),
                 10-Q/10-K MD&A/Outlook — best feedstock for an LLM outlook score
Finnhub (free)   eps/revenue estimates, recommendation trends, price targets;
                 ~60 req/min covers the universe (some endpoints now paid — verify)
FMP (free)       transcripts + estimates, but ~250 req/day → scope to the vetter
                 candidate pool only, not the full universe
yfinance/Yahoo   free forward estimates/revisions but unofficial/ToS-gray/fragile
                 — research/prototyping only, do not productionize
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

### Design Decision: sector provenance — OVERVIEW trickle + snapshot carry-forward, latest-non-null reads

`universe_tickers.sector` has a two-source lifecycle, and every consumer must
respect it (this closed the W29 "sector cap inert" finding):

```text
1. LISTING_STATUS carries NO sector — every fresh universe snapshot inserts
   sector=NULL for all rows.
2. The AV OVERVIEW (fundamentals) fetch backfills sector per ticker as it
   trickles through the universe (investable names weekly, the rest on a
   ~30-day rotation). The UPDATE is unscoped by snapshot, so all snapshots
   converge on the latest label.
3. save_universe_snapshot CARRIES FORWARD the latest known non-null sector
   from prior snapshots into each new snapshot at creation, so a weekly
   refresh never resets coverage to zero.
4. READERS must never scope sector to "the newest snapshot" — they take the
   latest NON-NULL sector per ticker across snapshots
   (DISTINCT ON (ticker) ... ORDER BY ticker, (sector IS NULL), snapshot_id DESC).
   Universe MEMBERSHIP still comes from the newest snapshot; only the sector
   LABEL reads across snapshots. Applied in: portfolio-builder (max_sector_weight
   cap), pipeline (sector-neutralized factors), llm-vetter, api/dashboard,
   evaluator packet, backtester config-replay.
```

Residual nulls (~half the universe) are names whose OVERVIEW has not been
fetched yet or for which AV has no OVERVIEW data (micro-caps). They are
overwhelmingly outside the investable/ranked set — ranked candidates need
fundamentals, whose fetch is exactly what writes the sector — so a mass
OVERVIEW backfill of the tail is not warranted.

## Current Design Choice

Start with:

```text
Alpha Vantage + Alpaca
AV LISTING_STATUS as the canonical equity universe source
```

Add new sources later only if specific weaknesses matter.

---

## The Sharadar corpus is sound; three defects are in how we READ it (2026-08-08)

Found while diagnosing why a 2021-2023 Wealth Core chain rehearsal produced
frozen metrics from 2023-02 onward. The investigation started at a single
security and ended at three independent defects, none of which is a strategy
finding and all of which would have silently corrupted any baseline that run
produced.

**The corpus itself is in good shape** and that is the load-bearing conclusion:
`bt_actions` carries 664,039 rows across 18 action types spanning 1998-01-02 to
2026-08-07. Nothing below is fixed by re-downloading, and a bulk re-import
would faithfully reproduce every one of these defects on fresh data. **Fix the
reader before rebuilding the corpus** — otherwise the rebuilt corpus is
certified while carrying them invisibly.

### The security that exposed it

```text
BIOT   bt_prices   2021-01-26 .. 2023-02-02   (510 bars)
                   2026-07-24 .. 2026-08-05   (9 bars)
       bt_actions  2026-07-24 listed          (the ONLY row)
```

Two companies, one symbol, a 3.4-year hole between them. `bt_universe`'s own
snapshot history records both:

```text
2026-07-25  BIOTECH ACQUISITION CO         2021-01-26..2023-02-02  is_delisted=t
2026-07-29  INSTINCT BIO TECHNICAL CO INC  2026-07-24..            is_delisted=f
2026-08-03  INSTINCT BIO TECHNICAL CO INC  category ADR Common Stock, permaticker 6400922
```

The vendor told us the SPAC delisted. Only the LAST snapshot carries a
`permaticker`, and it is the 2026 company's.

### Defect A — `bt_universe` is keyed on TICKER, so identity is destroyed on insert

```sql
PRIMARY KEY (snapshot_date, ticker)
ON CONFLICT (snapshot_date, ticker) DO UPDATE SET ... permaticker=EXCLUDED.permaticker
```

Sharadar TICKERS returns a separate row per permanent security, and a reused
symbol means two companies with the same `ticker` in one snapshot. They collide
on the key and the last row processed wins — **which company survives depends on
API row order.** `permaticker` was added as a COLUMN without changing the KEY,
so the table cannot represent the thing the column exists to express.

`_upsert_universe()` returns `len(rows)` — rows ATTEMPTED, not rows persisted.
That is why 49,834 attempted against 21,733 stored read as unremarkable for
months: a ~56% loss to key collisions, reported by a number that looks like an
answer. **A writer that cannot report what it stored cannot be audited**, and
this is the second instance of that shape in the codebase.

### Defect B — spliced price history (a consequence of A)

`_META_SQL` and `_IDENTITY_SQL` both filter `WHERE permaticker IS NOT NULL`. The
SPAC's surviving row has none, so it never reaches the resolver, which then sees
exactly ONE owner for the symbol — and `IdentityResolver.resolve` documents that
case explicitly:

```python
if len({x.security_id for x in listings}) == 1:
    # One owner ever. The window is NOT consulted
```

That skip is correct in general: a security's price history can legitimately
start before its snapshot's `first_price_date`, and refusing those bars would
discard real history to guard a rare case. But with one owner erased by A, the
rare case is invisible, so every 2021-2023 SPAC bar resolves to the 2026 ADR —
under the 2026 company's `category` and `permaticker`.

All three of the resolver's refusals (`unknown_ticker`, `ambiguous`,
`out_of_window`) are bypassed, and `reused_tickers` does not list the symbol.
**The disambiguation logic is sound and never fires, because A removed its
input.** A run spanning 2023 to 2026 would read straight across the hole as one
continuous position and book a fabricated multi-year return.

### Defect D — the engine's corporate-action vocabulary does not match the vendor's

SIX of the seven names in `TERMINAL_ACTIONS` do not exist in the corpus.
Comparison is exact set membership (`action not in TERMINAL_ACTIONS`), no prefix
matching, so every non-matching name is silently dropped:

```text
code expects              corpus has                  rows    matched
delisted                  delisted                  19,216    yes
acquisition               acquisitionby              7,512    NO
bankruptcy, liquidation   bankruptcyliquidation      3,348    NO
regulatory                regulatorydelisting          883    NO
(absent from the code)    voluntarydelisting           376    NO
merger                    mergerto                     134    NO
reversemerger             -                              0    -
```

**12,253 genuinely terminal events the engine never sees**, against 19,216 it
does. Same defect elsewhere: `adrratiosplit` (386) is not in `SPLIT_ACTIONS`, so
those ADR share-ratio changes never adjust the split factor; `spinoffdividend`
(497) is not in `DIVIDEND_ACTIONS`; `specialdividend` IS in the code and matches
zero rows; and `tickerchangeto` / `tickerchangefrom` (13,437 each) are entirely
unconsumed — 26,874 rows of the vendor stating that a symbol moved, which is
directly relevant to A and B.

**THE ACQUIRER-SIDE TRAP. Do not fix this with a substring match.**
`acquisitionof` (7,193) and `mergerfrom` (116) are the ACQUIRER's side of a deal
and are NOT terminal for the security that carries them. Treating them as
terminal would write off the wrong company — the buyer rather than the target.
The fix is an explicit per-name mapping with a stated side for each name; any
scheme that pattern-matches on `acquisition` or `merger` is worse than the bug.

**D IS A PREREQUISITE FOR THE ORPHAN POLICY (C), NOT AN INDEPENDENT ITEM.** The
policy in docs/architecture.md "orphan resolution" branches on whether resolvable
terminal terms exist, and falls through to a zero write-off when they do not.
With `acquisitionby` and `mergerto` invisible, 7,646 real cash mergers fail that
test and write off at ZERO with their settlement terms sitting unread in the
corpus. That failure is far harder to notice than a block: a block halts the run,
a zero merely lowers the return. Ship D before or with C, never after.

### Open question, one query

Whether Sharadar emits `delisted` ALONGSIDE the reason decides D's severity.
If it does, termination is mostly DETECTED and D is a terms bug (mergers paying
nothing). If it does not, those names go unmarkable and BLOCK.

```sql
WITH t AS (SELECT DISTINCT ticker FROM bt_actions
            WHERE action IN ('acquisitionby','mergerto','bankruptcyliquidation',
                             'regulatorydelisting','voluntarydelisting'))
SELECT count(*) AS terminal_by_other_name,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM bt_actions d
         WHERE d.ticker = t.ticker AND d.action = 'delisted')) AS also_has_delisted
  FROM t;
```

### Remediation order (owner decision, 2026-08-08)

```text
1  A   re-key bt_universe on (snapshot_date, permaticker); ticker becomes an
       ATTRIBUTE and a lookup key, never permanent identity. _upsert_universe
       must report rows PERSISTED, with rows lacking a valid permaticker
       counted and named rather than dropped silently.
2  B   re-run the universe backfill, then QUANTIFY the splices — reused_tickers
       only becomes truthful once A is fixed, so the population is unknown today.
3  D   per-name action mapping with an explicit side per name. Prerequisite for 4.
4  C   the orphan-resolution accounting contract — docs/architecture.md.
5      tests for all four, THEN re-run the 2021-2023 rehearsal.
```

Acceptance test for A, required before anything downstream is believed:

```text
attempted TICKERS rows
  == rows keyed by distinct (snapshot_date, permaticker)
  == rows persisted
except for rows with no valid permaticker, which must be counted and DOCUMENTED
rather than silently absent.
```

A bulk Sharadar export remains a reasonable future step for VINTAGE COHERENCE —
a corpus assembled piecemeal is a patchwork of vendor vintages and no hash over
it is reproducible by construction. It is NOT a fix for A, B or D, and doing it
first would certify a corpus that still carries all three.
