# PR D — single Sentinel runtime + Docker layer reuse

This PR establishes one deployable Sentinel runtime image, `Dockerfile.sentinel`, and preserves content-addressed layer reuse. The image contains normal Sentinel code, broker-capable command routes and Alpaca transport, the baked execution-capability contract, and the fixed non-root runtime identity.

Broker activity still requires explicit invocation plus the existing runtime-intent, signed authority, account/environment, fencing, and financial gates. Default startup remains `status`.

`Dockerfile.sentinel-authorized` is a fail-closed tombstone with no build stage. `Dockerfile.sentinel-test` is a CI-only test lens, not a deployable runtime.

All Compose services use the same `sentinel@sha256:...` runtime. Stable base/dependency/shared/user layers remain below the exact source-SHA/application boundary, so source-only changes reuse stable blobs while the final image digest remains exact to the built commit.

The complete Sentinel, runtime-boundary, PITR, operator, Compose, Wealth Core, mutation, and adversarial suites remain mandatory.
