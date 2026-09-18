# Reconciliation following CHECKPOINT.md

The subsequent #399 comments were read before finalizing this continuation.

**5723541838:** the concurrent automation pass records 28 real SIGKILL cases across both sides of 14 control/lease/cycle SQL commits. This closes the exercised SQL state/event atomicity boundaries. F5/F7 orchestration and broker-finality exceptions remain active. Probe commit: `12feb946e30eafe488a0c392d312423d76d57812`.

**5723567109 — F15 (P2):** a missing historical `sentinel_action_coverage` row silently removes accepted split economics from the actual runtime action reader, even while the current publication/schema/receipt checks succeed. The independent 10 × 2 × 3 = 60-share history becomes an expected 30 or 20 shares. The actual reconciler flags the unchanged correct 60-share broker position as foreign activity. Normal SQL deletion remains protected by an immutable trigger; the executed trigger is isolated corrupt/incomplete stored evidence. No incorrect broker trade was demonstrated.

The concurrent five-case witness covers both missing historical rows and three controls. Its raw logs and probe are held by the originating continuation. Those executions are not included in this tranche's test counts or package.

F15 is an active exception to the retained-action evidence closure. The 24 normal retention passes remain valid in their stated scope. F14 remains separate: the semantic restore CLI omits rolling validation for damage that the direct rolling checks reject.

## Current inventory and evidence

Retain **F1–F15**, **C1/F6 counted once**, **C2**, **C3**, and #400 intersections. Source-review exhaustion and economic sign-off remain open.

This tranche's own completed evidence remains 310 existing-test passes in three clean runs (164 backup/config/schema, 24 retention, 122 ownership/admin), the strengthened two-case F14 reproduction, and two physical-base scope controls. Environment/lifecycle remains 111 passes plus five isolated `/dev/fd` failures, followed by 35 passes in the complete host shell, with 30 overlapping cases. Mixed runtime and original setup failures remain explicit in CHECKPOINT.md.

The original F14-era attachment is unchanged: `audit399_restore_retention_evidence.zip`, 160,249 bytes, SHA-256 `6a626b26c4cadcfa07f53cfea6acca856eb2a72e5b220ff4f8d616a775a49cbf`.

The final reconciled attachment is **`audit399_restore_retention_reconciled_F15.zip`**, **162,144 bytes**, SHA-256 **`fccf2baa1d29e41c06e11a48496b86e46811202b13fcbdc684857d2a93cc3839`**. Its 43 files include the original executed evidence, source/run integrity records, bounded disposition matrix and subsequent ledger reconciliation. ZIP integrity and every SHA256SUMS entry were checked.

Both committed probes exactly match the bytes executed locally: Git blobs `53007fea6cb7f3bb0fd12624e03f2cfe0efe080e` (F14) and `4ad315e9c19770c64c84775153b776ff717e3ab3` (physical-base scope). Both production source copies retain all 1,164 selected Git blobs unchanged. Audit-owned PostgreSQL processes were shut down after completion.

Continue broker retry/finality and cash continuity, callback-result authority, action-history integrity adjacency, and consolidated reader/writer/caller reconciliation. Actual NAS, provider, broker and production-sized compound-failure acceptance remains separate.
