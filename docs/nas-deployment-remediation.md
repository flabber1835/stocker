# NAS deployment remediation

This record tracks defects discovered during the first deployment of merged
Sentinel main (`f65e9e34bc204250e4e5a99b61dfdc099e0392ef`) to a Synology NAS.
It is intentionally separate from the deployment checkout: production keeps
running reviewed images while fixes and falsifiers accumulate in this draft PR.

## Confirmed findings

### 1. Sharadar API key appears in HTTP request logs

**Observed:** `feed-daily` emitted `httpx` INFO request URLs containing the
literal `api_key` query parameter.

**Impact:** terminal capture, supervisor logs, copied diagnostics, and support
transcripts can disclose the data-vendor credential.

**Acceptance:** ordinary and verbose execution, retry paths, and terminal HTTP
errors never render secret query values. A falsifier uses a sentinel secret and
asserts that it is absent from stdout, stderr, log records, and exception text.

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

### 4. Derived-only splits need explicit certification disposition

**Observed:** a daily ingest reported 14 price-domain split ratios for which
SHARADAR/ACTIONS had no row, including unusually large ratios.
The subsequent bounded backfill reported the same 14 tickers on the backfill's
different leading date. This demonstrates that they are adjustment-vintage seam
artifacts, not 14 corporate actions that happened on both reported dates. The
normalizer's seam guard records and suppresses such ratios, but the shared
warning incorrectly says it is "using the derived ratio".

The same backfill also found three ACTIONS/price-domain disagreements where the
two values were near exact reciprocals (for example approximately 30 versus
1/30). The current policy unconditionally applies ACTIONS. That is not enough
evidence to distinguish a vendor share ratio from a price adjustment factor,
and an orientation error would materially corrupt share counts for a position
held across the event.

**Impact:** fallback is safer than ignoring a genuine split, but a certified
run must not hide whether an uncorroborated ratio affected an eligible or held
security.

**Acceptance:** certification retains the complete derived-only event list and
states a deterministic warning/refusal policy based on economic relevance.
Seam-suppressed artifacts are not reported as applied derived-only splits.
Reciprocal disagreements refuse economically relevant use until the ACTIONS
orientation is proved from retained source evidence. Tests cover ordinary,
seam, reciprocal, eligible, and held-security cases.

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

### 6. Legacy corpus publication cannot backfill the required SPY tail

**Observed:** publishing a previously unversioned corpus with `feed-daily`
advanced prices through the current session, but the legacy database had no
rows in `sentinel_spy_total_return`. Daily ingestion overlaps 14 calendar days,
while readiness requires an exact 41-session SPY total-return tail, leaving all
41 required rows absent after a successful current publication.

**Impact:** the corpus is coherent, versioned, continuous, and fresh but can
never pass readiness through repeated daily operation. The runbook forbids
`feed-seed` over a non-empty corpus and there is no supported benchmark-only
backfill command, so an upgraded deployment reaches an operational dead end.

**Acceptance:** legacy publication detects an incomplete required benchmark
tail and performs a bounded, versioned SPY backfill (or exposes an explicit
idempotent repair command). It must not rewrite unrelated bars, weaken corpus
locking/publication, or require a full reseed. A PostgreSQL-backed falsifier
starts with a complete legacy bar corpus and empty SPY table, runs the supported
upgrade sequence, and ends with a passing 41-session frontier benchmark.

## Deployment observations that are not yet code defects

- Existing PostgreSQL volumes do not adopt a changed Compose password. The
  operator synchronized the database role with the deployment environment.
- The deployment correctly refused an unbound account and an absent current
  execution plan.
- A verified physical base backup and post-base WAL recovery marker were
  successfully written to an independent ext4 USB target.

## Change policy

Every remediation must include a regression falsifier for the observed NAS
sequence. This draft remains additive while deployment continues. It must not
be marked ready for review until each resolved item has targeted tests and the
remaining items are explicitly scoped in the PR summary.
