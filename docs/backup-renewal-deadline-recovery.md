# Deadline-owned backup renewal and attributable failures

Decision 2026-11-09, before implementation, continuing the owner-authorized local
PAPER patch. Main is independently verified at
1e7f4b181fbcb998b3086833ab813c21b1c2ca8e; feature HEAD before this correction is
8a0add691eebbda7136731704277fc5105e54958. The installed application/maintenance
package is 4dd0a32473caf25faac0a6e57491aaa5bed56ef2. Keep all installed sources,
financial state and original incident evidence immutable.

## Demonstrated failure chain

The ordinary shared-integrity pass refused at 03:57:18 UTC on November 10.
The coordinator discarded the worker's detailed safe error and slept another
300 seconds. Runtime-chain evidence last published at 03:51:49.024643 expired
at 04:01:49.024643. The next successful publication at 04:02:26.694057 left
637.669414 seconds between successes; health recorded failure and recovery
47.693856 seconds apart. The initiating worker refusal cannot be reconstructed
from the retained generic error. Do not label it contention, corruption or expiry
without evidence.

An independent classifier defect turned unchanged healthy scheduled-wait rows
into additional REVIEW conditions when the backup prerequisite expired. Genuine
backup failure and recovery acknowledgement must remain visible.

## Closed failure protocol at the actual refusal owner

Retain an explicit bounded machine failure envelope from the worker through
Docker transport, status shell and supervisor. Use closed stage/cause enums,
finite elapsed/owner-wait/proof-clock facts, and separate lock/container cleanup
outcomes. Never export raw exception text, SQL, DSNs, credentials or arbitrary
stderr. Unknown faults stay explicit hard refusals. Cleanup failure must preserve
the initiating cause and forbid automatic transient retry.

Select only BUSY, PROOF_WINDOW_EXPIRED and the narrowly defined SELECTION_MOVED
below as retryable. They must be named by the actual owner's existing lock,
original-clock or selected-base identity guard. Introduce narrowly typed exception
precision at those boundaries without changing their conditions. Other media,
integrity, policy, transport and unclassified refusals are not guessed transient.
Preserve shell exit classification and the typed record across wrappers.

The concurrent reader can also observe a normal atomic base-selection change.
Select a narrow SELECTION_MOVED retry only for a proved selected-base identity
change with the same physical system and geometry. It forces fresh outer
selection/admission; it never reuses the old expected base or accepts a geometry,
timeline, media or integrity mismatch. This is not a general MEDIA_CHANGED retry.

When a second owner observation finds a genuinely expired authenticated receipt,
expose only diagnostic clock facts after all non-clock context/boot/schema gates
pass. The positive proof must still be absent. Do not expose an expired positive
proof as an alternative reusable authority, duplicate receipt decoding, renew the
clock on a hit, or remove either byte/metadata pass. The 300-second full-proof
clock and 600-second dashboard evidence lifetime are unchanged.

## Renewal cadence belongs to publication, not pass completion

Emit a closed result for every ordinary pass: SUCCESS, RETRYABLE, BLOCKED or
STANDBY, safe terminal phase/cause, and the exact last successfully published
runtime-chain observation. Return the database's actual publication timestamp
alongside the unchanged proof; never substitute command completion time. A later
retention/checkpoint error does not erase an already successful publication.
These structured systemd diagnostics do not grant positive backup health and
must not be disguised as base-renewal authority.

Schedule ordinary renewal against the retained publication deadline and a
monotonic bound. A classified transient or target-lock standby gets bounded
backoff within that same original deadline, rather than a fresh five-minute
sleep. Every retry reacquires the proper owner and re-observes selection/media.
Do not retry corrupt media as if healthy, extend lifetimes, invent a fresh proof,
or wait indefinitely. Expired/unresolved evidence remains a failure.

Bulk base/retention work must not acquire an extra post-completion sleep which
starves authority refresh. Preserve its target/media locks, original finite
budgets and active mutation units. A periodic freshness reader may operate under
the same owning coordinator while bulk work is outstanding: it is broker-free,
does not run retention/base production or introduce a competing writer, and uses
the same common proof owner and fresh physical guards as ordinary application
readers already running during maintenance. Trigger only at actual renewal
boundaries, with bounded single ownership; record failures and original deadlines.
Do not shorten a timeout to kill an active backup/deletion or silently omit
retention. Genuine inability to establish fresh evidence still expires visibly.

## Independent incident attribution

