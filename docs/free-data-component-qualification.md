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

## Reviewed paper lifecycle deltas

Review the seven changed paper lifecycle definitions against the documented
protected-order contract before updating their explicit delta registry. The
opening reader bypasses quotes only for the selected protected policy; target
projection authenticates historical RAW references and retains legacy sizing.
The instrument map checks immutable projection/native identities and preserves
reductions. Execution retains quiescent cash and exact reconciliation gates,
records the selected funding basis and does not report missing-price convergence.
The fresh broker validator preserves all account, certificate, lease, source,
readiness, session and plan checks while consuming only privately verified
structural state; submission additionally rechecks canonical allocation equity.
The guarded broker owns funding derivation from committed rows and the actual
certified composition. It accepts no caller-chosen funding permission.

Record these intentional reviewed deltas and their direct acceptance tests in
`production-champion-paper-deltas.json`; leave the historical extraction manifest,
its original source hash and every historical AST unchanged. The structural
falsifier must continue rejecting an arbitrary unreviewed function fingerprint.
This registry update grants no execution authority.

The complete structural lifecycle module, both native pre-transport fixture
branches and the actual scoped dual-digest corruption test passed 12 cases in
114.68 seconds, zero failures/errors/skips:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_paper_package_architecture.py tests/sentinel/test_native_paper_rehearsal.py::test_native_checks_run_before_inner_submit_and_prove_no_transport tests/sentinel/test_rolling_paper_inputs.py::test_fresh_dual_guard_reuses_only_its_verified_state_digest --junitxml=/evidence/result.xml
```

The native fixture now supplies its exact default MARKET/DAY terms. The scoped
guard test corrupts the real private proof return, asserts that injection ran,
and requires the unchanged stale-state refusal. It no longer patches an unused
public hook. The lifecycle registry's unreviewed-fingerprint falsifier still
passes. These repairs change no Sentinel runtime source.

## Complete-basket timing refusal and pure-work correction

Exact image `36993b6b` (`sha256:35a5eec67db0ea18df32fd16dee923c6f6aaa5a4912396cd41ced885bb7d6cfb`)
in fresh private namespace 16 submitted 15 simulated protected orders without
refusals or deferrals. PREPARE took 96.29 seconds; EXECUTE took 225.04 seconds,
and terminal RECOVER returned successfully in 86.69 seconds. The first POST
was 119.60 seconds, but complete-basket time was 311.89 seconds. The unchanged
300-second gate therefore REFUSED qualification. Final success/book assertions
after that gate are not claimed. Private cleanup passed and the failed cycle
was preserved. Native broker calls remained zero.

The next candidate reduces only exact-text SQL normalization and duplicate
canonical reference construction as documented before implementation. The
pricing/schema cohort passed 77 cases in 60.23 seconds:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_order_terms_schema.py tests/sentinel/test_limit_day_sizing.py --junitxml=/evidence/result.xml
```

