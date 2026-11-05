# Operational state contract: qualification evidence

This records local qualification of the operational-state candidate on
2026-11-05. The implementation design is
[operational-state-contract.md](operational-state-contract.md). The verified base
is `4122aa29bc86dcf5c4e5d6a91047030a95bf9890`. Delivery is a validated pull request;
this work does not install, activate or merge the candidate.

## Test environment

Focused Python tests ran in the existing
`sentinel-operational-state-tests:local` Python 3.12 image, with no network, no
production credentials, one CPU and a 2 GiB memory limit. Relevant fixtures used
private PostgreSQL and actual spawned processes. The worktree was mounted at
`/work`, with `PYTHONPATH=/work:/work/shared`. The local runner's exact invocation
form was:

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-run-tests.py <test paths> -q
```

That runner executes the following container command, appending the requested
test arguments:

```sh
docker run --rm --network none --cpus 1 --memory 2g --pids-limit 256 \
  --mount type=bind,src=/mnt/c/GitHub/stocker/.codex-tmp/operational-state-contract,dst=/work \
  --workdir /work --env PYTHONPATH=/work:/work/shared \
  --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python \
  sentinel-operational-state-tests:local -B -m pytest -p no:cacheprovider <test paths> -q
```

## Automation coverage owner

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-sourcewake-coverage.py
```

Result: **716 passed**, with **100.00%** statement and branch coverage for
`sentinel.automation.service` (917 statements and 372 branches). The local
evidence helper selects the complete owner through `automation_modules`, runs
pytest under `coverage.Coverage(branch=True, source=['sentinel.automation.service'])`
and refuses a result below 100%. This used the existing Python 3.12
`sentinel-live-url-tests:local` image with the same isolated resource and network
limits. It does not claim 100% coverage for the new panel modules.

## Focused observer and durability evidence

These directly observed batches overlap. Their counts must not be added to
represent unique tests. They qualified their respective implementation stages;
the final required CI checks must also pass on the submitted commit.

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-run-tests.py tests/sentinel/test_observer_failure_diagnostics.py tests/sentinel/test_observer_attempt_store.py tests/sentinel/test_operational_read_projection.py::test_reader_reports_changed_expired_periodic_and_failure_work_reasons tests/sentinel/test_verifier_transient_recovery.py -q
```

Result: **75 passed in 40.07 seconds**. This includes typed private-cause
diagnostics, subject supersession, original finite deadlines, retry cadence,
clock regression, identity-read failure, negative-result fingerprints and the
existing periodic-refresh regression.

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-run-tests.py tests/sentinel/test_observer_failure_review.py tests/sentinel/test_dashboard_review.py tests/sentinel/test_observer_attempt_store.py tests/sentinel/test_verifier_transient_recovery.py -q
```

Result: **72 passed in 50.60 seconds**. Actual PostgreSQL tests cover a failed
attempt healing before any projector or HTTP pass, one durable native review
event per failed attempt, retention across replacement/restart, atomic rollback,
authentication and owner fencing. Missing completion time remains missing.

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-run-tests.py tests/sentinel/test_operational_projection_worker.py -q
```

Result: **14 passed in 31.59 seconds**. Actual spawned-process tests cover import
and intent-memo reuse with fresh mutable reads, changed source-version reload,
bounded timeout/reaping, a fresh process after timeout, strict bounded metadata,
private exception-message exclusion and parent death while the child is inside
a blocked call. Guard-removal controls execute for the deadline, retained
failure, authentication, owner-fence, native-note and parent-death invariants.

## Final frozen source seal

After production files were frozen, an independent run completed:

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-run-tests.py tests/sentinel/test_url_selected_source_basis.py -q
```

Result: **116 passed in 327.20 seconds**. The candidate map contains 450 Python
source entries. The separately normalized and checksummed
`sentinel/url_selected_source_basis.py` completes the 451-file Python source
closure: its normalized bytes are bound by `module_sha256`, and its profile pin
authenticates the JSON profile. The JSON profile is an additional artifact,
not the 451st source file. The SHA256 of
`sentinel/url-selected-trading-transition.json` at this run was:

```text
aabcb71e0ac54ba91a76c60ff6209a7a3f90c6993beff650e27569b5af10262f
```

The source-basis tests retain exact authenticated predecessor maps and the
existing economic/history mappings; this is source identity qualification, not
a new economic certification.

## Complete affected regression selection

