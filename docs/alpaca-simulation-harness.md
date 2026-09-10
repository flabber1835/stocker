# Alpaca simulation harness

Decision: 2026-09-10. Verified base: `96f705c3b699ec283dbac7e93b973dba9769f038`.

## Authority and scope

Alpaca supplies execution facts: account identity, cash, positions, orders and
fills. Wealth Core owns the immutable strategy book; Sentinel owns exposure
intent. A broker discrepancy must never rewrite either strategy state.

Add a test-only, deterministic Alpaca wire simulator under `tests/support/`.
Its independent Decimal ledger records actual cash, shares, orders and native
activities. The production `AlpacaExecutionBroker` consumes simulated HTTP
responses through its existing `http_provider` seam using `httpx.MockTransport`.
No listener, real credential, network fallback or brokerage connection exists.
The existing generic `SimulatedBroker` remains the broker-independent contract
oracle. This harness exercises Alpaca serialization, pagination, parsing and
reconciliation as an assembled path.

Two economic profiles are required: PAPER and LIVE_CASH. PAPER models omitted
dividends/fees, quote fills independent of displayed size, and account replacement.
LIVE_CASH adds limited fill liquidity, explicit fees/dividends, deposits,
withdrawals and settlement holds. These are deterministic stress assumptions,
not forecasts of exchange fills, broker fees or settlement policy. Cash movements
can also be injected adversarially into PAPER. Margin-capable and blocked account
payloads must be refused by the existing cash-only gate.

Both profiles feed the paper adapter through an in-memory transport. Actual live
URLs must continue to fail at construction. This does not certify or enable a
live adapter. Activity SSE remains a candidate parser: tests may call it directly
for wire acceptance; production capability flags and guarded refusal stay intact.

## Failure and recovery model

Fault scripts attach to a method/path/request occurrence, before or after the
broker effect. They may drop a request, accept then lose the response, return
HTTP failures or damaged JSON, replace/reorder/duplicate a response, return an
older view, or mutate the world between observation phases. Broker truth and
delivered evidence are separate. All scripts are bounded, reproducible and
inspectable. Restart recreates the adapter while retaining broker truth.

Required assertions include:

- exact client-key retries create at most one broker order;
- uncertain POSTs remain UNKNOWN until positive exact-key recovery;
- partial fills conserve cash/shares and preserve pending quantity;
- cancel acceptance is not cancellation; cancel/fill races reconcile;
- mismatched accounts/assets, malformed values, partial pagination, repeated
  identities and inconsistent reads cannot authorize increased exposure;
- late and duplicate cash events are booked once by native identity, with
  deposits/withdrawals/journals excluded from strategy P&L;
- corrections, busts and unsupported in-kind transfers retain explicit refusal;
- deposits/withdrawals during an immutable plan cause a cash mismatch; the
  current gateway requires resolution and a later decision-session plan;
- recovery across a fresh PostgreSQL connection reproduces the broker book and
  retains command economics/history; retry after convergence submits nothing;
- loss of cash ledger/cursor state and changed native activity economics refuse;
- safety gates remain closed for unapproved live and source capabilities.

Existing incident coverage to compose with this harness: #124 (asset identity),
#125 (omitted orders/stale restore), #127 (late terminal fills), #128 (account
bracketing), #129 (snapshot freshness), #131 (fill completeness), #183 (HTTP,
clock and activities), #209/#220/#222/#223 (cash/corporate-action/close authority).

The impossible case remains explicit: identical stale or fabricated responses
can pass structural consistency. Simulation cannot establish vendor honesty or
late-publication finality. Existing capability and restore fences remain the
authority boundary for those cases. A passing harness is software evidence,
not authenticated paper-account acceptance or live-money approval.

## Defects exercised by this harness

An exact client-order lookup may establish absence only through its explicit
404 result. Empty or non-object successful responses are corrupt evidence and
must preserve UNKNOWN. The harness reproduces an accepted order omitted from
the open view while the exact 200 response is `{}`.

Before cash-cursor reuse, including a same-time no-op, reconcile the persisted
account-specific ledger total and last native identity to that cursor. A missing
or mismatched ledger refuses before any new activity is inserted. This detects
nonzero loss and loss of the last activity; arbitrary offsetting historical
deletions still require independent backup/integrity evidence. A total alone is
not a complete event-set witness and earns no new source capability.

## Sources and execution

Vendor contract checked 2026-09-10:

- https://docs.alpaca.markets/us/docs/paper-trading
- https://docs.alpaca.markets/us/docs/account-activities
- https://docs.alpaca.markets/us/docs/working-with-orders

The default Sentinel safety suite discovers the new tests. A dedicated workflow
will run the harness and adjacent broker tests, retain JUnit results and fail on
missing PostgreSQL prerequisites. Fixed-seed sequences augment named scenarios;
the seed and operation trace identify failures. Mutation checks must demonstrate
that representative removed guards are detected. Exact commands and results are
recorded in the PR.
