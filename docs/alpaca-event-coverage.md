# Alpaca event coverage for Sentinel

Sentinel must expect Alpaca data to arrive late, out of order, or in pieces.
The market-data API does not promise when complete corporate-action terms will
be available. Corporate-action terms, actual account postings, position
snapshots and spendable cash are separate observations. Acceptance of one
cannot establish facts that only the others carry.

## Cash posting reader

The Activity SSE examples encode settlement days as ISO calendar dates and
as UTC midnight timestamps. Accept both encodings of the same calendar day,
preserve the original payload, and reject times and offsets outside that
contract. Use the same parser during validation and posting. Late publication
is still discovered by the existing publication cursor; settlement day only
assigns the posting to its accounting date.

Include the legacy Trading API `CIL` and `DIVWH` cash posting codes as internal
account activity. Require an explicit amount even for a zero posting. A cash
payment for fractional entitlement is accounting evidence only for the actual
credit or debit. It does not establish a share conversion or authorize funding.

Separate share legs from actual cash postings. For stock mergers and stock or
cash reorganizations with a documented subtype, book only explicit cash
consideration that matches the broker's declared payout. A share leg with a
nonzero amount that cannot be classified as cash remains a refusal. A group
may post its cash before or after its securities; seeing the cash never marks
the group complete or reconciles the corresponding holdings.

## Qualified LIVE activity discovery

The current LIVE execution certificate may authorize `ACTIVITY_READ` alongside
`READ`. An issuer must grant the operation only when its accounting and
recovery receipts cover the exact account's Trading API Activity SSE origin,
account history and publication replay contract. Ordinary `READ` or a PAPER
qualification leaves the feature off. Recheck the permission immediately at
the activity HTTP boundary so replacement or revocation during an await cannot
silently preserve access. No permission is issued by the software or fixtures.

When scoped in this way, the existing LIVE writer reads and commits the account
activity cursor and any accepted amendments together, before ordinary holdings
reconciliation at preparation, recovery or execution. The journal stays
separate by broker namespace. This accounting source never supplies LIVE buy
funding, order permission or collateral. The signed funding policy still uses
its independent account evidence. Any missing/conflicting predecessor, identity
or broker order leaves the correction pending for the next bounded observation.

## Qualification boundary

Qualify supported software paths with production-shaped fixtures for both
environment namespaces. Exercise duplicate, late, revised, missing and
reordered events, restart and replay, and exact fractional quantities. Record
remaining restrictions explicitly. Account-specific settlement and publication
authority, and provider capabilities of the actual LIVE retail account, need
separate evidence under [LIVE funding admission](live-funding-admission.md).
Alpaca's partner Activity SSE documentation does not establish retail access.

| Event | Software acceptance boundary |
| --- | --- |
| Ordinary fills, partial fills, cancel and unknown transport outcome | Existing guarded order lifecycle and owned command reconciliation remain in force. |
| Revised fill or bust | Exact owned order and unambiguous active predecessor required. Reversal/replacement, cursor and command update are atomic. A prior action changing the security's share units can still require separate recovery. |
| Cash deposit/withdrawal, dividend, compensation, withholding, fee and interest | Named cash posting codes are attributed by their actual signed amount and native identity. General non-trade reversals and rebooking still need production handling. |
| Effective stock merger for a held, pending or reference security | Shared strategy recovers with complete source terms and exact entitlement. Corrections can replace an unconsumed publication. Missing cash-in-lieu terms and revisions after consumption remain unresolved. |
| Forward and reverse splits | Existing scalar share-unit reconciliation remains. Fractional remainders requiring a cash-in-lieu or whole-share settlement rule need exact evidence. |
| Stock dividend, spinoff, non-scalar reorganization, cash or mixed merger, rights and other distributions | Market announcements and actual cash legs are distinct. General matching of all delivered and surrendered shares to broker holdings still needs production integration. |
| In-kind transfer | A securities movement is distinct from cash. Production needs reliable asset identity, matching account postings and an accepted valuation policy for capital-flow attribution. |
| Newly introduced or contradictory event | Preserve uncertainty. Do not synthesize a fill, cash amount, position, entitlement or spending authority. |

Primary contracts are [corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1),
[Trading API account activities](https://docs.alpaca.markets/us/docs/account-activities),
and [Activity SSE](https://docs.alpaca.markets/us/docs/activity-sse).
