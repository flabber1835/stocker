# Issue #250 — Sharadar ingress authority closure

## Status

Design approved for implementation on `codex/issue-250-sharadar-ingress`. The
base is `c9d40863270aa088783a534c78cd9a61bd6ec47f` (`main` at investigation
start). This change is feed-only: it does not alter Wealth Core ranking,
portfolio construction, Sentinel controller rules, broker behavior, or account
authority.

## Problem statement

The current feed can still report a green publication while one of its source or
projection boundaries is weaker than the claim attached to that publication:

1. a complete identity rebuild can lose to an older `snapshot_date` in the
   current-universe projection;
2. SEP and SFP requests are trusted to honor their requested interval rather
   than proving every returned row belongs to it;
3. a stable but partial historical SEP response can pass aggregate population
   floors;
4. duplicate source keys and impossible TICKERS listing models are not rejected
   before normalization;
5. manual `feed-daily` derives its boundary from the container calendar date;
6. a seed spans multiple independent source observations without an immediate
   full overlap proof; and
7. complete ACTIONS reconciliation constructs several simultaneous whole-table
   Python object graphs and therefore depends on an oversized memory envelope.

The common defect is authority ordering. Transport success, observation date,
aggregate plausibility, and heap capacity are not publication authority.

## Invariants

### Publication-generation precedence

An `identity_rebuild` run is a complete replacement generation. In the same
transaction that inserts its corpus-publication row, `feed_universe_current`
must be replaced from that candidate generation and proved equal to it for:

- exact `(permaticker, ticker)` membership;
- `first_price_date`; and
- `last_price_date`.

Publication version outranks vendor observation date. `snapshot_date` remains
provenance only. Schema rebuild/reprojection applies the same ordering: the
latest published identity-rebuild generation is the membership floor, and later
published generations outrank earlier generations even when their observation
date is older. A failed assertion rolls back both projection and publication.

### Source-envelope proof before content proof

Every SEP/SFP row crosses one reusable source validator before fingerprinting,
staging, normalization, or watermark advancement. The validator proves:

- valid ISO source dates;
- exact inclusive `date.gte` / `date.lte` containment;
- membership in the XNYS session set when the caller claims a market-session
  window;
- exact `lastupdated.gte` / `lastupdated.lte` containment for CDC; and
- `lastupdated <= observation_through` when a seed earns a watermark.

A violating row rejects the complete observation. It is never filtered away.
This membrane is reused by ordinary seed/daily acquisition, CDC, historical
renormalization, deep and recent reconciliation, and SPY/BIL SFP acquisition.

### Canonical source keys

Before downstream processing:

- SEP and SFP enforce one semantic row per `(ticker, date)`;
- TICKERS enforces one semantic row per `(permaticker, ticker)`;
- a byte-for-byte/canonically equal repeat may collapse under an explicit rule;
- a conflicting repeat is a hard refusal;
- staging also has a practical unique key so a future caller cannot bypass the
  source membrane silently; and
- ACTIONS remains at exact seven-column source-row grain, preserving legitimate
  siblings that share `(ticker, date, action)`.

TICKERS additionally refuses reversed listing intervals, malformed listing
state, and overlapping active intervals where the same ticker is assigned to
different permanent identities.

### Exact seed coverage

The exact stable SEP TICKERS snapshot defines the expected listing population
for each session. Strategy eligibility is frozen from the reviewed Wealth Core
common-equity classifier before any SEP rows are inspected. For every requested
session the seed records:

- expected eligible identities;
- observed expected identities;
- missing eligible identities;
- expected but absent ineligible identities; and
- source rows outside the expected active listing set.

Missing strategy-eligible identities and unexplained extras are refusals. Exact
named exceptions, if ever introduced, live in a reviewed constant with reason
and bounded identity/session scope; there is no ratio waiver. Existing aggregate
row/domain checks remain secondary diagnostics rather than completeness proof.
Coverage evidence is persisted at candidate-run/session grain and becomes
meaningful only with the publication that owns the run.

