# Local storage/read closeout commands

Working directory: the PR #425 checkout. Host launcher is Python 3.12 via the
configured local runtime; test processes use the retained `sentinel-test:ci`
image digest. All Docker test networks are isolated. No provider/NAS call occurs.
Counts below overlap and are not a review-coverage percentage.

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_observation_storage_envelope.py tests/sentinel/test_status_memory.py
# 92 passed, 57.78 s (before adding the decompression-budget case)

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_observation_storage_envelope.py tests/sentinel/test_rolling_restore_integrity.py tests/sentinel/test_shadow_static_ownership.py tests/sentinel/test_status_memory.py
# 112 passed, 181.07 s

python audit/economic_399/local_closeout/run_local.py storage
# 19 positive controls; 8/8 intended mutants detected

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_shadow_observation.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_initialization.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_status_inputs.py tests/sentinel/test_issue270_restore_validation.py tests/sentinel/test_production_decision.py
# 185 passed, 533.47 s

python audit/economic_399/local_closeout/postgres16.py --evidence ../stage-one-storage-pg16
# 49 passed, 44 deselected, 34.94 s; 8,408-series storage: 50.66 s
# PG16.14 peak 300,748,800 bytes; zero OOM or reclaim-limit events

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_restore_integrity.py::test_public_status_checks_final_compressed_series_after_valid_storage_rehash
# 2 passed, 42.35 s before adding the explicit positive public-status precondition

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_state_hash_allocations.py tests/sentinel/test_production_state.py tests/sentinel/test_status_memory.py tests/sentinel/test_rolling_restore_integrity.py tests/sentinel/test_ownership.py
# 141 passed, 231.98 s
# Earlier invocation incorrectly named test_production_ownership.py: no tests ran.

python audit/economic_399/local_closeout/run_local.py read
# 5 positive controls, 8.71 s; 4/4 intended mutants detected

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_restore_integrity.py::test_public_status_checks_final_compressed_series_after_valid_storage_rehash tests/sentinel/test_state_hash_allocations.py tests/sentinel/test_paper_package_architecture.py
# 13 passed, 63.81 s; includes the explicit positive public-status precondition

python audit/economic_399/local_closeout/input_inventory.py --scratch ../stage-one-raw-source
# Raw SFP source SHA matches the retained manifest; 21,939 TICKERS rows pass
# structural/metadata validation. This is not production publication admission.

python audit/economic_399/local_closeout/prior_sources.py
# Per-file unchanged/changed evidence bindings, without claiming old runs reran.
```

The complete initial failed resource command and storage-only before probe are
in the initial README/archive. The intermediate one-pair SQL candidate failed
too and is retained, rather than presented as a successful repair.

```sh
python audit/economic_399/local_closeout/run_stages.py --source ../stage-one-resource-pair-source --evidence ../stage-one-storage-pair --universe 8408 --stages storage
# PostgreSQL backend OOM again, approximately 31.5 s

python audit/economic_399/local_closeout/run_stages.py --source ../stage-one-resource-compressed-source --evidence ../stage-one-storage-compressed --universe 8408 --stages storage
# Storage equality passes, 42.17 s, PG17 peak 323,059,712 bytes, zero OOM

python audit/economic_399/local_closeout/run_stages.py --source ../stage-one-resource-compressed-source --evidence ../stage-one-resource-compressed-8408 --universe 8408
# Initialization passes; origin status and HTTP OOM at the unchanged 512 MiB cap.
# Later stages and their exact metrics are retained separately; this run fails.

python audit/economic_399/local_closeout/run_stages.py --source ../stage-one-resource-read-source --evidence ../stage-one-resource-read-8408 --universe 8408
# Final read-copy repair campaign. See measured stage results; no assumed pass.
```

`read_allocations.py` was run against the intermediate isolated PostgreSQL via
its existing network namespace, source mounted read-only, with 1 GiB/1 CPU and
swap equal to memory. This diagnostic identifies copies; its raised diagnostic
memory limit is explicitly not panel acceptance. It performs only reads and
checks transaction read-only status. The actual qualifying panel runs always
retain 512 MiB/0.5 CPU, runtime 4 GiB/2 CPU and PostgreSQL 1 GiB/1.5 CPU.

Syntax: parse every changed `.py` relative to verified `origin/main` using
`ast.parse(Path(name).read_text(), filename=name)`: 40 files pass. Pyflakes on
those paths reports the pre-existing decision import redefinition and existing
side-effect/pytest fixture imports; the changed production storage/read sources
and new audit/test modules have no warnings. Exact output is retained.

CI run 35531327152/job 106133309207 reported zero source-anchor matches for two
economic mutants after exact arithmetic replaced their expressions. The updated
anchors inject identical sign errors and the original tests detect both. No
test was removed or weakened. Required fresh-head CI remains a separate gate.

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_restore_integrity.py::test_populated_physical_restore_preserves_book_and_advances_next_session
# Published-price accounting oracle: 2 passed, 95.76 s (25 inline / 129 compressed).

python audit/economic_399/local_closeout/run_local.py oracle
# Positive accounting control: 1 passed, 18.79 s; removed cash guard detected.
# A retained cash balance increased by $1 must fail the independent source-price oracle.
```

The intermediate full campaign's production advancement completed, but its old
audit reader queried inline feed prices, which compressed storage no longer
exposes in that physical location. That campaign fails; it is not an accounting
pass. The replacement audit oracle reads published snapshot open/close prices
directly and independently computes position cost, fees, cash and NAV. Neither
the production calculation nor the numerical tolerances changed.

The final campaign's coordinator was resumed after its origin status stage,
preserving the isolated database and all service caps. The original and resumed
source manifests prove all 406 production files identical; only three audit files
changed. Exact commands and container identities are in the resource archive.
No failed stage was skipped or relabeled as passing.

CI allocation follow-up: `python audit/economic_399/local_closeout/run_local.py read`
passes five controls and detects all four mutants with a fresh-process allocation
check. The original 4 MiB threshold remains; the restored-copy mutant fails it.
