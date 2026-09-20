# Local PostgreSQL pressure evidence

Design and result interpretation: [postgres-local-pressure.md](../../../docs/postgres-local-pressure.md).
This audit uses the production PG16 image with unchanged default durability and
the configured 1 GiB database / 4 GiB client limits. Its isolated synthetic
publisher executes the existing production preparation path; two independent
processes recompute all snapshot content hashes, then the existing wide
observation storage probe checks exact round-trip equality.

From the repository root, using the cached Docker images named in the runner:

```sh
python audit/economic_399/postgres_pressure/run_local.py --evidence ../postgres-pressure-pg16
python audit/economic_399/postgres_pressure/report.py --evidence ../postgres-pressure-pg16
```

The evidence destination must be new. The runner has no network or host ports;
it removes only its own randomly named containers and disposable database volume.
It records the command line, inspected limits/images, source hashes, raw memory
samples, normal PostgreSQL settings, database/temp/WAL counters and scan plans.
`report.py` requires every stage and successful container completion. It keeps
total-memory pressure visible even when the sampled non-file-cache estimate is
small. A full content verification compares stored row hashes to the sealed
manifest; it is not source/provider or strategy-return certification.

Targeted tests (cached image, `--network none`, 512 MiB memory/swap, one CPU):

```sh
python -m pytest tests/sentinel/test_postgres_pressure_evidence.py -q -p no:cacheprovider
python audit/economic_399/postgres_pressure/mutations.py
```

Results: **8 passed in 2.89 seconds**; **3/3 mutants detected**, each with the
intended assertion failure and the other seven cases passing. Mutants omit
shared memory from the estimate, label a charged peak at the cap as margin,
and ignore an OOM event. Mutations execute in disposable copies only. Host
Python lacks pytest; the initial host invocation ran no tests, then the cached
test image ran the commands above. Pyflakes is clean for all five added Python
files. No Wealth Core or unrelated regression suite is required: production
code and configuration are unchanged by this investigation.

Raw evidence is retained in `evidence.zip` (137,127 bytes, 38 members), SHA-256
`4763efc328cf5dee300f7a21003be36de5040c3f157bda2f1d26f121f62d309a`.
`SHA256SUMS.json` binds every archive member; `results.json` is the readable
summary. Existing PR #425 resource archives are preserved unchanged.

The CI-layout reproduction copies only this reporter into `/work/audit`, as
specified in `Dockerfile.sentinel-test`, and imports production from `/app`.
`tests/sentinel/test_postgres_pressure_evidence.py` plus
`tests/sentinel/test_image_layout.py` pass **51 tests in 13.55 seconds** there.
No repository-root import shortcut is used for that check.

The separate main-lane CI timeout correction and **54 passing workflow tests**
are recorded in [the CI contract](../../../docs/status-runtime-ci.md#main-lane-wall-time-budget-2026-09-20).
`validation-evidence.zip` retains the old cancelled job/log and ownership PASS
(495 modules, zero unowned); `validation-SHA256SUMS.json` binds its three members.
No unfinished CI run is reported as passing.
