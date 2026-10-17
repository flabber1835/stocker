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
