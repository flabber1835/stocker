# Autonomy remediation qualification record

Implementation base: `118b7c15249e47bd7ea79a23ecbc58b6dc947741`.
Qualified runtime implementation commit: `e9172f444acee40a20c0ecbbaa13f3c09e8eb953` on
`codex/autonomy-live-qualification`. Later commits change tests and this record;
the runtime, operational scripts, workflows and image-build sources are unchanged.
Historical image evidence below identifies `bc734310` and
`05c516a69401fe0cc4cf4355a311c3527f9706b8` explicitly. This record distinguishes software tests,
provider observations and deployment/live authority. It is not a signed release
certificate or a permission to trade.
The host-only probe import repair and checksum migration have separate evidence
below. The current source checkout/test lens and native host-script proof
include the import repair; operational host scripts are not packaged in the
runtime image. That image includes the checksum migration. Earlier images
retain their original attribution.

## Implemented scope

The nine confirmed review findings have repairs: owned-wrapper database retry;
authenticated current asset identity; bounded action-history roll-off; conversion
dividend ownership; available paper purchase funds; paper reconciliation of
serialized cumulative fill averages;
foreground Alpaca retry; candidate clean tails; and retained provenance shape.
The forward-cash change has an explicit v2 strategy transition and authenticated
v1 source/admission compatibility. Wealth Core's shared implementation is unchanged.

An additional cross-review regression reproduced a partial-restore hole: deleting
an observation and its provenance could leave its witness undetected. The follow-up
repair inventories orphaned legacy and compact witnesses in bounded pages, checks
their metadata before excluding valid pre-binding history, and preserves legitimate
sequence gaps. The old implementation failed the actual PostgreSQL loss cases;
the final image includes this repair and passed its immutable software checks. Independently current
primary, provenance or witness timestamps retain account scope, so backdating
one representation cannot hide a disagreement with the others.

Full-window admission now renews the original lease in bounded row batches and
closes its price cursor on consumer failure. A per-symbol latest-absence index
replaces repeated scans with an equivalent predicate. Owner, fence, absolute
deadline, transaction boundaries, source generations and observation clocks are
preserved. Controlled slow-work and operation-count cases failed before repair;
deadline, fence-loss, cursor-close and selection-parity cases pass afterward.

Optimizations cover compact candidate facts, shared immutable ledger chunks,
paged observation verification and compact witnesses, shared freshly acquired
price payloads, statement-level retention authorization, sparse runtime checkouts,
a credential-free build context, shared probe parsing and reused validated source
profiles. Logical state and authority do not depend on physical compression.

History verification, complete-state hashing and historical command reconstruction
remain linear. Shared ledger references still grow. Fresh provider downloads
remain complete; no delta-only source coverage or general runtime speedup is
claimed. Larger workflow/module consolidation and authenticated verified-prefix
checkpoints remain separate work with their own proof obligations.

## Current e917 immutable-image and functional qualification

Runtime image:
`sha256:6a1dac0dac44033aa4244b50eaf492a885eb9b7e674417cc9fc3bcf329a6b6ca`.
Test lens:
`sha256:e36658fabc42d3e0d85ec1031910a16925b0e2a8594c1f4c80397e3ea0637c31`.
Both identify source `e9172f444acee40a20c0ecbbaa13f3c09e8eb953`.
The clean committed build, UID 10001, baked dependency lock and matching ordinary
CLI/unchanged restore filesystem identities were independently verified.
The native identity was
`fbae4f848c9419f51742392cfd67ab6a1f74bee82e19163d28697fdb181c66d2`.

Immutable-image checks passed 620 affected regressions in 135.854 s, 257 selected
source-profile tests in 6.148 s, 17 host tests in 0.459 s and all 44 acquisition
mutants in 234.875 s. The original forty mutant labels remain; the four added
cases cover auxiliary reference hashes, both retained-root pins and actual
legacy constraint retirement. Build acceptance passed 46 layout tests in
41.20 s, 1,581 operator tests in 154.82 s and 79 browser tests in 10.48 s.
The existing isolated native host-probe integration passed in 62.237 s.

The immutable feed selection initially passed 161 tests and failed three host
imports in 236.516 s because its harness omitted `/work/scripts` from
`PYTHONPATH`. Those same three selectors passed in 2.857 s with the corrected
path, without source changes. This is preserved as an initial failure and a
separate correction, not a single all-green invocation. Later test-only codec,
accounting, restore and reader fixture overlays on these unchanged images are
recorded below. Groups overlap; the complete suite is not claimed. Exact Docker
argument arrays and image/overlay attribution are retained in the evidence JSON.

The new cold v3 run passed `functional_status`, `financial_proof_status` and
`cleanup_status`, with `private_project_stopped=true`. Its complete raw report
was 16,728 bytes, SHA256
`9e609fe8c5397a2a446817ca89d4f95de5294e3aa096178c7da8b14d045813fa`.
All command exits were zero. The original work deadline remained
`2026-10-17T08:47:27.867514Z`.

