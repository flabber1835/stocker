# Stage 1: exact cash reconciliation

Reviewed base: `daa43caf995779bfa7e67195785520744021cb45`, independently
refetched from `flabber1835/stocker:main`. Delivery is a separate feature PR;
the unrelated PR #419 workflow assertion fix is delivered on #419 itself.

**P2 implementation defect, locally fixed.** The production caller in
`sentinel/paper/cash.py:232` multiplied durable cumulative quantity/average price,
added signed notionals and subtracted native-activity baselines under the ambient
Decimal context. This could round the admission comparison across its unchanged
$1 bound. It could also change `expected_cash` in the retained, non-renewable
120-second endpoint-lag identity when caller precision changed after restart.
No evidence establishes that a deployed account or historical return was affected.

Example: plan cash $1,000 and a one-share buy costing $100 plus 10^-30 dollars
leave expected cash $900 minus 10^-30. Observed $901 is outside the tolerance;
the old arithmetic accepted it. This is a small boundary error, not evidence of
a material historical return error. Reduced-precision tests additionally check
ordinary balance tolerances. Wealth Core and controller decisions are unchanged.

The contract decision was recorded in `docs/sentinel-execution-contract.md`
before implementation. Production now evaluates finite-decimal sums/products
as exact fractions and uses an independently sized, inexact-trapping Decimal
context solely to render the terminating result. Durable quantities, prices,
cash baselines, tolerance and ownership/finality rules are unchanged.

## Local acceptance and falsifiers

Tests use actual isolated PostgreSQL command/baseline persistence and fresh
connections after commit. The economic oracles use 100-digit Decimal arithmetic
and scaled integers, independently of production Fraction arithmetic.

```text
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_cash_grace_identity.py tests/sentinel/test_paper_close_nav_gate.py tests/sentinel/test_paper_activation.py tests/sentinel/test_alpaca_simulation_durability.py
133 passed in 54.09s
```

After strengthening the final comparison falsifier from 10^-26 to 10^-30,
the complete changed module passed again: **20 passed in 9.60s**. Four mutants
then failed their intended acceptance assertion: rounded final comparison,
rounded fill product, omitted activity delta, and rounded grace identity.
The first comparison mutant initially survived the weaker 10^-26 case; its
survival prompted the stronger independent boundary case. It is not counted as
a detection. All four final mutations are detected, with source restored after
the campaign. No import/setup failure counts as a killed mutant.

Run the following in a disposable Linux copy of this source using the existing
test image; the mutation runner intentionally edits that disposable copy:

```sh
python -m pytest tests/sentinel/test_cash_grace_identity.py -q --tb=short -p no:cacheprovider
python audit/economic_399/cash_precision/mutations.py
```

Actual container controls: `docker run --rm --network none --memory 4g --cpus 2`
with read-only source mounted at `/source`, copied to `/tmp/repo` before execution,
and `PYTHONPATH=/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts`,
`SENTINEL_REPO_ROOT=/tmp/repo`, `PYTHONDONTWRITEBYTECODE=1`.
Image: `sentinel-test:ci`,
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
This is local source validation, not an exact deployed-image qualification.

`python tools/validate_test_responsibility.py` passes: 491 modules, zero unowned.
AST parsing passes for all three changed Python files. `python -m pyflakes`
reports eleven existing unused imports in the cash module, identical to base;
there are no new warnings. `git diff --check` passes. Retained `regression.log`,
`mutations.log` and `sha256.json` bind the results and reviewed Python bytes.

## Remaining gates and deployment handoff

This closes one cash-consumer precision defect. It does not certify the upstream
cash producer, provider exhaustiveness/fixed-close finality (C1/F6), native fill
correction/bust/average-price guarantees (F19), or predecessor ownership and
negative-space evidence (C3). No capability flag was enabled. The complete
code-review ledger still contains open gates; no zero-defect claim is made.

Before NAS qualification, merge only after required exact-head/merge CI passes,
then build the authorized image for the merged source and use the documented
continuation/admission procedure. Preserve existing databases, golden evidence,
and the $1 tolerance. Run the deployment/backup/restore and resource procedures
in `docs/sentinel-deployment.md` and the existing Stage 1 handoff; retain image,
schema/source identities, scheduler/retention evidence, restore/restart results
and measured real-universe capacity/latency. Pass only with matching identity,
successful recovery and no unexplained economic differences. Synthetic local
tests do not substitute for those observations. No NAS or broker was contacted.
The full historical backtest and economic deltas remain deferred Stage 2 work.
