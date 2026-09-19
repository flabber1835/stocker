# Host lock ownership evidence

Verified main base: `65e261312ec219e014f062c0b6b374066db19d75`.
Feature branch: `codex/backup-lock-ownership`; delivery is PR-only against main.
The containing commit and `source-provenance.json` identify the reviewed source.
PRs #406 and #407 are separate pending changes and are not in this base.

The backup and GO verifiers checked contention at a matching inode. Their
contract instead requires ownership by the inherited open-file description.
Both now call a shared read-only helper that requires Linux descriptor-associated
exclusive whole-file flock evidence with matching device/inode. Unavailable,
malformed or oversized evidence refuses. The helper cannot acquire, upgrade or
release a lock. The change is a P1 serialization-integrity fix; it does not
attribute a historical economic discrepancy or deployed corruption to this bug.

## Exact local commands

```text
python audit/economic_399/host_lock_ownership/run_local.py regression
python audit/economic_399/host_lock_ownership/run_local.py entrypoints
python audit/economic_399/host_lock_ownership/run_local.py backup
python audit/economic_399/host_lock_ownership/run_local.py mutations
python audit/economic_399/host_lock_ownership/run_local.py host --image python:3.8.15-slim
python tools/validate_test_responsibility.py --base 65e261312ec219e014f062c0b6b374066db19d75 --output ownership.json
git diff --check
```

Host launcher:
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Every runner prints its exact Docker command to the retained log. Source is
mounted read-only and copied into a disposable writable checkout without `.git`,
`.env` or bytecode so existing GO tests can create their private lock artifacts.
Network is disabled. No real broker, NAS, deployment or backup target is used.
The backup shell suite uses its existing deterministic command adapter; it is
not a new physical PostgreSQL restore qualification.

Local images:

- `sentinel-test:ci`: `sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`, Python 3.12.13.
- `python:3.8.15-slim`: `sha256:b5abf044b0a94dbfc0463b9f7bd1e13010a096c64b98a441c7dabb5fb44b0308`.

## Results

- **55 ownership/GO regression passes in 15.93 seconds** on final test source.
- **40 entrypoint/output-guard/liveness passes in 8.94 seconds**.
- **45 backup publication lifecycle passes in 144.08 seconds**.
- **Two compatibility tests passed on actual Python 3.8.15**, exercising both
  production verifiers and an inherited duplicate descriptor.
- **Six guard mutants detected**: backup ownership, GO ownership, exclusive
  mode, overflow-byte read, evidence-size refusal and descriptor identity.
  Failures occur at intended assertions on disposable files, not collection or
  infrastructure failures. No production deployment entrypoint is invoked by
  the falsifiers.
- **475 owned test modules, zero unowned; eight changed Python files parse and
  have zero pyflakes findings.** Static inspection applies `ast.parse` and
  `pyflakes.api.checkPath` to each provenance path. The changed media harness
  passed `bash -n scripts/test-backup-runtime-media.sh` inside the offline image.

Independent kernel contention checks establish that verification leaves the
actual owner's lock held and leaves shared locks unmodified. Pipe-synchronized
process tests establish ownership after the original parent exits, refusal of
another owner while the child lives, and successful new acquisition after child
exit. Existing production GO phase and backup shell tests cover callers and
the updated helper bundle. No economic fixture or capability was changed.

`results.zip` retains the initial focused/53-case run, final 55-case regression,
entrypoint/backup/Python 3.8 results, initial/final mutation traces and ownership
output. `source-provenance.json` hashes final source with Git LF normalization;
`SHA256SUMS.json` binds the package. Verify committed blobs before push and use
the exact committed-range whitespace check used by CI.

## Remaining gates / NAS handoff

See [design and concrete qualification criteria](../../../docs/host-lock-ownership.md).
The actual NAS kernel/procfs must expose descriptor lock records; test that
prerequisite on a disposable clone before deployment. Missing records refuse
instead of falling back to contention-only proof. Retain exact kernel, source,
image and Python identities and positive/negative process evidence.

Existing lock scopes are unchanged: backup is canonical-target plus host UID,
GO is its checkout. Cross-UID/cross-host backup publishing and independent GO
checkouts still require a reviewed ownership contract. Directory discovery,
recurring maintenance, horizon rollover/retention and other recorded
provider/data/NAS gates remain open. Step 1 and economic certification are not
complete. No self-merge.
