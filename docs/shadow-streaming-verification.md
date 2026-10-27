# Bounded shared-snapshot verification

The October 26 dashboard repeatedly failed on `FETCH FORWARD 5000` after eight
seconds. Read-only EXPLAIN on the actual current normalized snapshot shows why:
the shared branch expands every session's JSON rows and sorts the entire window
before returning the first batch. A server-side cursor bounds client buffering;
it does not make this blocking server-side sort incremental. A reboot or a
larger database memory limit cannot establish a reliable bound for this query.

Keep the complete canonical content verification, exact ordering, price domains,
immutable source identities and existing statement/worker deadlines. Change only
the physical traversal: enumerate actual stored sessions from legacy rows and
shared block references, then stream one session at a time in the original
security-ID C collation. Apply caller bounds to both enumeration and row reads.
Enumerate storage rather than the declared manifest axis so unexpected stored
sessions remain visible to the independent coverage and digest checks. Missing,
duplicate and altered data must remain failures. Legacy-only installations keep
their existing ordered index scan. Do not add another book or verification cache.

A completed observation containing an unreadable/negative financial result must
be eligible for the existing 30-second retry interval. It remains visibly failed
until a fresh independent check passes; it must not be treated as a successful
five-minute cached observation. Successful results keep their original freshness
and normal refresh schedule. Independent PAPER failures must not shorten the
successful shadow result's lifetime.

Qualify exact legacy/shared row order and digests, inclusive bounds, unexpected
stored sessions, duplicate/missing/corrupt input and the old blocking-query
falsifier. On retained production input, measure first-batch and complete-check
time under the unchanged deadlines before reporting the dashboard repaired.
Keep all failed attempts. Repeated green snapshots alone do not replace these
measurements. Broker writes, financial state and backtest resources are outside
this repair.

## Completing an installation after an ordinary host restart

The owner rebooted Windows after the six candidate application roles had started
but before the final green-dashboard receipt. The primary container, image,
volume and database survived; its process start time necessarily changed. At the
final APPLICATIONS_STARTED stage only, the backed installer may observe that
new process incarnation while independently requiring unchanged financial state,
native holdings and orders, configuration, six healthy exact-image roles, stable
advancing leadership and a fresh green dashboard. No earlier installation stage
gets this exception. Record the actual current PostgreSQL facts in the new final
receipt; retain the original preflight facts and request unchanged. Require the
observed incarnation to remain unchanged throughout the final observation.
Subsequent deliveries consume the recorded current incarnation. Changing any
container, image, volume, mount source or database command remains a refusal.

If that final dashboard cannot pass because the running candidate itself needs
this repair, an explicitly selected `--allow-started-predecessor` build may
replace an APPLICATIONS_STARTED operation. It must retain the unfinished receipt
as unfinished. Require its valid digest-linked journal, completed successor
canonical proof, exact running six-role image/configuration, unchanged financial
snapshot/native positions/notification history and the same primary storage.
Record the explicit option and the actual current PostgreSQL incarnation in the
new build. Earlier partial stages remain ineligible. The replacement must earn
its own complete qualification, exact-image restore and normal installation
gates; the unfinished predecessor grants no green status or broker authority.
