# Bounded database recovery and local backed PAPER patch

Decision: 2026-10-26 UTC, before implementation. At 04:50 a raw psycopg
ConnectionTimeout escaped the worker's fresh clock sample. The supervisor's
bounded holder-file publication then timed out during replacement and escaped
its launch loop. Docker recovered the process; the two critical alerts remained.
Concurrent backup maintenance is a suspected load contributor, not an established
cause. The owner authorized a locally qualified patch and updating existing PR
540 without waiting for CI, merge or signed publication.

Recognize real psycopg OperationalError/InterfaceError subclasses without an
SQLSTATE, including ConnectionTimeout, through the existing database availability
classifier. Preserve the existing SQLSTATE allowlist and integrity/programming
refusals. A failed fresh clock connection/query becomes a typed infrastructure
wait before lease acquisition or broker work. Never invent a clock sample or
widen the skew limit. A failed main-loop connection waits using the existing
poll bound, discards its local idle permit and retries with a new connection.
This is not recovery from an uncertain write: callback/journal outcomes retain
their existing reconciliation path.

The supervisor retries a bounded launch dependency timeout and temporary
resource exhaustion (EAGAIN/ENOMEM) with the existing capped restart pause.
Each attempt uses the existing killable observer and reaping guard. A failed
holder publication cannot launch a worker. Configuration, permission and
programming failures still escape; callback, heartbeat and lease deadlines are
unchanged. No replacement may coexist with an unreaped predecessor.

Qualification must reproduce the old connection and holder-timeout failures,
test persistent recovery and permanent refusal, and prove no lease/cycle/order
mutation before a valid fresh clock sample. Retain real PostgreSQL and kernel
process/observer tests, with guard-removal falsifiers. Exercise maintenance load
and injected connection loss in private isolated resources while a supervised
worker waits for the open; use no provider/broker calls or production tables.

## Local delivery exception

Use an offline source layer over the exact installed signed DDA foundation,
truthfully labelled with the qualified local commit and actual image digest.
Retain the exact source hashes and qualification report; export a portable
patch/bundle. Update only the complete current structural candidate map and its
transition pin, preserving all independent baseline, checker, economic and
historical witnesses. Unknown candidate bytes still refuse. No economic code,
canonical book, source inputs or financial expectation changes.

The archive-off local installer is not applicable. A backed local application
roll must explicitly require REQUIRED_V1, the immutable ACTIVE predecessor
receipt, actual unchanged PostgreSQL container/volume/system and archive-on
configuration, current future WAITING_OPEN plan, zero working/uncertain commands,
same-account PAPER GET-only observation, identical old/new canonical proof and
automation configuration, and genuine current-image full restore evidence.
Reuse the current verified physical base/WAL; do not create redundant bases.
Use canonical lifecycle/media ownership and the existing authenticated shadow
drain before stopping only the six application roles. Preserve financial controls
and all durable histories. Start the candidate shadow and re-prove the unchanged
book before starting the other roles. No PostgreSQL/engine/WSL restart or reset.

Maintain a separate clean candidate checkout/private literal environment and
current-source backup maintenance owner; do not falsify an installation or
signed authority receipt. Keep the old release/evidence recoverable. Completion
requires healthy exact-image roles, advancing leadership, preserved future plan,
healthy recurring maintenance and genuinely green finite dashboard receipts.
Historical predecessor incidents may be acknowledged before preflight captures
notification history, after independently confirming the old services recovered.
Record the actual failure and qualification, and explicitly state that the new
patch is still pending installation. This is owner-authorized incident review,
not an assertion of deployment readiness. Capture those durable acknowledgements
in the immutable handoff history; completion still requires every gate above.
This is local PAPER operational qualification, not CI or live-money approval.

