# Protected paper execution: component qualification

Date: 2026-10-19. Verified repository base:
`1e1db91b878d3073549a1e46337893882c3935b2`.
Selected design: [free-data execution](free-data-execution-proposal.md).

The initial sealed executable successor covers 29 existing Sentinel modules and
exactly three additions. Its SHA256 was
`72dcd8cfca2ca2e342d8d5d220117d2cc89e01ee0406d0bb42465af48a6f2e67`.
All 16 historical descriptors and 21 complete predecessor manifests retain their
original bytes. The actual formed-book test proves admission and restart without
reformation, reacquisition, book mutation or commands.

These are component results. The separate committed-image cold gateway, native
paper behavior, signed release and activation require their own evidence. The
1% cap in private timing scenarios is a test configuration; no production cap is
selected here. Production and the running historical backtest were not changed.

## Component source and import checks

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

At the initial commit, all 17 new branch modules had permanent existing owners. Their 717 cases
collected successfully; collection is not a claim that all 717 executed locally.
No ownership rule, safety workflow, timing gate or test selection contract was
weakened. Native Python 3.8 host execution remains the required CI check; local
grammar validation used Python 3.12's 3.8 grammar mode. Neither `make test` nor
`tests/wealth_core` ran locally.

## Full-gateway correction

The first committed-image protected gateway rehearsal (`2146264b`) passed native
simulation preflight but refused during PREPARE: the new detached shadow-equity
return referenced `decimal_text` without importing it. It sent no orders; private
cleanup passed. Component tests had not exercised that real return. This failed
run remains diagnostic evidence, not a timing qualification.

Restore the documented scalar contract with the missing import. A new isolated
regression executes the real `_rederive_plan`, restores canonical state, loads
persisted authority and invokes the real `build_execution_plan`. Three exact
Decimal values pass. A private full-module import-removal falsifier reproduces
the original NameError after the derived plan matches its immutable authority.

The corrected source-profile seal is
`577f7fcb2559e8ee6b40020c0f463633736bc4e6b050be518d7cdf7bd0e114e1`.
The checker mechanism, 29+3 scope and all historical descriptor/witness bytes
remain unchanged. Five cases passed in 22.76 seconds, zero failures/errors/skips:

```sh
python -B -m pytest tests/sentinel/test_dual_plan_scalar_proof.py tests/sentinel/test_opening_latency_upgrade.py::test_profile_scope_predecessors_and_current_bytes_are_exact -q --tb=short -p no:cacheprovider --durations=10 --basetemp=/tmp/protected-sizing/pytest --junitxml=/evidence/protected-sizing.xml
```

The corrected committed image still needs a fresh private admission and complete
cold gateway run. Release evidence is recorded on the pull request; this
component record does not substitute for that gate.

CI also exposed three moved mutation anchors in the existing Alpaca, Sentinel
and V5 harnesses. Update only their target strings to the current guard sites;
retain their mutant IDs, replacement behavior, test selections and kill checks.
All 52 rewrite anchors are unique and independently compile. The three selected
baselines pass and all three actual mutants are killed by the existing verifiers.
Normalize only the new SQL fixture's CRLFs and extra EOF blank lines in four new
tests: SQL `Path.read_text()` content and Python ASTs remain identical. No fixture
expectation, golden hash, workflow or whitespace rule changes.

## Funding integration and release-reader correction

The second exact committed-image gateway (`9791d1fa`, private namespace 15)
passed PREPARE but failed the unchanged timing gate: EXECUTE returned after
139.035 seconds with zero orders. Read-only inspection found all 15 protected
reference limits and allocations READY, but no commands or funding basis.
The new funding path unconditionally required a native cash-activity interval;
the actual Alpaca adapter intentionally quarantines that unaccepted capability.
The returned callback detail was not retained, so this is a code-path blocker
corroborated by durable state, not a stored exception claim. The failed cycle
and evidence remain preserved. No broker order was submitted.

