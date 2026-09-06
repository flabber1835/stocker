# PR D — Sentinel Docker layer reuse optimization

## Scope

This PR improves content-addressed Docker layer reuse for the Sentinel runtime. It changes no strategy economics, Wealth Core logic, Sentinel financial/risk thresholds, broker behavior, dependency versions, runtime permissions, or image immutability semantics.

## Layer contract

The ordinary Sentinel image keeps this order:

1. pinned `python:3.12-slim@sha256:...` base
2. stable TLS configuration
3. pinned dependency lock copy/install
4. shared-package copy/install
5. fixed Sentinel uid/gid and persistent state-directory setup
6. exact `SOURCE_GIT_SHA` label/environment identity boundary
7. frozen reviewed-rule documentation/config inputs
8. Sentinel application source
9. ordinary-runtime broker-capability removal
10. final non-root `USER`

The authorized runtime continues to inherit the complete ordinary runtime and adds only its broker-capable membrane.

## Changes

Two early cache invalidators were corrected.

The fixed uid/gid and `/var/lib/sentinel` state-directory construction previously sat after `COPY sentinel/ /app/sentinel/`. Any small Sentinel source edit invalidated that stable filesystem-identity layer. It now sits immediately after the pinned dependency/shared-package layers.

`SOURCE_GIT_SHA` was also consumed near the top of the Dockerfile by the OCI source label and `SENTINEL_IMAGE_SOURCE_REVISION`. A new commit therefore entered Docker's build state before dependency and shared-package construction. The exact-SHA identity boundary now sits after every stable base/dependency/shared/uid layer and immediately before reviewed configuration/application source.

The final image still contains the same exact source-revision label and in-process source-revision environment value. Existing runtime identity checks continue to compare those values to the approved Git commit. The change only moves where that commit-specific build state begins.

For a source-only application edit, Docker can reuse the pinned base, TLS, dependency, shared-package, fixed uid/gid, and state-directory layers. The resulting final image remains commit-specific and is certified/deployed only by its immutable digest.

## Tests

`tests/sentinel/test_docker_layering_contract.py` locks the intended ordering and proves:

- pinned base precedes dependency locks
- dependency installation precedes shared-package installation
- fixed runtime identity/state setup precedes the commit-specific source boundary
- the exact SHA label and in-process identity remain present exactly once
- the commit-specific identity boundary precedes mutable application source
- no `SOURCE_GIT_SHA` dependency contaminates the stable dependency/shared/uid section
- authorized runtime inherits the ordinary runtime image

Existing Sentinel image-layout, non-root runtime, exact-head, synthetic-merge, PITR, operator/bring-up, shell/Compose, Wealth Core boundary, mutation, and adversarial checks remain authoritative.

## Reproduction

```bash
pytest -q tests/sentinel/test_docker_layering_contract.py
pytest -q tests/sentinel/test_image_layout.py
```

A practical cache inspection can compare consecutive builds with a source-only edit. The expected property is cache reuse through the fixed uid/gid and state-directory layer, with cache invalidation beginning at the exact-SHA identity boundary. Certification still trusts only the resulting immutable digest.
