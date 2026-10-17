# Automation clock sampling qualification — 2026-10-17

Exact-image tests and fresh local real-provider GO passed for PR #530.
Qualification is local; this grants no live authority or protected certification.
No installed stack was changed and no native account checks were performed.

## Frozen identity

| Subject | Identity |
| --- | --- |
| Source | `e8f04420ce1fd3c279c0ca0336ad060c40b911da` |
| Runtime | `sha256:8b117d65847a8675ae48e73d3596ee253b9feeb5e351e4958e2e7288e365b43c` |
| Test image | `sha256:0561f77b3d7997edc8ea7f20c98163842d7171ecb60ba3d108cc789811ac20aa` |
| Clock profile SHA256 | `885ce3556ee3eae0aab3a02af313dc20ecc5e28ceff9fffe0d1c96192b809372` |

Design preceded implementation in
[automation clock sampling](automation-clock-sampling.md).
Uncertain clock samples WAIT before financial work; material skew still refuses.
The five-second limit is unchanged. Retained compatibility has authority effect
NONE and exact finite pins; historical descriptors/native checker are unchanged.

## Exact-image evidence

Production imports `/app/sentinel`; tools/tests are `/work`, without source
overlays. All 22 runtime layers are preserved. The 344-file source identity is
`9ab089847334fe48a69d8ed3d5ba1af59bb6d63118c876e9c7624c900814fc1a`.
Baked requirement hashes remain intact through verified read-only `/tmp/req`.

| Check | Result | Sealed receipt |
| --- | --- | --- |
| Automation/continuity/composition/clock | 459 passed; command elapsed 87.827s | `clock-exact-automation.json` |
| Source profiles/current-source falsifier/shards | 366 passed, 21 deselected; JUnit 14.104s | `clock-compat-evidence/exact/clock-exact-compatibility-qualification.json` |
| Actual pre-clock formed book | 1 passed, 93.23s | same compatibility receipt |
| Native transport/history/funding/recordings/tools | 250 passed, 2.405s | `clock-exact-native/clock-exact-native-qualification.json` |
| Existing fill/cash/execution/recovery | 225 passed, 42.805s | same native receipt |
| Fixed offline acceptance | 23 results, 1.371s; SIMULATION_ONLY | same native receipt |
| Image-build groups | 46 passed; 1,581 passed with one warning; 79 passed | `clock-exact-qualified-handoff.json`; original build log retained locally |

Zero JUnit failures/errors/skips. Groups overlap; do not sum as distinct tests.
The separate formed case does not replace all 21 deselections. It uses the
authentic 343-file 18a4c8b7 predecessor, forbids reformation/acquisition, preserves
origin/rows/state and proves admission/restart with zero broker commands.

## Before failures and corrections

`automation-clock-sampling-before.json` executes the old
production AST with substituted clock/database seams and no external access.
A 1.6ms backward correction and six-second scheduling gap after the first wall
read both caused fatal `AutomationRefused`.

Preserved intermediate attempts:

- 42 passed/3 failed: parent-local callback instrumentation could not observe
  the isolated child. Shared-file instrumentation fixed it; 45 then passed
  before three boundary cases were added.
- First mutation harness NOT_QUALIFIED: copied globals bypassed virtual-clock
  monkeypatching; corrected to actual module globals.
- Layout attempt: 342 passed/1 failed/4 setup errors/64 skips; `/tmp` was
  read-only and source changed. No qualification claimed.
- Broad run: 409 passed/2 failed. Two frozen-wall/database fixtures needed
  coherent virtual monotonic time; original behavior assertions remain.
- Compatibility: 168 passed/2 failed/1 deselected. A historical falsifier
  targeted a new successor, and duplicate open-time validation broke its read
  count. Both corrected; no golden or safety limit weakened.

## Earlier evidence retains its attribution

Earlier c712-lens source overlays produced
`clock-sampling-qualification/clock-sampling-qualification.json`,
two before-method falsifiers and seven intended guard deaths;
`clock-sampling-qualification/clock-service-fixture-remediation.json`
includes those same 48. `clock-compat-evidence/clock-compatibility-qualification.json`
records 365 + separate guard 1 + formed 1; its 13-case precision baseline repeats 12
shards. `clock-compat-evidence/clock-precision-ci-qualification.json`
removes `if outer > limit:`: intended `DID NOT RAISE
TransientInfrastructureFailure`, not another skew error. None is a new-image
mutation run.

