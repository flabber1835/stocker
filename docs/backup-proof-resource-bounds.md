# Runtime archive proof resource bounds

Step 1 review on base `3c4fb030b3ad06bc8996771479b2d68b71cb17e6`
found two implementation gaps in `sentinel/backup_runtime_authority.py`:

* WAL enumeration used a million-segment ceiling before the existing 1,024
  object / 1 GiB proof ceilings were applied. A stale base could consume work
  disproportionate to a proof that must immediately refuse.
* Hash SQL sampled file size again after the byte budget was checked. A file
  growing between metadata observation and hashing could enlarge the read past
  the accepted budget. A bounded prefix digest alone would not establish that
  the complete archived object remained unchanged.

The existing limits and restore-horizon authority remain the contract. Count
the inclusive WAL interval arithmetically before constructing names. Include
the required timeline-history object in the object count, and reject a WAL
byte subtotal exceeding the existing byte limit before metadata or payload
reads. The later full metadata check still accounts for timeline-history bytes.
Exactly-at-limit intervals remain valid when their complete metadata fits.

Hash each object using its already-observed byte length, passed as a SQL value.
Do not restat its size inside the read expression. PostgreSQL's documented
[bounded binary file read](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADMIN-GENFILE)
returns at most that length; a short/missing read cannot match the retained
complete-object digest. After hashing, re-observe all required object and
sidecar metadata and repeat the existing alias check before granting or caching
the proof. A changed observation is a retryable unavailable horizon; it never
produces a successful partial proof or advances the retained observation.

The real PostgreSQL test then found a third defect: `pg_stat_file` exposes
second-resolution timestamps, so a same-size replacement within one second can
leave the metadata tuple unchanged. The old five-minute metadata-based hash
reuse is withdrawn. Each mutation proof performs two bounded complete content
passes and compares their digests with each other and the retained sidecars.
Metadata and alias checks follow both passes. A difference between content
passes is retryable unavailable; stable content differing from its sidecar is
an integrity refusal. The process-local last-observation map may detect a
regressing frontier but cannot skip content reads or grant authority. No new
SQL tables, filesystem cache, service, clock assumption or database commits
are introduced.

The unchanged 1 GiB ceiling limits distinct payload bytes in the selected
horizon. The two passes explicitly bound total payload reads to 2 GiB and
hash operations to twice the accepted object count. Actual latency and RSS
require measurement on the accepted production image and full restore horizon;
this correctness fix does not claim that the worst case fits a broker deadline.
An efficient future reuse mechanism needs stronger verified file identity and
its own review; raising limits or restoring timestamp-only reuse is not an
acceptable performance workaround.

Acceptance uses arithmetic boundaries independent of generated filenames,
an enumeration tripwire on over-budget input, fixed-length reads against real
isolated PostgreSQL, and changes injected between real metadata/hash operations.
Positive coverage must still accept a complete unchanged chain and repeat its
content proof. Falsifiers remove each early bound, restore the stat-sized read,
skip the second pass, restore content reuse, or remove the post-read stability
gate and must fail at behavioral assertions.

This closes only these archive enumeration/read defects. It does not implement
recurring verified base creation, WAL retention or proactive horizon renewal.
Base-directory scanning, manifest parsing, actual full-universe I/O cost and
blocked-filesystem behavior remain separate resource review/qualification work.
No broker, economic algorithm, backup deletion policy or NAS access is involved.

## NAS handoff (not executed)

Prerequisites: owner-reviewed merge and passing exact-head CI; the accepted
runtime/test image digests and PostgreSQL version; a disposable clone with no
broker credentials or external network; independent retained backup media; and
the actual configured memory/CPU limits and mutation-callback deadlines. Preserve
all existing golden and physical backup artifacts. The following runner replaces
a present `.env` with an empty file and mounts source read-only.

```text
python audit/economic_399/backup_proof_bounds/run_local.py regression --image <accepted-test-image>
python audit/economic_399/backup_proof_bounds/run_local.py backup --image <accepted-test-image>
python audit/economic_399/backup_proof_bounds/run_local.py mutations --image <accepted-test-image>
python audit/economic_399/backup_proof_bounds/run_local.py payload --segments 64 --image <accepted-test-image>
```

Pass requires no unexpected failures/skips/xfails, detection of all nine mutants,
and no successful or newly retained proof after an injected change. Healthy and
repaired media must pass. Record exact commands, source/image hashes, database
version, raw logs and the payload JSON. The 1 GiB payload case must report 128
hash operations per proof, two bounded passes and finite peak-memory/latency data.
It deliberately uses synthetic sparse files in a disposable local PostgreSQL;
that result alone is insufficient to qualify production storage.

On the separately authorized physical clone, run the repository's
`scripts/test-backup-runtime-media.sh` and `scripts/test-backup-physical.sh` in
their disposable environments. Retain the full trace and restore marker/LSN,
selected base, WAL names, source/image/database identities and zero-exit checks.
Then measure the complete production authority call under its actual deployment
limits with realistic populated WAL and concurrent workloads. Include cold
restart, the largest admitted horizon, missing/truncated/corrupt/aliased media,
and proof after repair. Pass requires refusal before financial mutation on every
fault, completion within each configured caller deadline, and observed cgroup
peak memory below the accepted deployment limit. A timeout, OOM, unexplained
state change or unsupported restore horizon is a qualification failure; do not
raise budgets or restore coarse-timestamp reuse to manufacture acceptance.