The qualification tool now records returned dispositions, financial deferrals
and refusal reasons before a following timing check can fail. Its 70 focused
cases passed in 3.77 seconds, with zero failures/errors/skips:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_limit_day_gateway_qualification.py --junitxml=/evidence/result.xml
```

The release current-plan reader and ordinary CLI now receive the same explicit
policy/cap as the signed configuration issuer and authorized services. This
prevents a legacy `/1` identity from contradicting selected `/2` execution
configuration during activation. The two directly relevant host/configuration
modules passed 126 cases in 15.01 seconds, including both omitted-forwarding
falsifiers, with zero failures/errors/skips:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_deploy_plan_reader.py tests/sentinel/test_env_automation_config.py --junitxml=/evidence/result.xml
```

These cohorts used the same bounded, network-disabled test image and read-only
source mounts. Neither is full-gateway qualification or production activation.
The separately tagged no-activity plan-cash funding design required separate
implementation tests and a new seal, recorded below. Its fresh committed-image
cold run remains a distinct gate.

The new no-activity `/2` variant passed 40 focused cases in 26.40 seconds:

```sh
python -B -m pytest tests/sentinel/test_limit_day_plan_cash_funding.py -q --tb=short -p no:cacheprovider --durations=10 --basetemp=/tmp/protected-sizing/pytest --junitxml=/evidence/protected-sizing.xml
```

These execute the actual sealed AssetId Alpaca composition and canonical guarded
funding callback, persisted typed basis, restart identity, disabled activity
capability, strict cash/quiescence, no-credit ceiling, deposit/withdrawal bounds,
all live/terminal promise states and executable guard-removal falsifiers. The
retained activity-backed funding module also passed 52 cases in 20.11 seconds,
including its existing six canonical guard-removal falsifiers:

```sh
python -B -m pytest tests/sentinel/test_limit_day_funding.py -q --tb=short -p no:cacheprovider --durations=10 --basetemp=/tmp/protected-sizing/pytest --junitxml=/evidence/protected-sizing.xml
```

The source seal for this funding correction is
`6415a51c222e5eff3ec28a84cc528ebf738e7199c1c61be67fb7b7bd40b0fcd5`.
The 29+3 source scope, 16 historical descriptors and 21 complete predecessor
witnesses remain unchanged. The isolated private PostgreSQL cgroup was corrected
from 0.5 CPU/768 MiB to the installed 1.5 CPU/1 GiB without restart, settings or
SQL changes; remaining conservative configuration differences are documented in
the design. This neither changes production/backtest resources nor supplies a
gateway pass.

The exact current-profile byte/witness check passed one case in 14.16 seconds:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_opening_latency_upgrade.py::test_profile_scope_predecessors_and_current_bytes_are_exact --junitxml=/evidence/result.xml
```

The direct execution-wiring and selected-policy guard modules passed 42 cases
in 20.64 seconds, zero failures/errors/skips:

```sh
python -B -m pytest tests/sentinel/test_limit_day_execution_wiring.py tests/sentinel/test_limit_day_policy_guard.py -q --tb=short -p no:cacheprovider --durations=10 --basetemp=/tmp/protected-sizing/pytest --junitxml=/evidence/protected-sizing.xml
```

All three funding/wiring cohorts used fresh bounded disposable PostgreSQL
clusters, and their recorded source hashes remained unchanged. The ownership
validator accepted all 669 Sentinel test modules under the existing 13 owners;
the new funding module belongs to the general partition. The independent
four-partition collection verifier is not claimed here because the canonical
partition set has six entries. No ownership or partition selection was changed.

## Canonical free-quote contract tests

The general CI shard exposed two obsolete SIP-request expectations after the
documented restoration of canonical legacy IEX execution quotes. The attended
service rehearsal had the same stale request expectation. Correct only those
tests and names, preserve distinct historical SIP and IEX decoding coverage,
and retain all sixty-second freshness, raw-side, HTTP403 single-request and
service ownership checks. No runtime source, parser or permission guard changed.
Both modules passed 32 cases in 32.01 seconds, zero failures/errors/skips:

```sh
python -B -m pytest tests/sentinel/test_unattended_operating_contract.py tests/sentinel/test_paper_service_rehearsal.py -q --tb=short -p no:cacheprovider --junitxml=/evidence/transport.xml
```

All 348 Sentinel Python source hashes were unchanged across that cohort. The
protected policy still forbids every quote GET, independently of legacy decoding.
