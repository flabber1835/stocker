# Sentinel GO validation liveness and authority phase contract

**Status: implemented on PR #276, pending exact-head CI/final review, 2026-08-27.**

## Problem

The prior NAS GO path mixed stable exact-artifact certification, volatile market/data readiness, production corpus mutation, and operator activation verdicts in one serial command. Legitimate fail-closed states were therefore discovered late and an unchanged retry repeated the expensive certification work.

The correction must improve liveness without allowing uncertified code to mutate the production financial corpus, weakening Sharadar authority, or confusing local Docker image IDs with the registry RepoDigests used by broker-authorized services.

## Supported operator entry

Production operators use only:

```text
bash scripts/sentinel-go-validate.sh
```

The launcher holds one nonblocking host lock across image builds, retained-certification state, bounded financial mutation, final readiness, runtime promotion, panel recreation, and the post-validation handoff. The lock file descriptor is inherited by the child process tree so loss of the small lock-holder parent cannot release serialization while a validation still runs. The financial preparation membrane additionally requires a process-local verified-orchestration capability armed only by the supported verified entry after that kernel lock has been proven; merely acquiring the lock and invoking a lower-level module is not mutation authority.

## Required phase order

```text
A  cheap READ-ONLY prerequisites
   - compatible host Python
   - readable Linux boot identity used by retained-certification binding
   - runtime-selector / Compose configuration validity
   - stale/missing prior ordinary image is diagnostic, not authority
   - GET-only paper-account preflight for broker-capable targets
   - SHADOW target skips the paper-account preflight
   - exact ordinary-runtime READ-ONLY SEP CDC diagnostic after source-finality
   - no schema/cursor/bar/publication mutation in that diagnostic
        |
        v
B  stable exact-artifact certification
   - clean current main / freshly fetched origin/main identity
   - exact ordinary runtime image ID
   - exact authorized runtime image ID
   - exact Sentinel test-lens image ID
   - exact bt-engine / bt-data test-image IDs
   - complete required certification suites
   - certification PASS is mandatory before phase C can mutate
        |
        v
C  ONE feed-bound mutable preparation
   - only after phase B is PASS and complete
   - verified process-local orchestration capability + inherited host flock
   - clean-HEAD + exact-image feed gate
   - external-WAL durability before every write
   - schema migration
   - one bounded recovery/catch-up
   - ALREADY_CURRENT is terminal success, not a second vendor ingest
   - failure short-circuits the remaining expensive readiness probes
        |
        v
D  read-only financial readiness
   - current publication and publication chain
   - Wealth Core differential/parity
   - database/index/schema health
   - current Sharadar readiness
   - fresh actual remaining time to following execution open
   - second, final GET-only paper-account observation for broker-capable verdicts
        |
        v
E  explicit requested target verdict
   - SHADOW readiness
   - DUAL_RUN / PAPER_OBSERVATION_ONLY readiness
   - historical PAPER_EXECUTION certification remains a separate stricter verdict
        |
        v
F  local deployment finalization
   - refresh origin/main again
   - promote only the exact ordinary image ID recorded by certification
   - generic same-revision promotion is disabled
   - recreate the read-only panel through the validated-runtime Compose wrapper
   - inspect the running panel container and prove its image ID is the exact promoted ordinary image
   - record the exact local authorized/test image IDs for the next deployment boundary only after that postcondition passes
        |
        v
G  separately reviewed autonomous deployment / signed activation
   - tag and push the exact reviewed local authorized/test IDs
   - freeze registry RepoDigests with sentinel_certification_state.py
   - only those registry RepoDigests enter authorized Compose and signed authority
```

## Non-negotiable rules

