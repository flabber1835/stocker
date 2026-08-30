# Canonical PIT dataset design

**Branch:** `research/backtester`  
**Scope:** certification input construction and consumption  
**Initial window:** 2006-01-03 through 2007-12-31  
**Measurement begins:** 2006-07-31

## Decision

Historical reconstruction is a dataset-maintenance responsibility. A dedicated
builder reads the frozen raw authorities, resolves every causal fact once, and
emits one immutable, content-addressed dataset. The retained research engine and
the pinned production engine both consume that artifact through the same
validated loader.

An economic replay may validate and read the artifact. It may not read the raw
SEC, Sharadar ACTIONS, Sharadar SEP, Sharadar TICKERS, terminal-adjudication, or
cash-authority files to reconstruct an economically active historical fact.

```text
frozen raw authorities
        |
        v
canonical PIT builder (dataset maintenance)
        |
        v
content-addressed canonical dataset
        |
        +--------------------+
        |                    |
        v                    v
retained research       pinned production
strategy mechanics      strategy mechanics
```

The initial artifact is bounded to the diagnostic window. Extending its end
date is a new dataset-maintenance operation and produces a new dataset hash.

## Previous duplicated ownership

The strict research wrapper generated source that independently scanned SEP and
CIK evidence to create security episodes. It separately loaded SEC security-type
evidence, SEC SIC evidence, ACTIONS, SEP price domains, terminal actions, and the
cash series.

The strict production wrapper independently built security episodes and
issuer/security-type maps. Its feed runner separately parsed ACTIONS,
normalised SEP price and volume domains, resolved splits and terminals, built
the SIC-to-FF12 map, and completed the defensive cash series.

Those paths could use the same raw files while presenting different reconstructed
facts to the two strategies. Metadata-authority descriptions and source hashes
did not prove input equality.

## Artifact layout

```text
canonical-pit/<dataset-id>/
  observations-2006.csv.gz
  observations-2007.csv.gz
  metadata-timeline.csv.gz
  actions.csv.gz
  terminal-events.csv.gz
  cash.csv.gz
  benchmark.csv.gz
  session-hashes.csv
  manifest.json
  SHA256SUMS.txt
```

CSV column order, row order, UTF-8 encoding, newline spelling, numeric spelling,
and deterministic gzip metadata are part of the schema. Observation partitions
are ordered by `(session, ticker, security_id)`. Other tables state their sort
keys in the manifest.

`dataset_hash` is SHA-256 over the ordered sequence of each data member's
relative path, SHA-256, and byte length. The manifest contains that value and is
excluded from its own digest. `SHA256SUMS.txt` covers the completed artifact,
including the manifest.

## Canonical schema

### Observations

One row is one historically observed listed-instrument tape row.

| Field | Meaning |
|---|---|
| `session` | Trading session, `YYYY-MM-DD` |
| `security_id` | Causal security-episode identifier |
| `ticker` | Ticker printed by historical SEP on that session |
| `issuer_id` | `SEC_CIK:<cik>` or `SEC_UNKNOWN:<security_id>` |
| `issuer_source` | Strict-prior SEC CIK or explicit singleton policy |
| `security_type` | `common`, `non_common`, or `unknown` |
| `security_type_source` | Exact-session manual evidence, strict-prior SEC positive evidence, or unknown |
| `security_type_eligible` | `1` only for evidence-supported common equity |
| `sic` | Strict-prior SEC SIC, blank when unavailable |
| `ff12` | Frozen FF12 label; unknown is a security singleton label |
| `sector_source` | Strict-prior SEC CIK/SIC rule or explicit singleton policy |
| `listing_active` | `1`; row existence is the listing witness |
| `listing_first_session` | First observed historical SEP session for the causal security episode |
| `exchange` | Blank in schema 1 because no causal authority is admitted |
| `exchange_authoritative` | `0` in schema 1 |
| `raw_open` | Historical as-traded open |
| `raw_close` | Historical as-traded close (`SEP.closeunadj`) |
| `signal_close` | Split-adjusted, dividend-unadjusted close (`SEP.close`) |
| `reported_volume` | Vendor split-adjusted SEP volume |
| `raw_compatible_volume` | Volume converted to the as-traded share domain |
| `split_ratio` | Canonical share multiplier effective on the row |
| `dividend_per_share` | Canonical dividend on the as-traded share basis |
| `tradeable` | Causal tape-level tradeability fact |
| `metadata_admitted` | Fail-closed conjunction of required reconstructed metadata facts |
| `identity_source` | Historical SEP plus strict-prior CIK-change episode rule |

`metadata_admitted` does not encode momentum, price, liquidity, ranking, slot,
or portfolio rules. Each strategy computes those mechanics from the same
canonical observations.

### Metadata timeline

`metadata-timeline.csv.gz` is the de-duplicated causal timeline of the identity,
issuer, security-type, SIC/FF12, and metadata-admission fields in observations.
It is keyed by `(effective_session, security_id, ticker)`. Consumers use it for
as-of metadata lookup without reopening an upstream authority.

### Corporate actions

