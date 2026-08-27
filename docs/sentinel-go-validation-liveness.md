# Sentinel GO validation liveness and authority phase contract

**Status: deep-review decision record, 2026-08-27.**

## Problem

The current NAS GO path mixes four different kinds of work in one serial command: stable exact-artifact certification, volatile market/data readiness, production corpus mutation, and operator activation verdicts. That composition has repeatedly turned legitimate fail-closed states into long deployment dead ends.

The fix must improve liveness without allowing unvalidated code to mutate the production financial corpus or weakening Sharadar authority.

## Required phase order

```text
A  cheap READ-ONLY preflight
   - host Python
   - clean current main / origin-main identity
   - runtime-selection visibility
   - backup/config presence and read-only durability status
   - read-only database/publication/cursor sanity
   - read-only source-authority diagnostics where available
   - read-only Alpaca PAPER account check
   - current market/session timing
        |
        v
B  stable exact-artifact certification
   - exact ordinary runtime
   - exact authorized runtime
   - exact test lens
   - full certification suites
   - retain exact immutable evidence keyed to commit + image/source identities
        |
        v
C  ONE mutable preparation
   - only an already-certified exact image
   - external-WAL durability before every write
   - schema migration
   - one bounded recovery/catch-up
   - ALREADY_CURRENT is terminal success, not a reason for a second daily ingest
        |
        v
D  read-only financial readiness
   - current publication and chain
   - Wealth Core differential/parity
   - database/index/schema health
   - current source readiness
   - actual remaining time to following execution open
        |
        v
E  explicit target verdict
   - SHADOW readiness
   - DUAL-RUN / PAPER_OBSERVATION_ONLY readiness
   - historical PAPER_EXECUTION certification reported separately
        |
        v
F  separately signed paper-observation activation
```

## Non-negotiable rules

1. A cheap preflight may not mutate the production financial database merely to save time. Production corpus mutation is allowed only after the exact artifact has passed its required certification boundary.
2. Stable certification evidence may be reused on a retry only when every bound identity is exactly unchanged. A hand-authored PASS is never authority.
3. Mutable preparation happens once per validation attempt. An already-current coherent corpus is success; a second explicit daily ingest adds source risk without proving application semantics.
4. A source-authority ambiguity does not automatically trigger a reseed. Recovery must distinguish local recoverable/corrupt state from ambiguous vendor evidence.
5. Time-sensitive readiness uses the actual observation time and actual interval remaining to the following execution open. A theoretical source-final-to-open duration is not an elapsed-time budget.
6. Runtime deadlines must be enforced by the process, not merely checked after a command eventually returns.
7. Historical `PAPER_EXECUTION_GO` is distinct from the accepted `PAPER_OBSERVATION_ONLY` forward-observation authority. Operator output and process exit status must name the requested target.
8. Broker-authority lifetime must match the paper-observation contract. Expiry semantics may not be silently bypassed by a standing-authority path.
9. Local GO image IDs and the registry-qualified authorized/test RepoDigests consumed by signed activation are distinct identities and require an explicit, documented handoff.
10. Runtime promotion after a long validation must refresh `origin/main` again or explicitly state that it promotes the exact validated commit rather than claiming current upstream main.

## Consequences for the current implementation

The first implementation in PR #276 is **not merge-ready**. It performs mutable Sharadar preparation before the stable certification boundary and the existing core validator performs preparation again later. That saves time at the cost of the wrong authority ordering and does not eliminate the late-failure class.

Issue #275 tracks the complete remediation set. The accepted implementation must conform to the phase model above.
