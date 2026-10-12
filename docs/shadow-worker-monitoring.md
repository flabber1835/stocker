# Shadow worker monitoring and operator status

Decision: 2026-10-11. A verified saved portfolio and a running publisher are
different facts. The installed shadow supervisor stopped behind an
unacknowledged worker attempt after a restart, while the dashboard correctly
verified its saved Friday portfolio. The page omitted publisher liveness, and
startup with a retained pending attempt did not project an incident to the alert
outbox. Retained financial numbers also hid their LAST KNOWN label inside closed
technical details.

## Independent worker observation

The shadow supervisor publishes one compact, authenticated operational status
file in the existing shared state directory. The panel reads that directory
read-only. The record binds the configured database, observation identity, Git
revision and immutable image. It contains a per-supervisor incarnation, original
observation time, optional exact worker-attempt identity and its original
deadline. It contains no credentials, broker state or complete financial book.

Publication uses atomic replacement through the existing finite dependency
observer. This is an expiring liveness observation, not a durable financial
acknowledgement. A failed publication cannot abandon a supervised worker or
extend its deadline. The panel reads files in one bounded spawned observer;
filesystem stalls cannot block the HTTP worker indefinitely.

A positive record is current for at most 60 seconds from its original producer
time, and never beyond the attempt's original deadline. It requires the existing
local live-process proof for an active pending attempt. During the short handoff
from a completed child to durable acknowledgement, an existing positive record
from that same supervisor incarnation and exact attempt may retain only its
original validity; absence of a new proof cannot renew it. A restart cannot
adopt that record. Fresh idle observations require an absent pending marker.
An existing critical marker always overrides a positive observation. A pending
marker must agree with the observed attempt. Missing, malformed, unauthenticated,
foreign or expired observations cannot establish a healthy worker. Future
observations retain the panel's existing five-second clock-skew limit.

The normal producer updates once a second. The 60-second proof bound accommodates
the browser's existing 30-second refresh and 45-second document ceiling. A
healthy worker row also caps that document's validity by its remaining original
proof/deadline. Start the next browser read before that shorter boundary. This
prevents routine refresh flicker and prevents a newly rendered document from
extending a worker proof that is already close to expiry. Other current-row
status policies retain their existing contracts.

The worker row participates in the same required-current operational status as
JSON and HTML. A halted or unreadable worker makes the operational headline red;
an independently verified portfolio retains its own status. Worker liveness
does not grant execution authority, change strategy/controller state or clear
the interruption fence. Legacy deployments without a shadow service retain their
existing projection.

## Retained interruption alerts

Startup with a durable critical or pending marker still launches no child.
Publish a critical interruption incident through the existing durable outbox,
using the exact retained marker bytes to derive its idempotency key. Repeated
starts and retries coalesce for the same retained incident; a different attempt
creates a distinct incident. Marker contents remain on disk. The public alert
uses a bounded classification and attempt identity, never raw exception text or
private configuration. A bounded retry after a failed outbox write retains the
same incident identity and cannot soften the local fence.

An orphaned pending attempt is reported as an unacknowledged worker outcome.
The health diagnostic must not describe it as a missing critical-latch file.
This change supplies monitoring and diagnostics; recovery continues to require
independent retained-state verification and the reviewed operator fencing path.

## Visible status reasons and retained numbers

Show the current failed/unreadable checks beneath the operational headline,
using their plain-language labels and values. Link each reason to its row.
Keep the technical aggregate and its source values available. A historical
blocked cycle and an unacknowledged incident remain visible until their existing
recovery and acknowledgement contracts are fulfilled. A current healthy worker
cannot conceal another failed required check.

Render an explicit LAST KNOWN prefix for retained, unverified financial values
on the visible card. Preserve their original observation clocks and status.
Do not smooth colors by renewing proof, inventing current data, extending a
browser document's validity or hiding known failures during refresh.

## Qualification and release

Compose the producer, actual panel reader, JSON and HTML. Exercise real child
processes through healthy advance, natural exit, normal acknowledgement,
restart with a retained pending/critical marker, missing/stalled storage and
producer death. Falsify authentication, configuration/attempt binding, original
expiry, critical-marker dominance and incarnation checks. Verify idempotent
outbox publication and bounded retries with PostgreSQL. Inspect visible text
outside closed details for LAST KNOWN and the exact failed-row links. Retain
browser refresh and current financial-proof tests.

Pin the exact changed runtime sources and added observer in a separate reviewed
retained-source profile. Admit the complete preceding main and installed source
manifests without reformation, source reacquisition, financial record changes or
broker commands. Qualify the full source closure and actual formed-book upgrade
before release. UI fixes must be qualified and included in the certified image
before the next installation.
