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

**2026-08-20 correction:** that row count described the lossy backtest schema,
not the Sharadar source. The retained ACTIONS export contains 672,423 distinct
complete rows but only 669,801 distinct `(ticker,date,action)` keys: 2,622 rows
were unrepresentable across 1,594 collision groups. The reader findings below
remain historical evidence, but the old `bt_actions` cardinality is not corpus
soundness evidence. Current schema invalidates it and requires a complete-row
rebuild before readiness.

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

### Defect D — the vendor supplies EVENT METADATA, not holder-level settlement terms

**THE SEMANTIC FACT, stated first because it is the one that matters and the one
that took four queries to establish:**

```text
Sharadar ACTIONS gives event IDENTITY and AGGREGATE TRANSACTION VALUE.
It does NOT give holder-level settlement terms — no cash per share, no
exchange ratio, at any action type.
```

An earlier draft of this section led with the action-NAME mismatch and called it
the highest-severity finding. That was wrong and is corrected below: the naming
gap is real but secondary. No renaming, remapping or additional action type
produces terms the table does not contain.

#### What the columns actually hold (observed, 2026-08-08)

```text
ticker  date        action         value    contraticker  contraname
TMHC    2026-07-23  delisted       6768.8   N/A           N/A
TMHC    2026-07-23  acquisitionby  6768.8   BRK.B         BERKSHIRE HATHAWAY INC
NUVL    2026-07-15  acquisitionby  9792.6   GSK           GSK PLC
ORLA    2026-07-31  acquisitionby  3265.6   EQX           EQUINOX GOLD CORP
AVNS    2026-07-24  acquisitionby  1170.2   N/A           AMERICAN INDUSTRIAL PARTNERS CORP
CCRN    2026-07-21  acquisitionby   428.4   N/A           KNOX LANE LP
GVHGF   2026-07-31  delisted          0.2   N/A           N/A
```

```text
value         TRANSACTION VALUE IN MILLIONS OF DOLLARS. Identical across the
              `delisted` and `acquisitionby` rows of one event, so it is a
              per-EVENT attribute. TMHC/Berkshire at 6768.8 and NUVL/GSK at
              9792.6 are deal sizes; it is NOT a per-share price and NOT an
              exchange ratio.
contraticker  the acquirer's ticker when the acquirer is PUBLIC (BRK.B, GSK,
              EQX, IONQ, PSA, CLBK); the literal string 'N/A' when the acquirer
              is PRIVATE (Berkshire vs Knox Lane LP is the distinction).
contraname    the acquirer's NAME, always populated even when the ticker is 'N/A'.
```

#### Two coding defects follow from misreading those columns

**D1 — `'N/A'` is a SENTINEL STRING and defeats the absence check.**

```python
contra = row.get("contraticker") or None      # normalises None and '' — NOT 'N/A'
if contra:                                    # 'N/A' is truthy
    return TerminalTerms(..., kind=TerminalKind.CONVERSION,
                         delivered_ticker=contra, exchange_ratio=value, ...)
```