Historical c712 exact-image and GO evidence retains its original scope in
[native-read qualification](native-read-qualification-results.md). Earlier
e366 native mutants 9/14 remain source overlays.

## Fresh isolated GO — PASS

`clock-go-e8f04420-b-final.json` records functional, financial and cleanup PASS
for `sentinel-review-20261017t162128-e8edd0ec9700`. Preparation/publication,
canonical formation/restart parity, readiness, all 14 health checks, durable
initialization and separate-process resume, retained parity, two base backups
and full semantic restores all passed. Six session/hash identities matched.
The populated restore has attested saved rolling state at 2026-10-16, read-only
verification, unbound account, automation disabled and zero broker commands.
Private-project cleanup passed; broker mutation attempts were zero.

Actual inputs: ALPACA_OPENFIGI, policy
`sentinel.alpaca-openfigi-operational-source/3`, normalization
`sentinel.alpaca-openfigi-dividend-current-window/3`, 426
sessions through 2026-10-16, 5,937 selected/5,913 admitted, 2,198,840 canonical
rows, 159 components and 528,148,880 committed response bytes. Counts exclude
unpersisted corroboration. Original source clocks remain preserved in the
receipt; stock observations were 16:26:33–16:40:54 UTC, with 504.201–1364.987s
ages at the 16:49:18 diagnostic, not relabeled as current observations.

Financial-health measurements: preparation 1,536,952ms; full-forward replay
851,711ms. Distinct host command elapsed values are 1,535,152ms for preparation
and 851,663ms for canonical parity. Health measurements passed existing thresholds.
Automatic horizon renewal/resume was NOT_EXERCISED: zero calls. The two actual
backup/restore milestones do not qualify that separate branch.

The before-bootstrap observer closed normally: 12 actors/49 events, zero captured
OOM events, all its readers closed and project absent. Sixteen discrete samples
observed maxima of 736.6MiB worker and 858.8MiB Postgres; these are not whole-run
peaks. Auto-stat failures 77/inspect failures 3 and rejected 13/unverified 16 count
inspection attempts, potentially repeated IDs. Unlabeled restore actors were
excluded. Docker CLI has no explicit server-subscription ACK; the handshake
proved the event-reader process was alive before bootstrap release. Whole-run
OOM absence remains NOT_PROVEN. Raw logs stay private.

Attempt a remains FAIL before actors: `PRIVATE_OBSERVER_HANDSHAKE_EXHAUSTED`,
with cleanup PASS (`clock-go-e8f04420-a-handshake-failed.json`). Its separate
`clock-go-observer-e8f04420-a-host-cleanup.json` records zero actors/events,
explicit host-reader stop and verified absence. The original observer finally
did not execute; neither GO nor whole-run OOM absence is claimed for it.

## Reproduction and receipt pins

Receipt paths identify archive members; other paths identify repository files
or container locations. Receipts contain complete Docker/in-image argv,
selectors and XML hashes.
Isolation: network-none/read-only, 2 CPUs, bounded memory/tmpfs, private evidence,
disposable Postgres, no source overlay. Source uses exactly
`-k 'not formed and not preserved'`. Separate commands:

`python /work/tools/sentinel_native_acceptance.py --output /evidence/clock-exact-native-offline-acceptance.json`.
The compatibility receipt contains the full separate formed-book selector.

Overlay mutation: `python -m tools.sentinel_readiness_falsifiers --child clock_precision`.
GO uses unchanged `isolated_financial_go_v3.py` (SHA256
`b7da38bd7856e82014d98d78c64cc3200409b1de52bbca9928996c3534ff5da8`)
through `run_clock_observed_go.py`, with explicit private config and original
deadline including handshake; cleanup has its separate bounded allowance.

| Receipt | Bytes | SHA256 |
| --- | ---: | --- |
| Automation | 1,786 | `33d27dee520827fc11f0a015feb00c523a2c7b6135fc3b2f4ab11b7422436f92` |
| Compatibility | 6,917 | `a4fffd85ade87446fa77aa0a61152c0af93bea856e4d7b4cf69e46d74dba5e0e` |
| Native | 3,827 | `2fbda6d7d67d36b0bca7efd1c95ec529162460c4096cace8856b385021d8c5e0` |
| Failed handshake a | 2,659 | `cba4b4dfb0f9419125fa9811786ce7bbf741b6a45cac555eb0f3bbd513d2ce7f` |
| Final GO b | 17,024 | `45d36375fd61c1c44bc1a7987f536d900313e7526449c8cd29a4bda80f6032af` |
| Qualified aggregate | 2,416 | `44f9f7a0a5133be2259e0f932f74574193869688b6fed430c7acb0bbc19479c9` |
| Observer closed summary | 4,496 | `f83b4bfad9bbcbf0b7579d0ef1bf4570cc84d9150cbb99595a9a96db15e9f76d` |