| Genuine producer/check | Result and command elapsed |
| --- | --- |
| Initial base/status/full semantic restore | PASS, 24.487 s / 6.491 s / 21.436 s. |
| Complete provider preparation | PASS, 1,543.657 s main child; 1,545.535 s whole wrapper, including the separate 1.815 s retained-revision probe. |
| Completed-input diagnostic | PASS, 5.111 s. |
| 126-session canonical formation/restart parity | PASS, 905.347 s. |
| Read-only readiness | PASS, 82.989 s. |
| Read-only financial health | PASS, 90.411 s; all 14 checks true and zero database writes. |
| Native durable initialization | PASS, 188.733 s. |
| Fresh-process durable resume | PASS, 69.250 s; session, record, state, full ledger, checkpoint and execution-journal hashes equal. |
| Retained canonical restart parity | PASS, 74.793 s. |
| Populated base and exact backup status | PASS, 70.914 s / 7.872 s. |
| Populated full semantic restore | PASS, 119.736 s. |
| Private-project cleanup | PASS, 1.397 s. |

The provider window contained 426 sessions, 5,937 selected and 5,913 admitted
securities, 2,366,921 paired stock rows and 2,198,840 canonical stock rows.
At the `07:15:07.365530Z` diagnostic, original inventory age was 1,539.983 s;
stock ages were 521.275–1,374.752 s. Future observation counts were zero and
source clocks were not refreshed. Admission processed the actual rows in
54.212 s with 473 bounded working pulses; normalization took 128.508 s.
These observations do not establish a comparative runtime speedup or final
database size improvement.

The populated backup `base-20261017T073847Z` restored the attested October 16
book at publication version 1, with restart state present. Validation remained
read-only, with no bound account, zero commands and automation disabled.
The backup/status/full-restore producers passed for both the schema bootstrap
and populated book. Automatic horizon-triggered renewal was NOT_EXERCISED:
zero callback calls, zero successes and no exercised horizon resume. Controlled
renewal tests and these explicit producers are distinct evidence.

The auxiliary passive observer exited 1 after a `PermissionError` enumerating
the private backup's base directory. It verified no restore-worker containers;
current OOM and worker-log capture are NOT_PROVEN. This auxiliary failure does
not change the independently successful restore producer, semantic validation
or cleanup. Its failure is preserved separately. Original backup permissions
and the successful qualification were unchanged.

A bounded read-only copy of the historical populated backup established that
the two runs used different input observations. Selection, fundamental,
dividend and reset commitments matched; all 21 auxiliary reference hashes and
20 price-content partitions matched. The October 1–16 partition changed from
70,981 to 71,096 rows. Stale/noncontiguous exclusions changed 120 to 5 and
discontinuity exclusions 16 to 17, while admitted count rose by 114. The recorded
empty continuity-binding hash does not prove complete provider mapping
equivalence. Individual bars, upstream mechanism and one-to-one causality were
not established. The original backup stayed read-only, checked metadata hashes
were unchanged, and the isolated copy's container and volume were removed.

The same reviewed v3 driver and 7,200 s budget shown in the historical command
below were used with the current runtime digest, commit and a fresh private
workspace. The sanitized current evidence archive contains 32 members,
142,216 bytes, SHA256
`8d9edccc9ba19782ff04cf8fdf91721ed7bbb14dbb38eca8308b8f9c4b48c0b8`.
Its fixed manifest preserves historical failures, current failure/correction
history, diagnostic limits and immutable-image versus test-overlay attribution.
Fresh exact-head GitHub checks are a separate PR validation gate. Physical
backup independence, NAS capacity, signed release/deployment admission and live
authority remain NOT_PROVEN.

## Historical bc734310 images and test evidence

The following image/table/command evidence retains its historical source
attribution. Its uses of "final" refer to that earlier runtime, not e917.

Final runtime image:
`sha256:a0d52b8f0380025829b85464c63836fb113f28fa9eac3369a106c5a1957de01c`.
Final test lens:
`sha256:e042a245195c46e9c127138f66d1679a322757b0f36cf9a4e06e3f13c2495065`.
Both identify `SOURCE_GIT_SHA=bc7343100d9d8ba3357c339242fbf5962c1111cd`.
Local functional and financial GO passed on the corrected cold `bc734310`
attempt, including populated full restore and cleanup. All five affected
immutable-image test selections passed. The two failed attempts below remain
part of the evidence; they are not relabelled as passes.

Earlier runtime image:
`sha256:7d6e5418384336c0cf8f5c54bf8b5fdcdfaa5c4156e4a30a86e074407bff028b`.
Test lens over that runtime:
`sha256:f7d31e60c0f4dffe7e2bc5a0c5c05c413f0f6ef1f76b98e6a194afce38faf3dd`.
Those two earlier images used `SOURCE_GIT_SHA=05c516a69401fe0cc4cf4355a311c3527f9706b8`.
The test lens confirmed imports from `/app` and the installed shared package.

