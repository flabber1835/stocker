# Audit 399 continuation: F19 native-fill coherence

Audited commit: `aff4461d9af6d4a7367018768fda18d948958b49`.
Audited tree: `56790bb69b1c65b981ffee94c2a58542916b3b52`.
Canonical finding: issue #399 comment **5724527221**. Dividend extension: **5724569984**.

## Findings and executed controls

**F19, P2 confirmed:** native fills can contradict their immutable order quantity or submission time, enter durable history, advance strict recovery and generate ordinary trade notifications while reconciliation reports RUNNING.

A ten-share order can retain a twenty-share native fill and a twenty-share trade notification. Two distinct six-share fills become twelve shares of history for the same ten-share order. A later same-native-ID correction raises `FillEconomicsChanged` and retains the original contradictory data.

The downstream actual rolling entitlement scan records **$40 or $24 for a correct $20 dividend entitlement**. A ten-share ex-date acquisition accompanied by a falsely preceding native timestamp records **$20 of false entitlement and a permanent performance quarantine**, while its correct entitlement is zero. Two independent database reconnections retain the marker. Current command-based positions remain ten shares. No synthetic cash, real account mutation, wrong new order, realized loss or historical CAGR change is demonstrated. Responses are intentionally conflicting local fixtures; real Alpaca incidence is unverified.

Valid controls establish ten-share native/order agreement, correct $20/$0 pre-ex-date/ex-date entitlement, and six-then-four partial-fill progression across reconnects with ten shares/$1,000 and exactly two native fill notifications.

## Test results

| Campaign | Completed result |
|---|---|
| `test_fill_order_coherence.py` | 5 passed, 6.31s |
| `test_fill_entitlement_coherence.py` | 5 passed, 11.38s |
| `test_fill_progression_controls.py` | 1 passed, 4.30s; the same case also passed before a module-description clarification |
| Nine-file existing regression selection, STRICT_V1 | 193 passed, 6 failed, 74.26s; zero errors/skips |
| Entire journal/reconciliation test file, default legacy test policy | 81 passed, 52.67s; zero failures/errors/skips |

There are **11 distinct new targeted cases**. Existing regressions and the repeated partial-fill control are re-execution, not unique lifetime coverage.

All six strict-mode regression failures occur in `test_journal_and_reconcile.py`: recovered submission-time aging, overlap economics, and four missing-journal adoption crash-boundary cases. They expect legacy adoption of broker orders whose durable ownership preimage is absent. `recovered_order_policy.py` correctly installs the refusal in STRICT_V1. The separate default-policy run passes the entire 81-case file. Production configuration was unchanged. The first broader test invocation was interrupted at a 45-second tool limit; its incomplete log is retained separately and is not a completed campaign or production finding.

## Runtime and integrity

Python **3.12.13**, psycopg **3.3.4**, PostgreSQL **17.11**, isolated recovered CI-image chroot. Source artifact **10514848122**, run **35261876890**. Runtime artifact **10515536149**, run **35262421704**. OCI manifest: `sha256:3fe1ac70fd7e2a51044757704b327c493b77d24f76c7f417cc85de40cd35bc78`.

Both local production source copies match all **1,164 selected Git blobs**, including all **903 Python files**. The tests use the repository's local HTTP/source fixtures, accepted test-producer shell, tiny-universe floor, isolated absent-backup-media policy and disposable PostgreSQL. Actual provider/broker transport, NAS supervision, physical restore and actual notification delivery remain external acceptance surfaces.

Place these three probe files together and run them against the pinned checkout in the pinned test runtime. Set `SENTINEL_RECOVERED_ORDER_AUTHORITY=STRICT_V1` before importing production code. Use the repository test receipt key and the isolated test fixtures imported by the files. The companion local evidence bundle includes the exact runner, full logs/JUnit, source integrity, hashes, machine-readable caller index and all incomplete attempts.

## Native-fill surface disposition

A scan of all **419 non-test Python files** found **19 direct helper call sites** and **9 literal references** to `sentinel_fills`; every indexed site has an explicit disposition in the companion matrix.

Active promotion is `reconcile:608 -> journal.record_observation:1028 -> _write_fills:774`. Standalone `record_fills:818` has no direct non-test caller in this index. Outbox reconstruction/claim calls at `outbox:413,433` propagate F19. PAPER preparation calls at `preparation:453,503,582` reach the affected entitlement consumer. Permanent marker reads/writes at `paper_performance:96,133,188`, `panel/sources:1860`, and `trial:1034,1855,2069,2073,2145` propagate authenticated negative authority.

The positive close-verification caller at `trial:1640` retains a separate account-wide native-fill interval and fixed-close cash-finality requirement. It corroborates retained native identities/economics and requires total native quantity to equal command filled quantity. The twelve interval-proof and ten interval-evidence regressions pass under STRICT_V1. The current production adapter lacks accepted complete interval capability; a broker-backed positive close proof is not claimed.

The nine literal references are the outbox reader, journal insert/replay read, entitlement reader, fresh-initialization existence gate, two schema declarations, close-cash corroboration reader, and the informational module docstring in `trial_fills.py`. Broader dynamic SQL, generic migration, restore and economic-mutation closure remain open.

## Remaining audit

Preserve F1–F19, C1/F6 counted once, C2/C3 and the #400 intersections. Continue the consolidated 592-candidate economic-mutation matrix, compound process-death/recovery/adoption/restore paths, publication/retirement/correction interleavings, cash and endpoint-finality capability acceptance, physical backup/restore, NAS resource/timing limits, prolonged outages and actual alert delivery.

Production source and real accounts remain unchanged. **Economic sign-off remains blocked.**

## Probe SHA-256

- `test_fill_order_coherence.py`: `e7772eb9d018e6e5861b3f1149c70943a8648500ae989722756ddfb5fab18dbe`
- `test_fill_entitlement_coherence.py`: `b69768a99955d3226ab3cb8dcfa9b289935dae845c90190098497505f5777b98`
- `test_fill_progression_controls.py`: `f3ed44d41ce6875f27750b64bdbb12b9ad532f5c425622dd912ebf7ab40e47cd`
