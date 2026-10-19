# Protected paper execution: component qualification

Date: 2026-10-19. Verified repository base:
`1e1db91b878d3073549a1e46337893882c3935b2`.
Selected design: [free-data execution](free-data-execution-proposal.md).

The sealed executable successor covers 29 existing Sentinel modules and exactly
three additions. Its SHA256 is
`72dcd8cfca2ca2e342d8d5d220117d2cc89e01ee0406d0bb42465af48a6f2e67`.
All 16 historical descriptors and 21 complete predecessor manifests retain their
original bytes. The actual formed-book test proves admission and restart without
reformation, reacquisition, book mutation or commands.

These are component results. The separate committed-image cold gateway, native
paper behavior, signed release and activation require their own evidence. The
1% cap in private timing scenarios is a test configuration; no production cap is
selected here. Production and the running historical backtest were not changed.

## Final source and import checks

The following exact commands passed in isolated containers using
`sentinel-opening-profile-test:563e2c88`
(`sha256:4b38bf7a798daa53dba05382715bf4d2c4e07c8100ff5e7ccd58f8510a6413ba`).
Containers had no network, read-only source mounts, 0.5 CPU, 768 MiB memory,
private PostgreSQL and bounded private tmpfs. Source hashes matched before/after;
all containers exited. These are overlapping cohorts, not an additive test total.

121 collected and passed, zero failures/errors/skips, 353.74 seconds:

```sh
python -B -m pytest tests/sentinel/test_opening_latency_upgrade.py tests/sentinel/test_retained_source_compatibility.py tests/sentinel/test_clock_sampling_upgrade.py::test_actual_formed_book_survives_clock_repair_without_reformation_or_reacquisition -q --tb=short -p no:cacheprovider --durations=10 --junitxml=/evidence/successor-profile.xml
```

98 collected and passed, zero failures/errors/skips, 41.75 seconds. This includes
the final malformed-receipt handling and all changed test imports:

```sh
python -B -m pytest tests/sentinel/test_limit_day_execution_wiring.py tests/sentinel/test_limit_day_policy_guard.py tests/sentinel/test_limit_day_submit_receipts.py tests/sentinel/test_retained_binding_reuse.py::test_funding_cursor_reuses_signed_binding_but_unknown_lookalikes_are_economic tests/sentinel/test_retained_binding_reuse.py::test_removing_funding_cursor_classification_is_detected -q --tb=short -p no:cacheprovider --durations=10 --basetemp=/tmp/protected-sizing/pytest --junitxml=/evidence/protected-sizing.xml
```

31 collected and passed, zero failures/errors/skips, 21.65 seconds:

```sh
python -B -m pytest tests/sentinel/test_order_terms_schema.py tests/sentinel/test_order_terms_journal.py -q -s --tb=short -p no:cacheprovider --durations=10 --junitxml=/evidence/results.xml
```

47 collected and passed, zero failures/errors/skips, 48.80 seconds:

```sh
python -B -m pytest tests/sentinel/test_journal_and_reconcile.py::TestReconciliation tests/sentinel/test_journal_and_reconcile.py::TestTerminalRecoveryCrashBoundaries tests/sentinel/test_recovery_numeric_identity.py -q -s --tb=short -p no:cacheprovider --durations=10 --junitxml=/evidence/results.xml
```

## Additional focused evidence and test names

Earlier focused cohorts passed budget-constrained sizing (58), maximum-cost
funding and transport (246 unique passing cases across pure, PostgreSQL and
falsifier cohorts), policy/grant/funding regressions (102), qualification-tool
guards (125), host/Compose/namespace integration (28), and executor/paper/
automation integration (21). New guards include executable removal falsifiers.
Receipt coverage includes positive zero/partial/full counters, UNKNOWN retention,
restart, endpoint lag and original-clock expiry. Tests do not infer native fills
or fee behavior from the local simulator.

Preserved intermediate failures include incorrect test fixtures and a private
PostgreSQL WAL tmpfs exhaustion. Their affected cases were corrected or rerun in
fresh bounded containers; no limits or runtime guards were relaxed. A 177-case
earlier schema/recovery regression is a passing coverage union, not a single
clean 177-case invocation. No golden fixtures were re-pinned for passing results.

Eight new test files were renamed to avoid the repository's existing
`test_pr*.py` incident-name rule matching the word `protected`. The moves were
byte-identical except for four test-only import updates, which the final 98-case
cohort covers. Historical evidence retains the original names:

| Original basename | Current basename |
| --- | --- |
| test_protected_limits.py | test_limit_day_sizing.py |
| test_protected_funding.py | test_limit_day_funding.py |
| test_protected_limit_transport.py | test_limit_day_transport.py |
| test_protected_gateway_qualification.py | test_limit_day_gateway_qualification.py |
| test_protected_policy_guard.py | test_limit_day_policy_guard.py |
| test_protected_submit_receipts.py | test_limit_day_submit_receipts.py |
| test_protected_execution_wiring.py | test_limit_day_execution_wiring.py |
| test_protected_policy_env.py (host_python38) | test_limit_day_policy_env.py (host_python38) |

All 17 new branch modules have permanent existing owners. Their 717 cases
collected successfully; collection is not a claim that all 717 executed locally.
No ownership rule, safety workflow, timing gate or test selection contract was
weakened. Native Python 3.8 host execution remains the required CI check; local
grammar validation used Python 3.12's 3.8 grammar mode. Neither `make test` nor
`tests/wealth_core` ran locally.
