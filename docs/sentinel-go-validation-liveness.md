# Sentinel GO validation liveness and authority phase contract

**Status: implemented on PR #276, pending CI/final review, 2026-08-27.**

## Problem

The prior NAS GO path mixed four different kinds of work in one serial command: stable exact-artifact certification, volatile market/data readiness, production corpus mutation, and operator activation verdicts. That composition repeatedly turned legitimate fail-closed states into long deployment dead ends.

The fix must improve liveness without allowing unvalidated code to mutate the production financial corpus or weakening Sharadar authority.

## Required phase order

```text
A  cheap READ-ONLY preflight
   - host Python
   - clean current main / origin-main identity
   - runtime-selection visibility
   - read-only broker/account observation where configured
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
   - fresh actual remaining time to following execution open
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
2. Stable certification evidence may be reused on a retry only when the Git commit is still clean/current and every cached certified immutable image ID is still exactly inspectable. Development input remains non-authoritative.
3. Mutable preparation happens once per validation attempt. An already-current coherent corpus is success; a second explicit daily ingest adds source risk without proving application semantics.
4. A source-authority ambiguity does not automatically trigger a reseed. Preparation diagnostics distinguish local cursor state from ambiguous vendor/source evidence; the latter remains fail-closed.
5. Time-sensitive readiness uses a fresh actual observation of time remaining to the following execution open after the readiness work. The theoretical source-final-to-open duration remains descriptive evidence, not an elapsed-time budget.
6. Runtime deadlines are enforced by subprocess timeouts, not merely checked after a command eventually returns.
7. Historical `PAPER_EXECUTION_GO` is distinct from the accepted `PAPER_OBSERVATION_ONLY` forward-observation path. Operator output and process exit status name the requested target; production defaults to `DUAL_RUN_OBSERVATION`.
8. Ordinary paper observation authority expires with its signed certificate. Expired certificates may not authorize PREPARE/EXECUTE/SUBMIT/CANCEL/AUTOMATION; revocation and kill remain additional independent stops.
9. GO certification and the authorized CLI use the same immutable local `sha256:<image-id>` identity domain. Post-validation writes the exact certified authorized-runtime and test-lens IDs required as `SENTINEL_RUNTIME_IMAGE_DIGEST` and `SENTINEL_TEST_IMAGE_DIGEST`; the handoff artifact is evidence, not broker authority.
10. Runtime promotion refreshes `origin/main` immediately after the long validation and refuses if upstream moved. The read-only panel is then force-recreated on the promoted ordinary runtime so it cannot silently remain on older bytes.
11. Old GO scratch tags are removed only after a successful validation and never with `--force`; Docker therefore preserves any image still referenced by a running container.

## Retry behavior

A volatile preparation/readiness failure no longer destroys already-earned stable certification evidence. On an unchanged clean/current commit, the controller may reuse the exact cached certification summary only if all certified immutable image IDs remain locally inspectable and the cached evidence digest matches. Any commit change, dirty worktree, missing/replaced image, incomplete suite, or malformed cache forces the full suite again.

This reuse is a liveness optimization only. It does not grant paper authority, bypass the feed mutation binding, or make a historical paper verdict green.
