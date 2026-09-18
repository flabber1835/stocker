# Issue 399 — testing-only economic certification continuation

**Verdict: BLOCKED. Full source-review exhaustion and economic certification have not been established.**

Production baseline: `aff4461d9af6d4a7367018768fda18d948958b49`.
Tree: `56790bb69b1c65b981ffee94c2a58542916b3b52`.
Repository: `flabber1835/stocker`. Canonical ledger: issue **399**.
Audit-only evidence branch: `audit/economic-399-evidence`.
New test source retained at commit: `502cb0b605aab93a42f5b7e9861c7ed52826f8a3`.
Execution date: September 18, 2026 UTC / September 17, 2026 Pacific.

## Completed testing

| Campaign | Passed | Failed | Expected failures | Scope |
|---|---:|---:|---:|---|
| Storage, retention, migration and restore regressions | 170 | 0 | 0 | Ten selected existing Sentinel test files |
| Shared strategy, V5, Wealth Core, Median-5 and champion regressions | 1,086 | 0 | 3 | Five existing test directories |
| New logical snapshot/retention/restore composition | 8 | 0 | 0 | Four capture phases × two cleanup batch sizes |
| New physical WAL-replay/retention composition | 2 | 0 | 0 | Named recovery points before and after cleanup |
| New positive economic acceptance criteria | 5 | 6 | 0 | Required outcomes for existing F2, F9 and F10 |

These primary campaigns contain **1,280 unique test nodes: 1,271 passed, six failed and three existing expected failures**. The 21 newly authored cases contain 15 passes and six failures.

The same three expected-failure nodes were subsequently rerun with pytest `--runxfail`: **all three failed as ordinary assertions**. Their rerun adds no unique nodes. The latest explicit per-node disposition is therefore **1,271 passes and nine failing acceptance/reference checks** across 1,280 unique nodes. No setup errors or unexpected skipped conditions occur in the completed primary campaigns.

Two logical pilot cases and one physical pilot case overlap the final matrices and are excluded. A coverage-instrumented strategy attempt was interrupted due to slow Python tracing; its partial progress is excluded. The completed standard strategy run supplies the regression result. No completed code-coverage percentage is claimed. The runtime smoke test and read-only golden diagnostic add no test cases.

## Failed economic acceptance criteria

### F2: exactly affordable whole-share sizing

Three required-outcome assertions fail: direct V5 sizing, canonical close-admission/pending-intent/next-open filling, and production plan/opening-price/target projection. Equity and cash are **51,641.59**, the admitted intended budget is **2,582.0795**, the price is **103.18**, and the model transaction cost is **10 basis points**. Independent Fraction arithmetic over decimal-spelled inputs admits **25 shares exactly**. Each production path selects **24 shares**. Immediately adjacent below/above budget controls pass. Canonical state is preserved during production projection.

### F9: rounded diagnostic NAV changes target weights

A real canonical two-session fixture holds 20 securities with ten shares each. Economic NAVs **20,000.001** and **19,999.999** both become diagnostic NAV **20,000.00**. Production target-weight construction consumes that rounded denominator. Both directions fail the independent full-precision weight oracle; the total-weight error is approximately **5 × 10^-8**. The explicit Decimal representation tolerance is **10^-25**. The exact-cent control passes.

### F10: inclusive trailing-stop boundary misses the exit

An owned **101.00** peak and **70.70** close meet the exact inclusive 30% stop condition. Serialized and reloaded canonical state then receives a **60.00** next-session open. Required economics for the ten-share position are **exit pending, zero retained shares, and 599.40 net cash**. Actual economics are **no exit, ten retained shares, and zero cash**. Adjacent closes **70.69** and **70.71** pass their respective exit/hold controls.

These are six ordinary failing correctness assertions. They are additional evidence for existing findings, not six newly numbered defects. The inputs are controlled fixtures. Actual provider incidence, live loss, and historical return impact are unmeasured.

## Existing golden-reference acceptance gap

The three baseline strict-xfail nodes concern the retained synthetic Wealth Core v1 fixture. Running their assertions with `--runxfail` produces the same actual result hash in the current and fresh interpreter:

- Expected result hash: `5c1af5731f79c7029d0c92b82275ef3b2b84d2a4fed0afbdc32688dfb6103a89`.
- Actual result hash: `11566dc3608fa06644d31aecb90f470ab3c2cec7075b9d32ab84e063a10ecaef`.

