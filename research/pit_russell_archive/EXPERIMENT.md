# Russell 3000 PIT archive reconstruction experiment

Status: **RESEARCH ONLY — NOT AUTHORITY FOR PRODUCTION OR BACKTEST CERTIFICATION**

Branch: `research/pit-russell-archive-reconstruction`

Base revision: `main@8b42b1e109b2ff3cb6832f92757a45ced0df4c60`

## Objective

Determine whether the historical investable-universe problem can be reduced to a small, auditable set of point-in-time Russell 3000 annual membership snapshots, recovered from contemporaneous public artifacts, especially the Internet Archive Wayback Machine.

This experiment must not modify production strategy code, Sentinel execution code, the canonical backtester, or an existing certified corpus.

## Why this experiment exists

The difficult part of the current historical reconstruction is not daily price data. The hard part is reconstructing historical security identity and metadata with enough certainty to support a full point-in-time universe across roughly twenty years.

A narrower strategy contract may remove much of that dependency. If eligibility is defined as membership in the Russell 3000 on a causally available annual membership snapshot, the index provider supplies the investability/security-type decision. The strategy can then continue to apply observed price/liquidity requirements itself.

The candidate simplified data contract is:

- dated Russell 3000 membership;
- a stable security identity sufficient to prevent ticker reuse from joining unrelated securities;
- observed session/open/close/volume;
- observed split and dividend events needed by the price-domain contract;
- SPY data used by Sentinel;
- BIL data if the defensive sleeve remains enabled;
- an explicit conservative rule for unresolved terminal positions.

This is a research hypothesis. It is not an adopted strategy change.

## Proposed universe semantics to test

One annual final Russell 3000 membership list becomes the eligible universe only after its publication/effective-time contract is established. That universe remains frozen until the next accepted annual list.

Daily Wealth Core eligibility would still require its own market-data checks, including sufficient continuous price history, minimum price, ADV20, and signal-day dollar volume.

Annual freezing is deliberate. It makes the historical universe a finite set of dated facts and avoids inventing intrayear membership changes that cannot be proven.

## PIT rules

1. No future constituent list may be used to infer an earlier universe.
2. A Wayback capture timestamp is provenance evidence, not automatically the original publication timestamp.
3. If a capture occurs after an index effective date, the source document or independent contemporaneous evidence must establish when the underlying list was published/known.
4. Current membership must never be backfilled historically.
5. Ticker continuity alone must never join two securities when identity is uncertain.
6. Missing open, close, or volume observations must not be interpolated or fabricated.
7. Split events must not be guessed unless a separately defined, validated inference rule is adopted and sensitivity-tested.
8. A held security may not disappear economically. Unresolved terminal treatment must be explicit and conservative.
9. Every recovered source must retain URL, capture timestamp, HTTP status, content length, and SHA-256.
10. Raw third-party copyrighted constituent files are not committed by this experiment. The workflow preserves provenance, hashes, counts, and diagnostic metadata. Raw downloads remain ephemeral unless a later data-rights decision explicitly permits retention.

## Evidence grades

### Grade A — original/contemporaneous authoritative artifact

An original Russell/FTSE Russell membership artifact or a Wayback capture of the original publisher endpoint, with sufficient evidence to establish the list date and identity.

### Grade B — contemporaneous preserved copy with corroboration

A contemporaneous copy/mirror whose contents can be corroborated against independent dated evidence and whose provenance is sufficiently strong for research reconstruction.

### Grade C — deterministic reconstruction

A universe reconstructed from an accepted prior membership list plus dated authoritative additions/deletions. Grade C is not automatically equivalent to Grade A. It must be validated on holdout years where the true final list is known.

### Unresolved

Evidence that cannot establish membership without using future information or ambiguous ticker identity remains unresolved. The conservative strategy treatment is exclusion, not silent imputation.

## Experiments

### Experiment 1 — Wayback endpoint discovery

Query Internet Archive CDX for historical captures of known Russell 3000 membership-list URL patterns for 2005–2014, with primary focus on 2006, 2007, 2008, and 2013.

For every capture record retain:

- requested source URL;
- archived original URL;
- Wayback timestamp;
- status code;
- reported MIME type;
- Wayback digest;
- reported length.

### Experiment 2 — deterministic capture download

For candidate captures around the annual June/July reconstitution window, download unique archived representations using the Wayback raw (`id_`) form.

Record only derived evidence in the persisted experiment output:

- response URL;
- response content type;
- byte length;
- SHA-256;
- whether the payload has a PDF signature.

