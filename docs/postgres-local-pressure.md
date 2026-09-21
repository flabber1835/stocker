# Local PostgreSQL pressure investigation

This is the bounded L09 follow-up to PR #425. Base: `48f88fd4f3957c0dfc264e2eef2e35ecd753c9c1`;
prerequisite: `fa24fddc2a1982c91e6be76181b6b4c7af587ec5`.
No NAS, provider, broker or paper activation is involved.

## Measurement decision, before implementation

The retained PG17 campaign completed without OOM, but `memory.events:max`
increased to 52,181. Its final checkpoint contains 56,365,056 anonymous bytes,
147,140,608 shared-memory bytes and 737,361,920 filesystem-cache bytes
(`file - shmem`). Checkpoints alone cannot rule out transient backend growth.

Run the existing production publisher on the pinned production PostgreSQL 16.14
image with 8,408 securities and 300 sessions. Retain a one-second cgroup sample
stream, PostgreSQL settings, database/temp/WAL statistics and query plans. Then
repeat the actual ordered snapshot scan and exercise the compressed observation
writer/reader on the same database. Keep the 1 GiB memory/swap, 1.5 CPU and 1 GiB
shared-memory limits. Use a fresh disposable container with network disabled,
no published ports and only synthetic fixtures. Do not change durability, SQL
semantics, capability flags, production configuration or financial rules to
improve the measurement.

Report total charged memory, file cache excluding shared memory, and the
conservative sampled non-file-cache estimate `anon + shmem + kernel` separately.
Shared memory is already included in `file`; do not subtract it twice or call
all file bytes disposable. Retain raw peak, max/OOM counters, PSI stall totals,
refaults, dirty/writeback pages and sample gaps. A timer sample is not a bound
on unsampled spikes. Cache pressure does not earn a total-memory headroom PASS.

The existing 20% headroom threshold may describe the sampled non-file-cache
estimate, explicitly scoped to this workload; total-memory headroom and NAS
latency remain distinct. Do not invent an accepted latency budget. Compare
exact scan row counts and content digests across repetitions, and preserve
exact storage round-trip equality. If evidence identifies a code defect,
document its correction before changing production code. Otherwise retain a
diagnosis instead of making speculative tuning changes.

