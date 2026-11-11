# Dashboard dependency ownership and coherent handoff

Decision 2026-11-09, recorded before implementation. The owner authorized a
local PAPER patch and a second architectural review. Preserve strict financial
subjects, canonical economics, command identity, UNKNOWN outcomes, original
proof deadlines, the existing database and independent maintenance policy.
No financial trigger, market data, trading algorithm, or broker access changes.

## Demonstrated defect

Normal sixty-second account refreshes change equity without changing account
flags, cash, orders, completed trading state or worker ownership. The strict
PAPER revision correctly changes, but its use as a universal display dependency
withdraws every PAPER-associated card. Financial receipt replacement independently
has the same overbroad effect. The global partial marker also makes the image
grey and strips completed-run payloads, yielding a misleading next-plan placeholder.
The earlier expiry-only patch deliberately left this second path unchanged.

Keep the native SHADOW/PAPER financial subject and exact receipt identity. Separate
their display use through signed producer metadata. Receipt-only changes refresh
the financial rows, without invalidating unrelated native facts. Preserve the
existing conservative partial path for unproved changes and unknown row families.

## Bounded proof of the normal account update

Do not infer an account-only update from a transaction ID alone, skip equity in
financial invalidation, scan complete command/event histories, or add a second
revision registry and migration. Use the existing guarded counter and indexed
account append history as an explicitly bounded cause witness:

- Capture native subjects, the PAPER revision/incarnation/transaction version,
  and an account anchor that is both latest by observation and maximum sequence.
  Bind its sequence, row version, physical table identity and immutable scope in
  signed producer metadata captured with the composition's original inputs.
- At reuse, the same current physical/configuration/installation/DDL basis must
  recompute the original native subject using the original revision tuple.
- Require a revision advance of exactly one, an unchanged anchor, exactly one
  new account row (inspect at most two), that row now latest, and the same
  transaction identity for that row and the current guarded revision.
- Evaluate the actual account trigger's equality/time/date predicate. The new
  row must necessarily account for its own revision increment. An identical
  account append plus an unrelated update cannot satisfy the proof. Any additional
  dependency mutation necessarily makes the counter proof fail.
- Reuse the ordinary account validation and original deadlines. Routine
  valuation changes may preserve independently unchanged display facts; new
  account blocking, identity, missing/invalid economics or margin negatives must
  surface immediately. Reservation-dependent evidence needs its exact original
  guard; a witness does not grant a new cash reservation or financial authority.

Failure, missing metadata, multiple appends, an altered/deleted anchor, another
dependency mutation, reversed clocks or an unknown case retains conservative
partial delivery. No observation lifetime is renewed by the proof.

## Coherent ownership and publication

One HTTP response uses one repeatable-read, read-only database transaction and
one actual database clock. Add a caller-owned financial receipt reader and reuse
the invocation-local physical/installation/DDL facts. The connection-owning
compatibility reader remains available. Coordinate sampling also uses one
repeatable-read transaction. Never cache facts across transactions.

The full composition captures/fences its signed native basis before and after
collection. The existing fast publisher may reuse that composition for a proved
account-only or receipt-only change, overlaying current financial receipts and
account negatives in its owned transaction before signing new output. All
original stable-composition, row, recovery and owner deadlines remain binding.
The owned publication transaction also uses repeatable-read isolation. A
concurrent serialization refusal is superseded work with rollback and the
existing bounded retry schedule; it is not evidence of an operational incident
and cannot replay an uncertain commit.
An unchanged owner ID is insufficient: require its current lease to be live.
No HTTP collection, financial observer, broker request, incident write, new
polling service or corpus verification is introduced.

Fast reuse validates context and dependencies once in its final owned publication
transaction. Do not open an earlier coordinate transaction only to discard its
subjects and repeat the complete validation before commit. The bounded worker
health read preceding that final validation grants no publication authority.

Use the actual five-second fast-parent allowance for child retry admission;
keep the twenty-second full-collection bound separately. Never admit retries
against a longer internal clock than the parent permits.

## Independent public dimensions

Keep `observation_current` as the strict observation gate used by machine
readiness and acknowledgement. Add explicit consumer-only display currentness
and independently admitted display keys. Signed producer envelopes must carry
their empty consumer defaults. The public JSON exposes display and strict
currentness distinctly; HTML/header/browser delivery markers describe the human
display, while machine and ACK checks continue using the strict gate.
The machine endpoint cannot color an unknown/non-strict result green merely
because the independent human display is healthy: it remains neutral, or red
for a current negative, with UNKNOWN/current=false and HTTP 503.

Display readiness requires the proved native/financial row dependencies,
original observation/row/recovery bounds, current signed review head and live
producer owner. Current negatives always dominate. A server-side partial response
with an authenticated current negative keeps a red image border. Genuine browser
offline, stale-document and transport-failure states retain neutral styling.
Market countdowns require their own admitted card and browser freshness, rather
than an unrelated financial scope. Preserve unchanged completed-run identity and
payload so normal account valuation cannot replace it with a pending-plan card.

Reuse the computed human health once within JSON serialization. Retain independent
HTML and JSON preflight; the measured few milliseconds of pure classification
do not justify a new cache or framework.

## Qualification and architectural review

Use actual PostgreSQL account inserts and concurrent commits; falsify account
plus command/control mutation, identical append plus unrelated mutation, two
appends, changed anchors/physical/configuration/DDL/binding, expired owner,
negative account and financial receipt precedence, and expired original bounds.
Prove one read-only transaction per response, no new collection, and immediate
visibility on the next coherent read. Exercise ordinary full-to-refresh-to-full
account handoffs repeatedly with the production implementation, not a test oracle
that simply expects every scope mutation to grey the page.

Test effective border precedence for partial red and actual browser stale grey,
completed-run/card continuity, countdown independence, strict machine and ACK
refusal, and the fast retry budget. Record review coverage/findings and measured
limits. Deliver the qualified local patch through the existing backed autonomous
installer, trace it, and verify the real account/book/trading history and green
dashboard after activation. GitHub publication remains deferred pending stability.
