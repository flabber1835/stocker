# L03 cash identity acceptance

Scope and remaining gates: [local cash/fill closeout](../../../docs/stage-one-cash-fill-closeout.md).
Base: `eaae66f9e6626306f8b233fd723d25b278e13351` (owner merged #419 while
this work was in progress). `source-sha256.json` records the reviewed code
commit and exact production/test/campaign bytes; `artifact-sha256.json` records
retained evidence hashes. `raw-logs.zip` preserves successful and failed runs.

No NAS or real broker contact. Docker used `--network none --memory 4g --cpus 2`,
a read-only source mount copied into a disposable container, Python 3.12.13,
PostgreSQL 17.11 and psycopg 3.3.4. Local image `sentinel-test:ci`:
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
Both simulator profiles (`paper`, `live_cash`) are offline HTTP fixtures;
the latter name does not mean a real account was accessed.

## Exact validation

Run from repository root with Python 3.12 and the local test image:

```text
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_alpaca_simulation_durability.py tests/sentinel/test_alpaca_simulation_cash.py tests/sentinel/test_alpaca_execution_entrypoint.py tests/sentinel/test_issue_183_alpaca_hardening.py tests/sentinel/test_paper_close_nav_gate.py tests/sentinel/test_native_fill_acceptance.py tests/sentinel/test_native_fill_progression.py tests/sentinel/test_trial_fill_interval_evidence.py tests/sentinel/test_trial_fill_interval_proof.py
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_recovery_capability_boundary.py
python audit/economic_399/cash_zero_identity/run_local.py
python tools/validate_test_responsibility.py --base eaae66f9e6626306f8b233fd723d25b278e13351 --output ownership-zero-identity.json
python -m pyflakes sentinel/execution/alpaca.py sentinel/execution/broker_cash.py tests/sentinel/test_alpaca_execution_entrypoint.py tests/sentinel/test_alpaca_simulation_durability.py tests/sentinel/test_issue_183_alpaca_hardening.py audit/economic_399/cash_zero_identity/campaign.py audit/economic_399/cash_zero_identity/run_local.py
git diff --check
```

Host invocations used
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`;
pyflakes used `PYTHONPATH=C:/GitHub/stocker/.codex-tmp/lint-deps`.

- Final targeted regression: **248 passed, 33.19s**.
- Nested unaccepted producer boundary: **3 passed, 3.43s**.
- Final mutation controls: **12 passed, 5.58s**; **5/5 intended mutants detected**
  by missing changed-economics refusal (not import errors): decoder zero drop,
  durable consumer zero drop, nonzero replay guard, zero session guard,
  zero classification guard. Each mutant starts from restored source.
- Syntax parsing and pyflakes pass for seven changed Python files. Ownership
  validates 491 test modules with zero unowned tests. No new test module.

The acceptance fixture uses literal external-capital/P&L expectations, exact SQL
rows, and fresh connections. Corrections are published after both a new nonzero
withdrawal and zero fee, proving rollback of both persistence paths and cursor.
Zero evidence itself contributes no cash, external capital, or strategy return.

## Retained earlier outcomes

Initial reproduction on `daa43ca` with tests added, before code changes:
**6 failed, 2 passed, 20 deselected, 6.67s**. Four missing-refusal cases reproduce
nonzero→zero and zero→nonzero revisions; two positive zero identity controls
fail because no evidence was retained. The original nonzero-revision tests pass.

The first implementation attempted to insert zero rows in the cash ledger;
PostgreSQL correctly rejected its nonzero constraint (**10 failed, 234 passed**;
the first mutation controls also failed). Those logs remain for transparency.
The final design retains zero identity in the existing processed-session store
and preserves the ledger constraint. An intermediate version passed 244 tests
and 3/3 mutants before the extra metadata/rollback controls were added. These
intermediate counts are not added to the final coverage total.

No fixture repins, expected failures, production capability promotion or
provider-finality assumptions were introduced. Previously discarded zero
identities are recoverable only from actual retained complete source evidence.
