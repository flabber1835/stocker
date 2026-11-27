# Alpaca in-kind transfers and journals

Executed Alpaca securities transfers (`ACATS`, `FOPT`, `JNLS`) explain
changes in account shares separately from trading. Consume these records only
from the authenticated, account-bracketed Activity SSE. Record the native
reference, publication cursor position, signed share quantity, settlement day,
permanent Alpaca asset UUID, and original response together with the replay
cursor. Detect conflicting reuse and a missing record during restore.

Start with USD postings with explicit zero cash effect and exact nonzero share
quantity. The event's stable native asset must link uniquely to the current
position or previous owned command, and the proven transfer movement must
explain the complete broker quantity exactly. An older or unresolved order,
dependent share action, identity collision, missing stable asset, or revision
keeps the unexplained discrepancy fenced. No adopted instrument may substitute
for a broker UUID. Affected assets remain restricted at execution until there
is independent disposition authority. Unaffected, reconciled reductions can
continue without creating a synthetic fill in the trading journal.

Capital contribution and withdrawal values remain separate from cash and share
reconciliation. A native transfer activity `price` describes an instrument
price, with no contract that it supplies the account's performance valuation.
An aggregate ACATS transfer value includes any cash transferred separately, and
tax basis can arrive after settlement. These are insufficient to assign a
performance value to a particular securities leg. A transfer leaves portfolio
performance attribution unverified until an independently supported mark is
available; it never creates settled cash, purchasing power, or strategy return.

Qualify inbound and outbound fractional quantities, reverse order delivery,
duplicate references, wrong-account credentials, missing/reused UUIDs, open or
subsequent owned orders, overlapping actions, and restart and restore. The
[Trading API reference](https://docs.alpaca.markets/us/reference/subscribetoactivitiessse)
documents that `asset` may be omitted. The separate
[ACATS reference](https://docs.alpaca.markets/us/reference/listacatstransfers)
describes aggregate transfer valuation.
