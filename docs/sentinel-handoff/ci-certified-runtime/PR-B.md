# PR B — read-only verifier for the one CI-certified Sentinel runtime

The verifier resolves certification evidence for the exact current Git SHA and validates one deployable runtime subject: `ghcr.io/flabber1835/stocker/sentinel@sha256:...`.

It performs GET-only GitHub reads and has no Docker mutation, promotion, database, Sharadar, Alpaca, broker, or financial authority.

It verifies the exact successful protected-publication run, retained artifact SHA-256, exact bundle member/checksum set, canonical certification manifest hash/schema, source commit/tree, broker-capable single-runtime identity, dependency/test hashes, software counts, evidence status, runtime/semantic epochs, provenance binding, SLSA DSSE subject, originating safety run, and required exact-head CI jobs. Git identity is re-read at the end to close a verification-time HEAD race.

Artifact redirects remove GitHub authorization when the destination origin changes.

Stable refusal codes identify missing publication/evidence, tampering, source/runtime mismatch, unsupported schemas/epochs, failed jobs/tests, provenance/attestation mismatch, GitHub unavailability, and current-HEAD races.
