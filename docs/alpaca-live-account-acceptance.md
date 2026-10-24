# Alpaca account acceptance still required for live trading

Checked against official public documentation on 2026-10-24. This is a contract
map and acceptance checklist, not evidence that a particular account can use a
feed. No account was contacted, credentials loaded, support message sent or live
permission changed. Existing GET-only diagnostics remain a separate explicitly
requested step. Offline candidate arithmetic cannot establish native finality.

## Retail REST and partner streams are distinct contracts

The [retail account-activity reference](https://docs.alpaca.markets/us/reference/getaccountactivities-2)
documents `/v2/account/activities`. Its cursor is the last activity ID, not an
order ID. Filters use creation time rather than settlement date; fee records may
be created after the trading day. Use bounded ascending traversal and retain
native IDs, exact response bytes, requested bounds and account identity. Exercise
overlapping pages, equal timestamps, late publications, duplicates, changed IDs
and exhausted/repeated cursors. A last page proves traversal ended, not that no
later correction or economic event can arrive.

The [account-activity guide](https://docs.alpaca.markets/us/docs/account-activities)
describes separate fill and non-trade records, including fees, cash dividends,
withholding, cash/security transfers, mergers, symbol changes, spinoffs and splits.
Do not convert every `qty` into a position delta: dividend quantities can describe
entitlement rather than delivered shares. Do not count a trade twice by applying
both its gross quantity/price cost and its cash amount as independent cash flows.
Actual account samples must establish precise signs, identities and event legs.

The [Activity SSE integration guide](https://docs.alpaca.markets/us/docs/activity-sse)
addresses partners and a different envelope. Its `event_id` publication cursor,
stable `ref_id` and `previous_id` correction chain do not redefine retail REST
IDs. Non-fill order lifecycle events require their own source. The guide's beta
path, replay retention and migrations require explicit contract/version tracking.
Retail account access, complete correction/bust delivery and retention cannot be
inferred from these partner examples or a successful PAPER response.

## Shares received in a corporate action

Alpaca's [mandatory-action guide](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions)
distinguishes stock dividends, forward/reverse splits, spinoffs and stock/cash
mergers. Its mixed-merger example has separate old-security removal, new-share
allocation and cash allocation. Native acceptance must demonstrate complete action
group identity, permanent asset lineage, exact delivered quantities, fractional
shares or cash-in-lieu, effective/settlement/publication clocks, delayed/revised
legs and broker cost-basis adjustments. Description text or an incomplete set of
legs cannot prove entitlement. A received security is recorded as delivered
property; a separate reviewed disposition policy decides whether/when to trade it.

## Funding and actual-account checks

The [account guide](https://docs.alpaca.markets/us/docs/account-plans) describes
margin accounts and account-block flags. The
[cash-account explanation](https://alpaca.markets/support/alpaca-cash-accounts)
must be checked against the particular account's actual configuration. A one-times
multiplier, reported cash or buying power alone does not prove settled,
unreserved funds under the owner's unlevered policy. Confirm the supported source
for settlement dates, open/uncertain-order reservations, fees and withdrawals;
capture actual before/after balances and independently explain every change.

The [PAPER specification](https://docs.alpaca.markets/us/docs/paper-trading)
excludes dividends and regulatory fees, along with several market execution
effects. PAPER fills and generated events therefore qualify software handling,
not funded settlement, actual actions or live liquidity.

Before any live activation, retain the exact native account/environment/origin
subject, tested API paths and entitlement, authentication observations, complete
activity/order captures and independent balance reconciliation. An unfunded
account can establish identity/reachability/response shape; it cannot prove
financial behavior absent from that account. Keep provider completeness,
settlement and live authority NOT_PROVEN until their separate evidence is
accepted. Backups and restores remain disabled; this checklist does not authorize
them or substitute fabricated recovery evidence.
