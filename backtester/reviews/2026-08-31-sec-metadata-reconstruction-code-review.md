# SEC historical-metadata reconstruction code review

Date: 2026-08-31

## Scope

Reviewed repository head:

- Branch: `research/enrich-pit-2007-2026-metadata`
- Source commit: `0abb84d2327c4ae6353b8c3aa57ad532794d0a6f`
- 2006 workflow run: `33451687127`
- 2007-2026 workflow run: `33451712033`
- Candidate artifact: `metadata-candidates-2007-2026-0abb84d2327c4ae6353b8c3aa57ad532794d0a6f`
- Candidate artifact ID: `9780165601`
- Candidate artifact ZIP SHA-256: `783670cfeeb08a609da196b10fecd2338b7586dcbe54efa9188eb95718641697`

Reviewed the candidate builder, yearly evidence harvester, polite SEC transport wrapper, 2006 and 2007-2026 workflows, merge utility, canonical PIT issuer authority, retained SEC evidence, and current tests.

## Verdict

**NO-GO. Do not accept the current runs or redeploy this design with incremental patches.**

The current pipeline has multiple independent correctness, completeness, durability, and feasibility defects. A successful GitHub Actions conclusion would not establish that the resulting evidence is complete or suitable for rebuilding the canonical PIT dataset.

No strategy code was reviewed or changed in this decision. The defects are in historical metadata reconstruction and its evidence harness.

## P0 blockers

### P0-1 — `issuer_id` is being corrupted into bogus CIKs

The canonical dataset intentionally represents issuer authority as either:

- `SEC_CIK:<cik>` when a strict-prior CIK is known; or
- `SEC_UNKNOWN:<security_id>` when it is unknown.

The candidate builder passes the complete `issuer_id` string to `norm_cik()`. That normalizer removes every non-digit character and zero-fills short values. It does not reject values longer than ten digits.

Consequently, `SEC_UNKNOWN:247195603529201713` becomes the purported CIK `247195603529201713`. The harvester then requests URLs such as:

`https://data.sec.gov/submissions/CIK247195603529201713.json`

This is the exact malformed identifier visible in the live 2006 run.

I authenticated and inspected the candidate artifact produced by run `33451712033`. Across the 2007-2026 candidate shards:

- candidate episode rows: **77,196**
- valid CIK values of at most ten digits: **26,560**
- invalid values longer than ten digits: **53,737**
- rows containing only invalid values: **50,638**
- rows containing only valid CIKs: **23,459**
- rows containing both valid and invalid values: **3,099**
- invalid values equal to the row's `security_id`: **53,737**

The discovery fallback runs only when the CIK set is empty. A bogus security ID makes that set non-empty, so the fallback is skipped for most affected rows.

Required correction:

1. Parse `SEC_CIK:` explicitly.
2. Treat `SEC_UNKNOWN:` as no issuer evidence.
3. Reject every CIK that is non-numeric, zero, or longer than ten digits.
4. Rebuild all candidate shards and prove that no `security_id` appears in a CIK field.

### P0-2 — The 2006 job cannot finish within its configured timeout

The 2006 shard contains 6,722 tickers. The current polite transport enforces a minimum four-second interval per successful or attempted SEC request.

The theoretical lower bound for one request per ticker is:

`6,722 × 4 seconds = 26,888 seconds = 7.47 hours`

The workflow timeout is six hours. Real work requires a submissions request plus selected filing requests for many tickers, as well as retries and cooldowns. The current job is therefore infeasible even after the malformed-CIK defect is corrected.

### P0-3 — Calendar-year network sharding duplicates the same SEC corpus

Each yearly worker reads a four-year filing window. Adjacent yearly workers request the same submissions histories and many of the same filings. The cache is process-local and discarded at the end of each job.

This design multiplies SEC traffic, increases throttling risk, wastes GitHub runtime, and creates duplicate source artifacts.

Network acquisition must be partitioned by unique valid CIK/accession source objects. Calendar-year PIT timelines should be derived offline from the shared authenticated source corpus.

### P0-4 — The 2006 workflow's log pipeline is guaranteed to fail

The 2006 workflow pipes output to:

`tee "${OUT}/reconstruction.log"`

It does not create `${OUT}` before starting the pipeline. The live log confirms `tee: ... No such file or directory`.

