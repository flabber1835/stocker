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
