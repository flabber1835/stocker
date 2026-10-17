# Native read preparation qualification — 2026-10-17

This implements the offline preparation phase authorized by the owner, based on
verified main `90a960547b58bb245c998ae3f70d0baed1fe95d0`. The independent live
account checks are deferred. No live credentials, account calls, funding, broker
mutations, deployment or activation were used in this qualification.

The implementation binds native reads to an exact account UUID, deployment,
environment, origin and takeover epoch. It traverses retail activities with
bounded resources, caches exact-order enrichment, preserves exact Decimal
evidence, detects contradictory replay and quarantines unsupported economics.
Partial or contradictory batches cannot expose a financial projection.
Native funding assessment always defers; simulation arithmetic has no spending
authority. Existing paper grants, command keys and production capability flags
were not changed.

## Evidence and limits

The dependency image was the existing Python 3.12.13 test lens
`sha256:e36658fabc42d3e0d85ec1031910a16925b0e2a8594c1f4c80397e3ea0637c31`.
Current source was mounted read-only or copied byte-for-byte into a disposable
offline snapshot. This is source qualification against locked dependencies,
not qualification of a new immutable runtime image. Docker networking was
disabled; temporary copies were removed after execution.

The frozen source manifest contained 343 Sentinel Python files, with manifest
SHA256 `a5705a1b835be14a51688a097f341eb0591c99877bca5691c6bd33013392863f`.
Before/after source stability passed. The new closed source profile is
`200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b`.
The historical autonomy descriptor remains byte-identical. Fifteen exact
historical admission predecessors have immutable main-history witnesses;
unknown predecessors, altered neighbors and missing additions refuse.

| Check | Result |
| --- | --- |
| New native transport, normalization, history, funding, recording and tooling tests | 245 passed |
| Existing guarded execution, native fill, cash and recovery boundary regressions | 225 passed |
| Fixed offline acceptance inventory | 23 passed; zero failures/errors/skips |
| Transport guard removal | 9/9 mutants killed at their intended assertions |
| Normalization/history guard removal | 14/14 mutants killed at their intended assertions |
| Tooling inventory, hash, credential, promotion and redaction falsifiers | Passed within the integration tests |
| AST syntax and Git whitespace checks | Passed |

The acceptance receipt says `PASS_OFFLINE_QUALIFICATION`, provenance
`SIMULATION_ONLY`. Native history completeness, late-publication finality,
settlement, close-cash finality, restore-grade recovery and live authority all
remain `NOT_PROVEN`. No capability was promoted. Earlier provider GO evidence
remains bound to its original source/image; it is not relabeled as evidence for
these native reads or for live operation.

## Reproduction

With the locked test dependencies, run:

```sh
python -m pytest -q -p no:cacheprovider \
  tests/sentinel/test_native_readonly.py \
  tests/sentinel/test_native_activity.py \
  tests/sentinel/test_alpaca_retail_history.py \
  tests/sentinel/test_live_funding.py \
  tests/sentinel/test_native_activity_recording.py \
  tests/sentinel/test_native_acceptance_tools.py

python -m pytest -q -p no:cacheprovider \
  tests/sentinel/test_guarded_execution_broker.py \
  tests/sentinel/test_native_fill_acceptance.py \
  tests/sentinel/test_autonomy_execution_remediation.py \
  tests/sentinel/test_alpaca_boundary_overlay.py \
  tests/sentinel/test_alpaca_simulation_cash.py \
  tests/sentinel/test_recovery_capability_boundary.py

python tools/sentinel_native_acceptance.py --output /private/new-acceptance.json
```

The source compatibility command is:

```sh
python -m pytest -q -p no:cacheprovider \
  tests/sentinel/test_native_read_upgrade.py \
  tests/sentinel/test_autonomy_runtime_upgrade.py \
  tests/sentinel/test_retained_source_compatibility.py \
  tests/sentinel/test_close_cycle_upgrade.py \
  tests/sentinel/test_open_time_upgrade.py \
  tests/sentinel/test_shadow_ui_upgrade.py \
  tests/sentinel/test_callback_liveness_upgrade.py \
  tests/sentinel/test_startup_contention_upgrade.py \
  tests/sentinel/test_unsent_recovery_upgrade.py \
  tests/sentinel/test_dashboard_monitor_upgrade.py \
  tests/sentinel/test_operational_liveness_upgrade.py \
  tests/sentinel/test_paper_composition_upgrade.py \
  tests/sentinel/test_retained_readiness_upgrade.py \
  tests/sentinel/test_dual_plan_renewal_upgrade.py \
  tests/scripts/test_test_responsibility.py
```

Source admission qualification includes the new profile's predecessor/deletion
falsifiers and the retained-book tests in the existing upgrade modules. The
future GET-only account diagnostic and its explicit inputs are documented in
[live trading readiness](live-trading-readiness.md#offline-and-deferred-account-checks).
An unfunded account can establish authentication and response shapes; funded
economic/recovery scenarios and separately reviewed live activation remain open.
