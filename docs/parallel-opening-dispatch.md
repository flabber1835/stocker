# Opening order dispatch

The account writer settles a whole group of fixed-dollar purchase reservations
against one clean account observation before any member may reach the broker.
Each reservation charges the exact original principal and fee allowance. Its
stable command key remains the recovery identity for the lifetime of the order.
Allocation follows the approved plan order. Fixed-share market buys continue
to use fresh individual funding evidence and quotes.

One writer prepares and checkpoints commands. Up to four independent requests
may await a broker response together. Each starts only after its own committed
SEND_PENDING checkpoint. Its worker owns its single-use pretransport proof,
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
the order request headers. A fractional order sent by native asset ID uses one
current asset lookup to verify identity, tradability and denomination at submit.
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
