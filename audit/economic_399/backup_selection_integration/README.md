# PR 410 combined backup review

Verified main: `8212a55335500b4bbb81853572019d9eb4443724` (owner-merged #408).
Previous PR head: `ec0f1d3bc1535882fcc5fd3523f8455d248396a6`.
Delivery: existing [PR #410](https://github.com/flabber1835/stocker/pull/410),
targeting main, without history rewriting or self-merge. The merge commit
containing this package identifies the reviewed combined head; the retained
provenance binds the exact reviewed source bytes independently of that commit.

Conflicts were in two documentation sections and the shell-lifecycle script
bundle. Both documentation contracts and both helper modules are retained.
`scripts/test-backup-runtime-media.sh` also includes both helpers after its
automatic merge. The production selection, ownership and integrity algorithms
are unchanged from their respective reviewed parents. Original golden and
audit packages are preserved.

## Local results

All commands ran from the combined worktree. Docker used no network or broker
credentials, disposable files and isolated PostgreSQL. Tests copied source to
a disposable checkout; the payload and horizon probes mounted source read-only.
The cached test image was `sentinel-test:ci`, digest
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.

```text
python audit/economic_399/bounded_base_selection/run_local.py regression
python audit/economic_399/host_lock_ownership/run_local.py regression
python audit/economic_399/bounded_base_selection/run_local.py mutations
python audit/economic_399/host_lock_ownership/run_local.py mutations
python audit/economic_399/backup_proof_bounds/run_local.py payload --segments 64
python tools/validate_test_responsibility.py --base 8212a55335500b4bbb81853572019d9eb4443724 --output ownership.json
git diff --check
git diff --check origin/main HEAD
```

- Backup regression: **291 passed in 177.89 s**.
- Lock ownership and GO/backup concurrency: **55 passed in 16.10 s**.
- Selection: **7/7 mutants detected**. Ownership: **6/6 mutants detected**.
  Positive baselines passed first; mutations require an actual failed assertion,
  not a collection/import error. No skips, xfails or fixture repinning.
- Ownership inventory: **481 modules, zero unowned**.
- Five Python files parse and pass pyflakes; producer, publisher and physical
  harness shell syntax passes. Exact static commands are retained in static.log.
- Whitespace and retained/committed source and evidence hashes verified.

The existing worst-admitted-payload probe completed three samples of 64
16 MiB sparse zero-filled files: 1 GiB distinct bytes, 2 GiB reads and 128 hash
operations per proof. Times: **2.566277983 / 1.684766050 / 1.651214637 seconds**.
PostgreSQL backend peak RSS: 35,396 kB; whole container peak memory:
**1,245,999,104 bytes**, under the specified 2 GiB limit/two CPUs. PostgreSQL
was 17.11. This measures only the isolated payload phase. It does not establish
NAS throughput, the complete authority callback deadline, realistic populated
WAL behavior, full-universe resource cost or the production cgroup limit.

## Maintenance finding and independent arithmetic

**P1, A5 / backup A6 remains an implementation gate.** The deployment text's
daily cadence cannot alone guarantee continued runtime admission. The runtime
1 GiB ceiling permits only 64 full 16 MiB segments on timeline 1; a nonempty
history object consumes additional bytes on later timelines. The actual
interval function admits 64, refuses 65, and refuses the independent literal
288-segment interval spanning a log-ID boundary. The probe never changes limits
or enables capabilities, and does not claim arithmetic admission proves restore.

[PostgreSQL 16 archive_timeout documentation](https://www.postgresql.org/docs/16/runtime-config-wal.html#GUC-ARCHIVE-TIMEOUT)
states that switches depend on database activity and that early-switched archive
files retain full segment length. The repository sets 300 seconds. Thus a
five-minute-switch scenario consumes 64 segment slots over 320 minutes; a full
day represents 288 switches/4.5 GiB. Heavy writes, explicit switches, initial
recovery-marker segments or history bytes can reduce available time. This is
an inferred scenario, not a claim that idle PostgreSQL switches on schedule or
a deployed WAL-rate measurement. Merely installing a daily timer would leave
the existing gate unresolved.

Run the arithmetic probe from a credential-free disposable checkout:

```text
docker run --rm --network none --mount type=bind,source=<absolute-checkout>,target=/repo,readonly --workdir /repo -e PYTHONPATH=/repo:/repo/shared -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python sentinel-test:ci -u audit/economic_399/backup_selection_integration/horizon_probe.py
```

Review references: `sentinel/backup_runtime_authority.py:42`, `:268`, `:430`;
`docker-compose.sentinel-backup.yml:15`; `scripts/sentinel-base-backup.sh:22`,
`:202`; `scripts/sentinel_backup_lock.py:46`;
`docs/sentinel-deployment.md` section 10g.

Implementation still required: proactive verified successor creation/publication
before the horizon limit, durable restart/outage recovery, one maintenance owner
across the supported deployment scope, and retention that preserves every
required restore chain. The current backup lock is per canonical path/host UID;
it does not serialize different UIDs or hosts. The current producer still scans
abandoned staging; host status/cleanup resource bounds remain open. No scheduler,
retention policy or global ownership authority is added by this integration.

## Concrete NAS handoff (not executed)

Prerequisites: owner merge after all exact-head CI passes; a credential-free
disposable clone on the accepted host/kernel/filesystem; accepted test/runtime
image digests, PostgreSQL 16 and recorded CPU/memory limits; independent disposable
backup media. Complete the open maintenance implementation first if qualifying
continuous unattended operation. Preserve existing golden and physical evidence.

1. Run the regression/mutation commands above and the arithmetic probe using the
   accepted image (the original runners' image name must resolve to its recorded
   digest). Retain source/image/PG identities, raw logs, exit codes and hashes.
   Pass: all positive cases succeed, all 13 mutants are detected, no unexpected
   skip/xfail, and exact 64/65/288 interval results. These do not grant authority.
2. Run `bash scripts/test-backup-runtime-media.sh` and
   `bash scripts/test-backup-physical.sh` in their disposable environments.
   Retain selected base, manifests, system ID, marker LSN, archived WAL/checksums,
   actual restored-marker evidence and complete logs. Pass: real verified
   publication, inherited-owner survival, refused concurrent publication,
   unchanged prior evidence on failure, successful physical replay after repair.
3. Repeat the payload probe with `--image <accepted-test-image>` and separately
   measure the **complete production admission callback** with real populated
   WAL, concurrent writers and its actual deadlines/cgroup limits. Retain cold
   and warm latency, cgroup peak memory, timeout/OOM counters and refused mutations
   on media faults. Pass: within the accepted deadline and memory limit, no
   successful mutation or retained proof after corruption/change. The local
   payload numbers cannot substitute for this measurement.
4. Once maintenance exists, accelerate WAL growth across multiple 64-segment
   horizons; interrupt before/during/after verified successor publication and
   retention, kill the maintenance parent, restart the container/host, and resume
   after an outage beyond the ordinary cadence. Retain old/new selection and
   manifests, ownership evidence, recovery state and an actual restore for every
   retained required chain. Pass: one active producer, bounded proactive renewal,
   recovery without manual evidence manufacture, no deletion of required WAL/base,
   and preserved fail-closed mutation during unresolved faults. This gate is
   currently **OPEN**, not an executable qualification claim.

C1/F6 cash completeness/finality, F19 native authority, C3 predecessor evidence,
authoritative historical replay inputs and all listed NAS gates remain open.
No economic certification or historical strategy return is established here.
