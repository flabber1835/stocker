# PAPER opening recovery on November 12

The captured cycle began at 06:31:00 Pacific. Alpaca reports receipt of the
single 16-share CDNA DAY limit order at 06:35:02 and a fill at 06:35:16.
Sentinel recorded the fill at 06:38:04. A clean reconciliation completed the
cycle at 06:38:56. The order's submission clock comes from Alpaca because the
journal's `updated_at` records the PostgreSQL transaction timestamp. The trace
captured three independent failures before completion.

## Keep ordinary execution evidence attached to its plan

At 06:31:08 the PAPER check completed with a pending mirror stamp and dropped
the bounded in-progress status. The dashboard classified the current PAPER,
broker, and workflow warnings as a new incident. During exact EXECUTING or
RECONCILING, use the existing current-plan transport proof when the current
stamp is pending or absent. Bind it to the same plan, publication, commands,
fenced callback and original deadline. Keep prior mirror mismatches visible
as history. Require the current transport integrity check when history exists.
Classify the resulting typed PAPER transport row and the matching execution
rows as ordinary bounded progress. A submitted order without a known outcome
keeps its existing journal state. Current negative evidence, invalid identity,
lost ownership and expired deadlines keep their refusal. An unstamped completed
cycle retains its failure.

The existing signed partial view may still show a finite opening refresh
until independently current evidence arrives. The dated plan and account
remain last known in that view. Stale broker evidence cannot establish green.
Two neutral samples at 06:35:06 and 06:35:08 were a PAPER-only evidence
refresh after transport. The last signed view had the submitted reconciliation
state and no active recovery callback proof. The next signed view included the
callback. Keep the neutral fallback in this gap.

## Leave time to renew the strategy proof

The 06:25:50 strategy proof expired at 06:35:50. The 30-second reservation
headroom and 15-second verifier poll admitted renewal at 06:35:34, leaving
about 16 seconds for an 85-second verification. Observed admission-to-verdict
durations over three openings reached 88 seconds. End optional opening or
closing deferral at least 150 seconds before the earlier of the original
receipt and row expiry. This leaves at least 135 seconds under ordinary
polling and retains the finite scan slot and full existing work deadline.
Actual delays can still exhaust the original proof lifetime.

During an active bounded same-subject renewal, publish CHECKING under the
current attempt's original admission and deadline. The old result's completion
clock continues to bound the old verdict. It cannot expire a new CHECKING
observation or turn it into current positive evidence. Failed, foreign,
malformed or expired attempts retain their existing refusal and history.

## Keep recovery writes out of the scan wait

The recovery callback ingested broker cash evidence and held the PAPER
revision row while waiting for the verifier's snapshot scan. Its own periodic
authority observer then waited on that row and hit an 11-second statement
timeout. Later account evidence writers also hit the PAPER row.

Load and authenticate the exact recoverable plan and its canonical SHADOW
intent before reading and ingesting native cash evidence. Keep the original
account writer, publication pin, pre-transport freshness and authority
checks. Preserve cash ingestion before mirror revalidation and reconciliation.
Use one stable successful control verdict detail for the same certificate
across complete control and cycle validations. Continue earning and persisting
the fenced verdict at the original interval. A repeated success updates its
proof clock without changing the PAPER revision through wording alone. A
real verdict or authority change still invalidates dependent views.

The retry producer marks an unattended transient RECOVER retry as automatic.
Interpret that persisted phase as recovery with its own validated retry facts.
The exact session's original close bounds the retry display. The pre-open
REFRESH/PREPARE proof remains scoped to data preparation. A valid recovery retry
never grants submission permission, declares an unresolved command safe or
overrides a current failure. Malformed retry evidence still requires attention.
Existing stored RECOVER records use the same interpretation. Interpret a
historical transport event with that event's original diagnostics, timestamps
and reconciliation identifier. A later RECOVER failure cannot rewrite an
earlier positively evidenced submission as an interrupted transport.

## Qualification

Reproduce the exact pending-to-checking opening handoff and prove the negative
cases still surface. Exercise same-subject renewal at original expiry and
repeated authority publication while another PostgreSQL session holds the
PAPER revision. Verify plan/SHADOW proof precedes recovery cash ingestion and
the original account, authority, deadline, command and fence guards still
apply. The canonical book, journal identity, long-only unlevered PAPER
authority, backups and the protected backtest retain their existing contracts.

The 06:28–06:55 trace retained 558 dashboard, 946 database and 155 workflow
samples. One maintenance-journal read timed out; the observer kept its old
cursor and captured 16 successful backup passes, with a 135.914-second minimum
renewal margin across 15 comparable pairs. The backup renewal lead remains
appropriate for the observed opening. The 72-second recovery scan wait is
distinct from the 11-second row-lock timeout. The trace also sampled a 12-second
execution scan wait behind the strategy worker and a 41-second strategy scan
wait behind the verifier after the cycle completed. The scan slot remains
exclusive. The next opening trace can measure the revised scheduling and
recovery transaction independently.

## Retained source

The installed source is `fad555c0ea0449a9225b01c8f6d96e22140b35b3`. Append its
independently archived full module inventory to the existing retained source
profile and preserve every expanded historical map. Seal the exact candidate
with the existing structural predecessor, base and authority-effect checks.
The installed 475-module closure is
`129def6620017e734a6733dd9cfc541f8fd9a12f52f8227c9f3737e444d5f1fe`.
The preceding 47 expanded records have canonical JSON SHA256
`7a33e9f3400eac8f49a6a131c7b42d8ab646dce9f759fa349105f364db7852cb`.
Retaining the prior source establishes compatibility evidence only.
