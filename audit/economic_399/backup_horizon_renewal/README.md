# GO backup horizon renewal: local evidence

Verified main base: `8212a55335500b4bbb81853572019d9eb4443724`.
Feature branch: `codex/backup-horizon-renewal`; delivery is a PR to main.
The commit containing this additive package is the reviewed head; the source
provenance binds the reviewed bytes independently of the final commit identity.
Original golden and retained evidence packages are unchanged.

## Finding and changed behavior

**P1, A5 / backup A6 availability and recovery.** A recent intact chain of 65
16 MiB WAL segments was reported ready by the actual status shell, even though
runtime permits only 1 GiB. Certified GO therefore skipped renewal and later
runtime admission would refuse. A 64-segment chain plus timeline history also
exceeds that budget. No strategy-return discrepancy is inferred.

Status now applies the existing runtime payload/object ceilings before hashing.
Both the required timeline-history object and its bytes count. An exact
exit-code/token pair identifies exhaustion; arbitrary dependency failures
remain structural refusals. The existing certified GO classifier creates one
fresh verified base and verifies its exact path. Failed creation, missing
successor checksums and ambiguous reasons cannot pass. Old media is preserved;
exhaustion does not certify its skipped contents. This adds no capability flags,
runtime-budget increase, scheduler or retention deletion.

Code: `scripts/sentinel-backup-verify-chain.sh:81`, `:96`, `:104`;
`scripts/sentinel-backup-status.sh:182`; `scripts/sentinel_go_backup_refresh.py:34`.
Acceptance: `tests/backup/test_shell_lifecycle.py:105`, `:125`, `:142`, `:177`,
`:246`; `tests/sentinel/test_go_backup_refresh.py:148`.
[Decision recorded before implementation](../../../docs/backup-horizon-renewal.md).

## Commands and results

Run from the repository root with Python and the cached test image. The runner
uses `docker run --rm --network none`, mounts source read-only and copies it to
a disposable `/tmp/repo`, excluding `.git`, `.env` and Python bytecode. No NAS,
external broker or provider accounts were contacted.

```text
python audit/economic_399/backup_horizon_renewal/run_local.py focused
python audit/economic_399/backup_horizon_renewal/run_local.py regression
python audit/economic_399/backup_horizon_renewal/run_local.py postgres
python audit/economic_399/backup_horizon_renewal/run_local.py mutations
python tools/validate_test_responsibility.py --base 8212a55335500b4bbb81853572019d9eb4443724 --output ownership.json
bash -n scripts/sentinel-backup-status.sh
bash -n scripts/sentinel-backup-verify-chain.sh
git diff --check origin/main HEAD
```

- Before implementation: **5 failed, 10 passed in 49.75 s**. The retained log
  includes two intact over-budget false-ready results, two absent early object
  refusals and rejection of the new renewal reason by the old GO classifier.
  That initial focused selection predates the additional successor/SQL cases.
- Focused acceptance: **21 passed, 69 deselected in 56.44 s**.
- Relevant regression: **319 passed in 210.03 s**, zero skips/xfails. This covers
  backup reliability, certified GO refresh, its call contract and bring-up.
- Added real SQL acceptance: **1 passed in 6.93 s**. The production shell reads
  the manifest using actual PostgreSQL and hashes real sparse files; 64 segments
  pass and 65 refuse. This case was added after the 319-test snapshot, so the
  final regression command includes it (320 total cases at this source).
- **8/8 mutants detected**, after passing positive baselines: byte bound,
  history-byte accounting, object bound, history-object accounting, exit-code
  classification, exact token classification, GO renewal caller and successor
  verification. Each was killed by one failed acceptance test, not import or
  collection errors.
- Six Python files parse and pass pyflakes; both changed shell scripts pass
  syntax independently. Ownership: **479 modules, zero unowned**. Committed
  whitespace, source hashes and package hashes verified.

The first SQL fixture attempt lacked traversal permission for the real server
and failed before manifest parsing. Its log is retained. The fixture now grants
traversal only within its disposable media and read access to its own manifest.
This is explicitly SQL/budget acceptance, not production UID ownership proof;
the existing physical harness owns that contract. No production grant changed.

The shell fixture runs production orchestration over temporary media and a
strict command adapter. Its new checkpoint inputs advance the modeled manifest,
marker and archived frontier from WAL `...43` to `...44`; the test never rolls
the frontier back to make a new backup acceptable. It executes the actual GO
refresh function and shell producer. Its GO certification/token and Git
observations are fixtures; existing refusal tests own those admission gates.
The one-byte segment geometry isolates the object limit and is not a real
PostgreSQL configuration. The real SQL case uses 16 MiB segments. Sparse zero
WAL and synthetic base manifests do not establish physical recovery semantics.

Local image: `sentinel-test:ci`, digest
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`;
Python 3.12.13, PostgreSQL 17.11. Exact PG16/image CI remains required.

## Remaining gates and concrete NAS handoff

**Step 1 and economic certification remain open.** This fixes exhausted-horizon
GO recovery. Recurring proactive scheduling, global ownership across supported
hosts/UIDs, outage/restart scheduling, retention and bounded host
directory/manifest inspection remain implementation/review work. The shell's
whole-file hashing does not establish runtime-style bounded reads against a
growing file or full filesystem progress. C1/F6 cash completeness/finality,
F19 native fill authority, C3 predecessor completeness, full-universe resource
limits and authoritative historical replay remain separately open.

After owner merge and all applicable CI passing, use a disposable credential-free
NAS clone with accepted host/runtime/test-image digests, PostgreSQL 16, independent
backup media and recorded resource limits. Integrate #410's selection contract
before qualifying their combined deployment. Preserve old evidence.

1. Run the commands above on that clone, retaining Git tree/head, image digests,
   PG/host identities, raw logs, exit codes and artifact hashes. Pass: every
   positive case passes, all eight mutants fail their assertions, no unexplained
   skips/xfails, 64/65 boundaries agree with the actual runtime budget.
2. Run `bash scripts/test-backup-runtime-media.sh` and
   `bash scripts/test-backup-physical.sh` in their disposable environments.
   Retain complete physical creation, archive and restored-marker evidence.
   Pass: intact media restores, corrupt/missing/aliased media refuses, and
   repaired media restores without editing acceptance artifacts.
3. In a separately authorized disposable GO qualification run, generate enough
   real archived WAL to exceed 1 GiB from the selected base while its age remains
   fresh. Record the status reason, GO run/lock identity, old/new base and
   selection, manifests, checksums, marker LSN, frontier and refresh audit.
   Pass: status emits only the reviewed repairable reason; exactly one fresh
   verified successor is created, its exact path passes, the frontier advances,
   and a second fresh invocation creates no unnecessary backup. Inject creation
   and successor-check failures: each must refuse before preparation succeeds,
   retain all old media and produce no false ready/certification claim.
4. Qualify proactive maintenance, restart/outage recovery and retention only
   after their separate implementation exists. Current local GO recovery is
   not a substitute for that service, supported-scope ownership, physical
   power-loss testing or real-device evidence.

No broker mutation is required or authorized by this package. No self-merge.
