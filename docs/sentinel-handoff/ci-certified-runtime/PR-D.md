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
6. frozen reviewed-rule documentation/config inputs
7. Sentinel application source
8. ordinary-runtime broker-capability removal
9. final non-root `USER`

The authorized runtime continues to inherit the complete ordinary runtime and adds only its broker-capable membrane.

## Change

The fixed uid/gid and `/var/lib/sentinel` state-directory construction previously sat after `COPY sentinel/ /app/sentinel/`. Any small Sentinel source edit invalidated that stable filesystem-identity layer during rebuild/pull lineage.

This PR moves that stable layer immediately after the pinned dependency/shared-package layers. Its bytes and semantics are unchanged. A source-only application edit can retain all lower layers through uid/gid/state-directory creation and transfer only changed upper content-addressed layers.

The source revision label remains commit-specific and therefore changes the final image identity exactly as required. Docker may reuse unchanged layer blobs while the certified image digest remains unique to the exact built artifact.

## Tests

`tests/sentinel/test_docker_layering_contract.py` locks the intended ordering and proves:

- pinned base precedes dependency locks
- dependency installation precedes shared-package installation
- fixed runtime identity/state setup precedes mutable application source
- authorized runtime inherits the ordinary runtime image
- the dependency layer boundary remains above application source changes

Existing Sentinel image-layout, non-root runtime, exact-head, synthetic-merge, PITR, operator/bring-up, shell/Compose, Wealth Core boundary, mutation, and adversarial checks remain authoritative.

## Reproduction

```bash
pytest -q tests/sentinel/test_docker_layering_contract.py
pytest -q tests/sentinel/test_image_layout.py
```

A practical cache inspection can compare consecutive builds with a source-only edit. The expected property is cache reuse through the stable runtime identity layer. Certification still trusts only the resulting immutable digest.
