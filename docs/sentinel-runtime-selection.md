# Sentinel validated runtime selection

**Status: design decision, 2026-08-26.**

## Problem

`sentinel-go-validate.sh` builds and validates commit-scoped candidate images, but ordinary Sentinel Compose commands may still resolve `sentinel:latest` or a stale `SENTINEL_RUNTIME_IMAGE_REF`. That permits validation and later runtime selection to diverge. The feed mutation gate correctly refuses the stale image, but only when the later mutation is attempted.

This is a liveness and deployment-identity defect: successful financial validation must leave the ordinary runtime selector bound to the exact ordinary image built from the validated clean `main` commit, while broker-capable authorized and test images remain separate artifacts.

## Decision

1. **Early preflight before expensive validation.** `sentinel-go-validate.sh` inspects the currently selected ordinary runtime before the certification build/test phase. It reports whether that image's baked `org.opencontainers.image.revision` equals clean repository `HEAD`. A stale or absent prior runtime is reported immediately, not after the long validation run. It does not weaken or bypass any later gate.

2. **Separate ordinary runtime promotion.** The candidate ordinary image remains `sentinel-go-runtime:<full-commit>`. The authorized runtime and test image remain distinct and are never promoted into the ordinary runtime slot.

3. **Promote only after successful production validation.** When production GO validation exits successfully, the launcher resolves the exact immutable image ID of `sentinel-go-runtime:<validated-commit>`, verifies its baked revision equals the still-clean `main` HEAD and `origin/main`, and atomically writes a non-secret deployment pointer:

   `artifacts/sentinel/deployment/validated-runtime.env`

   containing exactly:

   `SENTINEL_RUNTIME_IMAGE_REF=sha256:<ordinary-runtime-image-id>`

   Development-input validation never promotes a runtime.

4. **The supported Compose wrapper consumes that pointer.** `scripts/sentinel-compose.sh` loads the validated runtime pointer before Compose resolution. A stale shell or `.env` value cannot silently override the validated pointer. An explicit `SENTINEL_RUNTIME_IMAGE_REF` is therefore treated as development/validation-only unless the validated pointer is absent.

5. **Safety remains redundant.** The existing `sentinel_feed_gate.py` continues to bind every feed mutation to clean HEAD and the selected image's baked revision. The pointer is selection state, not authorization. Editing or corrupting it cannot authorize a stale image to mutate the corpus.

6. **No implicit broker activation.** Runtime promotion changes only the ordinary Sentinel runtime selector. It does not issue certificates, select the authorized broker membrane, enable automation, release the kill switch, migrate an account, or submit broker orders.

## Operational consequence

A normal post-merge NAS flow becomes:

```text
update clean main
        |
        v
sentinel-go-validate.sh
        |
        +-- immediate runtime-selection preflight
        |
        +-- build/test exact commit-scoped candidates
        |
        +-- financial validation
        |
        +-- on success only: atomically promote exact ordinary runtime digest
        |
        v
subsequent sentinel-compose.sh commands resolve that validated ordinary digest
```

The intended invariant is:

```text
successful production GO validation
    => ordinary operational runtime selector == validated ordinary candidate
    => selected image revision == clean current main
```