The raw constituent PDF is not uploaded as a repository artifact by this workflow.

### Experiment 3 — holdout reconstruction validation

Once annual membership extraction is implemented, reconstruct one or more later years using only the evidence that would have been available under the proposed reconstruction method. Compare the reconstructed ticker/security set to an independently recovered complete final list for that same year.

Required metrics:

- exact intersection count;
- false inclusions;
- false exclusions;
- Jaccard similarity;
- affected securities that would actually pass Wealth Core's 127-session and liquidity gates;
- affected selection/portfolio-days in replay.

The last two metrics are economically more important than raw constituent-set error.

### Experiment 4 — uncertainty bounds

For unresolved membership/identity/terminal cases, run conservative and best-supported variants and measure the resulting spread in CAGR, maximum drawdown, turnover, and affected portfolio-days.

No reconstructed corpus should receive the normal `PIT CERTIFIED` result until its evidence contract is explicitly approved and incorporated into certification semantics.

## Initial web observations motivating the experiment

These observations are leads to test, not accepted corpus facts:

- A stable historical URL pattern was publicly referenced for a Russell 3000 membership PDF: `http://www.russell.com/indexes/documents/Membership/Russell3000_Membership_List.pdf`.
- A complete Russell 3000 list dated June 26, 2009 has been preserved on the public web.
- Public copies of original Russell membership PDFs have been located for many later years.
- A contemporaneous 2006 Russell 3000 additions document has been located.
- Contemporary 2007/2008 notices establish annual reconstitution publication/update timing.

The runner experiment exists to test whether the original Russell endpoint itself is recoverable through Wayback and to quantify the gaps.

## Success criteria

The approach is promising if all of the following hold:

1. The original Russell membership endpoint has usable archived captures for most target years, or missing years can be reconstructed from authoritative dated deltas.
2. Holdout reconstruction error is very small and, critically, causes negligible changes after Wealth Core's own history/liquidity gates.
3. Historical security identity can be kept fail-closed without widespread ticker ambiguity.
4. Terminal uncertainty can be bounded conservatively with small measured economic impact.
5. No reconstructed fact requires knowledge that became available after the strategy decision date.

## Failure criteria

Reject or materially revise this approach if any of these occur:

- recovered annual lists show large unexplained gaps;
- reconstruction requires current/future constituent information;
- ticker reuse cannot be separated reliably for a meaningful fraction of candidates;
- holdout reconstruction materially changes selections or performance;
- unresolved terminal events materially dominate results;
- archive availability is too inconsistent to make provenance reproducible.

## Isolation contract

Files created for this experiment live only under:

- `research/pit_russell_archive/`
- `tools/pit_russell_archive_probe.py`
- `tests/scripts/test_pit_russell_archive_probe.py`
- `.github/workflows/pit-russell-archive-experiment.yml`

The experiment must not import production databases, publish canonical PIT artifacts, alter production/backtester configuration, or write to production storage.

## Decision log

### 2026-09-03 — isolate on a dedicated branch

Decision: perform the experiment on `research/pit-russell-archive-reconstruction`, based exactly on current `main`.

Rationale: archive-reconstruction research should be independently discardable and must not change either the production strategy or the existing backtester while feasibility is unknown.

### 2026-09-03 — test annual Russell membership as eligibility authority

Decision: test whether annual PIT Russell 3000 membership can replace reconstructed historical `category`/broad-universe eligibility metadata.

Rationale: Russell membership already embodies the index provider's security eligibility rules. If sufficient historical membership evidence exists, separately reconstructing historical common-stock category for the entire U.S. market is unnecessary for this strategy variant.

### 2026-09-03 — preserve observed market prices as hard facts

Decision: do not interpolate missing open/close/volume data as part of this approach.

Rationale: these fields directly affect ranking, volatility, stops, fills, NAV, and liquidity eligibility. Fabricating them can create unbounded trading bias.

### 2026-09-03 — treat archive timestamp and publication timestamp separately

Decision: Wayback capture time is evidence of preservation, not proof that the source became public at that exact time.

Rationale: PIT certification must establish when information was knowable. A later archive capture can preserve an earlier published document, but the earlier publication must be evidenced independently.

### 2026-09-03 — do not persist raw constituent PDFs in GitHub artifacts by default

Decision: persist manifests/hashes/diagnostics only.

Rationale: the experiment needs reproducible provenance and integrity evidence; it does not need to republish third-party copyrighted constituent documents.
