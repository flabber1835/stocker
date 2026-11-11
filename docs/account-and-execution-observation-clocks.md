# Distinct account and execution observation owners

Decision 2026-11-09, before the forward correction. The first close-root local
candidate reached APPLICATIONS_STARTED and correctly failed its readiness gate.
Its independent-account expiry correction had also been applied to the broker
execution row, although that row has a different producer. Keep that failed
receipt unfinished; it is evidence, not a successful activation.

The minute-by-minute execution collector records account snapshots only. It
does not observe positions/orders, reconcile, or write sentinel_observations.
Consequently a fresh account append cannot renew old completeness, order or
reconciliation evidence. The earlier combined account/observation test fixture
incorrectly modeled both producers as refreshing together.

Use a separate account clock helper: ten minutes from the original recorded
account observation, independent of trading retries and scheduled wakes.
Restore the existing execution-observation contract for the broker row: its
original timestamp and explicitly saved classification describe recorded
execution evidence until its owner's next required check. Active execution or
reconciliation retains the ten-minute bound. Outstanding working/in-flight or
uncertain commands also force that bound even if a cycle claims to be idle.
Missing/invalid owner evidence remains conservative. Existing raw negative and
unknown results retain precedence, and protected reservations keep tighter
expiry guards.

This restores the broker row's existing documented event-driven contract; it
does not introduce a claim of live positions or current order completeness.
Keep its saved-observation wording and original as_of. The independently fresh
account, authority, ownership and service rows retain their separate purposes.
No dashboard row grants execution authority: the execution membrane must still
obtain the guarded fresh broker observations required before trading.

Qualification must model the real producers independently: append only account
evidence while retaining an older full execution observation. Cover a settled
WAITING_OPEN cycle, original timestamps and scheduled obligation, account-only
refreshes, stopped account collection, active execution, journal hazards,
negative/incomplete broker snapshots and stricter reservation deadlines.

Use the existing supported allow-started-predecessor forward repair with a new
qualified source, image and operation. Preserve the first operation, its failure,
the original plan/filled sale, database and independent maintenance. Do not
freshen the broker observation merely to get the failed candidate past its gate.