The shell uses `set -euo pipefail`. Even if Python completes, the failed `tee` process makes the step fail.

### P0-5 — Partial work is discarded on failure, cancellation, or timeout

Evidence and logs are uploaded only after a successful harvest step. The HTTP cache and source bytes remain on the ephemeral runner while harvesting. A timeout, process failure, or cancellation loses completed work.

Every bounded shard requires:

- periodic durable checkpoints;
- `if: always()` upload of logs, failure state, and completed source objects;
- content-addressed resume support;
- exact checkpoint identity and hash verification before continuation.

### P0-6 — The polite workflow has no final merge or admission gate

The original parallel workflow included a merge job. The current polite 2007-2026 workflow ends after per-year artifact upload. It does not:

- merge all yearly evidence;
- include 2006;
- prove every required year is present;
- audit cross-year conflicts;
- produce one authenticated evidence pointer;
- admit the evidence into a rebuilt metadata timeline;
- rebuild or certify an enriched canonical PIT dataset.

### P0-7 — Existing retained SEC archives are not used as the primary source

The repository already retains quarterly SEC Form 3/4/5 bulk archives from 2006 Q1 through 2026 Q2, with authenticated generated evidence. The current workflow redownloads issuer histories and filing bytes ticker by ticker.

The bulk archives must be parsed locally first. SEC web requests should cover only unresolved gaps and source types absent from the retained archives.

## P1 correctness findings

### P1-1 — Ticker-level grouping conflates distinct security episodes

Candidates are grouped by ticker. One verified CIK sets `admitted_for_ticker=True` and suppresses unresolved output for every candidate episode sharing that ticker.

Tickers are reused across issuers and can represent multiple securities or share classes. Admission and unresolved state must remain keyed by the canonical security episode, with independently proven identity intervals.

### P1-2 — Exact ticker matching does not handle vendor disambiguation suffixes

The candidate shards contain Sharadar-style suffixed tickers such as `ABI1`, `ACAS1`, and `ADI1`. In 2007 alone, 806 candidate rows end in a digit. All 806 carried only invalid observed-CIK values before independent mapping.

SEC issuer symbols generally do not contain these vendor disambiguation suffixes. Exact equality will fail unless an explicit, provenance-backed historical alias map resolves the suffix. Alias removal must fail closed on collisions.

### P1-3 — SIC evidence is order-dependent

The harvester processes filings chronologically. It accepts issuer-level SIC from a filing lacking ticker text only when an earlier processed filing has already established ticker/CIK identity.

A valid SIC filing can precede the filing that proves identity. The current one-pass logic drops that SIC permanently.

Use a two-pass join:

1. establish all historical identity evidence for the episode;
2. join issuer-level SIC evidence;
3. set `usable_after` to the later of the SIC filing date and the identity-proof date.

### P1-4 — Security-type authority is incomplete and under-specified

Security type is emitted only from ownership-form `securityTitle` values when the same filing also verifies the ticker. The implementation does not distinguish clearly among:

- the exchange-listed class;
- a derivative security;
- a reporting owner's held or transacted instrument;
- an issuer with multiple common or preferred classes.

The pipeline also lacks a reviewed parser for contemporaneous periodic-filing cover-page class descriptions. Admission rules need explicit source precedence, conflict handling, and share-class tests.

### P1-5 — Network failures can still produce `EVIDENCE_HARVEST_COMPLETE`

Network failures are retained, but the final status is always `EVIDENCE_HARVEST_COMPLETE`. A run with widespread request failures can therefore appear complete.

The status contract needs at least `PASS`, `PARTIAL`, and `FAIL`, with materiality gates tied to unresolved candidate episodes and candidate-session observations.

### P1-6 — The filing-discovery inputs are not retained as evidence

The SEC submissions JSON and historical submissions-index fragments determine which filings are selected. Their bytes and hashes are not retained in the output evidence package.

The package must retain every source object that influences source selection, including discovery files, response status, retrieval time, URL, content hash, and parser version.

### P1-7 — HTTP retry semantics waste time and obscure failure modes

The polite wrapper retries every HTTP error eight times, including permanent `404` and `410` responses. It also sleeps after the final failed attempt. The progress `requests` counter increments only after success, so it hides attempted calls and retry load.

