# Testing Sentinel

The production system uses Alpaca market data and OpenFIGI classification,
the canonical Wealth Core shadow book, Sentinel exposure control and one
broker-facing execution membrane. Tests should exercise those contracts.
Normalized historical fixtures and frozen economic oracles retain their exact
identities; they are not evidence of current-provider acquisition or deployment
readiness.

Read [the operational ground truth](sentinel-deployment.md) first. Use targeted
tests by default, as required by `AGENTS.md`. Do not run `make test` or the
Wealth Core suite merely because another component changed.

## Inventory and ownership

[`tests/test-responsibility.json`](../tests/test-responsibility.json) is the
permanent execution inventory. Its pytest owners cover:

| Owner | Scope |
|---|---|
| `sentinel.complete` | Current-provider acquisition, formation, daily transitions, controller, execution, recovery, operator presentation and their boundaries |
| `production-champion.regressions` | Champion, median5 and V5 economic/ownership regressions |
| `wealth-core.prospective` | Canonical Wealth Core contracts and the explicitly scoped historical golden quarantine |
| `scripts.operator` | Installer, command, certification, CI and evidence tooling |
| `backup.reliability` | Backup media, integrity, lifecycle, recovery and maintenance |
| `production-composition.authority` | Cross-process operational composition and interruption boundaries |
| `internal-state.contract` | Independent state/accounting oracles and infrastructure composition |
| `core.infrastructure` | Shared broker/SQL/filesystem infrastructure |

The separate `host-python38.compatibility` owner executes under Python 3.8.15.
Command owners run additional mutation and generated campaigns in CI. Delegated
owners name contracts already exercised by an execution owner; they do not
repeat that owner's pytest suite.

List the current Python 3.12 module inventory without running tests:

```bash
python tools/local_test_runner.py --list
python tools/local_test_runner.py --list --owner core.infrastructure
```

New test modules must have a permanent owner. The local runner refuses unowned
modules, duplicate ownership and empty owners. CI independently verifies exact
collection, authorized outcomes and complete same-attempt evidence. See
[CI sharding](sentinel-ci-sharding.md) and
[CI hardening](ci-suite-hardening.md).

## Reproduce targeted tests

Use Linux containers through Docker, Bash, GNU Make and Git. The runtime and
test lens pin the interpreter/base image and install hash-checked dependency
closures from `sentinel/requirements.lock` and `tests/requirements.lock`.
There is no second floating development dependency list.

Build the local test lens after changing source:

```bash
make test-image
docker run --rm --network none sentinel-test:local \
  tests/sentinel/test_fixture_compatibility.py -q -ra
```

The test lens contains the source it was built from. Rebuild after edits; an
older local image does not test the current checkout. Local image tags and
results confer no CI, deployment, economic or broker authority. The runner
passes no broker credentials and mounts only its diagnostic output directory.

To run one complete pytest owner with independent collection and outcome checks:

```bash
bash scripts/run-tests.sh --owner core.infrastructure
```

`SENTINEL_TEST_IMAGE` selects an already built lens. Set
`SENTINEL_TEST_EVIDENCE` to retain JUnit and `execution.json` in a chosen host
directory; otherwise the launcher creates a temporary directory and prints it.
Each owner runs in a fresh interpreter. Temporary source caches, backup-policy
identity and private PostgreSQL fixtures cannot become deployed authority.

## Complete local pytest and minimum-host checks

When a complete Python 3.12 pytest run is explicitly wanted:

```bash
make test
```

This builds the pinned images and runs every permanent Python 3.12 pytest owner.
The runner independently collects each complete owner, compares exact JUnit
instances and rejects omitted tests, empty execution, unauthorized skips,
unexpected expected failures and stale JUnit. Only the exact settled Wealth
Core expected failures in the authority may remain non-passes. A repaired
golden unexpectedly passing also requires an intentional authority change.
Historical certification scope remains documented in
[Wealth Core certification](wealth-core-certification.md); do not repin a golden
to make CI green.

For an owner subset while rebuilding current source:

```bash
make test TEST_RUNNER_ARGS='--owner core.infrastructure -- -vv'
```

Display options may follow `--`. Filtering a complete owner with `-k`, `-m` or
`--deselect` cannot produce a complete-owner pass; use direct targeted pytest
commands for partial runs.

Run the distinct minimum-host owner with an installed Python **3.8.15**:

```bash
make test-host HOST_PYTHON=/path/to/python3.8
```

The existing owner tool refuses a different interpreter. Python 3.12 execution
cannot substitute for this compatibility proof. Complete local pytest plus
host checks still do not replace CI's mutation campaigns, physical process and
recovery harnesses, protected scope proofs, signed artifact binding or image
publication checks.

## Fixtures, coverage and performance

New and renamed Sentinel test modules use real schema, source and producer
validation by default. `tests/sentinel/legacy-fixture-modules.txt` is a finite
opt-in registry preserving older doubles while they migrate. Do not add new
modules by default. Dedicated real-guard witnesses and the million-row warmup
keep their existing validation boundaries. Shared synthetic market/HTTP helpers
live under `tests/support`; helper reuse is not a second strategy implementation.

Automation-service branch coverage remains a mandatory CI gate. The manually
dispatched repository coverage campaign measures the complete Python 3.12
pytest owners using the same pinned lens, authenticates source paths and retains
per-domain branch/statement reports. Unimported source stays in the denominator.
Its initial result is an advisory baseline; shell and browser execution are
explicitly unmeasured by Python coverage. Coverage percentages complement
independent economic oracles, recovery cuts, mutation falsifiers and real SQL.

Use retained JUnit module timings to balance CI work. Keep meaningful independent
boundary tests even when assertions look alike. Preserve per-test database and
book isolation; do not share mutable strategy state to obtain a timing gain.
The million-row fixture remains in one worker so its source acquisition is not
repeated across shards. Targeted changes require directly relevant checks and a
falsifier shown to fail when each new guard is broken.
