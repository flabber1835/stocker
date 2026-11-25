# BUY-only opening cutoff alert

The automation notifier reconstructs alerts from immutable cycle events. A
`SUPERSEDED` opening remains `CRITICAL` unless the terminal event itself contains
positive evidence that only unsent purchases were missed. A later dashboard
projection or a later broker read must not retroactively lower an earlier alert.

For `MAX_EXECUTION_LATENESS_EXCEEDED`, the terminal-cycle writer may append a
versioned `missed_window_buy_only` witness only when all of these facts agree in
the same database transaction:

* The cycle made an execution attempt, has the exact saved plan and matching
  PAPER account identity, and is ending after a clean `RUNNING`, `COMPLETE`
  broker observation. The reconciliation diagnostic names that observation,
  reports no unresolved, foreign, or restricted state, and its expected
  positions equal both observed positions and the verified broker payload.
* The original saved plan's sale legs have complete `FILLED` command quantities.
  No required sale remains, and each remaining actionable delta is a positive
  BUY from the exact saved intent. A BUY may have no command because the cutoff
  can occur before planning it; every existing `PLANNED` BUY must match its
  remaining delta exactly.
* Every such `PLANNED` BUY has zero fill, no native order ID, and a bounded,
  chronological journal chain from creation to `PLANNED` with only restored
  pretransport checkpoints. Neither the terminal reconciliation observation
  nor the latest complete broker observation contains its client key. Both
  observations reject unexplained native orders; a prior plan's known filled
  order may remain in broker history.
* All other current-plan commands and broker orders are terminal. The global
  active command set consists exactly of those proven unsent BUY keys. Thus an
  `UNKNOWN`, working or foreign order cannot qualify.

The writer treats a missing, malformed, contradictory, or unreadable fact as
absence of proof. Proof reads run in a savepoint so an optional alert
classification error cannot prevent the fenced terminal transition. They have
a 1.5-second transaction-local statement timeout (or the caller's shorter
timeout), plus a four-second deadline checked between proof reads after the
initial control read. A statement started just before that deadline may add up
to 1.5 seconds. The caller's timeout is
restored before a successful savepoint exits. A timeout keeps the alert
`CRITICAL`. The
notifier accepts the exact versioned event witness for `WARN`; older events and
every unproved cutoff remain `CRITICAL`. The witness changes notification
severity only. It grants no trading authority and does not mutate a broker,
plan, command, reconciliation, or existing alert.
