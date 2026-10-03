# Alpaca operational completion

Decision: 2026-10-03. Complete the free operational source and test the actual
local acquisition, formation and daily continuation before publishing changes.
The canonical strategy, 300-session decision boundary, 126 formation transitions,
$50,000 genesis, retained ownership and execution membrane are unchanged.

## Instrument classification

Alpaca's active listed tradable asset inventory supplies discovery and stable
asset UUIDs. OpenFIGI mapping replaces Nasdaq name parsing as instrument-type
authority. Retain common stock, ordinary-equity ADR/GDR, New York registered
shares, REIT common shares, royalty trusts and partnership shares. Preserve the
previous broad policy's closed-end common fund shares (including BDCs);
exclude ETFs/ETPs, preference shares, warrants, rights, notes and bundled units.
No ticker-specific rules are permitted. US composite mappings must agree on
security type, composite FIGI and share class; absent, malformed or ambiguous
metadata excludes that candidate, with counts and reasons. Classification does
not merge assets or turn issuer identity into instrument identity.

Use only the fixed OpenFIGI mapping endpoint, bounded response sizes and batches,
rate pacing and bounded transient retries. Its POST is a read-only identifier
lookup, never broker transport. The optional free OPENFIGI_API_KEY goes only to
OpenFIGI and is never evidence. Persist classified references in the existing
retained acquisition parts per mapping batch; resume must reuse the exact
generation. Persist the initial classification plan, including cache choices and
batch size, before mapping. A slow job crossing a cache-expiry date must resume
that frozen plan rather than shifting completed batch identities or repeating work.
Reuse classifications from the preceding verified publication for
up to seven calendar days only when asset UUID, symbol, exchange and name still
match. Unresolved classifications expire after one day. Preserve original
observation dates, rather than renewing their age by copying them. New/changed
assets and expired classifications require fresh lookup. This avoids repeating
whole-universe mappings every day; it adds no database table.
Retain the latest publication's aggregated TICKERS acquisition part as a durable
classification dependency. Ordinary scratch cleanup must not delete that part
immediately after publication; older aggregates are released when replaced.
This pin does not retain completed price partitions or expired mappings as authority.
Operator progress identifies the retained component and FIGI batch count so a
metadata batch cannot look like a repeated whole-universe download. Classification
progress admits only bounded counts and the existing safe component-name grammar.
Source-revision recovery treats dated partitions and metadata subcomponents as
different names; a FIGI batch suffix is never parsed as a date interval.
Recheck Alpaca inventory after acquisition without repeating the entire classification.
The new ALPACA_OPENFIGI source identity cannot silently reuse an older Nasdaq
source as deployment authority. Old manifests remain inspectable with their
original source identity. A fresh unadmitted Nasdaq snapshot is replaced through
ordinary acquisition/publication, preserving the previous records.
Measure whole-universe coverage and liquid-universe changes before release.

## Formation work reuse

Use a source-bound, in-process rolling reader for formation. Validate each newly
read canonical row once and retain packed numeric arrays for at most 300 market
sessions. Every feature calculation invokes the existing canonical formulas on
its own trailing window; protected histories, state commitments and signal basis
bridges remain unchanged. Cache lifetime is one immutable pinned candidate.
Backward or nonadjacent requests rebuild their bounded slice. No future prices,
earlier-than-window candidate facts or broker state may enter a decision.
Emit formation-session progress. Compare full formation state, transition chain
and frontier inputs against the uncached implementation on the same snapshot.

## Free execution opening prices

Keep the regular opening minute and existing 120-second sizing freshness rule.
Use explicitly identified raw IEX minute bars, available on the free plan,
instead of requesting recent SIP bars which require a subscription. This is an
execution price-source change, not a controller or selection-rule change. Never
substitute yesterday's price or label IEX as consolidated SIP. Preserve positive
volume, exact minute, instrument identity and Decimal checks. Missing evidence
suppresses new buys while preserving the existing permitted reductions. No
broker mutation is authorized by this work package or its real-provider probes.

## Daily ownership and actions

Candidate-history reset remains appropriate for unsupported structural events
during cold formation. During continuation, an already-owned identity cannot
disappear through that reset. Map usable dated split terms into canonical share
multiplier events, corroborate adjusted/raw price evidence, and preserve held
history across that supported event. Ordinary dividends retain their current
canonical treatment. Signal closes use the independently supplied split-only
adjusted series; raw prices and volume remain the liquidity/share domains.
Across each supported split the change in adjusted/raw ratio must match the
stated new/old share multiplier. The first price must precede an in-window
split; missing corroboration cannot be inferred from a price jump. Unsupported
or ambiguous held events refuse before any
ownership mutation; never invent merger, spin-off, rename or fractional terms.
These restrictions are generic and automatically reconsidered on new source
observations. Broker account corrections are execution inputs, not authority to
rewrite the shadow book.

Actual provider qualification found cent-rounded split-adjusted closes paired
with sub-cent raw closes. A fixed five-basis-point ratio-range test wrongly
excludes otherwise consistent split histories. Keep that original test as the
first check. For a security with explicit usable split terms, additionally allow
one common adjustment factor whose interval agrees with every observation after
applying those exact cumulative multipliers. Cent-aligned adjusted prices have
at most half a cent of rounding displacement, capped by the existing shared
one-percent split-agreement tolerance; other prices retain the original narrow
relative interval. An empty intersection, unknown split, wrong multiplier or
missing predecessor still excludes the security. This does not reconstruct or
rewrite prices, infer share terms, or relax the population floor. Version this
normalization separately and replace an older unadmitted snapshot through ordinary
acquisition before GO can use the new semantics.

The fixed BIL sleeve is an execution-held instrument too. Retain its usable cash
dividend and split records even though the stock-candidate policy excludes ETFs.
Its signal open/close come from independent split-only bars, its total-return
close from all-adjusted bars, and its execution mark remains raw. Corroborate
split-only/raw discontinuities with the dated action terms. Missing or unsupported
BIL structural terms refuse publication rather than silently skipping sleeve
reconciliation. SPY continues to supply total-return benchmark closes.

Qualification must exercise held splits and dividends, repeated observations,
changed terms, unsupported held events, independent unrelated candidates,
successor publications, restart, missed sessions and paper top-up/reconciliation
through the production functions. Real provider acquisition and read-only GO
are distinct from simulated order/failure tests; reports must state each scope.
Passing a local diagnostic does not issue signed deployment admission.

Sources: [OpenFIGI mapping API](https://www.openfigi.com/api/documentation),
[Alpaca market-data access](https://docs.alpaca.markets/us/docs/market-data-faq).
