# Economic audit #399 — restore, retention and operational boundaries

Production baseline: `aff4461d9af6d4a7367018768fda18d948958b49`.
Tree: `56790bb69b1c65b981ffee94c2a58542916b3b52`.

This continuation added **F14 (P2)**. Existing F1–F13, C1/F6 counted once, C2, C3 and intersecting #400 findings retain their dispositions. Economic sign-off remains blocked. Whole-audit source-review exhaustion remains open.

## Findings and evidence

**F14:** the real semantic restore CLI omits current rolling checkpoint/payload verification. Two negative PostgreSQL tests create a receipted rolling publication and canonical cold start, inject damage into the isolated checkpoint authentication or current sealed snapshot, confirm that the direct runtime validator refuses, and then observe the actual restore CLI returning exit 0 with `restored_database_semantics_ready:true`.

Issue comment **5723377633** contains the complete path, consequence and acceptance criteria. Checkpoint **5723465086** records the stronger CLI reproduction. The executable probe is `test_restore_rolling_gap.py`, committed at `4a586470d0f594bbf7a6f04de34a10d35021a9bf`. Passing these probes demonstrates the existing defect. It does not constitute a repair.

**Declared physical-base limit:** two further tests use real `pg_basebackup`, archived WAL, `pg_verifybackup` and the production writer lock. Controlled base-payload damage causes the physical verifier to fail while the metadata/WAL runtime gate still permits an audit-table commit. This matches the documented assurance boundary in `docs/backup-reliability-harness.md:113–173`. No new F-number was assigned. Comment **5723511755** records the disposition. Probe: `test_base_payload_gap.py`, commit `57e21607b8b8f0e8ca302b5a01621d6419d2386e`.

## Completed test runs

| Run | Result | Python | PostgreSQL when used |
| --- | --- | --- | --- |
| Backup/configuration/schema | 164 passed | 3.12.13 | 17.11 |
| Rolling retention | 24 passed | 3.12.13 | 17.11 |
| Ownership/administration | 122 passed | 3.12.13 | 17.11 |
| Strengthened F14 probes | 2 passed | 3.12.13 | 17.11 |
| Physical-base scope probes | 2 passed | 3.12.13 | 17.11 |
| Environment/lifecycle | 111 passed; 5 harness failures | 3.12.13 | — |
| Complete host-capability file | 35 passed | 3.13.5 | — |

The first three rows total **310 existing test passes**, with zero failures/errors/skips. The strengthened F14 pair repeats the original successful pair. The five environment failures came from the reconstructed chroot's missing `/dev/fd`; all five pass in the complete host-shell run. Thirty cases overlap across those two environment runs. Mixed runtimes remain explicit. The original two F14 fixture-setup errors at the image backup-policy boundary and the interrupted initial retention attempt remain in the evidence package and are excluded from completed-pass totals.

The prior 956-pass campaign was not rerun in this continuation. Production PostgreSQL is pinned to 16.14; the new local database tests used 17.11.

## Bounded source dispositions

- Retention: authenticated current-checkpoint pins, durable action/publication coverage, reader/job ownership, lock order and post-lock rechecks, immutable retirement, bounded deletion, scratch ownership, and logical restore following origin-payload retirement examined. Preserve F4 and the #400 deployed-idle-drain finding.
- Backup/restore: producer lock and owner contracts, atomic base promotion, marker/archive identity, WAL checksums, bounded runtime proof, restore CLI and physical verification boundary examined. Preserve F14, C3 and #400's missing automatic base-backup lifecycle.
- Ownership/administration: exact account and epoch gates, stable empty enrollment, certificate consumption and binding joint commit, restored adoption and retired CLI refusal examined. Preserve F7's administrative duplicate-liquidation extension and C3's restored recovery-completeness restriction.
- Configuration/migrations: explicit schema transitions and catalog fingerprints, runtime read-only catalog checks, default/backfill boundaries, managed environment locks/replacement/fsync, receipt-key ancestry and deployment re-exec examined.
- Retained previews return in-memory books; diagnostic readiness/quarantine persistence does not replace the reviewed live coherence checks. These routes do not establish rolling restart authority.
- The 100 export omissions have build/runtime caller dispositions: 96 historical/research/design inputs were excluded from the reviewed production data path; three packaged PWA icons and one historical reference diff match their recorded Git blobs. The raw content of the 96 excluded files was not re-audited.

All **1,164 selected Git blobs** match in both extracted and executed source copies after tests. Production source and actual broker/account state remained unchanged. The audit-only branch contains evidence additions.

## Evidence package

Conversation attachment: `audit399_restore_retention_evidence.zip`, **160,249 bytes**.
SHA-256: `6a626b26c4cadcfa07f53cfea6acca856eb2a72e5b220ff4f8d616a775a49cbf`.

The package contains both probes, logs and JUnit including setup/harness failures, selection lists, runtime identities, source integrity checks, SHA256SUMS, and bounded surface dispositions. It also contains the mechanical **592-call-site / 113-file** candidate inventory. That inventory requires individual reconciliation and is not a completed coverage claim.

Selected JUnit SHA-256:
- backup/configuration/schema: `08450c224cbae8eaa442fcc48f169af84fa97c2cd43eda5ee08bd9a67b832fdc`
- retention: `5074ed1f49fc4698551074c3036135d0680c9c67799a5a7bb3dfb2f76059400f`
- ownership/administration: `8675cf383f51f284bccd7bac123946d19cb9fb3ef8d4aadfed40c722916f7b9a`
- strengthened F14: `4b5dd6ad4e19575d41744ca1090ae4c6ef75dd22dee3672dfaa395ace2938ffa`
- physical-base probes: `2a403bdefd379a56515cba0aae156f7a594ee8f7acb417896e4b4f4d50e9c5e2`

## Remaining whole-audit frontier

Continue automation callback/commit and retry/generation/kill/lease/fence transitions; broker uncertain/contradictory and action-aged recovery; generic cash activity identity and plan-baseline transaction closure; and the final full reader/writer/caller matrix. Actual NAS storage/reboot behavior, independent media, provider contracts, broker recovery completeness, production-size timing and compound failure sequences retain external acceptance requirements.

Use isolated disposable test resources to rerun the probes. No NAS deployment, actual broker/vendor request, historical market replay, or restore of a production database was performed here.