Every one of the 19,216 `delisted` rows carries a `contraticker` (0 of them equal
to the security's own ticker), so EVERY terminal event takes the conversion
branch. `'N/A'` then fails identity resolution as `unknown_ticker`,
`delivered_security_id` is None, and `completeness()` refuses with
`MISSING_DELIVERED_SECURITY` — the deal BLOCKS. That is the BIOT failure
reachable 19,216 ways, and it needs no missing action name to fire.

**D2 — `value` is read as an EXCHANGE RATIO.** It is a deal size in millions. The
code never uses the number today only because the completeness check refuses
first; that is luck, not design. Were identity resolution ever to succeed on that
field, a TMHC holder would be delivered 6,768.8 shares per share.

#### The naming mismatch — real, secondary, and MEASURED

SIX of the seven names in `TERMINAL_ACTIONS` do not exist in the corpus, and
comparison is exact set membership (`action not in TERMINAL_ACTIONS`):

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

**Severity is bounded by a measurement, not an estimate.** Every ticker carrying
one of those unmatched terminal actions ALSO carries a `delisted` row —
12,253 of 12,253, exactly — so termination is always DETECTED. The unmatched rows
add the counterparty identity (`contraname`, and `contraticker` when public), not
the fact of termination and not the terms. Fixing the names is worth doing for
provenance and for the audit diagnostic below; it resolves nothing on its own.

Also unconsumed, same class: `adrratiosplit` (386) is absent from
`SPLIT_ACTIONS`, so those ADR share-ratio changes never adjust the split factor —
a genuine correctness gap, since it IS a share-count change.
`spinoffdividend` (497) is absent from `DIVIDEND_ACTIONS`; `specialdividend` is
IN the code and matches zero rows; `tickerchangeto` / `tickerchangefrom` (13,437
each) are 26,874 rows of the vendor stating that a symbol moved, directly
relevant to defects A and B.

**THE ACQUIRER-SIDE TRAP. Do not fix the names with a substring match.**
`acquisitionof` (7,193) and `mergerfrom` (116) are the ACQUIRER's side and are
NOT terminal for the security carrying them. Treating them as terminal writes off
the buyer instead of the target. Any fix must be an explicit per-name mapping
with a stated side per name; a pattern match on `acquisition` or `merger` is
worse than the bug.

#### Consequence for settlement

Walk every branch and the corpus settles nothing:

```text
sentinel unfixed              CONVERSION -> MISSING_DELIVERED_SECURITY  -> blocks
sentinel fixed, PRIVATE buyer CASH_MERGER, per-share cash unknown
                                         -> MISSING_CASH_PER_SHARE      -> blocks
sentinel fixed, PUBLIC buyer  incomplete terminal economics; the public buyer
                              identifies the acquirer, not consideration
                                         -> MISSING_CASH_PER_SHARE      -> carries
                                            through the settlement waterfall
```

The public-buyer distinction is load-bearing.  ACTIONS can carry several
``acquisitionby`` rows for one consortium transaction (for example Air Lease
Corporation with SMBC Aviation Capital, Sumitomo, Brookfield and Apollo named
across sibling rows).  Treating every public ``contraticker`` as delivered
shares invents several mutually exclusive conversions from one acquisition.
The mapping therefore retains buyer ticker/name as provenance only and never
sets a delivered security, exchange ratio, or consideration type from those
fields.

So a terminal settlement policy is not an optional fallback for rare cases. It is
the ONLY path by which any of the 19,216 delisted securities can leave the book.
That is what forced the C1/C2 split in docs/architecture.md "orphan resolution" —
a blanket zero write-off would have been applied to 19,216 KNOWN acquisitions
whose holders were demonstrably paid.

#### Audit diagnostic (never portfolio cash)

`value x 1e6 / shares_outstanding` is computable where SF1 coverage permits and is
worth computing as a CHECK on the last-mark proxy for straightforward cash
acquisitions. It must never determine portfolio cash: deal value may include
assumed debt or other enterprise-value components, shares outstanding differ from
shares entitled at closing, options/RSUs/converts dilute, stock and mixed deals
are not cash-per-share deals at all, and SF1 counts can be stale relative to the
event. It produces a precise-looking, economically wrong number.

### Remediation order (owner decision, 2026-08-08)

```text
1  A   re-key bt_universe on (snapshot_date, permaticker); ticker becomes an
       ATTRIBUTE and a lookup key, never permanent identity. _upsert_universe
       must report rows PERSISTED, with rows lacking a valid permaticker
       counted and named rather than dropped silently.
2  B   re-run the universe backfill, then QUANTIFY the splices — reused_tickers
       only becomes truthful once A is fixed, so the population is unknown today.
3  D1  the 'N/A' sentinel: treat it as ABSENCE, not as a delivered security.
       Audit every `or None` normalisation against a vendor sentinel, since the
       idiom looks total and is not.
   D2  stop reading `value` as an exchange ratio. It is a deal size in millions
       and belongs in provenance, never in a share or price computation.
   D   per-name action mapping with an explicit SIDE per name (acquirer vs
       target), for provenance and the audit diagnostic. Resolves nothing alone.
4  C   the terminal-settlement contract, C1 and C2 — docs/architecture.md
       "orphan resolution". This is the ONLY path by which a delisted security
       can leave the book, not a rare-case fallback.
5      tests for all of the above, THEN re-run the 2021-2023 rehearsal.
```

D was reordered ahead of A at one point on the claim that 12,253 terminal events
were invisible and blocking. That claim was WITHDRAWN: the co-occurrence
measurement (12,253 of 12,253 also carry a `delisted` row) showed termination is
always detected, and the blocking comes from D1/D2 and the absent terms rather
than from the names. A stays first.

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

### Cold-boot TICKERS temporal contract (2026-08-15)

Sharadar TICKERS is a daily delivery of the vendor's current securities master.
`snapshot_date` is when Stocker observed that delivery; it is not the effective
date of every value in the row and must never be backdated. Sharadar documents
`permaticker` as a unique, unchanging security identifier in its
[TICKERS documentation](https://sharadar.com/docs/tickers), and exposes
`firstpricedate` / `lastpricedate` as the price-history interval for a
`(ticker, permaticker)` row. It does not expose effective-from/effective-to
history for `category` or `relatedtickers`.

The canonical loader therefore has two deliberately separate authorities:

```text
field                                      historical use
permaticker + ticker + first/last price    IDENTITY ONLY. A later observation
                                           may resolve a price bar only when
                                           its listing interval covers that
                                           exact session. The interval is
                                           required even for a symbol with one
                                           observed owner. Overlap or absence
                                           refuses instead of guessing.

category, relatedtickers, display ticker,  DECISION METADATA. The exact TICKERS
and firstpricedate used for eligibility    snapshot observed for each measured
or issuer-family construction              session is authoritative for that
                                           session. Changes apply forward from
                                           their observation session only.
```

`firstpricedate` and `lastpricedate` from a later delivery are evidence about
the label-to-identity pairing only. They do not make the later row a historical
category, issuer-family, display-label or listing-eligibility observation. If a
historical run lacks a complete session-by-session decision-metadata timeline,
the run refuses explicitly before producing candidates, hashes, or performance.
A start-frozen map would permanently exclude later listings; an end-frozen map
would rewrite earlier categories and issuer families. The canonical engine
therefore consumes the metadata snapshot effective for each decision session.
Identity resolution remains separately available to corpus parity, which needs
permanent bar keys but makes no eligibility decision. `permaticker` names the
permanent security; issuer-family grouping is a separate construction derived
from the contemporaneous `relatedtickers` observation.

The observation date always caps the interval: a delivery observed on D cannot
authorize a price session after D, even if `lastpricedate` is absent or bad.

Each retained decision snapshot is complete, so a row never inherits nullable
values from the preceding observation. Snapshot membership is recorded before
strategy eligibility is evaluated: every TICKERS security with usable row
identity is retained even when it is a fund, preferred, warrant, has a NULL
category, or trades on an unsupported exchange. Otherwise the absence of the
metadata row would erase an existing price row from the decision view and turn
"observed but ineligible" into "not delivered". The raw exchange is retained;
unsupported or empty exchange remains visible and is ineligible downstream.
The ingestion contract is:

```text
field                 present but empty/NULL             field absent
category              authoritative unknown; ineligible incomplete delivery; refuse
relatedtickers         authoritative empty family;        incomplete delivery; refuse
                      fall back to that security's
                      permaticker only
firstpricedate         authoritative unknown lower bound; incomplete delivery; refuse
                      ineligible for a new admission
lastpricedate          authoritative open/unknown upper   incomplete delivery; refuse
                      bound at that observation
exchange               authoritative unknown; ineligible incomplete delivery; refuse
```

`bt_universe.decision_metadata_complete` records that the vendor delivery
contained all five decision keys before normalization. Existing rows pre-dating that
provenance default to false and cannot certify a decision timeline. In
particular, the normalized SQL `NULL` for an observed empty `relatedtickers`
value means **clear the relationship**; it never means “reuse yesterday.”
Missing category never inherits an earlier common-stock label. Ticker and
permaticker remain required row identity; unusable permanent identity is
rejected by the writer.

The ingestion job buffers the complete paginated TICKERS response before the
snapshot write. A fetch exception therefore records a failed run and publishes
no partial observation. Independently, every retained row must carry the
per-row completeness bit above; completing the HTTP delivery cannot turn an
absent decision field into an authoritative empty value.

This split repairs the cold-boot case without future leakage. A fresh database
may contain historical `bt_prices` and only today's TICKERS delivery: bars whose
vendor interval covers their session resolve; bars outside it do not. A
non-empty price window that resolves to zero is an identity-authority failure,
not an empty market, a cash-only backtest, or millions of ordinary parity
membership differences.

Identity repair is TICKERS-only:

```bash
curl -fsS -X POST http://localhost:8021/jobs/backfill-universe
```

The endpoint always records the service's current observation date and never
touches `bt_prices`. Supplying an older `snapshot_date` is refused; copying
today's metadata under a historical date would fabricate exactly the
point-in-time evidence the loader is designed not to invent. No SEP refetch is
required. This current snapshot is sufficient for historical identity/corpus
parity when its bounded vendor listing intervals prove the pairings. It is
**not** historical decision metadata and does not make a multi-year Wealth Core
rehearsal certifiable. Such a rehearsal additionally requires the legitimately
observed TICKERS snapshot for every measured market session; a current-only
rebuilt corpus fails closed until that history is restored from an authoritative
retained source.

### Historical decision-metadata source audit

The repository contains no per-session historical TICKERS archive or database
dump. The reproduction-kit manifest names one external
`SHARADAR_TICKERS.zip`; it is one current securities-master export and has no
observation-date column from which daily category/relationship history can be
reconstructed. The Nasdaq Data Link TICKERS schema likewise exposes current
rows plus `firstpricedate`, `lastpricedate`, and `lastupdated`, not an
effective-dated history of category or `relatedtickers`.

The rebuilt NAS database has only its 2026 observation. No legacy NAS database
containing legitimate 2021--2023 daily observations has been identified or
verified. Unless an operator produces such a retained database/archive with
observation provenance, causal rehearsal remains blocked. A defensible
alternative would require a vendor product that supplies effective-dated
category and issuer-family relationships (plus listing identity), or a reviewed
strategy contract that demonstrably does not consume those fields; neither is
currently available. Current TICKERS rows must not be expanded backward.
