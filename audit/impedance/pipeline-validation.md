# Coherent synthetic pipeline: local validation

Production base: `da7b64a9429c9c73fb7efac90c8d4a5decb39e13`.
Research delivery: PR #431, extending prior research commit
`8434c16dc5a5ddc5c6a37fba3f7d203129341aa6`.
Interpretation and registered stimuli: [study](../../docs/core-sentinel-pipeline-study.md).

## Commands and results

From `C:\GitHub\stocker\.codex-tmp\core-sentinel-impedance`, using the existing
Python 3.12.14 runtime with NumPy 2.4.6, pandas 3.0.5, exchange_calendars 4.13.2
and pytest 8.3.5:

```powershell
$env:PYTHONPATH="$PWD;$PWD\shared;C:\GitHub\stocker\.codex-tmp\classification-check-runtime"
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.pipeline --output audit/impedance
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest research/impedance/test_pipeline.py research/impedance/test_study.py -q -p no:cacheprovider --junitxml audit/impedance/pipeline-tests.xml
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.pipeline_mutations --output audit/impedance/pipeline-mutations.json
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m compileall -q research/impedance
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe tools/validate_test_responsibility.py --base origin/main --output audit/impedance/pipeline-test-ownership.json
git diff --check
git diff --cached --check
```

- Pipeline exit 0: seven 120-session branches, 80 formation transitions and 252
  feature-warmup sessions; 49 restart checks, 49 order checks, 49 no-mutation
  checks, 920 NAV reconciliations, owned split-neutrality control passed.
- Targeted tests: **22 passed in 9.42s**. Twelve earlier research tests plus ten
  new tests; no full Wealth Core or unrelated suite run for this extension.
- Two new mutations: removed the NAV assertion or split dollar-equivalence
  assertion in isolated processes. Both falsifiers fail with `DID NOT RAISE`;
  parent reports both `killed: true`, exit 0. Production files were not changed.
  Prior two component mutations remain separately retained. The split-validator
  falsifiers consume retained pipeline rows; the actual pipeline run above is
  the integration evidence, not those intentionally corrupted rows.
- Syntax and test-ownership validation passed. Research tests are explicitly
  run diagnostics, not a new protected CI responsibility owner.
- The initial full pipeline run passed. Instrumentation was subsequently
  enriched and empty-book attribution made explicit. The repeated run's existing
  economic observations, decisions and summaries were exactly unchanged.

This dependency directory already existed locally. The bare older interpreter
environment could not obtain the requested exchange calendar; the repository's
existing replay dependency environment resolved that setup issue. No dependency
or runtime code was modified. Use an environment with these versions and repo
dependencies elsewhere; the machine-specific paths are not portable commands.

The source hashes normalize source text to LF. They identify named modules and
strategy identity; they are not a complete environment lock. Scalar dollar
comparisons use the explicit tolerances in the research code; split observation
and decision comparisons are exact. The artifact contains Core shadow NAV,
not Sentinel-account NAV or alternative-policy returns.

## Retained evidence

- `pipeline-results.json.gz`: deterministic gzip JSON, all formation/branch
  observations, decisions, current-session events, Native evidence, capital,
  cohort attribution, source hashes, runtime and verification cut indices.
- `pipeline-summary.json`: human-readable per-scenario results.
- `pipeline-tests.xml`: final local tests.
- `pipeline-mutations.json`: actual mutation failure output.
- `pipeline-test-ownership.json`: PASS responsibility verdict.

Final pipeline artifact size: **382,914 bytes**.
SHA256: `bd7b90d27ac44136876a742cf8c432730f30c992efa673fa9b091c5ca2b0e100`.

For inspecting the compressed evidence with any compatible Python:

```python
import gzip, json
from pathlib import Path
report = json.loads(gzip.decompress(Path('audit/impedance/pipeline-results.json.gz').read_bytes()))
print(report['cases']['staggered_damage']['records'][15])
```

PR #431's earlier composition run `35647615400` failed during artifact upload
finalization with HTTP 403. The aggregate composition check then failed because
its dependency failed; this was not a reported economic assertion failure.
The research update triggers fresh CI. Green CI would still not certify returns.
