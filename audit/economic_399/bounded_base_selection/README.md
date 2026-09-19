# Bounded default backup selection

Verified base: `58c3e071ede06c176e1ed814fb1a7e35b13c33b2` (merged #407).
Branch: `codex/bounded-backup-selection`; the containing PR records its final
reviewed head. #408 and #409 are separate pending changes.

P2 resource defect: default runtime selection enumerated and sorted the entire
retained base directory. It now reads a cluster-bound record, at most 257 bytes,
and admits only exact records within 256 bytes. All base/manifest/WAL/hash
checks remain required. The verified base producer publishes the record
atomically after promotion; the final reader check precedes recording a
successful observation. No selection means unavailability, with no scan fallback.

**Rollout:** create a fresh verified base with the updated backup command before
default runtime admission. Existing explicit checkpoint validation remains
usable. Do not hand-write selection, repin goldens or enable capability flags.
See [design and rollout](../../../docs/backup-runtime-selection.md).

## Local commands and results

Run from repository root. Host Python executable:
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
The runner prints the exact Docker invocation to each retained log.

| Command/campaign | Result |
|---|---|
| Initial new selection tests plus three shell publication cases | 17 passed in 17.42 s. |
| `python audit/economic_399/bounded_base_selection/run_local.py regression` first attempt | 4 failed, 285 passed in 173.71 s. Failures exposed successful-observation cache advancement before a failed final reread. |
| Same regression after correcting cache sequencing and adding real publication/rename tests | **291 passed in 176.80 s**, no skips/xfails. |
| `python -m pytest tests/sentinel/test_backup_selection_sql.py -q --tb=short -p no:cacheprovider` | 6 passed in 4.64 s, including actual root publication, PostgreSQL read-only access and failed rename. Included in final regression. |
| `python audit/economic_399/bounded_base_selection/run_local.py mutations` | **7 killed**: runtime caller wiring, cluster binding, final reread, read length, size guard, selection alias, producer wiring. |
| `python tools/validate_test_responsibility.py --base 58c3e071ede06c176e1ed814fb1a7e35b13c33b2 --output ownership.json` | PASS, 479 modules, zero unowned. |
| AST parse/pyflakes for eight changed/new Python files | All parse; zero findings. |
| `sh -n scripts/sentinel-backup-publish-selection.sh`; `bash -n scripts/sentinel-base-backup.sh scripts/test-backup-runtime-media.sh` | PASS. |
| `git diff --check HEAD^ HEAD`; `git diff --check origin/main HEAD` | Required before publication. |

The failed four cases retain their assertions: every media-read failure must
refuse without advancing successful proof observations. The correction moves
selection validation ahead of the observation update; it does not clear prior
history or weaken the test. Raw first-failure and first-regression logs remain
in `results.zip`. No economic oracle or golden was changed.

Acceptance covers 2,000 unrelated directories plus incomplete generations,
fresh-process reads, wrong cluster/schema/traversal/duplicate/truncated/oversized
records, missing record without fallback, explicitly selected checkpoints,
selection changing during proof, and continued full WAL integrity checks.
Actual PostgreSQL returns at most 257 bytes from a 32 MiB record. Actual shell
publication gives PostgreSQL selection read access without payload reads or
selection writes; rename failure retains the old complete record and removes
the temporary. The production producer-call falsifier removes the invocation
only in a disposable copy and requires its public lifecycle test to fail.

Offline image `sentinel-test:ci`:
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`;
Python 3.12.13, PostgreSQL 17.11. Input source read-only, disposable working copy,
network disabled, `.env` excluded. Actual PostgreSQL 16 Docker composition is
the existing mandatory CI/physical qualification gate, not established by these
local PostgreSQL 17 runs. No NAS or broker account was contacted.

`source-provenance.json` records Git-LF source hashes; `SHA256SUMS.json` binds
this package. Older retained audit evidence is unchanged.

## Concrete NAS handoff — not executed

Prerequisites: owner review/merge and exact-head CI, accepted runtime/test image
digests, reviewed independent backup target, and an isolated physical clone
without broker credentials/network. Preserve previous backups and all evidence.

1. Run `python audit/economic_399/bounded_base_selection/run_local.py regression`
   and `mutations` with the accepted local test image tag. Retain exact commands,
   source/image/PostgreSQL versions and raw output. Pass requires all tests and
   all seven falsifiers, without unexpected skips/xfails.
2. Run `bash scripts/test-backup-runtime-media.sh` in its disposable environment.
   The helper bundle now includes the selection publisher. Pass requires actual
   PostgreSQL 16 default authority to consume the verified producer's record,
   while payload reads and metadata writes remain denied. Retain its
   `BACKUP_RUNTIME_PASS` results, cluster identity, selected base and WAL proof.
3. On the separately authorized clone, run the updated
   `bash scripts/sentinel-base-backup.sh`. Retain the exact selected file bytes,
   owner/group/mode, selected base, manifest and WAL evidence. Expected record:
   three canonical lines, current cluster, promoted base, root:postgres 0640.
   Run `bash scripts/sentinel-backup-status.sh --backup <verified_base_path>`
   and require verified contiguous archive integrity.
4. Restart the isolated services and repeat the authority observation. Simulate
   missing selection, partial/wrong-cluster record, aliases, incomplete selected
   base and selection rollover during proof in copies only. Pass requires
   refusal before financial mutation, no directory fallback, no proof-history
   advancement on failure, and recovery after the valid producer restores state.
5. On disposable target media, interrupt before/after rename and test real
   power-loss recovery. Accept only an old or new complete record; never a
   truncated success. Retain fsync/rename outcomes and measure caller deadlines
   and resource use under realistic storage pressure.

Recurring scheduling, cross-host/UID ownership, retention, proactive horizon
rollover, host inspection/cleanup enumeration, filesystem progress, provider
finality and data-dependent replay remain open. This is not economic certification.
