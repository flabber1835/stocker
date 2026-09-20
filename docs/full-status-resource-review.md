# Complete status resource review

Review base: owner-merged main `29cdd7727ba2adea27672830c538d76a2218943e`,
with pending #415 `558673b1b434760673ee1de52c25c4e1e1f707c7` integrated in an
isolated branch. The existing PRs are not changed by this review.

## Measurement plan

Build a synthetic full-universe operational publication and canonical shadow
origin in disposable PostgreSQL using the existing provider/identity test
scaffolding. Use the real publication, warmup, transition, checkpoint, receipt
and status code. A fresh child process measures complete public shadow status,
separating its peak RSS from fixture/acquisition/warmup allocations. Instrument
phase duration and peak RSS without replacing their implementations. Retain
state/record/authority hashes and require read-only repeated status to agree.

First validate the harness on a smaller universe, then measure 5,000 securities
and concurrent readers on the same database. No deployment certification,
provider completeness guarantee or actual broker state is manufactured: test
clocks and test identity are explicit fixtures. No NAS access is authorized.
The synthetic references/actions do not establish realistic retained-history
capacity; that limitation must remain visible in the ledger.

Review the HTTP caller's concurrency behavior independently. A SQL statement
timeout does not bound cumulative Python work or concurrent memory. Any code
change needed to enforce a resource boundary must be documented here before
implementation, with real concurrency acceptance and a removal falsifier.

## Decision: bound simultaneous panel builds

The three full-build HTTP routes (`/`, `/panel.json`, `/operational-health`)
currently enter the synchronous thread pool independently, multiplying the
entire status working set inside one 512 MiB panel container. Permit one such
request at a time in the deployed single worker. Contenders receive immediate
503 UNKNOWN with a five-second retry hint and no cached evidence. The HTML
response retries automatically; health, static assets and subscription enrollment
remain independent. Hold admission through response construction and release in
`finally`, including exceptions. Explicitly select one Uvicorn worker so an
environment worker override cannot silently multiply the process-local limit.

This limits simultaneous allocation; it does not make a single read's memory
or elapsed time bounded. Preserve that distinction in qualification results.
Tests must hold a real routed request while every other full-build route is
called, show that only one build starts, keep health responsive, and prove that
success and failure both release admission. Removing acquisition, release or
the deployment worker selection must fail the respective falsifier.

## CI layout correction

PR #417's Sentinel main lane failed only
`test_deployed_panel_cannot_multiply_workers` (5,145 other tests passed).
The test derived `/work` from its own path, but the certified test image stores
Compose under `/work/repo` and already exposes that location through
`SENTINEL_REPO_ROOT`. The test now follows that existing convention with the
normal checkout path as fallback. Worker-count and 512 MiB assertions remain
unchanged; no runtime or CI gate is relaxed.

Integrated verified main `e255a78aaf4f89d25fc634864aafd2656c6cd176`; retained
both ledger sections when resolving the documentation-only conflict. The
original measurements and source hashes above remain tied to their original
reviewed commits.

Local verification used offline `sentinel-test:ci` containers:

- CI filesystem layout, with reviewed test, panel app and Compose bind mounts:
  `python -m pytest tests/sentinel/test_panel_concurrency.py -q --tb=short -p no:cacheprovider`
  — 13 passed. The original test reproduced the exact `/work/docker-compose.sentinel.yml`
  missing-file failure. Removing `--workers 1` in a disposable Compose copy then
  failed the corrected test at its worker assertion.
- Read-only checkout, with empty `SENTINEL_REPO_ROOT` and no `.env` file:
  `python -m pytest tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel.py tests/sentinel/test_operator_monitoring.py -q --tb=short -p no:cacheprovider`
  — 160 passed in 41.65 seconds. Both runs retain the existing Starlette/httpx
  deprecation warning.
- `git diff --check` passed. Full GitHub checks rerun after publication; local
  targeted acceptance is not a claim that the complete CI run has passed.