A read-only diagnostic evaluated fields beyond the first failing assertion:

| Field | Retained fixture | Actual execution |
|---|---:|---:|
| Final cash | 34,868.23 | 34,824.73 |
| Final state hash | `427baff03aa27870` | `11ee55f9687417d1` |
| Ledger hash | `0cf335b69e5a0279` | `1405d6573c67b811` |
| Final position count | 24 | 24 |
| Ledger event counts | Match | Match |
| Blocked session labels | Match | Match |

The **43.50 cash difference** requires economic-state/ledger reconciliation in the reference disposition. This test pass does not establish which reference semantics should be accepted or identify the causal change. Performance measurement preserves the actual result hash. The mismatch exists before measurement. The retained fixture and its xfail markers remain unchanged.

## Bounded recovery conditions established

### Logical PostgreSQL snapshots and restore: eight cases

Four snapshot points are exercised: before the next publication; after publication before the economic transition; after the economic candidate commit before authority append; and after authority append. Each point is crossed with cleanup batches of 5,000 and 50,000 rows.

Each case begins with the actual 25-security/300-session synthetic publication fixture and an invested canonical book. A separate REPEATABLE READ READ ONLY connection exports a PostgreSQL snapshot. The live connection advances publication/checkpoint/authority and actually retires **7,800 old price rows**, comprising 7,500 equity and 300 benchmark rows. The current candidate retains its 7,500 equity bars.

The exported snapshot preserves independent counts and sorted-row fingerprints for **all 81 production tables**. Actual `pg_dump --snapshot` runs after live cleanup. Actual `pg_restore` into a new database reproduces the complete table fingerprints after the exporter connection has closed. Restored structural authority and canonical state match the captured prefix. A committed trailing candidate is re-attested under explicit guards that fail on an attempted economic-transition replay. Pending transitions converge to the exact uninterrupted production result.

### Physical WAL replay: two cases

The repository PhysicalCluster harness supplies real PostgreSQL, the production WAL archive script, `pg_basebackup`, `pg_verifybackup`, archive namespaces and SHA sidecars, physical copying, WAL replay, promotion, and a fresh post-promotion base. The verified base predates the next publication/economic transition/checkpoint/authority and retirement.

Two explicit audit recovery targets select named WAL points immediately before or after retirement. After additional live cleanup and a later audit-control-row update, the primary is stopped and restored. Each target recovers the exact fingerprints of **81 production tables plus one audit-only control table, 82 total**. The later control update is absent, proving recovery stopped at the named target. The pre-cleanup target recovers all 7,500 old equity rows and no tombstone; the post-cleanup target recovers zero old equity rows and the tombstone. Both retain current prices and the exact attested canonical state, cash, holdings, ledger, and controller. Promotion succeeds and production backup-runtime authority accepts the new post-promotion proof.

These are bounded local database/physical recovery conditions. The economic equivalence oracle is the same uninterrupted production transition. Independent strategy arithmetic, complete deployed restore orchestration, real provider completeness, broker restore-grade authority, and NAS media/resource behavior retain separate gates.

## Remaining certification conditions

| Condition | Disposition |
|---|---|
| Exact selected production source and test-image provenance | Verified; zero mismatches |
| Newly tested logical and physical recovery schedules | Passed for the ten enumerated cases |
| F2/F9/F10 required economic outcomes | Failing: six assertions |
| Existing golden-reference compatibility | Unresolved: three direct assertion failures and economic-state/ledger drift |
| Other existing F1–F19 acceptance requirements | Retain their open ledger dispositions; this pass does not resolve them |
| Capability conditions C1/F6, C2 and C3 | Retain their existing scopes; C1/F6 counted once |
| Global function/mutation/configuration/migration inventory | Unexhausted; prior 592 mechanical candidates in 113 Sentinel files remain an open consolidated inventory |
| Remaining supervised broker/generation/lease/action/transport/restore compositions | Partially tested across prior work; whole-matrix closure unestablished |
| Accepted provider-native order/fill finality, cash and external-flow authority | Unestablished by these synthetic/local campaigns |
| Full deployment restore, long outage, NAS media/resources and actual alert delivery | Unestablished by these local campaigns |
| Historical-performance and economic-impact reconciliation | Unestablished; no historical return recalculation performed |

The detailed source/caller dispositions already recorded in #399 and relevant #400 comments remain authoritative. Acquisition, integrity and passed-case counts are not statements of exhaustive review coverage. **Full economic certification remains blocked.**

