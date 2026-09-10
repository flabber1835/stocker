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
oracle. This harness exercises Alpaca serialization, pagination, parsing,
reconciliation and the public `execute_session` entry point as an assembled path.

Two economic profiles are required: PAPER and LIVE_CASH. PAPER models omitted
dividends/fees, quote fills independent of displayed size, and account replacement.
LIVE_CASH adds limited fill liquidity, explicit fees/dividends, deposits,
withdrawals and settlement holds. Pending buy orders reserve buying power in both
profiles. Unfilled DAY orders expire at the modeled market close. These are
deterministic stress assumptions, not forecasts of exchange fills, broker fees or
settlement policy. Cash movements can also be injected adversarially into PAPER.
Margin-capable and blocked account payloads must be refused by the existing
cash-only gate.

Both profiles feed the paper adapter through an in-memory transport. Actual live
URLs must continue to fail at construction. This does not certify or enable a
live adapter. Activity SSE remains a candidate parser: tests may call it directly
for wire acceptance; production capability flags and guarded refusal stay intact.

## Trading-session timing

Decision: 2026-09-10, PR #347 review 5162217860. Both simulator profiles use
the locked `exchange_calendars` XNYS schedule over an explicit 1997–2100
horizon. The simulator reads session data directly from that dependency. Its
order lifecycle remains independent of production execution and calendar guards.

One session lookup drives the market clock, queue release, DAY expiry, and
ordinary fill eligibility. A session is open from its opening timestamp
inclusive to its closing timestamp exclusive. Pre-open and after-close orders
queue for their first eligible session; weekends, holidays, winter UTC offsets,
and early closes follow that schedule. `next_open` and `next_close` always name
future schedule boundaries. Advancing across the close expires the remaining
DAY quantity, preserves cumulative fills, releases its buying-power reservation,
and timestamps expiry at that session's close.

Ordinary fills require an eligible open session. The existing explicit
`late=True` fault models delayed fill reports after expiry or cancellation.
Delivery faults and `clock_overrides` continue to inject contradictory evidence
independently of broker truth. Literal dated regression expectations and mutation
checks exercise these boundaries through the production adapter and broker guard.

## Failure and recovery model

Fault scripts attach to a method/path/request occurrence, before or after the
broker effect. They may drop a request, accept then lose the response, return
HTTP failures or damaged JSON, replace/reorder/duplicate a response, return an
older view, or mutate the world between observation phases. Broker truth and
delivered evidence are separate. All scripts are bounded, reproducible and
inspectable. Restart recreates the adapter while retaining broker truth.

Required assertions include:

- exact client-key retries create at most one broker order;
- uncertain POSTs recover from positive account-bound broker evidence;
- an exact-key 404 cannot cancel a live order present in a complete observation;
- UNKNOWN recovery adopts an observed pending cancellation and preserves both
  cancellation and fill outcomes, including after a contradictory exact-key 404;
- partial fills conserve cash/shares and preserve pending quantity;
- pending buys reduce reported buying power and DAY orders expire at close;
- cancel acceptance is not cancellation; cancel/fill races reconcile;
- mismatched accounts/assets, malformed values, partial pagination, repeated
  identities and inconsistent reads cannot authorize increased exposure;
- late and duplicate cash events are booked once by native identity, with
  deposits/withdrawals/journals excluded from strategy P&L;
- zero-value legacy activities may advance traversal state without requiring a
  nonexistent cash-ledger row;
- corrections, busts and unsupported in-kind transfers retain explicit refusal;
- deposits/withdrawals during an immutable plan cause a cash mismatch; the
  current gateway requires resolution and a later decision-session plan;
- recovery across a fresh PostgreSQL connection reproduces the broker book and
  retains command economics/history; retry after convergence submits nothing;
- public `execute_session` coverage proves reduction-before-increase ordering,
  overlap prevention after UNKNOWN recovery, and terminal convergence;
- loss of cash ledger/cursor state and changed native activity economics refuse;
- mutation certification requires an actual pytest assertion failure with zero
  pytest errors, so fixture/setup failures cannot kill a mutant;
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

An exact client-order lookup may establish negative-space absence only when an
explicit 404 agrees with a complete account-bound observation containing no such
client key. Positive order evidence always wins over a conflicting 404. Empty or
non-object successful exact responses are corrupt evidence and preserve UNKNOWN.

Before cash-cursor reuse, including a same-time no-op, reconcile the persisted
account-specific ledger total to the durable cursor. A missing durable last-id is
accepted only when a complete replay proves that identity is a zero-value event.
That compatibility replay starts at account binding and omits the SSE resume
cursor, so an old zero-value event remains discoverable after idle periods or
cursor advancement. Successful normalization restores ordinary incremental replay.
New cursor state retains a last activity id only for a materialized nonzero cash
row. Missing nonzero rows and total mismatches refuse recovery. Arbitrary offsetting
historical deletions still require independent backup/integrity evidence. A total
alone is not a complete event-set witness and earns no new source capability.

Mutation evidence is parsed from pytest JUnit output. A killed mutant requires a
pytest exit code for test failure, at least one `<failure>`, and zero `<error>`
records. PostgreSQL startup, fixture setup, collection and other harness errors are
therefore certification failures.

## Sources and execution

Vendor contract checked 2026-09-10:

- https://docs.alpaca.markets/us/docs/paper-trading
- https://docs.alpaca.markets/us/docs/account-activities
- https://docs.alpaca.markets/us/docs/working-with-orders
- https://docs.alpaca.markets/us/docs/orders-at-alpaca#time-in-force
- https://docs.alpaca.markets/us/reference/clock-1

The default Sentinel safety suite discovers the new tests. The dedicated workflow
runs the harness, independent command-state model, and adjacent broker tests on
both the PR head and synthetic merge, retains JUnit results and source hashes,
and requires at least 450 cases with zero
skips. PostgreSQL is mandatory for this gate. Install the locked Sentinel/test
dependencies and PostgreSQL, then run from a clean checkout:

```bash
python tools/alpaca_harness.py --output artifacts/alpaca
PYTHONPATH=shared ALPACA_HARNESS_REQUIRE_POSTGRES=1 python tools/alpaca_harness_mutations.py --include-postgres --output artifacts/alpaca/mutations.json
```

Use a fresh output directory for each gate run. Fixed-seed sequences augment named
scenarios; the seed and operation trace identify failures. Nine mutation checks
remove representative guards: exact-response validity, UUID routing, observation
consistency, external-capital classification, ledger/cursor consistency, and
UNKNOWN recovery of an observed pending cancellation. Session mutations restore
the fixed UTC expiry, force an always-open clock, and disable the fill-time guard. Each
must produce an actual assertion failure in an isolated source overlay with zero
pytest errors. The PR records the exact tested revision and results.
