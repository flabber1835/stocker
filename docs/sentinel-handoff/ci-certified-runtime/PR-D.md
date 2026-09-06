# PR D — single Sentinel runtime + Docker layer reuse

## Scope

This PR establishes one deployable Sentinel runtime image and preserves content-addressed Docker layer reuse. It changes no strategy economics, Wealth Core logic, Sentinel financial/risk thresholds, order semantics, dependency versions, or live financial gates.

## Runtime contract

There is one production Sentinel image: `Dockerfile.sentinel`. It contains normal Sentinel runtime code, broker-capable command routes and Alpaca transport, the baked execution-capability marker/program used by existing authority checks, and the fixed non-root runtime identity.

Broker activity still requires explicit command invocation plus the existing runtime-intent, signed authority, account/environment, fencing, and financial gates. Container start/restart defaults to `status` and cannot trade by itself.

`Dockerfile.sentinel-authorized` is retained only as a fail-closed tombstone with no build stage so stale automation cannot silently create a second runtime. It is not a runtime image definition. `Dockerfile.sentinel-test` is a CI-only test lens layered on the one production image; it is not deployable.

## Layer contract

The production image keeps stable base/dependency/shared/user layers below the exact source-SHA identity and application-source boundary. The exact SHA still changes the final immutable image identity while source-only changes reuse stable lower layers.

## Deployment contract

All Compose services, including automation and the explicit `authorized-cli` profile, resolve the same `sentinel@sha256:...` runtime. `authorized-cli` is an execution-authority profile, not an image class. Protected publication exports and publishes one runtime digest under the Sentinel repository.

## Tests

The Docker-layer contract proves stable layers precede the exact-SHA/application boundary, source identity remains baked exactly once, broker code is present, the execution-capability contract is present, default runtime command remains `status`, and no stable layer depends on `SOURCE_GIT_SHA`. The complete Sentinel, runtime-boundary, PITR, operator, Compose, Wealth Core, mutation, and adversarial suites remain mandatory.
