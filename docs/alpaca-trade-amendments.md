# Alpaca trade corrections and busts

Alpaca's [Activity SSE contract](https://docs.alpaca.markets/us/docs/activity-sse)
publishes a trade correction or bust as a `TRD` with a new `ref_id`, a
publication `event_id`, and a `previous_id` pointing to the execution it
replaces. The consumer must reverse that execution exactly once. A correction
also contributes the replacement execution. A bust contributes no replacement.
Publication time can be later than the order or plan that produced the fill.

Use the account-bound Activity SSE read for these operations. Exact order
identity, asset ID, side and client key bind the amendment to an owned command.
Reject missing predecessors, branches of one predecessor, changed event bytes,
cross-order or cross-account references, and corrections for which an exact
order read has not yet caught up. A never accepted fill cannot be subtracted
from an existing position based on an alleged negative activity. Ordinary
REST activity rows do not establish the Activity SSE predecessor relationship.
When a previously observed order has cumulative execution totals but lacks the
corresponding individual rows, use bounded and repeated Activity SSE evidence
for that order. Reconstruct the last accepted cumulative quantity and value
before admitting the amendment. This extra read occurs only on a correction
or bust and remains within the exact authenticated account.

A working order can publish ordinary fills and amendments in the same cursor
interval. Replay all new events for that owned order in publication order,
including ordinary fills before and after its first amendment. When the
durable fill cache is incomplete, corroborate its last accepted cumulative
quantity and price against a unique earlier publication state.
The first bounded activity read supplies the greatest accepted event ID and
the exact bytes for new effects. An additional history read can supply older
predecessors and must agree on the overlapping bytes. It cannot enlarge that
first boundary. A repeated ordinary fill must also agree with any retained
native cash posting. If the current exact order already reflects an execution that
the accepted prefix does not contain, keep the cursor pending until a fresh
complete read can explain it.

An ordinary fill can be older than the committed cash cursor and still
absent from the owned order journal. If a new amendment explicitly names
that fill, authenticated history may supply the earlier positive execution
at or before the prior cursor. Verify its native identity, order and cash
economics, and journal and consume it together with the amendment. Other
new ordinary effects still require the first bounded read.

The journal retains original fills and immutable amendment evidence. The active
execution projection excludes replaced fills and includes replacements so a
replay, a correction of a correction, and a restart use the same economics.
Change a command's execution totals only on agreement with a current exact
owned order read and the active executions. This is a special evidence path;
ordinary order observations retain monotonic fill requirements. Publish the
amendment, effective command economics, and activity cursor atomically. An
incomplete or mismatched read cannot advance the activity cursor. A previous
reconciliation must be refreshed after amendment before it can authorize an
order. Neither a reduction in a fill nor a bust proves a new order is due.

An amendment's gross principal derives from execution quantity and price.
Do not treat its raw `net_amount` as settled replacement cash without a
qualified native field contract. The existing cash and long-only gates still
require agreement with the current account. If late amended cash no longer
agrees with an existing frozen plan baseline, that baseline cannot support
additional exposure. A subsequent plan must start from the reconciled account.
The independent close interval, native settlement and restored-history
certification requirements still apply.

The streaming parser and journal mechanics can be qualified using local
recordings and private databases. Account entitlement to the feed, completeness,
true settlement and authorization to trade continue to be separate evidence
requirements. Installation and funded broker operations are out of scope.
