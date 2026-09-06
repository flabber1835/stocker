# PR B — read-only CI certification evidence verifier

## Scope

This PR adds a host-side verifier for reusable software-certification evidence. It has GET-only GitHub access and no runtime-promotion, database, broker, data-preparation, or financial mutation authority.

## Authority chain

For the exact current Git commit, the verifier:

1. records current `HEAD` and `HEAD^{tree}`
2. locates a successful protected-publication workflow run for that exact SHA
3. requires the exact publication workflow ID/path, `main`, `workflow_run`, completed/success
4. locates the exact non-expired `sentinel-provenance-<sha>` artifact from that run
5. verifies the GitHub artifact SHA-256 against the downloaded archive
6. requires the exact certification bundle member set
7. verifies `SHA256SUMS`
8. validates certification schema `sentinel.software-certification/1`
9. validates `manifest_sha256`
10. requires source repository, commit, and Git tree to equal the current checkout
11. requires an immutable `sha256:` runtime digest, matching authorized-runtime digest, and matching `name@digest` reference
12. requires the recorded software test counts to contain three completed suites and zero non-pass outcomes
13. requires both exact-head CI job conclusions to be `success`
14. validates provenance schema/bindings against the same source, publication run, safety run, certification file hash, and runtime digest
15. validates the retained SLSA DSSE payload names the same exact runtime digest
16. re-fetches the originating Sentinel safety run and verifies exact workflow ID/path, exact source SHA, `main`, `push`, completed/success, and exact run attempt
17. re-fetches safety jobs and requires `host-python-38-exact-head` and `sentinel-exact-head` to exist exactly once and succeed
18. re-reads `HEAD` and `HEAD^{tree}` and refuses if either changed during verification

The GitHub Actions artifact is the verifier's publication authority. The durable GHCR referrer created by PR A remains retained alongside the image. Normal GO consumption is introduced separately in PR C.

## Stable refusal codes

Examples include:

- `CERT_NO_PUBLICATION`
- `CERT_ARTIFACT_MISSING`
- `CERT_ARTIFACT_DIGEST_MISMATCH`
- `CERT_MANIFEST_SCHEMA_UNKNOWN`
- `CERT_MANIFEST_TAMPERED`
- `CERT_SOURCE_SHA_MISMATCH`
- `CERT_SOURCE_TREE_MISMATCH`
- `CERT_IMAGE_DIGEST_MISSING`
- `CERT_AUTHORIZED_RUNTIME_MISMATCH`
- `CERT_REQUIRED_JOB_MISSING`
- `CERT_REQUIRED_JOB_FAILED`
- `CERT_PROVENANCE_BINDING_INVALID`
- `CERT_ATTESTATION_BINDING_INVALID`
- `CERT_CURRENT_HEAD_CHANGED`

CLI errors expose the stable code plus a SHA-256 of the detail string.

## Network and credentials

The verifier uses only Python standard-library HTTPS GET requests to GitHub. Public repository reads can run anonymously. `SENTINEL_GITHUB_READ_TOKEN` or `GITHUB_TOKEN` is used when supplied for rate-limit/repository access. No token is written to output or evidence.

## Reproduction

```bash
python scripts/sentinel_ci_certification_verify.py
```

Optional machine-readable output for a later GO consumer:

```bash
python scripts/sentinel_ci_certification_verify.py \
  --output /tmp/sentinel-software-certification.json
```

Unit contract:

```bash
pytest -q tests/scripts/test_sentinel_ci_certification_verify.py
```

The normal Sentinel exact-head and synthetic-merge workflows remain the required CI authority for this PR.