Keep the complete prerequisite predicate for green eligibility, missing proof,
financial subjects, accounts, feed, authority, workers and plan/history identity.
Classify otherwise fully proved scheduled waiting facts by their own subjects.
An independent backup failure or typed bounded renewal may prevent global green
without inventing a new incident on unchanged waiting/history rows. Preserve the
actual backup FAILED event, genuine recovery and acknowledgement latch.

## Qualification and delivery

Test complete successful-publication, typed failure/standby, bounded retry and
later publication sequences against the actual 600-second row expiry. Cover
busy ownership, expiry during final/second observation, hard corruption, lost
transport, failed cleanup, retained publication before a later failure, and long
bulk work with independent bounded freshness. Execute guard-removal falsifiers.
Mixed WAITING_OPEN/historical PAPER plus backup expiry must produce exactly the
backup failure, then recovered-but-unacknowledged amber, without waiting warnings.

Keep application and maintenance source/image parity. The handover host may use
the exact same candidate commit and the identical completed application
qualification report, with explicit executing-tool/test coverage and fresh clean
source validation. For a distinct host-only successor retain the existing exact
three-file delta qualification. Bind/revalidate both routes in the existing
authenticated journal; no source/image override or unchecked fallback is allowed.
The operational qualification inventory always includes the tracked handover
script and its direct test, even when neither changed in that release. This
keeps the same-commit route usable for later qualified reader updates; test
execution is still an independent admission requirement, not inferred from a
file's presence. Existing reports already containing those files keep their
exact meaning. An absent legacy file is not synthesized into an old inventory.

Do not change economic contributors, strategy/controller configuration, canonical
book, saved plans, broker commands, UNKNOWN outcomes, long-only/unlevered guards,
LIVE prohibition, backup retention policy or genuine restore qualification. Export
the complete local patch; perform qualified application installation and safe
reader handover, then verify current dashboard/account/plan and finite normal
renewal stability. Acknowledge only resolved reviewed conditions through the
supported exact-view interface, never as the root-cause fix.

## Bounded freshness transport budget

The optional status argument `--timeout-seconds N` bounds the whole status
invocation, at no more than its existing 600-second ceiling. Preserve elapsed
shell time when deriving the remaining bridge budget; do not start another
fresh deadline after archive/base guards. The bridge uses an absolute monotonic
deadline across its preflight, worker and cleanup. Reserve the existing ten
seconds for uniquely owned Docker cleanup, with at most five seconds for removal
and five seconds for exact-name absence verification when removal cannot confirm
success. Never inspect unrelated containers or infer absence from driver text.

The bridge passes a shorter independent worker alarm when a freshness-only
caller has less time. Retain the existing maximum worker alarm of 540 seconds,
Docker wait of 560 seconds and whole-status bound of 600 seconds. Reject an
exhausted/invalid transport budget with a closed hard deadline failure rather
than invent a retryable owner or original-proof expiry. These transport budgets
do not alter the original 300-second byte-proof clock, extend dashboard evidence,
cancel an unrelated base/retention writer or admit a one-pass fallback.

## Coordinator mechanism

The ordinary pass emits one closed `maintenance_pass_result:` record. A nested
read-only refresh emits `maintenance_refresh_result:` instead, so the outer
pass result cannot be confused with a refresh result. Both retain the actual
database publication time even when later work fails. Structured diagnostics
are separate from positive backup evidence and base-renewal progress.

Use a small publication-deadline controller shared by the pass and its bounded
freshness callback. The existing process transport accepts an optional due-time
callback object. It submits at most one bounded callback in a worker thread,
continues draining the bulk process pipes, and joins the callback before return.
No callback starts without a cleanup reserve in the original process deadline.
The callback directly invokes `--freshness-only` under the coordinator's existing
inherited target fence; it never reacquires that fence or starts another writer.
Its independent read-only budget is passed into the shared-proof transport, with
time reserved for exact worker cleanup. A failed refresh cannot cancel bulk work.

The retention worker's `observe-current` action reads selected metadata without
taking its exclusive writer lock. It performs no retention, publication or base
creation. The ordinary fresh physical/status/common-proof guards still prove
the exact current selection before evidence is published. Existing `observe`
and `retain` writer-lock behavior and retention/deletion policy remain unchanged.

The freshness budget is the smaller of the remaining original bulk deadline,
the remaining original publication lifetime while that lifetime is unexpired,
and the existing 600-second status ceiling, with a cleanup reserve deducted.
Do not impose an unrelated shorter hashing budget. If the old publication has
already expired it remains failed; a later independently completed fresh proof
may establish new evidence. Never move the expired publication's own deadline.
The status command accounts for its metadata prelude and worker cleanup inside
the supplied whole-command budget. The callback has no authority to cancel an
active base or retention mutation or to change their original deadlines.