After restoring original UTF-8 comments/DDL literals from an edit-encoding
error, the final schema module and current source-seal check passed 23 cases
in 22.27 seconds, zero failures/errors/skips:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_order_terms_schema.py tests/sentinel/test_opening_latency_upgrade.py::test_profile_scope_predecessors_and_current_bytes_are_exact --junitxml=/evidence/result.xml
```

All historical DDL assignment literals match the preceding commit's AST exactly.
Catalog fingerprints and historical fixtures are unchanged; existing post-warmup
catalog-damage refusals still run. Pure normalization tests preserve SQL quoted
semantics and re-read mutable input text before cache lookup. The pricing tests
still authenticate a fresh canonical reference context and reread RAW rows on
each invocation, rejecting changed prices.

The new 29+3 source seal is
`c15470418da30f2b842481eb605305f750d17cbaec94d72796aa00f44849f73d`.
All 16 historical descriptors and 21 complete predecessor manifests are retained.
Fresh namespace 17 has zero commands/cycles and the unchanged private base book.
A new actual-image admission and cold run remain required.

The operator CI lane also caught two unclassified legacy-converter settings.
The retired-Stocker converter now deliberately leaves policy/cap unset, with
reasons; ordinary reviewed Sentinel release-file copying is unchanged. Its
module passed 31 cases in 12.02 seconds, including an actual converted-file
selection test and the inherited-policy falsifier:

```sh
python -m pytest -q -p no:cacheprovider tests/scripts/test_env_from_stocker.py --junitxml=/evidence/result.xml
```

## Source-day refusal after the market close

The next exact candidate, `b8ec6329`
(`sha256:7a35a11316185c787aec9ff35e95c3b010e4106e9a3a715bf8625266a01c1b73`),
passed explicit private migration and actual retained admission in namespace 17.
Its cold run passed recovery preflight but refused during PREPARE after the real
market close: `RollingSourceFrontierPending: ROLLING_INPUTS_NOT_READY: rolling
source-final frontier`. The retained Friday source snapshot was no longer the
source-final frontier. The supervisor surfaced the unreviewed exception as
`SoftwareDefect`; no production classification was changed to admit this stale
campaign. No execution callback or simulated order occurred. Cleanup passed;
all failed evidence remains preserved. This is not a new timing pass.

The qualification tool now requires the real source-final decision frontier
before campaign setup, in addition to its existing current-effective-day check.
Its execution-window fixture does not change that source clock. This diagnostic
precondition refuses expired input explicitly before any phase callbacks,
without weakening ordinary source readiness or substituting historical data.
The 72-case tool module passed in 4.35 seconds, zero failures/errors/skips,
including removal of the new precondition:

```sh
python -m pytest -q -p no:cacheprovider tests/sentinel/test_limit_day_gateway_qualification.py --junitxml=/evidence/result.xml
```

Sentinel runtime source remains at seal
`c15470418da30f2b842481eb605305f750d17cbaec94d72796aa00f44849f73d`.
The remaining cold qualification needs a fresh private copy of the normally
published book and a matching real effective day. No old command is replayed
to a native broker. Production and the backtest remain unchanged; no production
price band, merged release or activation is claimed.

## CI fixture and historical successor alignment

Current-head CI at `58410e5d` passed all other workflow suites and Sentinel
lanes, but ordinary shards 0 and 2 reported 22 failures. The final exact-head
and synthetic-merge aggregators correctly refused those failed dependencies.

Twelve adapter observation cases shared a legacy native-order fixture without
the now-required explicit MARKET/DAY terms. Supply those terms in the fixture;
keep production's missing/contradictory-terms refusal intact. The asset-identity
journal fixture also needs the new canonical order-terms column so its unchanged
broker-asset mismatch assertion reaches the intended guard.

Seven historical autonomy transition cases still required the installed bytes
to equal the original release. Authenticate the original before-to-after edge
against its unchanged descriptor, then require any installed successor to match
the exact reviewed opening-latency profile. Two older schema tampering cases
must expect the newer full-closure refusal, which runs before individual
economic-source comparison. Their unreviewed-neighbor mutations still must be
rejected. No historical descriptor, hash fixture or Sentinel runtime source is
changed by these test repairs.

The targeted cohort passed 298 cases in 171.49 seconds, zero failures, errors
or skips, in a network-disabled container capped at 0.5 CPU/768 MiB with a
private temporary Postgres. All Sentinel Python and selected test-file hashes
were unchanged during the run. This includes the native-terms, private receipt,
limit-fill, capability and whole-quantity guard-removal falsifiers, plus exact
historical origin/environment and neighboring-source tampering refusals.

```sh
python -B -m pytest -q --tb=short -p no:cacheprovider tests/sentinel/test_adapter_and_recovery_drill.py tests/sentinel/test_issue209_asset_identity.py tests/sentinel/test_autonomy_runtime_upgrade.py tests/sentinel/test_callback_liveness_upgrade.py::test_callback_transition_is_exact_and_neighbor_change_refuses tests/sentinel/test_operational_liveness_upgrade.py::test_only_exact_operational_source_transitions_are_allowed tests/sentinel/test_operational_liveness_upgrade.py::test_neighbor_change_in_operational_file_refuses_full_admission tests/sentinel/test_operational_liveness_upgrade.py::test_operational_runtime_transition_is_exact_and_authenticated tests/sentinel/test_limit_day_transport.py --junitxml=/evidence/result.xml
```

AST checks passed for all five changed Python modules; `git diff --check` passed.
These results repair CI coverage only. The pending cold timing qualification,
price-band choice and signed deployment obligations remain unchanged.
