# PR #415 current-main integration

Previous reviewed PR head: `558673b1b434760673ee1de52c25c4e1e1f707c7`.
Fetched main: `99410e5aff363f9d3d1b0b8d3dbc4e9b93ef4b45`, containing
owner-merged #412, #413 and #414. All six workflows on the previous head passed;
the merge blocker was conflicting append-only additions to
`docs/economic-code-closure.md`.

Merge current main without rebasing or rewriting published history. Preserve
both complete ledger additions, with main's sections before the PR's sections.
All 27 other files from the original PR are unchanged byte-for-byte. No new
production behavior, design decision, golden value or capability is introduced.
Earlier source/artifact manifests continue to describe their explicitly reviewed
commits; do not reinterpret their ledger hash as the merged document's hash.

Validation on the combined tree:

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_status_inputs.py tests/sentinel/test_rolling_recovery_report_inputs.py
python tools/validate_test_responsibility.py --base origin/main --output <scratch>/pr415-main-integration-ownership.json
git diff --check
```

**9 passed in 37.76 seconds**, in the existing offline disposable test image.
All 16 Python files from the original PR parse. Ownership: **487 modules, zero
unowned, PASS**. Raw test output and ownership report are retained byte-for-byte
in `results.zip`; `SHA256SUMS.json` identifies the ZIP and its members. The first
sandboxed Docker invocation was denied access to the Docker named pipe before
tests started; the authorized invocation above completed successfully.

The PR description records the resulting merge commit and fresh CI status.
Pending labels in earlier ledger entries are historical. Stage 1 and economic
certification remain open; no NAS/broker access or self-merge occurred.
