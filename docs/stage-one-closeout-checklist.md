# Stage 1 finite local closeout checklist

This is the current remaining-work index, requested by the owner after the
chronological audit ledger could no longer support a reliable completion estimate.
It supersedes that ledger's vague references to "remaining local review", not
its retained evidence or unresolved certification gates. There are **10 fixed
closeout items below**, not ten known bugs or ten equally sized tasks.

Baseline checked on 2026-09-20: main
`daa43caf995779bfa7e67195785520744021cb45`; open PR #419 at
`53442c02fda54fec2be23cfdb0bfec133063fd52`; open PR #421 at
`8eb53b16da40149837ac2d5c37989399556c5127`. This is an inventory across those
reviewed changes, not a claim that their combined tree has passed validation.
The source scope is the economic production paths and their operational
dependencies listed below. It is not the entire repository.

## How an item closes

For each item, retain the reviewed commit, production caller and durable-state
references, acceptance evidence, independent oracle where economics are involved,
and relevant refusal/failure evidence. Reuse existing valid evidence; run only
missing cases or checks affected by integration. Changed guards require a detected
removed/broken-guard control. A module count, two identical executions of the
same algorithm, or a green test count alone cannot close an item.

Use `LOCAL PASS`, `OPEN CODE/TEST`, `BLOCKED INPUT`, or `INTEGRATION PENDING`.
Do not convert a blocked input into a pass. Provider and deployed qualification
remain separately tracked even when their local refusal boundary passes.
Discoveries belong under an existing ID with a named defect and disposition;
do not silently grow a new generic review backlog. If a genuinely new required
scope is discovered, explicitly record the new gate and its completion impact.

## The ten items

- [ ] **L01 — Integrate the reviewed fixes and pass required CI.**
  **Now:** INTEGRATION PENDING, #419, #421 and the L04 acceptance PR #423 are open.
  **Done when:** the reviewed changes are owner-merged through PRs, any overlap is resolved,
  and required CI passes on the resulting reviewed source. Validate affected
  integration seams, including the split test-image imports; do not count a
  passing older commit as evidence for the merged one. No agent self-merge.

- [ ] **L02 — Finish the numeric economics and identity cross-check.**
  **Now:** substantial local evidence; final integrated caller review pending.
  **Scope:** F2/F9/F10/F11/C2; canonical admission/opening quantity and stops,
  execution sizing, NAV serialization, terminal returns, plan/strategy identity,
  and #421's exact cash/P&L helper and consumers.
  **Done when:** each public caller uses the reviewed numeric policy through
  persistence and restart; affordability, inclusive stop, terminal proceeds,
  signed cash/P&L and identity boundaries have independent expected values.
  Reuse the retained sizing/terminal evidence and #421's 237-test/eight-mutant
  campaign where its source remains applicable. No new golden pins.

- [ ] **L03 — Close cash and native-fill consumer coverage.**
  **Now:** consumer fixes have local acceptance; final producer-to-consumer
  cross-check pending. Scope C1/F6/F8/F19 in `execution/alpaca.py`,
  `broker_cash.py`, `fill_integrity.py`, journal, paper cash and performance.
  **Done when:** account/native identity, timestamps, cumulative quantity/notional,
  duplicate/overlap replay, partial-to-complete progression, corrections/busts,
  cursor/ledger mismatch and empty responses have explicit safe outcomes through
  their actual callers. Valid supported history must progress after restart;
  missing or contradictory authority must not publish certified economics.
  Provider guarantees E1/E2 below remain open; no capability flags earn a pass.

