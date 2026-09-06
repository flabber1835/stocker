# PR A — CI-certified immutable Sentinel runtime publication

## Scope

This change extends the existing protected `Sentinel safety` → `Sentinel protected publication` chain. It does not change NAS GO consumption, strategy economics, financial gates, broker behavior, promotion authority, or runtime selection.

## Certification chain

1. `Sentinel safety` checks out and tests one exact SHA.
2. The existing pinned ordinary, authorized, and test images are built with that exact SHA.
3. Existing non-root, PITR, complete Sentinel, operator/bring-up, automation coverage, prospective Wealth Core, shell/Compose, adversarial, and mutation checks remain mandatory.
4. After all software checks pass, CI assembles `software-certification-input.json` containing:
   - exact commit and Git tree
   - exact local authorized image ID
   - authorized-runtime capability-marker hash
   - individual dependency-lock hashes
   - tracked test-manifest hash
   - exact three-suite pytest counts
   - adversarial-evidence hash/status
   - mutation-evidence hash/status
   - runtime/semantic epochs
   - safety workflow run/attempt
5. The assembler runs on PR exact-head and synthetic-merge jobs as an integration check. Only an exact `main` push exports the tested OCI image plus certification input for publication.
6. The protected publication workflow downloads the exact tested-image artifact and verifies its checksum manifest.
7. Before issuing a certificate, publication independently re-observes and requires equality for:
   - trigger SHA vs certification-input source SHA
   - trigger safety run ID/attempt vs certification-input run ID/attempt
   - exact publication checkout SHA/tree vs certification-input source SHA/tree
   - loaded authorized image ID vs tested image ID
   - loaded image source-revision label vs trigger SHA
   - current authorized-runtime capability marker vs recorded hash
   - current dependency locks vs recorded lock hashes
   - current tracked test manifest vs recorded test-manifest hash
8. Publication queries the originating safety run and requires both `host-python-38-exact-head` and `sentinel-exact-head` to have conclusion `success`.
9. It computes the final OCI registry digest through the existing pinned loopback-registry publication path.
10. `certification.json` binds the source, tree, dependency locks, tests, required job conclusions, evidence hashes, workflow IDs, epochs, timestamp, exact GHCR digest, and immutable `name@digest` reference.
11. The certification manifest carries `manifest_sha256`, computed over canonical JSON excluding only that field. Verification fails on any content change.
12. Existing Sigstore SLSA provenance remains required and is bound to the same image digest.
13. The image is copied to GHCR and re-resolved to prove the destination digest is unchanged.
14. The complete certification/provenance/checksum bundle is attached to `ghcr.io/flabber1835/stocker/sentinel-authorized@sha256:…` as an OCI referrer with artifact type `application/vnd.stocker.sentinel.software-certification.v1`.
15. Publication fails if that exact certification referrer cannot be rediscovered from the exact runtime digest.

The commit tag remains a human-readable locator. The certification manifest records and binds the immutable digest. Future NAS verification will consume the digest-bound evidence in PR B/C.

## Fail-closed properties added here

- missing software-certification input refuses publication
- input checksum mismatch refuses publication
- malformed/unknown input schema refuses publication
- trigger/source SHA mismatch refuses publication
- source-tree mismatch refuses publication
- safety workflow run/attempt mismatch refuses publication
- loaded image ID/revision mismatch refuses publication
- capability-marker mismatch refuses publication
- dependency-lock mismatch refuses publication
- tracked test-manifest mismatch refuses publication
- any skipped/failed/error/xfailed/xpassed software result refuses certification input
- missing required CI job refuses certification
- unsuccessful required CI job refuses certification
- malformed registry digest refuses certification
- certification-manifest tampering fails `manifest_sha256`
- authorized-runtime digest and Docker image digest must agree
- immutable image reference must agree with subject name and digest
- OCI certification attachment must be discoverable from the immutable runtime digest

## Reproduction

Run the unit contracts locally in the project test environment:

```bash
pytest -q tests/scripts/test_sentinel_ci_certification_manifest.py
pytest -q tests/scripts/test_sentinel_ci_certification_input_binding.py
```

Run the same complete safety workflow surfaces used by branch protection through the PR. The required merge checks remain:

- `sentinel-exact-head`
- `sentinel-synthetic-merge`
- `host-python-38-exact-head`
- `host-python-38-synthetic-merge`

After this PR is merged, a successful exact-main safety run triggers protected publication. Its job summary records the immutable runtime digest and immutable certification-referrer digest. The Actions provenance artifact remains a secondary retained copy; GHCR carries the durable digest-bound certification referrer.

## Deliberately unchanged

- `scripts/sentinel-go-validate.sh`
- NAS GO behavior
- local certification behavior
- financial/live-state gates
- promotion scripts and selector
- Dockerfiles
- strategy and Wealth Core economics
- broker execution behavior