| Check | Observed result |
| --- | --- |
| Execution, observations, native fill candidates and recovery | 393 passed in 132.25 s; exact command in [execution remediation](autonomy-execution-remediation.md). |
| Final three-copy observation recovery and execution selection | 446 passed in 143.81 s; includes the new partial-restore and scope cases. |
| Historical source profiles and authenticated closure | 257 passed, 20 deselected in 167.66 s; selected formed-book cases ran separately. |
| Final immutable-image source profiles | 257 passed, 20 deselected in 6.12 s. |
| Final immutable-image retained admission chain | 36 passed in 2.20 s. |
| Final immutable-image canonical continuation, lost-commit recovery and retained-book restarts | 4 passed in 278.67 s. |
| Scratch combined chunked-ledger physical restore | 1 passed in 114.98 s on the final test lens; genuine canonical formation generated at least 256 events and a shared chunk, then physical backup/verification, separate restored PostgreSQL, semantic validation and restart preserved state and full ledger. |
| Accounting, storage, compact inputs and formation | 89 passed in 399.31 s. |
| Canonical continuation, lost commit, retained-book restarts and source matcher falsifiers | 7 passed in 472.36 s. |
| Feed/source/retention | 127 passed initially; all four failed cases passed on the corrected rerun. The three host-helper imports needed `/review/scripts`; the remaining case crossed a source edit during the initial run. |
| Read-only provider diagnostic tests | 11 passed. |
| Final admission pacing, absence indexing and revision recovery | 61 passed in 65.32 s; two additional clean-basis-tail cases passed in 6.42 s. |
| Endpoint, operator and affected CI checks | 288 passed in 71.55 s. |
| Shadow acquisition budgets, contention, outages, renewal and unattended operation | 81 passed in 1,247.04 s. |
| Final immutable-image autonomous recovery selection | 81 passed in 675.95 s. |
| Exact test image, new regression files | 186 passed in 39.20 s. |
| Final immutable runtime, 25 affected regression files | 620 passed in 139.08 s. |
| Test-image build acceptance | 46 image-layout, 1,581 operator and 79 browser tests passed. |
| Test responsibility and merge authority | PASS; 649 owned test modules, no unowned modules. |
| Workflow materialization | 19 checkout steps in seven workflows verified; isolated Git sparse checkout retained code/tests and omitted SEC archives. |
| Static checks | 1,240 Python files parsed, workflow YAML and `git diff --check` passed. |

These groups overlap and are not a unique test count. Every row labelled final
immutable, the earlier exact-image selection and build acceptance used immutable
images. Other source tests used the existing dependency
image with current feature source mounted read-only and provider networking
disabled. No `make test`, complete Sentinel suite or `tests/wealth_core` run is
claimed. Protected CI and signed publication remain later release gates.

The combined physical-restore fixture used synthetic market observations and
declared dividends, while retaining native runtime/feed identity validation and
the canonical strategy transition. Its disposable developer backup-media marker
was absent. It called the real semantic validator directly, rather than the
restore shell; the candidate book was not given a runtime attestation. It proves
the combined chunk codec/physical semantic path, not
production backup independence or real-provider financial authority. The fixture
is separate from the genuine provider GO below.

The final immutable regression command was:

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  --mount type=bind,source=<private-evidence>,target=/evidence \
  --env PYTHONDONTWRITEBYTECODE=1 \
  sentinel-autonomy-qualification-test:bc734310 \
  -q -p no:cacheprovider --tb=short -o junit_family=legacy \
  --junitxml=/evidence/final-runtime-regressions.xml \
  tests/sentinel/test_autonomy_compact_features.py \
  tests/sentinel/test_autonomy_storage.py \
  tests/sentinel/test_autonomy_execution_remediation.py \
  tests/sentinel/test_autonomy_runtime_upgrade.py \
  tests/sentinel/test_observation_witness_storage.py \
  tests/sentinel/test_trading_environment.py \
  tests/sentinel/test_dependency_recovery.py \
  tests/sentinel/test_market_data_capture.py \
  tests/sentinel/test_alpaca_boundary_overlay.py \
  tests/sentinel/test_native_fill_progression.py \
  tests/sentinel/test_native_fill_acceptance.py \
  tests/sentinel/test_trial_fill_interval_proof.py \
  tests/sentinel/test_trial_fill_interval_evidence.py \
  tests/sentinel/test_regular_quote_submission.py \
  tests/sentinel/test_dual_regenesis_handover.py \
  tests/sentinel/test_journal_and_reconcile.py \
  tests/sentinel/test_guarded_execution_broker.py \
  tests/sentinel/test_automation_runtime.py \
  tests/sentinel/test_alpaca_observation.py \
  tests/sentinel/test_alpaca_revision_recovery.py \
  tests/sentinel/test_dual_reconciliation.py \
  tests/sentinel/test_opening_submit_freshness_boundary.py \
  tests/sentinel/test_v5_opening_execution_freshness.py \
  tests/sentinel/test_dual_regenesis_pre_adoption.py \
  tests/sentinel/test_dual_regenesis_automation_scope.py
