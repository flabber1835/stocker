# PR 410 fixture integration follow-up

Reviewed failing head: `5fd72485c9bbe1e28a470ddbb9697f9ea7ba4aac`.
Verified base remains `58c3e071ede06c176e1ed814fb1a7e35b13c33b2`.
Delivery: existing PR [410](https://github.com/flabber1835/stocker/pull/410),
`codex/bounded-backup-selection`, targeting `main`; no self-merge.

## Findings and correction

P2 test integration defects, not newly demonstrated strategy-output defects:

- `tests/internal_state/physical.py:159`: the real physical fixture verified
  its base and archived recovery marker but never selected the generation.
  Every default runtime admission therefore refused. This affected all four
  [internal lifecycle shards and the contract job](https://github.com/flabber1835/stocker/actions/runs/35457716572).
  The fixture now atomically publishes the canonical record after those proofs,
  syncing the file and parent in its owned temporary directory. It remains an
  unprivileged laboratory model, not production ownership certification.
- `tests/production_composition/test_canonical_go_e2e_harness.py:238`: the
  simulated post-seed backup left selection on the old generation. Its old WAL
  horizon correctly exceeded the existing byte budget. The producer now also
  selects the new generation. A stale-selection negative control preserves that
  exact refusal. [Failed composition job](https://github.com/flabber1835/stocker/actions/runs/35457716570/job/105936049536).

Production code, byte budgets, provider flags, strategy logic and all existing
golden/economic reference artifacts are unchanged by this follow-up.
`tests/internal_state/test_physical.py:109` independently checks canonical
selection bytes, real default admission, failed verification/archive preserving
the previous selection, recovery, missing-selection refusal, and explicit
checkpoint admission. Four deliberate producer breakages must fail these tests.

## Exact local commands and results

Host Python:
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Run from the PR checkout. Output directories must be new. The runner prints
its complete Docker and child command lines; retained launch logs include them.

```text
python audit/economic_399/backup_selection_ci/run_local.py regression --output /NEW/regression
python audit/economic_399/backup_selection_ci/run_local.py lifecycle --output /NEW/lifecycle
python audit/economic_399/backup_selection_ci/run_local.py falsifiers --output /NEW/falsifiers
python tools/validate_test_responsibility.py --base 58c3e071ede06c176e1ed814fb1a7e35b13c33b2 --output /NEW/ownership.json
git diff --check HEAD^ HEAD
git diff --check origin/main HEAD
```

- Before correction, the two exact failed nodes reproduced: **2 failed in
  9.30 s**. Original failures are retained, not overwritten.
- Focused non-root `python -m pytest tests/internal_state/test_physical.py
  tests/production_composition/test_canonical_go_e2e_harness.py -q --tb=short
  -p no:cacheprovider`: **27 passed in 33.73 s**.
- `regression` runs both affected owner suites: **655 passed, 1 failed in
  126.81 s**. The sole failure is unchanged
  `test_foreign_owner_selector_is_replaced_with_current_process_owner`:
  `FileNotFoundError: sudo`. The local image has no sudo; GitHub's Ubuntu runner
  has it and this node passed in the original 410 composition job. This is an
  environment limitation, not a passing local claim. No skip, xfail or fake
  ownership operation was introduced. Complete CI remains required.
- `falsifiers`: **4 killed** (no publication, publication before verification,
  publication before archive confirmation, and stale composition selection).
- Root container `python -m pytest tests/internal_state/test_physical.py -q
  --tb=short -p no:cacheprovider`: **7 passed in 55.77 s**, exercising the
  fixture's root-to-PostgreSQL ownership path as well as the non-root run above.
- `lifecycle`: **10 of 10 scenarios PASS**: populated lifecycle, media loss
  and repair, same-size WAL corruption and repair, populated physical restore
  in both simulated account profiles, plus generated seeds 0 and 1. Retained
  campaign coverage includes restart, broker-fill simulation, durable command
  recovery, actual archived media and physical restore. No real accounts.
- The final runner refuses `--inside` on the actual host checkout before Git
  mutations. Its valid disposable-container path was rerun with all four
  falsifiers detected. This runner-only restriction was added after the
  regression/lifecycle snapshot; fixture and acceptance-test sources are the
  same across campaigns.
- Five Python files parse; pyflakes reports zero findings. Ownership: **479
  test modules, zero unowned**.

Offline image `sentinel-test:ci`, digest
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12.13 / PostgreSQL 17.11. Each campaign copies read-only source into a
disposable container with network disabled and no `.env`. The lifecycle runner
creates a clearly labeled synthetic Git snapshot solely to enforce the
harness's unchanged-source rule; it is not the reviewed GitHub commit.
`source-provenance.json` binds the changed source bytes; `results.zip` retains
raw logs, JUnit, scenario inputs/reports/snapshots and provider simulations.
`SHA256SUMS.json` binds this additive package. The earlier
`bounded_base_selection` evidence remains unchanged.

## Remaining qualification and NAS handoff

Require all five fresh-head GitHub workflows to pass before owner merge. In
particular, require all four internal-state shards, the entire composition
authority suite (including the real foreign-owner test), and the PostgreSQL 16
physical/GO stages previously blocked by these fixture failures. Retain head,
synthetic merge identity, run/attempt, JUnit, lifecycle reports and image digests.

For separately authorized NAS qualification, prerequisites and concrete commands
remain in [the original handoff](../bounded_base_selection/README.md#concrete-nas-handoff--not-executed).
Use its actual reviewed backup producer, PostgreSQL 16/default runtime checks,
restart and filesystem-failure procedures. Never run this laboratory's fixture
publisher against deployed media. Pass requires verified physical media,
durable complete selection, refusal on missing/corrupt/stale evidence and
recovery through the real producer. These fixture changes add no NAS acceptance.

Step 1 and economic certification remain open. Recurring backup maintenance,
ownership/retention/horizon bounds, provider finality, authoritative historical
replay and NAS-only physical qualification remain as classified in the
[certification ledger](../../../docs/economic-code-closure.md).