| Field | Meaning |
|---|---|
| `effective_session` | First replay session on or after the causal action date |
| `security_id` | Canonical identity effective for the event |
| `ticker` | Historical action ticker |
| `action` | Canonical action kind |
| `vendor_value` | Frozen source value |
| `canonical_value` | Value presented to both engines |
| `disposition` | Reconciliation result |
| `sep_derived_value` | Independent SEP price-domain witness where applicable |
| `known_by` | Latest permissible evidence date used by an adjudication |
| `authority` | Causal source rule |
| `evidence_hash` | Frozen adjudication/evidence identity where applicable |

Every split conflict stays visible. Certification requires zero unresolved
economically relevant actions. An evidence-backed no-event disposition carries
`canonical_value=1.0`; the conflicting vendor and SEP witnesses remain present.

### Terminal events

The terminal table contains the fully coalesced event consumed by both engines:
effective session, security ID, ticker, terminal kind, disposition, cash terms,
delivered-security terms, reference, authority, and evidence hash. Raw terminal
rows are provenance, not replay inputs. A source event that states termination
without consideration remains explicitly incomplete and reaches each strategy's
settlement mechanics in the same form; a coalescing conflict is a dataset
certification blocker.

### Cash and benchmark

`cash.csv.gz` contains session, gap factor, intraday factor, close-to-close
factor, and source. `benchmark.csv.gz` contains the canonical SPY session axis
and close-to-close factor. Both engines use these rows directly.

### Session hashes

For every session, `session-hashes.csv` records SHA-256 over the ordered
canonical observation rows plus same-session action, terminal, cash, and
benchmark rows. Each engine copies that hash into its daily evidence. This
proves identical input population and values at the strategy boundary.

## Field authorities and causal rules

| Fact | Authority and exact rule |
|---|---|
| Session axis | Frozen SPY factor observations in the requested range |
| Security identity | Historical SEP ticker observations; a new episode starts on the first observed session strictly after a filed SEC CIK change |
| Ticker | Historical SEP row on the simulated session |
| Issuer | Latest SEC CIK whose filing date is strictly earlier than the session; unknown becomes a security singleton |
| Security type | Exact-session evidence-backed manual admission first, then SEC/EDGAR positive common-equity evidence filed strictly earlier than the session and matching the strict-prior CIK; otherwise explicit unknown/ineligible |
| SIC and FF12 | Strict-prior CIK, then latest SIC submission strictly earlier than the session, then frozen FF12 definition; missing evidence becomes a security singleton group |
| Listing existence | Presence on the historical SEP tape, with causal terminal evidence represented separately; no future last-price date |
| Exchange | Blank and economically inert until a causal authority is admitted |
| Raw prices | Frozen historical SEP `closeunadj`; raw open is `open * closeunadj / close`, rounded to production precision |
| Signal price | Frozen historical SEP split-adjusted, dividend-unadjusted `close` |
| Volume | Reported SEP volume and the shared dollar-liquidity-preserving raw-domain conversion |
| Splits | PIT ACTIONS `split` rows plus SEP price-domain witness plus frozen primary-source adjudications; `adrratiosplit` is provenance only |
| Dividends | PIT ACTIONS dividend rows converted to the historical raw-share domain using the same-session price-domain factor |
| Terminal events | PIT ACTIONS terminal rows coalesced with frozen evidence-backed terminal terms |
| Defensive cash | Actual BIL factors when causally available; previous completed calendar month's frozen GS3M with calendar-day accrual otherwise |
| Eligibility metadata | Evidence-supported common equity, active observed listing, and resolved required metadata; unknown type is ineligible |

Current Sharadar TICKERS fields have no authority in this contract.

## Builder and consumer gates

The builder:

1. verifies every raw input against its frozen manifest or checksum;
2. applies the field-authority rules in deterministic order;
3. emits deterministic tables and per-session hashes;
4. records source, adjudication, and reconstruction-code hashes;
5. certifies row/session/security counts and unresolved counts;
6. marks the artifact `FAIL` when any economically relevant action remains unresolved.

The loader rejects a missing member, member hash mismatch, dataset-hash mismatch,
schema mismatch, range mismatch, non-PASS status, unresolved action count, or
unexpected row order.

Research and production receive the same validated dataset path. Their wrappers
must not import reconstruction helpers or open raw authority paths. Static tests
enforce this ownership boundary.

## Dataset manifest

The manifest records at least:

- schema and dataset ID;
- reconstruction code SHA and reconstruction module SHA-256;
- source file hashes and byte lengths;
- frozen evidence and adjudication hashes;
- warm-up, measurement, and end dates;
- row, security, and session counts;
- unresolved corporate-action count;
- unknown security-type and issuer observation counts;
- member hashes and deterministic aggregate dataset hash;
- certification status and blocker details.

The production SHA and retained-research source SHA remain run provenance. They
do not alter dataset identity.

## Diagnostic acceptance sequence

1. Build and inspect the 2006-01-03 through 2007-12-31 artifact.
2. Keep AAWW 2006-04-03, MBCRQ 2006-06-20, and ETELY 2007-09-04 as blockers
   until immutable primary-source adjudications validate their economics.
3. Require a PASS dataset manifest before economic replay.
4. Run both engines concurrently from the same dataset path.
5. Require the same dataset hash and session hash on every comparable session.
6. Locate the first strategy divergence in eligible universe, rankings,
   selections, Wealth Core equity, breadth, native target, LD-RC state,
   allocation, and NAV.
7. Keep the full 20-year workflow disabled until this bounded sequence passes.