Required behavior:

- `404`/`410`: terminal source absence, no repeated retry;
- `403`/`429`: global cooldown, honor `Retry-After`;
- `5xx` and transport interruption: bounded exponential retry;
- no delay after the final attempt;
- separate counters for attempts, successes, status classes, retries, and terminal absences.

## P2 durability, provenance, and test findings

1. Workflow path filters omit material script dependencies, so code changes may not launch the intended workflow.
2. The separate 2006 workflow plus two yearly workers creates three simultaneous SEC clients; `max-parallel: 2` is not a global request limit.
3. Artifacts expire after 90 days. The current polite flow creates no durable package and commits no content-addressed pointer.
4. Per-year evidence lacks a single required manifest binding the canonical dataset hash, candidate-shard hash, source commit, parser hashes, discovery-index hash, runtime lock, source-object Merkle/hash list, and workflow identity.
5. Existing tests cover only filing-table parsing, filing selection, and progress formatting.
6. There are no tests for malformed issuer authority, CIK validation, ticker reuse, alias collisions, evidence ordering, network status semantics, checkpoint/resume behavior, timeout feasibility, workflow directory creation, complete-year merge, or deterministic repeat hashes.

## Required replacement architecture

### Phase 1 — Local authenticated SEC corpus

1. Verify every retained quarterly Form 3/4/5 ZIP against committed checksums.
2. Parse `SUBMISSION` once for historical ticker/CIK evidence.
3. Parse transaction and holdings tables for security-title evidence keyed by accession number.
4. Retain normalized rows plus source archive/member hashes and parser identity.
5. Build candidate coverage and unresolved reports before any network request.

### Phase 2 — Bounded web fallback

1. Construct a de-duplicated list of unresolved, valid CIKs and required accession/source objects.
2. Partition by stable CIK hash shards, not calendar year.
3. Use one global request governor across all workers.
4. Persist a content-addressed cache and checkpoint after bounded batches.
5. Upload checkpoint, source bytes, and logs on success, failure, timeout, or cancellation.
6. Print exact live progress: source objects complete/total, valid CIKs complete/total, HTTP attempts by status, retained failures, and checkpoint hash.

### Phase 3 — Offline PIT timeline derivation

1. Join identity, security-type, and SIC evidence by security episode.
2. Apply `filed < decision_session` exactly.
3. Carry classifications forward only under an explicit continuity rule.
4. Fail closed on conflicts, ambiguous aliases, and unresolved episode boundaries.
5. Derive 2006-2026 yearly coverage from the common source corpus.

### Phase 4 — Merge, admission, and certification

1. Prove every required year and security episode is represented.
2. Audit cross-year and cross-source conflicts.
3. Quantify unresolved observations and their economic materiality.
4. Produce one immutable content-addressed evidence package and committed pointer.
5. Rebuild the canonical metadata timeline and canonical PIT dataset.
6. Rerun PIT integrity, causality, and production/research equivalence certification.

## Mandatory tests before another GitHub harvest

- `SEC_CIK:<cik>` parses to the exact validated CIK.
- `SEC_UNKNOWN:<security_id>` produces no CIK.
- CIKs longer than ten digits are rejected.
- Candidate artifacts contain no security IDs in CIK fields.
- Discovery fallback activates after invalid identifiers are removed.
- Ticker reuse remains separated by security episode.
- Vendor alias mapping fails closed on ambiguity and collision.
- SIC preceding identity receives the correct later `usable_after` date.
- Ownership and periodic-filing class evidence follow explicit precedence rules.
- `404`/`410`, `403`/`429`, `5xx`, transport interruption, and final retry each follow their intended policy.
- Network incompleteness cannot produce `PASS`.
- Output directories exist before logging begins.
- Logs and checkpoints upload under failure and cancellation.
- Resume rejects mismatched code, candidate, dataset, and checkpoint hashes.
- Merge fails when any year from 2006 through 2026 is missing.
- Two clean runs produce identical normalized evidence hashes.

## Decision

The current 2006 and 2007-2026 run outputs are **rejected as certification evidence**.

The next implementation must address this review as one coherent repair. It must pass the mandatory local tests and a small bounded SEC integration probe before launching the full harvest.
