# Informational PAPER mirror for reviewed dual observation

**Decision:** reviewed `dual` mode may send the immutable certified close-unit
plan to Alpaca PAPER only as `INFORMATIONAL_PAPER_MIRROR`. It is not
`PAPER_EXECUTION_GO`, and Alpaca account P/L is never strategy-performance
authority.

## Why this mode exists

Sharadar publishes the effective-session split evidence after that session's
close. Alpaca's corporate-actions endpoint provides positive events but no
creation-time or complete negative-space guarantee. With only those two sources,
the system cannot truthfully attest before the open that every active security
has multiplier `1`. The strict pre-open authority contract therefore remains
mandatory for any future funded/live mode and keeps `PAPER_EXECUTION_GO` red.

The user still needs PAPER orders and positions visible in the external
Snowball iOS app connected to Alpaca while the independent broker-free shadow
ledger measures the strategy. Snowball displays only Alpaca's informational
PAPER trades, positions, and P/L; it is not Sentinel's status surface. Dual mode may do
that without relabeling missing evidence as authority:

1. The dual planner consumes the exact `VERIFIED` shadow `SessionState` and
   record as its one-way strategy-intent authority. It must not advance or
   consult a second PAPER catch-up strategy lineage. Dual preparation bypasses
   the legacy PAPER processed-session cursor and never synthesizes historical
   PAPER cycle obligations from it during an upgraded deployment.
2. The planner deterministically account-sizes that state with the canonical
   `build_execution_plan` adapter, using one bound, complete Alpaca account
   snapshot and observation plus the pinned Sharadar decision-close marks.
   The complete sizing-input commitment is stored with the plan. Every later
   reconciliation reloads those inputs and re-derives the exact target basket,
   plan fingerprint, shadow record, publication, and following XNYS session.
   Broker state can size transport but can never feed back into or rewrite the
   shadow ledger.
3. Before any PAPER mutation, the exact immutable plan is durably stamped
   `PREOPEN_UNPROVEN/PENDING`. The executor uses the plan's own close-unit basket;
   no locally fabricated multiplier or target basket may replace it.
4. Broker reconciliation, account ownership, cash/increase fences, foreign-
   position refusal, terminal/replaced-order refusal, and command idempotency
   remain unchanged. The mirror never auto-sells or auto-liquidates an unknown
   or mismatched book.
5. At the effective session's source-final post-close publication (not before
   23:45 New York), the next preparation reloads canonical Sharadar action
   evidence for every active plan/command identity. No material unit change
   advances the stamp to `POSTCLOSE_VERIFIED_NO_UNIT_CHANGE`. Any split/unit
   change advances it to `POSTCLOSE_MISMATCH`, latches PAPER automation
   `BLOCKED`, emits a critical alert, and prevents future broker mutations.
6. Post-close validation never rewrites the immutable plan, command quantities,
   broker book, or shadow ledger. It explains whether the PAPER transport was a
   faithful mirror; it does not retroactively make the pre-open evidence proven.

The enrolled PAPER account may start with any positive, empty, cash-only equity.
Its enrollment snapshot is bound once, and PAPER performance is shown only as a
normalized, non-authoritative return. It is neither required nor expected to
equal the shadow research capital: fills, slippage, and Alpaca's omitted
dividend simulation can make the two capital paths differ legitimately.

## Status semantics

| Surface | Clean mirror | PAPER mismatch |
|---|---|---|
| Certified shadow strategy return | `VERIFIED` | remains `VERIFIED` if its own data/lineage is valid |
| Alpaca/PAPER accounting | `NOT_VERIFIED` | `NOT_VERIFIED` |
| PAPER unit evidence | `PREOPEN_UNPROVEN/PENDING`, then post-close checked | `POSTCLOSE_MISMATCH` |
| Overall operational status | amber while pending, green only for shadow authority | red/blocked |
| Future PAPER mutations | allowed only inside the reviewed mirror lifecycle | refused until explicit review/reactivation |

Only a shadow data, revision, model, or lineage failure withdraws the certified
strategy verdict. A PAPER divergence makes the operational surface red without
contaminating or erasing an independently valid shadow return.

Sentinel's separate mobile web panel shows the certified shadow return, PAPER
reconciliation status, and the combined operational red/green status. Nothing
in this mode changes or controls Snowball's display.