The final repeated selection of 66 directly affected modules completed with
**2,309 passed, no failures, in 641.72 seconds**. It includes panel and observer
modules, durable projection/review, independent scope currentness, source waits,
finite workers, automation composition, operator monitoring and test ownership.
The exact local command was:

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/run-operational-targeted-fast.py
```

The task-owned runner and its 66-module manifest are local evidence helpers,
outside the delivered source tree. It used a fresh native Linux volume and the
same Python 3.12 test image and limits above. Native `git archive` captured commit
`13f372f3084565793d325e2ec28d74e8f98f88a5`, excluding only `sec-filings`, matching
CI's sparse checkout policy. All 2,623 archived files were checked against their
Git blob identities. Its 107,079,680-byte archive has SHA256:

```text
4ce8df97b8b1cf712c9ed7ff4263914999815424f36a393699e488af83943aae
```

The runner overlaid the four corrected test fixtures and recorded their exact
hashes with the arguments and JUnit output. All 451 runtime Python files and the
transition profile were verified against the working candidate before the run;
production source remained unchanged during fixture corrections. The native
volume avoids Windows-mounted filesystem timing effects. This is test-fixture
qualification, not a production database benchmark.

The extracted segment-disclosure source regression was also qualified after
retargeting its four unchanged warning assertions to the actual imported helper:

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-fast-run-tests.py --overlay-test tests/sentinel/test_operational_readiness_regressions.py tests/sentinel/test_operational_readiness_regressions.py -q
```

Result: **9 passed in 3.32 seconds**. The runtime source remained identical.

## Genuine current-workflow composition

The current-profile workflow uses its real generated inputs, financial
authority parsers, formed book, signed PAPER callbacks, notification path and
HTTP application. Its disposable database installs the existing presentation
schema while fenced. Real HTTP startup records its incarnation before the
independent spawned worker publishes the operational snapshot. Only the
disposable external trust-root and issuer-reference file inputs are redirected;
their original parsers and all production guards remain in use.

```powershell
wsl -d Ubuntu -- python3 -B /mnt/c/GitHub/stocker/.codex-tmp/operational-state-fast-run-tests.py --overlay-test tests/sentinel/test_current_operational_workflow.py --overlay-test tests/support/current_workflow_run.py tests/sentinel/test_current_operational_workflow.py -q -s --tb=short
```

Result: **3 passed in 752.00 seconds**. Actual spawned collection, publication
and worker cleanup took **3.108 seconds**, within the unchanged 20-second
collection deadline. Existing verified-book/20-slot, PAPER classification,
completed-cycle/reconciliation identity and real JSON/HTML assertions passed.
This qualifies the complete private generated-data path; it does not measure
the production database or establish production performance.

## Browser qualification

The candidate server ran in the separately owned local container
`sentinel-operational-state-browser-20261105` at
`http://127.0.0.1:18064`, without a production database or credentials. It served
the real standalone negative template. Existing Windows Playwright 1.63 and
installed browser engines were used; no package or browser installation was
needed.

The final command was:

```powershell
$env:NODE_PATH='C:/GitHub/stocker/tests/browser/node_modules'
$env:SENTINEL_BROWSER_BASE_URL='http://127.0.0.1:18064'
$env:SENTINEL_BROWSER_CHANNEL='msedge'
node C:/GitHub/stocker/tests/browser/node_modules/@playwright/test/cli.js test --config C:/GitHub/stocker/.codex-tmp/operational-state-contract/tests/browser/playwright.config.js --workers=1 --retries=0 --output=C:/GitHub/stocker/.codex-tmp/operational-state-contract/tests/browser/test-results/final-qualified
```

Result: **47 passed, 17 expected engine-specific skips, no failures**, in 1.1
minutes. This covers the two configured projects, real negative-template layout
and details, banner assets, page resume and finite neutral expiry, a PARTIAL
response on launch, and Chromium service-worker/offline/reopen, permission and
synthetic-push paths. Local failure traces and final results remain in ignored
`tests/browser/test-results` artifacts.

The Chromium project used installed Microsoft Edge **156.0.4314.58**. The
Playwright-managed Chromium binary failed before navigation with
`browserType.launch: spawn UNKNOWN` on this Windows host; the approved Edge
fallback passed. Required Linux browser run `42066947086` subsequently passed
on source commit `13f372f3`: **47 passed, 17 expected skips in 37.5 seconds**, using
the workflow's locked WebKit and Chromium engines. Later test-fixture-only
commits still require their own exact-head CI. The `webkit-iphone` project uses
desktop WebKit with a
393 by 852 viewport. This does not qualify a physical iPhone, its installed
Home Screen lifecycle or real Apple push delivery.

## Scope and remaining release evidence

The required 100.00% branch-coverage gate in
`.github/workflows/sentinel-safety.yml` applies to
`sentinel.automation.service` and its complete automation lane. It is not a
claim of 100% coverage for the new panel modules. The separate repository
coverage workflow is advisory. Exact-head required CI and PR-target verification
remain the release evidence recorded with the pull request.

Incomplete local batches supply no passing totals. Required exact-head CI and
the final PR target are verified separately; their completed results belong in
the pull request evidence.

No local Wealth Core or full repository suite was run for this operational
change. No production service, financial database, broker or installed software
was changed. Passing local tests demonstrates these contracts under the stated
fixtures; it does not establish production stability over time or qualify an
installation. Installation and activation require the later owner action.