The backed graph spells authorized service images as repository digests. A local
source-layer image has an actual immutable image ID without a registry manifest.
The host delivery driver therefore appends an operation-private Compose overlay
containing only the eight application image selectors and `pull_policy: never`.
The selected ID must equal the request's exact predecessor or candidate image;
the overlay cannot contain PostgreSQL, environment, mounts or commands. Existing
overlay bytes must match the deterministic rendering. The three canonical backed
Compose inputs and all database guards remain unchanged. Qualify this separately
as a host-tool fix, bind the executing tool commit/hash in retained evidence, and
keep the already qualified runtime commit/image and its completed full restore.
Host tooling can advance independently of the installed runtime; do not relabel
or rebuild identical runtime code merely to deliver an image-selector correction.

## Completed-predecessor notification repair

Decision: 2026-10-30, before implementation. The owner explicitly authorized
fixing both the dashboard and the separately observed worker error locally.
The normal generation-boundary wait carries an older SUCCEEDED cycle and the
current leader permit. Its fallback notification key omits that permit's fence,
although the immutable payload includes it. Lease reacquisition therefore
reuses the key with different content and correctly trips ImmutableAlertChanged.

Do not modify, delete or reuse the old alert payload, catch its integrity refusal,
or make status polling create one new warning per lease. The exact normal
WAITING result for an older-generation SUCCEEDED cycle, with a current permit
and the existing terminal-generation-boundary reason, is quiet. Other states,
actions, missing permits, unexpected reasons and current/future generations keep
their existing notification and immutable-outbox behavior. Reproduce the old
collision against a real private outbox and falsify removal of the quiet guard.

An explicit `POST_TRADE_SUCCESSOR` backed local handoff may preserve this idle
state without inventing a current-generation successful cycle. Require the
same currently owned PAPER account/deployment/takeover, enabled and kill-released
current control, no current-generation cycle, exactly one older SUCCEEDED cycle
for today's exchange session, its real completion and positive authenticated
clean reconciliation, and no failure or historical-state-only flag. Its original
immutable plan must name the sole current unsuperseded successor via
superseded_by; that successor must match current control/rollout/source and have
the same dated decision, effective session and targets. Keep both plan IDs and
their distinct authority scopes explicit in retained evidence.

Re-derive the current successor plan under current signed authority, preserving
the existing complete old/new canonical comparison, native PAPER account and
zero-open-order GETs, history/notification proofs, source-idle requirement and
absence of any in-flight/UNKNOWN command or other active financial cycle. Keep
the original post-trade close-minus-fifteen-minute admission margin and all
handoff/drain budgets. Preserve current generation, certificate, binding,
PostgreSQL, book, source and completed execution history. Neither the old cycle
nor its superseded plan becomes current execution authority or is replayed.

The ordinary PRE_OPEN, POST_TRADE and exact BLOCKED_UNSENT paths retain their
existing guards. Apply only the qualified compatible source layer through the
canonical backed application handoff; reuse real current base/WAL evidence and
do not add an image-specific full restore. The repaired worker must establish
stable advancing leadership without new notification collisions before an
actually resolved incident may be acknowledged. Preserve unrelated negative
facts and report actual local commit/image provenance without a CI claim.

This repair may observe the exactly identified predecessor automation service
restarting from ImmutableAlertChanged while its container/image and control
remain owned. In POST_TRADE_SUCCESSOR only, retain the exact known incident
identity and original notification payload, require the other five applications
healthy and all ordinary no-active-work/account/source guards, and stop the
automation through the canonical handoff before replacement. This is no general
unhealthy-service exception. The candidate must establish healthy services and
stable advancing leadership with no repeated collision.

Do not acknowledge the active incident to pass admission. The new mode's final
software-verification receipt may retain only those exact predecessor incident
alerts as visibly red, with their immutable identities/payloads unchanged and
all unrelated current checks healthy or ordinarily pending. It must record the
actual panel verdict, not claim a green dashboard. Notification-history checks
remain strict throughout the handoff. After the verified operation releases
ownership, acknowledge only incidents whose causes are then independently
resolved through the supported CLI, and re-read local/public operational state.
