# Native read preparation qualification — 2026-10-17

This implements the offline preparation phase authorized by the owner, based on
verified main `90a960547b58bb245c998ae3f70d0baed1fe95d0`. The independent live
account checks are deferred. The offline checks used no broker credentials or
network access. No native account calls, funding, broker mutations, deployment
or activation were performed. The separate real-provider GO run reads market
data; it does not qualify native account behavior.

The implementation binds native reads to an exact account UUID, deployment,
environment, origin and takeover epoch. It traverses retail activities with
bounded resources, caches exact-order enrichment, preserves exact Decimal
evidence, detects contradictory replay and quarantines unsupported economics.
Partial or contradictory batches cannot expose a financial projection.
Native funding assessment always defers; simulation arithmetic has no spending
authority. Existing paper grants, command keys and production capability flags
were not changed.

## Exact immutable image evidence

The tested commit is `c71277c4b6d25972df24309ad687ef7cc18b346e`:

| Artifact | Immutable identity |
| --- | --- |
| Runtime image | `sha256:e95e7db8290aeffed907c1b0e74e60e19a9a7ae903d8aae4abee6614f0b9192a` |
| Test image | `sha256:7b8d1e4daf4f215154405d46ec8c63190168531b3a064fcdfc520bc5eb25f9df` |
| Exact-image qualification receipt | `native-exact-image-qualification-c71277c4.json` |

The test lens preserves the runtime layers and imports production Sentinel from
`/app/sentinel`; tests and tools are in `/work`. These runs used no source
overlay. Docker networking was disabled, the root filesystem was read-only,
temporary storage was a bounded tmpfs, and only the diagnostic evidence directory
was mounted writable. The native checks used injected mock transports.

The frozen source manifest contained 343 Sentinel Python files, with manifest
SHA256 `a5705a1b835be14a51688a097f341eb0591c99877bca5691c6bd33013392863f`.
Before/after source stability passed. The new closed source profile is
`200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b`.
The historical autonomy descriptor remains byte-identical. Fifteen exact
historical admission predecessors have immutable main-history witnesses;
unknown predecessors, altered neighbors and missing additions refuse.

| Check | Result |
| --- | --- |
| Native transport, normalization, history, funding, recording and tooling | 250 passed; `native-exact-integration.xml` |
| Source compatibility and responsibility checks | 340 passed, 20 formation/preservation cases deselected; `native-exact-source.xml` |
| Existing guarded execution, native fill, cash and recovery regressions | 225 passed; `native-exact-existing.xml` |
| Actual formed-book preservation through the retained upgrade path | 1 passed in 72.84s; `native-exact-retained.xml` |
| Fixed offline acceptance inventory | 23 passed; `native-exact-offline-acceptance-c71277c4.json` |
| Image-build checks | 46 passed; 1,581 passed with one warning; 79 passed |
| Tooling inventory, hash, credential, promotion and redaction falsifiers | Passed within the integration tests |
| AST syntax and Git whitespace checks | Passed |

All executed tests above had zero failures, errors and skips. The source group
explicitly deselected 20 expensive formation/preservation instances; it does not
claim that those instances ran. The separate retained result executes
`test_actual_formed_book_preserved[ready0-close_cycle_preceding]` against the same
exact image. That single case does not stand in for the other deselected cases.

The acceptance receipt says `PASS_OFFLINE_QUALIFICATION`, provenance
`SIMULATION_ONLY`. Native history completeness, late-publication finality,
settlement, close-cash finality, restore-grade recovery and live authority all
remain `NOT_PROVEN`. No capability was promoted. Earlier provider GO evidence
remains bound to its original source/image; it is not relabeled as evidence for
these native reads or for live operation.

Earlier guard-removal evidence used the existing dependency lens
`sha256:e36658fabc42d3e0d85ec1031910a16925b0e2a8594c1f4c80397e3ea0637c31`
with read-only current source or a byte-for-byte disposable source snapshot:
9/9 transport mutants and 14/14 normalization/history mutants were killed at
their intended assertions. Those are source-overlay falsifier results, not
mutant runs against the new immutable image. Their original attribution remains
unchanged.

## Required real-provider GO — passed

The fresh isolated campaign against the exact commit and runtime above passed.
Its sanitized report is `native-go-c71277c4-b-final.json`, 16,721 bytes, SHA256
`77a6b9f5ce6f5991f72507ad11d6492826ddff229cfb42812be89c96533aaa1b`.
The project was `sentinel-review-20261017t144054-c892d65cd1da`; the installed
stack was not changed. Final functional, financial and cleanup statuses are
all `PASS`.

| Operational check | Result |
| --- | --- |
| Real-provider preparation and atomic input publication | PASS |
| Canonical formation/full-forward replay and restart parity | PASS |
| Readiness and all 14 financial-health checks | PASS |
| Durable initialization and separate-process resume | PASS; all six compared session/hash fields matched |
| Retained canonical restart parity | PASS |
| Bootstrap and populated base backups, exact status and full semantic restores | PASS for both milestones |
| Private-project shutdown | PASS |

