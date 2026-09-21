# Current Sentinel parameter comparison

Verified main base: `ee23c894c97a2c4023654ce3a56a62728f5b061e`.
Branch: `codex/sentinel-parameter-probes`; PR-only research delivery.
Design, predefined parameters, all results, and economic explanations:
[sentinel-parameter-probes.md](../../docs/sentinel-parameter-probes.md).

Production code/configuration is unchanged. The same canonical Core stream feeds
five isolated research controllers; no candidate receives a production identity
or influences Core. This is a parameter experiment, not deployment certification
or a twenty-year backtest. No NAS/broker requests or historical inputs were used.

## Provenance

The eight pre-existing `research/impedance` helper files are copied unchanged
from #432, commit `7250ce3d65cc38a103989d460fe3c557a38343c8`, including PR #431's
unchanged synthetic prices. They make this branch independently runnable before
the other PRs merge. The account arithmetic/timing tests reuse #432's test file
under a new name, replacing only the profile factory with current production.

`reference-owned-summary.json` is an unchanged copy of #432's retained summary,
SHA256 `704879dcc183ace38a10824f1ace2a5c1f6e77b03a918c13f52cecb6d06a0849`.
Only its `current` rows are comparison oracles. The new comparison does not
implement or rerun #432's owned-impairment profile. Existing golden artifacts
are preserved unchanged.

## Exact commands and results

Local working directory:
`C:\GitHub\stocker\.codex-tmp\sentinel-parameter-probes`.
Existing runtime: Python 3.12.14, NumPy 2.4.6, pandas 3.0.5,
exchange_calendars 4.13.2, pytest 8.3.5. Machine-specific paths below can be
replaced by a repository-compatible environment with root/shared on PYTHONPATH.

```powershell
$env:PYTHONPATH="$PWD;$PWD\shared;C:\GitHub\stocker\.codex-tmp\classification-check-runtime"
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest research/impedance/test_parameters.py -q -p no:cacheprovider --basetemp C:/GitHub/stocker/.codex-tmp/parameter-unit --junitxml audit/parameter-probes/parameter-tests.xml
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest research/impedance/test_parameter_accounts.py -q -p no:cacheprovider --basetemp C:/GitHub/stocker/.codex-tmp/parameter-accounts --junitxml audit/parameter-probes/account-tests.xml
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.parameter_mutations --output audit/parameter-probes/mutations.json --scratch C:/GitHub/stocker/.codex-tmp/parameter-mutants
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.compare_parameters --output audit/parameter-probes --reference audit/parameter-probes/reference-owned-summary.json
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m compileall -q research/impedance
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe tools/validate_test_responsibility.py --base origin/main --output audit/parameter-probes/test-ownership.json
git diff --check
git diff --cached --check
```

- Parameter mechanisms, isolation, identity and restart: **16 passed in 0.37s**.
- Independent whole-share/fee arithmetic and opening timing: **3 passed in 12.88s**.
- Deliberately disabled identity and production-target parity guards: **2/2
  killed** by expected assertion failures, not import/setup errors.
- Seven markets x five profiles x 120 sessions: comparison exit 0; **920 distinct
  production-control closes agree**, **280 controller** and **280 account**
  restart pairs agree. Baseline economics exactly match all seven reference rows.
- Syntax and test responsibility pass. Research tests/mutations are explicitly
  invoked local checks, outside the production test ownership roots. No new
  runtime tests, certification status change or unrelated full suite.

## Retained evidence

- `results.json.gz`: all observations, leadership, native/overlay states and
  decisions, account trades, fees, positions and NAV; source/parameter identities,
  source hashes, reference hash, formation and restart cuts.
- `summary.json`: all five profiles' NAV/drawdown/costs and dated transitions.
- `reference-owned-summary.json`: immutable prior baseline input.
- `parameter-tests.xml`, `account-tests.xml`, `mutations.json`,
  `test-ownership.json`: executable check evidence.

`results.json.gz`: **583,777 bytes**, SHA256
`ac431bb3258cdf240e2b841e7e8a9b5b47711fa924bba9d62a5d77f32c433bfa`.

Named-source hashes are normalized text hashes, not a dependency lock. Synthetic
accounts use ideal next-open fills, 10 bps costs and zero bill yield. They exercise
production whole-share projection but do not establish durable broker transport,
real slippage, provider completeness, historical performance or expected returns.
