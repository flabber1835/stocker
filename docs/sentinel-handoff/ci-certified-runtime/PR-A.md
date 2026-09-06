# PR A — reusable CI certification for one Sentinel runtime

## Contract

A successful exact-main `Sentinel safety` run certifies exactly one deployable Sentinel runtime: `ghcr.io/flabber1835/stocker/sentinel@sha256:...`.

That runtime is broker-capable by construction. The certificate does not create a read-only/authorized image distinction.

## Certification evidence

After the complete software suite passes, CI records:

- exact Git commit and tree
- exact local runtime image ID and source-revision label
- runtime capability-marker hash
- dependency-lock hashes
- tracked-test-manifest hash
- exact pass/non-pass counts for Sentinel, operator/scripts, and prospective Wealth Core suites
- adversarial and mutation evidence hashes
- safety workflow run/attempt
- runtime and semantic epochs

Protected publication independently re-observes the source/tree/image/dependency/test bindings, checks the required exact-head jobs, computes the immutable registry digest, and produces `certification.json` with a canonical `manifest_sha256`.

The exact runtime digest receives GitHub Sigstore/SLSA provenance. The certification manifest, provenance, Sigstore bundle, and checksums are retained as a GitHub Actions artifact and attached as an OCI referrer of that exact runtime digest in GHCR.

## Fail-closed properties

Certification refuses missing/unknown schemas, wrong source identity, changed local runtime ID, wrong registry subject, non-pass software counts, missing or failed required jobs, dependency/test-manifest drift, malformed digests, evidence drift, manifest tampering, or a runtime certificate that does not explicitly identify the subject as broker-capable.

No NAS GO consumption changes are included here. Live financial/data/account gates remain outside this software certificate and will be wired separately.
