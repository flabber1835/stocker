# Offline cash and securities accounting candidate

Decision: 2026-10-24, before implementation. Extend the isolated preparation in
`live-readiness-20261024.md`, not the running PAPER adapter or its positive-only
fill journal. This is an execution accounting candidate, never another strategy
book. Broker observations do not become Wealth Core or Sentinel inputs.

## Ownership and evidence

Use the existing gross-trade correction/bust replay for trade principal and
share deltas. Separately interpreted cash legs account for dividends, fees,
withholding, interest, deposits, withdrawals and corporate-action cash. Never
book a fill's gross principal a second time as a generic cash activity. A fee
linked to a trade has its own native activity identity; missing links refuse.
Ordinary cash legs must agree with the existing native normalizer on their
exact identity, amount and classification; preserving raw bytes while changing
an interpreted amount is a contradiction. Unknown security/action payloads
remain explicit unaccepted interpretations, rather than guessed native parsers.

Every entry binds the complete existing execution subject, a publication ULID,
stable entry identity and original canonical native evidence. Cash/security legs
also retain their exact native activity evidence. These are explicit local
interpretations; neither hashes nor generated fixtures authenticate an Alpaca
account, native parser contract, entitlement, interval completeness or finality.
The retail REST and partner SSE contracts must still be accepted independently.

An account projection starts from zero and explains only the supplied immutable
event history. An unexplained current broker balance is never inserted as an
opening adjustment. Negative explained inventory or cash refuses rather than
inventing stock, loans, cash or a compensating order. This restriction means an
incomplete historical prefix cannot masquerade as an account balance.

## Shares received through corporate actions

Support complete interpreted groups for stock dividends, scalar splits,
spinoffs, stock mergers, mixed stock/cash mergers and cash in lieu. The group
declares the exact expected native leg identities. All legs must be present,
unique, correctly scoped and shape-consistent before the complete transaction
is applied. Missing legs never publish a partly transformed account. A split
additionally binds its before/after quantity and exact net share delta. Mixed
mergers surrender the original security and receive the new shares and cash.

Accept exact fractional delivered quantities; do not round them to whole shares
or fabricate cash in lieu. Actual cash-in-lieu credits are separate evidenced
legs. Group corrections reverse the exact active predecessor and then apply its
replacement atomically; busts reverse only the predecessor. A fork, inactive or
missing predecessor, changed action/account/security identity, reused native
leg, changed bytes or regressed publication refuses.

A stable corporate-action identity owns exactly one entry chain. Another POST
under different entry/leg identities cannot credit the same action again;
corrections must identify that action's active predecessor, including when the
original chain was busted. A stock dividend may include actual cash in lieu in
the same complete group; arbitrary cash classifications remain disallowed.

Do not revise an earlier trade or security-distribution group across a later
corporate action which depends on an affected source/destination security.
Reversing an old fill after a split cannot merely subtract its pre-split
quantity from a post-split account. Complete authoritative dependency rebasing
is not implemented. Such histories refuse rather than recomputing invented
native action terms; unrelated security histories are unaffected.

Current ownership does not prove historical entitlement: a delayed distribution
may arrive after the parent was sold. Record the explicitly interpreted receipt
without demanding current parent shares. The candidate cannot authenticate the
record-date entitlement or provider-complete distribution; that status remains
explicitly unproven, independent of a complete supplied leg manifest.

Received securities retain their action origin and remain restricted pending an
explicitly reviewed disposition/target policy. This candidate never sells,
buys, values, assigns cost basis to, or admits them into the canonical twenty
slots. Broker-provided cost-basis/tax treatment remains retained raw evidence,
not an inference from a distribution ratio or a fabricated zero price.

## Financial boundaries and recovery

Use bounded Decimal inputs and exact Fraction accumulation, with the shared
exact Decimal renderer. Apply each correction/group atomically before checking
the nonnegative execution envelope. Same-identity byte-identical replay is
idempotent. Revalidate frozen model copies at every replay boundary. Immutable
sealed envelopes contain original interpreted entry bytes and digests, not
trusted derived balances; recovery recomputes the projection against the exact
subject and externally retained original hash.

The candidate can explain gross principal plus separate cash movements. It
cannot declare provider-complete net economics, settled funds, available cash,
native finality or live authority. Spendable cash remains exactly zero, order
authority NONE, and all native settlement/finality/live flags false. Do not
wire this module into cash reservations, production reconciliation, orders,
configuration, source identities or capability declarations in this phase.

## Qualification

Exercise trade corrections/busts with linked fees, dividends/withholding,
cash movements, fractional receipts, same/different-company stock payouts,
split/reverse-split quantities, complete mixed mergers, cash in lieu, action
corrections/busts, repeated/late delivery and seal/recovery. Falsify subject,
completeness, shape, identity, no-double-booking and nonnegative guards. Keep
native provider acceptance, settlement and live submission explicitly unproven.

No backups, archives, restore drills, protected backtest access, production
service changes, credentials, native broker access or automatic action disposal.

The bounded candidate reuses complete canonical gross-prefix replay as each
trade arrives. Its worst-case work is quadratic in the supplied trade count.
These correctness tests do not qualify operational-scale timing; benchmark and
design a reviewed incremental owner before runtime integration rather than
forking the canonical gross arithmetic to optimize this offline candidate.