## Runtime and source integrity

Executed runtime: Python **3.12.13**, PostgreSQL **17.11**, psycopg **3.3.4**, pandas **3.0.5**, NumPy **2.4.6**, pytest **8.4.2**, exchange_calendars **4.13.2**. `SENTINEL_RECOVERED_ORDER_AUTHORITY=STRICT_V1` is set before imports. Production imports resolve to `/app/sentinel` and the installed `stock_strategy_shared` package.

The recovered image filesystem executes in a chroot. Test-only accommodations provide writable temporary paths and host-kernel entropy FIFOs. An isolated receipt-signing key is supplied. Existing synthetic source/attestation/time fixtures are explicit. Logical tests use absent-backup-media isolation; physical tests override it with REQUIRED_V1 and actual disposable base/WAL targets.

The final integrity pass verified **1,164 acquired source paths**, **1,164 runtime source-mirror paths**, and **921 mapped executed-source/test/tool/script paths**, for **3,249 checks with zero mismatches**. Forty recovered audit-evidence blobs match the evidence-branch tree. The source inventory contains 1,264 paths; 100 unselected archive/image/document paths remain explicit acquisition exclusions. The exact selected source was used to populate required test-image convenience paths. Existing production bytes were unchanged.

Input artifact provenance:

| GitHub artifact | Purpose | ZIP SHA-256 |
|---|---|---|
| 10514848122 | Selected pinned source | `bb5eea2f6f9675543452c501b6eb0de753fda05a3d54e4c719a0371701e676b4` |
| 10515536149 | Matching retained test image | `90f011c310aab5f128a832408ac531f4437e58d8889234b2a724398f635631ea` |
| 10532865017 | Continuation ledgers/evidence snapshot | `3e6e96bf36970e234290b7e6ae5e8fdb9b7ce74afee481689548359433345116` |

The inner source archive SHA-256 is `b21400523d501ade8dc7694174c485c9b3a6faf9035367660a7b6e4763385603`.

The three exact executed test files are retained in `tests/audit399_certification/` at evidence commit `502cb0b605aab93a42f5b7e9861c7ed52826f8a3`. The remote file blobs were read back and verified:

| Test | Git blob |
|---|---|
| `test_economic_acceptance.py` | `2ff0353d770c9cf5ed4b5c743c44d62e9bbd182b` |
| `test_physical_retention_replay.py` | `c8c1dcb3c0f1b5d7cc133d51a82a9540d9a0cf50` |
| `test_snapshot_retention_restore.py` | `ab6fff7bfd473ceb6b5e084cbfa8c622a74b1e9d` |

## Reproduction and retained evidence

Run against the pinned production checkout and matching test runtime. Overlay the three audit-only test files and the retained fixture `audit/economic_399/continuation_20260917/probes/test_rounded_nav.py`. The installed Sentinel/shared source must remain pinned. PostgreSQL server/client binaries, an isolated writable data directory, and the matching repository source paths are required by the existing harness.

The executed wrapper and complete argument/environment records are retained. It uses the local recovered image at `/mnt/data/audit399/rootfs`, `/work` as its working directory, and the source mirror `/work/repo`. Its paths describe this execution environment. Use the recorded commands and root layout for a like-for-like rerun. Final per-campaign commands appear in `campaign-summary.json` and `logs/*.execution.json`.

Core commands inside the prepared test runtime:

```sh
python -m pytest -q tests/audit399_certification/test_economic_acceptance.py
python -m pytest -q tests/audit399_certification/test_snapshot_retention_restore.py
python -m pytest -q tests/audit399_certification/test_physical_retention_replay.py
python -m pytest -q tests/shared tests/v5 tests/wealth_core tests/median5 tests/champion
```

The economic-acceptance command must currently fail its six assertions. Changing expected outcomes, fixture pins or product logic would change the certification question.

Bundle contents include exact new tests, reused fixture, complete final and pilot logs/JUnit, the excluded instrumentation record, runtime wrapper, read-only golden diagnostic/source, campaign/per-node JSON and CSV, source/artifact integrity, an explicit remaining-conditions table, and a SHA-256 file manifest. No production fix or real account action was performed.

Canonical ledger additions: `5725258987` (initial 170-test checkpoint), `5725359676` (six failed economic conditions), `5725376976` (ten bounded recovery conditions), and `5725430804` (strategy/reference-gap results and physical-table clarification).
