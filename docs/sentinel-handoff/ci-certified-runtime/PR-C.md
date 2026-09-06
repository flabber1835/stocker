# PR C — Consume the one CI-certified Sentinel runtime in normal GO

## Objective

Normal production GO reuses the exact immutable Sentinel runtime already certified and published by GitHub CI for the current clean `main` commit. It does not rebuild the deployable runtime or rerun the full deterministic software suite on the NAS.

There is exactly one deployable Sentinel image. It contains broker-capable code. A CI-only test lens exists only for software certification and for the explicit local-full fallback mode; normal GO never deploys or requires that lens.

## Default production flow

1. Preserve the existing host compatibility, lifecycle lock, deployment-secret, host-identity, runtime-selection and GET-only paper-account preflights.
2. Verify the exact current-SHA software certificate through `sentinel_ci_certification_verify.py`.
3. Reuse the exact `ghcr.io/flabber1835/stocker/sentinel@sha256:...` image if already cached, or pull that exact immutable reference if absent.
4. Require Docker `RepoDigests`, local image ID and OCI source-revision label to bind the local bytes to the certified registry digest and current commit.
5. Run a small offline identity/parity-presence probe from the same runtime image.
6. Use the CI certificate as the software-certification result for the existing phased GO controller.
7. Continue all current mutable preparation and live/current database, backup/WAL, Sharadar, parity, account/Alpaca, timing/deadline, shadow and requested-target gates.
8. After the requested financial target passes, re-verify the CI certificate and local digest binding.
9. Atomically select the exact certified GHCR digest reference as the validated runtime.
10. Recreate the panel from that same one runtime and retain an evidence-only handoff.

## Explicit local-full mode

`--local-full-certification` keeps a full local certification path available. It builds one deployable Sentinel runtime and one CI-only test lens, runs the three required software suites locally, then uses the same live GO gates. It never builds the retired second runtime image.

## Fail-closed properties

Normal GO refuses on missing or wrong certification evidence, source SHA/tree mismatch, unsupported schema, failed required CI jobs, manifest/provenance/attestation tampering, missing immutable digest, wrong local `RepoDigest`, source-revision mismatch, image-pull failure, incompatible runtime identity, GO-invocation/host-boot binding mismatch, current-HEAD race, or promotion-time certificate drift.

No automatic fallback from failed CI certification to local-full certification exists. Local-full requires the explicit command-line flag.

## Scope guard

This PR does not change strategy economics, Wealth Core economics, Sentinel financial/risk thresholds, order semantics, broker endpoint policy, account policy, Sharadar/data authority, backup authority, or the meaning of GO/NO_GO.

The software-certification source changes. The live certification gates remain current and mandatory on every GO invocation.

No merge is requested or performed by this PR.
