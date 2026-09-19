# Combined PR #405 / #406 validation

The owner merged #405. Fetch verified current main as
`65e261312ec219e014f062c0b6b374066db19d75`; this record accompanies its merge
into #406 parent `8a2a72403a5506a60841798779f207033039b531`.
The merge had no conflicts and required no production or test edits.
Existing evidence packages and economic golden artifacts remain unchanged.

From the merged repository root, using the local Python launcher:

```text
python audit/economic_399/backup_proof_bounds/run_local.py regression
python audit/economic_399/rolling_admission_ci_405/run_local.py regression
python audit/economic_399/backup_proof_bounds/run_local.py mutations
python audit/economic_399/rolling_admission_ci_405/run_local.py mutations
python tools/validate_test_responsibility.py --base 65e261312ec219e014f062c0b6b374066db19d75 --output ownership.json
git diff --check
git diff --cached --check
```

Both retained runners print their exact Docker command. Runtime:
`sentinel-test:ci`, image ID
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12.13, PostgreSQL 17.11, network disabled, read-only source mount,
disposable local databases. This does not replace exact-head GitHub CI or
deployed PostgreSQL 16/NAS qualification.

Results:

- Backup regression: **94 passed in 13.49 seconds**.
- Admission/deployment regression: **130 passed in 113.89 seconds**.
- Backup mutations: **9 killed**, admission mutations: **8 killed**.
  Expected test failures from broken guards are retained in the mutation logs.
- Test ownership: **475 modules, zero unowned, PASS**.
- All **33 changed Python files** across both PRs parsed with `ast.parse`.
  Expanded production/script/tool pyflakes inspection found four diagnostics,
  all reproduced unchanged on fetched main: unused `Path` and `SimpleNamespace`
  imports in `scripts/sentinel_autonomous_deploy_driver.py:13,18`, unused
  `calendar` in `sentinel/feed/rolling_go_inputs.py:9`, and the existing
  conditional `REFERENCE_SOURCE_SHA256` import in `sentinel/core/decision.py:277`.
  No new pyflakes diagnostic was introduced. These are retained explicitly;
  this is not a claim that the combined source is lint-clean.
- Both staged and unstaged diff whitespace checks passed.

`results.zip` retains raw campaign logs, ownership output, and static inspection
results with Git-LF-normalized source SHA256 hashes. `SHA256SUMS.json` authenticates
the retained files. The containing merge commit identifies the reviewed source;
source hashes are checked against its committed blobs before push.

No NAS or real broker account was accessed. This merge closes no additional
economic-certification gate. Step 1 remains open for the maintenance and resource
implementation gaps recorded in `docs/economic-code-closure.md`; provider,
historical-data and NAS gates remain separate. Fresh CI on the published merged
head is required before the owner merges #406.