```

The final source-profile run used that image/isolation with the 13-file
selection and `-k 'not formed and not preserved'` documented below, writing
`final-source-profiles.xml`. The final autonomous run used the five-file
selection below and wrote `final-autonomy-recovery.xml`.

The directly changed retained-admission contract ran separately with that same
image/isolation, `--junitxml=/evidence/final-retained-admission-chain.xml` and
`tests/sentinel/test_retained_admission_chain.py`.

The final retained continuation command used that image/isolation with
`--junitxml=/evidence/final-retained-continuation.xml` and these selectors:

```text
tests/sentinel/test_rolling_daily.py::test_daily_advances_pending_book_and_matches_canonical_transition
tests/sentinel/test_rolling_daily.py::test_lost_commit_reply_recovers_once
tests/sentinel/test_callback_liveness_upgrade.py::test_formed_book_callback_upgrade_does_not_reform_or_reacquire
```

The earlier exact-image regression command was:

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  --mount type=bind,source=<private-evidence>,target=/evidence \
  --env PYTHONDONTWRITEBYTECODE=1 \
  sentinel-autonomy-qualification-test:05c516a6 \
  -q -p no:cacheprovider --tb=short -o junit_family=legacy \
  --junitxml=/evidence/exact-image-regressions.xml \
  tests/sentinel/test_autonomy_compact_features.py \
  tests/sentinel/test_autonomy_storage.py \
  tests/sentinel/test_autonomy_execution_remediation.py \
  tests/sentinel/test_autonomy_runtime_upgrade.py \
  tests/sentinel/test_observation_witness_storage.py \
  tests/sentinel/test_trading_environment.py \
  tests/sentinel/test_dependency_recovery.py \
  tests/sentinel/test_market_data_capture.py
```

The other root operator/CI selection used `python -m pytest -x -q -p
no:cacheprovider` with `test_trading_environment.py`, `test_paper_allowlist.py`
under `tests/sentinel/`, and `test_sentinel_bringup_source_liveness.py`,
`test_sentinel_go_validate.py`, `test_test_responsibility.py`,
`test_sentinel_ci_shards.py` under `tests/scripts/`.

The final 446-test execution run used `python -m pytest -q -p no:cacheprovider
--tb=short` with the 13 files recorded in execution remediation plus
`tests/sentinel/test_trading_environment.py`. Removing reverse inventory detected
all four legacy/current interior/all-loss cases. Restoring unsafe date cutoffs
detected both backdating cases; restoring primary-only scope detected three
independent-copy cases. These deliberate mutations stayed in disposable process
memory. A separately focused final selection passed 144 tests in 52.90 s.

The 81-test autonomous selection used the same command with these complete files:

```text
tests/sentinel/test_shadow_acquisition_budget.py
tests/sentinel/test_runtime_contention.py
tests/sentinel/test_production_outage_recovery.py
tests/sentinel/test_dual_plan_renewal.py
tests/sentinel/test_unattended_operating_contract.py
```

The core/source selections used `python -m pytest -p no:cacheprovider -q`.
The 257-test command selected these files and appended
`-k 'not formed and not preserved'`:

```text
tests/sentinel/test_autonomy_runtime_upgrade.py
tests/sentinel/test_retained_source_compatibility.py
tests/sentinel/test_close_cycle_upgrade.py
tests/sentinel/test_paper_composition_upgrade.py
tests/sentinel/test_retained_readiness_upgrade.py
tests/sentinel/test_dual_plan_renewal_upgrade.py
tests/sentinel/test_callback_liveness_upgrade.py
tests/sentinel/test_startup_contention_upgrade.py
tests/sentinel/test_shadow_ui_upgrade.py
tests/sentinel/test_dashboard_monitor_upgrade.py
tests/sentinel/test_open_time_upgrade.py
tests/sentinel/test_unsent_recovery_upgrade.py
tests/sentinel/test_operational_liveness_upgrade.py
```

The 89-test command selected:

```text
tests/sentinel/test_autonomy_storage.py
tests/sentinel/test_observation_storage_envelope.py
tests/sentinel/test_forward_cash_distributions.py
tests/sentinel/test_forward_cash_migration.py
tests/sentinel/test_autonomy_compact_features.py
tests/sentinel/test_current_window_formation.py
```

The seven continuation/restart/falsifier cases selected:

