# Cash distributions learned after the ex-date

Corporate-action knowledge is point in time. An ex-date describes entitlement;
the captured publication describes when this book learned the terms. Provider
processing and payment dates remain source evidence and must not replace either
date. A process-date API returning a previously absent dividend is ordinary new
information, not proof that an earlier decision was wrong.

Current-window continuation separates cash distributions from structural share
events. Split, merger, identity and other structural changes retain their exact
history guards. Cash changes produce a state-bound forward reconciliation input.
It includes native identities and processing/payment terms when available, the
prior and current snapshot commitments, and the ex-date aggregate for each
permanent security. The aggregate avoids double counting two native payments on
one ex-date. Source disappearance alone is not a cancellation: retain the last
observed obligation until a later explicit replacement supplies changed terms.
Captured native identities and aggregate knowledge remain in authenticated
session evidence across rolling-window expiry. A native identity that changes
its security or ex-date is pending; it cannot create a second entitlement under
the same identity. Price-window expiry cannot erase a pending cash correction.
Legacy aggregates without native component identities remain a conservative
floor if a later native query reports fewer components. That uncertainty is
pending evidence, never inferred permission to cancel the missing payment.
Malformed cash terms are pending cash evidence; they do not quarantine otherwise
valid raw price observations or claim that a dividend was paid.

Entitlement is the canonical shadow ledger's ownership immediately before the
ex-date session's fills, including that session's split/conversion receipts.
Neither current holdings, a controller reference basket, nor broker positions
can establish it. Former holdings remain eligible. The origin's complete formed
ledger establishes the available ownership interval; dates before that interval
have unknown entitlement and remain pending. Zero proven ownership records an
audit result without cash. A positive difference from already accrued amounts
creates a current-session receivable once; the canonical configured settlement
lag then settles it. This is modeled shadow cash, not a broker payout or an
assertion that a provider payable date has occurred. No old ledger, NAV, peak,
controller decision, or input is rewritten.
The existing receivable's `accrued_session` remains its ex-date entitlement key;
the appended accrual ledger event's session is the actual knowledge session.
Settlement ages from creation using `due_in`, never from that historical key.

Reduced explicit terms first cancel the still-unsettled portion of that exact
entitlement, then debit already settled cash only when the unlevered balance can
cover it. Both changes append current-session correction events. Otherwise the
whole correction remains pending, without a partial debit. Pending cash
evidence is audited and automatically reconsidered on subsequent publications;
it does not become a supervisor-wide permanent failure. Structural ambiguity,
invalid authenticated state and unexplained broker cash still refuse.

Reconciliation is deterministic and atomic with the next canonical session
checkpoint. Append-only ledger audit events bind the entitlement date, security,
observed target, amount already recognized and source commitment. The archived
input binds every observation to the predecessor state and held publication.
Retry, restart and lost acknowledgements reuse that checkpoint; they cannot
accrue twice. No broker data enters Wealth Core or the controller.

## Retained economic-policy upgrade

This forward-input policy changes economic source identity. It cannot use the
administrative compatibility mask. A reviewed, pinned migration profile lists
the exact original and replacement hashes of economic modules. The original
manifest must reproduce the authenticated origin; every changed economic byte
must match that profile, and all model/configuration/dependency/calendar guards
remain. Admission is fenced, backup protected, HMAC bound to the actual new
runtime and target strategy, and grants no paper authority.
The profile also pins the newly introduced cash module and migration verifier;
only the verifier's embedded profile digest is normalized to avoid a circular
hash. A later edit to these modules requires a newly reviewed profile.
The pure session kernel checks the embedded profile commitment and exact
predecessor/target input. Admission validates the profile and executable bytes;
the kernel itself performs no file or environment reads.

Historic genesis/specification and records retain their original identities.
The first forward transition archives a migration input binding the predecessor
hash, original strategy, target strategy and migration profile. Only the target
data-source semantics and this named policy may differ; holdings selection and
controller/configuration identities cannot change. Its new state records the
actual target economic identity. The authenticated checkpoint loader supports
that explicit transition and rejects arbitrary mixed-identity histories.
Historical parity uses the identity and input of the record being replayed.

## Broker cash after an immutable execution plan

A recognized native cash event is separate from modeled shadow entitlement.
First reconcile all outstanding commands and prove the fresh account cash from
the immutable plan baseline, durable fills and native activities. A changed
activity set supersedes the stale plan after clean reconciliation, including
offsetting events with zero net cash. Automation then waits for the next ordinary
decision; it does not repeatedly execute the same stale plan, resize its intents
or backfill a missing/legacy baseline. Unknown broker outcomes retain priority.

## Qualification

Cover current/former/zero ownership, ex-date buys and sells, splits, multiple
payments, duplicate observations, changed rates, disappearing rows, unknown
terms, pre-origin dates, restart and serialized replay. Falsify entitlement,
exactly-once, structural history and migration source/identity bindings. Exercise
real PostgreSQL checkpoint/restart/rollback and GET-only provider GO over the
retained formed book. Separately exercise post-plan native cash recovery,
including offsetting events, unresolved orders and missing/legacy provenance.
