# Dashboard and adjacent paths: architectural review

Review date: 2026-11-09. Local predecessor: `7d267e004b894b4d98ccad977bbbc041dcf4b11c`.
Authoritative main independently fetched as `1e7f4b181fbcb998b3086833ab813c21b1c2ca8e`.
The owner authorized root-cause corrections and local PAPER installation. This
review uses source inspection, independent dependency/publication/UI reviews,
the actual installed service state and captured read-only response transitions.
It does not certify LIVE trading, future market openings or every possible fault.

## Architecture from the outside

The operator needs independently dated account balances, immutable saved intent,
current execution progress, the canonical strategy book, worker capability and
review history. A new account mark does not change a completed order. A completed
order does not change Wealth Core. A successful HTTP round trip is connection
evidence, not a new financial verification. Acknowledging an incident changes
review metadata, never authority to trade.

The intended structure is therefore an acyclic evidence pipeline: existing owners
publish financial/native facts; one bounded background projector authenticates
and composes them; a coherent read-only consumer validates current dependencies;
one pure human classifier feeds HTML/JSON; the browser controls connection age.
Strict machine readiness remains a separate view of the same evidence. Expiry,
workflow phase, source identity and negative evidence retain distinct meanings.

The existing application already has the important boundaries: execution-only
broker access, broker-independent strategy, owned bounded verifier workers,
signed purpose-specific projections, append-only review history, finite document
age and exact-view acknowledgement. The defects are in how dependency versions
and currentness are composed across those boundaries, rather than evidence of a
need for another dashboard service, broker poller, replacement book or framework.

## Demonstrated event and causal chain

The account record in the owner's photo matches the 08:55:47 Pacific observation:
equity $48,482.11 and cash $12,311.65. Successive minute observations changed only
equity, with cash, buying power, account identity/status and flags unchanged.
The installed account trigger legitimately advanced the shared PAPER revision.
An observed later revision row had the same transaction identity as its new
account row; installed trigger definitions confirmed the update path.

During a live read-only reproduction at 08:58:50–08:59:02 Pacific, responses were
PARTIAL with changed scope PAPER and retained=false. The account still had its
original close-time validity boundary; the book was independently current. At
08:59:03 the response became CURRENT/green. HTTP requests succeeded, all six
applications were healthy and no application restart occurred. This is a
dependency handoff defect, distinct from the earlier short-expiry HTTP refusal.
The exact original 08:56 response body was not retained; the reproduction and
matching durable account evidence establish the mechanism without inventing it.

## Findings and selected corrections

| Area | Finding | Root correction |
|---|---|---|
| Display dependencies | One strict PAPER token invalidates account values, plans, completed runs, ownership, authority and worker status together. | Separate native and receipt dependencies; prove ordinary account-only revision advance with a bounded indexed witness. Keep other changes conservative. |
| Financial renewal | A healthy financial receipt replacement changes signature/row version and invalidates unrelated composition. | Consume financial rows independently under the same native basis; keep fresh negatives dominant. |
| Read coherence | HTTP starts repeatable-read but opens another transaction for financial replacements. Coordinates are sampled under multiple read-committed snapshots. | Caller-owned receipt reads, coherent coordinate/publication transactions, invocation-local shared facts. |
| Fast-publication duplication | An early complete coordinate read discards its subjects, then repeats context/dependency validation in the publication transaction. | Keep the final owned fence and remove the discarded early transaction. |
| Current account negatives | PAPER invalidation refreshed reconciliation but did not immediately project newly recorded account-blocking facts. | Consume current account safety negatives in the coherent display path, retaining identity/economics/reservation guards. |
| Owner liveness | Context binds owner ID, not expiry; the old global neutral gate indirectly supplied this safety. | Explicit current owner-lease and original deadline checks before independent display readiness. |
| Border precedence | The server-partial CSS selector overrides red health with grey. | Preserve current red evidence on a partial response while genuine browser stale/offline states remain neutral. |
| Completed plan card | Broad withdrawal removes completed-run payload, causing a misleading next-plan placeholder. | Preserve unchanged admitted run identity/payload; do not fabricate a next plan or modify trading progress. |
| Countdown | A card's countdown also depends on global financial observation currentness. | Use that card's eligibility and the browser's original document/lifecycle limits. |
| Retry ownership | A five-second fast parent controls a child admitting retries against twenty seconds. | Use the actual fast budget for retry admission; retain separate full-collection and parent deadlines. |
| Pure duplication | Partial JSON computes the same human health twice; combined preflight measured about 4.7 ms. | Reuse the result within serialization; retain real HTML and JSON preflight. |
| Test oracle | Existing tests explicitly require broad withdrawal for every PAPER change. | Add production-path account/receipt handoff oracles, concurrent PostgreSQL falsifiers and effective border tests. |

