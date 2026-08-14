# NAS deployment remediation

This record tracks defects discovered during the first deployment of merged
Sentinel main (`f65e9e34bc204250e4e5a99b61dfdc099e0392ef`) to a Synology NAS.
It is intentionally separate from the deployment checkout: production keeps
running reviewed images while fixes and falsifiers accumulate in this draft PR.

## Review-fix status

The seven deployment remediations below are implemented. Review then found two
additional certification defects: event-day admission floors were being used as
a proxy for full-history split irrelevance, and anomaly rows had no publication
lifecycle. Both review fixes and their PostgreSQL falsifiers are now
implemented. The PR remains draft until the final Linux safety workflow passes
on the pushed head. No network ingestion, broker action, credential change, or
deployment is part of this remediation branch.

## Confirmed findings

### 1. Sharadar API key appears in HTTP request logs

**Observed:** `feed-daily` emitted `httpx` INFO request URLs containing the
literal `api_key` query parameter.

**Impact:** terminal capture, supervisor logs, copied diagnostics, and support
transcripts can disclose the data-vendor credential.

**Acceptance:** ordinary and verbose execution, retry paths, and terminal HTTP
errors never render secret query values. A falsifier uses a sentinel secret and
asserts that it is absent from stdout, stderr, log records, and exception text.

**Resolution:** authenticated HTTP diagnostics are suppressed for the complete
request/status/exception boundary, and every propagated failure is rebuilt from
a key-free request target without exception chaining. Success, retry, 4xx, 5xx,
transport, and verbose-log falsifiers inspect all four rendering surfaces.

### 2. CPU capability detection can contradict the Docker daemon

**Observed:** the capability detector selected the canonical `cpus:` graph on
Synology, then Docker refused container creation with `NanoCPUs can not be set`
because CFS quota was unavailable.

**Impact:** the supported resolver cannot start Sentinel on the host it was
designed to support; operators must manually select the generated no-CPU graph.

**Acceptance:** an explicit, recorded force-no-CPU mode and/or an active daemon
probe selects the generated graph. Only `cpus:` is removed; `mem_limit` and
`shm_size` remain. Tests reproduce a daemon-info false positive followed by a
NanoCPUs refusal.

**Resolution:** daemon metadata is followed by a no-pull `docker create --cpus`
probe against the already-local pinned PostgreSQL image. An explicit
`SENTINEL_FORCE_NO_CPU_LIMITS=1` selects the generated graph even when metadata
or the active probe is inconclusive. The generated graph removes only `cpus:`;
the measurement artifact records `OBSERVED_NOT_BOUNDED` and cannot certify a
CPU envelope for that graph.

### 3. A verified base backup can block first schema initialization

**Observed:** `sentinel-base-backup.sh` created
`sentinel_backup_recovery_markers` before behavioral-schema initialization.
The markerless-schema classifier then refused its own recovery-marker table as
an unknown behavioral relation.

**Impact:** the safety-first sequence "backup existing corpus, then initialize
Sentinel" cannot complete without manually dropping Sentinel's own table.

**Acceptance:** the exact sequence passes on a legacy corpus, without weakening
refusal for genuinely unknown relations. Restore-marker verification remains
effective and the migration bootstrap decision remains durable.

**Resolution:** the recovery-marker table is classified as backup
infrastructure only after its relation, columns, defaults, primary-key
constraint, index, and trigger fingerprints match the table created by the
backup script exactly. Malformed marker tables and unrelated `sentinel_*`
relations retain the markerless-schema refusal.

### 4. Derived-only splits need explicit certification disposition

**Observed:** a daily ingest reported 14 price-domain split ratios for which
SHARADAR/ACTIONS had no row, including unusually large ratios.
The subsequent bounded backfill reported the same 14 tickers on the backfill's
different leading date. This demonstrates that they are adjustment-vintage seam
artifacts, not 14 corporate actions that happened on both reported dates. The
normalizer's seam guard records and suppresses such ratios, but the shared
warning incorrectly says it is "using the derived ratio".

