# Persistent owned impairment: implementation and synthetic evidence

Base verified by `git fetch origin main`:
`da7b64a9429c9c73fb7efac90c8d4a5decb39e13`.
Branch: `codex/persistent-owned-impairment`, PR-only delivery, no self-merge.
Design, complete rule, results and limitations:
[sentinel-owned-impairment.md](../../docs/sentinel-owned-impairment.md).

The stimulus helpers in `research/impedance` are reused from PR #431 at
`0070f4109257d6b42078ed081fe5ded347cf221f`. Only `make_origin` gains a factory
argument so each profile forms its own production state. Prices/scenario
functions are unchanged. The supporting component-study sources are included
so this branch is independently runnable before #431 merges; existing research
golden evidence is neither changed nor repinned. Production imports no research.

## Exact commands

Working directory:
`C:\GitHub\stocker\.codex-tmp\persistent-owned-impairment`.
Existing local runtime: Python 3.12.14, NumPy 2.4.6, pandas 3.0.5,
exchange_calendars 4.13.2, pytest 8.3.5. Paths below are machine-specific;
elsewhere use the repository dependencies and root/shared on PYTHONPATH.

```powershell
$env:PYTHONPATH="$PWD;$PWD\shared;C:\GitHub\stocker\.codex-tmp\classification-check-runtime"
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.impedance.compare_owned --output audit/owned-impairment

& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest tests/champion/test_owned_impairment.py tests/champion/test_owned_kernel.py research/impedance/test_owned_accounts.py -q -p no:cacheprovider --basetemp C:/GitHub/stocker/.codex-tmp/owned-tests-final --junitxml audit/owned-impairment/owned-tests.xml

& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m tools.owned_impairment_mutations --output audit/owned-impairment/mutations.json --scratch C:/GitHub/stocker/.codex-tmp/owned-mutants

& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest tests/champion/test_controller.py tests/champion/test_authority.py tests/sentinel/test_canonical_session_kernel.py tests/sentinel/test_production_decision.py tests/sentinel/test_state_hash_allocations.py::test_private_canonical_view_preserves_trimming_and_public_ownership tests/sentinel/test_production_state.py::test_reload_is_identical_and_does_not_alias_prior_state tests/sentinel/test_production_state.py::test_failure_leaves_the_prior_envelope_authoritative tests/sentinel/test_production_state.py::test_repeated_serialization_cycles_preserve_every_production_output -q -p no:cacheprovider --basetemp C:/GitHub/stocker/.codex-tmp/owned-regressions --junitxml audit/owned-impairment/regressions.xml

& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m compileall -q sentinel/controller/owned_impairment.py sentinel/controller/champion_config.py sentinel/controller/ex3_v6.py sentinel/controller/machine.py sentinel/controller/median5.py sentinel/core/session.py sentinel/core/kernel.py sentinel/core/decision.py sentinel/strategy.py research/impedance tests/champion/test_owned_impairment.py tests/champion/test_owned_kernel.py tools/owned_impairment_mutations.py
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe tools/validate_test_responsibility.py --base origin/main --output audit/owned-impairment/test-ownership.json
git diff --check
git diff --cached --check
```

## Results

- Full seven-scenario comparison: exit 0. Each profile runs 252 feature-warmup,
  80 formation and 840 scenario transitions. All paired Core states, ledgers
  and observations agree. Eight restart cuts per case/profile: 112 matches.
- New checks: **25 passed in 26.02s**. This includes the production-kernel
  acceptance case, independent account arithmetic and causal opening timing.
- Compatibility regressions: **52 passed in 17.03s**. The old champion's frozen
  transitions/authority and canonical serialization remain covered.
- Mutations: **4/4 killed** by real assertion failures, not import/setup errors:
  disabled entry, seven-session early recovery, bypassed final ceiling through
  the kernel, and ignored snapshot cursor. Production files are not rewritten.
- Syntax, normalized source manifest, whitespace and test ownership pass.
  New `tests/champion` tests inherit its protected CI responsibility. Research
  account tests and this mutation driver are explicitly invoked local checks.
- A repeat after schema/cursor checks were tightened and top-level cause
  reporting added has exactly the same seven economic summaries. No scenario,
  severity or timing parameter was changed in response to returns.

No broad Wealth Core/full repository test run, database campaign, NAS access,
real broker request, live credentials or strategy activation occurred.

## Artifacts

- `comparison.json.gz`: complete profile identities, source hashes, daily
  observations/decisions, owned memory, Core and account economics, trades,
  fees and restoration cuts. Deterministic gzip, normalized-source hashes.
- `summary.json`: final marked account values, drawdown, costs and transitions.
- `owned-tests.xml`, `regressions.xml`: final passing test results.
- `mutations.json`: mutation names and actual failing assertions.
- `test-ownership.json`: test responsibility verdict.
- `initial-controller-tests.xml`: retained intermediate 40-pass/1-fail result
  for the fixture's incorrect assumption that existing LD exposure stayed at
  one. The final positive assertion distinguishes its actual 0.55 ceiling from
  the new zero ceiling. This file is historical diagnostic evidence, not the
  final validation verdict.

`comparison.json.gz`: **808,656 bytes**,
SHA256 `eb190a1b596434cb8c0e74fee4f2e963e4b154f2f3a61279fc48265388f8305f`.

Source hashes identify named files; they are not a complete dependency lock.
The simulator uses production whole-share projection with ideal next-open fills
and a zero-yield defensive asset, not the broker command journal or a calibrated
execution model. The $100,000 accounts are established at the scenario-origin
close so the first overnight shock is included. Capital, costs and timing are
identical across strategies. There is no historical CAGR or performance
certification claim.
