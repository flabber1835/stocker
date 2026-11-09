# Activation joins producer health renewal

Decision, 2026-11-08, before implementation. The signed main installation at
`2714afbb25fd` completed software installation, financial preparation, shadow
attestation, plan reconciliation, authority release and the leader/heartbeat
proof. Its final role sweep refused the shadow container's unhealthy state.
Docker recorded `shadow health projection binding changed`. The authenticated
hint was last published at 2026-11-08T20:36:19Z, before this installation, and
both its configuration and database row-inventory bindings differed. The new
publisher had not completed a worker before the activation path quiesced it;
the resumed worker was again interrupted by final refusal. This is a missing
producer/consumer startup handoff, not evidence of invalid financial holdings.

The read-only shadow-status subprocess can verify the retained financial state
independently of the producer. That success must not let activation interrupt
the producer before it renews the configuration-bound health hint. Do not repair
the hint from the installer, disregard its binding, widen the health deadline,
or accept Docker process liveness as financial readiness.

Give an authenticated, schema-valid projection binding mismatch, or an absent
hint after committed origin, a distinct `ValueError` subtype carrying its signed
session when one exists. Existing health consumers
still refuse it. The activation shadow observer recognizes only that exact
negative condition while the actual publisher has a fresh authenticated
ACTIVE_WORKER status, matching durable pending records, stable incarnation,
binding and attempt, and an unextended live worker deadline. It emits a typed
HEALTH_REBINDING wait through the existing bounded formation protocol. Its
session is null only when no hint exists, and never grants session authority. Idle,
unknown, expired, replaced, malformed, unauthenticated and other failed health
states remain refusals. Legacy/nonoperational configuration keeps its existing
attestation behavior.

Observe this cheap prerequisite before invoking the independent financial
status verifier. While renewal is pending, wait for the one canonical producer
instead of repeatedly replaying the same retained history in status children.
After renewal, run the unchanged financial attestation and reconciliation;
resumption and the final exact-image/full-health checks still apply. The
existing data-work deadline bounds the wait. No positive evidence is cached,
no new producer is launched by a read, and no financial or broker state changes
are introduced by this observer.

Renewal reobservations use a 30-second cadence, capped by the original remaining
data-work budget. They do not inherit the three-second financial-formation poll
cadence: a multi-minute producer replay must not create hundreds of disposable
status containers. This does not change Docker health cadence or proof age.

Qualification reproduces a valid financial frontier with an obsolete health
hint and a live producer. Prove the old path accepts too early, the corrected
path waits without calling the independent verifier, and fresh producer
publication permits its ordinary verifier. Reject idle/stale/replaced owners,
bad HMAC/schema, unrelated errors and expired deadlines; execute falsifiers for
the renewal prerequisite and the owner/attempt continuity guards. Join the
actual activation wait to this response, including the post-resume path. The
final health predicate, PAPER fences, immutable installation receipt and book
remain unchanged.
