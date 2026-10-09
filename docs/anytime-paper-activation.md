# Anytime paper activation

Decision: 2026-10-09. This supersedes the following-open activation wait in
`installation-activation-separation.md` and `unattended-operating-contract.md`.
Software installation and automation activation do not require a future market
open. Missing current data, account readiness, authenticated lineage, signing,
reconciliation or recovery proof still prevents financial activation. The clock
alone does not prevent a fully admitted system from becoming ACTIVE.

Activation keeps the latest actually closed decision and its exact published
frontier. It prepares and reconciles that actual immutable plan, enables control
behind the kill fence, proves the coordinated semantic restore, resumes the
attested shadow and starts the lease-owning scheduler. It does not invent a
future decision, move a plan's effective session, reset the book or backdate a
receipt. A newer closed decision appearing during this sequence remains a typed
readiness wait. Historical research/vendor modes retain their prospective
admission rules; the anytime rule applies to reviewed operational dual mode.

The durable scheduler cycle is the cutover. A new or still-undispatched
`DISCOVERED` obligation first reached at or after its regular-session open is
superseded after shared-journal recovery, without preparation or new transport.
This includes activation during
the first ten execution minutes, and an activation whose restore/resumed-shadow
checks straddle the open. The terminal event survives process restart. The
scheduler keeps running and prepares the next actual closed-session decision for
its following eligible open. A cycle already prepared by the running scheduler
before the open retains its ordinary bounded execution/recovery rules; restarting
that process does not throw away its plan or invent a new activation generation.

Older-generation adoption and unresolved transport recovery precede this gate.
An UNKNOWN/send-pending obligation is reconciled under the existing account,
identity, authority and lease checks; it cannot be discarded as a missed open.
Current pre-transport obligations are terminalized with an explicit
`DISCOVERED_AFTER_SESSION_OPEN` reason. No state-only terminal event claims that
an economic transition or broker execution occurred. Ordinary fresh-execution
windows, quote/cash checks and journal identity remain unchanged.

The deliberate `DISCOVERED_AFTER_SESSION_OPEN` cutover is displayed as waiting
for the next session, never as failed reconciliation or successful execution.
Other superseded, missed or blocked obligations keep their failure presentation.

Operational financial GO is a consumer of the installed schema, not a second installer.
Its preparation validates the exact behavioral and feed catalogs read-only.
Explicit migration also recognizes a completely validated current catalog and
returns without DDL, preserving the migration lock and singleton/corruption
checks. Fresh or recognized additive upgrades still use the existing atomic
migration transaction. This avoids acquiring AccessExclusive locks merely to
add columns that already exist while status readers are running.

Qualification joins host activation at pre-open, open, intraday, post-close and
non-session clocks with the actual PostgreSQL scheduler. It proves no same-open
transport, next-session continuation, retained cutover after restart, and
priority for uncertain outcomes during upgrades. Concurrent real database
readers must not make a no-op migration or financial GO issue DDL. Broken clock,
cutover, catalog and recovery guards require behavioral falsifiers. Tests and
rehearsals use isolated databases and blocked broker transport; they do not
authorize deployment. Exact-head CI, protected signed publication and the new
release's supported activation remain required.

## Responsive operator reads

Full retained shadow verification must not occupy an HTTP request or hide
current control, account, source and backup facts. The HTTP assembly schedules
one owned, read-only financial observer in a spawned process. The existing
killable dependency supervisor enforces a five-minute wall-clock deadline and
parent-death cleanup. The panel never opens a connection before spawning that
observer, shares a database connection with it, or starts a broker/writer.
Other panel facts retain their own bounded reads and the existing one-build slot.

A completed full verification is delivered once, with its actual observation
time. Later requests show its values explicitly as LAST KNOWN while another
observer verifies; they cannot replay that positive verdict into machine health.
Pending, timed-out, malformed or failed financial reads remain UNKNOWN. A changed
configuration discards the old result; it cannot inherit verified styling.
This is presentation work, not a new financial admission cache. Trading and
activation continue to use the complete canonical financial readers. No health
hint, last-known HTML or observer fixture gains paper authority.

Qualification must block a real observer, demonstrate that current panel facts
still render, enforce deadline/reaping and one-observer ownership, and prove a
completed positive result cannot be reused or survive configuration changes.

## Qualification scope for this repair

The owner authorized changing the qualification approach and stopping repeated
pre-activation backups, restores and compaction. For this repair, the following
replaces the repeated real-provider cold GO requirement in deployment guidance:
build the exact feature runtime and test lens, run the changed host/GO/scheduler,
catalog and operator paths plus adjacent failure boundaries on isolated
PostgreSQL, and join activation completion to real restore, lease, heartbeat and
receipt evidence. Explicit provider/authority/transport fixtures remain named.
Reuse the retained real acquisition, canonical formation/parity and immutable
book evidence from the previous exact certified release for unchanged paths;
do not claim those observations ran on the new image. No repeated production
backup, restore or data acquisition is needed to qualify this control-flow
repair. Normal exact-head CI and protected signed certification are still
required. The new certified release must pass its own supported activation and
one coordinated recovery milestone before trading authority is released.
