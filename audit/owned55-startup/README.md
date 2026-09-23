# Owned55 and $50k formation: local evidence

Work: 2026-09-22–23. Verified main base:
`ee23c894c97a2c4023654ce3a56a62728f5b061e` (#430), freshly fetched again before
delivery. Branch: `codex/owned55-bootstrap`. Design was committed first as
`bce259745810c46c67777ff132a1a335a83e9cdd`. See the PR head for the reviewed
implementation commit; `implementation-source.json` pins the tested Python files.

**Owned55, fresh historical formation and local acceptance are implemented.**
Final-head CI and deployed input/transport/resource evidence remain separate
gates. This report is not permission to deploy and is not economic certification.
The original implementation evidence below is preserved; the integrated GO
evidence and handoff follow it. New policy decisions were recorded in commit
`07105770273acce0ca6f48acdd27ecf147577cd7` before integration code.

## What is established locally

- The new production identity applies a 55% ceiling after five severe owned-book
  closes, releases after eight healthy closes, and preserves lower parent
  allocations including independent zero causes. It never changes Core holdings.
- New service, automation, panel and deployment defaults use $50,000. Explicit
  capital remains explicit; source, policy and state identities cannot silently
  relabel old books. Execution uses independently observed account capital.
- The candidate formation wrapper calls canonical feature warmup and kernel:
  252 feature sessions and 126 economic sessions; checkpoints at 0, 1, 47, 63,
  125 and 126 reproduce uninterrupted state exactly. Operational price state
  remains at most 300 sessions. Candidates are explicitly `NOT_ADMITTED`.
- A held security survives a rename and doubles shares at a 2:1 split without
  creating cash. Its dividend becomes a receivable, then cash on the next
  session. Every synthetic session reconciles cash and shares from ledger
  movements. Independent whole-share math uses $50k, not accumulated shadow NAV.
- Rejected duplicate/gapped inputs, changed source/capital, checkpoint tampering,
  and a late failure after book calculations cannot advance the candidate.
- Current controller breadth uses residual-correlation peers, not sector labels.
  A mixed stressed book distinguishes the two and is invariant to sector labels;
  bypassing peer breadth is killed by the test. Exchange labels are also ignored
  by current eligibility, with positive admissions proving the comparison is not
  a vacuous empty book. Future first-session dates and unknown security types
  prevent admission. Historical sector/exchange membership is not a requirement.

Fresh GO now fetches one sealed 379-close Sharadar generation, warms 252 closes,
then advances the same canonical book/controller for 126 historical sessions.
The current close creates the first forward decision. Current-information
metadata is an explicit initialization policy, not historical PIT reconstruction.
Ordinary acquisitions return to 300 sessions and strategy price memory stays
bounded at 260. Historical events produce no broker commands or execution plans.

Every formation transition has a source/configuration-bound authenticated
checkpoint. An interrupted attempt resumes exactly once. A newer generation
requires a fresh replay after authenticating and retaining the old attempt;
capital or strategy changes refuse. Authenticated formed origin is distinct from
ordinary cold genesis, and its identity survives daily advancement and restart.
The independent live strategy baseline starts at $50,000; the formed Core's
historical gain is not a deposit. Execution sizes from actual account capital.

The first funded-open calculation removes the Core's hypothetical rotation
fees and charges one entry into the resulting stock/BIL composition. A flat
half-stock/half-cash Core at full allocation returns 0.9995 after 10bp stock
entry, not 1.0000. A $50 gross gain with $9 hypothetical Core rotation fees on
$10,000 has gross factor 1.005, not 1.0041. These independent cash equations and
their deliberately broken variants are retained in the acceptance tests.

| Reviewed production boundary | Acceptance |
| --- | --- |
| `sentinel/controller/owned_impairment.py:31`, canonical kernel and restored session envelope | Exact five/eight boundaries, missing signal behavior, parent zero, active target connected to the kernel; controller mutations |
| `sentinel/feed/operational_snapshot.py:58`, typed window and catalog migration | Fresh 379/ordinary 300 separation, full source readiness, existing 300-only catalog upgrade without changing an old manifest |
| `sentinel/core/formation_inputs.py:9`, `sentinel/core/formation.py:53` | Canonical feature warmup and daily transitions, source/cursor binding, independent cash/share/action oracle, bounded state and interrupted replay |
| `sentinel/formation_bootstrap.py:81`, `sentinel/formed_origin.py:50`, rolling initialization/checkpoint | Real empty PostgreSQL to formed origin, HMAC tamper refusal, per-session commit acknowledgement loss, no historical commands, immutable restart |
| `tools/sentinel_operational_parity.py:92`, host GO proof validator | Read-only full formation, current/restored transition parity, old feature-only proof refusal, no duplicate feature-corpus allocation |
| `sentinel/formed_economics.py:16`, shadow observation first-funded transition | Independent entry-cost equations, missing marks, no free entry/double rotation fee, unchanged $50k baseline and daily resume |
| Rolling paper preparation, projection, execution and journal | Verified formed shadow only, independently observed account NAV, held-basket decision-close prices, whole shares, acknowledgement/restart identity and duplicate submission prevention |

## Commands and results

Commands run from the worktree on Windows; Python is
`../bounded-feed-venv/Scripts/python.exe`. Local imports use
`PYTHONPATH=<worktree>;<worktree>/shared` (plus `/scripts` for GO checks).
No command below contacted a broker or NAS. Test groups overlap; counts are not
added together as a coverage claim.

```text
python -m pytest tests/champion tests/median5/test_warmup.py tests/sentinel/test_production_state.py -q -p no:cacheprovider --basetemp=../owned55-bootstrap-tests-a
71 passed in 40.78s

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_initialization.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_projection_and_executor.py tests/sentinel/test_shadow_service.py tests/scripts/test_sentinel_go_validate.py tests/champion tests/sentinel/test_historical_formation.py
302 passed, 1 failed in 643.44s

python -m pytest tests/champion tests/sentinel/test_historical_formation.py tests/sentinel/test_authority_static_architecture.py tests/sentinel/test_feed_static_architecture.py tests/sentinel/test_shadow_static_ownership.py tests/wealth_core/test_static_restore_ownership.py tests/sentinel/test_shadow_service.py::test_new_installation_defaults_to_fifty_thousand_across_runtime_callers -q -p no:cacheprovider --basetemp=../owned55-bootstrap-final-unit
96 passed in 148.08s

python audit/economic_399/rolling_status/run_local.py test tests/scripts/test_sentinel_go_validate.py tests/sentinel/test_shadow_service.py
96 passed in 1.06s

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_autonomous_deploy.py tests/sentinel/test_automation_runtime.py
76 passed in 4.79s

python -m pytest tests/sentinel/test_historical_formation.py::test_current_controller_uses_correlation_peers_not_sector_labels -q -p no:cacheprovider --basetemp=../owned55-bootstrap-sector-falsifier
1 passed in 20.70s

python -m pytest tests/sentinel/test_historical_formation.py::test_current_eligibility_ignores_exchange_but_requires_first_session -q -p no:cacheprovider --basetemp=../owned55-bootstrap-metadata-test
1 passed in 19.52s

python -m pytest tests/sentinel/test_historical_formation.py::test_rejected_input_does_not_advance_candidate -q -p no:cacheprovider --basetemp=../owned55-bootstrap-late-refusal
1 passed in 2.80s

python -B tools/owned55_startup_mutations.py --output audit/owned55-startup/mutations
8/8 KILLED; original source restored after each case

git diff --check
PASS
Python ast.parse over each changed/new Python file
23 files PASS (hashes in implementation-source.json)
```

The isolated Linux harness uses existing image `sentinel-test:ci`, image ID
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
`--network none --memory 4g --cpus 2`. It copies the read-only mounted worktree
into the container and runs its local PostgreSQL fixtures.

The one initial Linux failure was a GO fixture reporting $100k when the request
now defaulted to $50k. The guard correctly refused. The positive test now covers
both the new default and explicit $100k; negative fixtures use matching capital
so other faults are not masked. An intermediate Windows GO run had 58 passes and
one POSIX `0600` permission failure; the entire file passed in Linux above.
The original formation test mistakenly named `feed.sessions` instead of
`feed.seen_sessions`; its corrected bounded-state assertion passes. No golden
data was repinned, no xfail/skip added and no production invariant weakened.

## Real archive preview

`tools/historical_formation_preview.py` streams the original archive, not a
prebuilt portfolio. The 378-session slice is 2025-01-29 through 2026-07-31;
formation starts 2026-01-30. Original archive SHA256:
`7d86c6f728f0392516dec5e2a709c16d45b2f46bc139fe7f3d29af25ae4dfce8`.
Dataset identity:
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
Original archive, supplements and research golden outputs are preserved.

The runner uses the separately frozen sibling `../owned55-formation-runtime`;
348 hashes are in `preview-source.json`. Outputs/checkpoints are retained in
`../owned55-formation-preview`. The preview completed all 126 formation sessions
through July 31. Independent verification in `preview-verification.json` checked
the exact calendar, all unique session/state hashes, seven identically replayed
rows after checkpoint resume, every cash/share ledger movement and the 260-close
state bound. Final state is
`957fee76b5f4edeb3c001a3ef15a8f9055cc87aea32f6e11975446953303a449`;
checkpoint is `187ff76d03c383ece5dff1f27adeb6a7a01239fc2a0ceea7a1c8fe6b49b273d1`.
It holds 13 names, shadow cash $18,364.760295 and shadow NAV $59,232.990295.
The 55% endpoint allocation is the **parent** ceiling; the owned cause is inactive.
These values are formation mechanics, not qualified performance or paper capital.

```text
PYTHONPATH=../owned55-formation-runtime;../owned55-formation-runtime/shared
python -u ../owned55-formation-runtime/tools/historical_formation_preview.py --archive ../pit-source-5bdc6b39.zip --supplements ../economic-replay-merged-ee23c894/supplements-continued.json --output ../owned55-formation-preview --seconds 1800
# Only after that worker exits: the identical command with --resume.
python tools/verify_formation_preview.py ../owned55-formation-preview --output audit/owned55-startup/preview-verification.json
```

This archive has research SEP-tape/SEC identities rather than native Sharadar
permatickers. Its classification assumptions and known SILV issuer error on
12 warmup sessions remain explicit. It cannot authorize GO or establish
historically exact economic performance. No July checkpoint will be deployed:
fresh GO must acquire current inputs and build its own book.

The frozen preview uses the earlier `HISTORICAL_PIT_V1` research-fixture policy.
The production `CURRENT_INFORMATION_INITIALIZATION_V1` caller is independently
covered by the sealed-source PostgreSQL tests; the preview is not passed off as
production producer acceptance.

## Integrated GO commands and results

The same offline image runs `tools/owned55_local_validation.py`; its read-only
source mount is copied to a private directory before testing or mutations. Each
log starts with a frozen source digest. Earlier logs hash Python files under
sentinel/shared/tests/tools; the final runner also includes scripts. Resource
checks share the 4 GiB container with disposable PostgreSQL; a process high-water
measurement is not a separate enforced 512 MiB panel-container result.

```text
python tools/owned55_local_validation.py test tests/sentinel/test_formed_startup.py::test_first_funded_open_accounts_for_entry_and_preserves_formed_identity tests/sentinel/test_rolling_go_inputs.py tests/scripts/test_sentinel_go_validate.py
83 passed in 92.05s; formed-go-proof.log

python tools/owned55_local_validation.py test tests/v5 tests/sentinel/test_economic_boundaries.py tests/sentinel/test_nav_quantity_precision.py tests/sentinel/test_warmup_economic_contract.py tests/sentinel/test_issue209_simplified_ldrc_runtime.py tests/sentinel/test_issue_160_deployed_fenced.py tests/sentinel/test_operational_parity.py
299 passed in 40.08s; ci-fixture-regression.log

python tools/owned55_local_validation.py mutations
5/5 killed; formed-mutations-detailed.log retains actual failure output
python tools/owned55_local_validation.py mutations unsigned_formed_origin
Signature falsifier refined to start with an otherwise-valid forged chain;
formed-origin-signature-falsifier.log must show DID NOT RAISE without the guard.

python -m pytest tests/sentinel/test_authority_static_architecture.py tests/sentinel/test_feed_static_architecture.py tests/sentinel/test_shadow_static_ownership.py tests/wealth_core/test_static_restore_ownership.py -q -p no:cacheprovider --basetemp=../owned55-final-ownership
30 passed in 2.52s; final-ownership.log
python tools/validate_test_responsibility.py --base origin/main --output audit/owned55-startup/test-responsibility-final.json
PASS, no unowned tests

python tools/owned55_local_validation.py test tests/sentinel/test_rolling_initialization.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_paper_inputs.py
99 passed, 2 failed in 2439.96s; formed-runtime-regression.log. Both failures
were the former cold-book assertion that the first plan must contain new Core
dollar intents. A formed book already owns shares. The corrected acceptance
independently calculates its actual account share basket using exact Fractions,
then exercises the same current execution/retry path, without changing production
execution rules. See formed-paper-execution.log for the focused rerun:
python tools/owned55_local_validation.py test tests/sentinel/test_rolling_paper_inputs.py::test_real_paper_preparation_and_restart_reuse_only_verified_rolling_shadow
2 passed in 110.59s; formed-paper-execution.log.
python tools/owned55_local_validation.py test tests/sentinel/test_rolling_go_inputs.py::test_snapshot_parity_uses_canonical_warmup_without_creating_a_book tests/sentinel/test_formed_startup.py tests/sentinel/test_formed_economics.py
20 passed in 262.46s; formed-final-acceptance.log.
python tools/owned55_local_validation.py resource 5000
PASS: 5,000 securities / 1,895,000 rows / 126 formation sessions.
Publication 517.17s, formed origin 2930.22s, verified status 78.45s.
Status VmHWM 328.12 MiB < 512 MiB; shared container peak 3.2024 GiB < 4 GiB;
no OOM events. See formed-resource-summary.json and original logs.
python tools/owned55_local_validation.py test tests/sentinel/test_rolling_snapshot_storage.py::test_existing_300_only_catalog_migrates_without_rewriting_old_manifest tests/sentinel/test_formed_startup.py::test_authenticated_origin_cannot_change_context_or_seed
2 passed in 38.54s; final-migration-and-origin.log.
python tools/owned55_local_validation.py test tests/sentinel/test_formed_restore.py
1 passed in 39.80s; formed-logical-restore-final.log.
python tools/owned55_local_validation.py test tests/sentinel/test_rolling_retention_runtime.py
2 passed in 87.48s; formed-retention-restore.log.

python tools/owned55_local_validation.py test tests/sentinel/test_autonomous_deploy.py tests/sentinel/test_autonomous_deploy_driver.py tests/sentinel/test_autonomous_deploy_bootstrap.py tests/sentinel/test_host_python_compat.py tests/host_python38/test_env_ingestion.py tests/host_python38/test_env_review_fixes.py
970 passed in 39.02s; formed-deploy-timeout.log. Includes generated environment
parser cases because the bounded deployment setting passes through that parser.
python tools/owned55_local_validation.py mutations formation_health_timeout
python tools/owned55_local_validation.py mutations status_short_timeout
python tools/owned55_local_validation.py mutations late_status_acceptance
3/3 KILLED; formed-deploy-mutation-<case>.log retains the failures.
Eighteen distinct faults killed overall; repeated refinements are not counted twice.

Python ast.parse over final changed/new Python files
64 files PASS; integrated-source.json pins their bytes.
Python 3.8 ast.parse of scripts/sentinel_go_validate.py
PASS; actual host interpreter remains covered by required CI.
git diff --check
PASS
```

Intermediate failures are retained rather than hidden: `formed-startup-final.log`
had 18 passes and one failure because the startup-only checkpoint validator also
ran on daily checkpoint subclasses. Restricting the origin check to the origin
schema fixed that defect; first funded daily resume then passed. The initial
broader run in `formed-go-regression.log` was stopped after that same root cause
was identified; it is not counted as a passing run. A Windows attempt at the CI
fixtures stopped at collection because host deployment requires POSIX `fcntl`;
the complete affected group passed on Linux. CI at `7b2567ba` also exposed old
profile/default expectations and hand-built state fixtures with an unadvanced
Owned55 cursor. Fixtures now carry the new documented identity/cursor, preserving
the consistency refusal. No economic golden was repinned and no xfail was added.
The first logical-restore fixture mistakenly dumped its empty administrative
database. The restored runtime correctly refused missing schema. The corrected
fixture dumps the actual populated connection; no runtime/schema gate changed.

The scale probe exposed a disconnected deployment timeout: a synthetic test
provided a data-work budget that the real Config never defined, so deployment
fell back to five-minute process health. Its 30-second status timeout was also
shorter than the measured 78.45-second verified read. Real configuration now
supplies a separate 7,200-second data deadline (bounded 30–7,200), with each
verified status read capped at 300 seconds and the remaining deadline. A result
arriving after the deadline refuses. Real-Config clock-driven acceptance and
broken-wiring/deadline variants exercise the measured durations without an
hour-long artificial sleep. No causal source/open cutoff was changed.

The resource probe used PostgreSQL 17 inside the shared 4 GiB disposable
container. Its 311 sentinel/shared production Python files matched the runtime
at that check (`formed-resource-runtime-source.json`). The subsequent observation
authorization change modifies one of those files and adds two proof modules;
`resource-source-followup.json` records the exact difference. Durable formation,
storage and status paths retain their measured bytes. The new read-only proof
has functional evidence, not a new broad-universe resource measurement.
Later host deployment timeout changes are separately tested above. This proves
local synthetic scale mechanics, not deployed PG16, NAS concurrency or startup
latency. The child process budget uses `/proc` VmHWM; inherited RUSAGE_MAXRSS from
its larger parent is retained but is not treated as the child's high-water value.

## Final CI fixture and price-domain follow-up

CI at `a2570f4db42af446aeda3aefab61262803b1579c` finished with failures retained
in `ci-a2570f4d-findings.json`. All four internal-state lifecycle campaigns,
Wealth Core, replay, automation, operator, existing mutations, warmup, host Python
3.8, runtime build/PG16 recovery, browser, broker simulation and backup checks
passed. The remaining failed assertions came from stale fixtures or the missing
closed-list registration of the new formation SPY transport. Required workflow
aggregators correctly stayed red; no success is inferred from partial CI.

The contract fixture now independently supplies the Owned55 identity, parent
target and owned cursor, with new owned-cursor/ceiling falsifiers. Its exposure
falsifier uses a negative matched allocation so the ceiling check cannot mask
the long-only bound. The warmup mock now carries its actual warmup commitment.
The opening-freshness integration selects the actual Owned55 profile. The status
memory acceptance now restores the formed book and independently reconciles its
cash from ledger movements rather than asserting unspent cold-start capital.
Certification section 5b records the exact new SPY transport file before its
allowlist addition; the tokenizer remains strict, the file has only one named
SPY transport occurrence, and distinct SPY/equity/BIL inputs plus two deliberately
broken domain substitutions prove the separation. No production code changed.

```text
python tools/owned55_local_validation.py test tests/internal_state/test_contract.py tests/internal_state/test_restore.py
Collection error: nonexistent restore test path; final-ci-contract.log, no tests.
python tools/owned55_local_validation.py test tests/internal_state/test_contract.py tests/internal_state/test_physical.py
41 passed, 1 failed in 33.75s; final-ci-contract-corrected.log. The old upper-bound
falsifier hit owned_ceiling first; the isolated negative-bound falsifier then passed.
python tools/owned55_local_validation.py test tests/internal_state/test_contract.py tests/sentinel/test_feed_domains.py tests/sentinel/test_v5_opening_execution_freshness.py tests/median5/test_warmup.py tests/sentinel/test_rolling_initialization.py::test_composed_input_keeps_spy_equity_and_bil_domains_separate tests/sentinel/test_status_memory.py::test_formed_checkpoint_reuses_verified_observer_and_retains_economics
69 passed in 40.00s; final-ci-fixture-acceptance.log.
python tools/owned55_local_validation.py mutations formation_spy_domain
python tools/owned55_local_validation.py mutations formation_bil_domain
2/2 KILLED; formed-domain-mutation-<case>.log. Eighteen distinct faults overall.
```

## Canonical GO audit follow-through

The normal composition workflow at `c159e868` passed, but its PR campaign does
not invoke full canonical GO. Source review found a legacy-only publication
observer and disconnected legacy feed/readiness fault hooks in that manual
audit. The observer now authenticates the selected generation and reads the
rolling frontier; the hooks reach the actual rolling production calls. The
synthetic fixture uses $50k and explicitly covers at least 379 closes. These are
audit changes, with no change to production strategy or admission rules.

A manual `positive` campaign runs the real shell GO, local-full test lens,
PostgreSQL preparation, read-only formation/parity, promotion and panel handoff
once. It explicitly records no stage-sensitivity cases; the default `all`
campaigns are preserved. The full canonical positive run remains pending until
its exact-head output is retained and independently checked.

```text
python tools/owned55_local_validation.py test tests/production_composition/test_canonical_go_e2e_harness.py tests/production_composition/test_internal_go_stage_faults.py
56 passed in 5.45s; canonical-go-harness-check.log.
python tools/owned55_local_validation.py mutations go_legacy_frontier
python tools/owned55_local_validation.py mutations go_disconnected_preparation_fault
python tools/owned55_local_validation.py mutations go_disconnected_readiness_fault
python tools/owned55_local_validation.py mutations go_false_sensitivity_claim
4/4 KILLED for the intended assertion; each isolated unmodified test passed first.
Twenty-two distinct faults overall, including four audit-only faults.
python tools/validate_test_responsibility.py --base origin/main --output audit/owned55-startup/test-responsibility-final.json
PASS, no unowned tests.
```

The first two hook mutation invocations failed during an isolated import, not
at the intended assertion. Their `*.setup-failure.log` artifacts are retained
and do not count as kills. The test now sets its own script import path, and the
mutation runner requires an individually passing baseline before modifying any
source. The final retained mutation logs include that baseline and the specific
`DID NOT RAISE` failures for disconnected hooks. A mistyped initial ownership
tool path did not execute; the correct command above passed.

The first manual run, [35866335437](https://github.com/flabber1835/stocker/actions/runs/35866335437),
passed the composition checks but refused during the predecessor feed fixture.
Its retained `go-attempt-35866335437.json` has `all_pass=false`. The HTTP fixture
ignored ACTIONS' `action` filter: the renames-only preflight received the three
unrelated relation/dividend/split rows, while the complete ACTIONS capture
correctly contained no renames. Production stability refused the discrepancy.
The fixture now filters the requested action types without removing anything
from the unfiltered export. The HTTP acceptance test now includes the production
identity preflight and its full-range action corroboration.

```text
python tools/owned55_local_validation.py test tests/production_composition/test_canonical_go_e2e_harness.py tests/production_composition/test_internal_go_stage_faults.py
60 passed in 5.30s; canonical-go-action-filter-check.log.
python tools/owned55_local_validation.py mutations go_action_filter_ignored
Unmodified HTTP witness passed; ignored-filter mutant KILLED by unrelated rows
in the rename-only response. Twenty-three distinct faults overall (five audit-only).
```

No completeness guard, capability, production source evidence or golden was
changed to make this synthetic fixture pass. The successful full GO run remains
an outstanding gate; the failed attempt grants no authority.

## Formed observation authority and complete GO suite isolation

The second canonical attempt, [35867850976](https://github.com/flabber1835/stocker/actions/runs/35867850976),
passed source seeding and the populated physical backup, but correctly returned
REFUSED at software certification. Its monolithic Sentinel test process reported
a failure and then exited 137 without its final summary. Memory pressure is
suspected, not proven by an OOM record. The failed JSON and bundle/log hashes are
retained in `go-attempt-35867850976*.json`; no qualification is inferred from it.

Independent reproduction found an actual startup integration defect: paper
observation authorization still proved a 252+1 cold book, while the production
initializer used 126 economic formation sessions. Observation and GO now share
the canonical read-only formation adapter. The initializer independently reaches
the same state; the preview creates no progress, processed-session or fill rows.
Both candidate creation and the offline issuer refuse rehashed cold evidence
under Owned55. Legacy profiles retain their explicit cold proof. The selected
current-information policy and historical-certification limitation are unchanged.

Both local-full GO callers now run general, rolling, warmup and automation in
fresh network-disabled containers of the identical test image. All four must
pass before the logical Sentinel suite counts as complete. The Wealth Core
historical exclusions are unchanged. No test is skipped or repinned. Actual
full and partitioned pytest collections are compared independently for missing
and duplicate nodes; future ordinary test modules belong to the general group.

```text
python tools/owned55_local_validation.py test tests/sentinel/test_rolling_admission_readers.py::test_warmup_is_the_selected_canonical_production_transition
Before fix: 1 failed in 32.23s; observation-startup-before.log.
python tools/owned55_local_validation.py test tests/sentinel/test_rolling_admission_readers.py::test_warmup_is_the_selected_canonical_production_transition tests/sentinel/test_rolling_admission_readers.py::test_owned_candidate_and_issuer_refuse_rehashed_cold_warmup tests/sentinel/test_rolling_admission_readers.py::test_signed_rolling_candidate_installs_and_activates_with_reobserved_inputs tests/sentinel/test_operational_parity.py
12 passed in 79.36s; observation-startup-acceptance.log.
python tools/owned55_local_validation.py test tests/scripts/test_sentinel_go_validate.py tests/scripts/test_sentinel_go_suites.py tests/scripts/test_sentinel_single_runtime_go_build.py tests/scripts/test_sentinel_go_ci_runtime.py tests/sentinel/test_rolling_admission_readers.py tests/sentinel/test_paper_observation_authority.py tests/sentinel/test_operational_parity.py tests/sentinel/test_image_layout.py
178 passed, 1 failed in 179.13s; observation-go-partition-acceptance.log.
The negative decision-session case refused correctly but with changed message
ordering. Source bindings now retain their original precedence; test unchanged.
python tools/owned55_local_validation.py test tests/sentinel/test_observation_startup.py tests/sentinel/test_rolling_admission_readers.py::test_candidate_refuses_warmup_for_different_generation_or_strategy tests/sentinel/test_rolling_admission_readers.py::test_owned_candidate_and_issuer_refuse_rehashed_cold_warmup tests/sentinel/test_rolling_admission_readers.py::test_warmup_is_the_selected_canonical_production_transition
16 passed in 101.94s; observation-startup-final.log.
python tools/owned55_local_validation.py test tests/sentinel/test_operational_parity.py::test_owned_observation_refuses_legacy_publication_before_loading_formation
1 passed in 1.53s; observation-legacy-refusal.log.
python tools/owned55_local_validation.py mutations observation_cold_fallback
python tools/owned55_local_validation.py mutations observation_cold_proof_allowed
python tools/owned55_local_validation.py mutations observation_issuer_guard_removed
python tools/owned55_local_validation.py mutations go_partition_failure_ignored
python tools/owned55_local_validation.py mutations go_partition_misclassified
5/5 KILLED, each after its unmodified test passed; mutation-<case>.log.
Twenty-eight distinct mutants overall. Counts from overlapping test runs are
not added together as unique test coverage.
python tools/owned55_local_validation.py test tests/scripts/test_sentinel_go_validate.py tests/scripts/test_sentinel_go_suites.py tests/scripts/test_sentinel_single_runtime_go_build.py tests/scripts/test_sentinel_go_ci_runtime.py
109 passed in 0.46s; go-partition-final.log. Both real GO callers covered.
python tools/owned55_local_validation.py partitions
PASS: 5,610 collected nodes; general 5,103, rolling 345, warmup 20, automation
142. No missing or duplicate nodes; go-partition-collection-final.log.
python tools/validate_test_responsibility.py --base origin/main --output audit/owned55-startup/test-responsibility-final.json
PASS, no unowned tests; final changed/new Python source pins and syntax result
are in integrated-source.json. Changed GO host modules also parse as Python 3.8.
```

An initial host invocation including `test_sentinel_go_ci_runtime.py` could not
collect because Windows lacks `fcntl`; it executed no tests. The same tests
passed in the offline Linux invocation above. The first collection helper
invocation omitted the argparse `--` delimiter and did not collect tests;
`go-sentinel-collection.argument-error.log` retains this setup error.

The older Sentinel main job subsequently ended at its 75-minute limit:
5,091 general tests passed in 2,643.92 seconds, followed by only 13% of the 344
rolling cases before cancellation. `ci-b7577af0-time-budget.json` retains its
timestamps and job link. The formed-startup fixtures need more audit time. The
main lane now allows 150 minutes (other lanes remain 45); the full GO audit outer
budget is four hours and its manual job five hours. Production source, execution
and formation deadlines are untouched. An incomplete run still refuses.
Superseded GO attempt `35878014779` was explicitly cancelled before replacement.

```text
python tools/owned55_local_validation.py test tests/scripts/test_sentinel_ci_parallel_evidence.py tests/production_composition/test_canonical_go_e2e_harness.py tests/production_composition/test_internal_go_stage_faults.py
114 passed in 5.96s; ci-formation-budget.log. Coverage, failure propagation and
actual GO fault hooks remain required under the larger audit-only budget.
```

## Independent formation and provider-wait configuration

Final consumer tracing found a real configuration collision: the added formation
limit reused `SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS`. The real driver already
owned that setting for provider freshness (43,200 seconds by default), while
the new base Config limited it to 7,200. Copying `.env.example` therefore passed
the shared validator but failed actual driver construction. With no explicit
setting, the driver silently replaced the formation budget with its longer
provider budget. The earlier base-Config tests did not expose this boundary.

Formation now uses its own `SENTINEL_DEPLOY_FORMATION_TIMEOUT_SECONDS` and
`formation_timeout_seconds` property (default 7,200; range 30–7,200). Provider
waiting retains its existing separate range and default. The shared validator
has one entry per key and `.env.example` supplies both. The real driver accepts
the shipped settings; a late formation status cannot consume unused provider
time. This restores the documented separation without extending market cutoffs.

```text
python tools/owned55_local_validation.py test tests/sentinel/test_autonomous_deploy_driver.py::test_shipped_wait_settings_agree_with_actual_driver
Before correction: 1 failed in 0.27s, the actual driver refused the shipped
43,200-second provider setting; formation-setting-before.log.
python tools/owned55_local_validation.py test tests/sentinel/test_autonomous_deploy.py tests/sentinel/test_autonomous_deploy_driver.py tests/host_python38/test_env_ingestion.py tests/host_python38/test_env_review_fixes.py
966 passed in 39.69s; formation-setting-acceptance.log.
python tools/owned55_local_validation.py mutations formation_uses_provider_budget
python tools/owned55_local_validation.py mutations formation_env_collision
python tools/owned55_local_validation.py mutations formation_env_range_unbounded
3/3 new mutants KILLED after passing baselines; 31 distinct faults overall.
python tools/owned55_local_validation.py mutations formation_health_timeout
python tools/owned55_local_validation.py mutations status_short_timeout
python tools/owned55_local_validation.py mutations late_status_acceptance
All three affected timing mutants KILLED again; passing baselines and intended
failures retained in formation-setting-mutation-<case>.log.
python tools/owned55_local_validation.py partitions
Final collection after the two driver witnesses: 5,612 nodes (general 5,105,
rolling 345, warmup 20, automation 142), zero omissions or duplicates;
go-partition-collection-settings.log. All 85 changed/new Python files parsed;
the two changed deployment/environment modules also parse as Python 3.8.
```

Superseded GO attempt `35878872952` was cancelled before the replacement audit;
it does not qualify the corrected deployment settings.

## Remaining gates and concrete NAS handoff

| Gate | Severity / disposition | Required evidence and pass/fail |
| --- | --- | --- |
| Final source delivery | P1 release gate | Green required CI for the final reviewed PR head, user review/merge; retain exact main commit and image digest. No self-merge. |
| Canonical GO composition | P1 local qualification gate | Full positive real shell GO on the final head, bound runtime/test lens, fresh 379-close publication and formed read-only proof, zero broker/behavioral mutation, successful promotion and panel handoff. PR smoke alone does not close this gate. |
| Startup producer | P1 deployed input gate | Fresh admitted Sharadar generation with exactly 379 closes, permanent identities and required action/terminal terms. Missing/contradictory coverage is refusal, never inferred from an empty response. Current metadata policy must appear in formed origin. |
| C1/F6 cash authority | P1 provider gate, unchanged | Account-bound authoritative cash producer, incremental completeness, revisions and finality. Obtain accepted provider guarantees and retained interval evidence; ordinary cash equality or empty history is insufficient. See economic-audit-399-remediation.md:407 and sentinel/execution/alpaca.py:2052. |
| F19 native fills | P1 provider gate, unchanged | Native fill identity, exact order/asset/side/time, cumulative quantity/notional, corrections/busts and accepted average-price precision contract. No capability flag grants acceptance (sentinel/execution/alpaca.py:1715). |
| C3 predecessor recovery | P1 provider/deployment gate, unchanged | Complete predecessor-incarnation command evidence, durable owner and restart reconciliation. Unknown or missing coverage blocks certification/replacement (sentinel/execution/alpaca.py:2363; economic-audit-399-remediation.md remaining gates). |
| Deployed resources and restore | P1 NAS gate | Real startup within 4 GiB worker budget; status within 512 MiB panel budget; PG16 at configured 1 GiB, no OOM, measured latency/headroom and populated exact-point restore with unchanged origin/cursor. Local synthetic measurements do not establish NAS latency/concurrency. |
| Economic performance | Data-dependent, unqualified | Research archive classification/identity limitations remain. A performance number is not inferred from the formation preview or ordinary CI. Historical reference/golden identities are preserved. |

On the NAS, after the owner merges and approves deployment:

1. Check out the exact merged main commit. Verify the promoted image/source
   identity, fresh installation/empty behavioral lineage, reviewed `$50,000`
   shadow configuration and intended paper account with $50,000 initial funding.
   Actual execution capital remains independently observed; a different account
   balance is not silently rebased by changing the shadow. Keep broker credentials
   outside repository/evidence. Existing strategy state cannot be relabelled.
2. Retain a verified backup and runtime archive authority. Run the repository's
   ordinary GO preflight, including its explicit schema migration (the candidate
   axis constraint now allows 300 or the typed 379-close startup window).
   Do not alter the constraint or capabilities manually:

   ```bash
   bash scripts/sentinel-go-validate.sh
   bash scripts/sentinel-autonomous-deploy.sh --explain
   ```

3. Retain the complete GO bundle: exact commit/image, fresh source manifest and
   actions, `ROLLING_FORMED_STARTUP_AND_RESTART` proof with count 126 and matching
   source/state commitments, unchanged source during proof, read-only proof
   transaction and backup/host ownership checks. Any failed/stale clause is NO-GO.
4. Use the reviewed paper deployment flow only after GO permits it. Retain
   `FORMED_START_COMMITTED`, the authenticated `sentinel.formed-origin/1` receipt,
   feature/formation dates, source/policy, controller cursor, independent live
   starting NAV $50,000 and zero historical commands. At the next open, retain
   one current plan, whole-share projection from actual account capital and
   stable command identities through acknowledgement loss/retry. Restart must
   preserve the same origin rather than reform or deposit shadow gains.
5. Advance normally to a 300-close publication; verify the unchanged origin and
   one daily transition. Restore the populated database to an independently
   evidenced point, verify input/action retention, origin and command ownership,
   and compare all relevant state/ledger hashes. Retain memory/OOM/latency results
   under deployed service caps. Missing predecessor/provider evidence remains
   an explicit certification refusal, even if forward paper observation is safe.

NAS pass criteria must include the exact fresh 252+126 session axis, selected
metadata policy/source commitments, authenticated formed state and controller
cursor, actual paper starting capital and whole-share projection, restart
continuity, no historical orders, execution identity/reconciliation evidence,
and successful bounded-resource/restore checks. Any missing or stale required
evidence is NO-GO. Ordinary green CI cannot grant economic certification.
