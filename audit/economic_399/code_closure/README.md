# Post-402 local code-review evidence

This is a new evidence package. `../pre_nas_402` and the historical golden
artifacts are unchanged. See [the disposition ledger](../../../docs/economic-code-closure.md).
Step 1 and economic certification remain open; known implementation, provider,
historical-input and deployed-evidence gates are listed separately there.

Base: `748d54e12a4cdb4b5403c56feb8d6b68e47d0104` (owner-merged #402).
`source-provenance.json` records changed-source SHA256 values. `SHA256SUMS.json`
checksums this package; it excludes itself. The final reviewed code commit and
delivery PR are recorded in `delivery.json` after the source commit exists.
Raw logs are stored byte-for-byte in `results.zip`, with individual hashes in
`raw-log-sha256.json`. Log names below refer to entries in that archive.

## Reproduction

`commands.json` retains selected pytest argument arrays, environment, exact local
image ID, the mutation names, and the ownership invocation. Each pytest command
is `python -m pytest <campaign selectors> -q --tb=short --show-capture=no -p
no:cacheprovider`; newer runs additionally used `-u` for unbuffered output.
The tests ran inside Docker with an empty `.env`, a read-only checkout,
`--network none`, `/repo` working directory and the recorded three environment
variables. PostgreSQL uses disposable container storage.

To repeat one campaign with an available PostgreSQL-capable test image:

```text
python audit/economic_399/code_closure/run_local.py notification-fence-green
python audit/economic_399/code_closure/run_local.py deployment-regression-final
python audit/economic_399/code_closure/run_local.py recovery-source-final
python audit/economic_399/code_closure/run_local.py continuation-restore-regression
python audit/economic_399/code_closure/run_local.py rolling-falsifiers
python audit/economic_399/code_closure/run_local.py deployment-global-fence
python tools/validate_test_responsibility.py --base 748d54e12a4cdb4b5403c56feb8d6b68e47d0104
git diff --check
```

Pass `--image <accepted-test-image>` to bind another qualified image. Run each
additional `commands.json` mutation name similarly. Internally each named audit
mutation runs `python tools/economic_audit_mutation_check.py <name>` and requires
its baseline to pass before the altered guard produces a test failure. The
rolling falsifier tool runs all 15 guards. Neither tool modifies production
files. A mutation's intended assertion failure is required, not a collection or
infrastructure error.

## Results and limits

| Retained output | Result |
|---|---|
| `notification-fence-green.log` | 126 passed, 50.71 s |
| `deployment-regression-final.log` | 77 passed, 10.35 s |
| `recovery-source-final.log` | 86 passed, 72.32 s |
| `continuation-restore-regression.log` | 41 passed, 582.64 s |
| `reconstruction-regression.log` | Earlier 81 passed, 616.89 s |
| `final-recovery.log` | Earlier 282 passed, 104.36 s; predates final notification schema/dispatcher additions |
| `mutation-*.log` | 22 successful new guard removals/changes; use `mutation-reconstruction-health-final.log` for that guard. `mutation-deployment-fence.log` includes both fence mutants. |
| `rolling-daily-falsifiers-final.log` | 15 killed |
| `static-final.json` / `ownership-final.log` | No introduced pyflakes findings / ownership PASS, 472 modules |

Counts overlap. Logs without a campaign definition are retained exploratory or
earlier regression evidence, not a claim of an additional final-head campaign.
The stalled `notification-occurrence.log`, initial fixture failures and an
initial surviving reconstruction-health mutant are deliberately retained.
See the ledger for corrections and their passing reruns. No passing result is
assigned to a terminated process. Older seams in the rolling falsifier driver
were updated to the actual source-precision and shared daily-commit guards;
the underlying acceptance expectations were preserved.

Local runtime: Python 3.12.13, PostgreSQL 17.11, psycopg 3.3.4. No NAS or real
broker account was accessed. No finality was inferred from an empty response,
no production capability was enabled, and no historical 20-year multiple was
computed. Paired recovery equality is not an independent oracle for every
strategy choice; its separate stop/cooldown and no-retroactive-order assertions
test the specific continuity contract. The full economic/reference and provider
gates from #402 remain separate.