The implementation decision and exact invariants are in
[dashboard-dependency-handoff.md](dashboard-dependency-handoff.md). In particular,
the account witness is not transaction-ID inference: one guarded revision advance
must be exhausted by one necessarily-invalidating append, with an unchanged
anchor and physical/configuration basis. Mixed writes, ambiguous histories,
missing metadata and unknown cases cannot earn display readiness.

## Review coverage and boundaries

Reviewed producer collection/composition, native and receipt invalidation, signed
snapshot validation, worker ownership/timeouts, account evidence publication and
eligibility, current/complete trading card selection, financial receipt consumption,
human health versus machine readiness, exact-view ACK, HTML/JSON preflight,
DOM replacement, PWA/header validation, countdown/browser clocks and styling.

The existing one-way strategy/controller/execution membrane remains correct and
is preserved. The current book, filled command, clean reconciliation, database
volume, backup/WAL policy and independent maintenance process are release
preservation checks, not inputs to strategy reconstruction. No Wealth Core or
financial trigger change is selected. Strict account-trigger invalidation remains
necessary because PAPER verification reads account evidence in its recovery and
post-open alignment guards.

No evidence warrants replacing the browser's existing single-flight refresh,
deferred DOM update or bounded lifecycle controls. Pure classifier work is small;
introducing a long-lived verdict cache would add new invalidation risk. The full
composition's finite refresh margin is an intentional scheduling allowance, not
proof that every periodic read is redundant. This patch removes demonstrated
unnecessary recomposition caused by account/receipt churn; broader refresh-rate
changes require measured evidence and their own deadline proof.

## Qualification and delivery evidence

Qualification must exercise real source inserts and the public production path,
including account plus control/command mutation, identical and multiple appends,
anchor mutation/deletion, physical/configuration/DDL changes, current account and
financial negatives, owner/row expiry, cross-transaction commits, strict machine
and ACK refusal, negative border precedence and browser stale behavior. Executed
omission falsifiers must detect removal of safety guards.

The final local qualification report, source seal, immutable patch/bundle,
autonomous install receipt and dynamic execution trace will bind the delivered
commit. Post-install observation must cover routine account renewal, stable book
and completed-trade cards, current account values, green human health and actual
strict safety state without acknowledgement of active failures. A later genuine
failure must still be visible immediately. GitHub publication remains deferred
until the owner's stability review.

Each qualification cohort binds unchanged runtime inputs and the changed test
files it actually executes. Every changed test must be covered by a successful
cohort, and the final qualification binds all tracked candidate bytes. A change
to an unrelated test assertion or explanatory document does not require another
database test run when its runtime inputs are unchanged.

## Post-install falsification: numeric account sequence ordering

The first installed candidate was deliberately observed across three ordinary
account renewals before acceptance. That check rejected the candidate: each
account renewal still produced a brief partial response, although receipt-only
handoffs worked. A coherent read-only diagnostic isolated the cause to the new
account-coordinate SQL. Selecting `seq::text` and then `ORDER BY seq` lets the
output alias control ordering, so the maximum query chose `9999` instead of the
actual numeric latest record `22862`. Both anchors became null and the cause
witness correctly refused reuse. Existing small single-digit fixtures missed it.

The same query also performed an avoidable scan and text sort of about 22,765
account rows. Qualified numeric ordering uses the existing primary-key index
backwards with `LIMIT 1`. Qualify numeric sequence columns in maximum, latest
tie-break and bounded append queries; keep text only for wire representation.
Add PostgreSQL digit-boundary and tied-clock cases, the production-like sequence
range, execution-plan checks, and an executed text-ordering omission falsifier.
No financial trigger or cause-proof invariant is weakened. Preserve the failed
renewal capture and repeat the real routine-renewal observation after correction.

## Adjacent installer contract

The post-trade installation exposed another boundary error: final verification
required an OK notification-history row even when a delivered, resolved incident
was the only remaining unacknowledged item. It also skipped post-trade publication
waiting and did not distinguish the new human-current dimension from strict
readiness. Its partial-publication adapter called a private runtime row predicate
with incomplete stand-in models. These are host-readiness contract defects;
rebuilding the already healthy application does not correct them.

The selected host-only correction consumes the public JSON protocol and explicitly
requires strict readiness for final acceptance. The existing reviewed-history
allowance is extended narrowly to completed, positively reconciled post-trade
installs, with zero pending/DLQ deliveries, no active conditions or warnings and
an explicit restricted result. The installer never acknowledges history. An
expired final observation uses the existing separately journaled recovery command
with a new finite observation, unchanged processes and fresh canonical proof;
it never resets the original deadline or restarts trading. See
[dashboard-posttrade-install-readiness.md](dashboard-posttrade-install-readiness.md).
