# Reconcile Alpaca's exact corporate share movements

Alpaca can remove an old position and allocate the successor in separate
account activities. Seeing the successor in the positions endpoint by itself
does not establish its ownership. A market-data announcement also does not
establish what the broker allocated to this particular account.

Use the qualified account Activity SSE consumer for this execution evidence.
Reuse its account verification, durable publication cursor, initial replay
and writer transaction. Retain merger, linked cash-in-lieu, and `DIV/SDIV`
rows with their original native
identity, publication ID, event bytes and exact account binding. This includes
zero-cash rows. The existing cash ledger records no cash for these legs.
Cross-check the raw activity inventory against its durable commitment before
using it after a restart or restore. A prefix ending before this feature was
introduced may bootstrap once from the same account replay. It cannot assume
older groups were absent.

The first production case recognizes a pure stock merger from two original,
executed USD activities in one complete native group. Require two distinct
activity and asset UUIDs, a common corporate-action ID and group ID, identical
native economics, old shares removed and exact new shares received, and no
cash, correction or additional leg. A successor allocation must equal the old
quantity times Alpaca's exact ratio. Stable asset IDs are mandatory. A symbol
or a quote cannot stand in for one. The positions read must be complete and
account bound and its quantities must reflect both legs. The old position must
come from Sentinel's own journal before the native position date. A known
overlapping share-unit event, incompatible fill history, or command in flight
leaves the ordinary reconciliation restriction or refusal in place.

The same restricted classification can establish a cash-only or mixed merger
when the complete original group includes its distinct posted cash leg. A
cash-only group removes the old shares and contains exactly one confirmed
positive cash payout. A mixed group additionally delivers shares of the
identified successor at the exact documented ratio. Every share leg must have
zero cash effect. The cash leg must have zero shares and an actual amount that
matches the declared payout in that group. Company terms or a price times
shares cannot substitute for a posted amount. Missing or revised legs remain
pending and cannot explain the position change.

A stock dividend uses one original executed USD `DIV/SDIV` row with exact
asset UUID and zero cash. Require the entitled share balance to equal the
date-bounded owned quantity, the posted share delta to equal `paid_qty`, and
the fresh position to equal `new_qty = entitled_qty + paid_qty`. Retain the
published rate as evidence. Its display precision does not change Alpaca's
exact posted quantity. The sole asset remains restricted.

A documented stock spinoff or rights distribution can explain a newly posted
child position with its own stable asset ID. Require the executed, zero-cash
receipt to specify the same exact quantity as the completely observed position,
with no existing command history for the child. Validate the stated distribution
rate and position date. This accounts only for custody of that received child.
The descriptive parent symbol supplies no parent identity, entitlement sizing,
exercise instructions or changes to its holdings. Other discrepancies stay
under the usual independent reconciliation checks.

When those proofs agree, classify just the proven old/new quantity differences
as explained and restrict both identities from submission. A recognized group
does not turn into a journaled trade, funding, a disposal decision, a position
target or strategy evidence. Unrelated reconciled reductions may proceed under
the existing execution rules. Other unexplained movements and unknown command
outcomes retain their existing handling. This limited implementation does not
adopt the successor for later trading. Exact positive account balances get no
authority beyond the restricted classification.

Incomplete or overlapping groups, missing IDs, lagging position reads,
cash in lieu, revised groups, and transfers require additional
evidence. No provider completion claim is inferred from a quiet stream. If a
revision to a recorded group is observed, its original proof cannot be used
to explain current positions until its native revision is resolved.

Verify both leg arrival orders, separate polls, duplicate replay, restart and
restore, partial or late broker position publication, fractional ratios at exact
precision, same-symbol identity replacement, and unrelated foreign movement.
Falsify the scope, dates, both asset IDs, exact quantity, cash, native group,
durable cursor and absence-of-in-flight requirements. Private fixtures exercise
the same route used by PAPER and LIVE. Actual LIVE qualification requires the
selected account's observed production payload and remains independent of this
code test.

References: [Trading Activity SSE](https://docs.alpaca.markets/us/reference/subscribetoactivitiessse),
[optional asset fields](https://docs.alpaca.markets/us/v1.1/changelog/2026-10-28-activity-asset-1d88bef),
and [activity types, ordering and posting delay](https://docs.alpaca.markets/us/docs/activity-sse).
