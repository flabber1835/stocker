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
fallback passed. The required Linux browser workflow must still pass with its
locked Chromium engine. The `webkit-iphone` project uses desktop WebKit with a
393 by 852 viewport. This does not qualify a physical iPhone, its installed
Home Screen lifecycle or real Apple push delivery.

## Scope and remaining release evidence

The required 100.00% branch-coverage gate in
`.github/workflows/sentinel-safety.yml` applies to
`sentinel.automation.service` and its complete automation lane. It is not a
claim of 100% coverage for the new panel modules. The separate repository
coverage workflow is advisory. Exact-head required CI and PR-target verification
remain the release evidence recorded with the pull request.

The broader local operator batch was stopped after 188 completed tests with no
failures reported; it is an incomplete run and supplies no passing batch total.
A narrowed replacement was still running when this evidence note was updated.
Neither that unfinished replacement nor pending exact-head CI is counted as
successful qualification here. Their completed results belong in the final PR
evidence.

No local Wealth Core or full repository suite was run for this operational
change. No production service, financial database, broker or installed software
was changed. Passing local tests demonstrates these contracts under the stated
fixtures; it does not establish production stability over time or qualify an
installation. Installation and activation require the later owner action.