```text
tests/sentinel/test_autonomy_runtime_upgrade.py::test_full_proof_refuses_an_unreviewed_predecessor_even_with_matching_origin
tests/sentinel/test_autonomy_runtime_upgrade.py::test_removing_local_predecessor_check_is_detected
tests/sentinel/test_autonomy_runtime_upgrade.py::test_reintroducing_per_file_profile_reads_is_detected
tests/sentinel/test_rolling_daily.py::test_daily_advances_pending_book_and_matches_canonical_transition
tests/sentinel/test_rolling_daily.py::test_lost_commit_reply_recovers_once
tests/sentinel/test_callback_liveness_upgrade.py::test_formed_book_callback_upgrade_does_not_reform_or_reacquire
```

Feed commands used `python -m pytest -q -p no:cacheprovider --tb=short`.
The first run additionally used `-o junit_family=legacy
--junitxml=/evidence/feed-qualification.xml` and selected:

```text
tests/sentinel/test_alpaca_transport.py
tests/sentinel/test_alpaca_observation.py
tests/sentinel/test_alpaca_revision_recovery.py
tests/sentinel/test_rolling_history_retention.py
tests/sentinel/test_acquisition_resumption.py
tests/sentinel/test_rolling_retention_runtime.py
```

The corrected rerun added `/review/scripts` to `PYTHONPATH` and selected
`tests/sentinel/test_acquisition_resumption.py::test_metadata_successor_does_not_parse_suffix_as_date`
(three parameters) and
`tests/sentinel/test_rolling_retention_runtime.py::test_service_keeps_valid_trading_state_when_cleanup_fails`.
The diagnostic selection was `tests/sentinel/test_market_data_capture.py` under
that same import path. Original feed bugs and deletion/authentication guards
have separate old-code and mutation falsifiers described in the feed decision.

The final feed command, under that same isolated import path, was:

```sh
python -m pytest -q -p no:cacheprovider --tb=short \
  tests/sentinel/test_alpaca_observation.py \
  tests/sentinel/test_alpaca_revision_recovery.py
```

The separately added two cases used the same command with
`tests/sentinel/test_alpaca_observation.py::test_absence_index_respects_actual_clean_basis_tail`.

Original-source regressions and disposable intentional mutations detected the
repaired behaviors and guard removals. They include funding, UUID, average-price,
witness and binding checks; endpoint environment/origin checks; conversion
entitlements; storage authentication; and source matching/profile rereads. No
mutation was left in repository source or used to create acceptance evidence.

## Measured optimization fixtures

| Fixture | Before → after | Scope |
| --- | --- | --- |
| 24 retained observations, final 1,984 ledger events | 729,796 → 134,322 bytes, 81.6% lower | PostgreSQL column payloads including all new chunks; excludes heap/index/WAL overhead. |
| 5,000 candidate signals | 7,807,057 → 916,177 bytes, 88.3% lower | Canonical input JSON, identical scores. A separate publication fixture proves full transition/restart parity. |
| 5,000 events, 1,000 cash observations | Median 0.448 → 0.0402 process CPU seconds | Three runs; equal economics. No deployed latency claim. |
| 4,096 decoded 16-KiB observation rows | 67,744,186 → 2,150,779 peak Python bytes | Same semantic checksum; bounded page of 128 rows. |
| Third broker representation, 14 positions | 1,316 → 338 JSON bytes | New compact witness only; original primary/provenance remain. |
| Equal fresh price acquisition | 600 initial rows; zero added rows | Relation stayed 262,144 bytes. Changed acquisition added 18 rows; every observation still made 33 bar requests. |
| Runtime checkout archive exclusion | 921,904,567 tracked bytes omitted | Materialization savings; repository history remains. |
| 2,000 symbols and 2,000 old absent pairs | 4,000,000 → 2,000 pair visits | Identical admission/reasons; 99.95% fewer visits in this adversarial fixture. No deployed latency claim. |

## Real-provider source observation

At `2026-10-17T03:18:48.917785Z`, the earlier `05c516a6` runtime's read-only diagnostic
observed the October 16 session from Alpaca/OpenFIGI: 13,246 inventory entries,
two classifications, two benchmark bars under each of raw/split/all adjustments,
and 135 corporate actions. It passed in 9.070 s. The environment was PAPER.
The proof commitment was
`ee9b7a6e52fabe75db8c190af42945a3baebfd098a40714a9d4664ef0c3d3881`.
No account/order endpoint, database, publication or broker mutation was used.
The diagnostic pins runtime
`sha256:7d6e5418384336c0cf8f5c54bf8b5fdcdfaa5c4156e4a30a86e074407bff028b`;
it is separate from the final `bc734310` functional GO run.