Authoritative interpretation: [Linux cgroup v2 memory interface](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files)
defines `file`, `shmem`, limit events and memory pressure. PostgreSQL's
[resource settings](https://www.postgresql.org/docs/16/runtime-config-resource.html)
distinguish shared buffers from per-operation working memory and maintenance
memory; `work_mem` is not a whole-server memory cap.

## Result, 2026-09-20

**Local diagnosis complete: cache reclaim reproduced; no additional PostgreSQL
code defect reproduced. No production change or speculative tuning is justified
by this campaign.** The former observation-write OOM is repaired in #425.
This follow-up neither reopens that defect nor certifies all deployment capacity.

Reviewed production commit: `fbc18edcae815235c37f2dffda219e403e317e54`, the merge
of current main and #425. Production bytes are unchanged from #425. Retained
source hashes bind the files actually mounted during measurement and were
rechecked at completion. No production file or Compose setting changed here.

The pressure reporter is audit-only. Its one source file is copied into the
test image so the same eight evidence tests work in the isolated CI layout;
the production image receives neither the audit runner nor the reporter.

| Observation | Result |
| --- | --- |
| PostgreSQL | Pinned production image, 16.14; 1 GiB memory/swap, 1.5 CPU; no ports/network |
| Workload | 8,408 securities x 300 sessions = 2,522,400 published rows |
| Sampling | 719 samples over 727.01 s; largest gap 1.06 s |
| Total charged peak | 1,074,319,360 bytes, 577,536 bytes briefly above the enforced cap |
| Sampled non-file-cache peak | 268,746,752 bytes = 256.30 MiB; 74.97% sampled margin |
| Non-file-cache estimate at end | 164,392,960 bytes = 156.78 MiB |
| File cache peak, excluding shared memory | 890,138,624 bytes = 848.90 MiB |
| Limit crossings / OOM | `max=16591`; all OOM counters zero; all containers exit zero |
| Memory stall time | PSI some 0.675485 s / full 0.675176 s, about 0.093% of sampled time |
| Publication | 608.05 s worker / 611.98 s including container startup and inspection |
| Full content verification | 30.19 s and 29.91 s; identical sealed manifests and recomputed hashes |
| SQL ordered scan alone | EXPLAIN ANALYZE execution 2.154 s / 1.257 s; zero temp read/write blocks |
| Observation storage | 8,408-series exact genesis and observation round-trip; 41.02 s worker |

Separate phase peaks for the non-file-cache estimate are 256.30 MiB during
publication, 183.14 MiB for scan 1, 179.97 MiB for scan 2 and 160.65 MiB for
storage. No accumulating growth was observed across those reads; two reads do
not establish unlimited lifetime or arbitrary concurrency. The SQL plan uses
`sentinel_snapshot_bars_pkey` and incremental sort by session/security; largest
per-session sort allocation is 1,231 KiB. It does not need a new index for this
workload. The client also validates and hashes every row, so its full verification
time must not be confused with database execution time.

Publication does spill: PostgreSQL recorded 1,335,443,456 temporary bytes across
21 files, unchanged by both later scans and storage. That is retained disk I/O,
not silently discounted work. The published database occupied 925,645,847 bytes;
the staging relation was 404,430,848 bytes and the snapshot relation 505,962,496.
Automatic cleanup reduced database size to 521,247,767 bytes during repeated
reads; after observation storage it was 552,221,719 bytes. Normal `fsync`,
`full_page_writes` and `synchronous_commit` remained on, shared buffers 128 MiB
and work memory 4 MiB. WAL output and checkpoint logs are retained.

The original eight-stage PG17 artifacts remain unchanged. Their endpoint
anonymous allocation stays within 8 KiB across stages, and shared memory changes
by only 28 KiB; their high total usage is primarily file cache too. The new
continuous PG16 samples support that interpretation without claiming to observe
the old run's unsampled transient allocations.

## Disposition and verification

- **Local PostgreSQL investigation: complete.** Production publisher, full-content
  reader and compressed storage preserve exact data under enforced caps. No
  additional reproducible implementation defect was found. Relevant reviewed
  paths: `sentinel/feed/rolling_store.py:101` (`_write`), `:140` (`_rows`),
  `:271` (`verify_content`), `sentinel/feed/rolling_schema.py:26` (ordered primary
  key), and `sentinel/observation_storage.py:42` / `:63` (bounded encoding/decoding).
- **L09 capacity/latency qualification: still open, P2 qualification blocker.**
  Total-memory headroom is `TIGHT`, not PASS; cache fills the available cap.
  Sampled non-file-cache margin is evidence, not a proof against every subsecond
  spike or concurrent backup workload. NAS disk latency, admitted reference/action
  history, concurrent services and an accepted response-time budget remain to be
  qualified. No new economic-rule defect is inferred from these counters.

Exact commands, test outcomes, raw samples, plans, source/image identities and
artifact hashes are in [the retained audit package](../audit/economic_399/postgres_pressure/README.md).
Eight targeted tests pass; all three intended reporting mutants are detected.
Six changed Python files, including the CI assertion, parse and pass Pyflakes. A production/Compose
diff against the reviewed commit is empty. No golden artifacts were repinned.

## Concrete NAS handoff, not executed

After owner merge and required CI, use the reviewed image/schema with broker
mutation disabled and a populated disposable qualification restore. Preserve
the backup target and source identities. Run the existing [NAS resource
capture commands](../audit/economic_399/status_cost/README.md#nas-handoff-not-executed)
for the real publisher, daily continuation and repeated panel requests, including
the expected backup overlap. Those commands retain image/cap inspection, full
HTTP responses, state/NAV/authority hashes, cgroup counters and elapsed time.
Collect PostgreSQL `pg_stat_database.temp_bytes`, disk growth and checkpoint/WAL
logs as well. The Synology cgroup-v1 capture must retain its native `memory.stat`,
peak, failure/OOM and CPU counters; this audit's v2 parser must not be applied
to v1 field names.

Pass requires exact economic/data/authority invariants, no OOM or restart, no
unexplained repeated-request growth, justified resident working-set margin and
the accepted latency budget. File-cache occupancy at the limit is recorded
separately and is not itself proof of a leak. Excessive reclaim stalls or slow
storage fail latency qualification even with ample non-file-cache margin.
No provider guarantee, historical CAGR/multiple, broker authority or overall
economic certification is granted by this result.
