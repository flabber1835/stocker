# Strict-PIT certification runbook

This is the entry point for continuing strict-PIT certification on branch
`research/backtester`.

## Current certification target

- Production strategy source: `887f479b15ad861313da666ad698034d3847121c`
- Diagnostic warmup: `2006-01-03` through `2006-07-28`
- Diagnostic measurement: `2006-07-31` through `2007-12-31`
- Final diagnostic canonical dataset hash:
  `08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6`
- Dataset status: `PASS`
- Full 20-year job: deliberately disabled pending the completed diagnostic
  strategy-boundary audit
- Full-window PIT construction and the research-only 20-year replay are
  separate workflows. The replay starts only from a branch-pinned certified
  package.

The canonical dataset contains 3,151,110 observations, 7,301 securities, 502
sessions, 10,835 metadata-timeline rows, 22,674 action rows, and 952 terminal
rows. Its unresolved economically relevant corporate-action count is zero.

Research security-type coverage remains fail-closed and explicit:

- 454,628 candidate observations
- 338,920 evidence-classified common equity observations
- 115,708 unknown/ineligible observations
- 111,689 unknown observations without a strict-prior CIK
- 114,374 without strict-prior positive security-type evidence
- 1,334 with strict-prior positive evidence and a CIK mismatch

## Retained-research review-basis correction

The frozen production implementation records a position's age-119 review
basis from the split-adjusted execution-session open.  The retained research
source instead initialized that basis from the execution session's close and
then overwrote it again while initializing the episode peak.  That was an
implementation defect, not a strategy rule difference.

The backtester research wrapper now corrects this retained-source seam before
execution: the fill records the split-adjusted execution open as the immutable
review basis, while the entry-session close initializes only the episode peak.
The raw execution open remains the accounting fill price.  Regression guards
fail if either source seam moves or if an entry-close overwrite reappears.

## Architecture

```text
hash-pinned raw historical authorities
                 |
                 v
one canonical PIT reconstruction builder
                 |
                 v
immutable GHCR package + branch pointer
                 |
       +---------+---------+
       |                   |
       v                   v
retained research    pinned production
strategy mechanics   strategy mechanics
```

The complete schema and field-by-field causal authority rules are in
[`CANONICAL_PIT_DATASET_DESIGN.md`](CANONICAL_PIT_DATASET_DESIGN.md).

## Repository inventory

The branch contains everything required to reproduce the diagnostic:

- builder and validating loader: `backtester/canonical_pit_dataset.py`
- orchestration and equality gates: `backtester/run_certification_parallel_20y.py`
- research consumer: `backtester/run_research_strict_pit_certification.py`
- production consumer: `backtester/run_production_strict_pit_certification.py`
- workflow: `.github/workflows/backtester-strict-pit-20y.yml`
- tests: `tests/backtester/test_canonical_pit_dataset.py`
- raw source manifests and PIT extracts: `PIT input data/`
- SEC CIK/SIC evidence: `research/sentinel-fastgate/pit-evidence/`
- frozen split and terminal evidence: `backtester/data/`
- hash-pinned historical SEP/SFP sources: `sharadar/`

The 139 MB canonical diagnostic artifact is generated deterministically. The
full-window dataset is published once as a content-addressed GitHub Container
Registry package. A branch-owned pointer pins its package digest and canonical
dataset hash. Replay workflows pull by digest and validate every member before
strategy execution. An Actions artifact is retained as redundant build
evidence, not as the durable input authority.

No required certification input may exist only in `/tmp`, a local workspace,
or an uncommitted file.

## Diagnostic split dispositions

The reconciliation gate remains active. The three Run #18 blockers now have
content-addressed evidence sidecars:

| Event | Canonical multiplier | Disposition |
|---|---:|---|
| AAWW 2006-04-03 | 1.0 | same-session tape is a no-split witness |
| MBCRQ 2006-06-20 | 3.0 | announced 3-for-1; derived witness used a stale zero-volume price |
| ETELY 2007-09-04 | 1.0 | underlying reverse split offset by the depositary-ratio change |

SIM and SCEIQ retain their previously frozen adjudications. A missing,
conflicting, or hash-invalid adjudication makes the canonical build fail.

## Reproduce locally

The production checkout must be a clean detached checkout of the pinned SHA.

