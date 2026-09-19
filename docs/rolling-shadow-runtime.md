# Rolling shadow runtime and service

This connects the first-deployment GO input proof to the existing broker-free
shadow service. The NAS never passed GO; no operational book migration is part
of this work. Legacy publications retain their existing runtime. Dispatch uses
the authenticated publication storage contract, never an operator-selected
fallback. A rolling publication cannot enter legacy ingestion or replay.

## Authority after durable state

Reuse the canonical rolling initialization and adjacent-session continuation.
Their authenticated checkpoints and immutable session rows remain candidates.
Hold the existing behavioral writer lock and shared publication pin across
candidate commit and a separate runtime-attestation transaction. The PostgreSQL
clock must be sampled after candidate commit and before the following XNYS open.
Recheck current source-final readiness, exact publication/checkpoint binding,
runtime/configuration identity, and backup authority before recording authority.

Store an append-only, HMAC-authenticated, versioned rolling runtime attestation
in the existing cursor table. Bind the complete checkpoint digest, record/state,
input, current publication, reviewed runtime and readiness evidence, previous
attestation digest, post-commit timing and PITR target. Its distinct namespace
is explicitly admitted by rolling checkpoint readers for that observation;
candidate-only APIs still return CANDIDATE and grant no runtime verdict.

Read at most the latest two authority payloads and the existing bounded current
checkpoint closure. Reject future, foreign, malformed or unauthenticated rows.
The current authority must bind the exact current checkpoint. A new daily
authority requires its predecessor to bind the preceding immutable record;
missing authority cannot be skipped. Earlier signed authority rows remain audit
history, not a repeated whole-history replay requirement.

A crash after candidate commit preserves an unattested candidate. Retry may
attest that exact checkpoint only while its exact publication is still current
and the next open is future; it must not advance another session or rerun the
transition. Lost authority-commit acknowledgement returns the existing signed
authority. An expired candidate follows the distinct reconstruction contract in
[missed-session recovery](rolling-missed-session-recovery.md), preserving state
without claiming timely authority.

## Current verification and service routing

Current SHADOW_GO/VERIFIED reports explicitly name
ROLLING_CHECKPOINT_AND_CURRENT_INPUTS. They require authenticated runtime
authority, a matching current publication, current snapshot readiness and exact
checkpoint inputs. This is bounded current-state verification, not historical
certification or permission to submit broker orders. Structural health may
validate an old signed checkpoint before the next acquisition without claiming
current performance readiness. It must not reload expired origin prices.

The existing service classifies fresh, attested and recoverable-candidate states.
It initializes only the reviewed genesis publication. It prepares exactly the
next source-final snapshot only after authenticating existing runtime authority;
same-session polls verify without acquisition. Gaps and missed cutoffs use
[preserved-state recovery](rolling-missed-session-recovery.md) only with dated
retained inputs; missing evidence remains a named waiting dependency.
Recovery runs before acquisition. Neither a new genesis nor retrospective
performance is manufactured. Service configuration continues to reject broker
credentials and require the reviewed source/configuration/publication digests.
The production worker's outage-recovery wrapper dispatches this input contract
directly to the rolling service, including health. It cannot run legacy feed
catch-up or create legacy performance segments for a rolling book after a gap.

GO accepts the rolling startup/restart proof only with its matching rolling
input scope, exact snapshot binding and supported runtime-contract identifier.
Legacy scope validation remains separate. GO remains a first-deployment proof;
it cannot adopt failed-attempt state or reauthorize a different retained runtime.
[Rolling history and retirement](rolling-history-retention.md) now supplies
publication-bound action history and automatic cleanup after advancement and
during idle service wakes. Actual NAS qualification and paper activation remain
separate work.

## Validation

Use real PostgreSQL and synthetic source fixtures for first runtime approval,
daily continuation, current status, restart without original price history,
post-commit cutoff crossing, crash recovery, lost acknowledgements, altered
authority/checkpoint/runtime, missing predecessor, publication changes and
backup failure. Falsify each new runtime guard. Exercise the actual service
entry and host GO proof validator, preserving the existing legacy tests.
