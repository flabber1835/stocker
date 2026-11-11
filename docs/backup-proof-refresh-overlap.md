# Keep current WAL proof available through maintenance renewal

The November 10 close capture sampled ordinary maintenance hashing archived WAL
while three PAPER plan preparation callbacks retried. The captured failures had
lost their initiating exception. The shared-owner collision is the supported
explanation. The original receipt's age and coverage during the collision are
unknown. The attribution patch made the refusal visible and kept the same
durability and retry decisions.

The shared advisory owner serializes all content hashing and receipt updates.
It currently also prevents a caller from examining an already completed receipt
throughout another caller's scrub. In addition, ordinary maintenance schedules
its next pass 300 seconds after publishing its dashboard evidence. The shared
byte receipt expires 300 seconds after the earlier content-proof completion.
That schedule cannot overlap one maintenance-produced receipt with its next
scheduled renewal.

## Read a completed proof during renewal

The ordinary backed PAPER admission may use the authenticated receipt while the
exclusive proof owner is busy, provided the receipt covers the exact current
base, geometry, frontier, every required payload and sidecar, and all existing
physical, archiver, alias, and metadata guards pass. The concurrent path is a
bounded, read-only hit. Missing, new or changed objects require the existing
exclusive two-pass owner. Do not write a receipt or update the local proof cache
on a concurrent hit. A busy owner with no eligible receipt remains a retryable
strict refusal and does not call the absent-media policy. Actual media failures
retain their ordinary classification and continuity checks.

After both metadata observations and the current selection and frontier checks,
reread the exact authenticated primary-local receipt. The existing atomic file rename
orders the final file observation against publication and invalidation, even
within a repeatable-read SQL transaction. Recheck the original boot, postmaster,
and native uptime after that observation. A different generation, invalidation,
changed physical context, or expired clock refuses admission. A failure during
this read-only path cannot overwrite an active producer's result. The exclusive
owner still invalidates a failed proof through the existing immediate path.

## Refresh before the original clock expires

Only the ordinary maintenance producer can proactively perform a full scrub.
When the authenticated byte receipt is within 120 seconds of its original
expiry, maintenance performs both existing full byte and metadata passes even
when the old receipt is still eligible for a reader. The lead allows for the
observed 83-second pass and dispatch variation. It does not guarantee a full
scrub finishes within the remaining time. An expired receipt remains ineligible
and a failed scrub invalidates as before. Ordinary hits and incremental work
preserve the original full completion clock.

Drive the next pass from the earliest of the existing publication schedule and
the validated maintenance-produced byte renewal instant. Derive that instant
from the qualified original byte completion and primary native uptime at
publication. Carry it through the existing maintenance result as optional
scheduling data. Older results without it use the existing schedule. It grants
no financial or dashboard authority. Preserve the dashboard publication clock,
its 600-second deadline, and existing caller, worker and retry bounds.
The existing primary observation also carries the latest qualified maintenance
clock to seed the already-owned freshness reader if a long base renewal is due.
Other runtime evidence cannot replace a scheduled byte renewal.

Qualify exact concurrent hits, incomplete or changed coverage, generation
replacement, failure invalidation, selection change, and expiry, with a real
PostgreSQL repeatable-read observation where available. Qualify both hashes on
early refresh, unchanged hit clocks, and earlier scheduling based on the actual
byte proof. Prove the previous bounds and failure paths still refuse. Do not
modify LIVE or legacy policy, broker transport, journal, book, restore evidence,
or the semantics of the original 300-second integrity interval.