```bash
python backtester/canonical_pit_dataset.py build \
  --output backtester-results/canonical-pit-2006-2007 \
  --warmup-start 2006-01-03 \
  --measurement-start 2006-07-31 \
  --end 2007-12-31

python backtester/canonical_pit_dataset.py validate \
  --dataset backtester-results/canonical-pit-2006-2007

BACKTESTER_MAIN_SHA=887f479b15ad861313da666ad698034d3847121c \
python backtester/run_certification_parallel_20y.py \
  --end-session 2007-12-31 \
  --canonical-dataset backtester-results/canonical-pit-2006-2007 \
  --output-root backtester-results/strict-pit-2006-2007 \
  --spy-factors 'PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' \
  --lab-root . \
  --main-root main-src
```

Warmup output must say `WARMUP` and `CAGR=N/A`. Measurement output prints date,
research cumulative CAGR, production cumulative CAGR, and SPY cumulative CAGR
at calendar-quarter boundaries.

## Run in GitHub Actions

Open [Backtester - canonical PIT certification](https://github.com/flabber1835/stocker/actions/workflows/backtester-strict-pit-20y.yml),
select **Run workflow**, and choose `research/backtester`.

The workflow currently runs only the bounded diagnostic. It builds and uploads
the canonical artifact and verifies:

1. dataset status is `PASS`;
2. unresolved corporate-action count is zero;
3. both summaries record the same dataset hash;
4. both roles copy byte-identical per-session input hashes;
5. the first exact strategy divergence is recorded across universe, ranking,
   positions, Wealth Core equity, breadth, target, LD-RC state, allocation, and
   NAV.

### Build and store the 20-year canonical dataset

Open **Backtester - build and store canonical PIT 20-year dataset**, select
**Run workflow**, and choose `research/backtester`.

An audited automation may also update
`backtester/data/canonical-pit-20y-build-request.json`; that path is the only
push trigger for this expensive maintenance workflow.

This dataset-maintenance workflow performs no economic replay. It has a
six-hour attempt limit and automatically retries on a fresh GitHub runner after
an interrupted attempt. A successful attempt:

1. validates the canonical manifest and every member hash;
2. uploads redundant Actions evidence;
3. publishes the finished dataset to GHCR;
4. resolves the immutable GHCR digest;
5. commits `backtester/data/canonical-pit-20y.json` to
   `research/backtester` with the dataset hash, package digest, source run,
   reconstruction SHA, date window, and manifest hash.

The pointer commit is the admission event. A replay cannot consume an
unpublished run directory, a package tag, or a partially built dataset.

### Research-only 20-year replay

Open [Backtester - research-only canonical PIT 20-year replay](https://github.com/flabber1835/stocker/actions/workflows/backtester-research-only-20y.yml),
select **Run workflow**, and choose `research/backtester`.

This separate workflow covers warmup `2006-01-03` through `2006-07-28` and the
20-year measurement window `2006-07-31` through `2026-07-31`. It reads
`backtester/data/canonical-pit-20y.json`, pulls that exact GHCR digest, validates
the canonical dataset and declared hash, and then starts retained research. It
contains no PIT reconstruction step and does not check out the raw historical
authorities.

During warmup it reports `CAGR=N/A`; after measurement begins it prints paired
research and SPY cumulative CAGR records at each calendar-quarter boundary.
The completed replay artifact contains the pointer, canonical manifest,
research bundle, and replay log. This research-only job does not certify
production/research equivalence and does not enable the disabled 20-year
dual-engine certification job.

SPY path equivalence is checked after both outputs are rebased to the first
measurement session. Production retains the canonical warmup-based level while
research stores the same path rebased to `1.0`; different anchors are not an
economic divergence. Session axes must match exactly, every level must be
finite and positive, and the normalized paths must agree within `1e-10`.

## Promotion gate for the 20-year run

Do not enable the full job until the bounded diagnostic has completed and its
result is committed to this runbook. Required acceptance evidence:

- canonical build and integrity validation pass;
- research and production record the same dataset hash;
- per-session canonical hashes are identical;
- quarterly output is complete and warmup is labelled correctly;
- the first strategy divergence is identified and understood;
- no unresolved reconstruction blocker remains;
- every code, evidence, manifest, and raw input needed by Actions is present on
  `research/backtester` with a clean Git status.

After those conditions pass, extend the canonical dataset window first, record
its new hash, then enable the full workflow job. A 20-year replay must consume
that single extended artifact; neither engine may regain raw reconstruction
authority.

## Files that must never become historical authority

Current Sharadar `TICKERS` metadata is excluded from historical identity,
issuer, security type, listing, exchange, and sector decisions. Unknown facts
remain explicit and fail closed.
