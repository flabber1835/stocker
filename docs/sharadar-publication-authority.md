# Sharadar publication authority

**Status: design settled for issue #178, 2026-08-18.** This document is the
source-of-truth for the source-publication boundary implemented by
`sentinel/feed/authority.py` plus `sentinel/feed/coherence.py`. It supplements
the price-domain and corpus publication rules in `docs/sentinel-deployment.md`
and `docs/sentinel-execution-contract.md`; it does not weaken any of them.

## 1. Transport success is not publication authority

A successful Nasdaq Data Link Tables traversal proves only that the HTTP
requests completed. The documented Tables API pagination contract says to follow
`qopts.cursor_id` / `next_cursor_id` until there is no next cursor. The public
Tables documentation does **not** expose a generation identifier, snapshot token,
or isolation guarantee binding all cursor pages to one immutable table image.
Bulk export metadata has snapshot timestamps; cursor pagination does not expose
an equivalent authority token.

Sentinel therefore does not infer snapshot consistency from pagination. For
every source table whose rows can change a published corpus generation it takes
two complete observations and requires an order-independent, multiplicity-
sensitive content fingerprint to agree before publication may succeed.

Official documentation consulted for this decision:

- `https://docs.data.nasdaq.com/docs/in-depth-usage-1`
- `https://docs.data.nasdaq.com/v1.0/docs/parameters-1`

The check is application-level on purpose. If Nasdaq later documents and exposes
an immutable generation token, replacing the double-observation rule requires a
separate design change and a falsifier proving the token covers every page and
every table Sentinel joins.

## 2. The four Sharadar inputs and their authority fields

The stability fingerprint covers every field that can change current Sentinel or
Wealth Core behavior, plus persisted reference fields whose future consumption
must not bypass the authority boundary. Formatting-only or display-only vendor
fields do not get to create false publication churn.

### SEP

```text
date             session identity
ticker           symbol used for permanent-identity resolution
close            split-adjusted, dividend-unadjusted signal domain
closeunadj       as-traded close / marking domain
open             split-adjusted open used to reconstruct the as-traded open
volume           ADV/liquidity domain
```

`closeadj` is deliberately excluded from security-level SEP authority because
Wealth Core is forbidden to consume the total-return domain. The separately
scoped SPY regime path is SFP, below.

### TICKERS

```text
table            identifies which Sharadar product row the metadata describes
permaticker      permanent security identity
ticker           session-facing symbol / ticker-reuse boundary
category         certified Wealth Core eligibility input
relatedtickers   issuer-family grouping input; blank is legitimate evidence
firstpricedate   listing-window lower bound / history-age provenance
lastpricedate    listing-window upper bound / ticker-reuse disambiguation
sector           Sentinel breadth-sector input; sparse values are legitimate
isdelisted       retained listing-state evidence; terminal authority remains ACTIONS
```

The fingerprint covers every TICKERS field Sentinel persists. `category`,
`relatedtickers`, the listing bounds, permanent identity and `sector` can affect
current production decisions. `isdelisted` is retained evidence but does not
replace ACTIONS terminal state. Fields such as `name`, CUSIP, FIGI, company site,
and SEC filing URL are not persisted into Sentinel's strategy metadata and are
not authority-bearing.

`exchange` deserves an explicit note because the shared Wealth Core type supports
exchange gating. Sentinel's current production loader does **not** populate
`SecurityMeta.exchange` and therefore leaves `exchange_authoritative=False`; the
field cannot change current Sentinel behavior. Enabling authoritative exchange
filtering later requires adding `exchange` to this source contract and its
stability tests before the behavior is activated.

Blank `relatedtickers` is not "missing metadata": most securities have no issuer
siblings, so it has no non-null coverage floor. `sector` is also legitimately
absent for a small tail. Fields that were complete in the retained TICKERS ground
truth are required exactly; they do not share a generic 99% escape hatch that
could hide one stale category behind thousands of healthy rows.

A TICKERS snapshot is observed before the price traversal and corroborated only
after a complete protected SEP observation. This deliberately brackets the
cross-table join. A generation that changes listing bounds or strategy metadata
while SEP is being read is refused rather than publishing a mixture.

### ACTIONS

The complete canonical seven-field ACTIONS source identity is authority:

```text
date, action, ticker, name, value, contraticker, contraname
```

No coarser economic key is substituted at the source boundary. Normalization and
economic coalescing happen after source identity is preserved.

For a **daily** ingest there is one protected SEP window, so TICKERS, ACTIONS and
SFP are all corroborated across that window. A **multi-year seed** is different:
each yearly SEP chunk receives its own two-complete-observation stability proof,
but the first TICKERS, ACTIONS and SFP observations remain pending until the
**final** SEP chunk has completed its first observation. Only then are all three
reference sources corroborated. This brackets the full seed cross-table join
rather than proving ACTIONS after year one and then allowing later SEP years to
arrive under a different vendor action generation.

### SFP / SPY regime

```text
date
ticker
closeadj
```

This is the one named total-return path required by the frozen Sentinel regime
rule. Its first observation is also bracketed across protected SEP before it is
accepted as one publication generation.

