# Live trading preparation and acceptance

Owner decisions, 2026-10-16: Alpaca owns actual cash, positions, fills and
account activity; Wealth Core independently owns model holdings, and Sentinel
independently owns target exposure. Cash-only purchases wait for settled,
unreserved funds and may be deferred to the next eligible session. A later
session derives a fresh plan from current intent and actual broker state.

The exact trading origin selects the environment: `paper-api.alpaca.markets`
is PAPER and `api.alpaca.markets` is LIVE. One strict parser supplies that
classification and the source inventory endpoint. The same parser protects
the existing paper transport. Unknown origins, ports, URL suffixes and embedded
credentials refuse. The account/environment/endpoint/takeover subject is
distinct even if two environments return the same account identifier.

This change prepares shared execution behavior: authenticated current asset
continuity, conservative cash availability, rounded-average validation against
exact native fills, account-bound observation verification and recovery. It
does not enable live submission. The repository still requires a separately
reviewed live authority design and qualified native recovery before that gate
can change. No environment variable or endpoint edit grants authority.

Alpaca describes its trading accounts as margin accounts; a multiplier of one
can still permit reuse of unsettled proceeds. The paper purchase budget
`min(cash, buying_power)` is therefore not evidence of settled live cash. The
live adapter must obtain and qualify settlement and reservation evidence before
the settled-cash policy can authorize purchases. Neither a one-times multiplier
nor a field name supplies that proof. See Alpaca's [account
description](https://docs.alpaca.markets/us/docs/account-plans) and [limited-margin
explanation](https://alpaca.markets/support/alpaca-cash-accounts).

## Acceptance still required before live activation

| Boundary | Required evidence |
| --- | --- |
| Native account events | Supported retail Trading API history with stable event identity, pagination, tied timestamps, overlap, late arrivals, corrections/busts, dividends, fees, transfers and corporate actions. Broker API SSE must not be assumed available to a retail account. |
| Cash and settlement | Actual account constraints and reservation behavior; explain every cash change without synthesizing a balance. Paper omits live dividends and fees, so paper fixtures cannot prove live cash accounting. |
| Order and fill recovery | Complete native history, exact keys, lost responses, partial fills, cancellation races, process death and real restored-journal reconciliation. |
| Cash close finality | An explicit supported source and observation interval. The existing `PlanCashBaseline.close_cash_finality_authoritative` remains false. |
| Live authority | Signed environment, exact account, endpoint and takeover binding through every grant, plan, command and restore witness; paper authority must be unusable in live mode. |
| Operations | Real-provider acquisition, formed-book restart parity, verified backup/renewal, outage campaigns, durable independent backup media and deployment resource evidence. |
| Rollout | Separately authorized limited-capital activation through the single execution membrane, with fresh financial readiness and observed recovery. |

The production adapter's unqualified pagination, native activity, interval-fill,
account-freshness and restore-grade capabilities are not changed to true by
these tests. Its current declarations and every native acceptance limitation
remain visible. This document is a handoff contract for the separate live
review, not a live readiness certificate or order authorization.

## Implementation before native account qualification — 2026-10-17

The owner has authorized implementing and testing the integration before using
the unfunded live account. Account access, funding, deployment and live order
submission are deferred. This phase makes the following design choices.

1. Native reads use a separate, bounded, GET-only execution transport. Its
   versioned subject binds the exact trading origin, environment, deployment,
   account and takeover epoch. It verifies account identity before collection
   and again at the end. It cannot submit or cancel orders, adopt an account,
   create a plan, update a journal or issue execution authority. Existing paper
   grants, persisted identities and command keys retain their exact format.
2. Retail REST activities are traversed by native activity ID with bounded
   pages, bytes and elapsed time. Requested bounds refer to publication
   `created_at`, not economic or settlement date. Exhausting pagination proves
   only that traversal ended; it does not prove interval finality, absence of
   late publications, settlement or restore-grade completeness. Order lookup
   uses an exact native order ID; timestamp and order-ID cursors are never mixed.
3. A single typed normalizer produces native fills and classified broker cash
   events. Fills require exact native activity/order/asset identity, side,
   positive Decimal quantity and price. An exact order response may supply
   missing asset identity, but a symbol match cannot. Dividends, fees, interest,
   withholding and cash transfers remain actual execution economics and never
   become Wealth Core model inputs. Same-ID replay is idempotent; changed
   economics, correction/bust chains, securities transfers and unsupported
   corporate actions retain quarantine evidence and refuse financial projection.
   This phase does not silently invent reversal/rebooking or an adjusted book.
4. A separate settled-funds assessment describes the owner's live buy policy:
   settled cash less outstanding reservations, bounded by broker purchase
   constraints, with fresh account/subject evidence. An ordinary cash or buying
   power snapshot cannot supply a settlement proof. Unproven, stale or
   contradictory evidence produces a deferred buy, never a synthetic balance.
   Production settlement sources remain unaccepted until native qualification;
   synthetic evidence can exercise arithmetic but cannot authorize an order.
5. Offline acceptance replays the canonical reader and normalizer against a
   fixed scenario inventory. Receipts identify their sources and fixtures and
   distinguish simulation from recorded replay. Parser, isolation, replay and
   deferral checks may pass offline; native finality, settlement, restore-grade
   recovery and live authority remain NOT_PROVEN. The future account diagnostic
   uses explicit credentials and subject inputs without installed `.env`,
   database or Compose access. Its zero-balance result can establish reachability
   and response shape, not funded trading behavior.

The native read implementation and its tools are additive. They do not relax
`assert_paper_url`, production adapter capability declarations, paper
certification, close-cash finality or activation gates. Any source admission is
a separate exact, closed compatibility profile; historical profiles remain
immutable. A future live activation change must version durable execution
subjects through binding, planning, commands and restored-journal witnesses and
qualify the provider guarantees that are still absent here.

The REST contracts are the official [account activity reference](https://docs.alpaca.markets/us/reference/getaccountactivities-2)
and [order reference](https://docs.alpaca.markets/us/reference/getallorders-1).
The documented [activity SSE](https://docs.alpaca.markets/us/docs/activity-sse)
has a different event envelope and entitlement/retention boundary; it is not
silently substituted for a retail REST interval or inferred available from a
paper response.

The additive native-read source profile authenticates the exact current
`runtime_admission.py` and autonomy checker transition plus the named new
execution modules. It independently pins the unchanged historical autonomy
descriptor, its original checker identity and its original admission identity.
The historical checker accepts this one successor only after the successor
validator authenticates its normalized bytes and the current admission bytes.
The runtime admission matcher includes the successor's closed records and
addition set, including transitions of previously authenticated additions.
Unrelated source changes, unknown predecessor hashes and altered descriptors or
checkers still refuse. This is source compatibility only and carries no broker
or live authority.

Admission predecessors include the 15 exact `runtime_admission.py` versions
reachable in verified main `90a960547b58bb245c998ae3f70d0baed1fe95d0` history,
with their immutable commit witnesses in the successor descriptor. This
preserves the earlier retained-book upgrade path while replacing its former
wildcard administrative-source exception with a finite authenticated list.

## Offline and deferred account checks

[Offline qualification results](native-read-qualification-results.md) records
the tested implementation, exact scope and remaining native boundaries.

Run the fixed offline inventory from a Python 3.12 test environment with the
repository and `shared` on `PYTHONPATH`:

```sh
PYTHONPATH=.:shared python tools/sentinel_native_acceptance.py \
  --output /private/new-native-acceptance.json
```

The output path must be new. An optional private transcript requires both
`--recording` and its independently recorded `--recording-sha256`; replay cannot
establish that a capture came from Alpaca. The receipt retains source and fixture
identity, the exact required result inventory and explicit unproven native
guarantees. CI runs this inventory without broker credentials.

The immutable test lens keeps production imports in `/app` and test/tool files
in `/work`. The offline runner resolves the imported Sentinel package separately
when the tool root lacks a source package, hashes that actual runtime source,
and puts its parent on the isolated child's import path. It must not manufacture
a duplicate runtime under the test root. Repository runs retain their ordinary
single-root layout; synthetic layout tests exercise both arrangements.

After account checks are separately requested, the GET-only diagnostic can use
explicit environment-variable names for credentials. It never loads the installed
configuration. `--expected-account` is the native account UUID returned by Alpaca,
not its display account number. Example arguments, with placeholders:

```sh
PYTHONPATH=.:shared python tools/sentinel_live_diagnostics.py \
  --base-url https://api.alpaca.markets \
  --expected-account ACCOUNT_UUID --deployment-id DEPLOYMENT --takeover-epoch 1 \
  --api-key-env LIVE_DIAGNOSTIC_KEY --secret-key-env LIVE_DIAGNOSTIC_SECRET \
  --after 2026-10-16T00:00:00Z --through 2026-10-17T00:00:00Z \
  --output /private/new-live-diagnostic.json
```

An unfunded account can exercise authentication, exact account binding and empty
native response shapes. It cannot exercise funded settlement, real dividends,
regulatory fees, fills, corrections, liquidation or financial recovery. A
diagnostic PASS means only that the read-only collection completed; buys remain
deferred and native guarantees remain unproven. The implementation deliberately
quarantines ambiguous journals, funding memos, security transfers and unhandled
revision/corporate-action semantics. No diagnostic result enables live orders.
