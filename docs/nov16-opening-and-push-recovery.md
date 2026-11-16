# November 16 PAPER opening and notification recovery

## Production evidence

The 06:31 Pacific execution callback failed in 0.31 seconds with durable
classification `BackupProofBusy / COVERAGE_CHANGED`. The ongoing maintenance
pass began at 06:30:33. Its predecessor receipt covered WAL through `AC`; the
new receipt published at 06:31:13 covered `AD`. Renewal had combined admitting
the new segment and renewing every old segment under the same owner. An
ordinary concurrent reader correctly required the new exact frontier and could
not use the older receipt. The scheduler then sent a pre-transport refusal
through whole-cycle broker recovery and entered execution again at 06:32:55.
Placing the first order still involved a long cold execution callback. The
individual phases of that cold callback were not timed in production.

Alpaca filled MTD at 06:37:30. Sentinel recorded that fill at 06:39:12. The
required recovery before the next market increase completed at 06:40:00.
The original cutoff expired. CRL had no command, and the cycle closed
`SUPERSEDED / MAX_EXECUTION_LATENESS_EXCEEDED` with a complete clean
reconciliation, an owned fill, and the remaining actionable delta.

## Execution and durability decision

When proactive renewal is due and an authenticated unexpired receipt matches
the exact selected base and every previously proved archive object, first
prove any newly appended objects through the same two content passes, metadata
and alias rechecks, and selected-base fence. Publish that exact extended
receipt carrying its original full-scrub clock. Then carry out the ordinary
full scrub within the same exclusive owner. The in-progress scrub can coexist
with an ordinary concurrent reader only under its existing exact-coverage,
expiry, and atomic receipt revalidation checks. An expired receipt during the
incremental advance cannot authorize an operation. A failure of either proof
retains existing invalidation. A changed old object, missing evidence, new
incarnation, or different selection takes the existing strict path. Dashboard
publication still reports the completed full pass. Cap the extra append pass
at 64 MiB to keep rollover and backlog verification within the existing
renewal budget.

For unattended PAPER automation, explicitly classify owner contention from the
automated gateway's entry backup check or entry into its outer writer lock.
These exact call sites precede broker RPC and command creation. Allow the
current fenced cycle to take a bounded fresh-executor retry only for that
typed outcome, before the original cutoff and with no unresolved journal
commands for its account. All other execution exceptions and replacement
fences retain broker recovery. Every retry repeats the full gateway and safety
checks. Preserve the market BUY serialization and cash proof, the exchange
deadline, strategy and controller inputs, and the installed account/book.

## Web Push incident

The dispatcher recorded Apple HTTP 201 for the MTD fill at 06:39:15 and both
06:40 alerts to the same enrolled iPhone subscription. The operator saw none
of the three. Sentinel already distinguishes push-service acceptance from
handset display. Use a fresh enrollment test from the actual Home Screen app to
isolate client permission, subscription identity, and presentation. Avoid
replaying the historical trade alert or changing transport based on provider
acceptance alone.
