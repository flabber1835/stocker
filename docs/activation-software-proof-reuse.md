# Reuse software proof inside one activation owner

Decision: 2026-10-30. The supported activation owner currently downloads and
verifies the same signed CI runtime before financial preparation, during reviewed
preflight and again during runtime selection. These stages share one host owner
and immutable software identity. Only the first verification needs to download
and authenticate the publication and original qualification artifacts.

Keep one process-local software verification session on that deployment object.
It is never serialized, accepted from an installation receipt or shared with GO
children, another activation attempt, another process or a resumed owner. Each
new installation and activation independently earns its signed software proof.
Before every reuse, require the same resolved checkout, complete clean Git
commit/tree, verifier and promotion-policy source bytes and verifier trust/workflow
context. The stored result must bind that exact source and its immutable registry
image. A changed context refuses rather than silently refreshing or falling back.
The result returned to callers is a copy; modifying a returned record cannot
modify the authenticated session.

Reuse only software certification. Reinspect the actual local image ID, registry
digest and OCI revision at the existing boundaries. The reviewed financial bundle
hash/lifetime/source identity, broker account, current fenced lineage, signed
financial authority, backup checkpoint and final operational checks remain fresh.
The GO child retains its separate independent software verification boundary.
No persisted ready flag, operator skip option or environment-selected proof exists.

GO post-validation reconciles the panel with Compose `up --no-deps --wait`
instead of forcing recreation. Compose retains an unchanged image/configuration
and replaces a changed service definition. Independently require the exact selected
image ID and healthy running state before publishing the artifact handoff. Do not
use `--no-recreate`: a configuration change still requires reconciliation. The
180-second wait and all existing final host-command deadlines remain unchanged.

Qualification records the signed-verification call count for one owner and tests
that a fresh owner re-verifies. Changed checkout, commit/tree, dirty source,
verifier/policy/trust context, returned-result mutation and local-image drift must
refuse reuse. An executed removed-context-check mutant must fail the test. Panel
coverage executes the command and final inspection paths, including unhealthy,
wrong-image and Compose refusal results. No production operation is used.
