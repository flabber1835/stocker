# PR A — CI-certified immutable Sentinel runtime publication

## Scope

This change extends the existing protected `Sentinel safety` → `Sentinel protected publication` chain. NAS GO consumption, strategy economics, financial gates, broker behavior, promotion authority, and runtime selection remain unchanged in this PR.

## Certification boundary

Sentinel has two production image identities and the certificate preserves that separation:

- ordinary runtime: `ghcr.io/flabber1835/stocker/sentinel@sha256:...`
- broker-capable authorized runtime: `ghcr.io/flabber1835/stocker/sentinel-authorized@sha256:...`

The two local image IDs and the two final registry manifest digests must all remain distinct where the contract requires distinct roles. Normal live/read-only execution can therefore continue using the ordinary image while broker-capable execution stays behind the authorized membrane.

## Certification chain

1. `Sentinel safety` checks out and tests one exact SHA.
2. The pinned ordinary, authorized, and test images are built with that exact SHA.
3. Existing non-root, PITR, complete Sentinel, operator/bring-up, automation coverage, prospective Wealth Core, shell/Compose, adversarial, and mutation checks remain mandatory.
4. CI assembles `software-certification-input.json` containing exact commit/tree, both tested runtime image IDs, the authorized capability-marker hash, dependency-lock hashes, tracked-test-manifest hash, exact three-suite counts, adversarial/mutation evidence hashes/status, epochs, and safety workflow run/attempt.
5. The assembler executes on PR exact-head and synthetic-merge CI. Exact `main` additionally exports both tested OCI images, the certification input, commit marker, and checksum manifest.
6. Protected publication checksum-verifies and loads both tested images.
7. Publication independently re-observes the trigger SHA, safety run/attempt, checkout SHA/tree, both loaded image IDs/revision labels, authorized capability marker, dependency locks, and tracked test manifest.
8. Publication re-queries the originating safety run and requires `host-python-38-exact-head` and `sentinel-exact-head` to have conclusion `success`.
9. A pinned loopback registry computes the OCI manifest digest for each tested image before external publication.
10. `certification.json` binds source/tree, dependencies, test/evidence hashes, workflow IDs, epochs, timestamp, ordinary image subject/digest/local ID, and authorized image subject/digest/local ID/capability hash.
11. `manifest_sha256` covers canonical JSON excluding only the hash field.
12. GitHub generates separate Sigstore SLSA provenance attestations for the ordinary and authorized image digests.
13. The retained provenance bundle binds both runtime digests and both attestations to the same certificate and workflow lineage.
14. ORAS copies both exact manifests to GHCR and verifies each destination resolves to the precomputed digest.
15. The same certificate/provenance/checksum bundle is attached as a discoverable OCI referrer to both immutable runtime digests.

Commit tags remain human-readable locators. Immutable `name@sha256:digest` references are the certification identities.

## Fail-closed properties

Publication refuses on missing/malformed evidence, checksum failure, wrong trigger/source/tree, wrong safety run/attempt, either loaded runtime ID/revision mismatch, capability/lock/test-manifest mismatch, a non-pass required test, a missing/failed required CI job, malformed or duplicate runtime identity, destination digest drift, certificate hash failure, malformed attestation subject, or an undiscoverable certification referrer.

## Reproduction

```bash
pytest -q tests/scripts/test_sentinel_ci_certification_manifest.py
pytest -q tests/scripts/test_sentinel_ci_certification_input_binding.py
```

The required merge checks remain:

- `sentinel-exact-head`
- `sentinel-synthetic-merge`
- `host-python-38-exact-head`
- `host-python-38-synthetic-merge`

After merge, a successful exact-main safety run exercises the protected dual-runtime publication path and records both immutable runtime digests plus both immutable certification-referrer digests.

## Unchanged boundaries

- `scripts/sentinel-go-validate.sh`
- NAS GO behavior
- local certification behavior
- financial/live-state gates
- promotion scripts and selector
- Dockerfiles
- strategy and Wealth Core economics
- broker execution behavior