1. A cheap preflight may not mutate the production financial database merely to save time. Production corpus mutation is allowed only after exact-artifact certification is PASS and complete.
2. A certification failure cannot reach schema migration, Sharadar catch-up, or any other production-corpus mutation. The preparation membrane requires both the inherited GO flock and the verified-entry process capability.
3. Mutable preparation happens once per validation attempt. An already-current coherent corpus is success; a second explicit daily ingest adds source risk without proving application semantics.
4. A preparation failure does not spend additional parity/readiness time after its verdict is already necessarily NO_GO.
5. A source-authority ambiguity does not automatically trigger a reseed. Preparation diagnostics distinguish local cursor state from ambiguous vendor/source evidence; the latter remains fail-closed.
6. The early read-only Sharadar diagnostic is deliberately narrower than the certified daily path. It can fail fast on deterministic SEP CDC cursor/source/identity/raw-close defects, but it does not claim to pre-certify every TICKERS, ACTIONS, reconciliation, failed-candidate-recovery, or publication condition that the real daily transaction must still prove.
7. Runtime deadlines are enforced by subprocess timeouts, not merely evaluated after a command eventually returns.
8. Time-sensitive readiness uses an actual wall-clock observation after the long readiness work. GO requires the reviewed minimum remaining pre-open margin, not merely `next_open > now`.
9. The GO bundle keeps the established public v1 database-health schema so the autonomous-deploy parser remains exact-key compatible. Fresh wall-clock timing is an enforced predicate and caps the bundle `valid_until`; it is not smuggled in as an incompatible new public field.
10. The paper account is read cheaply before long work for broker-capable targets and re-read at the final verdict boundary. Both observations are GET-only; the first is a liveness filter, not retained final authority.
11. Historical `PAPER_EXECUTION_GO` is distinct from the accepted `PAPER_OBSERVATION_ONLY` forward-observation path. Production defaults to `DUAL_RUN_OBSERVATION`; a historical paper verdict is never fabricated to make observation mode green.
12. `PAPER_OBSERVATION_ONLY` preserves the deliberately reviewed standing forward-trial semantics from PR #210. Its signed certificate retains a bounded nominal observation window as evidence, but nominal expiry alone does not end an otherwise unchanged paper-only trial. The narrow standing loader still requires signature/trust-root validity, durable active lifecycle, no key/certificate revocation, exact account/deployment/rollout/runtime/strategy/configuration bindings, publication lineage, and all operational gates. Explicit revocation/kill or any binding/readiness drift stops authority; historical/admin authority does not inherit this exception.
13. Runtime promotion refreshes `origin/main` immediately after validation and requires the current `sentinel-go-runtime:<HEAD>` tag to resolve to the exact ordinary image ID recorded when the certification suite passed. A same-revision retag cannot cross promotion. The older generic promotion seam is fail-closed and cannot write the pointer.
14. The runtime preflight honors the same `validated-runtime.env` pointer precedence as `sentinel-compose.sh`. Malformed pointer/Compose state fails immediately; a merely absent prior image may continue because GO can build a fresh candidate.
15. Panel recreation executes through `sentinel-compose.sh --run`; it never resolves the graph in a child shell and then loses the pointer-selected runtime in a different process. Successful Compose exit is insufficient: GO inspects the resulting panel container and requires its `.Image` to equal the exact promoted ordinary image ID.
16. GO never treats a local Docker image ID as an authorized-service RepoDigest. Post-validation records local IDs only. `sentinel_autonomous_deploy.py` is the reviewed boundary that tags/pushes those exact bytes and freezes the registry RepoDigests consumed by authorized Compose.
17. GO performs no automatic old-image deletion. An image with no currently running container may still be required for restart of an active signed deployment; cleanup must be retention/authority aware.
18. Successful GO validation and local runtime promotion do not themselves grant broker authority.

## Retained certification / retry behavior

A volatile preparation, final paper-account, or readiness failure no longer destroys already-earned stable certification evidence. On retry, the full suite may be reused only when all of the following remain true:

- exact Git commit is unchanged, clean, on current `main`, and equals refreshed `origin/main`;
- complete cached suite summary is still structurally PASS;
- every cached authorized/test/bt immutable image ID is still exactly inspectable;
- the ordinary runtime tag still resolves to its separately recorded exact immutable image ID;
- the host boot identity matches the certification boot;
- certification age is no more than 24 hours;
- cache/sidecar integrity digests and schemas are valid.

Any mismatch forces the complete certification suite again. If the host boot identity is unavailable, production GO refuses before long work instead of discovering that retained promotion state cannot be bound afterward.

The retained record is **trusted-host local state**, not a remote attestation or signed broker authority. Its integrity digest detects stale/corrupt state; it is not a defense against a malicious local administrator who can arbitrarily rewrite the repository, Docker store, and artifact directory. The supported threat model therefore requires host/filesystem administrative integrity. Broker authority remains separately signed and independently revalidated.

## Identity handoff

There are deliberately two immutable digest domains:

```text
GO / local certification:
    sha256:<local Docker image ID>

Autonomous deploy / authorized Compose:
    repository@sha256:<registry manifest digest>
```

`sentinel_autonomous_deploy.py` takes the reviewed local authorized/test image IDs, tags and pushes those exact images, captures promotion evidence, resolves immutable registry RepoDigests, and only then sets `SENTINEL_RUNTIME_IMAGE_REPOSITORY`, `SENTINEL_RUNTIME_IMAGE_DIGEST`, and `SENTINEL_TEST_IMAGE_DIGEST` for authorized services. The post-GO handoff artifact is evidence for that next boundary; it is never broker authority itself.