The same backfill also found three ACTIONS/price-domain disagreements where the
two values were near exact reciprocals (approximately 30 versus 1/30, 9 versus
1/9, and 7 versus 1/7). Primary corporate-action filings confirm these were
1-for-30, 1-for-9, and 1-for-7 reverse events. Sharadar's positive ACTIONS value
therefore names the reverse-split denominator, while canonical `split_ratio`
is a post/pre **share multiplier** and must be the reciprocal. The current code
documents "no inversion" and unconditionally applies 30, 9, and 7. A position
held across a 1-for-30 event would be multiplied by 30 instead of divided by
30, a 900-fold orientation error relative to the correct resulting quantity.
This is release-blocking for paper automation, not a vendor-data caveat.

**Impact:** fallback is safer than ignoring a genuine split, but a certified
run must not hide whether an uncorroborated ratio affected an eligible or held
security.

**Acceptance:** certification retains the complete derived-only event list and
states a deterministic warning/refusal policy based on economic relevance.
Seam-suppressed artifacts are not reported as applied derived-only splits.
The ACTIONS mapping normalizes forward and reverse conventions into canonical
post/pre share multipliers and agrees with the independently derived price
domain. Ambiguous action types refuse economically relevant use. Tests cover
ordinary, seam, reciprocal, eligible, and held-security cases, including a
1-for-30 reverse event that must produce exactly 1/30 rather than 30.

**Resolution:** ACTIONS values remain raw until independent price-domain
evidence selects direct or reciprocal orientation. Noisy near-integral reverse
denominators are snapped only after that witness, so 30.003 becomes exactly
`1/30`; neither/either ambiguity applies `1.0`, writes a durable disagreement,
and blocks certification. Uncorroborated leading-window seams are recorded but
not applied and are excluded from the derived-only-applied list.

Certification renders every split in one of these explicit categories:

| Category | Application and certification policy |
|---|---|
| authoritative applied split | canonical ACTIONS multiplier at or below one; accepted |
| corroborated derived split | price evidence selects direct or reciprocal orientation; accepted |
| derived-only non-seam split | applied, but certification blocks without full-interval counterfactual equivalence evidence |
| seam artifact suppressed | not applied; certification blocks without full-interval counterfactual equivalence evidence |
| unresolved material disagreement | not applied and always blocks certification |

An event-day price, event-day liquidity, or absence from the observed book is
not such evidence. A split changes the cumulative signal series for every later
session; the security can later cross an admission floor, change rankings and
enter the book, while a wrong split can itself explain why it is absent from the
observed holdings. The current system has no full-interval counterfactual engine,
so both uncertain categories block. They may clear only if future evidence
demonstrates equivalence of eligibility, rankings, selections, holdings,
accounting and hashes under every alternate split treatment over the complete
certified interval. No event-local proxy may stand in for that proof.

### 4a. Anomaly evidence follows corpus publication

`sentinel_corpus_anomalies` is an append-only observation history, not a mutable
set of warnings. New observations carry the ingest or repair `run_id`. Rows from
an unpublished or failed run are historical candidate evidence and cannot
replace the active disposition. The publication row is the atomic activation
point: for a split economic event `(ticker, session)`, readers select only the
disposition attached to the newest published run, with pre-upgrade rows as a
legacy baseline. A corrected published corroboration or authoritative result
therefore supersedes an older disagreement/derived/seam disposition without
deleting it.

Legacy rows are never reset or inferred clean during upgrade. They retain a
NULL publication identity, are classified deterministically as the oldest
active baseline, and remain certification evidence until a newer published
observation for the same economic event exists. If legacy data contains more
than one split disposition at the same baseline, all tied rows remain visible
and any unsafe one blocks. Candidate observations participate in corpus
coherence, so a failed publication is visible as unpublished state while the
previously published disposition remains active. The corpus writer lock covers
observation writes and publication just as it covers bars, actions and repairs.

### 5. Backup validation cannot use attestation when Docker root is protected

**Observed:** an ordinary Synology administrator could use Docker but could not
`cd /volume1/@docker`. `sentinel_backup_root` failed while resolving that path
before its documented durable-target attestation could apply.

**Impact:** every supported Compose invocation requires host-root privileges
even after the operator independently proves that the USB target is a different
device.

**Acceptance:** unreadable Docker-root metadata fails closed by default, while
the explicit attestation path works without attempting to traverse the
protected directory. Tests distinguish absent, unreadable, same-device, and
independent-device targets.

**Resolution:** the lexical inside-Docker-root refusal runs before any
traversal and cannot be overridden. If Docker-root metadata is absent or
unreadable, validation fails closed unless the operator sets the documented
durable-target attestation; with attestation it does not traverse the protected
directory and still performs the PostgreSQL-UID write probe.

