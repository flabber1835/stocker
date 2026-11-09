# Reuse exact immutable image resolution within one invocation

The retained install trace measured 49 image inspections taking 14.903 seconds
across the original build/prepare/advance/resume invocations. Several came from
`BackedHost.load_values`, which repeatedly resolved the same immutable runtime
reference. This is a fixed image fact, separate from current application health,
financial state, or configuration.

Within a single BackedHost instance, memoize only the image ID resolved from an
exact immutable `sha256:<64 lowercase hex>` or `<repository>@sha256:<64 lowercase
hex>` reference. A first resolution must return the exact bare image ID, or list
the exact selected RepoDigest, and its resulting image ID must match both freshly
configured runtime and test image IDs. Failed resolutions are never cached.

Every call still rereads and validates the literal environment before consulting
the map and rechecks its current runtime/test IDs afterwards. Tags, mutable source
files, configuration, health, running containers, financial proofs and readiness
never enter this cache. Old/new references have distinct entries. A new Host in
another command or resume invocation resolves independently; there is no global,
persisted or cross-invocation cache. Image/container presence at mutation boundaries
continues to be checked by the existing host operations.

Tests must falsify absent immutable-reference checking, reuse across different
references, stale configuration reuse, a foreign Docker resolution, and accidental
cross-instance reuse. They must show that repeated exact immutable resolution
launches one inspection while fresh non-image environment values remain visible.

Prepare currently performs two full source validations. The first authenticates
the source before Host dynamically imports `scripts/sentinel_env.py`; the last
validates candidate source after intervening image/configuration probes. A safe
consolidation would require changing that bootstrap ordering or a separately
qualified immutable staged-source contract. This patch leaves those mutable-source
checks intact and does not cache the filesystem or readiness results.