## 3. Historical seed completeness is stricter than daily anomaly readiness

A one-time seed creates the foundation later daily generations inherit. It may
not publish merely because aggregate rows look plausible. Every seed SEP chunk
is checked session-by-session before its rows are allowed into the ingest:

```text
expected exchange session present                 required
session row count                                 >= 4,000
session population / local 20-neighbour median    >= 90%
permanent identity resolution                     >= 99%
signal close                                      >= 99%
raw close (closeunadj)                            >= 99%
reconstructable raw open                          >= 99%
volume field present                              >= 98%
```

The population tests have two jobs. Exchange-session continuity catches a whole
missing session. The absolute floor catches a uniformly truncated traversal that
a relative test cannot see. The local-median rule catches a session-local page
loss without assuming the market has a constant number of listed securities.

These are source-completeness guards, not investability rules. Zero volume is an
observed liquidity fact and counts as a present volume field; a security may be
ineligible later without making the vendor publication incomplete.

## 4. Calibration against the retained Sharadar ground truth

The thresholds above were measured before implementation against the retained
bulk Sharadar SEP/TICKERS files, not chosen from the observed production outage.
The SEP calibration covered **7,189 exchange sessions from 1998-01-02 through
2026-08-03**. Identity was resolved against the TICKERS `table=SEP` listing
intervals.

Observed worst SEP session values:

```text
identity resolution                      99.9516%
raw close                                99.9829%
signal close                            100.0000%
reconstructable raw open                100.0000%
volume field present                     98.7660%
local population / 20-neighbour median   94.1289%
absolute session population                 5,310   (historical minimum)
```

The retained TICKERS bulk snapshot contained 21,939 `table=SEP` rows. Its field
coverage was:

```text
permaticker                            100.0000%
category                               100.0000%
firstpricedate                         100.0000%
lastpricedate                          100.0000%
isdelisted                             100.0000%
ticker                                  99.9954%   (one blank row)
sector                                  99.4120%
relatedtickers                          58.1749%   (blank is legitimate semantics)
```

Accordingly, the exact fields above are required at 100%, ticker at 99.99%, and
sector at 99%. `relatedtickers` is fingerprinted but has no non-null floor.
This is the deliberate distinction between sparse semantics and a partial source
publication.

The 90% local-population threshold leaves more than four percentage points below
the worst legitimate contraction in the retained corpus, including the
2026-08-03 contraction that motivated the earlier daily-population review. The
4,000-row absolute floor is about 25% below the historical minimum. The 99%
identity/raw floors are materially below observed legitimate sparsity while still
rejecting a page-scale or cross-section-scale collapse. The 98% volume floor is
below the 98.766% historical low rather than incorrectly treating the known
2024/2025 zero/missing-volume tail as corruption.

A future clean corpus that violates one of these bounds is a reason to inspect
and deliberately recalibrate the contract, not a reason for runtime code to
silently lower the threshold.

## 5. TICKERS listing-window corrections may narrow

Sentinel must not assume `firstpricedate` can only move earlier or
`lastpricedate` can only move later. The vendor fields are reference-data
observations, not monotonic counters, and no immutable vendor guarantee was found
that corrections can only widen an interval.

Raw dated TICKERS snapshots remain append-only evidence. The derived
`feed_universe_current` projection carries the **latest non-null observed bound**
for each `(permaticker, ticker)` pair. A later authoritative snapshot may move
`firstpricedate` later or `lastpricedate` earlier. Null in a later sparse
snapshot means "no new observation" and carries the previous non-null value; it
does not erase a bound. Candidate identity resolution uses the same precedence
before publication, so the ingest validates bars against the exact interval it
would publish.

This replaces the old `MIN(firstpricedate)` / `MAX(lastpricedate)` envelope,
which made every historical widening permanent and could assign a reused ticker
to a security outside the vendor's corrected listing interval.

## 6. Refusal and retry semantics

`VendorPublicationUnstable`, seed completeness refusal, frontier-domain
incompleteness, and permanent-identity coverage refusal are **data-authority
refusals**. They are not evidence of corrupt durable Sentinel authority.

- No candidate generation publishes after one of these refusals.
- Readers continue to see the prior published generation under the existing
  visibility/pinning rules.
- Active automation records the refresh failure in `RETRY_WAIT` and retries the
  `REFRESH` phase.
- A deployed-but-fenced runtime records `AUTOMATION_FENCED_DATA_NOT_READY`, stays
  disabled with the kill switch engaged, and retries its data wake. Data becoming
  ready never releases broker authority by itself.
- Nonretryable automation refusal remains reserved for signed authority,
  configuration, schema, account identity, or other durable-integrity failures.

This is the #160 state split applied to source stabilization: **deployed** and
**operationally ready** are independent facts.

## 7. Invariants this design does not change

The source checks add a gate before publication. They do not alter the existing
transactional authority chain:

```text
candidate rows remain invisible until corpus publication
publication remains atomic
published readers remain pinned against in-place writes
unresolvable permanent identity is still refused, never ticker-guessed
execution still requires the full readiness + signed-authority gates
raw source evidence is retained; corrections happen through a new generation
```