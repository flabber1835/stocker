# Opening order dispatch

The account writer settles a whole group of fixed-dollar purchase reservations
against one clean account observation before any member may reach the broker.
Each reservation charges the exact original principal and fee allowance. Its
stable command key remains the recovery identity for the lifetime of the order.
Allocation follows the approved plan order. Fixed-share market buys continue
to use fresh individual funding evidence and quotes.

Alpaca's ordinary order list contains working orders. A reserved purchase
can fill before the prior worker records its broker acknowledgement. If a
previously sent member is absent from the working list, read its exact
client ID and match its native order terms, filled shares and cash. A pending
request in the active group may still be absent at the broker. Its full
allocation stays charged and its original command remains pending. A mismatch
between reads that straddle settlement earns one fresh account and book check.
An unexplained change still stops new submissions.

During one purchase callback the native cash reader can also provide its
bounded trade-publication interval. The reader takes the interval through the
current account-book observation and proves its account UUID and publication
cursor. A fully filled order may carry its verified debit into the next
contiguous interval if no trade event names that order. New executions must
match the native order, quantity and price. A cursor gap, correction, bust,
changed order or incomplete fill history requires a fresh full native fill
read or stops the purchase. The callback discards this evidence on exit.

For a group of named PAPER instruments or order keys, the guarded reader may
bracket a bounded batch of identical GET operations with a single current
authority check on each side. It verifies each result against its requested
identity and refuses a changed account. Each batch finishes before its result
is used. The financial writer serializes cash ingestion and journal changes.
Each purchase checks current open orders, positions, cash and buying power.
A reopened order or an unexplained change in the account withdraws the proof.
Independent instrument and exchange-clock reads can proceed while a sibling
is awaiting a network response. Each order still receives its own mutation
check and its original, single-use deadline check at the native request.

For two to four reserved PAPER dollar buys, the exact asset-ID adapter may
read one current exchange clock and the named instruments' trading rules as
a bounded batch. Only the named key and instrument can consume its result.
Stale evidence returns to the individual reader. Financial observations have
a shorter lifetime: after any sibling can reach the broker, cash alone cannot
prove that holdings, working orders and activity stayed unchanged. Each
purchase reads its own account snapshot followed by a complete orders and
positions observation under one signed read bracket. Both identities must
match the bound account before any financial information is used. The
existing writer still verifies cash activity, fills, open orders, holdings,
aggregate reservations and the individual order. If these endpoints straddle
a fill it makes the same bounded fresh retry. All observations used in the
retry are read again. A process restart discards every prefetched input.

The account display explains a cash hold at the time of its sample. During a
reserved PAPER opening basket, the native open-order list can contain one
purchase while earlier journal acknowledgments have already filled and other
members are still waiting to send. For fixed-dollar buys only, the collector
matches the complete native open list to that session's durable reservation
and accounts for the entire difference between cash and buying power. It
requires positive terminal broker records for acknowledged purchases missing
from the open list. Native account identity and balances bracket those reads.
The panel may show this dated evidence as purchases advance to confirmed fills
on the same plan. Foreign or uncertain commands, changed identity, amounts or
terms, unexplained cash, blocked accounts and expired samples still fail the
account check. This evidence cannot authorize orders or resolve a journal
command. Alpaca describes the hold in its [order buying-power documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca).

One writer prepares and checkpoints commands. Up to four independent requests
may await a broker response together. Each POST starts only after its own
committed SEND_PENDING checkpoint. A guarded native PAPER sale remains PLANNED
while queued and while checking its instrument. The writer obtains the final
mutation approval and commits its SEND_PENDING row just before POST. Each
worker owns its single-use pretransport proof,
final broker checks and exact client ID. The worker records the response before
finishing. The writer drains started requests before reconciliation or release
of ownership. On a definitive refusal or ambiguous response the writer stops
the entire group's unsent requests immediately, before waiting to persist
that response. Each worker checks the shared stop before its checkpoint and
before writing native request headers, including after slow TLS setup. A
worker that has already crossed its write boundary retains its real outcome.
Only an exact, single-use no-transport proof restores a pending sibling to
PLANNED. Rate-limit recovery cannot send a new order through a stopped group.
An interrupted request remains recoverable using its original key. Startup
reconciliation retains the existing UNKNOWN policy and same-security exclusion.

