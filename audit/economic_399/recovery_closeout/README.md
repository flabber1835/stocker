# Stage 1 L04 compound recovery evidence

Reviewed production base: `daa43caf995779bfa7e67195785520744021cb45`.
Production source is unchanged. See the
[caller/persistence review and remaining gates](../../../docs/stage-one-recovery-closeout.md).

Two validation gaps are repaired: crash/absence/later-shadow cases previously
ran separately, and the C3 takeover fixture lacked valid completion evidence
beneath its fence. No new production defect was demonstrated in this campaign.

## Commands and results

```sh
python audit/economic_399/recovery_closeout/run_local.py all
python audit/economic_399/recovery_closeout/run_local.py mutations
python -m pyflakes tests/sentinel/test_historical_recovery_process_death.py tests/sentinel/test_strict_recovery_predecessor.py audit/economic_399/recovery_closeout/campaign.py audit/economic_399/recovery_closeout/run_local.py
python tools/validate_test_responsibility.py --base daa43caf995779bfa7e67195785520744021cb45
git diff --check
```

`campaign.py` retains the exact pytest selectors, flags, timeout, mutant source
anchors and required failure messages. `run_local.py` records the Docker argv.
The host interpreter was
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Pyflakes used `PYTHONPATH=C:/GitHub/stocker/.codex-tmp/lint-deps`.

- Initial regression: **48 passed, 104.30 seconds**, including four new compound
  cases, real callback/process death, planless equity/BIL action units, boot
  recovery, numeric identity, nested capability refusal and automation routing.
- Initial mutation campaign: five intended detections; the takeover mutant
  reached a different missing-completion refusal. The runner correctly rejected
  this as insufficient evidence, rather than calling six mutants detected.
- Strengthened takeover fixture: a nonempty reconciled order earns an actual
  completion witness at epoch one; after another observation and connection
  restart at epoch two, its otherwise valid progress must be fenced.
- Final targeted controls: **3 passed, 23.83 seconds**, including that strengthened
  fixture. These overlap the 48 and are not 51 distinct tests. Only the takeover
  fixture changed after the 48-test regression; production and the compound
  test remained identical.
- Final mutations: **6/6 detected at the required contract failures**, with no
  collection errors or skips accepted as detections. Durations were 10.04,
  15.17, 15.68, 15.15, 5.97 and 4.25 seconds (see retained output).
- Four changed Python files: AST and pyflakes PASS. Ownership: **492 test modules,
  zero unowned, PASS**. Diff whitespace check PASS.

The test container was `sentinel-test:ci`, image
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`:
Python 3.12.13, PostgreSQL 17.11, psycopg 3.3.4. Networking was disabled, source
mounted read-only, memory capped at 4 GiB and CPU at two. The campaign copies
source to a disposable `/tmp/repo` before testing; mutations are confined there
and each original is restored. No NAS or broker account was accessed.

## Evidence interpretation

`raw-logs.zip` preserves the initial and final attempts, including two initial
compound-fixture errors (wrong database DSN and missing opening projection), the
rejected takeover-mutant attribution, and an intermediate positive-control setup
that hit the unrelated external-WAL gate. The final isolated recovery-only lock
does not claim production mutation/backup authority. The lower successor target
is explicitly a contract fixture, not an assertion about strategy allocation.

`source-and-artifact-sha256.json` binds the reviewed source paths, final tests,
campaign scripts and normalized retained logs. `base-strict-test.py` in the
archive preserves the exact pre-strengthening strict fixture used by the 48-test
run. Original historical golden artifacts remain untouched.

L04's local contract checks pass on this reviewed base. L01 still owns combined
#419/#421 integration and required CI. C3 predecessor completeness is still a P1
external certification blocker; current empty reads are never provider finality.
Stage 1 and economic certification remain incomplete.
