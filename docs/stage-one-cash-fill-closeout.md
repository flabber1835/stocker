# Stage 1 L03: cash and native-fill consumers

Reviewed 2026-09-20. Initial base `daa43caf995779bfa7e67195785520744021cb45`;
updated base after owner merge of #419:
`eaae66f9e6626306f8b233fd723d25b278e13351`. The delivered commit and exact file
hashes are retained with [the acceptance evidence](../audit/economic_399/cash_zero_identity/README.md).
This is the L03 local review of C1/F6/F8/F19 in the finite checklist (#422).
Local L03 review is complete with the fix and acceptance below; integration
awaits the owner's PR merge and combined CI. It does not close provider acceptance, Stage 1 integration, NAS qualification,
or the deferred twenty-year replay.

## Finding resolved: L03-Z1, P2

The candidate SSE decoder discarded explicit zero cash amounts, and the durable
consumer independently returned before checking their native identities.
Consequently a retained $1,000 deposit replayed as $0 was silently ignored;
an initially discarded $0 replayed as $1,000 could be booked as a new deposit.
Either misattributes external capital and can corrupt reported strategy returns
if used as accepted cash evidence. This is a demonstrated local defect, not
evidence that deployed returns were affected. Production cash capability is
still false.

The decoder now forwards recognized explicit zero amounts. The consumer retains
their identities as `broker-cash-zero/v1` evidence in processed sessions, checks
both zero evidence and the nonzero ledger before accepting revisions, and refuses
changes to amount, settlement session or classification. Both stores and the
cursor share the caller's writer lock and transaction. The database constraint
against zero cash-flow rows remains intact. The design was documented in
execution-contract section 5.4 before implementation.

Acceptance uses the actual HTTP parser, real PostgreSQL and fresh connections.
Independent economic controls assert unchanged $100,000 NAV, no external capital,
zero P&L and no cash-flow rows for zero events. A later contradiction rolls back
both an earlier withdrawal insert and an earlier zero-evidence insert. Legacy
zero last-id replay still needs complete owned-history evidence and now retains
the native zero identity. No golden economics or capability bits changed.

## Production and acceptance crosswalk

| Claim | Production path reviewed | Evidence and limits |
| --- | --- | --- |
| C1/F6 accepted cash dependency and atomic evidence | `execution/guarded.py:377` → `paper/cash.py:188` → `execution/broker_cash.py:376`; preparation, recovery, execution and settled-account bracket all use this consumer | Capability false returns no authority; inconsistent typed cash becomes activation refusal, transport failure remains retryable. Simulation durability tests cover overlap, cursor/ledger loss, changed identity and fresh-connection replay. L03-Z1 adds zero evidence and transaction rollback. |
| C1/F6 plan and close authority | preparation stamps immutable baselines; `paper/cash.py` compares plan cash with signed fills and activity delta; `paper/finalization.py:170` independently checks the due historical plan before any successor | `test_paper_close_nav_gate.py` covers no accepted finality, wrong account/plan/session, missing baseline, changed identity with unchanged totals and delayed finalization. No acceptance inferred from an empty response or repeated snapshot. Numeric refinements in #421 belong to L02 and still require integrated CI. |
| F8 nested producer boundary | `execution/alpaca.py` configured recovery overlay checks accepted native-fill capability before candidate SSE; guarded cash entry checks its separate capability | `test_recovery_capability_boundary.py` exercises actual nested calls with reachable and forbidden fake endpoints. Native acceptance fixtures explicitly opt in to modeled fill history only; that is not production authority. |
| F19 parser, cumulative economics and durable ownership | native SSE parser → exact broker order lookup → `reconcile.py:595` response and durable-union validation → atomic observation/fill journal | `test_native_fill_acceptance.py` and `test_native_fill_progression.py` cover asset/side/type/time, duplicate/replacement identities, positive missing notional, overfill, native corrections/busts, incomplete history and restart. Independent expected total is ten shares/$1,000; six-then-four and differently priced partials converge without duplicate ownership. |
| F19 reporting and retained close evidence | fill rows joined to immutable commands → notification reconstruction and `paper_performance.py:116` entitlement scanner; finalization retains account-wide fill interval before verdict | Missing durable coverage defers the permanent entitlement marker; incomplete progression later succeeds. `test_trial_fill_interval_evidence.py` and `test_trial_fill_interval_proof.py` cover native identities, account/plan/bracket binding, foreign/off-plan activity, changed payload and omitted retained fills. No provider rounding tolerance was invented. Notification delivery/attempt fencing remains L07. |

The cash replay oracles do not compare only two outputs of the same function:
they check independent dollars, SQL rows, retained cursor equality, fresh-connection
database reads and the absence of broker writes. The new falsifiers separately
restore decoder dropping, consumer dropping, and bypass amount, session and
classification replay checks. Earlier retained fill evidence remains under
`audit/economic_399/partial_fill_notional`; its golden artifacts are preserved.

## Remaining gates

| Gate | Status and precise missing evidence |
| --- | --- |
| E1 / C1/F6, provider blocker | No accepted account-bound complete cash producer or immutable plan/session close-finality witness. A successful bounded Activity SSE response supplies published events, not proof that no late event can change the close. |
| E2 / F19, P2 provider/accounting blocker | Native correction/bust events refuse; reversal accounting and an accepted cumulative average-price precision rule are not implemented/accepted. The production native-fill capability stays false. |
| E3 / C3, provider recovery blocker | Complete predecessor-incarnation history is not established by local simulation. L04 separately validates local recovery behavior. |
| Retained historic zero identities, data dependent | Previously dropped events outside available complete replay cannot be reconstructed by this fix. Need a retained, account-bound exhaustive activity interval including the original identities; never fabricate missing events from a balance. |
| L01 integration / L06 restore / N1 NAS | Owner merges, exact integrated CI and the broader restore qualification remain required. The new zero evidence uses the existing backed-up processed-session table; this local change does not certify an actual NAS backup or its retention schedule. |

Authoritative references rechecked 2026-09-20:
[Activity SSE endpoint](https://docs.alpaca.markets/us/reference/subscribetoactivitiessse)
and [Activity SSE semantics](https://docs.alpaca.markets/us/docs/activity-sse).
They describe replay/event identity and correction fields. Our conclusion is
that these documents do not supply the accepted close-finality and predecessor
coverage guarantees required by Sentinel; this is not a claim that endpoint
availability itself is missing.

## NAS handoff for this item (not executed)

1. Require reviewed merged code plus green exact integrated CI, paper-only
   configuration, a retained full backup and approved provider evidence for any
   capability intended to be enabled. This change authorizes no flag override.
2. Before deployment, run the exact offline commands in the evidence README on
   the release checkout. Require all selected tests and every intended mutant
   detector to pass. Record commit, runtime digest and unedited logs.
3. In the isolated restore qualification database, compare the complete source
   and restored result of:

   ```sql
   SELECT cursor_name,session,state FROM sentinel_processed_sessions
   WHERE cursor_name LIKE 'broker-cash-zero:%' ORDER BY cursor_name;
   SELECT flow_id,session,amount,detail FROM sentinel_cash_flows ORDER BY flow_id;
   ```

   Retain source/restore row counts and content hashes, plus the activity cursor
   rows. Any missing/revised identity or unmatched cash/cursor set fails restore.
   A second offline replay must add no duplicate rows or P&L; a changed identity
   must refuse without advancing the cursor. Run the repository's existing
   restore-drill procedure under its documented operational prerequisites.
4. Keep economic certification pending if a due cycle lacks accepted provider
   finality, fill interval authority, or predecessor coverage. A green local
   simulation is not the missing deployed/provider evidence.