Each PAPER order checks its applicable exchange window at the native POST.
The HTTP transport checks it again after socket and TLS setup, before writing
the order request headers. A fractional order sent by native asset ID carries
its exact instrument's 30-second eligibility through to that write. A reserved
PAPER dollar purchase can fetch rules alongside another order's funding check.
If funding or mutation approval consumes the rules' lifetime, it may fetch
them once more and obtain fresh mutation approval before sending the original
order. If the same instrument's evidence expires again, only that proven
unsent purchase waits. A different asset, a backward clock, an unknown order
outcome or loss of account authority still stops the group's unsent orders.
The opening deadline applies to every attempt.
The native write check is qualified against the HTTPX and httpcore versions in
the release lock. Changing either version requires exercising the mock-socket
deadline test before selecting the new version for order submission.
LIVE dispatch retains its independent signed, request-bound mutation permit,
funding policy and capital limits. For LIVE protected buys each permit charges
the original maximum principal of every outstanding commitment. An exact native
receipt for an unfilled sibling in the same active dispatch can arrive before
its journal acknowledgement. A new fill still requires book reconciliation.
Sales remain bounded by unreserved holdings.
Independent sales can reach the broker before the first sale pays out.

In PAPER the sell-funded BIL purchase normally follows confirmed fills of the
required sales. In the last minute of the original opening purchase window,
one defensive BIL purchase may use confirmed spendable cash from a fully
submitted exit with identified, still-working sales. Its reservation is capped
by the remaining BIL allocation. A later sale fill contributes cash to a future
plan. Outstanding orders continue to reconcile past the new-buy cutoff.

For the PAPER dashboard, a complete, current observation of owned working sales
can explain a pending opening cycle until its next scheduled recovery. The sale
proof checks native order identity, direction, share quantity and cumulative
fill against the journal and the displayed plan. It never explains a cash
shortfall. A basket with a working BIL purchase also needs that precise order
in both books and the existing purchase and account checks. Uncertain orders,
unexplained holdings, account blocks and expired observations remain actionable.

LIVE protected buys require the originally authorized share quantity and price
limit, covered by verified settled cash. A partial sale receipt cannot resize a
LIVE BIL order. If the full purchase cannot qualify before the cutoff, later
proceeds stay in cash for the next plan.

## Measuring the opening window

The dispatch and restart test uses a prepared strategy and supplies purchase
admission. Its elapsed time measures that fixture. A full opening measurement
uses the exact candidate and its installed strategy files, the normal scheduler,
signed authority, backup checks, strategy verification, sizing and final order
checks. Run the clock at wall speed through the original cutoff. Match planned
orders and durable commands to an independent private venue ledger and its final
cash and holdings. Record separately how many orders reached the venue by the
cutoff, how many filled by then and when the scheduler confirmed the result.
Before accepting a deadline measurement, exercise concurrent wall-clock reads
on the actual worker threads throughout the run. Compare their elapsed time
with independent monotonic time and PostgreSQL's clock. A single clock sample
from each service cannot detect an intermittent jump to host time.
Show a worker loss separately when exercised and observe the actual dashboard
at those same times. All venue timings from these tests describe a simulator.

Set up the ordinary backup marker table before issuing financial evidence in
a fresh private database. The evidence binds the database schema. Creating
the table for the first time during a later restore drill changes that schema
and correctly stops a subsequent opening before it can submit an order. Keep
that refusal in the test record. A rehearsal may start again from a correctly
initialized private database.

Before activating a new cash-only PAPER rehearsal account, verify that its
broker-recovery record identifies the original PostgreSQL cluster, timeline
and account takeover epoch. Where the initial backup already exists and the
account has never traded, use the documented [initial PAPER
anchor procedure](sentinel-execution-contract.md#initial-paper-anchor-on-the-unchanged-appliance)
with the independently recorded private cluster identity and the private
venue. A missing record can allow the scheduler to prepare a plan and still
prevent every purchase at the open. Keep the original funded database on
its timeline for next-session exit and process-restart tests. A promoted
restore exercises the separate replacement-host procedure.