### 6. Production ingest reads SPY from the wrong Sharadar table

**Observed:** publishing a previously unversioned corpus with `feed-daily`, then
running an explicit two-month `feed-seed`, advanced and republished all ordinary
prices but left `sentinel_spy_total_return` at exactly zero rows. Production
ingest only fetches `SHARADAR/SEP` and extracts `ticker == "SPY"` from those
rows. SPY is an exchange-traded fund; Sharadar fund prices are in
`SHARADAR/SFP`, not the equity-prices SEP table. Synthetic tests put SPY into
SEP and therefore false-green the production source boundary.

**Impact:** a real Sharadar corpus is coherent, versioned, continuous, and
fresh but can never pass readiness. Repeating daily ingestion or reseeding any
SEP interval cannot create the mandatory 41-session SPY tail. This blocks every
fresh deployment, not only legacy upgrades.

**Acceptance:** seed and daily ingestion fetch the bounded SPY total-return
series from the production fund-price source, stamp it into the same ingest run,
and publish it atomically with the corpus version. It must not broaden the
Wealth Core equity universe to funds or rewrite unrelated bars. A
PostgreSQL-backed falsifier keeps SPY absent from SEP, serves it only from the
fund table, runs both supported ingest modes, and ends with a passing exact
41-session frontier benchmark.

**Resolution:** both seed and daily ingest request only `ticker=SPY` from
`SHARADAR/SFP`, write only `closeadj` into the dedicated total-return table,
stamp the same ingest run, and publish atomically with the corpus. Daily repair
requests the exact 41-session readiness window. SFP rows never enter SEP bars or
the equity universe; repeated seed/daily loads are idempotent.

## Deployment observations that are not yet code defects

- Existing PostgreSQL volumes do not adopt a changed Compose password. The
  operator synchronized the database role with the deployment environment.
- The deployment correctly refused an unbound account and an absent current
  execution plan.
- A verified physical base backup and post-base WAL recovery marker were
  successfully written to an independent ext4 USB target.

## Remaining operational verification

- Rotate the Sharadar key if the pre-fix HTTP log was retained or shared; code
  redaction cannot retract an already disclosed credential.
- On first NAS start, keep the pinned probe image local or explicitly set
  `SENTINEL_FORCE_NO_CPU_LIMITS=1`; an `UNKNOWN` probe intentionally retains the
  canonical limits and may fail loudly rather than silently remove a ceiling.
- Durable-target attestation is an operator claim. Verify the mount's independent
  failure domain, then rerun base-backup status and the isolated restore drill.
- Run a real bounded SFP seed/daily repair with the deployment credential and
  confirm the exact 41-session SPY frontier before preparing any paper plan.
- Existing-volume PostgreSQL credentials still require the documented role/env
  synchronization; this remediation does not mutate database credentials.

## Validation evidence

- Review-fix focused PostgreSQL selection: `144 passed` with zero skips. This
  covers active/history supersession, failed and repeated ingest behavior,
  legacy upgrade, corpus publication/coherence/readiness, split repair and
  certification.
- Formal forward-run evidence consumer: `15 passed` with zero skips, including
  refusal when unpublished anomaly observations appear in the exact coherence
  schema.
- Formal authority/forward-run fixture selection after the exact coherence
  fixture correction: `76 passed` with zero skips under Linux-equivalent
  canonical inputs.
- Current-head backtester boundary: `100 passed` with zero skips.
- Full Python compilation, tracked-shell `bash -n`, the canonical/automation/
  authorized-cli Compose graphs, and `git diff --check`: pass.
- GitHub `Sentinel safety` workflow at review-fix code head `46775d3`: pass
  ([run 31818226735](https://github.com/flabber1835/stocker/actions/runs/31818226735)).
  The network-isolated complete Sentinel suite passed `2232` tests in its one
  post-fix full run; the changed production backtester boundary passed `100`
  tests. Both runs had zero skips. Compilation, tracked-shell syntax, the
  canonical/automation/authorized-cli Compose graphs, and `git diff --check`
  also passed in that workflow.

## Change policy

Every remediation must include a regression falsifier for the observed NAS
sequence. The remediation is ready for review because each resolved item has
targeted falsifiers and the remaining operational work is explicitly scoped in
the PR summary. Readiness for review does not authorize merge or deployment.
