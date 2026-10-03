# Alpaca-led cold-start GO without Sharadar

Decision: 2026-10-02. Scope: first deployment, broker-free formation, and a
read-only GO verdict. This design supersedes the Sharadar production-source
choice in older deployment and current-window documents. It does not turn an
old Sharadar certificate into an Alpaca certificate or authorize paper orders.

## Ownership and sources

Decision: 2026-10-03. Daily-bar request bounds use the inclusive New York
midnight timestamp of the first and last requested sessions. Alpaca labels
daily bars at that timestamp; requesting 23:59:59 unnecessarily reaches into
the future or the recent SIP interval unavailable to the free subscription.
This changes the timestamp filter, not the bar contents or the permission to
consume a session: the existing closed-session and source-final guards remain
required. Each boundary independently uses the New York daylight-saving offset.
Apply the same bounds to raw, split-adjusted and total-return benchmark bars
in GO and daily acquisition. Real authenticated requests returned identical
complete SPY/BIL bars with midnight and later historical bounds, including
the final requested session.
See the [SIP access restriction](https://docs.alpaca.markets/us/docs/market-data-faq)
and [inclusive stock-bar bounds](https://docs.alpaca.markets/us/reference/stockbars).

Alpaca SIP daily bars and corporate actions supply operational market facts.
The free Nasdaq Trader `nasdaqlisted.txt` and `otherlisted.txt` directories
supply a conservative current common-stock universe. This is an Alpaca-led,
Sharadar-free operational path, **not literally Alpaca-only input**. Preserve
Sharadar code, database data, and backtest tools for historical research; do not
query Sharadar, read its operational tables, or require its credential in GO.
Alpaca account/position/activity APIs remain inside execution and
reconciliation. Wealth Core and Sentinel do not read broker holdings.
The GO preparation child receives the two Alpaca API credentials solely to
read the fixed market-data and asset endpoints through a GET-only allowlisted
client. It receives no configured paper-account ID and must not call account,
order, position or activity endpoints. These credentials can technically grant
broker authority outside that client, so the reviewed runtime image and
zero-broker-mutation GO check remain mandatory; do not describe this as a
credential-level read-only key.
The ordinary run-only Sentinel compose service has no standing Alpaca keys.
The GO host passes both keys by name to its single reviewed preparation child;
other read-only probes and a manually started container inherit no broker
credentials from that service. This confines the unavoidable credential-bearing
process to the source acquisition operation.

The older local-full read-only Sharadar preflight is not part of this GO route.
Both normal and local-full GO use the same bounded Alpaca preparation and
readiness checks; retaining a separate Sharadar preflight would reintroduce a
credential/source dependency before that preparation begins.
The human-facing D2 banner calls this market-data readiness. Its existing
`sharadar_readiness` evidence key stays unchanged in schema v1 so older bundle
readers do not misparse the verdict; the gate now reads Alpaca/Nasdaq content.

The selected strategy and snapshot have new source/policy identities. An old
Sharadar publication or book cannot satisfy this GO. The first GO does not
enable daily automation or paper transport; those require their own source
continuation and action-economics qualification. A GO refusal must retain its
failed-attempt evidence and cannot delete the historical corpus.

## Current universe

Intersect the current Alpaca `active`, `tradable`, `us_equity` assets with both
current Nasdaq Trader directories. The Nasdaq row must uniquely match the
symbol and have `ETF=N`, `Test Issue=N`. Reject names that explicitly identify
warrants, preferred/preference shares, rights, notes, debentures, ETNs,
corporate/tangible-equity units, or unqualified depositary shares. Preserve
American and global depositary shares representing ordinary equity; the bare
`Depositary Shares` description denotes a separate security that this first
GO cannot safely classify as common stock.
`ETF=N` does not distinguish an operating-company share from a listed
closed-end fund or BDC common share. Sharadar's historical `Common Stock`
category itself includes some BDCs. Retain this broad listed-equity perimeter
for the first read-only comparison and treat issuer-type differences as a
separate economic-qualification question before paper orders.
Do not require a literal `Common Stock` phrase: that discarded hundreds of
otherwise eligible ADR and class-share issues. Do not exclude `depositary`
generically, because it also describes ordinary ADR equity. Nonmatching rows
and explicit non-stock instruments are excluded.
Asset UUID is the security identity; the current symbol is its label. First
listing date is the first verified observed bar in this captured window, not an
invented historical listing assertion. Nasdaq security-name wording is a
conservative policy filter, not a typed legal classification. On the saved
2026-09-30 provider capture, the initial broad rule retained 2,097 of the
2,105 Sharadar strategy-eligible tickers after the same price/liquidity screen,
with seven additional liquid symbols. A later action-history reset reduces the
Alpaca/Nasdaq admitted count further; those figures must not be confused.
The raw pre-liquidity capture contains 5,799 current Sharadar common-stock
tickers and 6,171 initial Alpaca/Nasdaq candidates from directories captured
the next day. Five of the latter are Sharadar-classified preferred securities;
their generic name patterns are now excluded, along with two other unit/share
descriptions. The tightened policy has 6,164 raw candidates. None of the
seven exclusions passed the saved liquidity screen. These
are ticker-overlap diagnostics, not an
identity-equivalence or future-universe guarantee. GO must report the selected
and admitted populations and refuse a large unexplained population collapse:
at least 95% of selected current symbols must have usable paired price history
through the frontier. This is an acquisition-availability guard, not Wealth
Core's liquidity or 300-session eligibility threshold.
The source files, Alpaca asset response, parameters, acquisition times and
checksums are sealed.

Nasdaq's free files do not provide reliable sector or issuer-family IDs.
The selected Owned55 controller already uses residual-return correlation peers
for breadth and does not consume sectors. Its kernel currently computes and
discards a legacy sector-based breadth first; remove that redundant calculation
for the selected Median-5 family while retaining the historical classifier for
other profiles. This first GO carries sector `None` without changing the
selected controller rule. Distinct listed classes have distinct Alpaca asset
UUIDs. If the same symbol maps to multiple assets or directory rows, refuse
the ambiguity rather than guessing from a ticker suffix.
The changed candidate universe still needs economic qualification before paper
execution.

## Bounded acquisition and action safety

Cold start acquires the selected 426 consecutive XNYS sessions: 299 feature
sessions, 126 broker-free canonical formation transitions, and the current
decision. Each formation decision still sees only its trailing 300 sessions.
Daily continuation, when implemented, uses the existing 300-session window and
retained ownership state; it never reconstructs the book from daily prices.

Request every page of Alpaca SIP raw and split-adjusted daily bars over this
window, with an explicit as-of date and bounded request/retry/rate budget.
The separate SPY/BIL benchmark acquisition pairs raw with Alpaca `all` adjusted
bars and transports the adjusted close as the typed benchmark `closeadj` field.
That name is permitted only at this exact source adapter and the already
reviewed benchmark transport path; stock signals and marks still use the
split-adjusted signal close and raw tradable close, never total return.
Batch up to 400 symbols per monthly daily-bar request. A month has at most 23
trading sessions, so one full batch has at most 9,200 bars under Alpaca's
10,000-bar page limit; still follow every returned page token. A live
400-symbol September 2026 probe returned 8,359 bars in one page. This replaces
roughly 62 requests per month and adjustment at 100 symbols with about 16,
without loosening response-size or identity checks.
Compare paired price series on each security to detect a split adjustment that
was not safely resolved. Obtain every page of corporate actions, including
incomplete observations, over a bounded process-date interval that covers the
acquisition. A dated split, merger, spin-off, rename or other
non-cash-dividend action inside the window resets the involved security's
candidate history: discard bars and dividends through its economic date, and
admit only a contiguous, paired history after the latest such event. The
candidate therefore has no formation holding that crosses an unmodelled
action. A structural event with an unknown or malformed economic date, or one
after the observed window, excludes the involved security from first GO. A
dated event before the observed price window is not a reason to discard a
current stock: its effects are already incorporated in that window's raw bars.
The raw/split-adjusted comparison independently checks for an unresolved
split in the admitted post-event history. This generic rule does not invent
shares or terminal outcomes and allows a stock to re-enter once clean history
has accumulated.

Ordinary cash dividends do not remove a stock from the universe. Admit one
only when its participant, ex-date within the admitted price history, USD rate
and unique action identity are usable. Map the per-share amount onto the ex-date
canonical bar and sum distinct same-day payments. A malformed, non-USD, or
ambiguous cash-dividend record excludes the affected stock. The `foreign`
indicator alone does not make a rate unusable: Alpaca's US corporate-action
feed supplies a per-share cash rate for foreign issuers, with source-country
withholding reflected upstream. Accept either boolean value when the rate is
positive and the currency, when provided, is USD; account-specific tax
withholding remains execution/reconciliation data, never a Wealth Core input.
A cash-dividend
record whose process date is within the queried interval but ex-date lies
outside the window does not mutate the window. This uses currently observed
action facts for broker-free book formation, not a point-in-time historical
announcement claim. A later phase must qualify action economics for held
securities before paper automation is enabled.

For an admitted security, paired raw and split-adjusted ratios must be
constant throughout its observed history. Raw close is therefore the
split-adjusted, dividend-unadjusted signal required by Wealth Core; raw
open/close remain execution/mark domains; split ratio is one. Broker-free
formation credits mapped cash dividends. Do not translate an adjusted series
into a raw price.
SPY and BIL are separate required benchmarks; their total-return and raw
domains are obtained explicitly from Alpaca and cover every session. No absent
bar, price, action or benchmark is synthesized. A missing candidate row removes
its contiguous eligibility; a missing held mark would still block mutation.

Persist complete bounded provider parts once, verify their bytes before reuse,
then build and seal an immutable candidate. Use the same publication CAS, worker
fence, backup authority and read-only GO pin as before. Alpaca has no atomic
cross-endpoint generation: record exactly what was fetched and when, reobserve
references and the frontier before publication, and never call a checksum an
Alpaca-wide snapshot. If a required reobservation differs, refuse or create a
bounded successor; do not restart from scratch indefinitely.
Retained-price scans and content checks use bytewise ticker order across all
parts, independent of the PostgreSQL database locale; dotted class symbols
must not change order between Python acquisition and database replay.

## Qualification gates

The first PR must prove provider pagination and duplicate-token refusal,
Nasdaq classification failures, asset-ID collisions, page corruption, action
quarantine, adjusted/raw discontinuities, missing candidates, exact session
and benchmark coverage, feature-window no-lookahead, formation/restart
equivalence, source-version rejection, and no Sharadar credential/network use.
Then run an actual local GET-only capture and cold-start GO against an isolated
database and the branch image. An official GO verdict still requires the
certified image built from the merged commit. No backtest CAGR or Sharadar
parity claim transfers to this source and strategy identity.

The 2026-10-01 target was exercised locally with real Alpaca/Nasdaq GETs and
an isolated PostgreSQL container capped at 1 GiB, matching the NAS database
limit. The run selected 6,162 current candidates, admitted 6,139 with paired
price histories, normalized 2,110,019 bars, sealed the independent key set,
completed operational validation, and published/read back data version 1.
This is a provider and publication rehearsal, not an official certified GO:
the unmerged checkout used local-only producer identity and backup substitutes.
One earlier attempt found a database-locale ticker ordering bug; a regression
now falsifies the bytewise ordering guard. Refused attempts remain recorded.
The optional manual synthetic full-GO harness still models Sharadar and does
not establish an Alpaca verdict. It must be replaced or rerun against a
reviewed Alpaca fixture before its full-lifecycle certificate is cited for
this source. Normal PR tests and the real-provider rehearsal are separate
evidence with narrower claims.
