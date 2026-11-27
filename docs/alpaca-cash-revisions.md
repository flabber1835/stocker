# Alpaca cash activity revisions

Alpaca's [Activity SSE](https://docs.alpaca.markets/us/docs/activity-sse)
identifies a revision with a new publication ID and a new reference ID.
The prior reference names what must be reversed. Cash is a signed USD
contribution attributable to its settlement day. Publication order controls
consumption, including events published after that settlement day.

Start with cash deposits and withdrawals, cash transfers and journals, cash
dividends, fees and interest. Accept only a qualified replacement amount for
the same ordinary cash type, subtype, account, settlement day, and native
relationship fields. A zero replacement must be explicit. No change of
effective date, cash classification, source relationship or securities
ownership is inferred from a cash revision. For retail streams, the exact
account's native qualification must corroborate that the reported amount
replaces the predecessor's contribution. Partner examples alone do not
qualify those field semantics or endpoint access.
The selected financially qualified PAPER stream and the signed LIVE
`ACTIVITY_READ` accounting scope use this narrow contract. LIVE provenance and
entitlement for the actual account still need separate acceptance.

Prove the whole predecessor before applying the revision. On an existing
database, the ordinary cash ledger or its zero witness binds the original
amount and date. Replay the older raw event when necessary to corroborate
its account, subtype, and relationship fields. An already revised activity
must match its retained full replacement amount and raw identity. The cash
row for a revision holds only the difference, so it cannot supply the next
revision's predecessor amount by itself. An active predecessor may have one
successor. A changed replay, fork or missing predecessor keeps the account
activity batch unaccepted.

Append a separately classified cash difference and two durable references
to the same accepted revision, keyed by its new identity and by the consumed
predecessor. Retain the raw predecessor and replacement as evidence. A
zero difference still records a revision. The difference keeps the original
capital-flow classification and settlement day. A fee revision never
qualifies as an ordinary newly posted debit fee or cash funding receipt.
The existing writer binds the evidence, cash membership, and publication
cursor in one transaction. Previous cash rows, plan baselines, and
published performance snapshots remain immutable. A correction can change
newly computed reporting for the affected interval, which should be marked
as a revision, and invalidates a plan when the existing cash checks require
that outcome.

Restart verification recomputes the receipt commitment and cash differences
from original and replacement contributions. It checks both immutable
references against the cash membership, and refuses a missing original,
effect, predecessor, or cursor commitment. Exercise a late event, a chain
with a zero intermediate amount, duplicate and changed replay, old account
binding, reordered events, a crash before publishing the cursor, and a
restore missing either row. Exercise both PAPER and LIVE namespaces with
isolated inputs.

Securities transfers require another contract. `ACATS`, `FOPT` and `JNLS`
can deliver or remove shares with zero cash. Identify the exact owned
account, direction, stable asset identity, and quantity from qualified
provider evidence and confirm those holdings. The current Trading API
documentation and partner examples do not establish these facts for every
retail account or the appropriate value of the cash-neutral transfer. Use
an approved, attributable market mark at the chosen transfer boundary for
external-capital reporting, separate from cash and tax cost basis. Additional
transferred holdings need explicit disposition and order restrictions until
they can enter a subsequent plan. Do not use a request ID to deduplicate
separate transfer legs or residual deliveries.