That smoke test is not complete-window acquisition or financial GO. Its overall
report correctly remained NOT_PROVEN. Its backup lookup used the root checkout's
NAS template. Subsequent active Compose discovery found the existing local
operator-attested target; the functional diagnostic is separately scoped in
[the qualification decision](autonomy-qualification.md#local-functional-environment).

The first `bc734310` genuine provider preparation passed. Its whole preparation
wrapper took 1,828.329 s, including a 2.335 s retained-revision probe; the main
provider child command took 1,825.906 s. It selected 5,937 securities and admitted
5,799, with 2,366,806 paired stock source rows and 2,171,076 canonical rows across
426 sessions. The acquisition retained its original source observation clocks.
At the `04:38:26Z` diagnostic, inventory age was 1,821.970 s and stock ages were
593.580–1,645.435 s. No future source observations were used.

Real full-window admission took 64.872 s and emitted 473 batch renewal/progress
events while preserving the original absolute work deadline. Normalization took
188.003 s. These are observed final-run timings, separate from the controlled
optimization fixtures above.

The first `bc734310` attempt passed 126-session canonical formation/restart
parity in 898.866 s, readiness in 57.851 s and financial health in 81.172 s.
All 14 health checks passed. Durable initialization, fresh-process resume and
retained parity passed in 185.610 s, 63.744 s and 74.928 s. The populated base and
exact backup status passed in 33.617 s and 6.229 s.

Its populated full restore failed with exit 4 after 128.149 s, with command-output
commitment `94049cb794dee651e2fde28b1c2f9dcc316cf77b657d801965183ed0e5db3d08`.
The captured refusal was `ShadowRuntimeRefused: running source/runtime identity
differs from the exact validated deployment identity`. No OOM event occurred;
PostgreSQL exit 137 followed explicit cleanup after the semantic validator
exited. Private-project cleanup passed in 1.359 s. This is a failed attempt.

The harness had masked `/tmp/req/requirements.lock` for ordinary workers while
the production restore launcher retained its visibility; the file digest belongs
to exact environment identity. The harness correction and required new cold run
are documented in [the qualification decision](autonomy-qualification.md#private-harness-filesystem-identity).
No production identity guard, existing book or admission is changed. Original
horizon-triggered renewal was not exercised; explicit base/status/restore calls
are recorded separately.

Two network-disabled identity probes confirmed that `image_lock_sha256` was the
only differing environment field. The masked CLI hash exactly matched the failed
attempt's original durable identity. Independent corrected-harness preflight
then produced identical complete identities under ordinary CLI and unchanged
production restore profiles, with the baked lock visible and temporary-file
create/read/remove successful as UID 10001. The reviewed v3 driver differs from
v2 only by its dedicated temporary mount and `TMPDIR`; its SHA256 is
`b7da38bd7856e82014d98d78c64cc3200409b1de52bbca9928996c3534ff5da8`.
The new cold attempt used an empty private database, fresh backup namespace and
new native identity. The implementation and test images were unchanged.

## Historical bc734310 corrected cold functional qualification: PASS

The corrected v3 attempt passed both `functional_status` and
`financial_proof_status`, with `private_project_stopped=true` and cleanup PASS.
Its native source identity was
`9004720bf9d30f0771917c199394efa52dc1cf4dd0d8013bf576612ff23da1b3`.
The original whole-run deadline remained `2026-10-17T07:09:03.933040Z`.
No failed book, checkpoint or admission was changed or reused.

| Genuine producer/check | Result and command elapsed |
| --- | --- |
| Initial full semantic restore | PASS, 24.259 s. |
| Complete provider preparation | PASS, 1,508.183 s main child; 1,509.968 s whole wrapper including the separate 1.729 s retained-revision probe. |
| Completed-input diagnostic | PASS, 5.542 s. |
| 126-session canonical formation/restart parity | PASS, 873.001 s. |
| Read-only readiness | PASS, 54.132 s. |
| Read-only financial health | PASS, 80.854 s; all 14 checks true, zero database writes, duplicate keys or chain gaps. |
| Native durable initialization | PASS, 176.844 s. |
| Fresh-process durable resume | PASS, 69.382 s; state, full ledger, retained record, checkpoint and execution-journal hashes unchanged. |
| Retained canonical restart parity | PASS, 75.729 s. |
| Populated base backup and exact backup status | PASS, 31.979 s and 6.295 s. |
| Populated full semantic restore | PASS, 108.018 s. |
| Private-project cleanup | PASS, 2.259 s. |

The provider window contained 426 sessions, 5,937 selected and 5,799 admitted
securities, 2,366,806 paired stock source rows and 2,171,076 canonical stock rows.
It made 133 committed OpenFIGI mapping observations and 630 committed stock
transport observations; these counts exclude unpersisted corroboration calls.
At the `2026-10-17T05:35:46.107423Z` diagnostic, original inventory age was
1,507.950 s and stock observation ages were 572.177–1,343.633 s. No future
observation or refreshed observation timestamp was used. The published-input
diagnostic measured 1,575,459,863 database bytes; it is an observation, not a
final post-book size or a disk-space improvement claim.

Full admission checked the actual 2,366,806 rows in 56.631 s with 473 working
batch progress events. Normalization produced 2,171,076 canonical rows in
163.980 s. These observed timings are separate from controlled before/after
optimization fixtures and do not establish a deployed speedup.

The populated backup `base-20261017T055805Z` restored the genuinely attested
`2026-10-16` book at publication version 1, with no reconstruction substitute.
Validation remained read-only, with no bound account, zero commands and
automation disabled. The semantic process exited 0 without an OOM event;
PostgreSQL's later exit 137 followed explicit cleanup. The production identity
guard, restore resource caps and semantic validator were unchanged.

The cold qualification command was the following; bracketed paths are private
operator/evidence locations rather than credential values:

```sh
python3 isolated_financial_go_v3.py \
  --repo <git-checkout> \
  --runtime-image sha256:a0d52b8f0380025829b85464c63836fb113f28fa9eac3369a106c5a1957de01c \
  --commit bc7343100d9d8ba3357c339242fbf5962c1111cd \
  --operator-config <existing-operator-config> \
  --credentials-file <local-untracked-env> \
  --workspace <new-private-directory> --budget-seconds 7200
```

The sanitized evidence archive contains 23 reviewed files, including all five
final JUnit selections, the three attempt summaries, reviewed driver versions,
identity probes, separate host-import proof and manifest. It is 78,223 bytes with SHA256
`ca0719884bbfc740b0f7b905b7b26e50e19720885ad69a6dcafd13aa37a56270`.
Independent member/hash, status-binding and redaction checks passed. Private
keys, configuration, raw logs, provider responses, database backups and WAL are
excluded. The archive is functional evidence, not a signed release certificate.

## Host probe import follow-up

The first PR head `9352fb59ae227e4c8e8312fe68b76096cdbeb835` failed the GitHub
Sentinel safety runtime-boundary check: the read-only data-preflight host script
called `probe_output` without importing it. The repair adds that one explicit
import, restoring the documented shared parser contract. The fixed script SHA256
is `7d94122ef8f9ab60644d647d62efc59c5f9ed78d83e944a4e0c21dda4197320d`.

The existing native integration reproduced the actual `NameError` before repair
(exit 1, 12.677 s) and passed after repair (exit 0, 45.421 s,
`GO_PROBE_RUNTIME_INTEGRATION_PASS`). Its six read-only checks and authentication,
mutable-import and receipt-ancestry refusals passed. The corrected run used only
a verified private Docker graph, no host ports, and successful cleanup. The
command, from an isolated integration checkout, was:

```sh
python3 scripts/test_go_probe_runtime_integration.py \
  sha256:a0d52b8f0380025829b85464c63836fb113f28fa9eac3369a106c5a1957de01c
```

Three directly relevant existing test files passed 17 tests in 8.07 s:

```sh
docker run --rm --network none --read-only \
  --tmpfs /tmp/sentinel-tests:rw,mode=1777 \
  --mount type=bind,source=<feature-worktree>,target=/review,readonly \
  --workdir /work --env PYTHONDONTWRITEBYTECODE=1 \
  --env SENTINEL_REPO_ROOT=/review --env TMPDIR=/tmp/sentinel-tests \
  --entrypoint python \
  sha256:e042a245195c46e9c127138f66d1679a322757b0f36cf9a4e06e3f13c2495065 \
  -m pytest -q -p no:cacheprovider \
  /review/tests/sentinel/test_go_readonly_data_preflight.py \
  /review/tests/sentinel/test_go_preflight_vendor_cursor_clock.py \
  /review/tests/scripts/test_sentinel_bringup_source_liveness.py
```

This is a read-only host-source overlay test. The existing test lens retains the
old embedded host script and is not relabelled as containing the repair. The
native runtime image does not package `scripts/`; its Sentinel/shared source,
embedded runtime probe expression and completed genuine financial GO producer
chain are unchanged. The corrected host script and its proof received independent
review. Fresh GitHub validation is required on the updated PR head.

## Acquisition checksum migration follow-up

Further mutation qualification exposed a genuine legacy-schema migration bug.
PostgreSQL names the original inline reference checksum
`sentinel_acquisition_parts_check`; the migration removed a different name.
The surviving legacy checksum rejects a valid schema /2 SEP auxiliary reference
of 1,288,907 bytes when its reference and price-content hashes differ. Fresh
databases also retained two equivalent checksum constraints. The disposable
PostgreSQL reproducer confirmed the rejected valid insert and exact catalog
names before the repair.

The [documented migration decision](autonomy-feed-remediation.md#acquisition-reference-constraint-upgrade)
removes the two explicitly owned reference-constraint names and installs one
validated canonical checksum. Existing /1 fallback, byte bounds, exclusivity,
immutability and corruption refusals remain required. Authentic fresh/legacy
database regressions and the acquisition mutation harness cover the repair.

This changes runtime source after `bc734310`. The preceding immutable-image
and genuine financial GO evidence remains attributed to that earlier runtime.
Fresh source profiles, immutable images, software checks and a new real-provider
financial/backup/full-restore GO passed for e917 as recorded above. This local
qualification precedes publication; exact-head GitHub validation is tracked on
the pull request separately.

The same `a437e7fe` CI run also found two stale source-codec fixtures in a
1,777-test shard. Their manifest double omitted the published reference/source
evidence now required for authenticated native asset identity. The unchanged
`e9172f44` test image reproduced two failures and three passes in 1.26 s. Updating
only that test file produced five passes in 1.07 s. Its digest-addressed database
double exercises the production evidence checksum and identity-binding readers;
the test asserts the exact evidence reads and canonical/native asset mapping.
The original lossy-symbol-conversion falsifier remains unchanged. Independent
review confirmed a test-only repair with no runtime guard bypass. The original
image is not relabelled as embedding the updated fixture.

### Recovery fixture compatibility

Further `a437e7fe` CI failures exposed physical-format assumptions in five test
and support files. The financial oracle now reads the complete ledger through
the storage codec and chunk reader. Its independent published-price Decimal
arithmetic, whole-share quantities, long-only cash, historical fees, twenty
slots, holdings, Core NAV and funded stock/BIL NAV assertions are unchanged.
Cash, trade-price and funded-NAV mutations are encoded with valid storage
checksums and still fail at their specific economic assertions. The checkpoint
case rehashes logical state, proves an unchanged positive restart, and retains
the exact `CHECKPOINT_RECORD_BINDING_CHANGED` refusal.

Only those three test/support files were overlaid on the unchanged
`e9172f44` runtime/test images. Four affected selectors passed in 320.082 s,
including genuine `pg_basebackup`/`pg_verifybackup`, separate PostgreSQL restart,
accounting parity and next-session advance for both inline and compressed
series variants. The production economic validator is not used as the oracle.
Existing immutable ledger chunks are not rewritten by the economic mutations.

The other two test files now create privileged physical corruption inside an
explicit local replica-role transaction, then restore and verify the ordinary
role before invoking the production reader/verifier. The missing rows are
asserted. All three affected cases passed in 6.33 s; their two surrounding
files passed 93 tests in 13.45 s. `benchmark_axis`, `empty_session` and
`restore_payload` mutations each died at the intended missing-refusal assertion.
Production retention guards and all original recovery refusal expectations are
unchanged. These groups overlap.

The exact Docker argument arrays, source hashes and image/overlay attribution
are preserved in `formed-accounting-fixture-remediation.json` and
`tamper-fixture-remediation.json` in the sanitized evidence archive. Their
pytest selections were:

```sh
python -m pytest -q -p no:cacheprovider --tb=short \
  'tests/sentinel/test_rolling_restore_integrity.py::test_populated_physical_restore_preserves_book_and_advances_next_session[inline]' \
  'tests/sentinel/test_rolling_restore_integrity.py::test_populated_physical_restore_preserves_book_and_advances_next_session[compressed]' \
  tests/sentinel/test_rolling_restore_integrity.py::test_published_price_oracle_refuses_a_dollar_of_invented_cash \
  tests/sentinel/test_rolling_initialization.py::test_changed_state_cannot_be_self_rehashed_into_checkpoint
python -m pytest -q -p no:cacheprovider --tb=short \
  tests/sentinel/test_rolling_reader.py tests/sentinel/test_rolling_snapshot_storage.py
```

## Remaining acceptance boundaries

The earlier `05c516a6` isolated run passed genuine initial backup/full restore
and real provider preparation; the latter took 1,608.384 s and retained 159
acquisition parts before publication cleanup. Its 126-session canonical
formation/restart parity passed in 1,098.388 s; read-only readiness and financial
health commands then passed in 89.146 s and 97.759 s. Genuine durable
initialization, fresh-process resume and retained parity passed in 208.256 s,
71.525 s and 65.468 s. The populated full restore failed with exit 4 after
183.732 s (`POPULATED_FULL_RESTORE_NOT_PROVEN`); its command-output commitment is
`4bed9c0dd4ad93beac0b772f1f2bbb7fb7cfd58b97e3e6a5ce8d2ee0570d3df4`.
The private project stopped cleanly. This failed attempt is preserved and does
not qualify the final repair bytes. Its cause remains UNKNOWN: the earlier
driver retained only output hashes, while ephemeral containers and raw error
output were removed. The final run has an independently reviewed passive
observer to retain private restore exit/OOM diagnostics without changing the
qualification command or its outcome.

The corrected `bc734310` isolated local functional GO passed before publication.
Genuine initial and populated backup/restore producers passed. Automatic
horizon-triggered renewal/resume remained NOT_EXERCISED (zero calls); controlled
renewal and unattended-operation tests are recorded separately above. No
unexecuted automatic-horizon stage is labelled PASS.

Independent physical backup durability, NAS capacity, protected CI, deployment
admission and live trading remain unproven. [Live readiness](live-trading-readiness.md)
records native activity, settlement, corrections, finality and recovery evidence
still required before a separately reviewed live authority gate can change.
No live capability flag or paper-only execution fence was removed.
