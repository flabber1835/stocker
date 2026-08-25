# Sharadar SEP/SFP source-authority envelopes

**Status: NORMATIVE — issues #254, #255, and #256.**

This document closes three source-authority gaps without changing Wealth Core's
strategy rules:

1. SEP's vendor-update clock must stay inside the causal observation envelope
   before it can affect a fingerprint or durable mutation cursor.
2. A historical SEP seed must prove every strategy-classified common-equity
   listing expected from the same complete TICKERS generation, not merely a
   percentage of rows that happened to arrive.
3. SEP and SFP must contain one and only one source row for each canonical
   `(ticker, date)` key before any candidate staging or upsert can begin.

The governing sequence is:

```text
transport traversal
    -> strict source-key/date/update-envelope validation
    -> exact duplicate rejection
    -> stable-source fingerprint
    -> cross-table and historical coverage proof
    -> staging / normalisation
    -> candidate validation
    -> atomic publication
    -> cursor advancement derived from validated evidence only
```

Validation after fingerprinting is too late. A repeated invalid source response
is stable, but it is not authoritative.

## 1. Canonical SEP update envelope

SEP has two independent dates:

- `date` is the historical market session represented by the row;
- `lastupdated` is the vendor's later mutation clock.

They must never be conflated. A valid retroactive correction can have a 2008
price date and a 2026 update date.

Every operation capable of establishing or advancing the SEP mutation cursor
must declare an explicit update envelope:

```text
complete seed / complete source proof    lastupdated <= observation ceiling
bounded CDC observation                  lo <= lastupdated <= hi
```

The rules are exact:

- a non-empty `lastupdated` is parsed as a strict ISO calendar date;
- complete-source observations may contain an empty `lastupdated`, but every
  non-empty value must be no later than the declared observation ceiling;
- CDC observations require a non-empty value on every returned row and require
  it to lie inside the exact inclusive request interval;
- a future, malformed, missing-when-required, or out-of-envelope value refuses
  the complete observation; it is never clamped or silently excluded from a
  maximum;
- a tracker commits its observed maximum only after its wrapped traversal has
  been exhausted successfully. Abandonment or failure cannot leave a partially
  advanced in-memory watermark;
- the durable cursor is monotonic over validated update evidence only and is
  still written only after the corresponding candidate publication exists.

A seed through `2026-08-24` therefore cannot earn `2099-01-01`, even when two
source traversals repeat the same invalid row. Conversely, a historical price
row updated exactly on the declared ceiling is valid.

## 2. Canonical-key uniqueness

For SEP and SFP, the source authority key is exactly:

```text
(upper-case non-empty ticker, strict ISO date)
```

One complete source observation may contain that key only once. Sentinel rejects
both conflicting and byte/semantically identical duplicates.

Rejecting identical duplicates is deliberate. Collapsing would make local
cardinality differ from the vendor observation and would require a second rule
for deciding which source row supplied provenance. The retained corpus has no
SEP/SFP canonical-key duplicates, so rejection is both stricter and
non-disruptive for the known valid source.

Duplicate evidence is deterministic and independent of page or row order. It
contains the table, canonical key, multiplicity, sorted row fingerprints, and
sorted differing field/value evidence. ACTIONS is excluded: distinct source
rows sharing an economic date/action can be legitimate and continue to retain
exact source-row identity.

The source validator runs before either complete traversal contributes to a
stable fingerprint. The SEP staging boundary also performs an independent
canonical-key preflight before yielding staged rows. This is defense in depth:
a future caller that bypasses the source validator still cannot degrade to
order-dependent last-write-wins behavior.

## 3. Exact historical seed coverage

The denominator for a historical seed comes from the same stable complete
`table=SEP` TICKERS generation that supplies permanent identity and listing
intervals. It is independent of the SEP rows received for the session.

For every expected XNYS session:

1. Determine every TICKERS listing whose authoritative
   `firstpricedate..lastpricedate` interval covers that session.
2. Resolve aliases and ticker changes to the permanent `permaticker`; canonical
   identity, not the display symbol, is compared.
3. Apply the production security-type predicate
   `stock_strategy_shared.wealth_core.eligibility.is_common_equity` to the raw
   TICKERS category. No seed-only category approximation is permitted.
4. Resolve every received SEP `(ticker, session)` through the same
   `IdentityResolver` built from that stable TICKERS generation.
5. Require exact equality between the expected and received canonical
   common-equity sets, after applying only reviewed exact exceptions.
6. Retain explicit counts for expected, received, and absent non-common-equity
   listings by category. They are accounted for, not hidden inside an aggregate
   tolerance.

The seed proof intentionally reuses the production **security-type** predicate,
not the complete dynamic entry predicate. Price, ADV20, signal-day dollar
volume, and history are computed from SEP itself; using those missing rows to
shrink the expected denominator would be circular and would allow any omitted
row to excuse its own absence. The existing post-fetch price-domain, identity,
volume, minimum-population, and neighboring-session checks remain additional
independent defenses.

### Reviewed source-onset exceptions

The retained 1997–2026 corpus was scanned against the stable TICKERS intervals.
No common-equity-class gaps were found before 2021. The only measured gaps are
37 exact opening-session absences across 29 unit-style listings categorized by
Sharadar as common-equity secondary class. In each case TICKERS begins the
listing interval before SEP's first observed price row.

These are not reclassified as ineligible: the production predicate includes
secondary-class common stock. Instead, each accepted gap is encoded as immutable
exact evidence:

```text
(session, permaticker, ticker, category,
 firstpricedate, first-observed SEP session, reviewed reason)
```

An exception applies only when every field matches. Changing a ticker,
permaticker, category, interval boundary, first-observed session, or reviewed
session invalidates it. The list is finite, source-reviewed, and carries no
percentage or pattern-based escape hatch. A new omission therefore refuses until
it is independently reviewed and represented by a new exact evidence record.

## 4. Bounded deterministic evidence

The validators must remain suitable for universe-scale annual chunks:

- SEP rows continue to be spooled and replayed rather than retained in RAM;
- exact source-key and coverage membership is stored in temporary local scratch
  with uniqueness constraints;
- failure evidence is sorted and bounded while retaining exact total counts;
- evidence includes the stable TICKERS projection digest so the expected set is
  tied to the source generation that produced it;
- source row order and pagination cannot change either the verdict or its
  evidence.

A refusal occurs before authoritative staging, publication, or cursor effect.
Retrying the same valid source remains idempotent; retrying an invalid source
cannot preserve partial progress.