Actual inputs were `ALPACA_OPENFIGI`, source policy
`sentinel.alpaca-openfigi-operational-source/3`, normalization
`sentinel.alpaca-openfigi-dividend-current-window/3`: 426 sessions through
2026-10-16, 5,937 selected and 5,913 admitted candidates, 2,198,840 canonical
stock rows, and 159 committed components. Committed transport proofs account
for 528,148,880 response bytes; this count excludes unpersisted corroboration.
Measured preparation was 1,684,629 ms and full-forward decision replay was
865,066 ms, both within the existing financial-health thresholds.

The fresh-process restart preserved the session, record, state, ledger,
checkpoint and execution-journal identities. The populated restore contained
the attested saved rolling state for 2026-10-16, with no reconstruction. Restore
verification was read-only; the account remained unbound, command count was
zero and automation remained disabled. Broker mutation attempts were zero.
Automatic horizon-triggered renewal/resume was `NOT_EXERCISED` (zero calls);
the two actual backup/restore milestones do not claim that separate branch.

The first private attempt passed bootstrap backup/restore, then failed during
preparation with `psycopg.OperationalError`; cleanup passed. Its original report
is preserved separately as `native-go-c71277c4-a-failed.json`. The cause remains
unestablished because its raw failure output was not retained. The fresh
campaign retained bounded private command output and project worker/database
logs. Its observer started after bootstrap and excluded unlabeled restore
actors, so whole-run OOM absence and those actors' logs remain `NOT_PROVEN`.
No raw logs or credentials are included in the sanitized evidence archive.

This is local market-data, canonical-book and logical-recovery qualification.
The existing operator-attested local backup target was used; physical
independence and NAS qualification remain `NOT_PROVEN`. Protected software
certification and live activation remain `NOT_PROVEN`. The tested code remains
at `c71277c4b6d25972df24309ad687ef7cc18b346e`; the later handoff changes this
ledger only and does not relabel the tested image. Native account checks remain
`DEFERRED`; all six native guarantees listed above remain `NOT_PROVEN`.

## Reproduction

The canonical in-image commands below ran in the immutable test image listed
above, with `/work` as the tooling root and `/app` as the production import root.
Use network-none, read-only Docker execution, bounded `/tmp` storage and a private
writable evidence mount at `/evidence`.

```sh
python -m pytest -q -p no:cacheprovider \
  tests/sentinel/test_native_readonly.py \
  tests/sentinel/test_native_activity.py \
  tests/sentinel/test_alpaca_retail_history.py \
  tests/sentinel/test_live_funding.py \
  tests/sentinel/test_native_activity_recording.py \
  tests/sentinel/test_native_acceptance_tools.py \
  --junitxml=/evidence/native-exact-integration.xml

python -m pytest -q -p no:cacheprovider \
  tests/sentinel/test_guarded_execution_broker.py \
  tests/sentinel/test_native_fill_acceptance.py \
  tests/sentinel/test_autonomy_execution_remediation.py \
  tests/sentinel/test_alpaca_boundary_overlay.py \
  tests/sentinel/test_alpaca_simulation_cash.py \
  tests/sentinel/test_recovery_capability_boundary.py \
  --junitxml=/evidence/native-exact-existing.xml

python tools/sentinel_native_acceptance.py \
  --output /evidence/native-exact-offline-acceptance-c71277c4.json
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
  tests/scripts/test_test_responsibility.py \
  -k 'not formed and not preserved' \
  --junitxml=/evidence/native-exact-source.xml
```

The separate formed-book command was:

```sh
docker run --rm --name sentinel-native-c712-one-retained \
  --network none --read-only --tmpfs /tmp:rw,nosuid,size=2g \
  --mount type=bind,src=<private-evidence-directory>,dst=/evidence \
  --memory 4g --cpus 2 \
  sha256:7b8d1e4daf4f215154405d46ec8c63190168531b3a064fcdfc520bc5eb25f9df \
  -q -p no:cacheprovider \
  tests/sentinel/test_close_cycle_upgrade.py::test_actual_formed_book_preserved \
  --junitxml=/evidence/native-exact-retained.xml
```

The companion sanitized evidence archive includes the original isolated GO
harness and its private-output wrapper. The executed market-data origin was
the paper API; credentials were supplied only to preparation. With the same
clean Linux source checkout, immutable image, existing operator-attested backup
configuration and a fresh workspace, its command is:

```sh
python run_native_observed_go.py \
  --repo /path/to/clean-c71277c4-checkout \
  --runtime-image sha256:e95e7db8290aeffed907c1b0e74e60e19a9a7ae903d8aae4abee6614f0b9192a \
  --commit c71277c4b6d25972df24309ad687ef7cc18b346e \
  --operator-config /private/operator.env \
  --credentials-file /private/paper-market-data.env \
  --workspace /private/fresh-native-preflight \
  --budget-seconds 7200
```

Source admission qualification includes the new profile's predecessor/deletion
falsifiers. The future GET-only account diagnostic and its explicit inputs are
documented in
[live trading readiness](live-trading-readiness.md#offline-and-deferred-account-checks).
An unfunded account can establish authentication and response shapes; funded
economic/recovery scenarios and separately reviewed live activation remain open.