- [x] **L04 — Close command identity and interrupted recovery.**
  **Now:** LOCAL PASS on main `daa43caf` plus tests/review in
  [#423](https://github.com/flabber1835/stocker/pull/423), head
  `1b49f3dcb47229f002cff043b9136947879c8d05`. The
  [caller/persistence map and bounded evidence](https://github.com/flabber1835/stocker/blob/1b49f3dcb47229f002cff043b9136947879c8d05/docs/stage-one-recovery-closeout.md)
  record 48 regression passes, three overlapping final controls and six detected
  mutants. Compound SIGKILL/absence/later-shadow coverage and a nonempty takeover
  control close two test gaps; no new production defect was demonstrated.
  Combined-tree revalidation and required CI remain L01; C3 completeness remains E3.
  Scope F5/F7/F17/F18/C3 and A8: executor, journal, recovery, reconciliation,
  paper recovery and `recovered_order_policy.py`.
  **Done when:** acceptance covers dispatch uncertainty, callback death and
  restart both before and after shadow advancement; the original command identity
  survives, replacement stays blocked until justified, and positive original-order
  evidence converges without a duplicate submission. Missing predecessor evidence
  retains the takeover fence. Provider completeness E3 is separate.

- [ ] **L05 — Close action, identifier and ownership economics.**
  **Now:** rename/rebase/entitlement fixes have retained evidence; final boundary
  cross-check pending. Scope F1/F3/F16 and A9/A10/A14/A15/A16: rolling continuity,
  dated references/action readers, target reprojection, returning identities,
  terminal handling and `paper_performance.scan_entitlements`.
  **Done when:** dated rename/rebase/split/terminal inputs preserve economic units;
  retained complete action coverage reaches each consumer; entitlement prices
  are required only for affected owners; absent ownership still refuses.
  Unsupported held spinoffs and entitlement assumptions need explicit reviewed
  support-or-refusal dispositions, never an invented continuation value.

- [ ] **L06 — Close rolling-state and restore integrity.**
  **Now:** logical and physical local restore evidence exists; final dependency
  closure against current source pending. Scope F14/F15 and the A21 restore
  extension: origin/daily checkpoints, authenticated observations,
  snapshot publication, retained references/actions and restore validation.
  **Done when:** every surviving economic state has its required origin,
  publication and retained-history evidence; missing/corrupt closure refuses;
  a supported restore can advance the next session with independently checked
  cash/holdings and unchanged prior intent. Map existing physical PostgreSQL
  evidence to the current paths; rerun only changed or unsupported claims.

- [ ] **L07 — Close notifications and process supervision.**
  **Now:** local fixes and takeover/crash tests exist; final cross-component
  ownership review pending. Scope F12/F13 and A1/alert-A4/A6/A17/A18/A19/A24/A25:
  outbox, Web Push, recipient rotation, incident recurrence, shadow/automation
  supervisors and deployment subprocess deadlines.
  **Done when:** late results cannot acknowledge a successor attempt or recipient;
  retryable obligations survive death/rotation; an expired callback is killed
  and reaped while required recovery remains visible. Distinguish HTTP acceptance
  from physical exactly-once delivery. Real devices and uninterruptible host I/O
  stay in deployed qualification, not local pass claims.

- [ ] **L08 — Close maintenance, retention and deployment sequencing.**
  **Now:** recurring maintenance is implemented and locally tested; it must not
  be relisted as missing code. Relevant F4 and A2/A3/A4/A5/backup-A6/A7/A11/A13/A20/A21/
  A22/A23/A26/A27 paths include dependency retry classification, backup maintenance,
  restore-gated retention, WAL/base selection and installer authority/fencing.
  **Done when:** existing acceptance establishes single ownership through worker
  death, verified successor before deletion, preservation of recovery-required
  inputs, and restart convergence after interrupted renewal/retention. Confirm
  migration/activation cannot precede required fencing and source identity checks.
  NAS scheduler and filesystem guarantees remain external evidence.

- [ ] **L09 — Qualify the locally available real-size workload.**
  **Now:** OPEN local/data-dependent resource work, A12 and remaining callback/
  status cost. #419 qualifies a 5,000-security synthetic scope; retained PIT
  inventory reaches 8,408 rows/day and 2,474,682 rows in a 300-session window.
  **Done when:** identify and admit a representative authoritative bounded window,
  including its required reference/action history; measure initialization,
  advancement, advanced status/full HTTP and restart at configured service caps.
  Retain wall time, peak/cgroup memory, OOM counters, source/image/input identities
  and economic invariants. No raised caps or omitted evidence to obtain a pass.
  Status/runtime latency needs an explicit accepted budget; absent that budget,
  report measurements and keep latency qualification open. Missing inputs get
  exact manifest/field/date and procedure entries. This is bounded resource
  qualification, **not** the deferred 20-year return backtest.

- [ ] **L10 — Publish the final finding-to-evidence reconciliation.**
  **Now:** all 22 economic finding IDs and all 27 autonomy labels (including
  three reused labels) have an explicit owner in the finding index. L04 has its
  final caller/evidence map; the other items' final reconciliation remains OPEN.
  **Done when:** every F1–F19/C1–C3 and relevant #400 finding has a disposition
  linked to L02–L09, current production caller, persistence/restart path and
  acceptance/falsifier or named external blocker. Reconcile duplicated A4/A5/A6
  labels and superseded historical "open implementation" rows. Inspect indirect
  callers and composed failures only within these named paths; log missing ones
  under the owning item. No unmapped required finding, unexplained numeric oracle,
  disconnected implementation, or generic "remaining local review" may remain.

## Separate gates — do not hide these in the local count

| ID | Gate | Required evidence / current limit |
| --- | --- | --- |
| E1 | C1/F6 cash provider authority | Accepted account-bound exhaustive history, correction/classification rules and fixed-close finality. Local arithmetic and repeated empty snapshots cannot establish it. |
| E2 | F19 native fill authority | Accepted cumulative-average precision, publication/completeness and correction/bust accounting contract. Unsupported lifecycles continue to refuse. |
| E3 | C3 predecessor recovery | Account/interval completeness plus durable command preimages and an accepted predecessor recovery protocol. Keep the takeover fence. |
| E4 | A14/A16 entitlement/action policy | Exact entitlement permission and authoritative action terms or a reviewed unsupported-event policy. Any required local implementation belongs in L05, not in a provider-only bucket. |
| N1 | NAS qualification | Exact authorized image/schema, scheduler/reboot, filesystem locking/rename/fsync, populated restore/WAL recovery, real-device notifications and target capacity/latency. No NAS access is authorized by this checklist. |
| B1 | Deferred Stage 2 | Authoritative 20-year day-by-day backtest, CAGR/multiple and independently explained historical economic deltas. Keep existing golden artifacts and provisional smoke limits. |

**Completion rule:** Stage 1 local code/review closure requires L01–L08 and L10
to be LOCAL PASS, and L09's locally feasible work completed with any external
input/budget blockage explicitly unresolved. An unresolved local implementation
or test cannot be relabeled as external. Full Stage 1 qualification/economic
certification must not be declared complete while any required resource,
provider/policy or deployed gate remains open. Local completion never means
that all possible bugs have been proven absent.

## Evidence index

- [Original finding/requirement ledger](economic-audit-399-remediation.md)
- [Requirement-to-caller and provider boundary review](economic-audit-399-pre-nas.md)
- [Finding ownership index, including reused #400 labels](stage-one-finding-index.md)
- [Chronological fixes, maintenance evidence and NAS handoff](economic-code-closure.md)
- [#419 resource/CI follow-ups](https://github.com/flabber1835/stocker/pull/419)
- [#421 cash precision fixes and retained evidence](https://github.com/flabber1835/stocker/pull/421)
- [#423 L04 compound recovery acceptance and review](https://github.com/flabber1835/stocker/pull/423)

2026-09-20 CI follow-up: #421's sole main-lane failure was the missing documented
cash precision delta in the package equivalence manifest (5,233 other tests
passed). Head `1864fab4e0528f5cfd55afdbf21beecb1dc9ac00` records that delta;
28 targeted architecture/cash cases passed. Its fresh CI remains required.
The original baseline heads above remain the inventory's initial snapshot.

Progress reports should name the IDs newly closed, IDs still open or blocked,
and newly discovered defects. Do not infer a percentage from test counts or
divide these unequal work packages into an effort estimate.
