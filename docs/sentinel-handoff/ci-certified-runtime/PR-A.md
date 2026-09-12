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

### Expected-failure evidence (PR #360)

Version 2 of the software-certification input and manifest carries the existing
three-node Wealth Core golden-hash quarantine through publication and NAS
verification. Assembly re-runs the permanent owner verifier against the exact
Wealth Core JUnit file, proving complete collection and the settled physical
outcomes. The certificate preserves the actual `passed` and `xfailed` counts,
the three exact node IDs, and the JUnit SHA-256. Each suite and the total must
agree with this evidence. Ordinary failures, skips, unexpected passes,
deselection, missing quarantine nodes, and additional expected failures refuse
certification. The settled inventory is checked at assembly and consumption.

Version 1 certificates retain their all-pass contract. Version 2 certificates
use the v2 OCI artifact media type. The NAS verifier supports both versions;
an unknown version or a version/schema mismatch refuses. This evidence change
preserves the current golden fixtures and strategy economics.

The exact runtime digest receives GitHub Sigstore/SLSA provenance. The certification manifest, provenance, Sigstore bundle, and checksums are retained as a GitHub Actions artifact and attached as an OCI referrer of that exact runtime digest in GHCR.

## Fail-closed properties

Certification refuses missing/unknown schemas, wrong source identity, changed local runtime ID, wrong registry subject, non-pass software counts, missing or failed required jobs, dependency/test-manifest drift, malformed digests, evidence drift, manifest tampering, or a runtime certificate that does not explicitly identify the subject as broker-capable.

No NAS GO consumption changes are included here. Live financial/data/account gates remain outside this software certificate and will be wired separately.