### Daily decision boundary

`feed-daily` accepts optional `--through`. Without it, the command resolves the
latest fully closed XNYS session from the pinned exchange calendar. An explicit
value must be a valid XNYS session and no later than the latest fully closed
session. The resolved session is printed before database mutation and is retained
as the ingest run/publication boundary. Container UTC rollover is never an
input.

### Post-seed closure

After the seed publication and before its mutation watermark is treated as
operational authority, the loader performs a complete current-source overlap
reconciliation across the published SEP horizon. The proof compares normalized
keys and strategy-critical values partition by partition. Failure leaves the
corpus published as historical evidence but does not earn the operational CDC
cursor/readiness state.

### Bounded ACTIONS reconciliation

The complete ACTIONS export is decoded incrementally into a PostgreSQL candidate
relation keyed by exact `source_row_id`. SQL set operations derive PRESENT,
REMOVED, changed dates, counts, and source evidence against
`sentinel_active_actions`. The Python process holds only a fixed-size insertion
batch and bounded result sets of affected dates; it never holds the complete
export, current identity map, prior identity map, and observation list
simultaneously. Publication lifecycle, negative-space semantics, source-row
siblings, replay semantics, retry recovery, and evidence fields are unchanged.

The reviewed test includes a structural assertion against whole-export
`list[dict]` materialization and an RSS measurement using the retained ACTIONS
fixture. The documented ceiling is measured peak RSS plus explicit headroom,
not a container-size workaround.

## Implementation boundaries

Expected production files:

- `sentinel/feed/source_validation.py` — reusable envelope, duplicate-key, and
  TICKERS-model validation;
- `sentinel/feed/authority.py`, `coherence.py`, `maintenance.py`,
  `snapshot_export.py`, `ingest.py`, and `ingest_impl.py` — membrane wiring,
  exact seed coverage, post-seed reconciliation, and bounded ACTIONS flow;
- `sentinel/feed/universe_projection.py` and `universe.py` — explicit rebuild
  generation precedence and exact pre-publication assertion;
- `sentinel/feed/schema.py`, `runtime_schema.py`, and `store.py` — candidate,
  evidence, and uniqueness relations plus streaming writers;
- `sentinel/__main__.py` — XNYS-resolved manual daily boundary; and
- deployment/certification documentation for the measured memory envelope and
  new operator-visible `--through` behavior.

No fallback accepts a weaker proof. An unavailable calendar, malformed source
row, conflicting duplicate, missing eligible listing, stale watermark, or
projection mismatch is a refusal.

## Verification plan

Dedicated adversarial regressions cover all issue falsifiers:

1. an older-dated identity rebuild replaces membership and corrected listing
   bounds; a fault after replacement but before publication rolls everything
   back;
2. out-of-window SEP/SFP dates, non-sessions, malformed dates, out-of-window CDC
   timestamps, and future seed watermarks all refuse before fingerprint/stage;
3. a stable partial seed missing one strategy-eligible ticker refuses while
   absent ineligible listings are accounted explicitly;
4. conflicting SEP/SFP/TICKERS duplicates, reversed intervals, ticker reuse
   overlap, and invalid listing state refuse; exact duplicates follow the
   documented collapse rule; ACTIONS siblings remain distinct;
5. at 17:30 America/Los_Angeles after UTC has advanced, daily resolution still
   chooses the latest fully closed XNYS session; future and non-session values
   refuse before mutation;
6. seed cannot earn the CDC watermark until complete overlap reconciliation
   succeeds; and
7. full ACTIONS reconciliation retains negative-space/source-row semantics while
   staying inside the measured memory ceiling.

Targeted suites are followed by the full Sentinel safety/financial CI matrix.
The PR remains unmergeable until those checks are green and the issue #235 memory
acceptance evidence is attached.