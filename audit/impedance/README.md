# Synthetic Core/Sentinel interface evidence

Reviewed production base: `da7b64a9429c9c73fb7efac90c8d4a5decb39e13`.
Decision and interpretation: [investigation](../../docs/core-sentinel-impedance.md).
Production decisions, configurations and golden artifacts are unchanged.

The later [coherent market pipeline extension](pipeline-validation.md) retains
seven generated-market runs through production warmup, Core and controller.
Its results and limitations are separate from the component evidence below.

## Results

- Nine synthetic path families; 960 Native transitions including warmup and
  restart after every transition. These are supplied controller observations,
  not a full market/canonical-book replay.
- 38 bounded-breadth cases with an exact-rational independent oracle.
- Real production peer-breadth calls on seeded ownership and flat prehistory;
  this isolates individual damage and has no residual-correlation edges.
- Canonical V5 adapter generates stops at the first close and executes ten
  sales at the next open. Independent dollar arithmetic verifies fees/cash/NAV.
- Two recovery population probes, compared uninterrupted versus restored.
- `12 passed` diagnostic tests; `19 passed` existing champion regression tests.
- Both in-memory mutants killed by assertion failures (not collection errors).
- Syntax compilation, diff whitespace and repository test responsibility checks
  pass. Research tests are manually invoked diagnostics, not added protected CI
  coverage. No broad Wealth Core, NAS, broker or full repository test run.

## Exact local commands

Run in `C:\GitHub\stocker\.codex-tmp\core-sentinel-impedance`.
The interpreter is existing Python 3.12.14, NumPy 2.5.3, pytest 8.3.5.

```powershell
$env:PYTHONPATH="$PWD;$PWD\shared"
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.study --output audit/impedance/synthetic-results.json
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest research/impedance/test_study.py -q -p no:cacheprovider --junitxml audit/impedance/diagnostic-tests.xml
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.mutations --output audit/impedance/mutation-results.json
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m compileall -q research/impedance

$env:PYTHONPATH="$PWD;$PWD\shared;C:\GitHub\stocker\.codex-tmp\classification-check-deps"
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest tests/champion/test_controller.py tests/champion/test_authority.py -q -p no:cacheprovider --basetemp C:/GitHub/stocker/.codex-tmp/impedance-champion-regression-3 --junitxml audit/impedance/champion-regression.xml
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe tools/validate_test_responsibility.py --base origin/main --output audit/impedance/test-ownership.json
git diff --check
git diff --cached --check
```

The regression interpreter initially lacked `cryptography`; the already-present
dependency directory above resolved collection without changing dependencies or
production code. The first mutation attempt exposed duplicate Python import
names in the new research test; absolute imports fixed the probe. The final
mutation result deliberately removes the production damage-acceleration gate
or the research memory expiry in isolated child processes. Both selected tests
fail as expected; parent exit is zero only when every mutant is detected.

For another checkout, use an environment with the repository's dependencies and
its root and `shared` on `PYTHONPATH`, replacing the machine-specific interpreter
and scratch paths. Source hashes in `synthetic-results.json` normalize line
endings, record the measured runtime and cover the named inspected modules;
they are not a complete dependency/environment lock.

## Evidence files

- `synthetic-results.json`: generated traces, source hashes and measurements.
- `run-summary.txt`: readable summary from the same producer.
- `diagnostic-tests.xml`, `champion-regression.xml`, `champion-regression.log`:
  retained local test results.
- `mutation-results.json`: mutations, selected tests and their actual failures.
- `test-ownership.json`: repository test-responsibility validation.

These artifacts verify mechanical examples and reproduction. They do not
establish a false-exit frequency, loss guarantee, winning replacement policy,
twenty-year performance or economic certification. No historical dataset was
loaded by the synthetic study.