The sanitized archive is `clock-sampling-evidence-e8f04420.zip`, 118,880 bytes,
SHA256 `e392c3a19d4c5e7e152d85ba19b76d03292a21b5ace42e402d7f23cbe95fe8fb`.
It contains 43 explicitly selected evidence files plus `manifest.json`; all
member sizes, hashes, CRCs and the exact inventory were verified. Raw logs,
environment files, databases and private captures are excluded.

Native account checks remain DEFERRED. History completeness, late-publication
finality, settlement, close-cash finality, restore-grade order recovery and live
authority all remain NOT_PROVEN; offline PASS promotes none. The existing
operator-attested local backup target was used; physical independence/NAS,
protected certification and live activation remain NOT_PROVEN.
Market-data/canonical-book/logical-recovery GO passed within this local scope.
No raw logs, recordings, accounts, balances, credentials or recovery keys are
included here.

The initial `5d572180` handoff following the tested commit changed documentation
only. Its runtime, tooling, tests and workflow bytes remained those qualified
at `e8f04420`.

## CI fixture follow-up — 2026-10-17

The [automation CI job](https://github.com/flabber1835/stocker/actions/runs/39053365224/job/117457503377)
ran the complete registered lane: 478 passed and six failed. The earlier local
selection omitted the startup-contention and worker-source-recovery modules.
Those fixtures froze the scheduling clock while monotonic time advanced; the
production sampler correctly classified their inconsistent samples as WAITING.
Consequently they never reached their intended lease, post-tick or recovery
assertions. This was a test-fixture defect; no production guard was relaxed.

An explicitly selected shared `frozen_clock_sample` fixture now provides
coherent wall, monotonic and database times only inside the original production
sampler. Its context restores real clocks before leases, callbacks, supervision
and process reaping. It is used only by the affected frozen-time tests, including
the two earlier service fixtures. The clock falsifiers retain their own clocks.
All 293 original assertion expressions in the three changed test modules are
AST-identical to `5d572180`.

The complete eleven-module CI automation command passed locally: **484 passed,
zero failures/errors/skips**, 11 fork deprecation warnings, in 163.16 seconds.
The unchanged `--fail-under=100.00` gate passed with **796/796 statements and
316/316 branches**, no partial branches or exclusions. This reproduction used
the exact test image listed above, three read-only test-file overlays, and no
production source overlay. All 344 production Python files were stable before
and after. Runtime, tooling and workflow bytes remain unchanged, so the earlier
real-provider GO retains its original source/image attribution.

The receipt is `ci530-automation/a/qualification.json`, SHA256
`c2e57901fc4e238fd52d79450a30698fd13b5cedbbe07b10955a06ba07682af1`.
Its companion `container-result.json`, `automation.xml`, `coverage.json` and
`assertion-preservation.json` retain exact commands, source/test hashes and
coverage results. These follow-up test-overlay results are separate from the
original immutable-image archive above; they do not relabel that archive.

The checkout's `python tools/sentinel_ci_shards.py --root . --lane
sentinel-automation` selected these eleven modules. The in-image commands use
`COVERAGE_FILE=/evidence/automation.coverage` and match CI's coverage ownership:

```bash
python -m coverage run --branch --source=sentinel.automation.service -m pytest \
  tests/sentinel/test_activation_startup_contention.py \
  tests/sentinel/test_automation_clock_sampling.py \
  tests/sentinel/test_automation_composition.py \
  tests/sentinel/test_automation_generation.py \
  tests/sentinel/test_automation_p1_continuity.py \
  tests/sentinel/test_automation_process_contracts.py \
  tests/sentinel/test_automation_safety_seams.py \
  tests/sentinel/test_automation_service.py \
  tests/sentinel/test_automation_service_fault_paths.py \
  tests/sentinel/test_automation_worker_source_recovery.py \
  tests/sentinel/test_issue_201_automation_financial_grade.py \
  -q -ra --junitxml=/evidence/automation.xml
python -m coverage report --precision=2 --fail-under=100.00
```
