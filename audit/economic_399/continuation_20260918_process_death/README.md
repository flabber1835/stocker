# Issue 399 — process-death persistence continuation

## Decision and identity

**Audit coverage remains incomplete. Economic and deployment sign-off remain blocked.**

F1–F19 and the existing C1/F6, C2 and C3 capability dispositions remain active. This continuation adds bounded clean commit-window dispositions and actual process-death evidence for existing #400 A4. No new finding identifier is assigned.

Production commit: `aff4461d9af6d4a7367018768fda18d948958b49`.
Production tree: `56790bb69b1c65b981ffee94c2a58542916b3b52`.
Probe retention commit: `789abb05fcc8128962ece260b503eb21b84c1aab`.
Evidence branch: `audit/economic-399-evidence`.

Canonical ledger: #399 comments 5724903307 and 5724951465. Operational cross-reference: #400 comment 5724960204, extending existing A4.

All 50 existing #399 comments through 5724704238 and all 30 #400 comments through 5724760843 were read before this continuation. Both acquired and executed source copies were checked against 1,164 selected Git blobs, including 903 Python files: zero mismatches. These are acquisition counts. Production files remain unchanged.

## Final completed checks

| Campaign | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| New rolling-runtime SIGKILL cases | 16 | 0 | 0 | 0 |
| New publication SIGKILL cases | 8 | 0 | 0 | 0 |
| New retention SIGKILL cases | 9 | 0 | 0 | 0 |
| Existing adjacent regressions | 184 | 0 | 0 | 0 |
| **Final selected checks** | **217** | **0** | **0** | **0** |

Pilot runs, superseded reruns and the separate environment smoke test are excluded. The 184 existing cases cover rolling runtime, daily advancement, initialization, operational snapshots, history retention, retention runtime, snapshot publication and snapshot jobs.

The three probe files in this directory match the executed local files byte for byte. The accompanying conversation evidence package contains raw logs, JUnit reports, per-case kill markers, source verification, file hashes, attempted-run dispositions and a 16-function selected-surface matrix. Full-function and global review closure remain open.

## Tested economic boundaries

### Rolling runtime — 16 cases

Cold initialization covers genesis, observation record, checkpoint, candidate commit before/after acknowledgement, authority insertion and authority commit before/after acknowledgement. Daily advancement covers the observation record, archived input, checkpoint and corresponding commits.

Each child uses an independent PostgreSQL connection. The parent receives an exact boundary marker, sends SIGKILL and confirms SIGKILL exit status. Recovery uses a fresh connection. Pre-commit deaths retain atomic absence. Committed candidates retain exact state, record, input and checkpoint hashes. Explicit guards reject economic replay and duplicate authority append. Advisory locks are reclaimable. The daily fixture has positions and invested cash; its recovered state equals the canonical production transition.

The daily oracle shares the production transition kernel. The result establishes restart equivalence for these fixtures and boundaries. Independent strategy arithmetic, open-window expiry and compound correction/restore remain separately scoped.

### Publication — 8 cases

The action-history insert, coverage manifest, publication row, validation receipt, operational binding, PUBLISHED job update and final commit before/after acknowledgement preserve joint visibility. Retry preserves one publication version, the same candidate and authenticated action hashes.

**Existing #400 A4 is reproduced.** Each pre-commit death leaves an active dead-worker lease. Immediate normal `operational_snapshot.prepare()` raises `JobRefused` with `owned, waiting, expired or terminal`. The probe explicitly advances the test lease expiry, after which normal fenced reclaim succeeds. Autonomous caller recovery remains blocked by A4. Post-commit retry directly reuses the publication.

### Retention — 9 cases

Actual retirement insertion, price-bar deletion, benchmark deletion, evidence release, retention commit, diagnostic write and separate diagnostic commit were tested. Mutation hooks require nonzero affected rows. Fresh connections distinguish rollback from committed retirement. Evidence payloads follow the same transaction boundary; diagnostics follow their separate commit.

Subsequent ordinary maintenance completes bounded cleanup and retains the current candidate. Exact action-history, coverage, publication, binding and job rows survive. Equity and BIL retain the historical `2 × 3 = 6` split factor. Automatic maintenance is explicitly deferred between three completed fixture publications to isolate the next invocation. This fixture checks publication/action closure; the rolling campaign checks behavioral checkpoint closure.

## Runtime and retained unsuccessful attempts

Python 3.12.13; psycopg 3.3.4; pandas 3.0.5; numpy 2.4.6; PostgreSQL 17.11. The retained image was unpacked and run through chroot with isolated synthetic source data, deterministic clock, reviewed test identity and disposable PostgreSQL databases. Recovered-order authority remained `STRICT_V1`. No broker/provider I/O occurred. Docker/NAS deployment, host failure and physical PITR acceptance were not exercised.

Earlier attempts remain preserved in the evidence package: one environment setup error from rootfs `/dev/null` permissions; a container-timeout-interrupted cold batch; one publication harness failure from a missing cursor `__iter__`; an adjacent-regression invocation with absent paths; and two retention harness failures caused by intercepting earlier writer-lock housekeeping commits. Corrections changed only the audit environment, invocation or probe code. The final selected campaigns report 217 passed, zero failures/errors/skips.

## Reproduction

Use the pinned production source and its test dependencies with Linux, Python 3.12.13 and disposable PostgreSQL 17.11. The probes explicitly import repository fixtures. The evidence package retains the exact environment wrapper and commands. Each probe was run separately with `python -m pytest -q <probe-path> -o junit_family=xunit1 --junitxml=<report-path>`.

Probe Git blobs:

- `test_rolling_commit_death.py`: `f7dfd06ce6cd529a3528c5544d6438907a1111c4`.
- `test_publication_commit_death.py`: `6c1ec2eaf82b7f74543f290fc6df81ba48fee7a9`.
- `test_retention_commit_death.py`: `b7d17e3cb7da034451873a6ef88352adde154f4c`.

## Remaining economic review inventory

1. Reconcile the existing per-function/AST mutation inventory, indirect effects, dynamic SQL, configuration and migration paths against explicit dispositions.
2. Complete compound broker acceptance/fill death, generation/lease changes, historical shadow advancement, action scaling and restore-grade recovery. F5/F7/F17/F18/F19 and C3 remain active.
3. Complete concurrent publication/correction/checkpoint authority/retention/restore interleavings, including expired-job and scratch cleanup. F1/F3/F4/F14/F15/F16 retain their established scopes.
4. Establish native cash/fill finality, corrections, fees, dividends, restrictions and account continuity. C1/F6 and F8 retain their capability boundaries.
5. Complete physical backup/PITR authority, long-outage/open-window recovery, resource-pressure, alert-delivery and NAS acceptance. Relevant #400 blockers remain active.
6. Consolidate final dispositions and establish historical economic impact separately. Sign-off requires explicit resolution or accepted scope limitations supported by executable evidence.
