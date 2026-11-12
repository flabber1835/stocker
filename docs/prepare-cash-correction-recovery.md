# Recovery of a planless cash-correction preparation block

Decision date 2026-11-12. The Nov 12 decision reached `PREPARING` with the
published Nov 12 close, then terminally blocked on
`CASH_CORRECTION_ORIGINAL_LINK_CHANGED`. No plan or transport was created for
the Nov 13 opening. Correcting the retained evidence reader cannot retry a
terminal cycle. A replacement must carry new, explicit scheduling authority.

## Exact recovery category

Extend [the existing unsent recovery](unsent-cycle-recovery.md) with
`PREPARE_CASH_CORRECTION_ORIGINAL_LINK_MISCLASSIFIED`. Admit only an ordinary,
planless `BLOCKED` predecessor with the exact `SoftwareDefect` code, detail
`unreviewed callback exception builtins.ValueError: CASH_CORRECTION_ORIGINAL_LINK_CHANGED`,
`PREPARE` retry phase, `SOFTWARE_DEFECT` callback classification and terminal
reason, and the `sentinel.automation.model.SoftwareDefect` exception type.
Other cash errors and phases remain ineligible. This receipt category records
which historical exception the corrected reader can re-evaluate. It does not
classify cash evidence or forgive an unresolved origin-link discrepancy.

Use the existing canonical writer, account and takeover binding, current signed
authority, immutable predecessor fingerprint and no-plan-reuse checks. Require
no historical transport event, durable command for this opening, or unresolved
account command. Verify current latest closed decision and both host and
PostgreSQL clocks before the actual intended open. Keep the original cycle,
events and journal intact. The operator supplies the exact cycle and decision,
actor, reason and required confirmations while the old worker is fenced and
automation remains killed. The same authorization is idempotent behind that
fence. Only the immediately following exact-authority kill release admits a
new scheduling generation.

The replacement takes the ordinary fresh, account-bound preflight and current
authenticated publication path. It may reuse the currently published close
through its usual evidence verification. Reconciliation and preparation may
read the PAPER broker before the opening. Only the normal opening-window
execution grant can submit orders. A remaining evidence error still blocks
preparation. If the open has already passed, resume with a later closed
decision using ordinary operator reactivation.

## Backed local repair handoff

Admit the new exact category to `BLOCKED_UNSENT` alongside the existing
publication-advance category. Use the same exact signature in host SQL,
snapshot validation and the read-only canonical program. The canonical program
runs on both predecessor and successor images, so it must recognize the
retained diagnostic without requiring a new symbol in the predecessor. Preserve
the prior category's receipt format. Record the new category with the immutable
blocked proof, verify it against the preserved cycle on later reads, and bind
the subsequent authorization/release proof to that exact category.

The local installer continues to require its stopped writer, plain kill,
unchanged backup/WAL, native observation, journal and 15-minute pre-open
admission checks. Installation is software-only and preserves the kill fence.
The dashboard proof admits the exact retained PREPARE failure and a stale
complete, reconciled broker row only when it reports zero working, planned,
in-flight and uncertain orders and matches the fresh native position count
that the installer verified independently. It still requires a red fenced
dashboard and rejects unrelated red conditions.
Run the existing signed `authorize-unsent-paper-recovery` command against the
installed successor with the old leader stopped, then use the existing exact
kill release and ordinary scheduler. Confirm the replacement has reached
`WAITING_OPEN` with its fresh plan. The local installer records its completion
as fenced software delivery and grants no financial authority.

Qualify exact diagnostic matching, independent tamper/falsifier checks,
unchanged predecessor replay, rejection of a changed recovery kind, and the
real scheduler path to a fresh plan without transport. Historical receipts,
economic policy and opening deadlines retain their existing interpretation.
